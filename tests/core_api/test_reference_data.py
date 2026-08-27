"""The reference catalogue, and the guard against it drifting from the services.

`core-api` serves these taxonomies but does not own their values - each belongs to the
service whose schema constrains it. core-api cannot import those services, so the
canonical copy lives in `sarana_shared` and this suite, which can import everything, is
what keeps the two honest.

Without this, the first symptom of drift is a status code that exists in the database and
not in the dropdown, discovered by an operator during an incident.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from agent_svc.repo.base import HAZARD_TYPES as AGENT_HAZARD_TYPES
from alerting_svc.repo.base import ALERT_STATUSES as ALERTING_ALERT_STATUSES
from alerting_svc.repo.base import HAZARD_TYPES as ALERTING_HAZARD_TYPES
from incident_svc.repo.base import DISPATCH_STATUSES as INCIDENT_DISPATCH_STATUSES
from incident_svc.repo.base import INCIDENT_STATUSES as INCIDENT_STATUSES_OWNED
from incident_svc.repo.base import INTAKE_CHANNELS as INCIDENT_INTAKE_CHANNELS
from ledger_svc.repo.base import DAMAGE_CATEGORIES as LEDGER_DAMAGE_CATEGORIES
from ledger_svc.repo.base import ENTITLEMENT_STATUSES as LEDGER_ENTITLEMENT_STATUSES
from ledger_svc.repo.base import PAYMENT_RAILS as LEDGER_PAYMENT_RAILS
from sarana_shared.domain.taxonomy import (
    ALERT_STATUSES,
    DAMAGE_CATEGORIES,
    DISPATCH_STATUSES,
    ENTITLEMENT_STATUSES,
    HAZARD_TYPES,
    INCIDENT_STATUSES,
    INTAKE_CHANNELS,
    LOCALES,
    PAYMENT_RAILS,
    missing_labels,
    reference_catalogue,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


# --------------------------------------------------------------------------------------
# The catalogue agrees with the services that own each taxonomy
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("shared", "owned", "owner"),
    [
        pytest.param(HAZARD_TYPES, AGENT_HAZARD_TYPES, "agent-svc", id="hazard-types-agent"),
        pytest.param(
            HAZARD_TYPES, ALERTING_HAZARD_TYPES, "alerting-svc", id="hazard-types-alerting"
        ),
        pytest.param(
            INCIDENT_STATUSES, INCIDENT_STATUSES_OWNED, "incident-svc", id="incident-statuses"
        ),
        pytest.param(
            INTAKE_CHANNELS, INCIDENT_INTAKE_CHANNELS, "incident-svc", id="intake-channels"
        ),
        pytest.param(
            DISPATCH_STATUSES,
            INCIDENT_DISPATCH_STATUSES,
            "incident-svc",
            id="dispatch-statuses",
        ),
        pytest.param(
            DAMAGE_CATEGORIES, LEDGER_DAMAGE_CATEGORIES, "ledger-svc", id="damage-categories"
        ),
        pytest.param(
            ENTITLEMENT_STATUSES,
            LEDGER_ENTITLEMENT_STATUSES,
            "ledger-svc",
            id="entitlement-statuses",
        ),
        pytest.param(PAYMENT_RAILS, LEDGER_PAYMENT_RAILS, "ledger-svc", id="payment-rails"),
        pytest.param(ALERT_STATUSES, ALERTING_ALERT_STATUSES, "alerting-svc", id="alert-statuses"),
    ],
)
def test_the_served_taxonomy_matches_the_service_that_owns_it(
    shared: tuple[str, ...], owned: tuple[str, ...], owner: str
) -> None:
    """A value the database accepts and the catalogue omits is invisible to every client."""
    assert shared == owned, (
        f"the shared catalogue has drifted from {owner}. Update "
        "sarana_shared.domain.taxonomy to match, and add labels for any new value."
    )


def test_the_two_copies_of_hazard_types_still_agree_with_each_other() -> None:
    """agent-svc and alerting-svc each declare this list. They must not diverge."""
    assert AGENT_HAZARD_TYPES == ALERTING_HAZARD_TYPES


# --------------------------------------------------------------------------------------
# Every value is labelled in all three languages
# --------------------------------------------------------------------------------------


def test_every_taxonomy_value_has_all_three_locales() -> None:
    """A dropdown in fewer than three languages is an access problem, not a polish one."""
    gaps = missing_labels()

    assert gaps == [], f"missing or blank labels for: {gaps}"


def test_the_catalogue_covers_every_declared_taxonomy() -> None:
    catalogue = reference_catalogue()

    assert set(catalogue) >= {
        "locales",
        "hazard_types",
        "incident_statuses",
        "damage_categories",
        "entitlement_statuses",
    }


def test_locales_are_exactly_the_three_the_platform_serves() -> None:
    assert LOCALES == ("si", "ta", "en")


# --------------------------------------------------------------------------------------
# The endpoint
# --------------------------------------------------------------------------------------


async def test_the_reference_endpoint_is_anonymous(client: AsyncClient) -> None:
    """The sign-in page needs its language picker before there is a token to present."""
    response = await client.get("/api/v1/meta/reference")

    assert response.status_code == 200


async def test_hazard_types_are_at_the_top_level(client: AsyncClient) -> None:
    """The definition of done reads `.hazard_types` directly."""
    response = await client.get("/api/v1/meta/reference")

    body = response.json()
    assert len(body["hazard_types"]) == len(HAZARD_TYPES)
    assert {row["value"] for row in body["hazard_types"]} == set(HAZARD_TYPES)


async def test_every_served_value_carries_its_labels(client: AsyncClient) -> None:
    response = await client.get("/api/v1/meta/reference")

    for taxonomy, rows in response.json().items():
        for row in rows:
            assert set(row["labels"]) == {"si", "ta", "en"}, f"{taxonomy}/{row['value']}"


async def test_the_reference_endpoint_is_cached_and_revalidates(client: AsyncClient) -> None:
    """It changes on a release, not on a request."""
    first = await client.get("/api/v1/meta/reference")

    assert first.headers["Cache-Control"] == "public, max-age=3600"

    second = await client.get(
        "/api/v1/meta/reference", headers={"If-None-Match": first.headers["ETag"]}
    )

    assert second.status_code == 304
