"""Finding out where to send a message.

Every citizen-facing message this service sends is addressed to a household, and a
household is a UUID until somebody resolves it. `admin.household` lives behind core-api and
holds the keyed hash a gateway needs, so this is the seam.

**It resolves to a hash, never a number.** `recipient_ref_hash` is an HMAC of the contact
number. The gateway turns it into a real address at the edge; nothing in this service ever
holds a phone number, which is what makes an alerting-svc database dump uninteresting.

**A household with no contact is a real answer, not an error.** Not everybody has a phone.
`None` means "cannot be messaged", and the caller records that as a delivery gap — the same
`NO_CHANNEL` state the fan-out already has — rather than treating it as a failure to retry.

**core-api being down is different again**, and raises. A household that cannot be resolved
right now must not be recorded as one that cannot be reached, because those two produce
completely different numbers on a coverage map and only one of them means somebody should
be sent in a vehicle.

The credential is a client-credentials grant (`sarana_shared.auth.ServiceCredentials`),
scoped to `household:contact_read` and nothing else. It was the only credential in the
platform holding that scope until file 14, when the warning agent needed to target
households itself; agent-svc holds it too now. Two is worth keeping small and worth
saying out loud, because this scope is the difference between a service whose database
dump is uninteresting and one whose dump is a list of everybody's phone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Protocol
from uuid import UUID

import httpx
import structlog

from sarana_shared.auth.service_credentials import CredentialUnavailable, ServiceCredentials
from sarana_shared.errors import UpstreamUnavailable

_log = structlog.get_logger(__name__)

CONNECT_TIMEOUT: Final = 2.0
READ_TIMEOUT: Final = 5.0

# How many resolutions to remember. A household's contact hash changes when somebody
# updates their number, which is rare; re-asking core-api for it on every message during a
# national fan-out is a self-inflicted load spike on the service everything depends on.
CACHE_SIZE: Final = 50_000

# One page of a bulk read, and how many pages a single area may take. The ceiling
# exists so a caller that names half the country gets a refusal rather than a fan-out
# that silently covered the first fifty thousand households and stopped.
PAGE_SIZE: Final = 2_000
MAX_PAGES: Final = 200


class DirectoryUnavailable(UpstreamUnavailable):
    """The household directory could not be reached.

    Distinct from "this household has no contact number" on purpose. One is a fact about a
    person and belongs in the delivery record; the other is a fact about the platform and
    belongs in an alert.
    """

    slug = "household-directory-unavailable"
    title = "Household directory unavailable"


@dataclass(frozen=True, slots=True)
class HouseholdContact:
    """Where to send one household's message, and in which language."""

    household_id: str
    recipient_ref_hash: str | None
    preferred_language: str
    gn_division_code: str

    @property
    def reachable(self) -> bool:
        """Whether this household can be messaged at all.

        The question to branch on. A household with no number is not a failure and not a
        retry; it is somebody who has to be reached another way, and the delivery record
        should say so.
        """
        return bool(self.recipient_ref_hash)


class HouseholdDirectory(Protocol):
    """Resolving a household to a messaging address."""

    async def contact(self, household_id: UUID | str) -> HouseholdContact | None:
        """Where to reach one household, or None if there is no such household.

        Raises:
            DirectoryUnavailable: if the directory could not be reached. Never returns
                None for an outage — that would silently turn "we could not ask" into
                "this person does not exist".
        """
        ...

    async def contacts_for(self, gn_division_codes: list[str]) -> list[HouseholdContact]:
        """Every messaging address in these divisions, for an alert fan-out.

        Households with no contact number are included with `recipient_ref_hash` None.
        They are the delivery gap, and dropping them here would report a division as fully
        covered when part of it cannot be reached at all.

        Raises:
            DirectoryUnavailable: if the directory could not be reached. Never a partial
                list - a fan-out over half a district, silently, is worse than one that
                refused.
        """
        ...

    async def aclose(self) -> None: ...


