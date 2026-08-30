"""The administrative hierarchy: the reference data everything else joins against."""

from __future__ import annotations

from core_api.domain.hierarchy.queries import (
    DEFAULT_SIMPLIFY_TOLERANCE,
    MAX_SIMPLIFY_TOLERANCE,
    RESOLVE_PRECISION,
    division_contacts,
    get_gn_division,
    get_gn_geometry,
    household_contact,
    list_districts,
    list_ds_divisions,
    list_gn_divisions,
    list_households,
    list_provinces,
    resolve_cache_key,
    resolve_point,
)

__all__ = [
    "DEFAULT_SIMPLIFY_TOLERANCE",
    "MAX_SIMPLIFY_TOLERANCE",
    "RESOLVE_PRECISION",
    "division_contacts",
    "get_gn_division",
    "get_gn_geometry",
    "household_contact",
    "list_districts",
    "list_ds_divisions",
    "list_gn_divisions",
    "list_households",
    "list_provinces",
    "resolve_cache_key",
    "resolve_point",
]
