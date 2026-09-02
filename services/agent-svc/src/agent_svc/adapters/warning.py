"""Wiring the warning agent to the real world: alerting-svc, core-api, and the database.

Four adapters, one per port, and none of them contains a decision. Everything that decides
anything lives in `agents/warning/`, which is why the whole agent can be run against fakes
and why these can be as thin as they are.

## What each one refuses to fake

**`AlertingCatalogue`** raises when the catalogue cannot be read. An empty list means "no
published template fits", which routes to a DMC operator - and an outage dressed up as that
question would put an officer in front of a decision the platform invented during a cyclone.

**`CoreApiTargets`** raises when core-api is unreachable, and returns unreachable households
rather than dropping them. Those two failures look identical in a delivery total and mean
opposite things: one is a platform outage, the other is a list of people who need a vehicle.

**`AlertingDispatcher`** never raises for one channel's failure - that is a `ChannelOutcome`
carrying an error, and the gap report counts the difference. A warning that reached five
channels and failed on the sixth is a warning that reached five channels.

**`SqlForecasts`** reads only the newest generation. `hazard.impact_forecast` is never
updated - a new run writes new rows - so a source returning everything it found would hand
the agent the same division at class 2 from six hours ago and class 4 from ten minutes ago.

## The credentials, and the one worth arguing about

All three HTTP adapters use the agent-svc client-credentials grant, requested per scope
rather than as one bundle - they are one machine identity, and keeping the scopes separate
is what lets a token audit see which of them a given call actually needed.

`household:contact_read` is the one to think hardest about. Until file 14 it was held by
alerting-svc alone, and that was the point: it is the difference between a service whose
database dump is uninteresting and one whose dump is a list of everybody's phone. The
warning agent holds it because targeting is per household - deduplicating two households
that share a handset, routing language per household, counting the households with no
channel at all - and each of those is the difference between a delivery figure that is real
and one that is decorative. The alternative, an endpoint on alerting-svc that resolves
targets on this agent's behalf, keeps the scope in one place and is the better shape; it is
more work than file 14 asks for and it is written down in HANDOFF.md rather than left as a
thing somebody inherits without noticing.

`alert:dispatch` on a machine is a smaller question than it looks. The soft human gate for
an alert lives in the alert's own `requires_human_signoff` column and in this agent's gated
tool, not in the token - and the two scopes a machine genuinely may never hold,
`dispatch:commit` and `disbursement:release`, are stripped at mint time regardless of what
any credential table says.
"""

from __future__ import annotations

from typing import Any, Final

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_svc.agents.warning.ports import (
    AlertTemplate,
    ChannelOutcome,
    DispatchOrder,
    DivisionReach,
    ForecastedDivision,
    PriorAlert,
    Receipt,
    WarningTarget,
)
from agent_svc.repo.hazard import ImpactForecast
from sarana_shared.auth.service_credentials import CredentialUnavailable, ServiceCredentials
from sarana_shared.errors import UpstreamUnavailable

_log = structlog.get_logger(__name__)

CONNECT_TIMEOUT: Final = 2.0
READ_TIMEOUT: Final = 10.0

# One page of a bulk household read, and how many pages one alert may take. The ceiling is
# the same reasoning as alerting-svc's: a caller naming half the country gets a refusal
# rather than a fan-out that silently covered the first hundred thousand households.
PAGE_SIZE: Final = 2_000
MAX_PAGES: Final = 200

# Fetching division exposure for the coverage figure. High because a national cyclone
# warning names every district.
EXPOSURE_LIMIT: Final = 20_000

# Languages a division is treated as having, by share of speakers in reference data. Below
# this a language is not in the division's dominant set - it is still reachable through a
# household's own stated preference, which is what actually routes most messages.
DOMINANT_LANGUAGE_PCT: Final = 15.0


class CatalogueUnavailable(UpstreamUnavailable):
    """The alert template catalogue could not be read."""

    slug = "alert-catalogue-unavailable"
    title = "Alert template catalogue unavailable"


class TargetsUnavailable(UpstreamUnavailable):
    """core-api could not be reached for households or division coverage."""

    slug = "warning-targets-unavailable"
    title = "Household directory unavailable"


class DispatchUnavailable(UpstreamUnavailable):
    """alerting-svc could not be reached to send an alert.

    Distinct from a channel failing. This is "the warning was never handed to anything",
    and it must never be recorded as a dispatch whose channels all happened to fail - one
    is a platform outage somebody fixes, the other is a coverage gap somebody drives to.
    """

    slug = "alert-dispatch-unavailable"
    title = "Alert dispatch unavailable"


