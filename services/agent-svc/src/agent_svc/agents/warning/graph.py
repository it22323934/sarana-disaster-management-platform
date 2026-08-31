r"""The warning dissemination agent.

```
START -> receive_forecast -> decide_alert_needed -> select_template -> resolve_targets
      -> plan_channels -> validate -> [human_signoff] -> dispatch -> collect_receipts
      -> assess_gaps -> record -> END
```

Eleven nodes and one interrupt, and the position of that interrupt is the safety design
rather than an implementation detail.

## The soft human gate, and what it is soft about

An alert built entirely from a published template with typed parameters dispatches on its
own. An alert carrying **any** free text stops and waits for a named DMC operator. That is
the one place in this agent where speed and control genuinely trade off, and templates are
how the speed is bought without giving up the control.

The gate is enforced three times over, in three independent places, because one layer is
one bug away from not being a layer:

  1. `dispatch` calls a **gated tool** for the free-text path, and
     `runtime.tools.assert_human_gate` refuses it without a decision naming *this* subject;
  2. `validate` will not mark a free-text alert dispatchable, so the graph routes to
     `human_signoff` before `dispatch` is ever reached;
  3. alerting-svc itself refuses to dispatch an alert whose `requires_human_signoff` is set
     and whose `signed_off_by` is null.

## Where a model is used, and where it is not

Two nodes call one, and neither decides anything on its own:

**`select_template`** chooses among *published, natively reviewed* text. Its answer is
discarded whole if it names something outside the catalogue or anything less severe than
the rule matrix requires.

**`plan_channels`** proposes channels. It can only widen the deterministic mix, never
narrow it, and never to a transport this deployment does not have.

`resolve_targets`, `validate`, `assess_gaps` and every threshold in the agent reach no model
at all. With the provider unreachable the same alert goes to the same people over the same
channels; what is lost is a slightly better-fitting template.

## One class band per run, and why the divisions at other bands are not in it

A run alerts on **one impact class**, and targets only the divisions at that class. Mixing
bands into one alert forces a choice between two harms: send the class 4 text to everybody
and a watch-level division is told to evacuate, or send the class 2 text and a division in
severe trouble is told to monitor water levels. Both destroy the thing that makes a warning
work, which is that people believe it.

So the band is part of the subject - `warning:hazard_event:{event}#c4` - and the divisions
at lower bands are named in the run's output as needing their own run, rather than being
silently folded in or silently dropped. `subject_for()` below builds the id, and it is
derivable from the event and the class, so a resume never has to search for its thread.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any, Final

import structlog
from langgraph.graph import END, START, StateGraph

from agent_svc.agents.warning import catalogue as templates
from agent_svc.agents.warning import channels as channel_rules
from agent_svc.agents.warning import gaps as gap_rules
from agent_svc.agents.warning import targeting
from agent_svc.agents.warning.ports import (
    AlertDispatcher,
    AlertHistory,
    AlertTemplate,
    DispatchOrder,
    DivisionReach,
    ForecastedDivision,
    ForecastSource,
    ModelCall,
    TargetDirectory,
    TemplateCatalogue,
    WarningTarget,
    as_division,
)
from agent_svc.runtime.nodes import audit_write, request_approval, rg_append
from agent_svc.runtime.registry import AgentSpec
from agent_svc.runtime.state import AgentState
from agent_svc.runtime.tools import REGISTRY as TOOLS
from sarana_shared.domain import cap, sms
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import COLOMBO, utc_now

_log = structlog.get_logger(__name__)

AGENT: Final = "warning"
SUBJECT_TYPE: Final = "hazard_event"

# Who the CAP document says sent it. Overridable per deployment; the default matches
# alerting-svc's `SARANA_ALERTING_CAP_SENDER`, because two services disagreeing about the
# sender of the same alert is a consumer deduplicating two warnings into none.
DEFAULT_SENDER: Final = "dmc@sarana.lk"

# How long an alert stays in force unless something supersedes it. Six hours: long enough
# to cover the gap between forecast generations, short enough that a stale evacuation
# order visibly expires rather than sitting on a public feed for a week.
VALIDITY_HOURS: Final = 6

# CAP's own category vocabulary, per hazard. Landslides are geophysical and everything else
# SARANA warns on is meteorological; a consumer filtering on category gets the right answer
# without SARANA writing them an adapter, which is the whole reason for emitting CAP.
CAP_CATEGORIES: Final[dict[str, str]] = {
    "FLOOD": "Met",
    "CYCLONE": "Met",
    "STORM_SURGE": "Met",
    "DROUGHT": "Met",
    "LANDSLIDE": "Geo",
}
DEFAULT_CAP_CATEGORY: Final = "Met"


def subject_for(hazard_event_id: str, impact_class: int) -> str:
    """The subject id for one hazard event at one impact class.

    `#c4` rather than a second colon: the thread id is `{agent}:{subject_type}:{subject_id}`
    and the resume endpoint splits it on the first two colons only, so a colon here would
    survive - but a subject id that looks like it has structure the splitter understands is
    one somebody will eventually split wrongly.
    """
    return f"{hazard_event_id}#c{impact_class}"


def event_and_class(subject_id: str) -> tuple[str, int | None]:
    """Pull the hazard event and the band back out of a subject id.

    Returns `None` for the band when the subject names no band, which is how a run started
    from the console with a bare event id asks the agent to pick the highest.
    """
    event, _, band = subject_id.partition("#c")
    if not band or not band.isdigit():
        return subject_id, None
    return event, int(band)


class WarningState(AgentState, total=False):
    """The warning run's own state, on top of the shared base.

    **Targets are not in here.** A national fan-out is several hundred thousand households,
    a checkpoint row stays under 64KB, and a checkpoint holds references rather than
    payloads. What travels is the division codes and the per-division counts;
    `dispatch` resolves the targets again from the directory in the same run. The cost is
    one extra directory read; the alternative is a resume that has to load half a megabyte
    of contact hashes before it can ask a person a question.
    """

    hazard_event_id: str
    hazard_type: str
    impact_class: int
    divisions: list[dict[str, Any]]
    deferred_bands: dict[str, int]

    alert_needed: bool
    selection: dict[str, Any]
    free_text: dict[str, str] | None

    division_codes: list[str]
    division_ids: list[str]
    target_counts: dict[str, dict[str, int]]
    target_summary: dict[str, int]
    division_languages: dict[str, list[str]]

    plan: dict[str, Any]
    validation: dict[str, Any]
    dispatched: dict[str, Any]
    gap_report: dict[str, Any]
    division_gaps: Annotated[list[dict[str, Any]], list.__add__]


# ---------------------------------------------------------------------------------------
# The two dispatch tools. One is gated; that is the whole point of there being two.
# ---------------------------------------------------------------------------------------


async def _send_templated_warning(
    *, dispatcher: AlertDispatcher, order: DispatchOrder
) -> list[Any]:
    """Dispatch an alert built entirely from a published template.

    Not gated. Every word of it has been through native review in all three languages, and
    a warning that needs a person to click before it can go out is a warning that goes out
    when that person is asleep.
    """
    return await dispatcher.dispatch(order)


async def _send_free_text_warning(
    *, dispatcher: AlertDispatcher, order: DispatchOrder
) -> list[Any]:
    """Dispatch an alert carrying text no native reviewer has signed.

    Gated, and the registry does the refusing: without a human decision naming *this*
    subject, this function is never entered. That is layer one of three - see the module
    docstring - and it is the layer that holds when somebody wires the graph wrongly.
    """
    return await dispatcher.dispatch(order)


TOOLS.tool(side_effect=True, name="dispatch_templated_warning")(_send_templated_warning)
TOOLS.tool(side_effect=True, requires_human_gate=True, name="dispatch_free_text_warning")(
    _send_free_text_warning
)


# ---------------------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------------------


def build_nodes(
    *,
    forecasts: ForecastSource,
    catalogue: TemplateCatalogue,
    directory: TargetDirectory,
    dispatcher: AlertDispatcher,
    history: AlertHistory | None = None,
    call: ModelCall | None = None,
    now: datetime | None = None,
    available_channels: tuple[str, ...] = channel_rules.ALL_CHANNELS,
    sender: str = DEFAULT_SENDER,
    target_cap: int = channel_rules.DEFAULT_TARGET_CAP,
    audit: Any = None,
    graph_writer: Any = None,
) -> dict[str, Any]:
    """Build the eleven nodes, closed over their dependencies.

    `now` is passed rather than read from the clock inside a node, for the same reason the
    forecast agent passes its window: an agent that reads `datetime.now()` internally
    cannot be replayed at a fixed hour, and the quiet-hours rule is precisely a claim about
    what this agent does at a particular hour. A test that could not fix the clock could
    not test the rule that keeps a district asleep.
    """
    clock = (lambda: now) if now is not None else utc_now

    async def receive_forecast(state: WarningState) -> dict[str, Any]:
        """Read the forecast this alert would be written against."""
        subject = str(state.get("subject_id", ""))
        supplied = dict(state.get("output", {}))
        hazard_event_id, band = event_and_class(subject)
        hazard_event_id = str(supplied.get("hazard_event_id") or hazard_event_id)

        rows = [as_division(raw) for raw in supplied.get("divisions", [])]
        if not rows:
            rows = await forecasts.current(hazard_event_id=hazard_event_id)

        hazard_type = str(supplied.get("hazard_type") or "FLOOD").upper()
        _log.info(
            "warning_forecast_received",
            hazard_event_id=hazard_event_id,
            hazard_type=hazard_type,
            divisions=len(rows),
            band=band,
        )
        return {
            "hazard_event_id": hazard_event_id,
            "hazard_type": hazard_type,
            "impact_class": band if band is not None else 0,
            "divisions": [_division_as_dict(row) for row in rows],
            "notes": [f"{len(rows)} forecast divisions for {hazard_event_id}"],
        }

    async def decide_alert_needed(state: WarningState) -> dict[str, Any]:
        """Pick the band, and stop here if nothing reaches the threshold.

        The band is the one named in the subject if there is one, and otherwise the highest
        present. Divisions at other bands are counted and named in the output rather than
        folded in: see the module docstring on why one alert never covers two bands.
        """
        rows = [as_division(raw) for raw in state.get("divisions", [])]
        eligible = [row for row in rows if row.impact_class >= channel_rules.ALERT_FROM]

        if not eligible:
            return _completed(
                state,
                alert_needed=False,
                reason=(
                    f"no division reached impact class {channel_rules.ALERT_FROM}; "
                    "a public alert below that is the one people learn to ignore"
                ),
                confidence=0.95,
            )

        requested = int(state.get("impact_class") or 0)
        band = requested if requested >= channel_rules.ALERT_FROM else max(
            row.impact_class for row in eligible
        )
        in_band = [row for row in eligible if row.impact_class == band]

        if not in_band:
            return _completed(
                state,
                alert_needed=False,
                reason=(
                    f"this run is for impact class {band} and no division is at that "
                    "class in the current forecast"
                ),
                confidence=0.9,
            )

        deferred: dict[str, int] = {}
        for row in eligible:
            if row.impact_class != band:
                key = f"class_{row.impact_class}"
                deferred[key] = deferred.get(key, 0) + 1

        if deferred:
            _log.info(
                "warning_bands_deferred",
                band=band,
                deferred=deferred,
                impact="those divisions need their own run; this alert covers one class",
            )

        return {
            "alert_needed": True,
            "impact_class": band,
            "divisions": [_division_as_dict(row) for row in in_band],
            "deferred_bands": deferred,
            "notes": [f"alerting {len(in_band)} divisions at impact class {band}"],
        }

    async def select_template(state: WarningState) -> dict[str, Any]:
        """Choose the template and fill it, or ask an operator.

        Every failure here is a review item rather than a failed run. An agent that
        stopped with a traceback because the catalogue had a gap would leave a district
        unwarned and nobody looking at a queue.
        """
        if not state.get("alert_needed"):
            return {}

        hazard = str(state.get("hazard_type", "FLOOD"))
        band = int(state.get("impact_class", 0))
        rows = [as_division(raw) for raw in state.get("divisions", [])]

        published = await catalogue.published(hazard_type=hazard)
        facts = _facts_for(rows, hazard=hazard, moment=clock())

        try:
            choice = await templates.select(
                hazard_type=hazard,
                impact_class=band,
                catalogue=published,
                facts=facts,
                call=call,
            )
        except templates.NoSuitableTemplate as error:
            _log.warning(
                "warning_no_suitable_template",
                hazard_type=hazard,
                impact_class=band,
                reason=str(error),
                impact="routed to a DMC operator; the agent does not improvise alert text",
            )
            return {
                "selection": {},
                "output": {
                    **dict(state.get("output", {})),
                    "needs_human_review": True,
                    "review_reason": f"no_suitable_template: {error}",
                    "confidence": 0.0,
                    "reasoning": str(error),
                    "provenance": "DETERMINISTIC",
                },
                "notes": ["no suitable template; an operator decides"],
            }

        body = choice.rendered()
        _log.info(
            "warning_template_selected",
            template=choice.template.code,
            method=choice.method,
            confidence=choice.confidence,
            notes=list(choice.notes),
        )
        return {
            "selection": {
                "template_id": choice.template.id,
                "template_code": choice.template.code,
                "severity": choice.template.severity,
                "urgency": choice.template.urgency,
                "certainty": choice.template.certainty,
                "parameters": choice.parameters,
                "body": body,
                "confidence": choice.confidence,
                "method": choice.method,
                "provenance": choice.provenance,
                "reasoning": choice.reasoning,
                "notes": list(choice.notes),
            },
            "notes": [f"template {choice.template.code} ({choice.method})"],
        }

    async def resolve_targets(state: WarningState) -> dict[str, Any]:
        """Expand divisions to households. Deterministic, and no model anywhere near it."""
        if not state.get("alert_needed"):
            return {}

        rows = [as_division(raw) for raw in state.get("divisions", [])]
        codes = tuple(sorted({row.gn_division_code for row in rows}))
        ids = sorted({row.gn_division_id for row in rows})

        found = await directory.targets_in(codes)
        reach = await directory.reach(codes)

        priors = []
        if history is not None:
            priors = await history.recent(
                hazard_event_id=str(state.get("hazard_event_id", "")),
                since=targeting.fatigue_window_start(clock()),
            )

        plan = targeting.build_plan(
            found,
            reach=reach,
            priors=priors,
            impact_class=int(state.get("impact_class", 0)),
        )

        if not plan.targets:
            _log.warning(
                "warning_targets_empty",
                divisions=len(codes),
                suppressed=len(plan.suppressed),
                impact="this alert would reach nobody; either every household was already "
                "warned at this level, or the directory returned nothing",
            )

        return {
            "division_codes": list(codes),
            "division_ids": ids,
            "target_counts": plan.counts_by_division(),
            "target_summary": plan.as_summary(),
            "division_languages": plan.division_languages,
            "notes": [
                f"{len(plan.targets)} targeted, {len(plan.no_channel)} with no channel, "
                f"{len(plan.suppressed)} suppressed for fatigue"
            ],
        }

    async def plan_channels(state: WarningState) -> dict[str, Any]:
        """Decide the channel mix. The model proposes; the validator below has the say."""
        if not state.get("alert_needed"):
            return {}

        band = int(state.get("impact_class", 0))
        codes = tuple(state.get("division_codes", []))
        reach = await directory.reach(codes) if codes else {}
        coverage = _worst_coverage(reach)
        targeted = int(state.get("target_summary", {}).get("targeted", 0))

        proposed = await channel_rules.propose(
            impact_class=band,
            available=available_channels,
            cell_coverage_pct=coverage,
            call=call,
        )
        plan = channel_rules.plan(
            impact_class=band,
            now=clock(),
            available=available_channels,
            cell_coverage_pct=coverage,
            targeted=targeted,
            cap=target_cap,
            proposed=proposed,
        )

        _log.info(
            "warning_channels_planned",
            channels=list(plan.channels),
            deferred=list(plan.deferred),
            method=plan.method,
            coverage_pct=coverage,
            exceeds_cap=plan.exceeds_cap,
        )
        return {
            "plan": {
                "channels": list(plan.channels),
                "deferred": list(plan.deferred),
                "reasons": plan.reasons,
                "method": plan.method,
                "release_at": plan.release_at.isoformat() if plan.release_at else None,
                "exceeds_cap": plan.exceeds_cap,
                "cap": plan.cap,
                "summary": plan.as_sentence(),
            },
            "notes": [plan.as_sentence()],
        }

    async def validate(state: WarningState) -> dict[str, Any]:
        """Build the CAP document and check everything that can be checked before sending.

        Four checks, and each refuses for a different reason:

        **CAP 1.2.** The document is built here and validated here, rather than being
        discovered invalid by alerting-svc after this graph has finished. A consumer that
        cannot parse it is a broadcaster that does not broadcast it.

        **Trilingual completeness.** Enforced inside `cap.validate` and asserted again on
        the rendered body, because the body is what an SMS carries and the CAP document is
        what a broadcaster reads - they can be missing a language independently.

        **Target-count sanity.** Above the cap, nothing is sent without an explicit
        override and a written reason.

        **SMS segments.** A rendered body over two segments is recorded, not refused.
        Refusing to send a warning because a long division name pushed it three characters
        over would trade a real warning for a tidy one.
        """
        if not state.get("alert_needed"):
            return {}

        selection = dict(state.get("selection", {}))
        free_text = state.get("free_text") or None
        problems: list[str] = []

        if not selection:
            problems.append("no template was selected")
            return _validation(state, problems=problems, document=None, requires_signoff=True)

        body = dict(selection.get("body", {}))
        merged = _merge_free_text(body, free_text)

        moment = clock()
        document = cap.CapAlert(
            identifier=f"sarana.lk.{uuid7()}",
            sender=sender,
            sent=moment,
            msg_type="Alert",
            status="Actual",
            scope="Public",
            event=selection.get("template_code", "Alert"),
            category=CAP_CATEGORIES.get(str(state.get("hazard_type", "")), DEFAULT_CAP_CATEGORY),
            severity=cap.cap_case(str(selection.get("severity", "UNKNOWN"))),
            urgency=cap.cap_case(str(selection.get("urgency", "UNKNOWN"))),
            certainty=cap.cap_case(str(selection.get("certainty", "UNKNOWN"))),
            headline=merged,
            description=merged,
            instruction=merged,
            effective=moment,
            expires=moment + timedelta(hours=VALIDITY_HOURS),
            area=cap.Area(
                gn_codes=list(state.get("division_codes", [])),
                description=f"{len(state.get('division_codes', []))} GN divisions",
            ),
        )

        try:
            cap.validate(document)
        except cap.CapInvalid as error:
            problems.extend(error.problems)

        if state.get("plan", {}).get("exceeds_cap"):
            problems.append(
                f"this alert targets {state.get('target_summary', {}).get('targeted', 0):,} "
                f"households, above the {state.get('plan', {}).get('cap'):,} cap; confirm "
                "the area selection and override with a written reason"
            )

        if not state.get("plan", {}).get("channels"):
            problems.append("no channel is available to carry this alert")

        oversized = {
            language: sms.count(text).as_sentence()
            for language, text in merged.items()
            if not sms.fits(text)
        }
        if oversized:
            # Recorded, not refused. See the docstring.
            _log.warning(
                "warning_body_exceeds_sms_segments",
                languages=sorted(oversized),
                impact="those languages cost an extra SMS segment and can arrive in parts",
            )

        return _validation(
            state,
            problems=problems,
            document=document,
            requires_signoff=bool(free_text),
            oversized=oversized,
        )

    async def human_signoff(state: WarningState) -> dict[str, Any]:
        """Pause for a named DMC operator.

        **This node re-executes from the top when the run resumes.** Everything above the
        `interrupt()` call runs a second time, so nothing above it may have a side effect
        that is not idempotent - and there is deliberately nothing above it here but
        reading state. The dispatch is a separate node downstream, which is what stops an
        evacuation order being sent twice to the same district.
        """
        selection = dict(state.get("selection", {}))
        validation = dict(state.get("validation", {}))

        decision = request_approval(
            state,
            question=(
                "This alert needs a person before it goes out."
                if selection
                else "No published template fits this forecast. Choose one, or author the text."
            ),
            detail={
                "hazard_type": state.get("hazard_type"),
                "impact_class": state.get("impact_class"),
                "template_code": selection.get("template_code"),
                "divisions": len(state.get("division_codes", [])),
                "targeted": state.get("target_summary", {}).get("targeted", 0),
                "no_channel_available": state.get("target_summary", {}).get(
                    "no_channel_available", 0
                ),
                "channels": state.get("plan", {}).get("channels", []),
                "problems": validation.get("problems", []),
                "why": state.get("output", {}).get("review_reason"),
            },
        )

        # Below the interrupt. Runs exactly once.
        approved = bool(decision.get("approved"))
        chosen_code = decision.get("template_code")
        free_text = decision.get("free_text")

        _log.info(
            "warning_human_decided",
            approved=approved,
            decided_by=str(decision.get("decided_by")),
            template_code=chosen_code,
            carries_free_text=bool(free_text),
        )

        update: dict[str, Any] = {
            "human_decision": decision,
            "notes": [f"human {'approved' if approved else 'refused'} this alert"],
        }
        if free_text:
            update["free_text"] = dict(free_text)
        if chosen_code:
            update["selection"] = {**selection, "template_code": chosen_code}
        return update

    async def dispatch(state: WarningState) -> dict[str, Any]:
        """Send it, over every planned channel at once.

        The targets are resolved again here rather than carried through the checkpoint -
        see `WarningState`. The gated tool is chosen by whether there is free text, and the
        registry refuses the gated one without a decision naming this subject.
        """
        if not state.get("alert_needed") or not state.get("validation", {}).get("dispatchable"):
            return {}

        decision = state.get("human_decision") or {}
        if decision and not decision.get("approved", True):
            return _completed(
                state,
                alert_needed=False,
                reason="a person reviewed this alert and said no; a refusal is a decision",
                confidence=1.0,
                provenance="HUMAN",
            )

        selection = dict(state.get("selection", {}))
        codes = tuple(state.get("division_codes", []))
        found = targeting.deduplicate(await directory.targets_in(codes))
        free_text = state.get("free_text") or None

        order = DispatchOrder(
            hazard_event_id=str(state.get("hazard_event_id", "")),
            template_code=str(selection.get("template_code", "")),
            template_id=str(selection.get("template_id", "")),
            body=_merge_free_text(dict(selection.get("body", {})), free_text),
            parameters=dict(selection.get("parameters", {})),
            gn_division_ids=tuple(state.get("division_ids", [])),
            gn_division_codes=codes,
            channels=tuple(state.get("plan", {}).get("channels", [])),
            division_languages=dict(state.get("division_languages", {})),
            effective_at=clock(),
            expires_at=clock() + timedelta(hours=VALIDITY_HOURS),
            targets=found,
            free_text=free_text,
            correlation_id=str(state.get("correlation_id", "")),
        )

        tool = "dispatch_free_text_warning" if free_text else "dispatch_templated_warning"
        outcomes = await TOOLS.invoke(tool, state, dispatcher=dispatcher, order=order)

        failed = sorted(outcome.channel for outcome in outcomes if outcome.failed_outright)
        if failed:
            # Loud, immediately, and not after twenty minutes of quiet retries. A telco
            # gateway that is down during a cyclone is an operator decision, not a
            # background task.
            _log.error(
                "warning_channel_failed_outright",
                channels=failed,
                impact="those channels carried nothing; the remaining channels completed "
                "and the gap report counts the difference",
            )

        return {
            "dispatched": {
                "tool": tool,
                "cap_identifier": state.get("validation", {}).get("cap_identifier"),
                "channels": list(order.channels),
                "channels_failed": failed,
                "targets": len(found),
            },
            "notes": [f"dispatched over {len(order.channels)} channels via {tool}"],
        }

    async def collect_receipts(state: WarningState) -> dict[str, Any]:
        """Read the receipts as they stand, including anything a DLR has upgraded.

        A telco confirms delivery minutes after the send, so this is the node that turns
        SENT into DELIVERED. It reads once rather than polling: a graph that waited for
        every receipt would hold the run open for the length of the dispatch window, and
        the gap report is more useful early and revisable than late and complete.
        """
        if not state.get("dispatched"):
            return {}

        identifier = str(state.get("validation", {}).get("cap_identifier", ""))
        receipts = await dispatcher.receipts(alert_key=identifier)
        return {
            "notes": [f"{len(receipts)} receipts at the close of the dispatch window"],
            "dispatched": {**dict(state.get("dispatched", {})), "receipts": len(receipts)},
        }

    async def assess_gaps(state: WarningState) -> dict[str, Any]:
        """Say who was probably not reached, per division, worst first."""
        if not state.get("dispatched"):
            return {}

        identifier = str(state.get("validation", {}).get("cap_identifier", ""))
        codes = tuple(state.get("division_codes", []))
        found = targeting.deduplicate(await directory.targets_in(codes))
        receipts = await dispatcher.receipts(alert_key=identifier)

        outcomes = _outcomes_from(receipts, failed=state.get("dispatched", {}).get(
            "channels_failed", []
        ))
        report = gap_rules.assess(outcomes, found)

        return {
            "gap_report": report.as_dict(),
            "division_gaps": [division.as_dict() for division in report.gaps],
            "notes": [report.as_sentence()],
        }

    async def record(state: WarningState) -> dict[str, Any]:
        """Write the audit entry, append the observations, and finish.

        Last node, downstream of the interrupt, so it runs once however many times
        `human_signoff` re-executed.
        """
        summary = dict(state.get("target_summary", {}))
        report = dict(state.get("gap_report", {}))
        selection = dict(state.get("selection", {}))

        observations = [
            {
                "subject_type": "gn_division",
                "subject_id": division["gn_division_code"],
                "observation": "warning_reachability",
                "value": division["confirmed_fraction"],
                "confidence": division["reachability_confidence"],
                "source": f"{AGENT}:{selection.get('template_code', 'none')}",
            }
            for division in state.get("division_gaps", [])
        ]
        await rg_append(state, observations=observations, writer=graph_writer)

        audited = await audit_write(
            state,
            action="warning.alert.dispatched",
            subject=str(state.get("hazard_event_id", "")),
            detail={
                "impact_class": state.get("impact_class"),
                "template_code": selection.get("template_code"),
                "selection_method": selection.get("method"),
                "channels": state.get("plan", {}).get("channels", []),
                "deferred_channels": state.get("plan", {}).get("deferred", []),
                "cap_identifier": state.get("validation", {}).get("cap_identifier"),
                "requires_human_signoff": state.get("validation", {}).get("requires_signoff"),
                "signed_off_by": (state.get("human_decision") or {}).get("decided_by"),
                **summary,
                "confirmed": report.get("confirmed"),
                "divisions_below_threshold": report.get("divisions_below_threshold"),
            },
            writer=audit,
        )

        return {
            **audited,
            "status": "COMPLETED",
            "output": {
                "alert_needed": True,
                "hazard_event_id": state.get("hazard_event_id"),
                "impact_class": state.get("impact_class"),
                "template_code": selection.get("template_code"),
                "cap_identifier": state.get("validation", {}).get("cap_identifier"),
                "channels": state.get("plan", {}).get("channels", []),
                "deferred_channels": state.get("plan", {}).get("deferred", []),
                "divisions": len(state.get("division_codes", [])),
                "deferred_bands": state.get("deferred_bands", {}),
                **summary,
                "confirmed": report.get("confirmed", 0),
                "unconfirmed": report.get("unconfirmed", 0),
                "failed": report.get("failed", 0),
                "divisions_below_threshold": report.get("divisions_below_threshold", 0),
                "delivery_summary": report.get("summary", ""),
                "confidence": float(selection.get("confidence", 0.0)),
                "reasoning": str(selection.get("reasoning", "")),
                "needs_human_review": False,
                "provenance": (
                    "HUMAN" if state.get("human_decision") else selection.get(
                        "provenance", "DETERMINISTIC"
                    )
                ),
            },
        }

    return {
        "receive_forecast": receive_forecast,
        "decide_alert_needed": decide_alert_needed,
        "select_template": select_template,
        "resolve_targets": resolve_targets,
        "plan_channels": plan_channels,
        "validate": validate,
        "human_signoff": human_signoff,
        "dispatch": dispatch,
        "collect_receipts": collect_receipts,
        "assess_gaps": assess_gaps,
        "record": record,
    }


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


def _division_as_dict(division: ForecastedDivision) -> dict[str, Any]:
    return {
        "gn_division_id": division.gn_division_id,
        "gn_division_code": division.gn_division_code,
        "impact_class": division.impact_class,
        "confidence": division.confidence,
        "lead_time_hours": division.lead_time_hours,
        "households": division.households,
        "names": division.names,
    }


def _completed(
    state: WarningState,
    *,
    alert_needed: bool,
    reason: str,
    confidence: float,
    provenance: str = "DETERMINISTIC",
) -> dict[str, Any]:
    """A run that finishes without dispatching, saying why in words.

    "No alert was needed" and "the agent fell over" have to be distinguishable from the
    outside, and the only thing that distinguishes them is this being an explicit,
    confident output rather than an empty one.
    """
    return {
        "alert_needed": alert_needed,
        "status": "COMPLETED",
        "output": {
            "alert_needed": alert_needed,
            "hazard_event_id": state.get("hazard_event_id"),
            "impact_class": state.get("impact_class"),
            "confidence": confidence,
            "reasoning": reason,
            "needs_human_review": False,
            "provenance": provenance,
        },
        "notes": [reason],
    }


def _validation(
    state: WarningState,
    *,
    problems: list[str],
    document: Any,
    requires_signoff: bool,
    oversized: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The validation verdict, and the CAP document if one was built."""
    dispatchable = not problems and not requires_signoff
    if problems:
        _log.error(
            "warning_alert_failed_validation",
            problems=problems,
            impact="nothing was sent; a schema-invalid or over-cap alert never dispatches",
        )

    update: dict[str, Any] = {
        "validation": {
            "problems": problems,
            "requires_signoff": requires_signoff,
            "dispatchable": dispatchable,
            "cap_identifier": document.identifier if document is not None else None,
            "cap_xml": cap.to_xml(document) if document is not None and not problems else None,
            "oversized_sms": oversized or {},
        },
        "notes": [
            "validated: dispatchable"
            if dispatchable
            else f"validated: {len(problems)} problem(s), signoff={requires_signoff}"
        ],
    }
    if requires_signoff:
        output = dict(state.get("output", {}))
        update["output"] = {
            **output,
            "needs_human_review": True,
            "review_reason": output.get("review_reason")
            or "this alert carries free text and needs a named DMC operator",
        }
    return update


