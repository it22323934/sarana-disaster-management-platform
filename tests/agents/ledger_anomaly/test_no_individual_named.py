"""The post-check that stands between a model and somebody's career.

Build file 17 names this file in its definition of done. ADR-009 is why: a flag against a
named GN officer can end a career on a statistical artifact, and the divisions that were hit
hardest will legitimately look like outliers.

Three properties, tested at the level each is enforced:

**No individual may be named** — checked structurally, at any depth in the document, because
a name in `innocent_explanations[2]` names somebody just as surely as one in the summary.

**No accusatory or conclusive language** — the deny-list is shipped and tested, per the build
file, and so are the grammatical shapes that make a finding without using any of the words.

**A flag with no innocent explanation is suppressed, not raised bare** — an empty list does
not mean the pattern is damning; it means a reviewer would supply their own explanation, and
it would be about a person.
"""

from __future__ import annotations

import pytest

from agent_svc.agents.ledger_anomaly import context as context_rules
from agent_svc.agents.ledger_anomaly import redaction
from agent_svc.agents.ledger_anomaly.normalisation import build_profiles
from agent_svc.agents.ledger_anomaly.ports import Evidence, Signal
from tests.agents.ledger_anomaly.conftest import (
    GOOD_CONTEXT,
    SEVERE,
    BrokenCall,
    RecordingCall,
    context,
    division,
)


def a_signal() -> Signal:
    return Signal(
        detector="value_distribution",
        gn_division_code=SEVERE,
        score=0.7,
        evidence=[Evidence(label="total_loss_share", value=0.8, compared_with=0.35)],
        ruled_out=["genuine total losses in a severe division were checked first"],
    )


def a_profile():
    rows = division(SEVERE, count=20)
    return build_profiles(rows, {SEVERE: context(SEVERE, impact_class=2)})[0]


# ---------------------------------------------------------------------------------------
# No individual named
# ---------------------------------------------------------------------------------------


def test_a_personal_name_is_rejected() -> None:
    """The failure this whole file exists for."""
    result = redaction.check({"pattern_summary": "Assessments approved by Nimal Perera cluster."})

    assert not result.clean
    assert result.rejections[0].rule == "no_individual_named"


def test_a_uuid_is_rejected() -> None:
    """A user id names somebody as surely as a name does, and the database CHECK behind
    this rejects one at any depth in the rationale."""
    result = redaction.check(
        {"summary": "assessor 3f8b9c21-4d5e-4a7b-8c9d-1e2f3a4b5c6d approved these"}
    )

    assert not result.clean
    assert result.rejections[0].rule == "no_individual_named"


def test_a_name_nested_deep_in_the_document_is_still_caught() -> None:
    """A name in the third innocent explanation names somebody just as surely as one in the
    summary, so the check is recursive - as the database CHECK behind it is."""
    result = redaction.check(
        {
            "pattern_summary": "Values cluster at total loss.",
            "innocent_explanations": [
                "the survey covered the worst streets first",
                {"note": "confirmed with Sunil Bandara"},
            ],
        }
    )

    assert not result.clean


def test_a_place_name_is_not_mistaken_for_a_person() -> None:
    """The check would be useless if it rejected every sentence containing a district.

    Without the allow-list the contextualiser could never produce a usable sentence, and a
    safeguard that blocks everything gets removed.
    """
    result = redaction.check(
        {
            "pattern_summary": (
                "In Kandy District, the Grama Niladhari division shows House Full claims "
                "above the Divisional Secretariat average."
            )
        }
    )

    assert result.clean


# ---------------------------------------------------------------------------------------
# No accusatory or conclusive language
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "term",
    ["fraud", "corrupt", "misuse", "embezzle", "fake", "falsified", "bribe", "collusion"],
)
def test_the_deny_list_rejects_accusatory_terms(term: str) -> None:
    """Build file 17: ship the deny-list, test it."""
    result = redaction.check({"pattern_summary": f"This pattern suggests {term}."})

    assert not result.clean
    assert any(item.rule == "no_accusatory_language" for item in result.rejections)


def test_stems_catch_the_inflected_forms() -> None:
    """`fraudulent` and `corruption` are the words a model actually writes."""
    assert redaction.is_accusatory("fraudulent claims") is not None
    assert redaction.is_accusatory("evidence of corruption") is not None


@pytest.mark.parametrize(
    "sentence",
    [
        "This is clearly a deliberate manipulation of the figures.",
        "The numbers prove that the claims were inflated.",
        "This indicates wrongdoing in the division.",
        "The officer should be suspended pending review.",
    ],
)
def test_conclusive_phrasing_is_rejected_even_without_a_denied_word(sentence: str) -> None:
    """A model told not to say "fraud" writes "this is clearly evidence of deliberate
    manipulation", and every word in that sentence is allowed. The shapes are checked
    separately for exactly that reason."""
    result = redaction.check({"pattern_summary": sentence})

    assert not result.clean


