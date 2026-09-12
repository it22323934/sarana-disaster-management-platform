"""GN officer registry, household registry, and NIC verification.

These are the two registries that put a name to a division and a household to an address.
They are also the only adapters in this package that carry personal data, so three rules
apply here and nowhere else:

  **Every record the mock serves is synthetic.** Names are generated from Sinhala, Tamil
  and Muslim Sri Lankan naming conventions and distributed by district the way the
  population actually is. No record corresponds to a real person, including people whose
  details are on a public electoral roll. There is no configuration that changes this.

  **A verification failure is not an exclusion.** `verify_nic` returns three outcomes and
  `NOT_FOUND` is the interesting one: real registries have gaps, and roughly one valid NIC
  in twelve does not resolve. A household that cannot be verified is a household that
  needs a manual check, never one that is dropped from an aid list. Anything consuming
  this must branch on all three outcomes.

  **SARANA stores none of it.** The household registry is read on the assessment path to
  confirm a household exists; the platform's own tables keep a reference and a keyed hash,
  never the name. Personal data absent beats personal data redacted.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

from sarana_shared.adapters.gov.base import Integration, MockGovClient, RealClientStub


class NicVerification(StrEnum):
    """The outcome of checking a National Identity Card number.

    `NOT_FOUND` is deliberately distinct from `INVALID`. A malformed number is the
    officer's typo; a well-formed number the registry has never heard of is the
    registry's gap, and the two lead to completely different next steps.
    """

    VALID = "valid"
    INVALID = "invalid"
    NOT_FOUND = "not_found"


class Officer(BaseModel):
    """A Grama Niladhari officer, as the registry holds them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_no: str
    name: str
    gn_division_code: str
    # The number the DMC would actually ring. Synthetic, like everything else here.
    contact_msisdn: str
    appointed_year: int
    active: bool = True


class HouseholdRecord(BaseModel):
    """A household as the registry holds it.

    `head_name` and `address` exist because the real registry has them and the adapter
    must model the real contract. Nothing in SARANA persists either.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    household_ref: str
    gn_division_code: str
    head_name: str
    head_nic: str
    address: str
    member_count: int = Field(ge=1)
    # Present when the registry itself flags the record as stale or disputed. Passing it
    # through matters: an officer assessing damage should know the register is unsure.
    registry_note: str | None = None


class HouseholdPage(BaseModel):
    """One page of households, with the cursor for the next.

    Cursor-paginated because the real registry is, and badly: page sizes vary and the
    cursor is opaque. Code that assumes an offset works until the first division with
    more households than one page.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    households: tuple[HouseholdRecord, ...] = Field(default_factory=tuple)
    next_cursor: str | None = None

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


class NicResult(BaseModel):
    """The registry's answer about one NIC."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nic: str
    outcome: NicVerification
    # Only ever populated for VALID. The caller should not need it, and asking for a name
    # back from a verification call is how a verification endpoint becomes a lookup one.
    gn_division_code: str | None = None


class RegistryClient(Protocol):
    """What SARANA needs from the officer and household registries."""

    async def officers(self, *, gn_division_code: str) -> list[Officer]:
        """The officers posted to one GN division."""
        ...

    async def officer(self, service_no: str) -> Officer:
        """One officer by service number.

        Raises:
            GovRecordNotFound: if the service number is not on the register.
        """
        ...

    async def households(
        self, *, gn_division_code: str, cursor: str | None = None
    ) -> HouseholdPage:
        """One page of households in a GN division."""
        ...

    async def household(self, household_ref: str) -> HouseholdRecord:
        """One household by reference.

        Raises:
            GovRecordNotFound: if the reference is not on the register.
        """
        ...

    async def verify_nic(self, nic: str) -> NicResult:
        """Check a NIC against the register.

        Never raises for a NIC the register does not hold — that is `NOT_FOUND`, a real
        answer. It raises only when the register itself could not be reached.
        """
        ...

    async def aclose(self) -> None: ...


class RegistryMockClient(MockGovClient):
    """Talks to `gov-mock`'s officer and household registry routes."""

    system: ClassVar[str] = "registry"

    async def officers(self, *, gn_division_code: str) -> list[Officer]:
        body = await self._get_json(
            "/gnreg/v1/officers", params={"gn_division_id": gn_division_code}
        )
        return [Officer.model_validate(row) for row in body["officers"]]

    async def officer(self, service_no: str) -> Officer:
        body = await self._get_json(f"/gnreg/v1/officers/{service_no}")
        return Officer.model_validate(body["officer"])

    async def households(
        self, *, gn_division_code: str, cursor: str | None = None
    ) -> HouseholdPage:
        body = await self._get_json(
            "/hhreg/v1/households",
            params={"gn_division_id": gn_division_code, "cursor": cursor},
        )
        return HouseholdPage.model_validate(body["page"])

    async def household(self, household_ref: str) -> HouseholdRecord:
        body = await self._get_json(f"/hhreg/v1/households/{household_ref}")
        return HouseholdRecord.model_validate(body["household"])

    async def verify_nic(self, nic: str) -> NicResult:
        body = await self._post_json("/hhreg/v1/verify-nic", json={"nic": nic})
        return NicResult.model_validate(body["verification"])


class RegistryRealClient(RealClientStub):
    """The Department for Registration of Persons and the GN officer register.

    Not yet written, and the one on this list with the heaviest privacy obligations. NIC
    verification touches the national identity register; household data touches the
    electoral roll. Both need a lawful basis stated per query type, not a blanket
    credential, and both need an access log SARANA can produce on request.

    The design constraint that follows: verification returns an outcome, never a record.
    An integration that hands back a name for any NIC presented to it is a bulk lookup
    facility with a verification label on it.
    """

    integration: ClassVar[Integration] = Integration(
        system="registry",
        organisation=(
            "Department for Registration of Persons; District Secretariat GN officer register"
        ),
        base_url="https://api.drp.gov.lk",
        credential=(
            "an agency account with per-query lawful-basis assertion, and a retained "
            "access log disclosable to the data subject"
        ),
        agreement=(
            "a data protection impact assessment and a data-sharing agreement limiting "
            "queries to verification of a household already claiming disaster relief"
        ),
    )

    async def officers(self, *, gn_division_code: str) -> list[Officer]:
        self._pending("officers", "/officers")

    async def officer(self, service_no: str) -> Officer:
        self._pending("officer", f"/officers/{service_no}")

    async def households(
        self, *, gn_division_code: str, cursor: str | None = None
    ) -> HouseholdPage:
        self._pending("households", "/households")

    async def household(self, household_ref: str) -> HouseholdRecord:
        self._pending("household", f"/households/{household_ref}")

    async def verify_nic(self, nic: str) -> NicResult:
        self._pending("verify_nic", "/verify-nic")
