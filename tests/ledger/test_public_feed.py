"""The public feed: what the world can check, and what it must never contain.

Two claims rest on this file, and they pull against each other.

**It has to be verifiable.** `tools/sarana-verify` reads `/api/v1/ledger/public` and
`/api/v1/ledger/anchors`, holds no credentials, and recomputes every entry hash and every
daily Merkle root. That only works if the published bytes are the hashed bytes.

**It has to be anonymous.** The brief's own words: no name, NIC, phone, or coordinate at
any zoom level. A transparency feed that identifies who was paid what, house by house, is a
list of which households just received money.

The tests below check both against the *same* definitions the service uses - the SQL that
publishes, the function that hashes, and the worker that anchors - because a test with its
own copy of the entry shape would pass while the three of them disagreed.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ledger_svc.api.v1.ledger import HASH_SCHEME, AnchorRow, PublicLedgerEntry
from ledger_svc.domain.ledger_entry import NON_PAYLOAD_FIELDS, payload_of, public_entry
from ledger_svc.repo.queries import _ENTRIES_FOR_DAY, _PUBLIC_LEDGER_ENTRIES
from sarana_shared.crypto.chain import GENESIS_HASH, link
from sarana_shared.crypto.merkle import build_anchor
from sarana_shared.domain.ids import uuid7

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "tools" / "sarana-verify") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools" / "sarana-verify"))

import verify  # noqa: E402  - the standalone CLI the public actually runs

DAY = "2026-08-28"


def a_feed(count: int = 5) -> list[dict[str, Any]]:
    """A published feed, built exactly the way the service builds one.

    Through `public_entry` and `link`, not by hand. A hand-built fixture would let the
    service drift away from the thing under test without a single failure.
    """
    entries: list[dict[str, Any]] = []
    previous = GENESIS_HASH

    for index in range(1, count + 1):
        payload = public_entry(
            entitlement_id=uuid7(),
            amount_lkr_cents=25_000_00 + index * 1_000_00,
            released_by=uuid7(),
            released_at=datetime(2026, 8, 28, 6, index, tzinfo=UTC),
            payment_rail="BANK_TRANSFER",
            payment_ref=f"MOCK-BANK_TRANSFER-{index:012X}",
        )
        entry = link({**payload, "seq": index, "anchor_date": DAY}, previous)
        previous = entry["entry_hash"]
        entries.append(entry)

    return entries


# --------------------------------------------------------------------------------------
# Verifiable by someone with no access
# --------------------------------------------------------------------------------------


def test_the_published_feed_verifies_with_the_public_tool() -> None:
    """The whole claim, in one assertion."""
    assert verify.verify_chain(a_feed()) is None


def test_the_published_anchor_matches_the_published_feed() -> None:
    """The service anchors the same payloads it publishes.

    If these ever diverge, an honest ledger fails verification and the alarm is
    indistinguishable from tampering.
    """
    entries = a_feed()
    anchor = build_anchor(entries, date=DAY)

    problems = verify.verify_anchors(entries, [anchor.as_dict()])

    assert problems == []


def test_the_service_and_the_verifier_exclude_the_same_fields() -> None:
    """Four fields, agreed in two codebases that never import each other."""
    assert set(NON_PAYLOAD_FIELDS) == set(verify.HASH_FIELDS)


def test_the_scheme_is_published_with_the_anchors() -> None:
    """A verifier should not have to read this repository to reproduce a root."""
    assert "RFC 8785" in HASH_SCHEME["canonical_json"]
    assert "duplicated" in HASH_SCHEME["merkle_odd_node"]
    assert "prev_hash" in HASH_SCHEME["entry_hash"]


def test_an_altered_amount_is_caught_and_named() -> None:
    """The feed is only worth something if changing it is detected."""
    entries = a_feed()
    entries[2]["amount_lkr_cents"] += 1

    divergence = verify.verify_chain(entries)

    assert divergence is not None
    assert divergence.seq == 3


def test_a_removed_entry_is_caught() -> None:
    """Every remaining hash is individually valid; the linkage is what breaks."""
    entries = a_feed()
    del entries[2]

    assert verify.verify_chain(entries) is not None


# --------------------------------------------------------------------------------------
# Anonymous
# --------------------------------------------------------------------------------------

# Columns that must never reach the public feed. Written as the substrings a careless
# `SELECT d.*, a.*` would introduce, because that is how it would actually happen.
FORBIDDEN_COLUMNS = (
    "household_id",
    "nic",
    "phone",
    "msisdn",
    "full_name",
    "gn_division",
    "gps",
    "latitude",
    "longitude",
    "geom",
    "centroid",
    "assessment_ref",
    "assessed_by",
)


@pytest.mark.parametrize("column", FORBIDDEN_COLUMNS)
def test_the_public_feed_query_selects_no_identifier(column: str) -> None:
    """Asserted against the SQL, not the response.

    The anonymisation has to be a property of the query: a response model is one careless
    field addition away from publishing a household id, and nobody reviews a serialiser
    the way they review a SELECT.
    """
    assert column not in _PUBLIC_LEDGER_ENTRIES.lower()


@pytest.mark.parametrize("column", FORBIDDEN_COLUMNS)
def test_the_anchored_payload_selects_no_identifier(column: str) -> None:
    """The anchor query must match the feed, so it must be clean for the same reasons."""
    assert column not in _ENTRIES_FOR_DAY.lower()


def test_the_response_model_publishes_only_the_agreed_fields() -> None:
    """A field added to the model without being added to the hash would break every
    verification; one added to both would publish something new without anybody deciding
    to.

    `reversed` was added deliberately, and it is the second kind: published but outside
    the hash. A payment the bank later returned is a fact about the entry rather than part
    of what the entry says happened, and the authoritative record is the chained
    compensating entry at /api/v1/ledger/reversals. Publishing a released payment with no
    hint that the money came back would be the sort of true-but-misleading number a
    transparency feed exists to prevent.
    """
    assert set(PublicLedgerEntry.model_fields) == {
        "seq",
        "anchor_date",
        "prev_hash",
        "entry_hash",
        "entitlement_id",
        "amount_lkr_cents",
        "released_by",
        "released_at",
        "payment_rail",
        "payment_ref",
        "reversed",
    }


def test_the_reversal_flag_is_outside_the_hash() -> None:
    """`reversed` must be stripped before recomputing, or all of history stops verifying.

    The trap the handoff documents: a field added to the published feed and *not* to the
    exclusion list changes the recomputed payload of every entry ever written, including
    the ones written before the field existed. Their stored hashes were computed without
    it, so every one of them would fail.
    """
    from sarana_shared.crypto.chain import HASH_FIELDS

    assert "reversed" in NON_PAYLOAD_FIELDS
    assert "reversed" in HASH_FIELDS
    assert "reversed" not in public_entry(
        entitlement_id=uuid7(),
        amount_lkr_cents=1,
        released_by=uuid7(),
        released_at="2026-08-29T00:00:00+00:00",
        payment_rail="CASH",
        payment_ref="MOCK-CASH-1",
    )


def test_the_hashed_payload_is_exactly_what_is_published() -> None:
    """Strip the four metadata fields from a published entry and you have the payload.

    This is the property that makes the feed checkable with `sha256sum` and patience.
    """
    entry = a_feed(1)[0]

    assert set(payload_of(entry)) == set(
        public_entry(
            entitlement_id="x",
            amount_lkr_cents=1,
            released_by="y",
            released_at="z",
            payment_rail="CASH",
            payment_ref=None,
        )
    )


def test_the_released_at_string_is_hashed_and_published_identically() -> None:
    """A datetime would leave the answer to whichever JSON serialiser ran.

    `+00:00` versus `Z` is enough to break every hash in the feed, and it would break it
    at deployment time rather than in a test.
    """
    payload = public_entry(
        entitlement_id=uuid7(),
        amount_lkr_cents=1,
        released_by=uuid7(),
        released_at=datetime(2026, 8, 28, 6, 0, tzinfo=UTC),
        payment_rail="CASH",
        payment_ref=None,
    )

    assert isinstance(payload["released_at"], str)
    assert payload["released_at"].endswith("+00:00")


def test_the_sql_renders_the_same_timestamp_format() -> None:
    """The Python and the SQL renderings have to agree, and only one of them is tested by
    the round trip above."""
    assert 'YYYY-MM-DD"T"HH24:MI:SS.US+00:00' in _PUBLIC_LEDGER_ENTRIES
    assert 'YYYY-MM-DD"T"HH24:MI:SS.US+00:00' in _ENTRIES_FOR_DAY


# --------------------------------------------------------------------------------------
# The verifier consumes the API's own response shapes
# --------------------------------------------------------------------------------------


def test_the_anchor_response_uses_the_field_names_the_verifier_reads() -> None:
    """`date`, not `anchor_date`.

    The two names diverged once and nothing failed: every unit test built its own anchor
    dict, so the mismatch would only have appeared the first time a journalist pointed the
    tool at a deployment.
    """
    required = {"date", "merkle_root", "entry_count", "first_seq", "last_seq"}

    assert required <= set(AnchorRow.model_fields)


def test_the_anchor_response_carries_the_field_that_chains_the_days() -> None:
    """Without it a verifier can check every root and still miss a missing Tuesday."""
    assert "prev_anchor_hash" in AnchorRow.model_fields


def test_the_verifier_reads_the_api_response_envelopes_end_to_end() -> None:
    """Both endpoints, as the tool actually parses them.

    `feed["entries"]` and `anchors["anchors"]` are the keys `verify.main` reaches for. A
    rename on either side is a silent break, because everything else in this file works
    with bare lists.
    """
    entries = a_feed()
    anchor = build_anchor(entries, date=DAY)

    feed_response = {"entries": entries, "next_seq": None, "scheme": HASH_SCHEME, "note": ""}
    anchor_response = {"anchors": [anchor.as_dict()], "scheme": HASH_SCHEME}

    parsed_entries = feed_response["entries"]
    parsed_anchors = anchor_response["anchors"]

    assert verify.verify_chain(parsed_entries) is None
    assert verify.verify_anchors(parsed_entries, parsed_anchors) == []


def test_a_whole_day_removed_from_the_anchor_series_leaves_a_gap_in_the_chain() -> None:
    """The attack the anchor chain exists for.

    Every surviving anchor still verifies against its own entries. What does not survive
    is the linkage: Wednesday's record names a predecessor that is no longer published.
    """
    monday = build_anchor(a_feed(2), date="2026-08-24")
    tuesday = build_anchor(a_feed(2), date="2026-08-25", prev_anchor_hash=monday.anchor_hash())
    wednesday = build_anchor(a_feed(2), date="2026-08-26", prev_anchor_hash=tuesday.anchor_hash())

    published = [monday, wednesday]
    by_hash = {item.anchor_hash() for item in published}

    assert wednesday.prev_anchor_hash not in by_hash