class CoreApiDirectory:
    """The real directory: core-api, behind a client-credentials grant."""

    def __init__(
        self,
        base_url: str,
        *,
        credentials: ServiceCredentials,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._credentials = credentials
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        )
        self._cache: dict[str, HouseholdContact | None] = {}

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
        await self._credentials.aclose()

    async def contact(self, household_id: UUID | str) -> HouseholdContact | None:
        key = str(household_id)
        if key in self._cache:
            return self._cache[key]

        try:
            headers = await self._credentials.authorization()
        except CredentialUnavailable as error:
            raise DirectoryUnavailable(
                "No service credential is available to read household contacts."
            ) from error

        try:
            response = await self._client.get(
                f"{self._base_url}/api/v1/admin/households/{key}/contact", headers=headers
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            _log.warning(
                "household_directory_unreachable",
                household_id=key,
                error=type(error).__name__,
            )
            raise DirectoryUnavailable("core-api is unreachable.") from error

        if response.status_code == 401:
            # The credential was rotated or revoked under us. Drop the cached token so the
            # next attempt fetches a fresh one rather than re-presenting a refused token
            # forever, and raise rather than treating it as "no such household".
            self._credentials.invalidate()
            _log.error(
                "household_directory_unauthorised",
                household_id=key,
                hint="the alerting-svc credential was rotated, revoked, or lacks "
                "household:contact_read",
            )
            raise DirectoryUnavailable("core-api refused this service's credential.")
        if response.status_code == 404:
            # A real answer: no such household, or one outside this service's area. Cached,
            # because it is a fact rather than an outage.
            self._remember(key, None)
            return None
        if response.status_code >= 400:
            _log.warning(
                "household_directory_failed", household_id=key, status=response.status_code
            )
            raise DirectoryUnavailable(
                f"core-api returned {response.status_code} for a household contact."
            )

        body = response.json()
        contact = HouseholdContact(
            household_id=body["household_id"],
            recipient_ref_hash=body.get("recipient_ref_hash"),
            preferred_language=body.get("preferred_language", "en"),
            gn_division_code=body["gn_division_code"],
        )
        self._remember(key, contact)
        return contact

    async def contacts_for(self, gn_division_codes: list[str]) -> list[HouseholdContact]:
        """Page through every household in these divisions."""
        if not gn_division_codes:
            return []

        try:
            headers = await self._credentials.authorization()
        except CredentialUnavailable as error:
            raise DirectoryUnavailable(
                "No service credential is available to read household contacts."
            ) from error

        found: list[HouseholdContact] = []
        offset = 0
        for _ in range(MAX_PAGES):
            body = await self._contacts_page(gn_division_codes, headers, offset)
            found.extend(
                HouseholdContact(
                    household_id=row["household_id"],
                    recipient_ref_hash=row.get("recipient_ref_hash"),
                    preferred_language=row.get("preferred_language", "en"),
                    gn_division_code=row["gn_division_code"],
                )
                for row in body["contacts"]
            )
            next_offset = body.get("next_offset")
            if next_offset is None:
                return found
            offset = int(next_offset)

        # A division set this large is a caller bug, not a paging problem. Raising beats
        # returning a truncated list that a fan-out would treat as the whole area.
        raise DirectoryUnavailable(
            f"more than {MAX_PAGES} pages of households for {len(gn_division_codes)} "
            "divisions; narrow the area rather than warning part of it"
        )

    async def _contacts_page(
        self, codes: list[str], headers: dict[str, str], offset: int
    ) -> dict[str, Any]:
        try:
            response = await self._client.get(
                f"{self._base_url}/api/v1/admin/households/contacts",
                params={"gn_division_code": codes, "limit": PAGE_SIZE, "offset": offset},
                headers=headers,
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            _log.warning("household_bulk_unreachable", error=type(error).__name__)
            raise DirectoryUnavailable("core-api is unreachable.") from error

        if response.status_code == 401:
            self._credentials.invalidate()
            _log.error(
                "household_bulk_unauthorised",
                hint="the alerting-svc credential was rotated, revoked, or lacks "
                "household:contact_read",
            )
            raise DirectoryUnavailable("core-api refused this service's credential.")
        if response.status_code >= 400:
            _log.warning("household_bulk_failed", status=response.status_code)
            raise DirectoryUnavailable(
                f"core-api returned {response.status_code} for a bulk contact read."
            )

        page: dict[str, Any] = response.json()
        return page

    def _remember(self, key: str, value: HouseholdContact | None) -> None:
        if len(self._cache) >= CACHE_SIZE:
            # Crude, and deliberately so. An LRU would be better and this is a mock-adjacent
            # cache over data that barely changes; clearing beats importing a dependency to
            # evict one entry more cleverly.
            self._cache.clear()
        self._cache[key] = value


class NullDirectory:
    """A directory that resolves nothing, and says so every time.

    For a deployment with no service credential configured. It returns None rather than
    inventing a recipient, and logs at warning with the consequence spelled out, because a
    platform that silently stops telling households about their payments looks identical to
    one where nothing has gone wrong.
    """

    async def contact(self, household_id: UUID | str) -> HouseholdContact | None:
        _log.warning(
            "household_directory_not_configured",
            household_id=str(household_id),
            impact="this household will not be messaged; set SARANA_ALERTING_CLIENT_SECRET "
            "and restart, or run tools/seed/service_clients.py to provision one",
        )
        return None

    async def contacts_for(self, gn_division_codes: list[str]) -> list[HouseholdContact]:
        _log.warning(
            "household_directory_not_configured",
            divisions=len(gn_division_codes),
            impact="this alert will reach nobody; set SARANA_ALERTING_CLIENT_SECRET and "
            "restart, or run tools/seed/service_clients.py to provision one",
        )
        return []

    async def aclose(self) -> None:
        return None


def build_directory(
    *,
    core_api_url: str,
    client_id: str,
    client_secret: str | None,
    scope: str = "household:contact_read",
) -> HouseholdDirectory:
    """Build the directory a deployment should use.

    Falls back to `NullDirectory` only when no secret is configured, and never falls back
    on an *error* — a credential that exists and does not work must fail loudly rather than
    degrade into silence.
    """
    if not client_secret:
        _log.warning(
            "household_directory_disabled",
            reason="no client secret configured",
            impact="no household will be messaged about a payment or a reversal",
        )
        return NullDirectory()

    return CoreApiDirectory(
        core_api_url,
        credentials=ServiceCredentials(
            base_url=core_api_url,
            client_id=client_id,
            client_secret=client_secret,
            scope=scope,
        ),
    )