def _merge_free_text(body: dict[str, str], free_text: dict[str, str] | None) -> dict[str, str]:
    """Append the operator's own words to each language, where they supplied them.

    Appended rather than substituted: the reviewed template still says what it said, and
    the addition is visibly an addition. A language the operator did not write in keeps
    the template text alone rather than being left blank, because a blank language is an
    alert that does not dispatch at all.
    """
    if not free_text:
        return dict(body)
    return {
        language: f"{text} {free_text[language]}".strip()
        if free_text.get(language)
        else text
        for language, text in body.items()
    }


def _facts_for(
    divisions: list[ForecastedDivision], *, hazard: str, moment: datetime
) -> templates.SelectionFacts:
    """The structured values a template may be filled from.

    `gn_division_name` is the single division's name when the alert covers one, and the
    count when it covers several. "6 GN divisions in Kandy District" is accurate; naming
    one of six in a message going to all six is not, and picking the first alphabetically
    would put a stranger's village in somebody's evacuation order.
    """
    names = [division.names.get("en") for division in divisions if division.names.get("en")]
    if len(divisions) == 1 and names:
        area = names[0]
    else:
        area = f"{len(divisions)} GN divisions"

    return templates.SelectionFacts(
        gn_division_name=area,
        hazard_name=hazard.replace("_", " ").title(),
        # Colombo local, because it is read by somebody deciding whether they have time.
        deadline_time=moment.astimezone(COLOMBO).strftime("%H:%M"),
        effective_time=moment.astimezone(COLOMBO).strftime("%H:%M"),
    )


