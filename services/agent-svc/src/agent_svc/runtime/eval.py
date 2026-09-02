"""The evaluation harness: what an agent actually does, written down.

```bash
python -m agent_svc.runtime.eval --agent noop --fixtures data/fixtures/smoke
make eval AGENT=noop
```

Runs an agent over labelled fixtures and writes a markdown report to `artifacts/eval/`.
These reports are what goes in front of a ministry or a judge, so they are built as an
artefact rather than printed — a number nobody can re-read a week later is not evidence.

Four things it measures, and the second is the one that matters most:

**Accuracy against the labels.** Per case and in aggregate, and the report names the cases
that were wrong. An accuracy figure with no failing case list is one nobody can act on.

**Calibration (ECE), with a reliability diagram.** `AgentOutput.confidence` drives real
gates: below a threshold the run stops and waits for a person. That only means something if
0.9 confidence is right about nine times in ten. An uncalibrated confidence used as a gate
is *worse* than no gate, because it looks like a safety property and is not one — so the
number is measured and shown, not asserted.

**Latency, tokens and cost.** p50 and p95 rather than a mean: the mean hides the run that
took eleven seconds while a dispatcher watched a spinner.

**The human-review rate, and whether review changed the outcome.** Both halves are needed. A
low review rate on an agent that is often wrong is a gate that is not firing; a high review
rate where review almost never changes anything is a queue burning operator attention for
nothing. Neither is visible from accuracy alone.

Fixtures are JSONL, one case per line — see `data/fixtures/smoke/noop.jsonl`. A case that
expects a human decision carries the answer to give, so the reviewed path is exercised too
rather than being the part nobody measures.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from langgraph.types import Command

from agent_svc.agents import spec_named
from agent_svc.runtime.checkpoint import config_for, memory_checkpointer
from agent_svc.runtime.registry import AgentRegistry, AgentSpec
from agent_svc.runtime.state import initial_state, thread_id_for

# Ten equal-width bins, the convention ECE is usually reported with. Fewer hides
# miscalibration; more leaves bins with one case in them, where the "accuracy" of the bin is
# 0 or 1 and the diagram becomes noise.
BINS: Final = 10

DEFAULT_FIXTURES: Final = Path("data/fixtures/smoke")
DEFAULT_OUTPUT: Final = Path("artifacts/eval")

# The gate CI runs at. Deliberately not perfect scores: a threshold nobody can pass is one
# somebody deletes. Overridden per fixture set by a `thresholds.json` beside the cases.
DEFAULT_MIN_ACCURACY: Final = 0.90
DEFAULT_MAX_ECE: Final = 0.15


@dataclass(frozen=True, slots=True)
class Case:
    """One labelled example."""

    id: str
    input: dict[str, Any]
    label: dict[str, Any]
    subject_id: str
    expect_human_review: bool = False
    human: dict[str, Any] | None = None

    @staticmethod
    def from_json(raw: dict[str, Any], *, index: int) -> Case:
        case_id = str(raw.get("id") or f"case-{index}")
        return Case(
            id=case_id,
            input=dict(raw.get("input", {})),
            label=dict(raw.get("label", {})),
            subject_id=str(raw.get("subject_id") or case_id),
            expect_human_review=bool(raw.get("expect_human_review", False)),
            human=raw.get("human"),
        )


@dataclass(frozen=True, slots=True)
class CaseResult:
    """What happened on one case."""

    case_id: str
    correct: bool

    # Whether the *agent's own* answer was right, before anybody reviewed it. Separate from
    # `correct`, and the separation is not pedantry: a reviewed case is correct because a
    # person made it correct. Scoring calibration on that would measure the reviewer, and
    # would report every agent that routes to a human as perfectly calibrated.
    agent_correct: bool
    confidence: float
    reviewed: bool
    review_changed_outcome: bool
    latency_ms: float
    tokens: int
    cost_usd: float
    predicted: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    gate_matched_expectation: bool = True
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Report:
    """The aggregate, and everything needed to render it."""

    agent: str
    fixtures: str
    generated_at: datetime
    results: list[CaseResult]
    min_accuracy: float
    max_ece: float

    @property
    def scored(self) -> list[CaseResult]:
        """Cases that produced an answer. A crash is counted as a failure, not dropped."""
        return list(self.results)

    @property
    def accuracy(self) -> float:
        """What the platform got right, end to end — review included.

        This is the number a ministry cares about: the answer that came out, however it
        was arrived at.
        """
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.correct) / len(self.results)

    @property
    def agent_accuracy(self) -> float:
        """What the agent got right on its own.

        Lower than `accuracy` by exactly the value the human gates add. If the two are
        equal, review is changing nothing and the queue is pure cost.
        """
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.agent_correct) / len(self.results)

    @property
    def errors(self) -> list[CaseResult]:
        return [r for r in self.results if r.error]

    @property
    def review_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.reviewed) / len(self.results)

    @property
    def review_changed_rate(self) -> float:
        """Of the cases a person looked at, how often they changed the answer.

        Near zero means the gate is asking about things the agent already had right, which
        is attention spent for nothing. Near one means the agent is routing correctly but
        is wrong whenever it hesitates — both are actionable, and neither shows up in
        accuracy.
        """
        reviewed = [r for r in self.results if r.reviewed]
        if not reviewed:
            return 0.0
        return sum(1 for r in reviewed if r.review_changed_outcome) / len(reviewed)

    @property
    def gate_agreement(self) -> float:
        """How often the agent asked for a person exactly when the fixture expected it."""
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.gate_matched_expectation) / len(self.results)

    def latency(self, quantile: float) -> float:
        values = sorted(r.latency_ms for r in self.results)
        if not values:
            return 0.0
        # Nearest-rank rather than interpolation: with a smoke set of ten cases,
        # interpolating a p95 invents a number between two real runs.
        index = min(len(values) - 1, max(0, round(quantile * len(values)) - 1))
        return values[index]

    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.results)

    @property
    def total_tokens(self) -> int:
        return sum(r.tokens for r in self.results)

    @property
    def bins(self) -> list[tuple[float, float, int, float, float]]:
        """The reliability diagram: (low, high, count, mean confidence, accuracy)."""
        out: list[tuple[float, float, int, float, float]] = []
        for index in range(BINS):
            low, high = index / BINS, (index + 1) / BINS
            # The top bin is closed so a confidence of exactly 1.0 has somewhere to go.
            members = [
                r
                for r in self.results
                if (low <= r.confidence < high) or (index == BINS - 1 and r.confidence == 1.0)
            ]
            if not members:
                continue
            mean_confidence = statistics.fmean(r.confidence for r in members)
            # The agent's own hit rate, not the post-review one: `confidence` is a
            # statement about what the agent believes, so calibrating it against an
            # answer a person supplied would make every gated agent look perfect.
            accuracy = sum(1 for r in members if r.agent_correct) / len(members)
            out.append((low, high, len(members), mean_confidence, accuracy))
        return out

    @property
    def ece(self) -> float:
        """Expected calibration error: the gap between stated confidence and being right,
        weighted by how many cases fall in each bin."""
        if not self.results:
            return 0.0
        total = len(self.results)
        return sum(
            (count / total) * abs(accuracy - mean_confidence)
            for _, _, count, mean_confidence, accuracy in self.bins
        )

    @property
    def passed(self) -> bool:
        return self.accuracy >= self.min_accuracy and self.ece <= self.max_ece and not self.errors


def load_cases(path: Path, *, agent: str | None = None) -> list[Case]:
    """Read one agent's cases from a fixture directory, or one file.

    A directory holding `noop.jsonl` and `forecast.jsonl` must not feed both sets to
    whichever agent was named: the cases are labelled for one agent's output, and scoring
    an agent against another's labels reports a confident 0%. So `{agent}.jsonl` wins when
    it exists, and only a directory with no file for this agent falls back to everything
    in it.

    Raises:
        FileNotFoundError: naming the path. A harness that silently reports 0 cases as a
            pass is one that goes green after somebody moves the fixtures.
    """
    if not path.is_dir():
        files = [path]
    elif agent and (path / f"{agent}.jsonl").exists():
        files = [path / f"{agent}.jsonl"]
    else:
        files = sorted(path.glob("*.jsonl"))
    if not files or not any(f.exists() for f in files):
        raise FileNotFoundError(f"No .jsonl fixtures at {path}")

    cases: list[Case] = []
    for file in files:
        for line in file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            cases.append(Case.from_json(json.loads(stripped), index=len(cases)))

    if not cases:
        raise FileNotFoundError(f"{path} holds no cases")
    return cases


def load_thresholds(path: Path, *, agent: str | None = None) -> tuple[float, float]:
    """The pass mark for this fixture set, and for this agent within it.

    Beside the fixtures rather than in the code, because the bar for a ten-case smoke set
    and a thousand-case regression set are not the same bar.

    Per-agent under `agents`, because agents in the same directory are not comparable. A
    deterministic classifier over three keywords should be near-perfect; a threshold engine
    whose fixture set deliberately includes cases it cannot see - a gauge blackout, an
    unsurveyed division - must not be, or its low-confidence bin would be empty and the
    calibration number would mean nothing. Holding both to one accuracy bar would force
    somebody to delete the cases that make the calibration honest.
    """
    file = (path if path.is_dir() else path.parent) / "thresholds.json"
    if not file.exists():
        return DEFAULT_MIN_ACCURACY, DEFAULT_MAX_ECE

    data = json.loads(file.read_text(encoding="utf-8"))
    settings = dict(data)
    if agent:
        settings.update(data.get("agents", {}).get(agent, {}))
    return (
        float(settings.get("min_accuracy", DEFAULT_MIN_ACCURACY)),
        float(settings.get("max_ece", DEFAULT_MAX_ECE)),
    )


def _matches(predicted: dict[str, Any], label: dict[str, Any]) -> bool:
    """Correct means every labelled field matches. Unlabelled fields are not judged."""
    return all(str(predicted.get(key)) == str(value) for key, value in label.items())


async def run_case(graph: Any, spec: AgentSpec, case: Case) -> CaseResult:
    """Run one case, review it if it pauses, and time the whole thing.

    The clock covers the review too. A run that pauses is not "fast": from the outside it
    is a decision that has not been made, and pretending otherwise makes every gated agent
    look better than it is.
    """
    thread_id = thread_id_for(spec.name, spec.subject_type, case.subject_id)
    config = config_for(thread_id)
    state = initial_state(
        agent=spec.name,
        subject_type=spec.subject_type,
        subject_id=case.subject_id,
        correlation_id=f"eval-{case.id}",
    )
    state["output"] = dict(case.input)

    started = time.perf_counter()
    try:
        values = await graph.ainvoke(state, config)
        reviewed = bool(values.get("__interrupt__"))
        before_review = dict(values.get("output", {}))

        if reviewed:
            if case.human is None:
                # The agent asked and the fixture has no answer. Not an error in the agent:
                # it is a hole in the fixture set, and a review path nobody measures is one
                # that regresses quietly.
                elapsed = (time.perf_counter() - started) * 1000
                return CaseResult(
                    case_id=case.id,
                    correct=False,
                    agent_correct=_matches(before_review, case.label),
                    confidence=float(before_review.get("confidence", 0.0)),
                    reviewed=True,
                    review_changed_outcome=False,
                    latency_ms=elapsed,
                    tokens=int(values.get("budgets", {}).get("tokens", 0)),
                    cost_usd=float(values.get("budgets", {}).get("cost_usd", 0.0)),
                    predicted=before_review,
                    expected=case.label,
                    gate_matched_expectation=case.expect_human_review,
                    error="paused for a human and the fixture supplies no decision",
                )
            decision = {
                "subject_id": case.subject_id,
                "decided_by": "eval-harness",
                "decided_at": datetime.now(UTC).isoformat(),
                "approved": True,
                **case.human,
            }
            values = await graph.ainvoke(Command(resume=decision), config)

        elapsed = (time.perf_counter() - started) * 1000
        output = dict(values.get("output", {}))
        budgets = dict(values.get("budgets", {}))

        return CaseResult(
            case_id=case.id,
            correct=_matches(output, case.label),
            agent_correct=_matches(before_review, case.label),
            # The confidence the *agent* stated, before a person overrode it. Scoring
            # calibration on a post-review value would measure the reviewer, not the model.
            confidence=_stated_confidence(before_review, output),
            reviewed=reviewed,
            review_changed_outcome=reviewed and not _same_answer(before_review, output),
            latency_ms=elapsed,
            tokens=int(budgets.get("tokens", 0)),
            cost_usd=float(budgets.get("cost_usd", 0.0)),
            predicted=output,
            expected=case.label,
            gate_matched_expectation=reviewed == case.expect_human_review,
        )
    except Exception as exc:  # noqa: BLE001 - a crashed case is a failed case, not a lost one
        elapsed = (time.perf_counter() - started) * 1000
        return CaseResult(
            case_id=case.id,
            correct=False,
            agent_correct=False,
            confidence=0.0,
            reviewed=False,
            review_changed_outcome=False,
            latency_ms=elapsed,
            tokens=0,
            cost_usd=0.0,
            expected=case.label,
            gate_matched_expectation=not case.expect_human_review,
            error=f"{type(exc).__name__}: {exc}",
        )


def _stated_confidence(before: dict[str, Any], after: dict[str, Any]) -> float:
    """The confidence the *agent* stated, before a person overrode it.

    Read from the pre-review output, because scoring calibration on a post-review value
    would measure the reviewer rather than the model. A non-numeric value scores 0 rather
    than raising: a malformed output is a case the agent got wrong, not a crashed eval run.
    """
    value = before.get("confidence", after.get("confidence", 0.0))
    return float(value) if isinstance(value, int | float) else 0.0


def _same_answer(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Whether review left the substance alone.

    `provenance` and the review flags always change when a person answers — that is the
    mechanism, not the outcome — so comparing whole dicts would report every reviewed case
    as changed and the metric would say nothing.
    """
    ignored = {"provenance", "needs_human_review", "review_reason", "confidence", "reasoning"}
    return {k: v for k, v in before.items() if k not in ignored} == {
        k: v for k, v in after.items() if k not in ignored
    }


