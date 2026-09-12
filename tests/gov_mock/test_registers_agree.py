"""gov-mock's registers and SARANA's seed must say the same thing.

gov-mock deliberately keeps its own copy of the administrative register, the landslide
zonation and the network inventory, because a real agency does — see
`gov_mock.data.districts` for the reasoning. Independent copies are the right shape, but
only if something checks them against each other. This is that something.

The failure these catch is quiet and expensive: the mock says a division is in landslide
zone 2 while `admin.gn_division` says zone 4, an agent reasons about one hazard map, a
warning is issued off the other, and nothing anywhere reports an error.

Same pattern as the vocabulary tests in `tests/incident`, `tests/alerting` and
`tests/core_api`: assert two independently-maintained sets are equal, in both directions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from gov_mock.data import nbro as nbro_data
from gov_mock.data import telco as telco_data
from gov_mock.data.districts import DISTRICTS, all_gn_codes

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_ROOT = REPO_ROOT / "data" / "seed" / "reference"


def _seed(name: str) -> list[dict[str, Any]]:
    """Load one seed file. UTF-8 explicitly: the names are Sinhala and Tamil."""
    path = SEED_ROOT / name
    if not path.exists():
        pytest.skip(f"{path} is not present; run `make seed-generate`")
    with path.open(encoding="utf-8") as handle:
        rows: list[dict[str, Any]] = json.load(handle)
    return rows


def test_the_district_registers_hold_the_same_codes() -> None:
    """Both copies list the same 25 districts.

    In both directions: a district the mock knows and the platform does not is a mock
    serving data for somewhere that cannot be resolved, and the reverse is a district the
    platform will never get a warning for.
    """
    mock_codes = {district.code for district in DISTRICTS}
    seed_codes = {row["code"] for row in _seed("district.json")}

    assert mock_codes == seed_codes


def test_the_district_registers_agree_on_names_and_centres() -> None:
    """Same code, same English name.

    Codes matching while names differ is the worse failure of the two: every join still
    works, and every screen shows the wrong place.
    """
    seed_names = {row["code"]: row["name"]["en"] for row in _seed("district.json")}

    for district in DISTRICTS:
        assert district.en == seed_names[district.code], (
            f"{district.code}: mock calls it {district.en!r}, seed calls it "
            f"{seed_names[district.code]!r}"
        )


def test_the_gn_division_code_shapes_agree() -> None:
    """Every GN code the mock can generate is one the platform holds.

    The mock derives codes arithmetically; the seed writes them out. If the two ever
    disagree about how many DS divisions a district has, every zonation and coverage
    lookup starts 404ing for the divisions past the end.
    """
    mock_codes = set(all_gn_codes())
    seed_codes = {row["code"] for row in _seed("gn_division.json")}

    assert mock_codes == seed_codes


def test_the_landslide_zonation_agrees_with_the_platforms_copy() -> None:
    """NBRO's zone for a division equals `admin.gn_division.landslide_zone`.

    The zonation survey is NBRO's product and the platform's column is populated from it,
    so the two must not be able to drift. `gov_mock.data.nbro.zone_for` reproduces the
    seed's arithmetic rather than importing it, and this is what holds the reproduction
    honest.
    """
    seed_zones = {row["code"]: row["landslide_zone"] for row in _seed("gn_division.json")}

    for code, expected in seed_zones.items():
        assert nbro_data.zone_for(code) == expected, (
            f"{code}: NBRO mock says zone {nbro_data.zone_for(code)}, "
            f"admin.gn_division says {expected}"
        )


def test_the_baseline_cell_coverage_agrees_with_the_platforms_copy() -> None:
    """Normal-day coverage equals `admin.gn_division.cell_coverage_pct`.

    Only the baseline. What the mock adds on top — sites losing mains power and running
    their batteries down as the storm passes — is the part the seed cannot have, and is
    exactly what makes a delivery gap demonstrable.
    """
    seed_coverage = {row["code"]: row["cell_coverage_pct"] for row in _seed("gn_division.json")}

    for code, expected in seed_coverage.items():
        assert telco_data.baseline_coverage_pct(code) == pytest.approx(expected), (
            f"{code}: telco mock baseline is {telco_data.baseline_coverage_pct(code)}, "
            f"admin.gn_division says {expected}"
        )
