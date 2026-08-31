"""Wiring the forecast agent to the real world: the feeds, core-api, and the database.

Three adapters, one per port, and none of them contain a decision. Everything that decides
anything lives in `agents/forecast/`, which is why the whole agent can be replayed against a
frozen fixture and why these can be as thin as they are.

## What each one refuses to fake

**`GovHazardFeeds`** raises when a source is unreachable rather than returning nothing. A
forecast run that scored every division against zero rainfall would complete successfully
and report a quiet day during a cyclone, which is the worst way for a forecasting service to
be broken.

**`CoreApiDivisions`** does the same. Without exposure attributes every division scores
against the default hazard zone, and a forecast that is confidently wrong about which slopes
are fragile is worse than no forecast.

**`SqlForecastStore`** writes forecasts and firings in one transaction. A trigger row whose
`forecast_id` points at nothing cannot be reviewed after the event, which is the only
question worth asking about a pre-agreed rule.
"""

from __future__ import annotations

from typing import Any, Final

import httpx
import structlog
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_svc.agents.forecast.exposure import DivisionExposure, StationReading
from agent_svc.agents.forecast.reconcile import SourceClaim
from agent_svc.agents.forecast.scoring import ZoneThresholds
from agent_svc.repo.hazard import AnticipatoryTrigger, ImpactForecast
from sarana_shared.adapters.gov.base import GovUpstreamError
from sarana_shared.adapters.gov.met import MetClient
from sarana_shared.adapters.gov.nbro import NbroClient
from sarana_shared.auth.service_credentials import CredentialUnavailable, ServiceCredentials
from sarana_shared.errors import UpstreamUnavailable

_log = structlog.get_logger(__name__)

CONNECT_TIMEOUT: Final = 2.0
READ_TIMEOUT: Final = 10.0

# One call fetches every division in the warned districts. High because a national cyclone
# warning names all 25 districts; see the endpoint's own comment on why truncating silently
# would be worse than a large response.
EXPOSURE_LIMIT: Final = 20_000

# The windows the Department publishes. Asking for any other returns 422, so a mistake here
# is a silent gap in the forecast rather than an error.
FORECAST_WINDOWS: Final[tuple[int, ...]] = (24, 48, 72)


class FeedsUnavailable(UpstreamUnavailable):
    """A hazard feed could not be reached.

    Raised rather than degraded to an empty reading, because "no rainfall was reported" and
    "we could not ask" produce identical forecasts and completely different truths.
    """


class ExposureUnavailable(UpstreamUnavailable):
    """core-api could not be reached for division exposure."""


