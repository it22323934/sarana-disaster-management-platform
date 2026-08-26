"""The Sri Lanka administrative hierarchy and RBAC area containment."""

from __future__ import annotations

import pytest

from sarana_shared.domain.admin import (
    AdminCodeError,
    AdminLevel,
    GNDivision,
    contains,
    district_of,
    ds_of,
    level_of,
)
from sarana_shared.domain.localised import LocalisedText

KANDY_GN = "LK-11-03-045"


def test_level_is_inferred_from_code_shape() -> None:
    assert level_of("LK") is AdminLevel.NATIONAL
    assert level_of("LK-11") is AdminLevel.DISTRICT
    assert level_of("LK-11-03") is AdminLevel.DS_DIVISION
    assert level_of(KANDY_GN) is AdminLevel.GN_DIVISION


def test_a_place_name_is_never_a_key() -> None:
    with pytest.raises(AdminCodeError):
        level_of("Batticaloa")


def test_ancestors_are_derived_from_the_code() -> None:
    assert ds_of(KANDY_GN) == "LK-11-03"
    assert district_of(KANDY_GN) == "LK-11"


def test_containment_is_segment_aware() -> None:
    """A truncated code must not accidentally cover a longer one."""
    assert contains("LK-11", KANDY_GN)
    assert not contains("LK-11-0", "LK-11-03")


def test_one_district_cannot_reach_another() -> None:
    assert not contains("LK-11", "LK-12-03-045")


def test_national_scope_covers_everything() -> None:
    assert contains("LK", KANDY_GN)


def test_province_scope_must_be_expanded_first() -> None:
    """Province is not a code prefix of district in the national scheme."""
    with pytest.raises(AdminCodeError, match="expand it to district codes"):
        contains("LK-P02", KANDY_GN)


def test_gn_division_exposes_its_ancestors() -> None:
    division = GNDivision(
        code=KANDY_GN,
        name=LocalisedText(si="පල්ලේකැලේ", ta="பள்ளேகலே", en="Pallekele"),
        population=2_140,
        household_count=530,
    )

    assert division.ds_code == "LK-11-03"
    assert division.district_code == "LK-11"
