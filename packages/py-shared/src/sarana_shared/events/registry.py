"""Event-type registry and JSON Schema export.

ADR-003 keeps the proposal's schema contracts but expresses them as Pydantic models with
a JSON Schema export and a CI compatibility check, rather than Avro in a schema registry.

Registration is by decorator at import time:

    @register("sarana.incident.report.received", version=1)
    class ReportReceived(BaseModel):
        ...
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from sarana_shared.events.envelope import EVENT_TYPE_PATTERN, EventEnvelope

ModelT = TypeVar("ModelT", bound=BaseModel)

# (event_type, schema_version) -> payload model
_REGISTRY: dict[tuple[str, int], type[BaseModel]] = {}


class UnknownEventType(KeyError):
    """No payload model is registered for this event type and version."""


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
        UnknownEventType: if nothing is registered. Consumers that only forward or
            archive events should not call this.
    """
    try:
        return _REGISTRY[(event_type, version)]
    except KeyError as exc:
        raise UnknownEventType(f"no payload model for {event_type} v{version}") from exc


def parse_payload(envelope: EventEnvelope) -> BaseModel:
    """Validate an envelope payload against its registered model."""
    return payload_model(envelope.type, envelope.schema_version).model_validate(envelope.payload)


def registered_types() -> list[tuple[str, int]]:
    """Every registered (type, version) pair, sorted. Used by the CI contract check."""
    return sorted(_REGISTRY)


def export_json_schemas() -> dict[str, Any]:
    """Build the machine-readable event catalogue.

    CI compares this against the committed copy and fails a PR that removes a field or
    narrows a type without a version bump.
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
