"""The anomaly agent, in the shape the evaluation harness can score.

```bash
make eval AGENT=ledger_anomaly
```

## Both rates, or neither

ADR-009 makes the false-positive rate a first-class tracked metric, and build file 17
requires it in this report. The reason is worth restating: **a detection rate without a
false-positive rate is a number designed to impress rather than inform.** Any detector can
reach 100% detection by flagging everything, and the cost of that lands on GN officers in
the divisions that were hit hardest.

So each case here is one division with a label saying whether it *should* produce a flag,
and the report carries per-detector detection and false-positive counts side by side.

## The case that proves the design works

`severe-division-high-values` is the one to look at first. A division at impact class 4
producing high-value, clustered, fast assessments is producing exactly what the forecast
predicted, and it must produce **no flag**. Its twin, `low-impact-identical-profile`, has an
identical assessment profile at impact class 1 and must produce one.

If those two ever come out the same, the exposure normalisation has stopped working and the
agent is comparing divisions with each other again — which is the failure ADR-009 exists to
prevent, and it would be invisible in an aggregate accuracy number.

## What the confidence means here

The detectors are arithmetic and have no belief about themselves, so `confidence` is the
highest score any detector returned — how far from expectation the division sat. On a
no-flag case it is one minus that, so a division the agent is confidently clean about
reports high confidence. Inventing a separate number to fill the field would have been the
dishonest option.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

from langgraph.graph import END, START, StateGraph

from agent_svc.agents.ledger_anomaly import detectors, normalisation
from agent_svc.agents.ledger_anomaly.ports import Assessment, DivisionContext
from agent_svc.runtime.state import AgentState

BASE_TIME: Final = datetime(2026, 12, 5, 4, 0, tzinfo=UTC)


def assessments_from(raw: dict[str, Any]) -> list[Assessment]:
    """Build one division's assessments from a compact case description.

    A case says how many assessments, what share are total losses, how fast they were
    approved and how many were confirmed. Writing them out row by row in a fixture would
    make the interesting number - the shape of the division - impossible to see.
    """
    code = str(raw.get("gn_division_code", "LK-21-01-001"))
    count = int(raw.get("count", 20))
    total_loss_share = float(raw.get("total_loss_share", 0.1))
    approval_minutes = float(raw.get("approval_minutes", 60.0))
    confirmed_share = raw.get("confirmed_share")
    burst = bool(raw.get("burst", False))

    rows: list[Assessment] = []
    for index in range(count):
        is_total = index < round(count * total_loss_share)
        # A burst puts every assessment in one hour; otherwise they spread over a working
        # day, which is what an ordinary survey looks like.
        offset = timedelta(minutes=index * 2) if burst else timedelta(minutes=index * 25)
        assessed = BASE_TIME + offset
        confirmed = (
            None if confirmed_share is None else index < round(count * float(confirmed_share))
        )
        rows.append(
            Assessment(
                assessment_id=f"a-{code}-{index}",
                gn_division_code=code,
                ds_division_code=code.rsplit("-", 1)[0],
                district_code=code.rsplit("-", 2)[0],
                household_id=f"hh-{code}-{index}",
                category="HOUSE_FULL" if is_total else "HOUSEHOLD_GOODS",
                assessed_value_lkr=500_000 if is_total else 40_000,
                assessed_at=assessed,
                approved_at=assessed + timedelta(minutes=approval_minutes),
                citizen_confirmed=confirmed,
            )
        )
    return rows


def context_from(raw: dict[str, Any]) -> DivisionContext:
    """One division's exposure context, from the case."""
    return DivisionContext(
        gn_division_code=str(raw.get("gn_division_code", "LK-21-01-001")),
        impact_class=int(raw.get("impact_class", 0)),
        expected_households_affected=int(raw.get("expected_households_affected", 0)),
        forecast_confidence=float(raw.get("forecast_confidence", 0.8)),
        household_count=int(raw.get("household_count", 400)),
        cell_coverage_pct=raw.get("cell_coverage_pct"),
        permanent_housing_pct=raw.get("permanent_housing_pct"),
    )


