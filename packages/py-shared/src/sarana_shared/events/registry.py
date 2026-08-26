"""Event-type -> Pydantic payload model registry, with JSON Schema export for CI's
schema-diff check (docs/build-prompts/06-event-bus.md, "Schema evolution rules").

This file owns the *mechanism* and the full *catalogue of event-type names*. The actual
payload models are registered by the service/agent that owns each event, in the file
that builds that event (08-incident-service.md, 09-alerting-service.md, etc.) — defining
them here would be business logic, which is explicitly out of scope for the scaffold
(docs/build-prompts/03-monorepo-scaffold.md).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class EventRegistryError(ValueError):
    pass


class _Registry:
    def __init__(self) -> None:
        self._models: dict[str, type[BaseModel]] = {}

    def register(self, event_type: str) -> Any:
        """Decorator: @registry.register("sarana.incident.report.received")"""

        def decorator(model_cls: type[BaseModel]) -> type[BaseModel]:
            if event_type in self._models and self._models[event_type] is not model_cls:
                raise EventRegistryError(
                    f"{event_type!r} is already registered to {self._models[event_type]!r}"
                )
            self._models[event_type] = model_cls
            return model_cls

        return decorator

    def model_for(self, event_type: str) -> type[BaseModel]:
        try:
            return self._models[event_type]
        except KeyError as exc:
            raise EventRegistryError(f"No payload model registered for {event_type!r}") from exc

    def is_registered(self, event_type: str) -> bool:
        return event_type in self._models

    def json_schema_for(self, event_type: str) -> dict[str, Any]:
        return self.model_for(event_type).model_json_schema()

    def export_all_json_schemas(self) -> dict[str, dict[str, Any]]:
        """Used by the CI job that diffs every event's schema against the previous
        commit and fails on a backward-incompatible change without a version bump."""
        return {et: model.model_json_schema() for et, model in self._models.items()}


registry = _Registry()


# ---------------------------------------------------------------------------
# The full event catalogue (docs/build-prompts/06-event-bus.md).
# Names only here — each is registered with its Pydantic payload model in the file
# that owns it. Grouped by the loop/service that publishes it.
# ---------------------------------------------------------------------------

HAZARD_EVENTS = (
    "sarana.hazard.event.declared",
    "sarana.hazard.reading.ingested",
    "sarana.forecast.impact.generated",
    "sarana.forecast.trigger.fired",
)

ALERT_EVENTS = (
    "sarana.alert.drafted",
    "sarana.alert.signoff.requested",
    "sarana.alert.signoff.granted",
    "sarana.alert.dispatched",
    "sarana.alert.delivery.confirmed",
    "sarana.alert.delivery.failed",
)

INCIDENT_EVENTS = (
    "sarana.incident.report.received",
    "sarana.incident.report.transcribed",
    "sarana.incident.report.flagged_for_review",
    "sarana.incident.verified",
    "sarana.incident.duplicate.linked",
    "sarana.incident.triaged",
    "sarana.dispatch.plan.proposed",
    "sarana.dispatch.signoff.requested",
    "sarana.dispatch.signoff.granted",
    "sarana.dispatch.signoff.rejected",
    "sarana.dispatch.released",
    "sarana.incident.resolved",
)

AID_EVENTS = (
    "sarana.aid.assessment.submitted",
    "sarana.aid.entitlement.calculated",
    "sarana.aid.approval.recorded",
    "sarana.aid.disbursement.released",
    "sarana.aid.disbursement.citizen_confirmed",
    "sarana.aid.anomaly.flagged",
    "sarana.aid.anomaly.disposed",
    "sarana.aid.grievance.raised",
    "sarana.aid.grievance.resolved",
)

PLATFORM_EVENTS = (
    "sarana.resilience.observation.appended",
    "sarana.audit.entry.written",
)

ALL_EVENT_TYPES: tuple[str, ...] = (
    HAZARD_EVENTS + ALERT_EVENTS + INCIDENT_EVENTS + AID_EVENTS + PLATFORM_EVENTS
)
