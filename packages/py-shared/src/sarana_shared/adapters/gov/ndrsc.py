"""NDRSC — the compensation cost schedule, and the Compensation Management System.

**Read this before writing anything against it.**

The National Disaster Relief Services Centre's Compensation Management System is the
**system of record** for compensation claims. SARANA is not. SARANA is the field-capture
and audit layer in front of it: it is where a GN officer's assessment is taken offline,
where the entitlement is calculated with a published trace, where the two approvals are
recorded, and where the payment is anchored in a hash chain the public can verify. When
all of that is done, the completed claim is **pushed** into the CMS and its status is read
back.

That direction is the whole design, and it is not a technical preference. A system that
models itself as the authority on who gets compensated is a system that asks NDRSC to
surrender its own register to a new piece of software, and it does not get adopted. A
system that hands NDRSC a better-evidenced claim than it has ever received, in its own
format, does.

So: `submit_claim` pushes, `claim_status` reads back, and there is deliberately no method
that edits or withdraws a claim once submitted. A correction is a new claim referencing
the old one, because that is how the CMS works and because an audit layer that can quietly
retract its own submissions is not one.

The cost schedule is read-only and versioned. `ledger_svc.domain.entitlement` pins the
version it calculated against; a new schedule never moves an existing entitlement.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

from sarana_shared.adapters.gov.base import Integration, MockGovClient, RealClientStub


class ClaimStatus(StrEnum):
    """Where a claim has got to inside the NDRSC CMS.

    These are the CMS's states, not SARANA's. `ledger_svc` has its own entitlement
    statuses and the two are deliberately not merged: the CMS rejecting a claim SARANA
    approved is a real and informative disagreement, and collapsing them into one field
    would hide it.
    """

    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"


class ScheduleLine(BaseModel):
    """One priced line of a published schedule.

    Shaped to match `ledger_svc.domain.entitlement.ScheduleLine` field for field. The
    formula is a published string, not a description of one: it is printed on the slip a
    household is given, and it has to be the thing that was actually computed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    line_id: str
    category: str
    unit_amount_cents: int = Field(ge=0)
    max_units: int = Field(ge=0)
    formula: str


class CostSchedule(BaseModel):
    """One version of the government compensation schedule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    published_at: datetime
    effective_from: datetime
    household_cap_cents: int = Field(ge=0)
    lines: tuple[ScheduleLine, ...] = Field(default_factory=tuple)

    def line_for(self, category: str) -> ScheduleLine | None:
        """The line pricing one damage category, or None if this schedule omits it."""
        return next((line for line in self.lines if line.category == category), None)


class ClaimSubmission(BaseModel):
    """A completed, approved claim being pushed into the CMS.

    Carries the calculation trace. That is the point of the whole platform reaching this
    far: NDRSC receives not a number but the working behind it, pinned to a schedule
    version, with both approvals named.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_reference: str
    household_reference: str
    gn_division_code: str
    cost_schedule_version: str
    amount_lkr_cents: int = Field(ge=0)
    assessed_at: datetime
    approved_by: tuple[str, ...] = Field(default_factory=tuple)
    calculation_trace: dict[str, object] = Field(default_factory=dict)


class ClaimReceipt(BaseModel):
    """What the CMS says about a claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_reference: str
    client_reference: str
    status: ClaimStatus
    received_at: datetime
    updated_at: datetime
    # Present when the CMS rejected or returned the claim. Carried through to the
    # household verbatim: "rejected" without a reason is not something anyone can appeal.
    reason: str | None = None


class NdrscClient(Protocol):
    """What SARANA needs from NDRSC."""

    async def cost_schedules(self) -> list[CostSchedule]:
        """Every published schedule version, newest first."""
        ...

    async def cost_schedule(self, version: str) -> CostSchedule:
        """One schedule version.

        Raises:
            GovRecordNotFound: if no such version was ever published.
        """
        ...

    async def submit_claim(self, submission: ClaimSubmission) -> ClaimReceipt:
        """Push a completed, approved claim into the CMS.

        Idempotent on `client_reference`. Re-submitting the same reference returns the
        existing receipt rather than creating a second claim, so a retry after a timeout
        cannot pay a household twice.
        """
        ...

    async def claim_status(self, claim_reference: str) -> ClaimReceipt:
        """Read a claim's current status back from the CMS.

        Raises:
            GovRecordNotFound: if the CMS has no such claim.
        """
        ...

    async def aclose(self) -> None: ...


class NdrscMockClient(MockGovClient):
    """Talks to `gov-mock`'s NDRSC routes."""

    system: ClassVar[str] = "ndrsc"

    async def cost_schedules(self) -> list[CostSchedule]:
        body = await self._get_json("/ndrsc/v1/cost-schedules")
        return [CostSchedule.model_validate(row) for row in body["cost_schedules"]]

    async def cost_schedule(self, version: str) -> CostSchedule:
        body = await self._get_json(f"/ndrsc/v1/cost-schedules/{version}")
        return CostSchedule.model_validate(body["cost_schedule"])

    async def submit_claim(self, submission: ClaimSubmission) -> ClaimReceipt:
        body = await self._post_json("/ndrsc/v1/claims", json=submission.model_dump(mode="json"))
        return ClaimReceipt.model_validate(body["claim"])

    async def claim_status(self, claim_reference: str) -> ClaimReceipt:
        body = await self._get_json(f"/ndrsc/v1/claims/{claim_reference}")
        return ClaimReceipt.model_validate(body["claim"])


class NdrscRealClient(RealClientStub):
    """The NDRSC Compensation Management System. Not yet written.

    The integration that matters most, and the one with the longest lead time: writing
    into the CMS means NDRSC accepting SARANA-originated claims as a source, which is a
    policy decision before it is a technical one.

    Read the module docstring before implementing this. The direction of the relationship
    is load-bearing and easy to get backwards under deadline pressure.
    """

    integration: ClassVar[Integration] = Integration(
        system="ndrsc",
        organisation="National Disaster Relief Services Centre",
        base_url="https://cms.ndrsc.gov.lk/api",
        credential=(
            "an authorised submitting-agency account, plus per-district officer "
            "identities the CMS will accept as approvers"
        ),
        agreement=(
            "NDRSC accepting SARANA as a claim origination channel, and agreeing the "
            "claim schema and the correction path (new claim referencing the old, "
            "never an edit)"
        ),
    )

    async def cost_schedules(self) -> list[CostSchedule]:
        self._pending("cost_schedules", "/cost-schedules")

    async def cost_schedule(self, version: str) -> CostSchedule:
        self._pending("cost_schedule", f"/cost-schedules/{version}")

    async def submit_claim(self, submission: ClaimSubmission) -> ClaimReceipt:
        self._pending("submit_claim", "/claims")

    async def claim_status(self, claim_reference: str) -> ClaimReceipt:
        self._pending("claim_status", f"/claims/{claim_reference}")