class GovHazardFeeds:
    """The Met Department and NBRO, behind the `HazardFeeds` port."""

    def __init__(self, *, met: MetClient, nbro: NbroClient) -> None:
        self._met = met
        self._nbro = nbro

    async def aclose(self) -> None:
        await self._met.aclose()
        await self._nbro.aclose()

    async def warned_districts(self) -> tuple[str, ...]:
        """Every district any warning currently in force names.

        Returns an empty tuple when nothing is in force, which is the ordinary quiet-day
        answer and produces a run that scores nothing. That is different from a feed being
        down, which raises.
        """
        try:
            warnings = await self._met.warnings()
        except GovUpstreamError as error:
            raise FeedsUnavailable(
                "The Department of Meteorology could not be reached, so which districts "
                "are warned is unknown. No forecast was produced."
            ) from error

        codes: set[str] = set()
        for warning in warnings:
            codes.update(warning.district_codes)
        return tuple(sorted(codes))

    async def observations(self) -> list[StationReading]:
        """Current gauge readings, including the stations that are silent.

        The silent ones are carried, not filtered: a station that has lost power reads the
        same as one recording no rain, and treating them alike understates exactly the
        districts in the worst trouble.
        """
        try:
            readings = await self._met.observations()
        except GovUpstreamError as error:
            raise FeedsUnavailable(
                "Station observations could not be read. Scoring against no rainfall "
                "would report a quiet day."
            ) from error

        return [
            StationReading(
                station_id=reading.station_id,
                lon=reading.lon,
                lat=reading.lat,
                rainfall_mm_24h=reading.rainfall_mm_24h,
                reporting=reading.reporting,
            )
            for reading in readings
        ]

    async def district_forecast(self, *, district_code: str, hours: int) -> float:
        """Expected 24-hour accumulation at the midpoint of a forward window.

        A single district's forecast failing is not fatal to the run: the division still
        has its observation, and one district losing its forward look is better than the
        whole country losing its forecast. It is logged, and the confidence already falls
        for a division with thin inputs.
        """
        try:
            forecast = await self._met.rainfall_forecast(district_code=district_code, hours=hours)
        except GovUpstreamError as error:
            _log.warning(
                "forecast_district_window_unavailable",
                district_code=district_code,
                hours=hours,
                error=type(error).__name__,
                impact="this district is scored on its observation alone for this window",
            )
            return 0.0
        return forecast.expected_mm

    async def thresholds(self) -> dict[int, ZoneThresholds]:
        """NBRO's rainfall thresholds, one set per hazard zone.

        Raises rather than defaulting. Every impact class in this platform is a comparison
        against these numbers, and inventing them would make the entire forecast a fiction
        with a government logo on it.
        """
        try:
            sets = await self._nbro.rain_thresholds()
        except GovUpstreamError as error:
            raise FeedsUnavailable(
                "NBRO's rainfall thresholds could not be read. Every impact class is a "
                "comparison against them, so no forecast was produced."
            ) from error

        return {
            int(threshold.zone): ZoneThresholds(
                zone=int(threshold.zone),
                window_hours=threshold.window_hours,
                watch_mm=threshold.watch_mm,
                warning_mm=threshold.warning_mm,
                evacuate_mm=threshold.evacuate_mm,
                provenance=threshold.provenance,
            )
            for threshold in sets
        }

    async def claims(self, *, district_codes: tuple[str, ...]) -> list[SourceClaim]:
        """Both institutions' statements, flattened onto one scale.

        NBRO bulletins are DS-scoped and Met warnings are district-scoped; the difference
        is preserved in `scope_type`, because specificity is what breaks a tie between two
        sources at the same severity.
        """
        claims: list[SourceClaim] = []

        try:
            for warning in await self._met.warnings():
                for code in warning.district_codes:
                    if code in district_codes:
                        claims.append(
                            SourceClaim(
                                source="DEPT_METEOROLOGY",
                                level=str(warning.level).upper(),
                                scope_type="district",
                                scope_code=code,
                                issued_at=warning.issued_at,
                                headline=warning.headline,
                            )
                        )
        except GovUpstreamError as error:
            raise FeedsUnavailable("Met warnings could not be read.") from error

        try:
            bulletins = await self._nbro.bulletins()
        except GovUpstreamError as error:
            # One source missing is not the same as none. The reconciliation floor takes
            # the most severe of what it has, and losing NBRO can only make the answer
            # *less* severe - so it is logged loudly rather than swallowed.
            _log.error(
                "forecast_nbro_bulletins_unavailable",
                error=type(error).__name__,
                impact="landslide bulletins are missing from this reconciliation; the "
                "hazard level may be lower than NBRO would say",
            )
            bulletins = []

        for bulletin in bulletins:
            for ds_code in bulletin.ds_division_codes:
                claims.append(
                    SourceClaim(
                        source="NBRO",
                        level=bulletin.level.upper(),
                        scope_type="ds_division",
                        scope_code=ds_code,
                        issued_at=bulletin.issued_at,
                        headline=bulletin.advice[:120],
                    )
                )
        return claims


