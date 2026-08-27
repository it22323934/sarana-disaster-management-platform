"""The `admin` schema: Sri Lanka's administrative hierarchy, households, users and roles.

    Province (9)
      District (25)
        DS Division (331)
          GN Division (~14,022)
            Household

Codes are official and hierarchical, and a parent's code is always a prefix of its
child's. Row-level security leans on that: covering a district is a prefix test, not a
recursive join.
"""

from __future__ import annotations

from typing import Any

from geoalchemy2 import Geography, Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core_api.repo.base import ADMIN_SCHEMA
from sarana_shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sarana_shared.db.constraints import localised
from sarana_shared.domain.geo import SRID_WGS84


class Province(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One of the nine provinces."""

    __tablename__ = "province"
    __table_args__ = (
        localised("name"),
        CheckConstraint("code ~ '^LK-P[0-9]{2}$'", name="code_shape"),
        {"schema": ADMIN_SCHEMA},
    )

    code: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    name: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=SRID_WGS84, spatial_index=False),
        nullable=True,
    )


class District(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One of the twenty-five districts. Second-level entitlement approval sits here."""

    __tablename__ = "district"
    __table_args__ = (
        localised("name"),
        CheckConstraint("code ~ '^LK-[0-9]{2}$'", name="code_shape"),
        Index("ix_district_geom", "geom", postgresql_using="gist"),
        {"schema": ADMIN_SCHEMA},
    )

    code: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    province_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ADMIN_SCHEMA}.province.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=SRID_WGS84, spatial_index=False),
        nullable=True,
    )


class DSDivision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A Divisional Secretariat division. First-level entitlement approval sits here."""

    __tablename__ = "ds_division"
    __table_args__ = (
        localised("name"),
        CheckConstraint("code ~ '^LK-[0-9]{2}-[0-9]{2}$'", name="code_shape"),
        Index("ix_ds_division_geom", "geom", postgresql_using="gist"),
        {"schema": ADMIN_SCHEMA},
    )

    code: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    district_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ADMIN_SCHEMA}.district.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=SRID_WGS84, spatial_index=False),
        nullable=True,
    )


class GNDivision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A Grama Niladhari division: the smallest administrative unit, ~14,022 of them.

    One GN officer per division. They perform damage assessments and are the primary
    Field Companion user.

    The static vulnerability columns are exposure denominators for the Forecast and
    Impact agent. They change on a census cycle, not during a disaster, which is why they
    live here rather than in the Resilience Graph.
    """

    __tablename__ = "gn_division"
    __table_args__ = (
        localised("name"),
        CheckConstraint("code ~ '^LK-[0-9]{2}-[0-9]{2}-[0-9]{3}$'", name="code_shape"),
        CheckConstraint("population >= 0", name="population_non_negative"),
        CheckConstraint("household_count >= 0", name="household_count_non_negative"),
        CheckConstraint(
            "elderly_pct IS NULL OR elderly_pct BETWEEN 0 AND 100", name="elderly_pct_range"
        ),
        CheckConstraint(
            "under5_pct IS NULL OR under5_pct BETWEEN 0 AND 100", name="under5_pct_range"
        ),
        # NBRO publishes four landslide hazard zones.
        CheckConstraint(
            "landslide_zone IS NULL OR landslide_zone BETWEEN 1 AND 4",
            name="landslide_zone_range",
        ),
        CheckConstraint(
            "cell_coverage_pct IS NULL OR cell_coverage_pct BETWEEN 0 AND 100",
            name="cell_coverage_pct_range",
        ),
        Index("ix_gn_division_geom", "geom", postgresql_using="gist"),
        Index("ix_gn_division_centroid", "centroid", postgresql_using="gist"),
        {"schema": ADMIN_SCHEMA},
    )

    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    ds_division_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ADMIN_SCHEMA}.ds_division.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)

    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=SRID_WGS84, spatial_index=False),
        nullable=False,
    )
    # Generated, not stored by the application: a centroid that disagrees with its own
    # boundary would send responders to the wrong place.
    centroid: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=SRID_WGS84, spatial_index=False),
        server_default=None,
        nullable=True,
    )

    population: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    household_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    elderly_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    under5_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    landslide_zone: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    flood_return_period_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    road_access_class: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    cell_coverage_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)


