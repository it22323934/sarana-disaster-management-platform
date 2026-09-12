"""The public area reference publishes places, never people.

`admin.household` is the one table in the `admin` schema that is about individuals, and it
is the only one under row-level security. The endpoints build file 21 added are anonymous,
so the property that has to hold is simple and absolute: they do not read that table, and
they do not read anything derived from it.

The second thing checked here is the geometry claim. This seed carries boundaries at GN
level only, as generated rectangles around real district centroids, so a district outline
is the union of those rectangles. That is an accurate statement about where the platform
believes its divisions are and it is not a survey boundary. Every geometry response says so
in the payload, because a caveat that lives only in a release note is a caveat nobody reads.
"""

from __future__ import annotations

import re

from core_api.api.v1.public import GEOMETRY_NOTE, PublicDistrict, PublicDSDivision
from core_api.domain.hierarchy.queries import (
    _PUBLIC_DISTRICT_GEOMETRY_SQL,
    _PUBLIC_DISTRICTS_SQL,
    _PUBLIC_DS_DIVISIONS_SQL,
)

PUBLIC_AREA_QUERIES = {
    "_PUBLIC_DISTRICTS_SQL": _PUBLIC_DISTRICTS_SQL,
    "_PUBLIC_DS_DIVISIONS_SQL": _PUBLIC_DS_DIVISIONS_SQL,
    "_PUBLIC_DISTRICT_GEOMETRY_SQL": _PUBLIC_DISTRICT_GEOMETRY_SQL,
}


def test_no_public_area_query_reads_the_household_table() -> None:
    """The one table in this schema that is about people is not in any of these queries.

    Stronger than a redaction, and the reason `admin.household` carries FORCE row-level
    security as well: even if this assertion were removed, an anonymous session's empty
    scope covers nothing and the table would come back empty. Two fences, and this is the
    one that fails loudly at build time rather than quietly at run time.
    """
    for name, sql in PUBLIC_AREA_QUERIES.items():
        assert "household" not in sql.lower().replace("household_count", ""), (
            f"{name} reads admin.household"
        )


def test_the_area_queries_publish_population_but_never_a_person() -> None:
    """`population` and `household_count` are columns on the division, not on a household.

    They are the denominators every per-capita figure on the dashboard needs. Summing them
    is aggregation over a place; the household table is not touched to produce either.
    """
    for sql in (_PUBLIC_DISTRICTS_SQL, _PUBLIC_DS_DIVISIONS_SQL):
        assert "SUM(g.population)" in sql
        assert "SUM(g.household_count)" in sql
        assert "admin.gn_division" in sql


def test_the_public_area_models_carry_a_code_and_a_trilingual_name() -> None:
    """The code is the identity and the name is a label, throughout SARANA.

    A page that keyed on the name would break the first time a district was transliterated
    differently; the codes are what every figure on the dashboard joins by.
    """
    for model in (PublicDistrict, PublicDSDivision):
        assert "code" in model.model_fields
        assert "dict[str, str]" in str(model.model_fields["name"].annotation)


def test_the_district_outline_is_built_from_its_divisions_not_from_a_stored_boundary() -> None:
    """`admin.district.geom` is null in this seed and the query does not read it.

    The seed generates geometry at GN level only. Reading a null district boundary would
    return an empty map; inventing one would publish a shape nothing supports. Dissolving
    the members says exactly what the platform knows.
    """
    assert "ST_Union(g.geom)" in _PUBLIC_DISTRICT_GEOMETRY_SQL
    assert "d.geom" not in _PUBLIC_DISTRICT_GEOMETRY_SQL


def test_the_simplification_preserves_topology() -> None:
    """A simplification that crossed a boundary over itself would place one district inside
    another. `ST_SimplifyPreserveTopology` is what the GN geometry endpoint uses for the
    same reason, and the plain `ST_Simplify` is not used anywhere near a boundary."""
    assert "ST_SimplifyPreserveTopology" in _PUBLIC_DISTRICT_GEOMETRY_SQL
    assert not re.search(r"(?<!Preserve)\bST_Simplify\(", _PUBLIC_DISTRICT_GEOMETRY_SQL)


def test_the_geometry_response_says_the_boundaries_are_generated() -> None:
    """Stated in the payload, not in a release note.

    A consumer that pulls this GeoJSON into a mapping tool never sees our documentation.
    The note travels with the data, and it names what the shapes are and what they must not
    be used for.
    """
    assert "not survey boundaries" in GEOMETRY_NOTE
    assert "generated" in GEOMETRY_NOTE.lower()
    assert "navigation" in GEOMETRY_NOTE


def test_the_district_geometry_is_ordered_so_its_etag_is_stable() -> None:
    """These responses are ETagged and cached for an hour.

    Without a deterministic order, Postgres choosing a different plan changes the byte order
    of the payload, which changes the ETag, which makes every conditional request a full
    download of a map that had not changed.
    """
    assert _PUBLIC_DISTRICT_GEOMETRY_SQL.rstrip().endswith("ORDER BY d.code")
