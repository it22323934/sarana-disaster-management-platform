"""One error shape, everywhere: RFC 9457 Problem Details.

Never return a bare string. Never leak a stack trace or SQL to a client. `detail` is safe
to show a user; anything sensitive goes to the logs keyed by `correlation_id`.
"""

from __future__ import annotations

from typing import Any, Final

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from sarana_shared.domain.ids import ensure_correlation_id

ERROR_TYPE_BASE: Final = "https://sarana.lk/errors"

PROBLEM_CONTENT_TYPE: Final = "application/problem+json"

_log = structlog.get_logger(__name__)


class FieldError(BaseModel):
    """One field-level validation failure inside a ProblemDetail."""

    model_config = ConfigDict(frozen=True)

    field: str
    code: str
    detail: str | None = None


class ProblemDetail(BaseModel):
    """RFC 9457 Problem Details, plus the correlation ID that ties it to the logs."""

    model_config = ConfigDict(frozen=True)

    type: str = Field(description="Stable URI identifying the problem class")
    title: str = Field(description="Short, human-readable summary, constant per class")
    status: int = Field(ge=400, le=599)
    detail: str | None = Field(
        default=None, description="Occurrence-specific explanation. Safe to show a user."
    )
    instance: str | None = Field(default=None, description="URI of the specific occurrence")
    correlation_id: str
    errors: list[FieldError] = Field(default_factory=list)


class SaranaError(Exception):
    """Base of every application error that maps cleanly onto a ProblemDetail.

    Subclasses set slug, title and status. Anything not derived from this class is an
    unexpected failure, reported as a generic 500 with the detail withheld.
    """

    slug: str = "internal-error"
    title: str = "Internal server error"
    status: int = 500

    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: list[FieldError] | None = None,
        instance: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.errors = errors or []
        self.instance = instance
        # Never serialised to the client. Logged alongside the correlation ID so an
        # operator can reconstruct what happened without the citizen seeing internals.
        self.context = context or {}

    @property
    def type_uri(self) -> str:
        """Stable, dereferenceable URI for this problem class."""
        return f"{ERROR_TYPE_BASE}/{self.slug}"

    def to_problem(self, *, instance: str | None = None) -> ProblemDetail:
        """Render as a ProblemDetail bound to the current correlation ID."""
        return ProblemDetail(
            type=self.type_uri,
            title=self.title,
            status=self.status,
            detail=self.detail,
            instance=instance or self.instance,
            correlation_id=ensure_correlation_id(),
            errors=self.errors,
        )


class ValidationFailed(SaranaError):
    """Request body or parameters failed validation."""

    slug = "validation-failed"
    title = "Request validation failed"
    status = 422


class NotFound(SaranaError):
    """The addressed resource does not exist, or is out of the caller scope.

    Deliberately indistinguishable from an out-of-scope resource: telling a caller that
    a household exists but sits outside their division is itself a disclosure.
    """

    slug = "not-found"
    title = "Resource not found"
    status = 404


class Conflict(SaranaError):
    """The request conflicts with the current state of the resource."""

    slug = "conflict"
    title = "Conflicting state"
    status = 409


class Unauthenticated(SaranaError):
    """No credential, or a credential that failed verification."""

    slug = "unauthenticated"
    title = "Authentication required"
    status = 401


class Forbidden(SaranaError):
    """Authenticated, but the token scopes do not cover this action or area."""

    slug = "forbidden"
    title = "Insufficient scope"
    status = 403


class IdempotencyKeyRequired(SaranaError):
    """A POST that creates, moves money or dispatches arrived without a key."""

    slug = "idempotency-key-required"
    title = "Idempotency-Key header required"
    status = 400


class IdempotencyKeyReused(SaranaError):
    """The same key arrived with a different request body inside the replay window."""

    slug = "idempotency-key-reused"
    title = "Idempotency-Key reused with a different payload"
    status = 409


class TranslationIncomplete(SaranaError):
    """A citizen-facing record was submitted in fewer than three languages.

    Non-negotiable #2. The record is not written; it goes to pending_translation.
    """

    slug = "translation-incomplete"
    title = "Citizen-facing text must exist in si, ta and en"
    status = 422


class HumanGateRequired(SaranaError):
    """The action needs a human decision that has not been recorded.

    One of the two mandatory gates: committing a life-safety dispatch action, or
    releasing a financial disbursement. There is no bypass flag.
    """

    slug = "human-gate-required"
    title = "Human approval required"
    status = 409


class UpstreamUnavailable(SaranaError):
    """A dependency, including a government mock, failed or timed out."""

    slug = "upstream-unavailable"
    title = "Upstream service unavailable"
    status = 503


def _problem_response(problem: ProblemDetail) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json", exclude_none=True),
        media_type=PROBLEM_CONTENT_TYPE,
    )


async def sarana_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render a SaranaError as a Problem Details response."""
    if not isinstance(exc, SaranaError):
        return await unhandled_error_handler(request, exc)
    problem = exc.to_problem(instance=request.url.path)
    log = _log.bind(correlation_id=problem.correlation_id, problem_type=problem.type)
    if exc.status >= 500:
        log.error("request_failed", detail=exc.detail, **exc.context)
    else:
        log.info("request_rejected", detail=exc.detail, **exc.context)
    return _problem_response(problem)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert FastAPI validation errors into the one error shape."""
    if not isinstance(exc, RequestValidationError):
        return await unhandled_error_handler(request, exc)
    errors = [
        FieldError(
            field=".".join(str(part) for part in error.get("loc", ())[1:]) or "body",
            code=str(error.get("type", "invalid")),
            detail=str(error.get("msg", "")) or None,
        )
        for error in exc.errors()
    ]
    problem = ValidationFailed(
        detail="One or more fields failed validation.", errors=errors
    ).to_problem(instance=request.url.path)
    _log.info(
        "request_rejected",
        correlation_id=problem.correlation_id,
        problem_type=problem.type,
        field_count=len(errors),
    )
    return _problem_response(problem)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert Starlette HTTPExceptions, including routing misses, into Problems."""
    if not isinstance(exc, StarletteHTTPException):
        return await unhandled_error_handler(request, exc)
    problem = ProblemDetail(
        type=f"{ERROR_TYPE_BASE}/http-{exc.status_code}",
        title=str(exc.detail) if exc.detail else "HTTP error",
        status=exc.status_code,
        detail=str(exc.detail) if exc.detail else None,
        instance=request.url.path,
        correlation_id=ensure_correlation_id(),
    )
    return _problem_response(problem)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last resort. Logs the exception in full, tells the client almost nothing."""
    correlation_id = ensure_correlation_id()
    _log.exception(
        "unhandled_exception",
        correlation_id=correlation_id,
        path=request.url.path,
        exc_type=type(exc).__name__,
    )
    problem = ProblemDetail(
        type=f"{ERROR_TYPE_BASE}/internal-error",
        title="Internal server error",
        status=500,
        detail="An unexpected error occurred. Quote the correlation ID when reporting it.",
        instance=request.url.path,
        correlation_id=correlation_id,
    )
    return _problem_response(problem)


def install_exception_handlers(app: FastAPI) -> None:
    """Register every handler on a FastAPI app. Called by the shared app factory."""
    app.add_exception_handler(SaranaError, sarana_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
