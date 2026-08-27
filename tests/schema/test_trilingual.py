"""No citizen-facing record may exist in only one language.

Non-negotiable #2. On 28 November 2025 the DMC and Defence Ministry press conference on
Cyclone Ditwah went out in Sinhala and English only, and Tamil-speaking communities on
the east coast - where the cyclone made landfall - were left without the warning. These
tests exist so that failure cannot be reproduced by this platform.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from sarana_shared.domain.ids import uuid7

COMPLETE = '{"si": "රතු අනතුරු ඇඟවීම", "ta": "சிவப்பு எச்சரிக்கை", "en": "Red alert"}'

# The migrated database is opened once per session, so its connections live on the
# session event loop. Without this the tests would run on a per-function loop and every
# query would fail with "attached to a different loop".
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('{"si":"a","ta":"b","en":"c"}', True),
        ('{"si":"a","ta":"b"}', False),
        ('{"en":"x"}', False),
        ('{"si":"a","ta":"  ","en":"c"}', False),
        ('{"si":"a","ta":null,"en":"c"}', False),
        ('{"si":"a","ta":123,"en":"c"}', False),
        ('"not an object"', False),
    ],
)
async def test_all_locales_present(db: AsyncConnection, value: str, expected: bool) -> None:
    result = await db.execute(
        text("SELECT public.all_locales_present(CAST(:v AS jsonb))"), {"v": value}
    )

    assert result.scalar_one() is expected


async def test_all_locales_present_rejects_null(db: AsyncConnection) -> None:
    result = await db.execute(text("SELECT public.all_locales_present(NULL::jsonb)"))

    assert result.scalar_one() is False


async def _insert_alert(db: AsyncConnection, headline: str) -> None:
    await db.execute(
        text(
            "INSERT INTO alerting.alert "
            "(id, hazard_event_id, cap_identifier, headline, description, instruction, "
            " severity, urgency, certainty, effective_at, expires_at, "
            " area_gn_division_ids, requires_human_signoff, correlation_id) "
            "VALUES (:id, :hazard_id, :cap, CAST(:headline AS jsonb), "
            f" '{COMPLETE}'::jsonb, '{COMPLETE}'::jsonb, "
            " 'SEVERE', 'IMMEDIATE', 'OBSERVED', now(), now() + interval '6 hours', "
            " ARRAY[:area]::uuid[], true, 'test')"
        ),
        {
            "id": uuid7(),
            "hazard_id": uuid7(),
            "cap": f"CAP-{uuid7()}",
            "headline": headline,
            "area": uuid7(),
        },
    )


async def test_an_alert_in_all_three_languages_is_accepted(db: AsyncConnection) -> None:
    await _insert_alert(db, COMPLETE)


async def test_an_english_only_alert_is_refused(db: AsyncConnection) -> None:
    """The Ditwah failure, as a constraint."""
    with pytest.raises(IntegrityError, match="headline_all_locales"):
        await _insert_alert(db, '{"en": "Red alert"}')


async def test_an_alert_missing_tamil_is_refused(db: AsyncConnection) -> None:
    with pytest.raises(IntegrityError, match="headline_all_locales"):
        await _insert_alert(db, '{"si": "රතු අනතුරු ඇඟවීම", "en": "Red alert"}')


async def test_a_blank_tamil_string_is_not_a_translation(db: AsyncConnection) -> None:
    with pytest.raises(IntegrityError, match="headline_all_locales"):
        await _insert_alert(db, '{"si": "අනතුරු", "ta": "   ", "en": "Alert"}')


async def test_the_constraint_covers_every_citizen_facing_column(
    db: AsyncConnection,
) -> None:
    """A rule applied to only some columns is a rule with a gap.

    This asserts the CHECK exists on every localised column across every schema, so
    adding a new one without its constraint fails here rather than in production.
    """
    result = await db.execute(
        text(
            "SELECT c.relname || '.' || con.conname "
            "FROM pg_constraint con "
            "JOIN pg_class c ON c.oid = con.conrelid "
            "WHERE con.conname LIKE '%_all_locales' "
            "ORDER BY 1"
        )
    )
    constrained = {row[0] for row in result}

    expected = {
        "province.ck_province_name_all_locales",
        "district.ck_district_name_all_locales",
        "ds_division.ck_ds_division_name_all_locales",
        "gn_division.ck_gn_division_name_all_locales",
        "role.ck_role_name_all_locales",
        "alert_template.ck_alert_template_body_all_locales",
        "alert.ck_alert_headline_all_locales",
        "alert.ck_alert_description_all_locales",
        "alert.ck_alert_instruction_all_locales",
        "incident.ck_incident_summary_all_locales",
        "cost_schedule_line.ck_cost_schedule_line_description_all_locales",
        "grievance.ck_grievance_description_all_locales",
        "grievance.ck_grievance_resolution_all_locales",
        "hazard_event.ck_hazard_event_name_all_locales",
    }

    assert expected <= constrained, f"missing: {sorted(expected - constrained)}"
