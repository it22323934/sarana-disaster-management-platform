"""The reversal vocabularies, in every place they are written down.

Three times, in three languages of the word: a Python enum in
`ledger_svc.domain.reversal`, a CHECK constraint in migration 0010, and the failure reasons
`gov-mock`'s payment rail actually reports. They have to be one set.

If they drift, the failure is a 500 at the worst possible moment: a household's payment has
just bounced, the settlement poller tries to record why, and the database rejects a value
the rail invented. The household is not told, the money stays on the books as delivered,
and the only symptom is a log line nobody is reading at 3 a.m.

Same pattern as `tests/incident/test_vocabularies.py`, `tests/alerting` and
`tests/core_api`. Written after the third time a vocabulary drifted from its schema; write
one whenever two systems hold the same list.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from gov_mock.api.pay import FAILURE_REASONS as RAIL_REASONS
from ledger_svc.domain.reversal import MACHINE_REPORTABLE, ReversalReason
from ledger_svc.repo.base import GRIEVANCE_CHANNELS
from sarana_shared.adapters.gov.payment import FailureReason

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _check_values(db: AsyncConnection, *, table: str, constraint: str) -> set[str]:
    """The values one CHECK constraint allows, read out of the live schema.

    Parsed from `pg_get_constraintdef` rather than assumed, so this test is about what the
    database will actually accept rather than about what a migration file says.
    """
    result = await db.execute(
        text(
            "SELECT pg_get_constraintdef(c.oid) "
            "FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace "
            "WHERE n.nspname = 'aid' AND t.relname = :table AND c.conname = :constraint"
        ),
        {"table": table, "constraint": constraint},
    )
    definition = result.scalar_one()
    # Every value is a single-quoted literal. Extracted by regex rather than by splitting,
    # because Postgres renders the constraint with the casts *outside* the quotes -
    # `ARRAY['ACCOUNT_CLOSED'::character varying, ...]` - and a naive split picks up
    # `::character varying,` as though it were a vocabulary member.
    return set(re.findall(r"'([^']*)'", definition))


async def test_the_reversal_reasons_match_the_schema(db: AsyncConnection) -> None:
    """The domain enum and the CHECK constraint are one set, in both directions."""
    allowed = await _check_values(
        db, table="disbursement_reversal", constraint="ck_reversal_reason_known"
    )
    declared = {reason.value for reason in ReversalReason}

    assert declared <= allowed, f"the schema rejects: {sorted(declared - allowed)}"
    assert allowed <= declared, (
        f"the schema allows values the domain does not: {allowed - declared}"
    )


async def test_the_grievance_channels_match_the_schema(db: AsyncConnection) -> None:
    """`SYSTEM` reached the constraint, not only the Python tuple.

    Migration 0010 adds it so a grievance raised because a bank returned a payment can say
    it arrived on no citizen channel. If the constraint were missed, that grievance would
    be refused at exactly the moment a household most needs the case opened.
    """
    allowed = await _check_values(db, table="grievance", constraint="ck_grievance_channel_known")

    assert set(GRIEVANCE_CHANNELS) == allowed
    assert "SYSTEM" in allowed


def test_every_reason_the_rail_reports_is_one_the_ledger_can_store() -> None:
    """The seam between file 11 and file 10.

    `gov-mock`'s rail invents the failure reason; `aid.disbursement_reversal` has to accept
    it. A reason the rail reports and the schema rejects is a 500 on the settlement path,
    and the settlement path only runs when a household's payment has already failed.
    """
    reportable = {reason.value for reason in ReversalReason}

    for reason in RAIL_REASONS:
        assert reason in reportable, (
            f"the payment rail can report {reason!r}, which the ledger cannot store"
        )


def test_the_adapter_and_the_mock_agree_on_failure_reasons() -> None:
    """The typed adapter must not narrow what the rail can actually say.

    `PaymentMockClient` parses the rail's response into `FailureReason`. A value the rail
    emits and the adapter's enum lacks is a validation error inside the client, which
    surfaces as an unparseable response rather than as the failed payment it is.
    """
    assert {reason.value for reason in FailureReason} == set(RAIL_REASONS)


def test_a_machine_may_record_every_reason_the_rail_can_report() -> None:
    """`MACHINE_REPORTABLE` must cover the whole rail vocabulary.

    The settlement poller is a machine. If the rail could report a reason the poller is
    forbidden from recording, that payment would fail silently forever — reversed by
    nobody, and the household never told.
    """
    machine_values = {reason.value for reason in MACHINE_REPORTABLE}

    for reason in RAIL_REASONS:
        assert reason in machine_values, (
            f"the rail reports {reason!r} but a worker may not record it, so a payment "
            "failing this way would never be reversed"
        )