def _worst_coverage(reach: dict[str, DivisionReach]) -> float | None:
    """The thinnest cell coverage across the targeted divisions.

    The worst rather than the mean, because the channel mix is chosen for the division that
    is hardest to reach. Averaging would let twenty well-covered divisions hide the one
    where the mesh and a printed sheet are the only things that work.
    """
    known = [
        division.cell_coverage_pct
        for division in reach.values()
        if division.cell_coverage_pct is not None
    ]
    return min(known) if known else None


def _outcomes_from(receipts: list[Any], *, failed: list[str]) -> list[Any]:
    """Group flat receipts back into per-channel outcomes for the gap assessment."""
    from agent_svc.agents.warning.ports import ChannelOutcome

    grouped: dict[str, list[Any]] = {}
    for receipt in receipts:
        grouped.setdefault(receipt.channel, []).append(receipt)

    outcomes = [
        ChannelOutcome(channel=channel, receipts=members)
        for channel, members in sorted(grouped.items())
        if channel not in failed
    ]
    outcomes += [ChannelOutcome(channel=channel, error="channel failed") for channel in failed]
    return outcomes


# ---------------------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------------------


def _after_decision(state: WarningState) -> str:
    return "select_template" if state.get("alert_needed") else "end"


def _after_selection(state: WarningState) -> str:
    """A missing template goes straight to a person, without targeting anybody.

    Resolving targets for an alert that has no text would read several hundred thousand
    household rows to build a fan-out nothing can be sent over.
    """
    return "human_signoff" if state.get("output", {}).get("needs_human_review") else "resolve_targets"


