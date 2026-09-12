"""`python -m sarana_shared.domain.i18n_check` - the Python half of `make verify-i18n`.

Walks data/seed and any service-owned locale catalogue, and fails if a citizen-facing
record is missing si, ta or en. The TypeScript half covers the web and mobile catalogues.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sarana_shared.domain.localised import check_completeness

# Field names whose values must be a complete LocalisedText wherever they appear.
LOCALISED_FIELD_SUFFIXES: tuple[str, ...] = (
    "name",
    "title",
    "headline",
    "description",
    "instruction",
    "body",
    "label",
    "message",
    "reason",
    "summary",
)

# Fields that end in a localisable suffix but are not citizen-facing content, so the rule
# must not apply to them. Two kinds:
#
#   - A person's own name. "Asiri Jayawardena" has no Sinhala and Tamil versions; demanding
#     three would mean inventing two, which is worse than leaving it in one.
#   - The name of a machine thing - an agent, a table, a file. Nobody reads these but us.
#
# Everything else ending in `name` stays covered, because a division name, a role label and
# a hazard type genuinely do reach a citizen.
NON_LOCALISED_FIELDS: frozenset[str] = frozenset(
    {
        # People
        "full_name",
        "first_name",
        "last_name",
        "given_name",
        "family_name",
        "head_name",
        "contact_name",
        "officer_name",
        # Machines
        "agent_name",
        "bus_name",
        "column_name",
        "event_name",
        "file_name",
        "host_name",
        "index_name",
        "schema_name",
        "service_name",
        "stream_name",
        "table_name",
    }
)

SKIP_DIRS = {"node_modules", ".next", ".turbo", "dist", "build", ".venv", "__pycache__"}


def _is_localised_field(key: str) -> bool:
    if key in NON_LOCALISED_FIELDS:
        return False
    return any(key == suffix or key.endswith(f"_{suffix}") for suffix in LOCALISED_FIELD_SUFFIXES)


def walk(node: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    """Yield (json_path, problem) for every incomplete localised field."""
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}"
            if _is_localised_field(key):
                result = check_completeness(value)
                if not result.complete:
                    yield child_path, result.reason
                continue
            yield from walk(value, child_path)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}[{index}]")


def check_file(path: Path) -> list[str]:
    """Return human-readable problems found in one JSON file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON - {exc}"]
    return [f"{path}: {json_path} - {reason}" for json_path, reason in walk(data)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sarana-i18n-check")
    parser.add_argument(
        "--path",
        type=Path,
        action="append",
        help="Directory to scan. Repeatable. Defaults to data/seed and data/fixtures.",
    )
    args = parser.parse_args(argv)

    roots = args.path or [Path("data/seed"), Path("data/fixtures")]
    problems: list[str] = []
    scanned = 0

    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            scanned += 1
            problems.extend(check_file(path))

    if problems:
        sys.stderr.write("i18n completeness check FAILED\n\n")
        for problem in problems:
            sys.stderr.write(f"  {problem}\n")
        sys.stderr.write(
            "\nNo citizen-facing record may exist in only one language. Fix the "
            "translation or move the record to the pending_translation queue.\n"
        )
        return 1

    sys.stdout.write(f"i18n completeness check passed ({scanned} file(s) scanned).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
