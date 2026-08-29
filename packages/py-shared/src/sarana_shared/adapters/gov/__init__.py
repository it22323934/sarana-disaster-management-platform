"""Adapters for the government and telco systems SARANA integrates with.

Import the Protocol and a factory, never a concrete client:

    from sarana_shared.adapters.gov import GovMode, build_met_client
    from sarana_shared.adapters.gov.met import MetClient

    met: MetClient = build_met_client(base_url=settings.gov_mock_url)

`GovMode.REAL` selects the stubbed real client, which raises `NotImplementedError` naming
the endpoint and the credential it needs. That is deliberate: a service configured for a
real integration that does not exist yet must fail at the first call with a work item,
never fall back to the mock and serve synthetic warnings as though they were real.

`integration_register()` returns what remains to be negotiated with each agency. It is
generated from the same `Integration` records the stubs raise from, so it cannot drift
from the code the way a document would.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

import httpx

from sarana_shared.adapters.gov.base import (
    CONNECT_TIMEOUT,
    MOCK_HEADER,
    MOCK_HEADER_VALUE,
    MOCK_SOURCE_FIELD,
    MOCK_SOURCE_VALUE,
    READ_TIMEOUT,
    GovMalformedResponse,
    GovRecordNotFound,
    GovRefused,
    GovTimeout,
    GovUpstreamError,
    Integration,
    MockGovClient,
    RealClientStub,
    envelope,
    parse_xml,
    require_mock_xml,
)
from sarana_shared.adapters.gov.dmc import DmcClient, DmcMockClient, DmcRealClient
from sarana_shared.adapters.gov.met import MetClient, MetMockClient, MetRealClient
from sarana_shared.adapters.gov.nbro import NbroClient, NbroMockClient, NbroRealClient
from sarana_shared.adapters.gov.ndrsc import NdrscClient, NdrscMockClient, NdrscRealClient
from sarana_shared.adapters.gov.payment import (
    PaymentClient,
    PaymentMockClient,
    PaymentRealClient,
)
from sarana_shared.adapters.gov.registry import (
    RegistryClient,
    RegistryMockClient,
    RegistryRealClient,
)
from sarana_shared.adapters.gov.telco import TelcoClient, TelcoMockClient, TelcoRealClient


class GovMode(StrEnum):
    """Which implementation of an external system to build."""

    MOCK = "mock"
    REAL = "real"


def _mock_or_real[M: MockGovClient, R: RealClientStub](
    mode: GovMode,
    mock_class: type[M],
    real_class: type[R],
    *,
    base_url: str,
    client: httpx.AsyncClient | None,
) -> M | R:
    """Build one client. Shared so every factory below is one line and cannot diverge."""
    if mode is GovMode.REAL:
        return real_class()
    return mock_class(base_url, client=client)


def build_met_client(
    *, base_url: str, mode: GovMode = GovMode.MOCK, client: httpx.AsyncClient | None = None
) -> MetClient:
    """Department of Meteorology."""
    return _mock_or_real(mode, MetMockClient, MetRealClient, base_url=base_url, client=client)


def build_nbro_client(
    *, base_url: str, mode: GovMode = GovMode.MOCK, client: httpx.AsyncClient | None = None
) -> NbroClient:
    """National Building Research Organisation."""
    return _mock_or_real(mode, NbroMockClient, NbroRealClient, base_url=base_url, client=client)


def build_dmc_client(
    *, base_url: str, mode: GovMode = GovMode.MOCK, client: httpx.AsyncClient | None = None
) -> DmcClient:
    """Disaster Management Centre."""
    return _mock_or_real(mode, DmcMockClient, DmcRealClient, base_url=base_url, client=client)


def build_ndrsc_client(
    *, base_url: str, mode: GovMode = GovMode.MOCK, client: httpx.AsyncClient | None = None
) -> NdrscClient:
    """NDRSC Compensation Management System."""
    return _mock_or_real(mode, NdrscMockClient, NdrscRealClient, base_url=base_url, client=client)


def build_registry_client(
    *, base_url: str, mode: GovMode = GovMode.MOCK, client: httpx.AsyncClient | None = None
) -> RegistryClient:
    """GN officer and household registries."""
    return _mock_or_real(
        mode, RegistryMockClient, RegistryRealClient, base_url=base_url, client=client
    )


def build_payment_client(
    *, base_url: str, mode: GovMode = GovMode.MOCK, client: httpx.AsyncClient | None = None
) -> PaymentClient:
    """Bank disbursement rail."""
    return _mock_or_real(
        mode, PaymentMockClient, PaymentRealClient, base_url=base_url, client=client
    )


def build_telco_client(
    *, base_url: str, mode: GovMode = GovMode.MOCK, client: httpx.AsyncClient | None = None
) -> TelcoClient:
    """Telco SMS and USSD gateway."""
    return _mock_or_real(mode, TelcoMockClient, TelcoRealClient, base_url=base_url, client=client)


# Every stubbed real client, in the order the systems appear in build file 11. The tuple
# is what `integration_register()` walks and what a test iterates to assert each stub
# implements the whole Protocol it stands in for.
REAL_CLIENT_CLASSES: Final[tuple[type[RealClientStub], ...]] = (
    MetRealClient,
    NbroRealClient,
    DmcRealClient,
    NdrscRealClient,
    RegistryRealClient,
    PaymentRealClient,
    TelcoRealClient,
)


def integration_register() -> list[Integration]:
    """Everything that still has to be negotiated before a real integration can be built.

    The technical annexe, generated rather than written. Print it when someone asks what
    SARANA needs from which agency; it is accurate by construction because the same
    records are what the stubs raise from.
    """
    return [real_client.integration for real_client in REAL_CLIENT_CLASSES]


__all__ = [
    "CONNECT_TIMEOUT",
    "MOCK_HEADER",
    "MOCK_HEADER_VALUE",
    "MOCK_SOURCE_FIELD",
    "MOCK_SOURCE_VALUE",
    "READ_TIMEOUT",
    "REAL_CLIENT_CLASSES",
    "DmcClient",
    "GovMalformedResponse",
    "GovMode",
    "GovRecordNotFound",
    "GovRefused",
    "GovTimeout",
    "GovUpstreamError",
    "Integration",
    "MetClient",
    "MockGovClient",
    "NbroClient",
    "NdrscClient",
    "PaymentClient",
    "RealClientStub",
    "RegistryClient",
    "TelcoClient",
    "build_dmc_client",
    "build_met_client",
    "build_nbro_client",
    "build_ndrsc_client",
    "build_payment_client",
    "build_registry_client",
    "build_telco_client",
    "envelope",
    "integration_register",
    "parse_xml",
    "require_mock_xml",
]