class _Authorised:
    """Shared plumbing for the two adapters that call a SARANA service."""

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

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
        await self._credentials.aclose()

    async def _headers(self, failure: type[UpstreamUnavailable], what: str) -> dict[str, str]:
        try:
            return await self._credentials.authorization()
        except CredentialUnavailable as error:
            raise failure(
                f"No service credential is available to {what}. Run `make service-clients` "
                "and set SARANA_AGENT_CLIENT_SECRET."
            ) from error

    def _check(
        self, response: httpx.Response, failure: type[UpstreamUnavailable], what: str
    ) -> None:
        if response.status_code == 401:
            # The credential was rotated or revoked under us. Drop the cached token so the
            # next attempt fetches a fresh one rather than re-presenting a refused one
            # forever, and raise rather than treating it as an empty answer.
            self._credentials.invalidate()
            _log.error(
                "warning_adapter_unauthorised",
                what=what,
                hint="the agent-svc credential was rotated, revoked, or lacks the scope",
            )
            raise failure(f"the upstream refused this service's credential for {what}.")
        if response.status_code >= 400:
            _log.warning("warning_adapter_failed", what=what, status=response.status_code)
            raise failure(f"the upstream returned {response.status_code} for {what}.")


class AlertingCatalogue(_Authorised):
    """The published template catalogue, from alerting-svc."""

    async def published(self, *, hazard_type: str | None = None) -> list[AlertTemplate]:
        headers = await self._headers(CatalogueUnavailable, "read the alert template catalogue")
        params: dict[str, Any] = {"status": "PUBLISHED", "limit": 500}
        if hazard_type:
            params["hazard"] = hazard_type

        try:
            response = await self._client.get(
                f"{self._base_url}/api/v1/templates", params=params, headers=headers
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise CatalogueUnavailable(
                "alerting-svc is unreachable, so which templates are published is unknown. "
                "An empty catalogue would look like 'no template fits'."
            ) from error

        self._check(response, CatalogueUnavailable, "the template catalogue")

        rows = response.json()
        templates = [
            AlertTemplate(
                id=str(row["id"]),
                code=str(row["code"]),
                hazard_type=str(row["hazard_type"]),
                severity=str(row["severity"]),
                urgency=str(row["urgency"]),
                certainty=str(row["certainty"]),
                body=dict(row["body"]),
            )
            for row in rows
        ]
        _log.info(
            "warning_catalogue_loaded",
            hazard_type=hazard_type,
            published=len(templates),
            codes=sorted(template.code for template in templates),
        )
        return templates


class CoreApiTargets(_Authorised):
    """Households and division coverage, from core-api."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Division exposure changes when a survey is redone, which is a matter of years.
        # Re-fetching it per alert during an event is a self-inflicted load spike on the
        # service everything else depends on.
        self._reach: dict[str, DivisionReach] = {}

    async def targets_in(self, gn_division_codes: tuple[str, ...]) -> list[WarningTarget]:
        """Every household in these divisions, reachable or not."""
        if not gn_division_codes:
            return []

        headers = await self._headers(TargetsUnavailable, "read household contacts")
        found: list[WarningTarget] = []
        offset = 0

        for _ in range(MAX_PAGES):
            body = await self._contacts_page(list(gn_division_codes), headers, offset)
            found.extend(
                WarningTarget(
                    household_id=str(row["household_id"]),
                    gn_division_code=str(row["gn_division_code"]),
                    target_ref_hash=row.get("recipient_ref_hash"),
                    preferred_language=row.get("preferred_language"),
                )
                for row in body["contacts"]
            )
            next_offset = body.get("next_offset")
            if next_offset is None:
                _log.info(
                    "warning_targets_loaded",
                    divisions=len(gn_division_codes),
                    households=len(found),
                    unreachable=sum(1 for target in found if not target.reachable),
                )
                return found
            offset = int(next_offset)

        # A division set this large is a caller bug, not a paging problem. Raising beats
        # returning a truncated list that a fan-out would treat as the whole area.
        raise TargetsUnavailable(
            f"more than {MAX_PAGES} pages of households for {len(gn_division_codes)} "
            "divisions; narrow the area rather than warning part of it"
        )

    async def _contacts_page(
        self, codes: list[str], headers: dict[str, str], offset: int
    ) -> dict[str, Any]:
        try:
            response = await self._client.get(
                f"{self._base_url}/api/v1/admin/households/contacts",
                params={"gn_division_code": codes, "limit": PAGE_SIZE, "offset": offset},
                headers=headers,
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise TargetsUnavailable("core-api is unreachable for household contacts.") from error

        self._check(response, TargetsUnavailable, "a bulk household contact read")
        page: dict[str, Any] = response.json()
        return page

    async def reach(self, gn_division_codes: tuple[str, ...]) -> dict[str, DivisionReach]:
        """Cell coverage and dominant languages, per division.

        Coverage comes from `admin.gn_division.cell_coverage_pct`, which is the same column
        the forecast agent scores against - so the channel mix and the impact class are
        arguing from one number rather than two that disagree.
        """
        wanted = [code for code in gn_division_codes if code not in self._reach]
        if wanted:
            await self._load_reach(tuple(wanted))
        return {
            code: self._reach.get(code, DivisionReach(gn_division_code=code))
            for code in gn_division_codes
        }

    async def _load_reach(self, codes: tuple[str, ...]) -> None:
        headers = await self._headers(TargetsUnavailable, "read division coverage")
        districts = sorted({code.rsplit("-", 2)[0] for code in codes if "-" in code})

        try:
            response = await self._client.get(
                f"{self._base_url}/api/v1/admin/gn-divisions/exposure",
                params={"districts": ",".join(districts), "limit": EXPOSURE_LIMIT},
                headers=headers,
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise TargetsUnavailable("core-api is unreachable for division coverage.") from error

        self._check(response, TargetsUnavailable, "division exposure")

        for row in response.json():
            code = str(row["code"])
            self._reach[code] = DivisionReach(
                gn_division_code=code,
                cell_coverage_pct=_as_float(row.get("cell_coverage_pct")),
                dominant_languages=_dominant_languages(row),
            )


class AlertingDispatcher(_Authorised):
    """Drafting and dispatching an alert, through alerting-svc.

    Two calls: a draft that returns an alert id, and a dispatch over that id. Deliberately
    not one - the draft is what carries the free-text flag into alerting-svc's own
    `requires_human_signoff`, which is the third of the three independent layers over the
    human gate, and collapsing them would remove it.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # The alert id alerting-svc assigned, keyed by the CAP identifier the agent
        # generated. Receipts are read by alert id and the graph only knows the CAP one.
        self._alert_ids: dict[str, str] = {}

    async def dispatch(self, order: DispatchOrder) -> list[ChannelOutcome]:
        """Draft, then send. Never raises for one channel's failure."""
        headers = await self._headers(DispatchUnavailable, "dispatch an alert")

        draft = await self._draft(order, headers)
        alert_id = str(draft["id"])
        self._alert_ids[draft.get("cap_identifier", alert_id)] = alert_id

        if draft.get("requires_human_signoff") and not order.free_text:
            # alerting-svc decided this needs a person and the agent did not. Not a
            # disagreement to paper over: something about the rendered text differs between
            # the two, and dispatching anyway would route around a gate.
            _log.error(
                "warning_dispatch_signoff_disagreement",
                alert_id=alert_id,
                impact="alerting-svc marked this alert as needing sign-off and the agent "
                "did not; nothing was sent",
            )
            return [
                ChannelOutcome(channel=channel, error="awaiting sign-off")
                for channel in order.channels
            ]

        try:
            response = await self._client.post(
                f"{self._base_url}/api/v1/alerts/{alert_id}/dispatch",
                json={"dry_run": False},
                headers=headers,
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise DispatchUnavailable(
                "alerting-svc is unreachable. Nothing was sent, and this is not recorded "
                "as a dispatch whose channels happened to fail."
            ) from error

        self._check(response, DispatchUnavailable, "an alert dispatch")

        receipts = await self.receipts(alert_key=draft.get("cap_identifier", alert_id))
        grouped: dict[str, list[Receipt]] = {}
        for receipt in receipts:
            grouped.setdefault(receipt.channel, []).append(receipt)

        return [
            ChannelOutcome(channel=channel, receipts=grouped.get(channel, []))
            for channel in order.channels
        ]

    async def _draft(self, order: DispatchOrder, headers: dict[str, str]) -> dict[str, Any]:
        payload = {
            "template_code": order.template_code,
            "hazard_event_id": order.hazard_event_id,
            "parameters": order.parameters,
            "gn_division_ids": list(order.gn_division_ids),
            "gn_division_codes": list(order.gn_division_codes),
            "effective_at": order.effective_at.isoformat(),
            "expires_at": order.expires_at.isoformat(),
        }
        if order.free_text:
            payload["free_text"] = order.free_text

        try:
            response = await self._client.post(
                f"{self._base_url}/api/v1/alerts", json=payload, headers=headers
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise DispatchUnavailable("alerting-svc is unreachable to draft an alert.") from error

        self._check(response, DispatchUnavailable, "an alert draft")
        drafted: dict[str, Any] = response.json()
        return drafted

    async def receipts(self, *, alert_key: str) -> list[Receipt]:
        """Per-target receipts as they stand, including anything a DLR has upgraded.

        Returns an empty list for an alert this adapter never drafted, rather than raising.
        A gap report over no receipts is a gap report saying nothing is confirmed, which is
        the truthful answer when nothing has been sent.
        """
        alert_id = self._alert_ids.get(alert_key)
        if alert_id is None:
            return []

        headers = await self._headers(DispatchUnavailable, "read delivery receipts")
        try:
            response = await self._client.get(
                f"{self._base_url}/api/v1/alerts/{alert_id}/delivery", headers=headers
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise DispatchUnavailable("alerting-svc is unreachable for delivery.") from error

        self._check(response, DispatchUnavailable, "a delivery read")

        # `/delivery` aggregates by channel and status rather than listing targets, so the
        # per-target keys are not recoverable from it. The receipts are expanded to the
        # counts the endpoint reports, with a synthetic key per message: the gap arithmetic
        # needs one record per outcome, and the identity of each target is already known to
        # the agent from the directory.
        body = response.json()
        expanded: list[Receipt] = []
        for channel, statuses in body.get("by_channel", {}).items():
            for status, count in statuses.items():
                expanded.extend(
                    Receipt(
                        target_key=f"{channel}:{status}:{index}",
                        channel=channel,
                        language="",
                        status=status,
                    )
                    for index in range(int(count))
                )
        return expanded


class SqlForecasts:
    """The impact forecast in force for a hazard event, from agent-svc's own schema."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def current(self, *, hazard_event_id: str) -> list[ForecastedDivision]:
        """The newest generation's rows, and only those.

        The newest `generated_at` for this hazard event decides the generation, and every
        row from it is returned. Mixing generations would let a division that has since
        been downgraded keep an old class, and the alert would go out against whichever
        row the sort happened to put first.
        """
        async with self._factory() as session:
            newest = await session.scalar(
                select(ImpactForecast.generated_at)
                .where(ImpactForecast.hazard_event_id == hazard_event_id)
                .order_by(ImpactForecast.generated_at.desc())
                .limit(1)
            )
            if newest is None:
                _log.info("warning_no_forecast_rows", hazard_event_id=hazard_event_id)
                return []

            rows = (
                await session.execute(
                    select(ImpactForecast).where(
                        ImpactForecast.hazard_event_id == hazard_event_id,
                        ImpactForecast.generated_at == newest,
                    )
                )
            ).scalars()

            divisions = [
                ForecastedDivision(
                    gn_division_id=str(row.gn_division_id),
                    gn_division_code=str(row.gn_division_code),
                    impact_class=int(row.impact_class),
                    confidence=float(row.confidence or 0.0),
                    lead_time_hours=int(row.lead_time_hours or 0),
                    households=int(row.expected_households_affected or 0),
                    names=dict((row.drivers or {}).get("_narrative", {}) or {}),
                )
                for row in rows
            ]

        _log.info(
            "warning_forecast_loaded",
            hazard_event_id=hazard_event_id,
            generated_at=newest.isoformat(),
            divisions=len(divisions),
        )
        return divisions


class NullHistory:
    """No alert history, so nothing is ever suppressed for fatigue.

    For a deployment where the history table has not been wired. It says so on every call,
    because the failure mode - the same watch-level message every fifteen minutes for three
    days - looks like the platform working hard rather than the platform being broken.
    """

    async def recent(self, *, hazard_event_id: str, since: Any) -> list[PriorAlert]:
        _log.warning(
            "warning_alert_history_not_configured",
            hazard_event_id=hazard_event_id,
            impact="no alert is suppressed for fatigue; a household can receive the same "
            "watch-level message on every forecast generation",
        )
        return []


def _as_float(value: Any) -> float | None:
    """Numeric columns come back as strings over JSON. None stays None.

    A missing coverage figure is not zero: an unsurveyed division and one with no signal
    look identical afterwards and mean opposite things for which channels are chosen.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dominant_languages(row: dict[str, Any]) -> tuple[str, ...]:
    """The languages a division is treated as reading, from reference data.

    Read from an explicit share per language where the row carries one. A division with no
    language data returns an empty tuple, and the caller falls back to the platform default
    order - never to an inference from anybody's name.
    """
    shares = row.get("language_pct") or {}
    if not isinstance(shares, dict):
        return ()
    ranked = sorted(
        (
            (code, float(share))
            for code, share in shares.items()
            if _as_float(share) is not None and float(share) >= DOMINANT_LANGUAGE_PCT
        ),
        key=lambda pair: -pair[1],
    )
    return tuple(code for code, _ in ranked)
