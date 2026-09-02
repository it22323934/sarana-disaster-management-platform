r"""The aid ledger and anomaly agent.

```
START -> receive_batch -> aggregate -> normalise_by_exposure -> detect_anomalies
      -> contextualise -> suppress_explained -> raise_flags -> record -> END
```

**Read ADR-009 before changing anything in this package.** This is the agent with the
highest potential to do harm, and the harm is not technical: a flag against a GN officer can
end a career on a statistical artifact, and the divisions that were genuinely hit hardest
will legitimately look like outliers. That is the damage speaking, not the officer.

## Four hard boundaries, and where each one is enforced

**It does not calculate entitlements.** That is deterministic code in ledger-svc. This agent
reads results and explains them. There is no port here through which a value could be
computed — an LLM anywhere near a money calculation is an unacceptable design, and the way
to guarantee it is to have nothing to call.

**It never releases money.** The disbursement gate is human, always. There is no
disbursement port in this package.

**A flag is not a finding.** Every output says a pattern warrants review.
`redaction.check` enforces the language on every string at any depth, and the database
rejects a rationale containing a user id behind it.

**No output names an individual, and officer identity is not a feature.** `Assessment`
carries no assessor, approver or user field, so no detector can group by person even by
accident. The proxy is the trap and it is closed too: the unit of analysis is the GN
division per day, everywhere.

## The step that makes the whole thing defensible

`normalise_by_exposure`. Every detector compares a division against **its own impact
forecast**, never against its peers. A division at impact class 4 producing high-value
assessments is expected behaviour and produces nothing. The same profile at impact class 1
is a question.

An unsurveyed division is suppressed rather than compared, which makes this agent blind in
unwarned districts. That is the correct trade — see `normalisation`.

## The useful, non-scary half

`aggregate` produces the sector figures the public dashboard runs on: assessments and
entitlements by area and category, budget against calculated against disbursed, median times.
Those are anonymised and minimum-cell-suppressed. Flags never appear publicly in any form,
aggregated or otherwise; what appears is the count of audits conducted and their outcomes.
Process transparency, not accusation transparency.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final

import structlog
from langgraph.graph import END, START, StateGraph

from agent_svc.agents.ledger_anomaly import aggregation, detectors
from agent_svc.agents.ledger_anomaly import context as context_rules
from agent_svc.agents.ledger_anomaly import normalisation as norm
from agent_svc.agents.ledger_anomaly.ports import (
    Assessment,
    AssessmentSource,
    DivisionContext,
    ExposureSource,
    Flag,
    FlagStore,
    ModelCall,
    Signal,
)
from agent_svc.runtime.nodes import audit_write, rg_append
from agent_svc.runtime.registry import AgentSpec
from agent_svc.runtime.state import AgentState
from sarana_shared.domain.time import utc_now

_log = structlog.get_logger(__name__)

AGENT: Final = "ledger_anomaly"
SUBJECT_TYPE: Final = "assessment_batch"

# What a flag is raised against. Always the division, never a person - the column's
# vocabulary allows ASSESSMENT and others, and this agent uses GN_DIVISION because that is
# the unit ADR-009 permits.
FLAG_SUBJECT: Final = "GN_DIVISION"

# Below this score a signal is not worth a reviewer's time. Set where it is because a
# review queue that includes marginal departures from a rule-threshold forecast is one
# people close without reading, and a queue people skim is worse than no queue: it looks
# like oversight.
MIN_SCORE: Final = 0.25


class AnomalyState(AgentState, total=False):
    """The run's own state.

    Carries divisions, counts and signals. **No assessor, no approver, no household id**
    beyond what a detector needed, and no citizen's name anywhere - a checkpoint outlives
    the run and is read during debugging.
    """

    district_code: str | None
    assessments: list[dict[str, Any]]
    division_context: dict[str, dict[str, Any]]
    aggregates: dict[str, Any]
    signals: list[dict[str, Any]]
    suppressed: Annotated[list[dict[str, Any]], list.__add__]
    flags: list[dict[str, Any]]
    raised: int


def build_nodes(
    *,
    assessments: AssessmentSource,
    exposure: ExposureSource,
    store: FlagStore,
    call: ModelCall | None = None,
    now: datetime | None = None,
    min_score: float = MIN_SCORE,
    audit: Any = None,
    graph_writer: Any = None,
) -> dict[str, Any]:
    """Build the nodes, closed over their dependencies."""

    def clock() -> datetime:
        return now if now is not None else utc_now()

    async def receive_batch(state: AnomalyState) -> dict[str, Any]:
        """Read the assessments in scope. The only node that reads the ledger."""
        raw = dict(state.get("output", {}))
        district = raw.get("district_code")
        since = raw.get("since")

        batch = await assessments.batch(
            district_code=district,
            since=datetime.fromisoformat(since) if isinstance(since, str) else since,
        )
        _log.info(
            "anomaly_batch_received",
            district=district,
            assessments=len(batch),
            divisions=len({item.gn_division_code for item in batch}),
        )
        return {
            "district_code": district,
            "assessments": [_assessment_as_dict(item) for item in batch],
            "notes": [f"{len(batch)} assessments in scope"],
        }

    async def aggregate(state: AnomalyState) -> dict[str, Any]:
        """The sector figures. The half of this agent that is not about suspicion.

        Runs before anything is detected and does not depend on it, because these numbers
        are the ones the public dashboard shows and they must be produced whether or not a
        single flag is raised.
        """
        batch = [_assessment_from(raw) for raw in state.get("assessments", [])]
        rollup = aggregation.summarise(batch)
        return {
            "aggregates": rollup.as_dict(),
            "notes": [
                f"aggregated {rollup.assessments} assessments across {rollup.divisions} divisions"
            ],
        }

    async def normalise_by_exposure(state: AnomalyState) -> dict[str, Any]:
        """Pair each division with what its own forecast predicted. The critical step."""
        batch = [_assessment_from(raw) for raw in state.get("assessments", [])]
        codes = tuple(sorted({item.gn_division_code for item in batch}))
        if not codes:
            return {"division_context": {}}

        found = await exposure.context_for(codes)
        return {
            "division_context": {
                code: _context_as_dict(division) for code, division in found.items()
            },
            "notes": [f"exposure context for {len(found)} of {len(codes)} divisions"],
        }

    async def detect_anomalies(state: AnomalyState) -> dict[str, Any]:
        """Run every detector. Deterministic, and no model anywhere near it."""
        batch = [_assessment_from(raw) for raw in state.get("assessments", [])]
        context = {
            code: _context_from(raw) for code, raw in state.get("division_context", {}).items()
        }
        profiles = norm.build_profiles(batch, context)
        signals = detectors.run_all(profiles)

        not_normalisable = [
            {
                "gn_division_code": profile.gn_division_code,
                "reason": profile.suppression_reason,
                "stage": "not_normalisable",
            }
            for profile in profiles
            if not profile.normalisable
        ]
        return {
            "signals": [_signal_as_dict(signal) for signal in signals],
            "suppressed": not_normalisable,
            "notes": [f"{len(signals)} signals from {len(profiles)} divisions"],
        }

    async def contextualise(state: AnomalyState) -> dict[str, Any]:
        """Ask why each pattern might be innocent. The only model call in the agent."""
        batch = [_assessment_from(raw) for raw in state.get("assessments", [])]
        context = {
            code: _context_from(raw) for code, raw in state.get("division_context", {}).items()
        }
        profiles = {
            profile.gn_division_code: profile for profile in norm.build_profiles(batch, context)
        }

        contextualised: list[dict[str, Any]] = []
        for raw in state.get("signals", []):
            signal = _signal_from(raw)
            profile = profiles.get(signal.gn_division_code)
            if profile is None:
                continue
            flag_context = await context_rules.contextualise(signal, profile, call=call)
            contextualised.append({**raw, "context": flag_context.as_dict()})

        methods = {item["context"]["method"] for item in contextualised}
        _log.info(
            "anomaly_signals_contextualised",
            signals=len(contextualised),
            methods=sorted(methods),
        )
        return {"signals": contextualised}

    async def suppress_explained(state: AnomalyState) -> dict[str, Any]:
        """Drop everything that is not fit to put in front of a reviewer.

        Three reasons, and each is a case where raising would cost more than it saves:

        a score below the threshold, which is a marginal departure from a rule-threshold
        forecast; a signal with nothing ruled out, which build file 17 says is not
        actionable; and a context with no innocent explanation, which is the model saying
        the flag is not ready.
        """
        kept: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []

        for raw in state.get("signals", []):
            signal = _signal_from(raw)
            flag_context = raw.get("context", {})

            if signal.score < min_score:
                dropped.append(
                    {
                        "gn_division_code": signal.gn_division_code,
                        "detector": signal.detector,
                        "reason": f"score {signal.score:.3f} below the {min_score} threshold",
                        "stage": "below_threshold",
                    }
                )
                continue

            if not signal.actionable:
                dropped.append(
                    {
                        "gn_division_code": signal.gn_division_code,
                        "detector": signal.detector,
                        "reason": (
                            "the detector ruled nothing out, so a reviewer would start from "
                            "zero and supply their own explanation"
                        ),
                        "stage": "nothing_ruled_out",
                    }
                )
                continue

            if not flag_context.get("innocent_explanations"):
                dropped.append(
                    {
                        "gn_division_code": signal.gn_division_code,
                        "detector": signal.detector,
                        "reason": (
                            "no innocent explanation could be produced, so this flag is not "
                            "ready to raise"
                        ),
                        "stage": "no_innocent_explanation",
                    }
                )
                continue

            kept.append(raw)

        if dropped:
            _log.info(
                "anomaly_signals_suppressed",
                suppressed=len(dropped),
                kept=len(kept),
                by_stage=_count(item["stage"] for item in dropped),
            )
        return {"signals": kept, "suppressed": dropped}

    async def raise_flags(state: AnomalyState) -> dict[str, Any]:
        """Write what survived, as OPEN, for a human to disposition."""
        flags: list[Flag] = []
        for raw in state.get("signals", []):
            signal = _signal_from(raw)
            flag_context = context_rules.FlagContext(**_context_kwargs(raw.get("context", {})))
            flags.append(
                Flag(
                    detector=signal.detector,
                    detector_version=detectors.DETECTOR_VERSION,
                    subject_type=FLAG_SUBJECT,
                    subject_id=signal.gn_division_code,
                    score=signal.score,
                    rationale={
                        **signal.as_rationale(),
                        "context": flag_context.as_dict(),
                        "context_available": flag_context.method == "LLM",
                    },
                    priority=context_rules.priority_for(signal, flag_context),
                    context_available=flag_context.method == "LLM",
                )
            )

        raised: list[str] = []
        if flags:
            raised = await store.raise_flags(flags)

        _log.info(
            "anomaly_flags_raised",
            raised=len(raised),
            by_detector=_count(flag.detector for flag in flags),
            without_context=sum(1 for flag in flags if not flag.context_available),
        )
        return {
            "flags": [_flag_as_dict(flag) for flag in flags],
            "raised": len(raised),
            "notes": [f"{len(raised)} flags raised for review"],
        }

    async def record(state: AnomalyState) -> dict[str, Any]:
        """Append observations, write the audit entry, and finish."""
        observations = [
            {
                "subject_type": "gn_division",
                "subject_id": flag["subject_id"],
                "observation": "anomaly_flag_raised",
                "value": flag["detector"],
                "confidence": flag["score"],
                "source": f"{AGENT}:{detectors.DETECTOR_VERSION}",
            }
            for flag in state.get("flags", [])
        ]
        await rg_append(state, observations=observations, writer=graph_writer)

        aggregates = dict(state.get("aggregates", {}))
        audited = await audit_write(
            state,
            action="ledger.anomaly.scan",
            subject=str(state.get("district_code") or "national"),
            detail={
                "assessments": aggregates.get("assessments", 0),
                "divisions": aggregates.get("divisions", 0),
                "flags_raised": state.get("raised", 0),
                "signals_suppressed": len(state.get("suppressed", [])),
                "detector_version": detectors.DETECTOR_VERSION,
                # Never a division code and never a person: the audit entry records that a
                # scan happened and how much it found, not who it looked at.
            },
            writer=audit,
        )

        return {
            **audited,
            "status": "COMPLETED",
            "output": {
                "district_code": state.get("district_code"),
                "assessments": aggregates.get("assessments", 0),
                "divisions": aggregates.get("divisions", 0),
                "flags_raised": state.get("raised", 0),
                "signals_suppressed": len(state.get("suppressed", [])),
                "aggregates": aggregates,
                "detector_version": detectors.DETECTOR_VERSION,
                "confidence": 1.0,
                "reasoning": (
                    f"{state.get('raised', 0)} patterns warrant review; "
                    f"{len(state.get('suppressed', []))} signals were suppressed as "
                    "explained, marginal, or not ready to raise"
                ),
                "needs_human_review": False,
                # The detectors are arithmetic. Where a model wrote context it is recorded
                # per flag, not here - the scan itself is deterministic.
                "provenance": "DETERMINISTIC",
            },
        }

    return {
        "receive_batch": receive_batch,
        "aggregate": aggregate,
        "normalise_by_exposure": normalise_by_exposure,
        "detect_anomalies": detect_anomalies,
        "contextualise": contextualise,
        "suppress_explained": suppress_explained,
        "raise_flags": raise_flags,
        "record": record,
    }


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


def _count(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return counts


def _assessment_as_dict(item: Assessment) -> dict[str, Any]:
    return {
        "assessment_id": item.assessment_id,
        "gn_division_code": item.gn_division_code,
        "ds_division_code": item.ds_division_code,
        "district_code": item.district_code,
        "household_id": item.household_id,
        "category": item.category,
        "assessed_value_lkr": item.assessed_value_lkr,
        "assessed_at": item.assessed_at.isoformat(),
        "approved_at": item.approved_at.isoformat() if item.approved_at else None,
        "citizen_confirmed": item.citizen_confirmed,
        "lon": item.lon,
        "lat": item.lat,
        "evidence_hashes": list(item.evidence_hashes),
    }


def _assessment_from(raw: dict[str, Any]) -> Assessment:
    def moment(value: Any) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    return Assessment(
        assessment_id=raw["assessment_id"],
        gn_division_code=raw["gn_division_code"],
        ds_division_code=raw.get("ds_division_code", ""),
        district_code=raw.get("district_code", ""),
        household_id=raw["household_id"],
        category=raw["category"],
        assessed_value_lkr=int(raw.get("assessed_value_lkr", 0)),
        assessed_at=moment(raw["assessed_at"]) or utc_now(),
        approved_at=moment(raw.get("approved_at")),
        citizen_confirmed=raw.get("citizen_confirmed"),
        lon=raw.get("lon"),
        lat=raw.get("lat"),
        evidence_hashes=tuple(raw.get("evidence_hashes", [])),
    )


def _context_as_dict(item: DivisionContext) -> dict[str, Any]:
    return {
        "gn_division_code": item.gn_division_code,
        "impact_class": item.impact_class,
        "expected_households_affected": item.expected_households_affected,
        "forecast_confidence": item.forecast_confidence,
        "household_count": item.household_count,
        "cell_coverage_pct": item.cell_coverage_pct,
        "permanent_housing_pct": item.permanent_housing_pct,
    }


def _context_from(raw: dict[str, Any]) -> DivisionContext:
    return DivisionContext(
        gn_division_code=raw["gn_division_code"],
        impact_class=int(raw.get("impact_class", 0)),
        expected_households_affected=int(raw.get("expected_households_affected", 0)),
        forecast_confidence=float(raw.get("forecast_confidence", 0.0)),
        household_count=int(raw.get("household_count", 0)),
        cell_coverage_pct=raw.get("cell_coverage_pct"),
        permanent_housing_pct=raw.get("permanent_housing_pct"),
    )


def _signal_as_dict(signal: Signal) -> dict[str, Any]:
    return {
        "detector": signal.detector,
        "gn_division_code": signal.gn_division_code,
        "score": signal.score,
        "evidence": [item.as_dict() for item in signal.evidence],
        "ruled_out": list(signal.ruled_out),
        "subject_type": signal.subject_type,
    }


def _signal_from(raw: dict[str, Any]) -> Signal:
    from agent_svc.agents.ledger_anomaly.ports import Evidence

    return Signal(
        detector=raw["detector"],
        gn_division_code=raw["gn_division_code"],
        score=float(raw["score"]),
        evidence=[
            Evidence(
                label=item["label"],
                value=item["value"],
                compared_with=item.get("compared_with"),
                note=item.get("note"),
            )
            for item in raw.get("evidence", [])
        ],
        ruled_out=list(raw.get("ruled_out", [])),
        subject_type=raw.get("subject_type", FLAG_SUBJECT),
    )


def _context_kwargs(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "pattern_summary": raw.get("pattern_summary", ""),
        "innocent_explanations": list(raw.get("innocent_explanations", [])),
        "what_would_resolve_it": list(raw.get("what_would_resolve_it", [])),
        "suggested_priority": raw.get("suggested_priority", context_rules.DEGRADED_PRIORITY),
        "confidence": float(raw.get("confidence", 0.0)),
        "method": raw.get("method", "TEMPLATE"),
    }


def _flag_as_dict(flag: Flag) -> dict[str, Any]:
    return {
        "detector": flag.detector,
        "detector_version": flag.detector_version,
        "subject_type": flag.subject_type,
        "subject_id": flag.subject_id,
        "score": flag.score,
        "rationale": flag.rationale,
        "priority": flag.priority,
        "context_available": flag.context_available,
    }


def build(
    checkpointer: Any,
    *,
    assessments: AssessmentSource | None = None,
    exposure: ExposureSource | None = None,
    store: FlagStore | None = None,
    call: ModelCall | None = None,
    now: datetime | None = None,
    min_score: float = MIN_SCORE,
    audit: Any = None,
    graph_writer: Any = None,
) -> Any:
    """Compile the graph.

    The three sources are optional so the registry can build this at boot. A graph without
    them refuses at the node that needs one rather than reporting a clean scan, which is
    the worst available failure here: it would say the ledger looks fine when nothing was
    looked at.
    """
    nodes = build_nodes(
        assessments=assessments or _RefusingAssessments(),
        exposure=exposure or _RefusingExposure(),
        store=store or _RefusingStore(),
        call=call,
        now=now,
        min_score=min_score,
        audit=audit,
        graph_writer=graph_writer,
    )

    builder = StateGraph(AnomalyState)
    for name, node in nodes.items():
        builder.add_node(name, node)

    builder.add_edge(START, "receive_batch")
    builder.add_edge("receive_batch", "aggregate")
    builder.add_edge("aggregate", "normalise_by_exposure")
    builder.add_edge("normalise_by_exposure", "detect_anomalies")
    builder.add_edge("detect_anomalies", "contextualise")
    builder.add_edge("contextualise", "suppress_explained")
    builder.add_edge("suppress_explained", "raise_flags")
    builder.add_edge("raise_flags", "record")
    builder.add_edge("record", END)

    return builder.compile(checkpointer=checkpointer)


class _RefusingAssessments:
    """Stands in when ledger-svc is unreachable. Refuses loudly.

    A clean scan and an unreadable ledger produce the same zero flags and mean opposite
    things, and only one of them means the ledger is clean.
    """

    async def batch(self, **kwargs: Any) -> Any:
        raise RuntimeError(
            "The anomaly agent has no assessment source configured, so nothing was "
            "examined. Reporting zero flags would say the ledger looks fine when nothing "
            "was looked at."
        )


class _RefusingExposure:
    """Stands in when the forecast is unreachable.

    Refuses rather than returning nothing. With no exposure context every division is
    unnormalisable and the run produces no flags - which is safe, but indistinguishable
    from a clean ledger, and this agent must not be quietly blind.
    """

    async def context_for(self, gn_division_codes: tuple[str, ...]) -> Any:
        raise RuntimeError(
            "The anomaly agent cannot read impact forecasts, so no division can be "
            "normalised against its own exposure. Every detector would be comparing "
            "divisions with each other, which is the failure ADR-009 forbids."
        )


class _RefusingStore:
    """Stands in when there is nowhere to write a flag."""

    async def raise_flags(self, flags: list[Flag]) -> Any:
        raise RuntimeError("The anomaly agent has no flag store configured.")

    async def disposition_rates(self, **kwargs: Any) -> Any:
        return {}


def _eval_build(checkpointer: Any) -> Any:
    """Imported lazily so the production graph does not depend on the eval one."""
    from agent_svc.agents.ledger_anomaly.evaluation import build as build_eval

    return build_eval(checkpointer)


def _eval_sections(report: Any) -> str:
    """The per-detector detection and false-positive table ADR-009 requires."""
    from agent_svc.agents.ledger_anomaly.evaluation import detector_rates

    return detector_rates(report)


SPEC: Final = AgentSpec(
    name=AGENT,
    subject_type=SUBJECT_TYPE,
    build=build,
    description=(
        "Aggregates assessments into the sector figures the public dashboard runs on, and "
        "surfaces patterns that warrant human audit - normalised against each division's "
        "own impact forecast, never naming an individual, and never stating a finding."
    ),
    degraded_note=(
        "Every detector is arithmetic and none touches a model, so the same signals are "
        "found with the provider down. What is lost is the narrative explaining why a "
        "pattern might be innocent - flags then carry a templated context block built from "
        "the detector's own ruled-out list, are raised at low priority, and are marked "
        "context_available: false so a reviewer knows they are looking at a rawer signal. "
        "The aggregation half is unaffected entirely."
    ),
    gated=False,
    eval_build=_eval_build,
    eval_sections=_eval_sections,
)
