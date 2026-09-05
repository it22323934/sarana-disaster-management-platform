"""The scope names the web console uses, checked against the scopes the platform issues.

A cross-language vocabulary test, in the same spirit as `tests/incident/test_vocabularies.py`.
The console filters its navigation by scope, and a scope string it invents rather than
holds fails **silently**: `principal.scopes.includes('admin:write')` is simply false for
everybody, the link never renders, and the screen behind it becomes unreachable from the
navigation while remaining perfectly functional at its URL. Nothing errors and nothing logs.

That is exactly what had happened, in two separate tables. `/approvals` was gated on
`entitlement:approve` and `/admin` on `admin:write`, and neither is a scope this platform
has ever defined - the real ones are `entitlement:approve_ds`, `entitlement:approve_district`
and `system:admin`. Two finished screens were invisible to every user who could have used
them. The **landing redirect** carried the same phantom `entitlement:approve`, so a DS
approver signing in fell through to the next matching row and arrived on the operator's map
instead of on the queue holding their signature.

TypeScript cannot import the Python enum, so the check runs from this side: parse both
tables out of the console's source and assert every scope in them is real.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sarana_shared.auth.scopes import ROLE_SCOPES, Role, Scope

REPO_ROOT = Path(__file__).resolve().parents[2]
CONSOLE = REPO_ROOT / "apps" / "web-ops"
APP_SHELL = CONSOLE / "src" / "components" / "app-shell.tsx"
# The root page decides where each role lands after sign-in, from the same vocabulary.
LANDING_PAGE = CONSOLE / "app" / "[locale]" / "page.tsx"

# `scopes: ['a', 'b']` on a NavItem. Any-of: an approver holds the DS scope or the District
# one and rarely both, and a link that required both would hide from most of the people who
# need it.
_NAV_ENTRY = re.compile(r"\{\s*href:\s*'(?P<href>[^']+)'[^}]*?\}", re.DOTALL)
_SCOPES = re.compile(r"scopes:\s*\[(?P<list>[^\]]*)\]")
_QUOTED = re.compile(r"'([^']+)'")


def nav_entries() -> list[tuple[str, list[str]]]:
    """Every navigation entry in the console shell, as (href, scopes)."""
    source = APP_SHELL.read_text(encoding="utf-8")
    table = source.split("const NAV", 1)[1].split("];", 1)[0]
    entries: list[tuple[str, list[str]]] = []
    for match in _NAV_ENTRY.finditer(table):
        scopes_match = _SCOPES.search(match.group(0))
        scopes = _QUOTED.findall(scopes_match.group("list")) if scopes_match else []
        entries.append((match.group("href"), scopes))
    return entries


def landing_scopes() -> list[tuple[str, str]]:
    """Every (scope, route) pair in the root page's landing table."""
    source = LANDING_PAGE.read_text(encoding="utf-8")
    table = source.split("const LANDING", 1)[1].split("];", 1)[0]
    return [
        (match.group(1), match.group(2))
        for match in re.finditer(r"\[\s*'([^']+)'\s*,\s*'([^']+)'\s*\]", table)
    ]


ALL_SCOPES = {scope.value for scope in Scope}


def test_the_navigation_table_was_found() -> None:
    """A parse that silently found nothing would make every test below vacuous."""
    entries = nav_entries()
    assert len(entries) >= 12, entries
    assert any(href == "/ops" for href, _ in entries)


@pytest.mark.parametrize("href,scopes", nav_entries())
def test_every_console_navigation_scope_is_a_scope_this_platform_issues(
    href: str, scopes: list[str]
) -> None:
    """A scope the console names and the platform does not is a screen nobody can reach.

    It fails silently, which is why this test exists rather than a code review note: the
    console renders, the user signs in, and one navigation item is simply absent.
    """
    unknown = [scope for scope in scopes if scope not in ALL_SCOPES]
    assert not unknown, (
        f"{href} is gated on {unknown}, which no role can hold. "
        f"Did you mean one of: {sorted(ALL_SCOPES)}"
    )


@pytest.mark.parametrize("href,scopes", nav_entries())
def test_every_console_navigation_scope_is_held_by_at_least_one_human_role(
    href: str, scopes: list[str]
) -> None:
    """A real scope that only machines hold is the same failure with a subtler cause.

    `AGENT` and `SERVICE` are excluded: a link only an agent could see is a link nobody
    sees, because agents do not use a browser.
    """
    human_roles = [role for role in Role if role not in (Role.AGENT, Role.SERVICE)]
    reachable = {scope.value for role in human_roles for scope in ROLE_SCOPES[role]}
    orphaned = [scope for scope in scopes if scope in ALL_SCOPES and scope not in reachable]
    assert not orphaned, f"{href} is gated on {orphaned}, which no human role holds"


def test_the_two_screens_that_were_unreachable_are_gated_on_scopes_that_exist() -> None:
    """Named individually because these two are the reason this file exists.

    `/approvals` and `/admin` were both built, tested and invisible. Regressing either is
    the specific failure this suite is here to stop, so it is asserted by name rather than
    only by the parametrised sweep above.
    """
    table = dict(nav_entries())
    assert set(table["/approvals"]) <= ALL_SCOPES
    assert table["/approvals"], "/approvals must name the scopes that make it useful"
    assert set(table["/admin"]) <= ALL_SCOPES
    assert Scope.SYSTEM_ADMIN.value in table["/admin"]


def test_the_landing_table_was_found() -> None:
    """A parse that silently found nothing would make the test below vacuous."""
    pairs = landing_scopes()
    assert len(pairs) >= 5, pairs
    assert any(route == "/ops" for _scope, route in pairs)


@pytest.mark.parametrize("scope,route", landing_scopes())
def test_every_landing_scope_is_a_scope_this_platform_issues(scope: str, route: str) -> None:
    """A phantom scope here sends a role to the wrong screen, silently.

    It does not error and it does not log: the row simply never matches, the loop falls
    through to the next one, and the user lands somewhere plausible. An approver who arrives
    on the operator's map has to navigate before they can do the one thing they signed in
    for, and during an incident that is a real cost.
    """
    assert scope in ALL_SCOPES, (
        f"the landing table sends {scope!r} to {route}, and no role can hold that scope"
    )


def test_both_approval_levels_land_on_the_approvals_queue() -> None:
    """DS and District approvers each hold one of two scopes, and rarely both.

    Naming only one would leave the other falling through to whatever matched next.
    """
    table = dict(landing_scopes())
    assert table[Scope.ENTITLEMENT_APPROVE_DS.value] == "/approvals"
    assert table[Scope.ENTITLEMENT_APPROVE_DISTRICT.value] == "/approvals"
