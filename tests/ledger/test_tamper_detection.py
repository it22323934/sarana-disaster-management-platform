"""Tamper detection: the test the build brief calls the most important one in the repo.

The claim SARANA makes is that aid disbursement is independently auditable. That claim is
worth exactly as much as this test. If someone with database access can change what was
paid and the published record still verifies, the transparency dashboard is decoration.

So these are written as attacks. Each one alters the ledger in a specific way and asserts
that `sarana-verify` — which holds no credentials and reads only public data — refuses it
and names the exact entry.

Three attacks, because they fail through different mechanisms:

  **Edit a row.** Its own hash no longer matches its contents.
  **Delete a row.** Every remaining hash is individually valid; the *linkage* breaks.
  **Rewrite the whole chain.** Every hash and every link is consistent — and the published
  Merkle anchor, which lives under a compliance-mode object lock, still disagrees.

The third is the one that matters most. An operator who can write to the database can
recompute the chain; they cannot alter what was anchored yesterday.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from sarana_shared.crypto.canonical import canonical_bytes
from sarana_shared.crypto.merkle import merkle_root

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "tools" / "sarana-verify") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools" / "sarana-verify"))

import verify  # noqa: E402  - the standalone CLI under test


def build_ledger(count: int = 6, *, day: str = "2026-08-28") -> list[dict[str, Any]]:
    """A small, correctly chained ledger, built the way the database builds one."""
    entries: list[dict[str, Any]] = []
    previous = verify.GENESIS_HASH

    for index in range(1, count + 1):
        entry: dict[str, Any] = {
            "seq": index,
            "anchor_date": day,
            "entitlement_id": f"01a04400-0000-7000-8000-{index:012d}",
            "amount_lkr_cents": 25_000_00 + index * 1_000_00,
            "payment_rail": "BANK_TRANSFER",
            "gn_division_code": "LK-21-01-001",
            "prev_hash": previous,
        }
        entry["entry_hash"] = verify.entry_hash(entry)
        previous = entry["entry_hash"]
        entries.append(entry)

    return entries


def build_anchor(entries: list[dict[str, Any]], *, day: str = "2026-08-28") -> dict[str, Any]:
    """The published anchor for a day's entries."""
    leaves = [
        hashlib.sha256(
            canonical_bytes({k: v for k, v in entry.items() if k not in verify.HASH_FIELDS})
        ).hexdigest()
        for entry in entries
    ]
    return {
        "date": day,
        "merkle_root": merkle_root(leaves),
        "entry_count": len(entries),
        "first_seq": min(int(e["seq"]) for e in entries),
        "last_seq": max(int(e["seq"]) for e in entries),
        "prev_anchor_hash": None,
    }


# --------------------------------------------------------------------------------------
# The baseline: an untouched ledger verifies
# --------------------------------------------------------------------------------------


def test_an_untouched_ledger_verifies() -> None:
    """Without this, every test below would pass for the wrong reason."""
    entries = build_ledger()

    assert verify.verify_chain(entries) is None
    assert verify.verify_anchors(entries, [build_anchor(entries)]) == []


def test_an_empty_ledger_verifies() -> None:
    """A day with no disbursements is not a failure."""
    assert verify.verify_chain([]) is None


# --------------------------------------------------------------------------------------
# Attack 1: edit a row
# --------------------------------------------------------------------------------------


def test_altering_an_amount_is_detected_and_the_seq_is_named() -> None:
    """The case the brief names: mutate one row, the verifier exits non-zero naming it."""
    entries = build_ledger()
    entries[2]["amount_lkr_cents"] = 1_000_000_00

    divergence = verify.verify_chain(entries)

    assert divergence is not None
    assert divergence.seq == 3
    assert "altered" in divergence.reason


def test_altering_the_beneficiary_is_detected() -> None:
    """Redirecting a payment is the attack with a motive."""
    entries = build_ledger()
    entries[4]["entitlement_id"] = "01a04400-0000-7000-8000-999999999999"

    divergence = verify.verify_chain(entries)

    assert divergence is not None
    assert divergence.seq == 5


def test_the_first_divergence_is_reported_not_the_last() -> None:
    """After a break every later hash differs too.

    Reporting all of them would bury the one entry that was actually touched under
    thousands of consequential failures.
    """
    entries = build_ledger(count=10)
    entries[1]["amount_lkr_cents"] = 1
    entries[7]["amount_lkr_cents"] = 2

    divergence = verify.verify_chain(entries)

    assert divergence is not None
    assert divergence.seq == 2


def test_rewriting_an_entrys_own_hash_to_match_does_not_help() -> None:
    """Recomputing one row's hash breaks the *next* row's link instead.

    An attacker has to rewrite everything after it, which is what the anchor then catches.
    """
    entries = build_ledger()
    entries[2]["amount_lkr_cents"] = 999_999_00
    entries[2]["entry_hash"] = verify.entry_hash(entries[2])

    divergence = verify.verify_chain(entries)

    assert divergence is not None
    assert divergence.seq == 4
    assert "removed or inserted" in divergence.reason


# --------------------------------------------------------------------------------------
# Attack 2: delete a row
# --------------------------------------------------------------------------------------


