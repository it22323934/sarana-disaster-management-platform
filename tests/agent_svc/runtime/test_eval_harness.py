"""The evaluation harness.

The reports this produces are what goes in front of a ministry, so the arithmetic has to be
right in the cases where getting it wrong would flatter the platform. That is what most of
these check.

The one to read first is `test_calibration_is_scored_on_the_agents_own_answer`. Scoring a
reviewed case as a hit for the model reports every agent that routes to a human as perfectly
calibrated — which would make ECE, the number that justifies using `confidence` as a gate at
all, meaningless in exactly the direction nobody would notice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_svc.runtime.eval import (
    Case,
    CaseResult,
    Report,
    evaluate,
    load_cases,
    load_thresholds,
    main,
    render_markdown,
    write_report,
)

SMOKE = Path("data/fixtures/smoke")


def result(
    case_id: str,
    *,
    correct: bool = True,
    agent_correct: bool | None = None,
    confidence: float = 0.9,
    reviewed: bool = False,
    changed: bool = False,
    latency_ms: float = 5.0,
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        correct=correct,
        agent_correct=correct if agent_correct is None else agent_correct,
        confidence=confidence,
        reviewed=reviewed,
        review_changed_outcome=changed,
        latency_ms=latency_ms,
        tokens=0,
        cost_usd=0.0,
    )


def report(results: list[CaseResult], *, min_accuracy: float = 0.9, max_ece: float = 0.2) -> Report:
    from datetime import UTC, datetime

    return Report(
        agent="noop",
        fixtures="test",
        generated_at=datetime.now(UTC),
        results=results,
        min_accuracy=min_accuracy,
        max_ece=max_ece,
    )


# --------------------------------------------------------------------------------------
# The definition of done
# --------------------------------------------------------------------------------------


async def test_the_reference_agent_passes_its_own_smoke_set() -> None:
    """`python -m agent_svc.runtime.eval --agent noop --fixtures data/fixtures/smoke`.

    Build file 12's definition of done, run as a test so it cannot rot between releases.
    It reaches no model provider, no API key and no network — an agent that needs a
    provider to prove the runtime works cannot prove it when the provider is down.
    """
    scored = await evaluate("noop", SMOKE)

    assert scored.passed, f"accuracy {scored.accuracy}, ECE {scored.ece}"
    assert len(scored.results) == 10
    assert not scored.errors


def test_the_command_line_exits_zero_on_a_pass(tmp_path: Path) -> None:
    assert main(["--agent", "noop", "--fixtures", str(SMOKE), "--out", str(tmp_path)]) == 0
    assert (tmp_path / "noop-latest.md").exists()


def test_a_mistyped_agent_name_says_which_ones_exist(capsys: pytest.CaptureFixture[str]) -> None:
    """The mistake people actually make on this command line, answered in a sentence
    rather than a traceback."""
    code = main(["--agent", "forecats", "--fixtures", str(SMOKE)])

    assert code == 2
    assert "noop" in capsys.readouterr().err


def test_missing_fixtures_fail_rather_than_reporting_a_perfect_score(tmp_path: Path) -> None:
    """A harness that reports zero cases as a pass goes green the day somebody moves the
    fixtures, and stays green."""
    assert main(["--agent", "noop", "--fixtures", str(tmp_path / "nowhere")]) == 2


# --------------------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------------------


def test_calibration_is_scored_on_the_agents_own_answer() -> None:
    """The one that would silently flatter every gated agent.

    Four cases where the agent said 0.3 and was wrong, and a person fixed all four. As
    delivered the platform got them all right. The agent did not, and `confidence` is a
    statement about what the *agent* believes — so the reliability diagram must show a bin
    at 0.3 confidence with an accuracy of 0.0.
    """
    scored = report(
        [
            result(f"c{i}", correct=True, agent_correct=False, confidence=0.3, reviewed=True)
            for i in range(4)
        ]
    )

    assert scored.accuracy == 1.0
    assert scored.agent_accuracy == 0.0

    (_, _, count, stated, actual) = scored.bins[0]
    assert count == 4
    assert stated == pytest.approx(0.3)
    assert actual == 0.0
    assert scored.ece == pytest.approx(0.3)


def test_a_perfectly_calibrated_agent_scores_zero() -> None:
    """Ten cases at 0.9 confidence, nine of them right."""
    results = [result(f"c{i}", correct=i < 9, confidence=0.9) for i in range(10)]

    assert report(results).ece == pytest.approx(0.0, abs=1e-9)


def test_an_overconfident_agent_is_caught() -> None:
    """0.95 stated, half right. This is the failure ECE exists to name: a gate that never
    fires because the agent is always sure, and is wrong half the time."""
    results = [result(f"c{i}", correct=i % 2 == 0, confidence=0.95) for i in range(10)]

    scored = report(results)

    assert scored.ece == pytest.approx(0.45)
    assert not scored.passed


def test_the_top_bin_includes_a_confidence_of_exactly_one() -> None:
    """Bins are half-open, so 1.0 would fall outside every one of them and vanish from the
    diagram — taking the most confident predictions the agent made with it."""
    scored = report([result("certain", confidence=1.0)])

    assert scored.bins
    assert scored.bins[0][2] == 1


def test_empty_bins_are_not_drawn() -> None:
    """A bin with no cases has no accuracy, and rendering it as 0 draws a reliability
    diagram that looks catastrophic and is not."""
    scored = report([result("a", confidence=0.95), result("b", confidence=0.95)])

    assert len(scored.bins) == 1


# --------------------------------------------------------------------------------------
# The review metrics
# --------------------------------------------------------------------------------------


async def test_review_that_changes_nothing_is_distinguished_from_review_that_helps() -> None:
    """Both halves are needed to read a gate.

    Review that never changes anything is a queue burning operator attention; review that
    changes everything means the agent routes well and is wrong whenever it hesitates.
    Neither shows up in accuracy.
    """
    scored = await evaluate("noop", SMOKE)

    assert scored.review_rate == pytest.approx(0.4)
    # Two of the four reviewed cases the agent had already got right; a person confirming
    # `unknown` is not a changed outcome.
    assert scored.review_changed_rate == pytest.approx(0.5)


def test_a_reviewed_case_is_not_counted_as_changed_for_its_provenance() -> None:
    """`provenance` and the review flags always change when a person answers — that is the
    mechanism, not the outcome. Comparing whole dicts would report every reviewed case as
    changed, and the metric would say nothing at all."""
    from agent_svc.runtime.eval import _same_answer

    before = {
        "category": "flood",
        "provenance": "DETERMINISTIC",
        "needs_human_review": True,
        "review_reason": "unsure",
        "confidence": 0.3,
    }
    after = {
        "category": "flood",
        "provenance": "HUMAN",
        "needs_human_review": False,
        "review_reason": "unsure",
        "confidence": 0.3,
    }

    assert _same_answer(before, after)
    assert not _same_answer(before, {**after, "category": "landslide"})


async def test_the_gate_firing_on_the_wrong_cases_is_its_own_metric() -> None:
    """Separate from accuracy, because an agent that is right about everything while
    asking a person about half of it is a different problem from one that is wrong."""
    scored = await evaluate("noop", SMOKE)

    assert scored.gate_agreement == 1.0


async def test_a_pause_with_no_fixture_answer_is_reported_as_a_hole(tmp_path: Path) -> None:
    """Not silently skipped. A review path nobody measures is one that regresses quietly."""
    fixtures = tmp_path / "cases.jsonl"
    fixtures.write_text(
        json.dumps(
            {
                "id": "unanswered",
                "subject_id": "s1",
                "input": {"text": "no hazard word here"},
                "label": {"category": "flood"},
                "expect_human_review": True,
            }
        ),
        encoding="utf-8",
    )

    scored = await evaluate("noop", fixtures)

    assert not scored.passed
    assert "supplies no decision" in (scored.errors[0].error or "")


# --------------------------------------------------------------------------------------
# Latency, and what the harness measures it over
# --------------------------------------------------------------------------------------


def test_p95_is_a_run_that_actually_happened() -> None:
    """Nearest-rank, not interpolation. On a ten-case set, interpolating invents a number
    between two real runs and puts it in a report somebody will quote."""
    results = [result(f"c{i}", latency_ms=float(i)) for i in range(10)]

    scored = report(results)

    assert scored.latency(0.50) == 4.0
    assert scored.latency(0.95) in {9.0}


def test_latency_on_an_empty_run_is_zero_rather_than_a_crash() -> None:
    assert report([]).latency(0.95) == 0.0


# --------------------------------------------------------------------------------------
# The report itself
# --------------------------------------------------------------------------------------


def test_the_report_names_the_cases_that_failed() -> None:
    """An accuracy figure with no failing case list is one nobody can act on."""
    scored = report(
        [result("good"), result("bad", correct=False, confidence=0.9)], min_accuracy=0.9
    )

    markdown = render_markdown(scored)

    assert "`bad`" in markdown
    assert "FAIL" in markdown


async def test_a_run_with_no_model_calls_says_so() -> None:
    """Rather than showing a bare $0.0000 that reads like a broken meter."""
    markdown = render_markdown(await evaluate("noop", SMOKE))

    assert "No model calls were made" in markdown
    assert "deterministic path" in markdown


async def test_the_report_shows_delivered_and_agent_accuracy_separately() -> None:
    """The gap between them is exactly what the human gates are buying."""
    markdown = render_markdown(await evaluate("noop", SMOKE))

    assert "Accuracy, as delivered" in markdown
    assert "Accuracy, agent alone" in markdown


async def test_a_latest_copy_is_written_for_ci_to_read(tmp_path: Path) -> None:
    """CI needs one stable filename; a human wants the timestamped history. Both."""
    scored = await evaluate("noop", SMOKE)

    path = write_report(scored, tmp_path)

    assert path.exists()
    assert (tmp_path / "noop-latest.md").read_text(encoding="utf-8") == path.read_text(
        encoding="utf-8"
    )


async def test_the_report_carries_a_portable_fixture_path() -> None:
    """These reports get read on machines that are not the one that made them."""
    scored = await evaluate("noop", SMOKE)

    assert "\\" not in scored.fixtures


# --------------------------------------------------------------------------------------
# Fixtures and thresholds
# --------------------------------------------------------------------------------------


def test_the_smoke_set_is_loadable_and_labelled() -> None:
    cases = load_cases(SMOKE, agent="noop")

    assert len(cases) == 10
    for case in cases:
        assert case.label, f"{case.id} has no label to score against"
        assert case.input, f"{case.id} has no input"


def test_every_case_that_expects_review_supplies_the_answer() -> None:
    """Otherwise the reviewed path is the part of the graph nobody measures."""
    for case in load_cases(SMOKE, agent="noop"):
        if case.expect_human_review:
            assert case.human is not None, f"{case.id} expects review but answers nothing"


def test_subject_ids_are_unique_across_the_set() -> None:
    """The thread id is derived from the subject, so two cases sharing one would land on
    the same thread and the second would rejoin the first's run."""
    subjects = [case.subject_id for case in load_cases(SMOKE, agent="noop")]

    assert len(subjects) == len(set(subjects))


