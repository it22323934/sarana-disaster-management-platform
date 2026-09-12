"""Vocabularies the console duplicates, checked against the ones the services enforce.

Same rule as `tests/incident/test_vocabularies.py`, across the language boundary. The
console cannot import a Python tuple, so a copy of a vocabulary lives in TypeScript and
this test is what stops the copy drifting.

The failure a drifted copy produces is not a type error and not a lint failure. It is a
400 on an action a user has already committed to: a GN officer picks a damage category
from a dropdown, presses the button, and the service rejects a value the console offered.
That is the worst place to discover a vocabulary mismatch, and it is exactly what happened
to the incident types twice during development before those tests existed.
"""

from __future__ import annotations

import re
from pathlib import Path

from sarana_shared.domain.taxonomy import DAMAGE_CATEGORIES

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "apps" / "web-ops" / "src" / "lib" / "schemas.ts"

_QUOTED = re.compile(r"'([A-Z_]+)'")


def console_array(name: str) -> list[str]:
    """The string literals in an exported `const NAME = [...] as const` array."""
    source = SCHEMAS.read_text(encoding="utf-8")
    body = source.split(f"export const {name} = [", 1)[1].split("]", 1)[0]
    return _QUOTED.findall(body)


def test_the_console_offers_exactly_the_damage_categories_the_service_accepts() -> None:
    """A category the console offers and `ledger-svc` rejects is a 400 on a filed claim.

    Both directions matter. An extra one in the console is a dropdown entry that fails on
    submit; a missing one is a category a GN officer cannot file at all, which quietly
    routes real damage into whatever nearest option they pick instead.
    """
    assert console_array("DAMAGE_CATEGORIES") == list(DAMAGE_CATEGORIES)


def test_the_console_offers_the_two_approval_levels_the_service_accepts() -> None:
    """DS and DISTRICT. A third would be a signature the gate has no threshold for."""
    assert console_array("APPROVAL_LEVELS") == ["DS", "DISTRICT"]


def test_the_console_scope_types_match_the_database_check() -> None:
    """`admin.user_role.scope_type` is constrained to exactly these four.

    The console offers them in the role-grant dialogue, and it also validates the *shape*
    of the code against the level before submitting. Both are conveniences - the database
    CHECK `scope_code_matches_type` is the authority - but a level the console offers and
    the constraint refuses produces a failure at the write rather than in the form.
    """
    assert set(console_array("SCOPE_TYPES")) == {"NATIONAL", "DISTRICT", "DS", "GN"}