def test_removing_an_entry_from_the_middle_is_detected() -> None:
    """Every remaining hash is individually valid. The linkage is what breaks.

    A per-row checksum would miss this entirely, which is why the chain exists.
    """
    entries = build_ledger()
    del entries[3]

    divergence = verify.verify_chain(entries)

    assert divergence is not None
    assert divergence.seq == 5
    assert "removed or inserted" in divergence.reason


def test_inserting_a_fabricated_entry_is_detected() -> None:
    """A payment that was never made, spliced into the record."""
    entries = build_ledger()
    fabricated = dict(entries[2])
    fabricated["seq"] = 25
    fabricated["amount_lkr_cents"] = 500_000_00
    entries.insert(3, fabricated)

    divergence = verify.verify_chain(entries)

    assert divergence is not None


def test_removing_the_last_entry_is_caught_by_the_anchor() -> None:
    """Truncation leaves a perfectly valid chain. Only the anchor's count catches it.

    This is why the anchor commits to `entry_count` as well as the root: duplicate-last
    Merkle construction lets a shorter tree collide with a longer one.
    """
    entries = build_ledger()
    anchor = build_anchor(entries)
    truncated = entries[:-1]

    assert verify.verify_chain(truncated) is None, "the chain alone cannot see this"

    problems = verify.verify_anchors(truncated, [anchor])
    assert problems
    assert "entries" in problems[0]


# --------------------------------------------------------------------------------------
# Attack 3: rewrite the whole chain
# --------------------------------------------------------------------------------------


def test_a_fully_rewritten_chain_still_fails_against_the_published_anchor() -> None:
    """The attack the anchor exists for, and the most important assertion here.

    An operator with database access can recompute every hash after altering a row - the
    chain alone proves nothing about them. What they cannot do is change the Merkle root
    published yesterday to object storage under a compliance-mode lock.
    """
    original = build_ledger()
    anchor = build_anchor(original)

    # Alter an amount and rebuild the entire chain from that point so it is internally
    # perfect.
    tampered = build_ledger()
    tampered[2]["amount_lkr_cents"] = 5_000_000_00
    previous = verify.GENESIS_HASH
    for entry in tampered:
        entry["prev_hash"] = previous
        entry["entry_hash"] = verify.entry_hash(entry)
        previous = entry["entry_hash"]

    assert verify.verify_chain(tampered) is None, "the rewritten chain is self-consistent"

    problems = verify.verify_anchors(tampered, [anchor])

    assert problems, "the published anchor must still refuse it"
    assert "merkle root differs" in problems[0]


def test_every_failing_day_is_reported_not_just_the_first() -> None:
    """Days are independent. A journalist checking a year wants every date that fails."""
    monday = build_ledger(count=3, day="2026-08-24")
    tuesday = build_ledger(count=3, day="2026-08-25")
    anchors = [build_anchor(monday, day="2026-08-24"), build_anchor(tuesday, day="2026-08-25")]

    monday[0]["amount_lkr_cents"] = 1
    tuesday[0]["amount_lkr_cents"] = 2

    problems = verify.verify_anchors(monday + tuesday, anchors)

    assert len(problems) == 2


# --------------------------------------------------------------------------------------
# The CLI contract: exit codes and a named sequence number
# --------------------------------------------------------------------------------------


def test_the_cli_exits_zero_on_a_clean_ledger(tmp_path: Path) -> None:
    entries = build_ledger()
    feed = tmp_path / "feed.json"
    anchors = tmp_path / "anchors.json"
    feed.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    anchors.write_text(json.dumps({"anchors": [build_anchor(entries)]}), encoding="utf-8")

    assert verify.main(["--feed", str(feed), "--anchors", str(anchors)]) == 0


def test_the_cli_exits_non_zero_and_names_the_seq(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The definition of done: non-zero, with the exact seq of the first divergence."""
    entries = build_ledger()
    anchor = build_anchor(entries)
    entries[3]["amount_lkr_cents"] = 99_999_999

    feed = tmp_path / "feed.json"
    anchors = tmp_path / "anchors.json"
    feed.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    anchors.write_text(json.dumps({"anchors": [anchor]}), encoding="utf-8")

    exit_code = verify.main(["--feed", str(feed), "--anchors", str(anchors)])

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "seq 4" in stderr
    assert "VERIFICATION FAILED" in stderr


def test_the_cli_exits_two_when_it_cannot_read_the_inputs(tmp_path: Path) -> None:
    """Distinct from a divergence: "I could not check" is not "I checked and it is fine"."""
    missing = tmp_path / "nope.json"

    assert verify.main(["--feed", str(missing), "--anchors", str(missing)]) == 2


def test_the_verifier_needs_no_credentials() -> None:
    """The property that makes this proof rather than assurance.

    If verification required access the public does not have, it would only ever
    demonstrate that SARANA agrees with itself.
    """
    source = (REPO_ROOT / "tools" / "sarana-verify" / "verify.py").read_text(encoding="utf-8")

    for forbidden in ("Authorization", "password", "SARANA_DATABASE_URL", "psycopg", "asyncpg"):
        assert forbidden not in source, f"the verifier must not reference {forbidden}"
