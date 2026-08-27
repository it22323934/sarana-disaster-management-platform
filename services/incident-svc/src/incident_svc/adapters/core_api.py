"""Talking to core-api, and coping when it does not answer.

Only one call matters on the intake path: resolving a coordinate to a GN division. It is
on the critical path for every citizen report, so it is cached hard and it degrades rather
than failing.

A report that cannot be placed is still a report. Losing it because a lookup timed out
would be the worst possible trade: the coordinate is already stored on the row, and a
human or a later pass can place it. Refusing the report loses the only copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import httpx
import structlog

_log = structlog.get_logger(__name__)

CONNECT_TIMEOUT: Final = 2.0
READ_TIMEOUT: Final = 3.0


@dataclass(frozen=True, slots=True)
class ResolvedDivision:
    """Where a coordinate falls, and how confident we are that it is right."""

    gn_division_id: str
    gn_division_code: str
    district_code: str
    resolved: bool = True


class CoreApiClient:
    """The subset of core-api this service needs.

    Holds its own cache keyed by rounded coordinate. Division boundaries change on a
    census cycle, so a cached answer is as good as a fresh one and costs no round trip
    during a surge.
    """

    def __init__(
        self,
        base_url: str,
        *,
        service_token: str | None = None,
        client: httpx.AsyncClient | None = None,
        cache_size: int = 20_000,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        )
        self._cache: dict[str, ResolvedDivision | None] = {}
        self._cache_size = cache_size
        self.reachable = True

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _key(lon: float, lat: float) -> str:
        return f"{round(lon, 5)}:{round(lat, 5)}"

    async def resolve(
        self, *, lon: float, lat: float, token: str | None = None
    ) -> ResolvedDivision | None:
        """The division containing a coordinate, or None.

        None means three different things and the caller does not need to distinguish
        them: the point is offshore, core-api is down, or core-api was slow. In all three
        the report is kept and left unplaced, which is the only safe answer.
        """
        key = self._key(lon, lat)
        if key in self._cache:
            return self._cache[key]

        # The service credential, unless a caller supplies something more specific.
        bearer = token or self._service_token
        headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
        try:
            response = await self._client.get(
                f"{self._base_url}/api/v1/admin/resolve",
                params={"lat": lat, "lng": lon},
                headers=headers,
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            # Not cached: core-api being down is a temporary fact about the platform, not
            # a fact about this coordinate, and caching it would keep reports unplaced
            # long after the service came back.
            self.reachable = False
            _log.warning("core_api_unreachable", error=type(error).__name__, lon=lon, lat=lat)
            return None

        self.reachable = True

        if response.status_code == 404:
            # A real answer: this point is in no division. Worth caching.
            self._remember(key, None)
            return None
        if response.status_code in (401, 403):
            # Named separately from any other failure: this one is a misconfiguration that
            # silently unplaces every report, and it should not look like a bad coordinate.
            _log.error(
                "core_api_resolve_unauthorised",
                status=response.status_code,
                hint="SARANA_INCIDENT_SERVICE_TOKEN is missing, expired, or lacks admin:read",
            )
            return None
        if response.status_code >= 400:
            _log.warning("core_api_resolve_failed", status=response.status_code)
            return None

        body: dict[str, Any] = response.json()
        division = ResolvedDivision(
            gn_division_id=body["id"],
            gn_division_code=body["code"],
            district_code=body["district_code"],
        )
        self._remember(key, division)
        return division

    def _remember(self, key: str, value: ResolvedDivision | None) -> None:
        if len(self._cache) >= self._cache_size:
            # Cheapest possible eviction. The access pattern during an incident is a burst
            # of nearby coordinates, so any entry is about as likely to be reused as any
            # other and a smarter policy would buy nothing.
            self._cache.pop(next(iter(self._cache)), None)
        self._cache[key] = value