class Household(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A household. Every column that identifies a person is encrypted at rest.

    ADR-011: this data leaves Sri Lanka to run in ap-south-1, and PDPA No. 9 of 2022 will
    eventually bind cross-border transfer. Field-level encryption is applied now so that
    the answer to a government partner on day one is a design, not a promise.

    `contact_msisdn_hash` is an HMAC-SHA256 keyed from Secrets Manager. Inbound SMS
    resolves a sender to a household by looking up the HMAC, so the platform never
    decrypts a phone number just to route a message.
    """

    __tablename__ = "household"
    __table_args__ = (
        CheckConstraint(
            "preferred_language IN ('si','ta','en')", name="preferred_language_supported"
        ),
        CheckConstraint("member_count >= 0", name="member_count_non_negative"),
        CheckConstraint(
            "location_accuracy_m IS NULL OR location_accuracy_m > 0",
            name="location_accuracy_positive",
        ),
        Index("ix_household_location", "location", postgresql_using="gist"),
        {"schema": ADMIN_SCHEMA},
    )

    gn_division_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ADMIN_SCHEMA}.gn_division.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    reference_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)

    head_name_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    contact_msisdn_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    contact_msisdn_hash: Mapped[str | None] = mapped_column(
        Text, nullable=True, index=True, doc="HMAC-SHA256, for lookup without decryption"
    )

    member_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    has_over_70: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    has_under_5: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    has_mobility_impairment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    location: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=SRID_WGS84, spatial_index=False), nullable=True
    )
    location_accuracy_m: Mapped[int | None] = mapped_column(Integer, nullable=True)

    preferred_language: Mapped[str] = mapped_column(String(2), nullable=False, server_default="si")


class AppUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An account. Officers, operators, approvers, auditors and citizens alike."""

    __tablename__ = "app_user"
    __table_args__ = (
        CheckConstraint(
            "status IN ('INVITED','ACTIVE','SUSPENDED','DEACTIVATED')", name="status_known"
        ),
        {"schema": ADMIN_SCHEMA},
    )

    email: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    phone_hash: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="INVITED")
    mfa_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    last_login_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=True)


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named role. Scopes are resolved from the role code in `sarana_shared.auth`."""

    __tablename__ = "role"
    __table_args__ = (
        localised("name"),
        CheckConstraint(
            "code IN ('CITIZEN','GN_OFFICER','DS_APPROVER','DISTRICT_APPROVER',"
            "'DMC_OPERATOR','DISPATCHER','AUDITOR','ADMIN')",
            name="code_known",
        ),
        {"schema": ADMIN_SCHEMA},
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)


class UserRole(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A role held by a user, within an administrative scope.

    Permission and area are two independent checks and both must pass. Holding
    DS_APPROVER is not enough to approve an entitlement in another district, which is
    what `scope_type` and `scope_code` carry.

    The scope is stored as an official code rather than a foreign key so that row-level
    security can do a prefix test without joining through three levels of the hierarchy
    on every row.
    """

    __tablename__ = "user_role"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "scope_code", name="uq_user_role_scope"),
        CheckConstraint("scope_type IN ('GN','DS','DISTRICT','NATIONAL')", name="scope_type_known"),
        CheckConstraint(
            "(scope_type = 'NATIONAL' AND scope_code = 'LK')"
            " OR (scope_type = 'DISTRICT' AND scope_code ~ '^LK-[0-9]{2}$')"
            " OR (scope_type = 'DS' AND scope_code ~ '^LK-[0-9]{2}-[0-9]{2}$')"
            " OR (scope_type = 'GN' AND scope_code ~ '^LK-[0-9]{2}-[0-9]{2}-[0-9]{3}$')",
            name="scope_code_matches_type",
        ),
        {"schema": ADMIN_SCHEMA},
    )

    user_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ADMIN_SCHEMA}.app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ADMIN_SCHEMA}.role.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
