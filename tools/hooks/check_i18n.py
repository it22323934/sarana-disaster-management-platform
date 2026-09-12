#!/usr/bin/env python3
"""Fail the commit if any locale catalogue is missing a key in si, ta or en.

Non-negotiable #2 in the master context: no citizen-facing record may exist in only
one language. This script is the commit-time half of that guarantee; CI runs the same
check over the whole tree. Stdlib only, so pre-commit can run it with `language: system`.

A locale catalogue is a directory containing `si.json`, `ta.json` and `en.json`. Keys are
compared as flattened dotted paths, so a nested object missing one leaf is caught.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

REQUIRED_LOCALES = ("si", "ta", "en")
SEARCH_ROOTS = ("packages", "apps", "data", "services")
SKIP_DIRS = {"node_modules", ".next", ".turbo", "dist", "build", ".venv", "__pycache__"}


def flatten(obj: object, prefix: str = "") -> Iterator[str]:
    """Yield dotted key paths for every leaf value in a nested JSON object."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from flatten(value, path)
    else:
        yield prefix


def find_catalogue_dirs(root: Path) -> Iterator[Path]:
    """Yield every directory holding at least one `{locale}.json` file."""
    seen: set[Path] = set()
    for candidate in root.rglob("*.json"):
        if any(part in SKIP_DIRS for part in candidate.parts):
            continue
        if candidate.stem not in REQUIRED_LOCALES:
            continue
        if candidate.parent not in seen:
            seen.add(candidate.parent)
            yield candidate.parent


def check_catalogue(directory: Path) -> list[str]:
    """Return a list of human-readable problems for one catalogue directory."""
    problems: list[str] = []
    keys_by_locale: dict[str, set[str]] = {}

    for locale in REQUIRED_LOCALES:
        path = directory / f"{locale}.json"
        if not path.exists():
            problems.append(f"{directory}: missing {locale}.json entirely")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"{path}: invalid JSON - {exc}")
            continue
        keys_by_locale[locale] = set(flatten(data))

        empty = sorted(k for k in flatten_empty(data))
        for key in empty:
            problems.append(f"{path}: key '{key}' is present but empty")

    if len(keys_by_locale) == len(REQUIRED_LOCALES):
        union = set().union(*keys_by_locale.values())
        for locale, keys in sorted(keys_by_locale.items()):
            for key in sorted(union - keys):
                problems.append(f"{directory / f'{locale}.json'}: missing key '{key}'")

    return problems


def flatten_empty(obj: object, prefix: str = "") -> Iterator[str]:
    """Yield dotted paths whose leaf value is an empty or whitespace-only string."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from flatten_empty(value, path)
    elif isinstance(obj, str) and not obj.strip():
        yield prefix


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    problems: list[str] = []
    checked = 0

    for root_name in SEARCH_ROOTS:
        root = repo_root / root_name
        if not root.exists():
            continue
        for directory in find_catalogue_dirs(root):
            checked += 1
            problems.extend(check_catalogue(directory))

    if problems:
        sys.stderr.write("i18n completeness check FAILED\n\n")
        for problem in problems:
            sys.stderr.write(f"  {problem}\n")
        sys.stderr.write(
            "\nEvery citizen-facing string must exist in si, ta and en. "
            "If a translation is not ready, the record does not ship - it goes to the "
            "pending_translation queue.\n"
        )
        return 1

    sys.stdout.write(f"i18n completeness check passed ({checked} catalogue(s)).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