def _after_validation(state: WarningState) -> str:
    validation = dict(state.get("validation", {}))
    if validation.get("requires_signoff"):
        return "human_signoff"
    if not validation.get("dispatchable"):
        return "end"
    return "dispatch"


def _after_signoff(state: WarningState) -> str:
    """Where a signed-off run goes next.

    A run that was interrupted before it had a template goes back through selection with
    the operator's answer; one interrupted only for free text goes on to dispatch.
    """
    decision = state.get("human_decision") or {}
    if not decision.get("approved"):
        return "end"
    if not state.get("selection"):
        return "end"
    if not state.get("validation"):
        return "resolve_targets"
    return "dispatch"


def build(
    checkpointer: Any,
    *,
    forecasts: ForecastSource | None = None,
    catalogue: TemplateCatalogue | None = None,
    directory: TargetDirectory | None = None,
    dispatcher: AlertDispatcher | None = None,
    history: AlertHistory | None = None,
    call: ModelCall | None = None,
    now: datetime | None = None,
    available_channels: tuple[str, ...] = channel_rules.ALL_CHANNELS,
    sender: str = DEFAULT_SENDER,
    target_cap: int = channel_rules.DEFAULT_TARGET_CAP,
    audit: Any = None,
    graph_writer: Any = None,
) -> Any:
    """Compile the graph.

    The dependencies are optional so `AgentRegistry.compile_all` can build this at boot the
    same way it builds every other agent, and so a test can supply fakes. A graph compiled
    without them refuses at its first node rather than reporting that no alert was needed,
    which is the worst available way for a warning service to be broken: it is
    indistinguishable from a quiet day.
    """
    nodes = build_nodes(
        forecasts=forecasts or _RefusingForecasts(),
        catalogue=catalogue or _RefusingCatalogue(),
        directory=directory or _RefusingDirectory(),
        dispatcher=dispatcher or _RefusingDispatcher(),
        history=history,
        call=call,
        now=now,
        available_channels=available_channels,
        sender=sender,
        target_cap=target_cap,
        audit=audit,
        graph_writer=graph_writer,
    )

    builder = StateGraph(WarningState)
    for name, node in nodes.items():
        builder.add_node(name, node)

    builder.add_edge(START, "receive_forecast")
    builder.add_edge("receive_forecast", "decide_alert_needed")
    builder.add_conditional_edges(
        "decide_alert_needed",
        _after_decision,
        {"select_template": "select_template", "end": END},
    )
    builder.add_conditional_edges(
        "select_template",
        _after_selection,
        {"resolve_targets": "resolve_targets", "human_signoff": "human_signoff"},
    )
    builder.add_edge("resolve_targets", "plan_channels")
    builder.add_edge("plan_channels", "validate")
    builder.add_conditional_edges(
        "validate",
        _after_validation,
        {"dispatch": "dispatch", "human_signoff": "human_signoff", "end": END},
    )
    builder.add_conditional_edges(
        "human_signoff",
        _after_signoff,
        {"dispatch": "dispatch", "resolve_targets": "resolve_targets", "end": END},
    )
    builder.add_edge("dispatch", "collect_receipts")
    builder.add_edge("collect_receipts", "assess_gaps")
    builder.add_edge("assess_gaps", "record")
    builder.add_edge("record", END)

    return builder.compile(checkpointer=checkpointer)


