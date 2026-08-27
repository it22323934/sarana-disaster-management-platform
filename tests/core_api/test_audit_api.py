"""The audit log: writing, reading, and proving it has not been edited.

The tamper test is the one that matters. An audit log nobody can verify is a log the
operator can quietly edit, and the whole reason the chain is a database trigger rather
than application code is that the application is not the thing being trusted.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from sarana_shared.domain.ids import uuid7

pytestmark = pytest.mark.asyncio(loop_scope="session")


def an_entry(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "actor_type": "SYSTEM",
        "action": "entitlement.calculated",
        "subject_type": "entitlement",
        "subject_id": str(uuid7()),
        "correlation_id": str(uuid7()),
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------------------
# Who may write, and where from
# --------------------------------------------------------------------------------------


async def test_the_audit_write_path_is_not_on_the_public_surface(
    client: AsyncClient, admin_header: dict[str, str]
) -> None:
    """No bearer token, however privileged, appends to the record via /api/v1."""
    response = await client.post("/api/v1/audit", headers=admin_header, json=an_entry())

    assert response.status_code in (404, 405)


async def test_an_internal_write_is_refused_without_the_system_scope(
    client: AsyncClient, auditor_header: dict[str, str]
) -> None:
    """Reading the log does not confer writing to it."""
    response = await client.post("/internal/v1/audit", headers=auditor_header, json=an_entry())

    assert response.status_code == 403


async def test_an_internal_write_is_refused_anonymously(client: AsyncClient) -> None:
    response = await client.post("/internal/v1/audit", json=an_entry())

    assert response.status_code == 401


async def test_an_agent_action_must_name_its_agent(
    client: AsyncClient, admin_header: dict[str, str]
) -> None:
    """Mirrors the database CHECK, so the failure is legible rather than a constraint error."""
    response = await client.post(
        "/internal/v1/audit",
        headers=admin_header,
        json=an_entry(actor_type="AGENT"),
    )

    assert response.status_code == 422
    assert "must name its agent" in response.text


async def test_a_human_action_must_name_the_human(
    client: AsyncClient, admin_header: dict[str, str]
) -> None:
    response = await client.post(
        "/internal/v1/audit",
        headers=admin_header,
        json=an_entry(actor_type="HUMAN"),
    )

    assert response.status_code == 422
    assert "must name the human" in response.text


async def test_an_unknown_actor_type_is_refused(
    client: AsyncClient, admin_header: dict[str, str]
) -> None:
    response = await client.post(
        "/internal/v1/audit",
        headers=admin_header,
        json=an_entry(actor_type="ROBOT"),
    )

    assert response.status_code == 422


# --------------------------------------------------------------------------------------
# Writing and chaining
# --------------------------------------------------------------------------------------


async def test_a_written_entry_is_hash_chained(
    client: AsyncClient, admin_header: dict[str, str]
) -> None:
    """The trigger fills the hash, so it is filled however the row arrived."""
    response = await client.post("/internal/v1/audit", headers=admin_header, json=an_entry())

    assert response.status_code == 201
    body = response.json()
    assert body["entry_hash"], "the chain trigger must have computed a hash"
    assert body["seq"] > 0


async def test_consecutive_entries_link_to_each_other(
    client: AsyncClient, admin_header: dict[str, str], schema_engine: AsyncEngine
) -> None:
    first = await client.post("/internal/v1/audit", headers=admin_header, json=an_entry())
    second = await client.post("/internal/v1/audit", headers=admin_header, json=an_entry())

    async with schema_engine.connect() as connection:
        result = await connection.execute(
            text("SELECT prev_hash FROM audit.audit_entry WHERE seq = :seq"),
            {"seq": second.json()["seq"]},
        )
        prev_hash = result.scalar_one()

    assert prev_hash == first.json()["entry_hash"]


# --------------------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------------------


async def test_the_audit_read_requires_the_auditor_scope(
    client: AsyncClient, citizen_header: dict[str, str]
) -> None:
    response = await client.get("/api/v1/audit", headers=citizen_header)

    assert response.status_code == 403


async def test_entries_can_be_filtered_by_subject(
    client: AsyncClient, admin_header: dict[str, str], auditor_header: dict[str, str]
) -> None:
    subject_id = str(uuid7())
    await client.post(
        "/internal/v1/audit",
        headers=admin_header,
        json=an_entry(subject_id=subject_id, subject_type="entitlement"),
    )

    response = await client.get(
        "/api/v1/audit",
        headers=auditor_header,
        params={"subject_type": "entitlement", "subject_id": subject_id},
    )

    assert response.status_code == 200
    assert [row["subject_id"] for row in response.json()] == [subject_id]


async def test_a_reversed_time_range_is_refused(
    client: AsyncClient, auditor_header: dict[str, str]
) -> None:
    response = await client.get(
        "/api/v1/audit",
        headers=auditor_header,
        params={"from": "2026-08-02T00:00:00Z", "to": "2026-08-01T00:00:00Z"},
    )

    assert response.status_code == 422


# --------------------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------------------


async def test_an_untampered_chain_verifies_clean(
    client: AsyncClient, admin_header: dict[str, str], auditor_header: dict[str, str]
) -> None:
    for _ in range(3):
        await client.post("/internal/v1/audit", headers=admin_header, json=an_entry())

    response = await client.get("/api/v1/audit/verify", headers=auditor_header)

    assert response.status_code == 200
    body = response.json()
    assert body["intact"] is True
    assert body["divergence"] is None
    assert body["checked"] >= 3


async def test_verification_detects_a_row_edited_in_place(
    client: AsyncClient,
    admin_header: dict[str, str],
    auditor_header: dict[str, str],
    schema_engine: AsyncEngine,
) -> None:
    """The case the brief names: mutate a row directly with the owner role.

    This is the whole point of the chain. Someone with database access changes what an
    action recorded, and the record has to be able to say so.
    """
    written = await client.post("/internal/v1/audit", headers=admin_header, json=an_entry())
    seq = written.json()["seq"]

    # Plain DML cannot do this: the `append_only` trigger refuses UPDATE and DELETE from
    # everyone, the table owner included. So the tamper is staged the only way it could
    # really happen - by disabling that trigger first, which needs ownership. The attacker
    # modelled here is therefore strictly more privileged than the brief assumed, and the
    # chain still catches them.
    async with schema_engine.begin() as connection:
        await connection.execute(text("ALTER TABLE audit.audit_entry DISABLE TRIGGER append_only"))
        await connection.execute(
            text("UPDATE audit.audit_entry SET action = :action WHERE seq = :seq"),
            {"action": "entitlement.approved", "seq": seq},
        )
        await connection.execute(text("ALTER TABLE audit.audit_entry ENABLE TRIGGER append_only"))

    response = await client.get(
        "/api/v1/audit/verify", headers=auditor_header, params={"from_seq": seq, "to_seq": seq}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intact"] is False, "an edited row must not verify clean"
    assert body["divergence"]["seq"] == seq
    assert "does not match the row contents" in body["divergence"]["reason"]

    # Put it back, so the chain is intact again for whatever runs next.
    async with schema_engine.begin() as connection:
        await connection.execute(text("ALTER TABLE audit.audit_entry DISABLE TRIGGER append_only"))
        await connection.execute(
            text("UPDATE audit.audit_entry SET action = :action WHERE seq = :seq"),
            {"action": "entitlement.calculated", "seq": seq},
        )
        await connection.execute(text("ALTER TABLE audit.audit_entry ENABLE TRIGGER append_only"))


async def test_verification_detects_a_row_removed_from_the_middle(
    client: AsyncClient,
    admin_header: dict[str, str],
    auditor_header: dict[str, str],
    schema_engine: AsyncEngine,
) -> None:
    """Every remaining hash is individually valid; the linkage is what breaks.

    Deleting an inconvenient entry is the subtler attack, and the one a per-row checksum
    would miss entirely.
    """
    written = [
        (await client.post("/internal/v1/audit", headers=admin_header, json=an_entry())).json()
        for _ in range(3)
    ]
    middle, last = written[1]["seq"], written[2]["seq"]

    async with schema_engine.begin() as connection:
        await connection.execute(text("ALTER TABLE audit.audit_entry DISABLE TRIGGER append_only"))
        await connection.execute(
            text("DELETE FROM audit.audit_entry WHERE seq = :seq"), {"seq": middle}
        )
        await connection.execute(text("ALTER TABLE audit.audit_entry ENABLE TRIGGER append_only"))

    response = await client.get(
        "/api/v1/audit/verify",
        headers=auditor_header,
        params={"from_seq": last, "to_seq": last},
    )

    body = response.json()
    assert body["intact"] is False
    assert "prev_hash does not match" in body["divergence"]["reason"]


async def test_a_verification_range_is_capped(
    client: AsyncClient, auditor_header: dict[str, str]
) -> None:
    """Unbounded, a verification pass is a denial of service against the auditor's own database."""
    response = await client.get(
        "/api/v1/audit/verify",
        headers=auditor_header,
        params={"from_seq": 1, "to_seq": 10_000_000},
    )

    assert response.status_code == 422
    assert "chunk" in response.text


async def test_verification_requires_the_auditor_scope(
    client: AsyncClient, citizen_header: dict[str, str]
) -> None:
    response = await client.get("/api/v1/audit/verify", headers=citizen_header)

    assert response.status_code == 403
