"""Minimal row builders for the constraint tests.

Deliberately raw SQL rather than the ORM: these tests are about what the database
refuses, and going through SQLAlchemy would let a model-level default quietly satisfy a
constraint the database was supposed to enforce.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from sarana_shared.domain.ids import uuid7

TRILINGUAL = '{"si": "සිංහල", "ta": "தமிழ்", "en": "English"}'

# Crockford base32 excludes I, L, O and U so a code cannot be misread over a phone
# line. The public-ref CHECK constraints enforce that alphabet.
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def public_ref(prefix: str, source: UUID) -> str:
    """Build a public reference in the shape the CHECK constraints require."""
    tail = source.int
    body = ""
    for _ in range(6):
        body += CROCKFORD[tail % 32]
        tail //= 32
    return f"{prefix}-251128-{body}"


async def make_admin_hierarchy(db: AsyncConnection) -> dict[str, Any]:
    """Create one province, district, DS and GN division, and return their ids and codes."""
    province_id, district_id, ds_id, gn_id = (uuid7() for _ in range(4))

    await db.execute(
        text(
            "INSERT INTO admin.province (id, code, name) "
            f"VALUES (:id, 'LK-P02', '{TRILINGUAL}'::jsonb)"
        ),
        {"id": province_id},
    )
    await db.execute(
        text(
            "INSERT INTO admin.district (id, code, province_id, name) "
            f"VALUES (:id, 'LK-11', :province_id, '{TRILINGUAL}'::jsonb)"
        ),
        {"id": district_id, "province_id": province_id},
    )
    await db.execute(
        text(
            "INSERT INTO admin.ds_division (id, code, district_id, name) "
            f"VALUES (:id, 'LK-11-03', :district_id, '{TRILINGUAL}'::jsonb)"
        ),
        {"id": ds_id, "district_id": district_id},
    )
    await db.execute(
        text(
            "INSERT INTO admin.gn_division "
            "(id, code, ds_division_id, name, geom, population, household_count) "
            f"VALUES (:id, 'LK-11-03-045', :ds_id, '{TRILINGUAL}'::jsonb, "
            "ST_Multi(ST_GeomFromText("
            "'POLYGON((80.6 7.2, 80.7 7.2, 80.7 7.3, 80.6 7.3, 80.6 7.2))', 4326)), "
            "2140, 530)"
        ),
        {"id": gn_id, "ds_id": ds_id},
    )

    return {
        "province_id": province_id,
        "district_id": district_id,
        "ds_id": ds_id,
        "gn_id": gn_id,
        "gn_code": "LK-11-03-045",
        "ds_code": "LK-11-03",
        "district_code": "LK-11",
    }


async def make_user_with_role(db: AsyncConnection, role_code: str, scope_code: str) -> UUID:
    """Create a user holding one role at one administrative scope."""
    user_id = uuid7()
    role_id = uuid7()

    await db.execute(
        text(
            "INSERT INTO admin.app_user (id, email, full_name, status) "
            "VALUES (:id, :email, 'Test Officer', 'ACTIVE')"
        ),
        {"id": user_id, "email": f"{user_id}@example.test"},
    )
    await db.execute(
        text(
            "INSERT INTO admin.role (id, code, name) "
            f"VALUES (:id, :code, '{TRILINGUAL}'::jsonb) "
            "ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code "
            "RETURNING id"
        ),
        {"id": role_id, "code": role_code},
    )
    resolved = await db.execute(
        text("SELECT id FROM admin.role WHERE code = :code"), {"code": role_code}
    )
    role_id = resolved.scalar_one()

    scope_type = {2: "DISTRICT", 3: "DS", 4: "GN"}.get(len(scope_code.split("-")), "NATIONAL")
    await db.execute(
        text(
            "INSERT INTO admin.user_role (id, user_id, role_id, scope_type, scope_code) "
            "VALUES (:id, :user_id, :role_id, :scope_type, :scope_code)"
        ),
        {
            "id": uuid7(),
            "user_id": user_id,
            "role_id": role_id,
            "scope_type": scope_type,
            "scope_code": scope_code,
        },
    )
    return user_id


async def make_entitlement(db: AsyncConnection, hierarchy: dict[str, Any]) -> dict[str, Any]:
    """Build a cost schedule, an accepted assessment and its entitlement."""
    schedule_id, assessment_id, entitlement_id = (uuid7() for _ in range(3))
    household_id = uuid7()
    officer_id = await make_user_with_role(db, "GN_OFFICER", hierarchy["gn_code"])

    await db.execute(
        text(
            "INSERT INTO admin.household "
            "(id, gn_division_id, reference_code, member_count, preferred_language) "
            "VALUES (:id, :gn_id, :ref, 4, 'ta')"
        ),
        {"id": household_id, "gn_id": hierarchy["gn_id"], "ref": f"HH-{household_id.hex[-12:]}"},
    )
    await db.execute(
        text(
            "INSERT INTO aid.cost_schedule "
            "(id, version, published_at, effective_from) "
            "VALUES (:id, '2025.11', now(), DATE '2025-11-01') "
            "ON CONFLICT (version) DO NOTHING"
        ),
        {"id": schedule_id},
    )
    resolved_schedule = await db.execute(
        text("SELECT id FROM aid.cost_schedule WHERE version = '2025.11'")
    )
    schedule_id = resolved_schedule.scalar_one()
    await db.execute(
        text(
            "INSERT INTO aid.damage_assessment "
            "(id, public_ref, household_id, gn_division_id, gn_division_code, "
            " hazard_event_id, assessed_by, category, cost_estimate_lkr_cents, "
            " evidence_hash, client_operation_id, status, correlation_id) "
            "VALUES (:id, :ref, :household_id, :gn_id, :gn_code, :hazard_id, :officer_id, "
            " 'HOUSE_FULL', 100000000, :evidence, :client_op, 'ACCEPTED', 'test')"
        ),
        {
            "id": assessment_id,
            "ref": public_ref("DMG", assessment_id),
            "household_id": household_id,
            "gn_id": hierarchy["gn_id"],
            "gn_code": hierarchy["gn_code"],
            "hazard_id": uuid7(),
            "officer_id": officer_id,
            "evidence": "a" * 64,
            "client_op": f"op-{assessment_id.hex[-12:]}",
        },
    )
    await db.execute(
        text(
            "INSERT INTO aid.entitlement "
            "(id, assessment_id, cost_schedule_id, cost_schedule_version, "
            " calculated_lkr_cents, calculation_trace, status, correlation_id) "
            "VALUES (:id, :assessment_id, :schedule_id, '2025.11', 100000000, "
            " :trace, 'APPROVED', 'test')"
        ),
        {
            "id": entitlement_id,
            "assessment_id": assessment_id,
            "schedule_id": schedule_id,
            "trace": '{"line": "HOUSE_FULL", "rate_lkr_cents": 100000000, "multiplier": 1}',
        },
    )

    return {
        "entitlement_id": entitlement_id,
        "assessment_id": assessment_id,
        "household_id": household_id,
        "schedule_id": schedule_id,
        "officer_id": officer_id,
    }
