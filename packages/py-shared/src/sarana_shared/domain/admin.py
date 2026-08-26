"""Sri Lanka administrative hierarchy.

    Province (9)
      District (25)              e.g. Kandy, Colombo, Batticaloa
        DS Division (331)        "Divisional Secretariat"
          GN Division (~14,022)  "Grama Niladhari" - the smallest admin unit
            Household

The GN officer is the state's field-level officer, one per GN division. They perform
damage assessments and are the primary Field Companion app user. DS approves
entitlements; District Secretariat gives second-level approval above a configurable
threshold.

Codes are official and hierarchical, and the parent code is always a prefix of the child.
That property is what makes RBAC scope matching a string prefix test rather than a join.
Never use a free-text place name as a key.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sarana_shared.domain.localised import LocalisedText

# district LK-{2}, DS {district}-{2}, GN {ds}-{3}. Province has no official code in the
# national scheme, so SARANA assigns LK-P{2} and never presents it as an official ID.
PROVINCE_CODE_PATTERN: Final = re.compile(r"^LK-P\d{2}$")
DISTRICT_CODE_PATTERN: Final = re.compile(r"^LK-\d{2}$")
DS_CODE_PATTERN: Final = re.compile(r"^LK-\d{2}-\d{2}$")
GN_CODE_PATTERN: Final = re.compile(r"^LK-\d{2}-\d{2}-\d{3}$")

PROVINCE_COUNT: Final = 9
DISTRICT_COUNT: Final = 25


class AdminLevel(StrEnum):
    """A rung of the hierarchy. Ordered coarse to fine by `depth`."""

    NATIONAL = "national"
    PROVINCE = "province"
    DISTRICT = "district"
    DS_DIVISION = "ds_division"
    GN_DIVISION = "gn_division"

    @property
    def depth(self) -> int:
        """0 for national, 4 for GN division. Larger means narrower scope."""
        return _LEVEL_DEPTH[self]


_LEVEL_DEPTH: Final[dict[AdminLevel, int]] = {
    AdminLevel.NATIONAL: 0,
    AdminLevel.PROVINCE: 1,
    AdminLevel.DISTRICT: 2,
    AdminLevel.DS_DIVISION: 3,
    AdminLevel.GN_DIVISION: 4,
}


class AdminCodeError(ValueError):
    """An administrative code is malformed or used at the wrong level."""


def level_of(code: str) -> AdminLevel:
    """Infer the hierarchy level from a code's shape.

    Raises:
        AdminCodeError: if the code matches no known pattern.
    """
    if code == "LK":
        return AdminLevel.NATIONAL
    if PROVINCE_CODE_PATTERN.match(code):
        return AdminLevel.PROVINCE
    if DISTRICT_CODE_PATTERN.match(code):
        return AdminLevel.DISTRICT
    if DS_CODE_PATTERN.match(code):
        return AdminLevel.DS_DIVISION
    if GN_CODE_PATTERN.match(code):
        return AdminLevel.GN_DIVISION
    raise AdminCodeError(f"not a recognised Sri Lanka administrative code: {code!r}")


def validate_code(code: str, expected: AdminLevel) -> str:
    """Return the code unchanged if it is well-formed at `expected`, else raise."""
    actual = level_of(code)
    if actual is not expected:
        raise AdminCodeError(
            f"expected a {expected.value} code, but {code!r} is a {actual.value} code"
        )
    return code


def parent_code(code: str) -> str | None:
    """Return the immediate parent code, or None at the top of the coded hierarchy.

    Province is not a code prefix of district in the national scheme, so a district's
    parent is resolved from the reference table, not from the string.
    """
    level = level_of(code)
    if level in (AdminLevel.NATIONAL, AdminLevel.PROVINCE, AdminLevel.DISTRICT):
        return None if level is AdminLevel.NATIONAL else "LK"
    return code.rsplit("-", 1)[0]


def district_of(code: str) -> str:
    """Extract the district code from any district, DS or GN code."""
    level = level_of(code)
    if level not in (AdminLevel.DISTRICT, AdminLevel.DS_DIVISION, AdminLevel.GN_DIVISION):
        raise AdminCodeError(f"{code!r} has no district component")
    return "-".join(code.split("-")[:2])


def ds_of(code: str) -> str:
    """Extract the DS division code from a DS or GN code."""
    level = level_of(code)
    if level not in (AdminLevel.DS_DIVISION, AdminLevel.GN_DIVISION):
        raise AdminCodeError(f"{code!r} has no DS division component")
    return "-".join(code.split("-")[:3])


def contains(scope_code: str, target_code: str) -> bool:
    """Whether `scope_code` covers `target_code` in the hierarchy.

    National covers everything. Otherwise this is a segment-aware prefix test, so
    `LK-11-0` never accidentally covers `LK-11-03`. Province scopes are not decidable
    from codes alone and must be expanded to their districts before calling this.
    """
    if scope_code == "LK":
        return True
    if PROVINCE_CODE_PATTERN.match(scope_code):
        raise AdminCodeError(
            "province scope cannot be resolved from codes alone; "
            "expand it to district codes via the reference table first"
        )
    if scope_code == target_code:
        return True
    return target_code.startswith(f"{scope_code}-")


class AdminUnit(BaseModel):
    """Fields common to every level of the hierarchy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    name: LocalisedText


class Province(AdminUnit):
    """One of the nine provinces."""

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        return validate_code(value, AdminLevel.PROVINCE)


class District(AdminUnit):
    """One of the twenty-five districts."""

    province_code: str

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        return validate_code(value, AdminLevel.DISTRICT)

    @field_validator("province_code")
    @classmethod
    def _check_province(cls, value: str) -> str:
        return validate_code(value, AdminLevel.PROVINCE)


class DSDivision(AdminUnit):
    """A Divisional Secretariat division. Approves entitlements."""

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        return validate_code(value, AdminLevel.DS_DIVISION)

    @property
    def district_code(self) -> str:
        """Parent district, derived from the code."""
        return district_of(self.code)


class GNDivision(AdminUnit):
    """A Grama Niladhari division - the smallest administrative unit.

    `population` and `household_count` come from the reference registry and are used as
    exposure denominators by the Forecast and Impact agent.
    """

    population: int = Field(ge=0)
    household_count: int = Field(ge=0)

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        return validate_code(value, AdminLevel.GN_DIVISION)

    @property
    def ds_code(self) -> str:
        """Parent DS division, derived from the code."""
        return ds_of(self.code)

    @property
    def district_code(self) -> str:
        """Ancestor district, derived from the code."""
        return district_of(self.code)
