"""NBRO routes: bulletins, landslide zonation, and the rainfall thresholds.

The thresholds endpoint is the one that matters. `rain_thresholds` is what the rule-based
fallback forecast keys off, and serving it from here — rather than embedding the numbers in
agent code — is what makes replacing the stand-in values with NBRO's real ones a data
change instead of a code change in a place nobody remembers to look.

Every threshold record carries a provenance string that begins `SYNTHETIC`. Keep it that
way until somebody has the real figures in writing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from gov_mock.api.deps import SimulatedHoursDep, SimulatedNowDep, StateDep, mock_json
from gov_mock.data import met as met_data
from gov_mock.data import nbro as nbro_data
from gov_mock.data.districts import DISTRICTS, ds_codes, gn_codes

router = APIRouter(prefix="/nbro/v1", tags=["nbro"])


def _bulletins(now: datetime, hours: float, seed: int) -> list[nbro_data.Bulletin]:
    """Bulletins in force, derived from rainfall against the zone thresholds.

    Built by asking the same question the platform's own fallback forecast asks: how much
    rain has this division had, and what does its zone's threshold say about it. If the
    mock issued bulletins on its own timetable, an agent could agree with NBRO by accident
    while its threshold logic was wrong.
    """
    issued: list[nbro_data.Bulletin] = []
    sequence = 1

    for district in DISTRICTS:
        rainfall = met_data.district_rainfall_mm(
            district.code, hours_since_landfall=hours, seed=seed
        )
        # A DS division inherits the worst level any of its GN divisions reaches. NBRO
        # issues at DS level, and a bulletin that averaged its divisions would stand down
        # the one place that still needs it.
        by_level: dict[str, list[str]] = {}
        for ds_code in ds_codes(district):
            worst: str | None = None
            for gn_code in gn_codes(district):
                if not gn_code.startswith(f"{ds_code}-"):
                    continue
                threshold = nbro_data.threshold_for(nbro_data.zone_for(gn_code))
                level = threshold.level_for(rainfall)
                if level is None:
                    continue
                if worst is None or _severity(level) > _severity(worst):
                    worst = level
            if worst is not None:
                by_level.setdefault(worst, []).append(ds_code)

        for level, codes in sorted(by_level.items()):
            issued.append(
                nbro_data.bulletin_for(
                    ds_division_codes=tuple(sorted(codes)),
                    level=level,
                    issued_at=now,
                    sequence=sequence,
                )
            )
            sequence += 1

    return issued


def _severity(level: str) -> int:
    return {"WATCH": 1, "WARNING": 2, "EVACUATE": 3}[level]


@router.get("/bulletins", summary="Landslide early-warning bulletins")
def bulletins(
    state: StateDep,
    now: SimulatedNowDep,
    hours: SimulatedHoursDep,
    ds_division_id: str | None = Query(default=None, description="DS division code"),
) -> Any:
    """Bulletins currently in force, optionally narrowed to one DS division."""
    issued = _bulletins(now, hours, state.seed)
    if ds_division_id is not None:
        issued = [b for b in issued if ds_division_id in b.ds_division_codes]

    return mock_json(
        {
            "bulletins": [
                {
                    "bulletin_id": bulletin.bulletin_id,
                    "level": bulletin.level,
                    "issued_at": bulletin.issued_at.isoformat(),
                    "valid_until": bulletin.valid_until.isoformat(),
                    "ds_division_codes": list(bulletin.ds_division_codes),
                    "advice": bulletin.advice,
                }
                for bulletin in issued
            ]
        }
    )


@router.get("/zonation", summary="Landslide hazard zone for a GN division")
def zonation(gn_division_id: str = Query(description="GN division code")) -> Any:
    """The hazard zone for one division, 1 (low) to 4 (very high)."""
    try:
        zone = nbro_data.zone_for(gn_division_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return mock_json(
        {
            "zonation": {
                "gn_division_code": gn_division_id,
                "zone": zone,
                "surveyed_year": nbro_data.surveyed_year(gn_division_id),
            }
        }
    )


@router.get("/rain-thresholds", summary="Cumulative-rainfall thresholds per hazard zone")
def rain_thresholds() -> Any:
    """The thresholds the fallback forecast keys off.

    Read `gov_mock.data.nbro` before relying on the numbers. They are stand-ins, they say
    so in `provenance`, and `ThresholdSet.is_official` reports False for them everywhere
    they are used.
    """
    return mock_json(
        {
            "thresholds": [
                {
                    "zone": threshold.zone,
                    "window_hours": threshold.window_hours,
                    "watch_mm": threshold.watch_mm,
                    "warning_mm": threshold.warning_mm,
                    "evacuate_mm": threshold.evacuate_mm,
                    "provenance": threshold.provenance,
                }
                for threshold in nbro_data.thresholds()
            ]
        }
    )
