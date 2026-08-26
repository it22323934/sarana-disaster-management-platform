"""Sri Lanka's administrative hierarchy: Province -> District -> DS Division -> GN Division.

Per docs/build-prompts/00-master-context.md, this is the one thing every service must get
right: `district LK-{2 digits}`, `ds {district}-{2}`, `gn {ds}-{3}` — never a free-text
place name as a key. This module owns the code format and parsing; the actual reference
data (9 provinces, 25 districts, 331 DS divisions, ~14,022 GN divisions) is seeded from
docs/build-prompts/28-simulation-and-seed-data.md, not hardcoded here.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from sarana_shared.domain.localised import LocalisedText

AdminLevel = Literal["PROVINCE", "DISTRICT", "DS", "GN"]

_DISTRICT_CODE = re.compile(r"^LK-\d{2}$")
_DS_CODE = re.compile(r"^LK-\d{2}-\d{2}$")
_GN_CODE = re.compile(r"^LK-\d{2}-\d{2}-\d{3}$")


class AdminCodeError(ValueError):
    pass


def validate_district_code(code: str) -> str:
    if not _DISTRICT_CODE.match(code):
        raise AdminCodeError(f"Not a valid district code: {code!r} (expected LK-##)")
    return code


def validate_ds_code(code: str) -> str:
    if not _DS_CODE.match(code):
        raise AdminCodeError(f"Not a valid DS division code: {code!r} (expected LK-##-##)")
    return code


def validate_gn_code(code: str) -> str:
    if not _GN_CODE.match(code):
        raise AdminCodeError(f"Not a valid GN division code: {code!r} (expected LK-##-##-###)")
    return code


def district_code_of(ds_code: str) -> str:
    """LK-21-05 -> LK-21"""
    validate_ds_code(ds_code)
    return ds_code.rsplit("-", 1)[0]


def ds_code_of(gn_code: str) -> str:
    """LK-21-05-014 -> LK-21-05"""
    validate_gn_code(gn_code)
    return gn_code.rsplit("-", 1)[0]


def district_code_of_gn(gn_code: str) -> str:
    """LK-21-05-014 -> LK-21"""
    return district_code_of(ds_code_of(gn_code))


class Province(BaseModel):
    id: str  # UUIDv7 as str at this layer; see db/base.py for the SQLAlchemy column type
    code: str
    name: LocalisedText


class District(BaseModel):
    id: str
    code: str
    province_id: str
    name: LocalisedText


class DSDivision(BaseModel):
    id: str
    code: str
    district_id: str
    name: LocalisedText


class GNDivision(BaseModel):
    id: str
    code: str
    ds_division_id: str
    name: LocalisedText
    population: int | None = None
    household_count: int | None = None
    landslide_zone: int | None = None  # NBRO hazard zone 1-4
    road_access_class: int | None = None
    cell_coverage_pct: float | None = None