def test_a_neutral_pattern_summary_passes() -> None:
    """The check has to be passable, or the contextualiser is dead code."""
    result = redaction.check(
        {
            "pattern_summary": (
                "Total-loss claims in this division are above what the forecast predicted "
                "for its impact class."
            ),
            "innocent_explanations": ["the survey may have covered the worst streets first"],
            "what_would_resolve_it": ["compare against the DS survey for the same period"],
        }
    )

    assert result.clean


def test_every_broken_rule_is_reported_not_just_the_first() -> None:
    """An output that names somebody *and* accuses them is a different kind of wrong, and
    whoever tunes the prompt afterwards wants both."""
    result = redaction.check({"pattern_summary": "Nimal Perera committed fraud in this division."})

    assert {item.rule for item in result.rejections} == {
        "no_individual_named",
        "no_accusatory_language",
    }


def test_assert_publishable_raises_for_a_caller_with_no_fallback() -> None:
    with pytest.raises(ValueError, match="may not be published"):
        redaction.assert_publishable({"summary": "this is fraud"})


# ---------------------------------------------------------------------------------------
# What happens to a rejected output
# ---------------------------------------------------------------------------------------


async def test_a_model_naming_an_officer_has_its_context_discarded_whole() -> None:
    """Not repaired, not re-asked. An output that reached for an accusation once is not one
    to negotiate with, and the templated context is a complete, honest artefact."""
    answer = (
        '{"pattern_summary": "Assessments approved by Nimal Perera cluster at total loss.", '
        '"innocent_explanations": ["the worst streets were surveyed first"], '
        '"what_would_resolve_it": ["compare with the DS survey"], '
        '"suggested_priority": "high", "confidence": 0.9}'
    )

    result = await context_rules.contextualise(a_signal(), a_profile(), call=RecordingCall(answer))

    assert result.method == "TEMPLATE"
    assert "Nimal" not in str(result.as_dict())


async def test_a_model_using_accusatory_language_has_its_context_discarded() -> None:
    answer = (
        '{"pattern_summary": "This division shows clear evidence of fraud.", '
        '"innocent_explanations": ["none"], "what_would_resolve_it": [], '
        '"suggested_priority": "high", "confidence": 0.9}'
    )

    result = await context_rules.contextualise(a_signal(), a_profile(), call=RecordingCall(answer))

    assert result.method == "TEMPLATE"
    assert "fraud" not in str(result.as_dict()).lower()


async def test_a_rejected_context_is_never_raised_at_high_priority() -> None:
    """Losing the narrative removes a safeguard, so what remains is raised quietly."""
    answer = '{"pattern_summary": "Nimal Perera approved these.", "innocent_explanations": ["x"]}'

    result = await context_rules.contextualise(a_signal(), a_profile(), call=RecordingCall(answer))

    assert context_rules.priority_for(a_signal(), result) == context_rules.DEGRADED_PRIORITY


# ---------------------------------------------------------------------------------------
# Innocent explanations are mandatory
# ---------------------------------------------------------------------------------------


async def test_a_context_with_no_innocent_explanation_is_not_usable() -> None:
    """Build file 17: if the model cannot think of one, the flag is not ready to raise.

    An empty list does not mean the pattern is damning. It means a reviewer handed nothing
    to rule out will supply their own explanation - and it will be about a person.
    """
    answer = (
        '{"pattern_summary": "Total-loss claims exceed the forecast for this class.", '
        '"innocent_explanations": [], "what_would_resolve_it": ["compare with the DS survey"], '
        '"suggested_priority": "medium", "confidence": 0.5}'
    )

    result = await context_rules.contextualise(a_signal(), a_profile(), call=RecordingCall(answer))

    assert result.innocent_explanations == []
    assert not result.usable


def test_a_signal_that_ruled_nothing_out_is_not_actionable() -> None:
    """The same rule one layer down: a detector that ruled nothing out produces a flag a
    reviewer starts from zero on."""
    bare = Signal(
        detector="value_distribution",
        gn_division_code=SEVERE,
        score=0.9,
        evidence=[Evidence(label="x", value=1)],
        ruled_out=[],
    )

    assert not bare.actionable


async def test_the_template_fallback_still_carries_innocent_explanations() -> None:
    """Which is why the degraded path can satisfy the non-empty rule at all: they come from
    the detector's own ruled-out list rather than from a model."""
    result = await context_rules.contextualise(a_signal(), a_profile(), call=BrokenCall())

    assert result.method == "TEMPLATE"
    assert result.innocent_explanations
    assert result.usable


async def test_a_good_model_context_is_used_as_written() -> None:
    """The safeguards have to let good output through, or the model call is pointless."""
    result = await context_rules.contextualise(
        a_signal(), a_profile(), call=RecordingCall(GOOD_CONTEXT)
    )

    assert result.method == "LLM"
    assert result.suggested_priority == "medium"


async def test_the_prompt_is_never_told_who_assessed_anything() -> None:
    """The strongest layer: the model cannot name somebody it was never told about.

    The instruction not to name anyone is the second layer, and the post-check is the
    third.
    """
    call = RecordingCall(GOOD_CONTEXT)

    await context_rules.contextualise(a_signal(), a_profile(), call=call)
    prompt = call.prompts[0]

    for forbidden in ("assessor", "approver", "officer_id", "user_id", "household_id"):
        assert forbidden not in prompt