async def evaluate(
    agent: str,
    fixtures: Path,
    *,
    min_accuracy: float | None = None,
    max_ece: float | None = None,
) -> Report:
    """Run every case in a fixture set against one agent, on a fresh in-process checkpointer.

    In-process deliberately: an eval that writes into the durable checkpoint table would
    put its own synthetic threads into the production approval inbox.
    """
    spec = spec_named(agent)
    registry = AgentRegistry()
    registry.register(spec)
    registry.compile_all(memory_checkpointer(), for_eval=True)
    graph = registry.graph(agent)

    cases = load_cases(fixtures, agent=agent)
    file_accuracy, file_ece = load_thresholds(fixtures, agent=agent)

    results = [await run_case(graph, spec, case) for case in cases]

    return Report(
        agent=agent,
        fixtures=fixtures.as_posix(),
        generated_at=datetime.now(UTC),
        results=results,
        min_accuracy=file_accuracy if min_accuracy is None else min_accuracy,
        max_ece=file_ece if max_ece is None else max_ece,
    )


def render_markdown(report: Report) -> str:
    """The report as it is handed to somebody who was not in the room."""
    verdict = "PASS" if report.passed else "FAIL"
    lines = [
        f"# Agent evaluation — `{report.agent}`",
        "",
        f"**{verdict}** · {len(report.results)} cases · "
        f"{report.generated_at.isoformat(timespec='seconds')}",
        "",
        f"Fixtures: `{report.fixtures}`",
        "",
        "## Summary",
        "",
        "| Metric | Value | Gate |",
        "| --- | --- | --- |",
        f"| Accuracy, as delivered | {report.accuracy:.1%} | ≥ {report.min_accuracy:.0%} |",
        f"| Accuracy, agent alone | {report.agent_accuracy:.1%} | — |",
        f"| Calibration error (ECE) | {report.ece:.3f} | ≤ {report.max_ece:.2f} |",
        f"| Human-review rate | {report.review_rate:.1%} | — |",
        f"| Review changed the outcome | {report.review_changed_rate:.1%} of reviewed | — |",
        f"| Gate fired as expected | {report.gate_agreement:.1%} | — |",
        f"| Latency p50 | {report.latency(0.50):.0f} ms | — |",
        f"| Latency p95 | {report.latency(0.95):.0f} ms | — |",
        f"| Tokens | {report.total_tokens:,} | — |",
        f"| Cost | ${report.total_cost_usd:.4f} | — |",
        "",
    ]

    if report.total_tokens == 0:
        lines += [
            "> No model calls were made. This agent ran its deterministic path end to "
            "end — the same code a provider outage falls back to — so the token and cost "
            "figures are zero rather than missing.",
            "",
        ]

    lines += [
        "## Calibration",
        "",
        "How often the agent was right, at each level of confidence it stated. "
        "`confidence` drives real gates, so the diagonal is the property that matters: a "
        "bin at 0.9 confidence should be right about nine times in ten.",
        "",
        "Scored on the agent's own answer, before review. A reviewed case is correct "
        "because a person made it correct, and calibrating against that would report "
        "every agent that routes to a human as perfectly calibrated.",
        "",
        "| Confidence | Cases | Stated | Actual | |",
        "| --- | --- | --- | --- | --- |",
    ]
    for low, high, count, stated, actual in report.bins:
        bar = "█" * round(actual * 20)
        lines.append(f"| {low:.1f}-{high:.1f} | {count} | {stated:.2f} | {actual:.2f} | `{bar}` |")
    if not report.bins:
        lines.append("| — | 0 | — | — | |")

    failures = [r for r in report.results if not r.correct]
    lines += ["", "## Cases that failed", ""]
    if not failures:
        lines.append("None.")
    else:
        lines += ["| Case | Expected | Got | Reviewed | Note |", "| --- | --- | --- | --- | --- |"]
        for result in failures:
            note = result.error or ""
            lines.append(
                f"| `{result.case_id}` | `{result.expected}` | `{result.predicted}` | "
                f"{'yes' if result.reviewed else 'no'} | {note} |"
            )

    lines += [
        "",
        "## Every case",
        "",
        "| Case | Delivered | Agent alone | Confidence | Reviewed | Changed by review | Latency |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in report.results:
        lines.append(
            f"| `{result.case_id}` | {'✓' if result.correct else '✗'} | "
            f"{'✓' if result.agent_correct else '✗'} | "
            f"{result.confidence:.2f} | {'yes' if result.reviewed else 'no'} | "
            f"{'yes' if result.review_changed_outcome else 'no'} | "
            f"{result.latency_ms:.0f} ms |"
        )

    # An agent may contribute its own section. See `AgentSpec.eval_sections` for why:
    # accuracy and calibration do not capture every agent's quality, and the anomaly
    # agent's false-positive rate per detector is a metric ADR-009 requires reported.
    addendum = _agent_sections(report)
    if addendum:
        lines += ["", addendum]

    lines += ["", f"_Generated by `agent_svc.runtime.eval`. Verdict: **{verdict}**._", ""]
    return "\n".join(lines)


def _agent_sections(report: Report) -> str:
    """This agent's own report section, or an empty string.

    Failing to build one must not lose the report: accuracy and calibration are already
    computed and are what CI gates on, so a broken addendum becomes a note in the report
    rather than an exception that discards it.
    """
    try:
        spec = spec_named(report.agent)
    except KeyError:
        return ""
    if spec.eval_sections is None:
        return ""
    try:
        return str(spec.eval_sections(report))
    except Exception as error:  # noqa: BLE001 - a broken addendum never loses the report
        return (
            f"## {report.agent} metrics"
            + "\n\n"
            + "_This agent's own report section could not be built "
            + f"({type(error).__name__}). The figures above are unaffected._"
        )


def write_report(report: Report, output_dir: Path) -> Path:
    """Write the markdown, and a stable `latest` copy for CI to diff against."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at.strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / f"{report.agent}-{stamp}.md"
    markdown = render_markdown(report)
    path.write_text(markdown, encoding="utf-8")
    (output_dir / f"{report.agent}-latest.md").write_text(markdown, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m agent_svc.runtime.eval",
        description="Run an agent against labelled fixtures and write a markdown report.",
    )
    parser.add_argument("--agent", required=True, help="Which agent to evaluate, e.g. noop")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-accuracy", type=float, default=None)
    parser.add_argument("--max-ece", type=float, default=None)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print the report instead of writing it. For a quick local look.",
    )
    args = parser.parse_args(argv)

    try:
        report = asyncio.run(
            evaluate(
                args.agent,
                args.fixtures,
                min_accuracy=args.min_accuracy,
                max_ece=args.max_ece,
            )
        )
    except (KeyError, FileNotFoundError) as exc:
        # The two mistakes anyone actually makes on this command line. Reported as a
        # sentence, not a traceback.
        sys.stderr.write(f"error: {exc}\n")
        return 2

    if args.no_write:
        sys.stdout.write(render_markdown(report))
    else:
        path = write_report(report, args.out)
        sys.stdout.write(f"wrote {path}\n")

    sys.stdout.write(
        f"{args.agent}: accuracy {report.accuracy:.1%} "
        f"(agent alone {report.agent_accuracy:.1%}, gate {report.min_accuracy:.0%}), "
        f"ECE {report.ece:.3f} "
        f"(gate {report.max_ece:.2f}), review rate {report.review_rate:.1%}\n"
    )
    if not report.passed:
        # Non-zero so CI fails on a regression rather than filing a report nobody opens.
        for failure in report.errors:
            sys.stderr.write(f"  {failure.case_id}: {failure.error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