async def scan_one_division(state: AgentState) -> dict[str, Any]:
    """Run every detector over the single division a case describes.

    The output keys are what the fixtures label against: `flagged` is the answer,
    `detectors_fired` names which, and both feed the per-detector rates the report prints.
    """
    raw = dict(state.get("output", {}))
    rows = assessments_from(raw)
    context = {raw.get("gn_division_code", "LK-21-01-001"): context_from(raw)}

    profiles = normalisation.build_profiles(rows, context)
    signals = detectors.run_all(profiles)

    # The eval scores the detectors, so the graph's own suppression threshold is applied
    # here rather than in `run_all` - a signal below it would never become a flag, and
    # counting it as a detection would overstate the agent.
    from agent_svc.agents.ledger_anomaly.graph import MIN_SCORE

    surviving = [signal for signal in signals if signal.score >= MIN_SCORE]
    fired = sorted({signal.detector for signal in surviving})
    top = max((signal.score for signal in surviving), default=0.0)

    return {
        "status": "COMPLETED",
        "output": {
            "flagged": bool(surviving),
            "detectors_fired": fired,
            "top_score": round(top, 4),
            "normalisable": all(profile.normalisable for profile in profiles),
            # The detectors have no belief about themselves. See the module docstring.
            "confidence": round(top if surviving else 1.0 - top, 4),
            "reasoning": (
                f"{len(surviving)} detector(s) fired: {', '.join(fired)}"
                if surviving
                else "no detector fired; this division is within what its own forecast predicted"
            ),
            "needs_human_review": False,
            "provenance": "DETERMINISTIC",
        },
        "notes": [f"{len(surviving)} signals"],
    }


def build(checkpointer: Any) -> Any:
    """A one-node graph over the detectors.

    Deliberately not the production graph: that one writes flags and calls a model for
    context, and an eval that raised flags would fill a review queue with fixtures.
    """
    builder = StateGraph(AgentState)
    builder.add_node("scan", scan_one_division)
    builder.add_edge(START, "scan")
    builder.add_edge("scan", END)
    return builder.compile(checkpointer=checkpointer)


def detector_rates(report: Any) -> str:
    """Detection and false-positive counts, per detector, as a markdown section.

    **Both, or neither.** ADR-009 makes the false-positive rate first-class and build file
    17 requires it in this report, for a reason worth restating every time somebody reads
    it: any detector reaches 100% detection by flagging everything, and the cost of that
    lands on GN officers in the divisions that were hit hardest.

    The rates are computed per detector from the cases each one fired on, so a detector
    that is quietly responsible for every false positive is visible rather than averaged
    away by the seven that behave.

    Attached to the agent through `AgentSpec.eval_sections`.
    """
    detected: dict[str, int] = {}
    false_positive: dict[str, int] = {}
    missed = 0
    correct_silence = 0

    for result in report.results:
        should_flag = str(result.expected.get("flagged", "")).lower() == "true"
        fired = list(result.predicted.get("detectors_fired", []))

        if should_flag and not fired:
            missed += 1
        if not should_flag and not fired:
            correct_silence += 1

        for detector in fired:
            if should_flag:
                detected[detector] = detected.get(detector, 0) + 1
            else:
                false_positive[detector] = false_positive.get(detector, 0) + 1

    names = sorted(set(detected) | set(false_positive))
    lines = [
        "## Detection and false positives, per detector",
        "",
        "Both rates or neither. ADR-009 makes the false-positive rate first-class because a "
        "detection rate on its own is a number designed to impress: any detector reaches "
        "100% detection by flagging everything, and the cost lands on the officers in the "
        "divisions that were hit hardest.",
        "",
        "| Detector | Fired on a case that should flag | Fired on one that should not |",
        "| --- | --- | --- |",
    ]
    if not names:
        lines.append("| _no detector fired on any case_ | 0 | 0 |")
    else:
        lines += [
            f"| `{name}` | {detected.get(name, 0)} | {false_positive.get(name, 0)} |"
            for name in names
        ]

    total_fp = sum(false_positive.values())
    should_flag_cases = sum(
        1 for result in report.results if str(result.expected.get("flagged", "")).lower() == "true"
    )
    clean_cases = len(report.results) - should_flag_cases

    lines += [
        "",
        f"**{total_fp} false positive(s)** across {clean_cases} case(s) that should raise "
        f"nothing; **{missed} missed** across {should_flag_cases} that should raise "
        f"something. {correct_silence} clean division(s) were correctly left alone.",
        "",
        "A missed detection is recoverable - the pattern is still in the ledger and the next "
        "scan sees it. A false positive puts a question against a division that did nothing "
        "unusual, and somebody has to answer it.",
    ]
    return "\n".join(lines)