def test_thresholds_come_from_beside_the_fixtures() -> None:
    """The bar for a ten-case smoke set and a thousand-case regression set are not the
    same bar, so the bar lives with the cases."""
    min_accuracy, max_ece = load_thresholds(SMOKE)

    assert min_accuracy == pytest.approx(0.9)
    assert max_ece == pytest.approx(0.2)


def test_a_fixture_set_with_no_thresholds_falls_back_to_the_defaults(tmp_path: Path) -> None:
    from agent_svc.runtime.eval import DEFAULT_MAX_ECE, DEFAULT_MIN_ACCURACY

    assert load_thresholds(tmp_path) == (DEFAULT_MIN_ACCURACY, DEFAULT_MAX_ECE)


def test_a_case_without_an_id_still_gets_one() -> None:
    """So a hand-written fixture line does not produce a report row labelled `None`."""
    case = Case.from_json({"input": {"text": "x"}, "label": {"category": "flood"}}, index=3)

    assert case.id
    assert case.subject_id == case.id


def test_a_crashing_case_counts_as_a_failure_rather_than_disappearing() -> None:
    """Dropping it would let a graph that raises on every third input score 100%."""
    scored = report(
        [
            result("ok"),
            CaseResult(
                case_id="boom",
                correct=False,
                agent_correct=False,
                confidence=0.0,
                reviewed=False,
                review_changed_outcome=False,
                latency_ms=1.0,
                tokens=0,
                cost_usd=0.0,
                error="RuntimeError: the checkpointer is unreachable",
            ),
        ]
    )

    assert scored.accuracy == 0.5
    assert not scored.passed


def test_one_agents_fixtures_are_not_fed_to_another(tmp_path: Path) -> None:
    """A fixture directory holds a file per agent.

    Cases are labelled for one agent's output; scoring an agent against another's labels
    reports a confident 0% and reads like a broken agent rather than a broken harness.
    """
    (tmp_path / "noop.jsonl").write_text(
        json.dumps({"id": "mine", "input": {"text": "flood"}, "label": {"category": "flood"}}),
        encoding="utf-8",
    )
    (tmp_path / "forecast.jsonl").write_text(
        json.dumps({"id": "theirs", "input": {}, "label": {"impact_class": 3}}),
        encoding="utf-8",
    )

    cases = load_cases(tmp_path, agent="noop")

    assert [case.id for case in cases] == ["mine"]


def test_a_directory_with_no_file_for_this_agent_still_loads(tmp_path: Path) -> None:
    """So a single-file fixture set does not have to be renamed to be usable."""
    (tmp_path / "cases.jsonl").write_text(
        json.dumps({"id": "only", "input": {"text": "flood"}, "label": {"category": "flood"}}),
        encoding="utf-8",
    )

    assert [case.id for case in load_cases(tmp_path, agent="noop")] == ["only"]
