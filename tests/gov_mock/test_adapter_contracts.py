"""The three-way contract: Protocol, MockClient, RealClient.

The stubbed real clients are the written record of what still has to be negotiated with
each agency, and they double as the technical annexe to each data-sharing agreement. That
only holds if they stay accurate, which means two things have to be true and neither is
enforced by the type checker on its own:

  **Every RealClient implements the whole Protocol.** A stub missing a method is a
  negotiation item nobody will remember to raise, and an `AttributeError` at the moment
  somebody switches to the real integration.

  **Every stub names its endpoint and its credential.** "Not implemented" is a mystery;
  "will call `https://cms.ndrsc.gov.lk/api/claims`, needs an authorised submitting-agency
  account, blocked on NDRSC accepting SARANA as a claim origination channel" is a work
  item somebody can act on.

The mock/real symmetry itself is checked by mypy: `build_met_client` is annotated to return
`MetClient`, so both implementations have to satisfy the Protocol or the build fails. What
mypy cannot check is that the stubs refuse *usefully*, which is what this file is for.
"""

from __future__ import annotations

import inspect

import pytest

from sarana_shared.adapters.gov import (
    REAL_CLIENT_CLASSES,
    GovMode,
    build_dmc_client,
    build_met_client,
    build_nbro_client,
    build_ndrsc_client,
    build_payment_client,
    build_registry_client,
    build_telco_client,
    integration_register,
)
from sarana_shared.adapters.gov.base import MockGovClient, RealClientStub
from sarana_shared.adapters.gov.dmc import DmcClient
from sarana_shared.adapters.gov.met import MetClient
from sarana_shared.adapters.gov.nbro import NbroClient
from sarana_shared.adapters.gov.ndrsc import NdrscClient
from sarana_shared.adapters.gov.payment import PaymentClient
from sarana_shared.adapters.gov.registry import RegistryClient
from sarana_shared.adapters.gov.telco import TelcoClient

SYSTEMS = [
    ("met", build_met_client, MetClient),
    ("nbro", build_nbro_client, NbroClient),
    ("dmc", build_dmc_client, DmcClient),
    ("ndrsc", build_ndrsc_client, NdrscClient),
    ("registry", build_registry_client, RegistryClient),
    ("pay", build_payment_client, PaymentClient),
    ("telco", build_telco_client, TelcoClient),
]


def _protocol_methods(protocol: type) -> set[str]:
    """The methods a Protocol requires, excluding `aclose` and dunders."""
    return {
        name
        for name, member in inspect.getmembers(protocol, inspect.isfunction)
        if not name.startswith("_") and name != "aclose"
    }


@pytest.mark.parametrize(
    ("name", "factory", "protocol"), SYSTEMS, ids=[system for system, _, _ in SYSTEMS]
)
def test_both_implementations_satisfy_the_protocol(
    name: str, factory: object, protocol: type
) -> None:
    """Mock and real both answer every method the Protocol declares.

    A service depends on the Protocol, never on a concrete client, so this is what makes
    `GovMode.REAL` a configuration change rather than a rewrite.
    """
    mock = factory(base_url="http://gov-mock:8006")  # type: ignore[operator]
    real = factory(base_url="http://gov-mock:8006", mode=GovMode.REAL)  # type: ignore[operator]

    for method in _protocol_methods(protocol):
        assert callable(getattr(mock, method, None)), f"{name} mock is missing {method}"
        assert callable(getattr(real, method, None)), f"{name} real stub is missing {method}"


@pytest.mark.parametrize(
    ("name", "factory", "protocol"), SYSTEMS, ids=[system for system, _, _ in SYSTEMS]
)
def test_the_factory_returns_the_implementation_it_was_asked_for(
    name: str, factory: object, protocol: type
) -> None:
    """`GovMode.REAL` must never silently fall back to the mock.

    A service configured for a real integration that does not exist yet has to fail at the
    first call with a work item. Falling back would serve synthetic warnings as though
    they were real, which is the worst outcome this whole package exists to prevent.
    """
    assert isinstance(factory(base_url="http://x"), MockGovClient)  # type: ignore[operator]
    assert isinstance(
        factory(base_url="http://x", mode=GovMode.REAL),  # type: ignore[operator]
        RealClientStub,
    )


@pytest.mark.parametrize(
    ("name", "factory", "protocol"), SYSTEMS, ids=[system for system, _, _ in SYSTEMS]
)
async def test_every_real_method_refuses_with_an_actionable_message(
    name: str, factory: object, protocol: type
) -> None:
    """Each stub names the endpoint, the organisation and the credential it needs.

    This is the assertion that keeps the technical annexe honest. A stub that raises a
    bare `NotImplementedError` passes a type check and tells whoever inherits it nothing.
    """
    real = factory(base_url="http://x", mode=GovMode.REAL)  # type: ignore[operator]
    integration = type(real).integration

    for method in sorted(_protocol_methods(protocol)):
        bound = getattr(real, method)
        args, kwargs = _dummy_args(bound)

        with pytest.raises(NotImplementedError) as raised:
            await bound(*args, **kwargs)

        message = str(raised.value)
        assert integration.base_url in message, f"{name}.{method} does not name its endpoint"
        assert integration.organisation in message, f"{name}.{method} does not name the agency"
        assert integration.credential in message, f"{name}.{method} does not name its credential"


def _dummy_args(bound: object) -> tuple[tuple[object, ...], dict[str, object]]:
    """Arguments that satisfy a stub's signature, read off the signature itself.

    Derived rather than tabulated. A hand-written table of arguments per method goes stale
    the first time somebody adds a parameter, and it goes stale *silently*: the test starts
    erroring on a TypeError that looks like a bug in the adapter rather than a gap here.

    The stub refuses before it looks at any argument, so a placeholder is enough.
    """
    signature = inspect.signature(bound)  # type: ignore[arg-type]
    args: list[object] = []
    kwargs: dict[str, object] = {}

    for parameter in signature.parameters.values():
        if parameter.default is not inspect.Parameter.empty:
            continue
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            kwargs[parameter.name] = "placeholder"
        elif parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            args.append("placeholder")

    return tuple(args), kwargs


def test_the_integration_register_covers_every_system() -> None:
    """One `Integration` per stubbed client, and no duplicates.

    `integration_register()` is what somebody prints when asked what SARANA needs from
    which agency. Generated from the same records the stubs raise from, so it is accurate
    by construction rather than by somebody remembering to update a document.
    """
    register = integration_register()

    assert len(register) == len(REAL_CLIENT_CLASSES)
    assert len({entry.system for entry in register}) == len(register)
    assert {entry.system for entry in register} == {name for name, _, _ in SYSTEMS}


def test_every_integration_states_what_is_actually_blocking_it() -> None:
    """No placeholder text in the register.

    A credential field reading "TBD" is worse than an empty one: it looks answered.
    """
    for entry in integration_register():
        assert entry.base_url.startswith("https://"), f"{entry.system} has no real endpoint"
        assert len(entry.credential) > 20, f"{entry.system} does not say what credential it needs"
        assert len(entry.agreement) > 20, f"{entry.system} does not say what is blocking it"
        assert "TBD" not in entry.as_dict().values()
