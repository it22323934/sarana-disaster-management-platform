"""One error shape, everywhere. RFC 9457 Problem Details."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from sarana_shared.domain.ids import set_correlation_id
from sarana_shared.errors import (
    Forbidden,
    NotFound,
    ProblemDetail,
    SaranaError,
    TranslationIncomplete,
    install_exception_handlers,
)
from sarana_shared.testing.fixtures import problem_of


def test_every_error_carries_a_dereferenceable_type_uri() -> None:
    assert NotFound().type_uri == "https://sarana.lk/errors/not-found"


def test_out_of_scope_is_indistinguishable_from_absent() -> None:
    """Telling a caller a household exists but is outside their area is a disclosure."""
    assert NotFound.status == 404
    assert NotFound.title == "Resource not found"


def test_context_is_logged_and_never_serialised() -> None:
    error = Forbidden("Outside your area.", context={"subject_id": "officer-1"})

    problem = error.to_problem(instance="/api/v1/entitlements/018f")

    assert "officer-1" not in problem.model_dump_json()
    assert error.context["subject_id"] == "officer-1"


def test_translation_incomplete_is_a_422_not_a_500() -> None:
    """A single-language submission is a client error with a fixable cause."""
    assert TranslationIncomplete.status == 422


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    install_exception_handlers(application)

    @application.get("/known")
    async def known() -> None:
        raise Forbidden("This record is outside your assigned administrative area.")

    @application.get("/boom")
    async def boom() -> None:
        raise RuntimeError("SELECT * FROM ledger.disbursement WHERE nic = '912345678V'")

    @application.get("/typed")
    async def typed(count: int) -> dict[str, int]:
        return {"count": count}

    return application


@pytest.fixture
async def client(app: FastAPI):  # type: ignore[no-untyped-def]  # httpx fixture
    set_correlation_id("test-correlation-0000")
    # Starlette sends the 500 response and then re-raises so the server can log it.
    # A real deployment has uvicorn at the top of the stack absorbing that; in-process
    # the exception would otherwise surface here instead of the response under test.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def test_a_known_error_becomes_problem_details(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get("/known")

    body = problem_of(response)
    assert response.status_code == 403
    assert body["type"] == "https://sarana.lk/errors/forbidden"
    assert body["instance"] == "/known"


async def test_an_unexpected_error_leaks_nothing(client) -> None:  # type: ignore[no-untyped-def]
    """Never a stack trace, never SQL, never a NIC - only a correlation ID."""
    response = await client.get("/boom")

    body = problem_of(response)
    assert response.status_code == 500
    assert "SELECT" not in response.text
    assert "912345678V" not in response.text
    assert body["correlation_id"]


async def test_validation_failures_name_their_fields(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get("/typed", params={"count": "not-a-number"})

    body = problem_of(response)
    assert response.status_code == 422
    assert body["errors"][0]["field"] == "count"


async def test_a_routing_miss_is_still_problem_details(client) -> None:  # type: ignore[no-untyped-def]
    response = await client.get("/no-such-route")

    body = problem_of(response)
    assert body["status"] == 404


def test_problem_detail_rejects_a_success_status() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 400"):
        ProblemDetail(
            type="https://sarana.lk/errors/x",
            title="Not an error",
            status=200,
            correlation_id="018f",
        )


def test_the_base_class_defaults_to_a_generic_500() -> None:
    assert SaranaError.status == 500
    assert SaranaError.slug == "internal-error"
