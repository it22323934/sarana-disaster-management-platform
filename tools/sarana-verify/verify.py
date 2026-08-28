"""Independently verify the SARANA aid ledger.

This tool is the proof. Everything else in the platform asks you to trust it; this asks
you to check.

It takes only **public** inputs — the anonymised ledger feed and the published daily
anchors — and recomputes the chain from scratch. It holds no credentials, needs no access
to any SARANA system, and shares no code with the service that wrote the data beyond the
two published algorithms (RFC 8785 canonicalisation and the Merkle construction). If the
government's numbers and the recomputed numbers disagree, this exits non-zero and names
the exact entry where they diverge.

Two independent things are checked, and they fail differently:

  **The chain.** Each entry's `entry_hash` is recomputed from its contents, and each
  entry's `prev_hash` must equal the previous entry's hash. Editing a row breaks the
  first; deleting one from the middle breaks the second while every remaining hash still
  looks individually valid.

  **The anchors.** Each day's Merkle root is recomputed from that day's entries and
  compared with the published anchor. The anchors are written to object storage under a
  compliance-mode lock, so an operator who recomputed the whole chain after tampering
  still cannot change what was anchored yesterday.

Usage:

    python verify.py --feed ledger.json --anchors anchors.json
    python verify.py --base-url https://api.sarana.lk

Exit codes: 0 verified, 1 divergence found, 2 could not fetch the inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The two published algorithms. Imported from the shared package here for convenience;
# an independent verifier would reimplement them from the specification, which is exactly
# the point of specifying them.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "packages" / "py-shared" / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "packages" / "py-shared" / "src"))

from sarana_shared.crypto.canonical import canonical_bytes  # noqa: E402
from sarana_shared.crypto.merkle import Anchor, merkle_root  # noqa: E402

# The genesis value the chain starts from, matching `public.sarana_hash_chain()`.
GENESIS_HASH = "0" * 64

# Fields that are not part of what gets hashed: the hashes themselves.
HASH_FIELDS = ("prev_hash", "entry_hash")

FETCH_TIMEOUT_SECONDS = 30


@dataclass(frozen=True, slots=True)
class Divergence:
    """Where the published record and the recomputed one stop agreeing."""

    seq: int
    reason: str
    expected: str | None = None
    found: str | None = None

    def render(self) -> str:
        lines = [f"  seq {self.seq}: {self.reason}"]
        if self.expected is not None:
            lines.append(f"    expected: {self.expected}")
        if self.found is not None:
            lines.append(f"    found:    {self.found}")
        return "\n".join(lines)


def entry_hash(entry: dict[str, Any]) -> str:
    """Recompute one entry's hash.

    `SHA256(canonical_json(entry without its hashes) || prev_hash)`, exactly as published.
    The entry's own `entry_hash` is excluded because it is what is being computed; its
    `prev_hash` is appended rather than included in the canonical form so the chain is
    visible in the algorithm rather than buried in the payload.
    """
    payload = {key: value for key, value in entry.items() if key not in HASH_FIELDS}
    previous = entry.get("prev_hash") or GENESIS_HASH
    return hashlib.sha256(canonical_bytes(payload) + previous.encode("ascii")).hexdigest()


def verify_chain(entries: list[dict[str, Any]]) -> Divergence | None:
    """Recompute the whole chain, returning the first divergence.

    Entries must be in `seq` order. Returns on the first problem rather than collecting
    all of them: after a break, every subsequent hash is expected to differ, and a list of
    ten thousand consequential failures obscures the one that matters.
    """
    previous_hash = GENESIS_HASH

    for entry in entries:
        seq = int(entry["seq"])

        # Gaps first: a missing entry is the subtler attack, and it makes the linkage
        # check below fail in a way that would otherwise look like an edit.
        declared_prev = entry.get("prev_hash") or GENESIS_HASH
        if declared_prev != previous_hash:
            return Divergence(
                seq=seq,
                reason="prev_hash does not match the preceding entry - an entry may have "
                "been removed or inserted",
                expected=previous_hash,
                found=declared_prev,
            )

        recomputed = entry_hash(entry)
        if recomputed != entry.get("entry_hash"):
            return Divergence(
                seq=seq,
                reason="entry_hash does not match the entry's contents - this row has "
                "been altered since it was written",
                expected=recomputed,
                found=entry.get("entry_hash"),
            )

        previous_hash = recomputed

    return None


def verify_anchors(entries: list[dict[str, Any]], anchors: list[dict[str, Any]]) -> list[str]:
    """Recompute every published daily root. Returns a problem per failing day.

    Unlike the chain, all days are reported: they are independent, and a journalist
    checking a year of anchors wants every date that fails, not the earliest.
    """
    problems: list[str] = []
    by_date: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        # The published feed carries the anchor date each entry belongs to.
        day = str(entry.get("anchor_date") or entry.get("released_at", ""))[:10]
        by_date.setdefault(day, []).append(entry)

    for record in anchors:
        anchor = Anchor(
            date=str(record["date"]),
            merkle_root=str(record["merkle_root"]),
            entry_count=int(record["entry_count"]),
            first_seq=int(record["first_seq"]),
            last_seq=int(record["last_seq"]),
            prev_anchor_hash=record.get("prev_anchor_hash"),
        )
        day_entries = sorted(by_date.get(anchor.date, []), key=lambda item: int(item["seq"]))

        if len(day_entries) != anchor.entry_count:
            problems.append(
                f"{anchor.date}: the anchor commits to {anchor.entry_count} entries, "
                f"the published feed has {len(day_entries)}"
            )
            continue

        leaves = [
            hashlib.sha256(
                canonical_bytes({k: v for k, v in item.items() if k not in HASH_FIELDS})
            ).hexdigest()
            for item in day_entries
        ]
        recomputed = merkle_root(leaves)
        if recomputed != anchor.merkle_root:
            problems.append(
                f"{anchor.date}: merkle root differs - anchored {anchor.merkle_root}, "
                f"recomputed {recomputed}"
            )

    return problems


def _load(source: str) -> Any:
    """Read JSON from a file or a URL."""
    if source.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(source, timeout=FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310 - operator-supplied public endpoint
                return json.load(response)
        except (urllib.error.URLError, TimeoutError) as error:
            raise SystemExit(f"could not fetch {source}: {error}") from error
    return json.loads(Path(source).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sarana-verify",
        description="Independently verify the SARANA aid ledger from public data.",
    )
    parser.add_argument("--feed", help="Public ledger feed: a JSON file or URL")
    parser.add_argument("--anchors", help="Published anchors: a JSON file or URL")
    parser.add_argument(
        "--base-url",
        help="A SARANA deployment; fetches /api/v1/ledger/public and /api/v1/ledger/anchors",
    )
    args = parser.parse_args(argv)

    if args.base_url:
        feed_source = f"{args.base_url.rstrip('/')}/api/v1/ledger/public"
        anchor_source = f"{args.base_url.rstrip('/')}/api/v1/ledger/anchors"
    elif args.feed and args.anchors:
        feed_source, anchor_source = args.feed, args.anchors
    else:
        parser.error("give either --base-url, or both --feed and --anchors")
        return 2

    try:
        feed = _load(feed_source)
        anchors = _load(anchor_source)
    except (OSError, json.JSONDecodeError) as error:
        sys.stderr.write(f"could not read the published data: {error}\n")
        return 2

    entries = feed["entries"] if isinstance(feed, dict) else feed
    anchor_records = anchors["anchors"] if isinstance(anchors, dict) else anchors
    entries = sorted(entries, key=lambda item: int(item["seq"]))

    sys.stdout.write(
        f"verifying {len(entries):,} ledger entries against "
        f"{len(anchor_records):,} published anchors\n\n"
    )

    divergence = verify_chain(entries)
    anchor_problems = verify_anchors(entries, anchor_records)

    if divergence is None and not anchor_problems:
        first = entries[0]["seq"] if entries else 0
        last = entries[-1]["seq"] if entries else 0
        sys.stdout.write(
            f"VERIFIED. Every entry from seq {first} to {last} hashes to its published "
            "value, the chain is unbroken, and every daily Merkle root matches its "
            "anchor.\n"
        )
        return 0

    sys.stderr.write("VERIFICATION FAILED\n\n")
    if divergence is not None:
        sys.stderr.write("The hash chain diverges:\n")
        sys.stderr.write(divergence.render() + "\n\n")
    for problem in anchor_problems:
        sys.stderr.write(f"Anchor mismatch: {problem}\n")

    sys.stderr.write(
        "\nThis means the published ledger does not match what was recorded. Quote the "
        "sequence number above when reporting it.\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
