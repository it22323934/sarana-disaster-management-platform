"""The two places this agent uses a model, and the guards on both.

Neither of them decides anything, and these tests are mostly about proving that. A model
that could lower a hazard level, or write a number nobody gave it, would be a model making
the decision - and the whole framing of this agent is that it does not.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from agent_svc.agents.forecast import narrative, reconcile
from agent_svc.agents.forecast.narrative import LANGUAGES
from agent_svc.agents.forecast.reconcile import SourceClaim
from agent_svc.agents.forecast.scoring import Driver, ImpactScore

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)


def met(level: str, code: str = "LK-21") -> SourceClaim:
    return SourceClaim("DEPT_METEOROLOGY", level, "district", code, NOW, "Cyclone Ditwah")


def nbro(level: str, code: str = "LK-21-01") -> SourceClaim:
    return SourceClaim("NBRO", level, "ds_division", code, NOW, "")


def responder(payload: object):
    async def call(_prompt: str) -> str:
        return json.dumps(payload) if not isinstance(payload, str) else payload

    return call


def raiser(error: Exception):
    async def call(_prompt: str) -> str:
        raise error

    return call


def a_score(**overrides: object) -> ImpactScore:
    defaults: dict[str, object] = {
        "gn_division_id": "gn-1",
        "gn_division_code": "LK-21-01-007",
        "impact_class": 3,
        "confidence": 0.85,
        "lead_time_hours": 48,
        "drivers": [
            Driver(factor="peak_rainfall_24h", value=146.4, threshold=200.0, contribution=3.0),
            Driver(factor="landslide_zone", value=3, threshold="watch 100 mm", contribution=0.0),
        ],
        "expected_households_affected": 340,
        "expected_road_access_loss": True,
    }
    return ImpactScore.model_validate({**defaults, **overrides})


# =======================================================================================
# Reconciliation
# =======================================================================================


async def test_conflicting_sources_resolve_to_the_conservative_interpretation() -> None:
    """Build file 13 names this outcome directly.

    Over-warning costs a preposition. Under-warning costs the thing this platform exists
    to prevent, and the asymmetry is why the rule is not a preference.
    """
    result = await reconcile.reconcile([met("AMBER"), nbro("EVACUATE")])

    assert result.level == "EVACUATE"
    assert result.severity == 3


async def test_a_model_cannot_talk_the_level_down() -> None:
    """The invariant the whole module exists for.

    A model asked to weigh a district-wide Amber against a DS-level EVACUATE can produce a
    fluent, defensible paragraph arguing for the lower one. Applied as a floor after the
    call rather than requested in the prompt, because a rule that lives only in a prompt is
    one the model may decline to follow on the input that matters.
    """
    persuasive = responder(
        {
            "level": "AMBER",
            "rationale": "The Met warning covers the whole district and is more recent.",
            "confidence": 0.95,
        }
    )

    result = await reconcile.reconcile([met("AMBER"), nbro("EVACUATE")], call=persuasive)

    assert result.level == "EVACUATE"
    assert result.method == "CONSERVATIVE", "the overruled rationale goes with the level"


async def test_a_model_may_explain_when_it_does_not_lower_the_level() -> None:
    agreeing = responder(
        {
            "level": "EVACUATE",
            "rationale": "NBRO's bulletin is specific to this DS division and is tied to a "
            "measured rainfall threshold.",
            "confidence": 0.8,
        }
    )

    result = await reconcile.reconcile([met("AMBER"), nbro("EVACUATE")], call=agreeing)

    assert result.level == "EVACUATE"
    assert result.method == "LLM"
    assert "specific" in result.rationale


async def test_an_invented_level_is_discarded() -> None:
    """The specific failure build file 13 warns about: a hazard level no source reported."""
    inventive = responder(
        {"level": "CATASTROPHIC", "rationale": "Unprecedented.", "confidence": 0.99}
    )

    result = await reconcile.reconcile([met("AMBER"), nbro("WATCH")], call=inventive)

    assert result.level == "WARNING"
    assert result.method == "CONSERVATIVE"


async def test_an_unparseable_response_degrades_rather_than_failing() -> None:
    result = await reconcile.reconcile(
        [met("AMBER"), nbro("WATCH")], call=responder("I think it is probably fine.")
    )

    assert result.method == "CONSERVATIVE"
    assert result.level == "WARNING"


async def test_a_fenced_code_block_is_still_read() -> None:
    """Models return one about a third of the time, and treating it as a failure would
    silently move most reconciliations onto the degraded path."""
    fenced = responder(
        '```json\n{"level": "EVACUATE", "rationale": "NBRO is specific.", "confidence": 0.7}\n```'
    )

    result = await reconcile.reconcile([met("AMBER"), nbro("EVACUATE")], call=fenced)

    assert result.method == "LLM"


async def test_a_provider_outage_changes_the_rationale_and_not_the_level() -> None:
    """The degraded path for this node is the floor it applies when the model is up, so
    losing the provider cannot change a decision."""
    claims = [met("AMBER"), nbro("EVACUATE")]

    up = await reconcile.reconcile(claims, call=raiser(TimeoutError("provider down")))
    down = await reconcile.reconcile(claims)

    assert up.level == down.level == "EVACUATE"
    assert up.method == down.method == "CONSERVATIVE"


async def test_the_model_is_not_called_when_sources_agree() -> None:
    """Most hours of most events they do, and a token spent agreeing with an agreement
    buys the answer the floor gives for free."""
    calls: list[str] = []

    async def counting(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps({"level": "WATCH", "rationale": "x", "confidence": 0.5})

    await reconcile.reconcile([met("YELLOW"), nbro("WATCH")], call=counting)

    assert calls == []


def test_agreement_is_more_confident_than_a_resolved_conflict() -> None:
    """Sources that concur have independently reached the same reading. A conflict
    resolved by taking the worse one is a decision made under uncertainty."""
    agreeing = reconcile.conservative([met("AMBER"), nbro("WARNING")])
    conflicting = reconcile.conservative([met("AMBER"), nbro("EVACUATE")])

    assert agreeing.confidence > conflicting.confidence


def test_a_tie_breaks_towards_the_more_specific_source() -> None:
    """Same severity, and the one describing a smaller area describes it better."""
    result = reconcile.conservative([met("AMBER"), nbro("WARNING")])

    assert result.chosen_source == "NBRO"


def test_no_sources_at_all_is_not_a_crash() -> None:
    result = reconcile.conservative([])

    assert result.level == "NONE"
    assert result.severity == 0


def test_the_prompt_lists_only_the_observed_levels() -> None:
    """Constraining the choice in the prompt as well as in the parser. Belt and braces on
    the failure that matters."""
    prompt = reconcile.build_prompt([met("AMBER"), nbro("EVACUATE")])

    assert "AMBER" in prompt
    assert "EVACUATE" in prompt
    assert "RED" not in prompt


# =======================================================================================
# Narrative
# =======================================================================================


async def test_a_narrative_with_an_invented_number_is_discarded_whole() -> None:
    """The post-check build file 13 requires, and the reason it is blunt.

    "180 households" when the drivers say 340 reaches a GN officer as a specific claim
    about their own division, attributed to the government, at the hour they are deciding
    whether to move people - and it will be believed, because everything around it is true.
    """
    fabricating = responder(
        {
            "si": "180 ගෘහ ඒකක",
            "ta": "180 குடும்பங்கள்",
            "en": "180 households will be affected.",
        }
    )

    result = await narrative.explain(a_score(), call=fabricating)

    assert result.method == "TEMPLATE"
    assert "180" not in result.text["en"]


async def test_a_narrative_using_only_given_numbers_is_kept() -> None:
    faithful = responder(
        {
            "si": "ගෘහ ඒකක 340 ක් බලපෑමට ලක්විය හැක.",
            "ta": "340 குடும்பங்கள் பாதிக்கப்படலாம்.",
            "en": "340 households are in the affected division; expect 146.4 mm.",
        }
    )

    result = await narrative.explain(a_score(), call=faithful)

    assert result.method == "LLM"
    assert "340" in result.text["en"]


async def test_rounding_a_given_number_is_not_inventing_one() -> None:
    """A model writing "146 mm" for a driver value of 146.4 is rounding. One writing "180"
    is inventing, and the check has to tell them apart or it rejects everything."""
    rounding = responder(
        {
            "si": "මිලිමීටර් 146",
            "ta": "146 மி.மீ",
            "en": "About 146 mm of rain is expected.",
        }
    )

    result = await narrative.explain(a_score(), call=rounding)

    assert result.method == "LLM"


async def test_a_narrative_missing_a_language_is_not_published() -> None:
    """Non-negotiable #2 does not degrade gracefully. A warning that reaches Sinhala and
    English speakers and not Tamil ones is the exact failure the rule exists to prevent."""
    partial = responder({"si": "යමක්", "en": "Something", "ta": ""})

    result = await narrative.explain(a_score(), call=partial)

    assert result.method == "TEMPLATE"
    assert result.is_complete


async def test_the_template_says_the_same_facts_in_all_three_languages() -> None:
    result = await narrative.explain(a_score())

    assert result.method == "TEMPLATE"
    for language in LANGUAGES:
        assert result.text[language].strip()
        assert "340" in result.text[language]


async def test_a_provider_outage_still_produces_a_narrative() -> None:
    result = await narrative.explain(a_score(), call=raiser(ConnectionError("no route")))

    assert result.method == "TEMPLATE"
    assert result.is_complete


def test_window_lengths_are_allowed_without_being_drivers() -> None:
    """ "over the next 24 hours" is how a person says it, and rejecting it would throw away
    almost every well-formed sentence."""
    allowed = narrative.allowed_numbers(a_score())

    assert not narrative.invented_numbers("Expect rain over the next 72 hours.", allowed)


def test_a_division_code_is_not_an_invented_number() -> None:
    """A narrative naming the division is doing the right thing."""
    score = a_score()
    allowed = narrative.allowed_numbers(score, "Kandy 1-7")

    assert not narrative.invented_numbers(f"{score.gn_division_code}: major impact.", allowed)


def test_a_threshold_quoted_from_a_driver_string_is_allowed() -> None:
    """Thresholds arrive as prose - "watch 100 / warning 150 / evacuate 200 mm over 24h" -
    and every figure in one is a real number the narrative may quote."""
    score = a_score(
        drivers=[
            Driver(
                factor="landslide_zone",
                value=3,
                threshold="watch 100 / warning 150 / evacuate 200 mm over 24h",
                contribution=0.0,
            )
        ]
    )

    allowed = narrative.allowed_numbers(score)

    assert not narrative.invented_numbers("The warning level here is 150 mm.", allowed)
    assert narrative.invented_numbers("The warning level here is 155 mm.", allowed)


def test_the_prompt_forbids_inventing_numbers() -> None:
    """Belt and braces: the parser enforces it, and the prompt asks for it, because a
    model that was never asked will do it far more often."""
    prompt = narrative.build_prompt(a_score(), "Kandy 1-7")

    assert "Do not calculate" in prompt
    assert "not listed" in prompt


@pytest.mark.parametrize("impact_class", [0, 1, 2, 3, 4])
def test_every_impact_class_has_words_in_every_language(impact_class: int) -> None:
    """A class with no Tamil word for it is a class that silently publishes an empty
    sentence to a third of the country."""
    for language in LANGUAGES:
        assert narrative.CLASS_WORDS[impact_class][language].strip()