class _RefusingForecasts:
    """Stands in when the service booted without a database. Refuses loudly."""

    async def current(self, *, hazard_event_id: str) -> Any:
        raise RuntimeError(
            "The warning agent has no forecast source configured, so it cannot tell which "
            "divisions to warn. Running without one would report that no alert was needed."
        )


class _RefusingCatalogue:
    """Stands in when alerting-svc is unreachable.

    Refuses rather than returning an empty catalogue. An empty catalogue means "no template
    fits", which routes to an operator - and an outage dressed up as that question would
    put a DMC officer in front of a decision the platform invented.
    """

    async def published(self, *, hazard_type: str | None = None) -> Any:
        raise RuntimeError(
            "The warning agent cannot reach the alert template catalogue. An empty "
            "catalogue would look like 'no template fits' and send an operator a question "
            "the platform made up."
        )


class _RefusingDirectory:
    """Stands in when core-api is unreachable. Same reasoning as the others."""

    async def targets_in(self, gn_division_codes: tuple[str, ...]) -> Any:
        raise RuntimeError(
            "The warning agent cannot reach the household directory. An alert dispatched "
            "to nobody while reporting success is the worst available outcome."
        )

    async def reach(self, gn_division_codes: tuple[str, ...]) -> Any:
        raise RuntimeError("The warning agent cannot reach core-api for division coverage.")


