"""Privacy constraints: anomaly flags name no one, and row-level security holds.

ADR-009: flagging a GN officer's assessments on a statistical artifact can end a career.
Divisions with genuinely worse damage will legitimately look like outliers - that is the
damage behaving as expected, not evidence about whoever assessed it. A flag describes a
pattern; it is never public and never names a person.

Non-negotiable #3: no personal data on any public surface. Row-level security is the
control that still holds when a handler forgets its scope filter.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from sarana_shared.db.sql import FORBIDDEN_RATIONALE_KEYS
from sarana_shared.domain.ids import uuid7

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _flag(db: AsyncConnection, rationale: str) -> None:
    await db.execute(
        text(
            "INSERT INTO aid.anomaly_flag "
            "(id, subject_type, subject_id, detector, detector_version, score, rationale) "
            "VALUES (:id, 'ASSESSMENT', :subject, 'cost-outlier', '1.0', 0.91, "
            " CAST(:rationale AS jsonb))"
        ),
        {"id": uuid7(), "subject": uuid7(), "rationale": rationale},
    )


async def test_a_pattern_without_a_name_is_accepted(db: AsyncConnection) -> None:
    await _flag(
        db,
        '{"pattern": "cost estimates 3.2 sigma above the division median",'
        ' "sample_size": 47, "window_days": 14}',
    )


@pytest.mark.parametrize("key", FORBIDDEN_RATIONALE_KEYS)
async def test_a_rationale_naming_an_individual_is_refused(db: AsyncConnection, key: str) -> None:
    with pytest.raises(DBAPIError, match="rationale_names_no_one"):
        await _flag(db, f'{{"{key}": "018f-abc"}}')


async def test_an_identity_nested_deep_is_still_caught(db: AsyncConnection) -> None:
    """Burying the name three levels down is the obvious way round a shallow check."""
    with pytest.raises(DBAPIError, match="rationale_names_no_one"):
        await _flag(db, '{"evidence": {"records": [{"officer_id": "018f-abc"}]}}')


async def test_the_word_appearing_as_a_value_is_not_a_name(db: AsyncConnection) -> None:
    """The check looks for keys, not for text. A false positive here would be its own bug."""
    await _flag(db, '{"note": "no officer_id is recorded against this pattern"}')


async def test_an_open_flag_has_no_disposition_recorded(db: AsyncConnection) -> None:
    with pytest.raises(DBAPIError, match="disposition_is_attributed"):
        await db.execute(
            text(
                "INSERT INTO aid.anomaly_flag "
                "(id, subject_type, subject_id, detector, detector_version, score, "
                " rationale, disposition) "
                "VALUES (:id, 'ASSESSMENT', :subject, 'd', '1.0', 0.5, "
                " '{\"pattern\": \"x\"}'::jsonb, 'REVIEWED_NO_ACTION')"
            ),
            {"id": uuid7(), "subject": uuid7()},
        )


async def test_false_positive_is_a_first_class_outcome(db: AsyncConnection) -> None:
    """The false-positive rate is a tracked metric, so the disposition must be recordable."""
    flag_id = uuid7()
    await db.execute(
        text(
            "INSERT INTO aid.anomaly_flag "
            "(id, subject_type, subject_id, detector, detector_version, score, rationale, "
            " disposition, disposed_by, disposed_at, disposition_note) "
            "VALUES (:id, 'ASSESSMENT', :subject, 'd', '1.0', 0.5, "
            " '{\"pattern\": \"x\"}'::jsonb, 'FALSE_POSITIVE', :by, now(), "
            " 'Division was genuinely worse hit; the outlier is the damage, not the officer.')"
        ),
        {"id": flag_id, "subject": uuid7(), "by": uuid7()},
    )

    result = await db.execute(
        text("SELECT disposition FROM aid.anomaly_flag WHERE id = :id"), {"id": flag_id}
    )
    assert result.scalar_one() == "FALSE_POSITIVE"