class CoreApiDivisions:
    """Division exposure from core-api, behind the `DivisionDirectory` port."""

    def __init__(
        self,
        base_url: str,
        *,
        credentials: ServiceCredentials,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._credentials = credentials
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        )
        # Exposure attributes change when a survey is redone, which is a matter of years.
        # Re-fetching several hundred rows every fifteen minutes during an event is a
        # self-inflicted load spike on the service everything else depends on.
        self._cache: dict[str, list[DivisionExposure]] = {}
        self._names: dict[str, dict[str, str]] = {}

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
        await self._credentials.aclose()

    async def divisions_in(self, district_codes: tuple[str, ...]) -> list[DivisionExposure]:
        key = ",".join(sorted(district_codes))
        if not key:
            return []
        if key in self._cache:
            return self._cache[key]

        try:
            headers = await self._credentials.authorization()
        except CredentialUnavailable as error:
            raise ExposureUnavailable(
                "No service credential is available to read division exposure. Run "
                "`make service-clients` and set SARANA_AGENT_CLIENT_SECRET."
            ) from error

        try:
            response = await self._client.get(
                f"{self._base_url}/api/v1/admin/gn-divisions/exposure",
                params={"districts": key, "limit": EXPOSURE_LIMIT},
                headers=headers,
            )
            response.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as error:
            raise ExposureUnavailable(
                "core-api could not be reached for division exposure. Without it every "
                "division would score against the default hazard zone."
            ) from error

        rows = response.json()
        divisions = [_division_from(row) for row in rows]
        self._cache[key] = divisions
        for row in rows:
            self._names[str(row["id"])] = row.get("name", {})

        _log.info("forecast_exposure_loaded", districts=key, divisions=len(divisions))
        return divisions

    async def names(self, gn_division_ids: list[str]) -> dict[str, dict[str, str]]:
        """Trilingual names, from whatever the exposure fetch already cached.

        No second call: a run always loads exposure before it needs a name, and asking
        core-api again for text it has already sent would be a round trip per division at
        the busiest moment.
        """
        return {
            division_id: self._names[division_id]
            for division_id in gn_division_ids
            if division_id in self._names
        }


def _division_from(row: dict[str, Any]) -> DivisionExposure:
    return DivisionExposure(
        gn_division_id=str(row["id"]),
        gn_division_code=str(row["code"]),
        ds_division_code=str(row.get("ds_division_code", "")),
        district_code=str(row.get("district_code", "")),
        centroid_lon=float(row.get("centroid_lon") or 0.0),
        centroid_lat=float(row.get("centroid_lat") or 0.0),
        household_count=int(row.get("household_count") or 0),
        population=int(row.get("population") or 0),
        landslide_zone=row.get("landslide_zone"),
        flood_return_period_m=row.get("flood_return_period_m"),
        road_access_class=row.get("road_access_class"),
        cell_coverage_pct=_as_float(row.get("cell_coverage_pct")),
        elderly_pct=_as_float(row.get("elderly_pct")),
        under5_pct=_as_float(row.get("under5_pct")),
    )


def _as_float(value: Any) -> float | None:
    """Numeric columns come back as strings over JSON. None stays None.

    A missing percentage is not zero: zero elderly residents and an unsurveyed division
    look identical afterwards and mean opposite things for who gets checked on first.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class SqlForecastStore:
    """Forecasts and trigger firings, written in one transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory
        self._pending_ids: list[str] = []

    async def save_forecasts(self, rows: list[dict[str, Any]]) -> list[str]:
        """Insert forecast rows and return their ids, in the order given.

        One statement rather than a loop: a generation writes several hundred rows and a
        round trip each would take longer than the interval between generations.

        Rows are never updated. A new run writes new rows and the unique key includes
        `generated_at`, so the whole forecast history for a division is reconstructable -
        which is what makes the Learn loop's accuracy scoring honest rather than a
        comparison against a number somebody overwrote.
        """
        if not rows:
            return []

        async with self._factory() as session:
            result = await session.execute(
                insert(ImpactForecast).returning(ImpactForecast.id), rows
            )
            ids = [str(row[0]) for row in result.fetchall()]
            await session.commit()

        self._pending_ids = ids
        _log.info("forecast_rows_written", count=len(ids))
        return ids

    async def save_firings(self, rows: list[dict[str, Any]]) -> None:
        """Insert anticipatory trigger rows.

        Every row records the forecast that fired it and the action taken. The database
        CHECK requires that a fired trigger names its action even when the answer is
        NO_ACTION, because a firing nobody can attribute an outcome to is one an
        after-action review cannot judge.
        """
        if not rows:
            return

        from datetime import UTC, datetime

        now = datetime.now(UTC)
        prepared = [
            {
                "hazard_event_id": row["hazard_event_id"],
                "gn_division_id": row["gn_division_id"],
                "gn_division_code": row["gn_division_code"],
                "condition": row["condition"],
                "fired_at": now,
                "action_taken": row["action_taken"],
                "forecast_id": row.get("forecast_id"),
                "notes": row.get("notes"),
            }
            for row in rows
        ]

        async with self._factory() as session:
            await session.execute(insert(AnticipatoryTrigger), prepared)
            await session.commit()

        _log.info("forecast_triggers_written", count=len(prepared))