class _RefusingDispatcher:
    """Stands in when there is nowhere to send an alert."""

    async def dispatch(self, order: DispatchOrder) -> Any:
        raise RuntimeError(
            "The warning agent has no dispatcher configured. Nothing was sent, and this "
            "run refuses rather than recording a fan-out that never happened."
        )

    async def receipts(self, *, alert_key: str) -> Any:
        return []


def _eval_build(checkpointer: Any) -> Any:
    """Imported lazily so the production graph does not depend on the eval one."""
    from agent_svc.agents.warning.evaluation import build as build_eval

    return build_eval(checkpointer)


SPEC: Final = AgentSpec(
    name=AGENT,
    subject_type=SUBJECT_TYPE,
    build=build,
    description=(
        "Turns an impact forecast into a trilingual, CAP-compliant alert: selects a "
        "natively reviewed template, resolves targets and languages, chooses the channel "
        "mix, dispatches, and reports who was probably not reached."
    ),
    degraded_note=(
        "Template selection falls back to a documented (hazard, impact class) matrix and "
        "the channel mix to a fixed severity matrix - both fully functional, slightly less "
        "well targeted. Targeting, language routing, CAP validation, the quiet-hours rule, "
        "the fatigue suppression and the gap report never touch a model at all, so with "
        "the provider down the same alert reaches the same people over the same channels."
    ),
    gated=True,
    eval_build=_eval_build,
)


__all__ = [
    "AGENT",
    "SPEC",
    "WarningState",
    "build",
    "build_nodes",
    "event_and_class",
    "subject_for",
]


# `WarningTarget` and `AlertTemplate` are imported for the type signatures above and are
# part of what a caller building this graph needs; re-exported so a wiring module does not
# have to import from two places.
__all__ += ["AlertTemplate", "WarningTarget"]
