"""Event contracts outlive the code that wrote them.

An envelope sitting in the outbox during a deploy was serialised by the old version and
will be read by the new one. A replay reads envelopes that are weeks old. So a contract
change that looks harmless in a pull request can break a consumer that is already running,
or fail every event already in the archive.

CI exports the JSON Schema for every event and diffs it against the committed copy. These
tests are that check, and the fifth required case - adding a required field to an existing
version must fail the build.
"""

from __future__ import annotations

import pytest

from sarana_shared.events import payloads  # noqa: F401 - importing registers the models
from sarana_shared.events.catalogue import ALL_EVENT_TYPES
from sarana_shared.events.registry import (
    SchemaIncompatible,
    assert_compatible,
    check_compatibility,
    export_json_schemas,
    registered_types,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


def catalogue_with(properties: dict[str, object], required: list[str]) -> dict[str, object]:
    """A one-event catalogue, for exercising the comparison directly."""
    return {
        "envelope": {},
        "events": {
            "sarana.aid.entitlement.calculated/v1": {
                "properties": properties,
                "required": required,
            }
        },
    }


async def test_every_catalogued_event_has_a_contract() -> None:
    """A type nobody declared a payload for cannot be consumed or replayed."""
    registered = {event_type for event_type, _ in registered_types()}

    assert set(ALL_EVENT_TYPES) - registered == set()


async def test_every_contract_is_in_the_catalogue() -> None:
    """And the reverse: nothing publishes a type the catalogue does not list."""
    registered = {event_type for event_type, _ in registered_types()}

    assert registered - set(ALL_EVENT_TYPES) == set()


async def test_adding_an_optional_field_is_allowed() -> None:
    """The intended way to evolve a contract without a version bump."""
    previous = catalogue_with({"amount": {"type": "integer"}}, ["amount"])
    current = catalogue_with(
        {"amount": {"type": "integer"}, "note": {"type": "string"}}, ["amount"]
    )

    assert check_compatibility(previous, current) == []


async def test_adding_a_required_field_fails() -> None:
    """The fifth required case.

    Every event already in an outbox or an archive was written without the field, so
    replaying any of them would fail validation.
    """
    previous = catalogue_with({"amount": {"type": "integer"}}, ["amount"])
    current = catalogue_with(
        {"amount": {"type": "integer"}, "schedule": {"type": "string"}},
        ["amount", "schedule"],
    )

    problems = check_compatibility(previous, current)

    assert len(problems) == 1
    assert problems[0].field == "schedule"
    assert "already in an outbox or archive" in problems[0].reason


async def test_removing_a_field_fails() -> None:
    previous = catalogue_with(
        {"amount": {"type": "integer"}, "schedule": {"type": "string"}}, ["amount"]
    )
    current = catalogue_with({"amount": {"type": "integer"}}, ["amount"])

    problems = check_compatibility(previous, current)

    assert [p.field for p in problems] == ["schedule"]
    assert "bump schema_version" in problems[0].reason


async def test_retyping_a_field_fails() -> None:
    """Worse than a removal: the consumer parses it and gets the wrong thing."""
    previous = catalogue_with({"amount": {"type": "integer"}}, ["amount"])
    current = catalogue_with({"amount": {"type": "string"}}, ["amount"])

    problems = check_compatibility(previous, current)

    assert [p.field for p in problems] == ["amount"]
    assert "retyped" in problems[0].reason


async def test_removing_a_whole_event_fails() -> None:
    """Consumers subscribed to it would never hear anything again."""
    previous = catalogue_with({"amount": {"type": "integer"}}, ["amount"])
    current: dict[str, object] = {"envelope": {}, "events": {}}

    problems = check_compatibility(previous, current)

    assert problems[0].field == "*"


async def test_the_assertion_reports_every_problem_at_once() -> None:
    """One CI run should surface all of them, not one per push."""
    previous = catalogue_with(
        {"amount": {"type": "integer"}, "schedule": {"type": "string"}}, ["amount"]
    )
    current = catalogue_with({"amount": {"type": "string"}}, ["amount"])

    with pytest.raises(SchemaIncompatible) as caught:
        assert_compatible(previous, current)

    assert "2 backward-incompatible change" in str(caught.value)


async def test_the_live_catalogue_is_self_consistent() -> None:
    """The real export, compared against itself, must be clean."""
    catalogue = export_json_schemas()

    assert check_compatibility(catalogue, catalogue) == []
    assert len(catalogue["events"]) == len(ALL_EVENT_TYPES)
