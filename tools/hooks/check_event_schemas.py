#!/usr/bin/env python3
"""Fail if the event contracts changed in a way that breaks a running consumer.

Run by CI and by pre-commit. Exports the current JSON Schema for every event and compares
it against the committed snapshot in `data/contracts/events.json`.

Events outlive the code that wrote them. An envelope sitting in the outbox during a deploy
was serialised by the old version and will be read by the new one, and a replay reads
envelopes that are weeks old. So a contract change that looks harmless in a pull request
can break a consumer that is already running.

`--update` rewrites the snapshot, which is how an intended change is accepted: the diff
lands in the pull request where a reviewer can see it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO_ROOT / "data" / "contracts" / "events.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sarana-event-schema-check")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Rewrite the snapshot to match the current contracts.",
    )
    args = parser.parse_args(argv)

    # Imported late so the argument parsing above works without the package installed.
    sys.path.insert(0, str(REPO_ROOT / "packages" / "py-shared" / "src"))
    from sarana_shared.events import payloads  # noqa: F401 - registers every model
    from sarana_shared.events.catalogue import ALL_EVENT_TYPES
    from sarana_shared.events.registry import (
        SchemaIncompatible,
        assert_compatible,
        export_json_schemas,
        registered_types,
    )

    current = export_json_schemas()

    registered = {event_type for event_type, _ in registered_types()}
    undeclared = registered - set(ALL_EVENT_TYPES)
    uncontracted = set(ALL_EVENT_TYPES) - registered
    if undeclared or uncontracted:
        sys.stderr.write("event catalogue and contracts disagree\n\n")
        for name in sorted(uncontracted):
            sys.stderr.write(f"  {name}: catalogued but has no payload model\n")
        for name in sorted(undeclared):
            sys.stderr.write(f"  {name}: has a payload model but is not catalogued\n")
        return 1

    if args.update or not SNAPSHOT.exists():
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        action = "updated" if args.update else "created"
        sys.stdout.write(f"event contract snapshot {action}: {SNAPSHOT}\n")
        return 0

    previous = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    try:
        assert_compatible(previous, current)
    except SchemaIncompatible as exc:
        sys.stderr.write(f"{exc}\n\n")
        sys.stderr.write(
            "If the change is intended, bump schema_version on the affected events and "
            "run:\n  python tools/hooks/check_event_schemas.py --update\n"
        )
        return 1

    if previous != current:
        SNAPSHOT.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        sys.stdout.write(
            "event contracts changed compatibly; snapshot refreshed. "
            "Commit the updated data/contracts/events.json.\n"
        )
        return 0

    sys.stdout.write(f"event contracts unchanged ({len(current['events'])} events).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
