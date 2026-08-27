"""Event payload contracts, and the rules for changing them.

ADR-003 keeps the proposal's schema contracts but expresses them as Pydantic models with a
JSON Schema export and a CI compatibility check, rather than Avro in a schema registry.

**The evolution rules, enforced by `check_compatibility` in CI:**

  - Additive-only within a `schema_version`. A new field must be optional. A removed field
    or a retyped field is a breaking change.
  - A breaking change means a new `schema_version`, and a consumer that handles both for
    one release cycle.

The reason these are strict is that events outlive the code that wrote them. An envelope
sitting in the outbox during a deploy was serialised by the old version and will be read
by the new one, and a replay reads envelopes that are weeks old.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from sarana_shared.events.envelope import EVENT_TYPE_PATTERN, EventEnvelope

ModelT = TypeVar("ModelT", bound=BaseModel)

# (event_type, schema_version) -> payload model
_REGISTRY: dict[tuple[str, int], type[BaseModel]] = {}


class UnknownEventType(KeyError):
    """No payload model is registered for this event type and version."""


class SchemaIncompatible(Exception):
    """A payload contract changed in a way that would break an existing consumer."""


def register(event_type: str, *, version: int = 1) -> Callable[[type[ModelT]], type[ModelT]]:
    """Bind a payload model to an event type. Raises on a duplicate registration."""
    if not EVENT_TYPE_PATTERN.match(event_type):
        raise ValueError(f"invalid event type: {event_type!r}")

    def decorator(model: type[ModelT]) -> type[ModelT]:
        key = (event_type, version)
        existing = _REGISTRY.get(key)
        if existing is not None and existing is not model:
            raise ValueError(
                f"{event_type} v{version} is already registered to {existing.__name__}"
            )
        _REGISTRY[key] = model
        return model

    return decorator


def payload_model(event_type: str, version: int = 1) -> type[BaseModel]:
    """Return the payload model for an event type.

    Raises:
        UnknownEventType: if nothing is registered. Consumers that only forward, archive
            or replay events should not call this.
    """
    try:
        return _REGISTRY[(event_type, version)]
    except KeyError as exc:
        raise UnknownEventType(f"no payload model for {event_type} v{version}") from exc


def parse_payload(envelope: EventEnvelope) -> BaseModel:
    """Validate an envelope payload against its registered model."""
    return payload_model(envelope.event_type, envelope.schema_version).model_validate(
        envelope.payload
    )


def registered_types() -> list[tuple[str, int]]:
    """Every registered (type, version) pair, sorted. Used by the CI contract check."""
    return sorted(_REGISTRY)


def export_json_schemas() -> dict[str, Any]:
    """Build the machine-readable event catalogue.

    CI compares this against the committed copy and fails a pull request that removes a
    field, retypes one, or adds a required field without bumping the version.
    """
    return {
        "envelope": EventEnvelope.model_json_schema(),
        "events": {
            f"{event_type}/v{version}": model.model_json_schema()
            for (event_type, version), model in sorted(_REGISTRY.items())
        },
    }


def write_json_schemas(path: Path) -> Path:
    """Write the catalogue to disk, stable-sorted so diffs are readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(export_json_schemas(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


@dataclass(frozen=True, slots=True)
class Incompatibility:
    """One way a payload contract changed that would break an existing consumer."""

    event: str
    field: str
    reason: str

    def __str__(self) -> str:
        return f"{self.event}: {self.field} - {self.reason}"


def _field_types(schema: dict[str, Any]) -> dict[str, Any]:
    """The declared type of every property, ignoring description and title churn."""
    properties = schema.get("properties", {})
    return {
        name: {key: value for key, value in spec.items() if key in ("type", "$ref", "anyOf")}
        for name, spec in properties.items()
    }


def check_compatibility(
    previous: dict[str, Any], current: dict[str, Any]
) -> list[Incompatibility]:
    """Compare two exported catalogues and report breaking changes.

    Three things break a consumer that is already running:

      - A field disappears. Anything reading it now gets a KeyError on old and new data
        alike, because the consumer was written against the field.
      - A field changes type. The consumer parses it and gets the wrong thing, which is
        worse than failing.
      - A required field appears. Every event already sitting in an outbox or an archive
        was serialised without it, so replaying them all fails validation.

    Adding an optional field is fine, and is the intended way to evolve a contract
    without a version bump.
    """
    problems: list[Incompatibility] = []
    previous_events = previous.get("events", {})
    current_events = current.get("events", {})

    for name, old_schema in previous_events.items():
        new_schema = current_events.get(name)
        if new_schema is None:
            problems.append(
                Incompatibility(
                    event=name,
                    field="*",
                    reason=(
                        "the whole event was removed; consumers subscribed to it will "
                        "never hear anything again"
                    ),
                )
            )
            continue

        old_fields = _field_types(old_schema)
        new_fields = _field_types(new_schema)

        for field, old_type in old_fields.items():
            if field not in new_fields:
                problems.append(
                    Incompatibility(name, field, "removed; bump schema_version instead")
                )
            elif new_fields[field] != old_type:
                problems.append(
                    Incompatibility(
                        name,
                        field,
                        f"retyped from {old_type} to {new_fields[field]}; "
                        "bump schema_version instead",
                    )
                )

        old_required = set(old_schema.get("required", []))
        for field in set(new_schema.get("required", [])) - old_required:
            problems.append(
                Incompatibility(
                    name,
                    field,
                    "added as required; every event already in an outbox or archive was "
                    "written without it. Make it optional, or bump schema_version.",
                )
            )

    return problems


def assert_compatible(previous: dict[str, Any], current: dict[str, Any]) -> None:
    """Raise if the current catalogue breaks the previous one.

    Raises:
        SchemaIncompatible: listing every problem, so one CI run reports all of them
            rather than one per push.
    """
    problems = check_compatibility(previous, current)
    if problems:
        detail = "\n".join(f"  {problem}" for problem in problems)
        raise SchemaIncompatible(
            f"{len(problems)} backward-incompatible change(s) to the event contracts:\n"
            f"{detail}\n\n"
            "Events outlive the code that wrote them. An envelope sitting in the outbox "
            "during a deploy was serialised by the old version and will be read by the "
            "new one."
        )
