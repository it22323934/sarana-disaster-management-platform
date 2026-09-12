"""The dashboard aggregates: what they publish, what they withhold, and what they never see.

Build file 21 put three endpoints on ledger-svc that no credential opens. This file holds
them to the same two claims `test_public_feed.py` holds the entry feed to, and adds a third
that only applies to aggregates.

**Anonymous.** No name, NIC, phone, household reference or coordinate, and — the part the
per-entry feed does not have to worry about — nothing grouped finer than DS division.

**Arithmetically honest.** A withheld row is still inside the district total. A page whose
subtotals do not add up to the figure on the screen before it costs more credibility than
the suppression saves.

**Readable at all.** The last test in this file is the one that matters most, and it exists
because the endpoints were silently broken before it: `aid.damage_assessment` is under FORCE
row-level security, a public session has the empty scope, and the empty scope covers
nothing. Every public query joining that table returned zero rows and looked exactly like a
country that had disbursed nothing. Nothing failed. See ledger-svc migration 0011.

Most of what follows needs no database, because it asserts properties of the SQL text and
of a pure function. That is deliberate: a privacy property that can only be checked by
booting Postgres is a privacy property that gets checked less often.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from ledger_svc.api.v1.public import DistrictMetrics, DSDivisionRow, PublicFunnel
from ledger_svc.domain.suppression import MIN_CELL_SIZE, apply_minimum_cell_size
from ledger_svc.repo.queries import (
    _PUBLIC_DISTRICT_DETAIL,
    _PUBLIC_DISTRICT_METRICS,
    _PUBLIC_FUNNEL,
)
from sarana_shared.db.sql import PUBLIC_AGGREGATE_SETTING

# --------------------------------------------------------------------------------------
# What the queries are not allowed to select
# --------------------------------------------------------------------------------------

PUBLIC_QUERIES = {
    "_PUBLIC_FUNNEL": _PUBLIC_FUNNEL,
    "_PUBLIC_DISTRICT_METRICS": _PUBLIC_DISTRICT_METRICS,
    "_PUBLIC_DISTRICT_DETAIL": _PUBLIC_DISTRICT_DETAIL,
}

# Columns that name a person, a place below the floor, or a position. Checked against the
# SQL text rather than against a response, because the anonymisation is a property of the
# query: a column that is never selected cannot leak however the serialiser changes.
FORBIDDEN_COLUMNS = (
    "nic",
    "phone",
    "msisdn",
    "contact_hash",
    "full_name",
    "public_ref",
    "gps_at_assessment",
    "gps_accuracy_m",
    "evidence_photo_uris",
    "geom",
    "centroid",
)


@pytest.mark.parametrize("name", sorted(PUBLIC_QUERIES))
def test_no_public_aggregate_selects_an_identifying_column(name: str) -> None:
    """A column that is never in the row cannot leak from the row."""
    sql = PUBLIC_QUERIES[name].lower()
    found = [column for column in FORBIDDEN_COLUMNS if column in sql]
    assert found == [], f"{name} selects {found}, which names a person or a position"


def outer_select(sql: str) -> str:
    """The projection that becomes the response, with the CTE bodies removed.

    A CTE may name `household_id` freely — `WITH accepted AS (SELECT a.household_id …)` is
    how the funnel gets something to count distinctly, and nothing in a CTE reaches a
    caller unless the outer query projects it. What matters is the final SELECT, so that is
    what these tests read.

    Splitting on a closing parenthesis at the start of a line, immediately followed by
    `SELECT`, is the boundary every query in this module writes. A query without a WITH
    clause has no such boundary and is returned whole, which is the correct answer for it.
    """
    return re.split(r"\n\)\n(?=SELECT)", sql)[-1]


@pytest.mark.parametrize("name", sorted(PUBLIC_QUERIES))
def test_household_id_is_only_ever_counted_never_projected(name: str) -> None:
    """`household_id` may be counted distinctly and must never reach a row.

    Counting households is the denominator every figure on the overview needs. Projecting
    one publishes a join key into the registry, which turns every aggregate on the page
    into a lookup — so the distinction is `COUNT(DISTINCT household_id)` against a bare
    column. Read from the SQL rather than from the response model, because the
    anonymisation is a property of the query and the model is only the second fence.
    """
    projection = outer_select(PUBLIC_QUERIES[name])

    for occurrence in re.finditer(r"household_id", projection):
        window = projection[max(0, occurrence.start() - 40) : occurrence.start()]
        assert "COUNT(DISTINCT" in window.upper(), (
            f"{name} projects household_id outside a COUNT(DISTINCT ...): "
            f"...{window.strip()}household_id..."
        )


@pytest.mark.parametrize("name", sorted(PUBLIC_QUERIES))
def test_no_public_aggregate_projects_a_gn_division_code(name: str) -> None:
    """The finest grain that reaches a caller is DS division.

    `gn_division_code` appears inside every one of these queries — it is what the district
    and DS codes are derived from — and it must not survive into the projection. A GN code
    beside a figure is how a small-cell suppression gets undone by a caption.
    """
    projection = outer_select(PUBLIC_QUERIES[name])
    # Counting the divisions a district assessed is a denominator, not a disclosure. The
    # alias is optional because the funnel counts a CTE column with no table prefix.
    counted = re.sub(
        r"COUNT\(DISTINCT\s+(?:\w+\.)?gn_division_code\)", "", projection, flags=re.IGNORECASE
    )
    assert "gn_division_code" not in counted, f"{name} projects a GN division code"


def test_nothing_is_grouped_below_ds_division() -> None:
    """The detail query groups by DS division and never by GN division.

    GN division is the level at which a four-household hamlet with one disbursement
    identifies a family by arithmetic. `gn_division_code` appears in the query - it is what
    the DS code is derived from and what `COUNT(DISTINCT ...)` counts - but never as a
    grouping key.
    """
    assert "GROUP BY 1" in _PUBLIC_DISTRICT_DETAIL
    assert "ds_division_code" in _PUBLIC_DISTRICT_DETAIL
    # The SELECT list is what reaches the caller. A bare `gn_division_code` in it would
    # publish the finest grain the platform holds.
    select_list = _PUBLIC_DISTRICT_DETAIL.split("FROM scoped")[0]
    assert "s.gn_division_code" not in select_list.replace("COUNT(DISTINCT s.gn_division_code)", "")


# --------------------------------------------------------------------------------------
# The response models
# --------------------------------------------------------------------------------------


def test_no_public_response_model_has_a_field_that_could_name_anybody() -> None:
    """The second fence, after the SQL: there is no field to put a name in."""
    for model in (PublicFunnel, DistrictMetrics, DSDivisionRow):
        fields = set(model.model_fields)
        assert not (fields & {"household_id", "nic", "phone", "name", "gn_division_code"}), (
            f"{model.__name__} has a field that could carry an identifier: {fields}"
        )


def test_the_funnel_reports_its_failures_as_first_class_fields() -> None:
    """Unconfirmed, disputed and reversed are siblings of disbursed, not a nested object.

    The brief is explicit that the uncomfortable figures carry the same prominence as the
    good ones. The response shape is the first thing that decides whether a page can bury
    them: a nested `problems` object is one `if` away from being left out of a render.
    """
    fields = set(PublicFunnel.model_fields)
    for failure in (
        "unconfirmed_count",
        "awaiting_reply_count",
        "reversed_count",
        "reversed_lkr_cents",
    ):
        assert failure in fields, f"{failure} is not a top-level field on the funnel"


def test_a_district_with_no_disbursements_can_report_null_rather_than_zero() -> None:
    """Null is an absence; zero is a measurement, and a choropleth colours them apart.

    A district that has disbursed nothing has no confirmation rate and no median wait. If
    those were typed as `int`/`float` the endpoint would have to send zero, and a map would
    paint the district that paid nobody the same colour as the one that paid everybody
    instantly.
    """
    for field in (
        "confirmation_rate",
        "median_days_to_disbursement",
        "disbursed_per_household_lkr_cents",
        "grievance_rate_per_1000_disbursements",
    ):
        annotation = DistrictMetrics.model_fields[field].annotation
        assert "None" in str(annotation), f"{field} cannot express 'no data'"


# --------------------------------------------------------------------------------------
# The privacy floor
# --------------------------------------------------------------------------------------


def a_division(code: str, *, disbursed: int, cents: int = 0) -> dict[str, Any]:
    return {
        "ds_division_code": code,
        "assessed_count": 10,
        "assessed_households": 10,
        "assessed_divisions": 2,
        "assessed_lkr_cents": 1_000_00,
        "approved_count": 8,
        "approved_lkr_cents": 800_00,
        "disbursed_count": disbursed,
        "disbursed_lkr_cents": cents,
        "confirmed_count": max(0, disbursed - 1),
        "median_wait_seconds": 86_400,
    }


def test_a_cell_below_the_floor_is_withheld() -> None:
    result = apply_minimum_cell_size(
        [a_division("LK-21-01", disbursed=4, cents=400)], min_cell=MIN_CELL_SIZE
    )
    assert result.rows == []
    assert result.divisions == 1
    assert result.disbursements == 4


def test_a_cell_at_the_floor_is_published() -> None:
    """Five is the floor, not the first suppressed value. An off-by-one here withholds a
    division that policy says may be published, which is a quieter failure than the
    reverse and just as wrong."""
    result = apply_minimum_cell_size(
        [a_division("LK-21-01", disbursed=MIN_CELL_SIZE, cents=500)], min_cell=MIN_CELL_SIZE
    )
    assert [row["ds_division_code"] for row in result.rows] == ["LK-21-01"]
    assert result.divisions == 0


def test_a_division_that_disbursed_nothing_is_published_as_a_zero() -> None:
    """The single most useful row on the page, and the one a naive filter drops.

    Only a small *non-zero* cell identifies anybody. "Nothing was paid in this division" is
    a finding, not a privacy risk, and withholding it would hide exactly what a reader came
    for.
    """
    result = apply_minimum_cell_size([a_division("LK-21-02", disbursed=0)], min_cell=MIN_CELL_SIZE)
    assert [row["ds_division_code"] for row in result.rows] == ["LK-21-02"]
    assert result.divisions == 0


def test_withheld_money_is_still_inside_the_district_total() -> None:
    """The columns add up, or the page contradicts the one before it."""
    rows = [
        a_division("LK-21-01", disbursed=40, cents=40_000),
        a_division("LK-21-02", disbursed=3, cents=3_000),
        a_division("LK-21-03", disbursed=2, cents=2_000),
    ]
    result = apply_minimum_cell_size(rows, min_cell=MIN_CELL_SIZE)

    assert len(result.rows) == 1
    assert result.divisions == 2
    assert result.disbursements == 5
    assert result.lkr_cents == 5_000
    # 40,000 published + 5,000 withheld. The total is over every row, not over the
    # published subset.
    assert result.totals["disbursed_lkr_cents"] == 45_000
    assert result.totals["disbursed_count"] == 45


def test_raising_the_floor_withholds_more_and_still_totals_the_same() -> None:
    """The floor can be raised. Whatever it is, the total does not move."""
    rows = [
        a_division("LK-21-01", disbursed=6, cents=6_000),
        a_division("LK-21-02", disbursed=20, cents=20_000),
    ]
    at_five = apply_minimum_cell_size(rows, min_cell=5)
    at_ten = apply_minimum_cell_size(rows, min_cell=10)

    assert len(at_five.rows) == 2
    assert len(at_ten.rows) == 1
    assert at_ten.divisions == 1
    assert at_five.totals == at_ten.totals


def test_the_suppression_result_never_carries_a_row_it_withheld() -> None:
    """A withheld row must not survive anywhere in the payload, including the totals row.

    The totals are integers by construction - `Suppressed.totals` is `dict[str, int]` - so
    a division code cannot ride along inside them.
    """
    rows = [a_division("LK-21-09", disbursed=1, cents=100)]
    result = apply_minimum_cell_size(rows, min_cell=MIN_CELL_SIZE)

    assert "LK-21-09" not in repr(result.rows)
    assert all(isinstance(value, int) for value in result.totals.values())


# --------------------------------------------------------------------------------------
# The row-security marker
# --------------------------------------------------------------------------------------


def test_the_marker_name_matches_the_policy_that_tests_for_it() -> None:
    """Python and the migration spell the session variable identically.

    A typo in either would silently restore the bug migration 0011 fixed: the policy would
    never match, `aid.damage_assessment` would stay invisible to a public session, and
    every figure on the dashboard would read zero with nothing failing anywhere.
    """
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[2]
        / "services"
        / "ledger-svc"
        / "alembic"
        / "versions"
        / "20260908_0011_public_aggregate_reads.py"
    ).read_text(encoding="utf-8")

    assert f'PUBLIC_AGGREGATE_SETTING = "{PUBLIC_AGGREGATE_SETTING}"' in migration
    assert PUBLIC_AGGREGATE_SETTING in migration


def test_the_policy_is_select_only() -> None:
    """The marker widens reads and nothing else.

    ADR-006's single-writer property - a GN officer owns the assessments for their own
    division and nobody else may write them - is what makes the offline operation log
    sufficient and a CRDT unnecessary. A permissive policy without `FOR SELECT` would let
    an unauthenticated session write, which would undo it.
    """
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[2]
        / "services"
        / "ledger-svc"
        / "alembic"
        / "versions"
        / "20260908_0011_public_aggregate_reads.py"
    ).read_text(encoding="utf-8")

    policy = migration[migration.index("CREATE POLICY assessment_public_aggregate") :]
    assert "FOR SELECT" in policy.split('"""')[0]


def test_the_public_session_sets_the_marker() -> None:
    """The one caller. If this call is removed the dashboard silently reads zeroes."""
    import inspect

    from ledger_svc.api.deps import get_public_session

    source = inspect.getsource(get_public_session)
    assert "mark_public_aggregate_read" in source
    # And it still applies the empty scope: the marker widens one table, it does not
    # replace row-level security for the session.
    assert "apply_row_security_scope" in source
