from sarana_shared.auth.scopes import Scope, any_scope_satisfies, scope_satisfies


def test_national_scope_satisfies_any_narrower_target() -> None:
    granted = Scope(resource="ledger", action="read", scope_type="NATIONAL", scope_id=None)
    assert scope_satisfies(
        granted,
        resource="ledger",
        action="read",
        target_scope_type="GN",
        target_scope_id="gn-1",
    )


def test_district_scope_satisfies_its_gn_descendant() -> None:
    granted = Scope(resource="assessment", action="read", scope_type="DISTRICT", scope_id="LK-21")
    assert scope_satisfies(
        granted,
        resource="assessment",
        action="read",
        target_scope_type="GN",
        target_scope_id="LK-21-05-014",
        target_ancestor_ids=frozenset({"LK-21-05", "LK-21"}),
    )


def test_district_scope_does_not_satisfy_a_different_district() -> None:
    granted = Scope(resource="assessment", action="read", scope_type="DISTRICT", scope_id="LK-21")
    assert not scope_satisfies(
        granted,
        resource="assessment",
        action="read",
        target_scope_type="GN",
        target_scope_id="LK-07-02-009",
        target_ancestor_ids=frozenset({"LK-07-02", "LK-07"}),
    )


def test_scope_never_inherits_upward() -> None:
    """A GN officer never gains DS rights — docs/build-prompts/05-auth-rbac.md."""
    granted = Scope(
        resource="entitlement", action="approve", scope_type="GN", scope_id="LK-21-05-014"
    )
    assert not scope_satisfies(
        granted,
        resource="entitlement",
        action="approve",
        target_scope_type="DS",
        target_scope_id="LK-21-05",
    )


def test_resource_or_action_mismatch_never_matches() -> None:
    granted = Scope(
        resource="assessment", action="create", scope_type="GN", scope_id="LK-21-05-014"
    )
    assert not scope_satisfies(
        granted,
        resource="assessment",
        action="approve",  # different action
        target_scope_type="GN",
        target_scope_id="LK-21-05-014",
    )


def test_scope_str_and_parse_round_trip() -> None:
    original = Scope(resource="ledger", action="read", scope_type="NATIONAL", scope_id=None)
    assert str(original) == "ledger:read:NATIONAL:*"
    assert Scope.parse(str(original)) == original

    narrow = Scope(resource="assessment", action="create", scope_type="GN", scope_id="LK-21-05-014")
    assert str(narrow) == "assessment:create:GN:LK-21-05-014"
    assert Scope.parse(str(narrow)) == narrow


def test_any_scope_satisfies_checks_the_whole_grant_list() -> None:
    grants = [
        Scope(resource="assessment", action="create", scope_type="GN", scope_id="LK-21-05-014"),
        Scope(resource="ledger", action="read", scope_type="DISTRICT", scope_id="LK-21"),
    ]
    assert any_scope_satisfies(
        grants,
        resource="ledger",
        action="read",
        target_scope_type="GN",
        target_scope_id="LK-21-05-014",
        target_ancestor_ids=frozenset({"LK-21-05", "LK-21"}),
    )
    assert not any_scope_satisfies(
        grants,
        resource="entitlement",
        action="approve",
        target_scope_type="GN",
        target_scope_id="LK-21-05-014",
    )
