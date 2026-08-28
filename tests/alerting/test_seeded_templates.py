"""The twelve Phase 1 templates.

Build file 09 names the twelve exactly, so this asserts all twelve exist, all are valid
under the template rules, and — the one that matters — none of them ships pre-reviewed.

Seeding a template as PUBLISHED would put a machine-translated life-safety message one API
call away from a district. The review workflow exists precisely to stop that, and a seed
file is the obvious back door.
"""

from __future__ import annotations

import pytest

from alerting_svc.domain import templates as template_rules
from alerting_svc.repo.base import (
    CAP_CERTAINTIES,
    CAP_SEVERITIES,
    CAP_URGENCIES,
    HAZARD_TYPES,
)
from tools.seed.templates import TEMPLATES

# The twelve the brief names, by the concept each covers.
REQUIRED_CODES = {
    "FLOOD_WATCH",
    "FLOOD_WARNING",
    "FLOOD_EVACUATE_IMMEDIATE",
    "LANDSLIDE_WATCH",
    "LANDSLIDE_WARNING",
    "CYCLONE_WARNING",
    "STORM_SURGE_WARNING",
    "SHELTER_OPEN",
    "SHELTER_FULL",
    "ROAD_CLOSED",
    "ALL_CLEAR",
    "AID_DISTRIBUTION_OPEN",
}


def test_all_twelve_templates_are_present() -> None:
    assert {template["code"] for template in TEMPLATES} == REQUIRED_CODES


def test_there_are_no_duplicate_codes() -> None:
    codes = [template["code"] for template in TEMPLATES]

    assert len(codes) == len(set(codes))


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: str(t["code"]))
def test_every_template_body_is_valid(template: dict) -> None:
    """Trilingual, consistent parameters, and every parameter fillable from data."""
    template_rules.validate_template(template["body"])


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: str(t["code"]))
def test_every_template_uses_vocabularies_the_schema_accepts(template: dict) -> None:
    """A template the database will not store is a template nobody can publish."""
    assert template["hazard_type"] in HAZARD_TYPES
    assert template["severity"] in CAP_SEVERITIES
    assert template["urgency"] in CAP_URGENCIES
    assert template["certainty"] in CAP_CERTAINTIES


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: str(t["code"]))
def test_no_template_ships_pre_reviewed(template: dict) -> None:
    """The gate's obvious back door, closed.

    A seed that set reviewer signatures would make twelve machine-translated life-safety
    messages dispatchable without any native speaker having read them.
    """
    assert "reviewed_by_si" not in template
    assert "reviewed_by_ta" not in template
    assert template.get("status", "DRAFT") == "DRAFT"


def test_the_immediate_evacuation_template_names_a_shelter_and_a_deadline() -> None:
    """The most consequential message of the twelve.

    "Evacuate now" without saying where to or by when is not an instruction.
    """
    evacuate = next(t for t in TEMPLATES if t["code"] == "FLOOD_EVACUATE_IMMEDIATE")
    parameters = template_rules.parameters_in(evacuate["body"])

    assert "shelter_name" in parameters
    assert "deadline_time" in parameters


def test_every_template_names_the_division_it_is_about() -> None:
    """A warning that does not say where it applies gets ignored everywhere."""
    for template in TEMPLATES:
        parameters = template_rules.parameters_in(template["body"])
        assert "gn_division_name" in parameters or "distribution_point" in parameters, (
            f"{template['code']} does not identify an area"
        )


def test_the_all_clear_is_the_only_template_with_past_urgency() -> None:
    """An all-clear is the one message that describes something already over."""
    past = {t["code"] for t in TEMPLATES if t["urgency"] == "PAST"}

    assert past == {"ALL_CLEAR"}
