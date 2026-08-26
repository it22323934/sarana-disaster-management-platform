"""ProblemDetail, the SaranaError hierarchy, and FastAPI exception handlers.

One error shape everywhere — RFC 9457 Problem Details — per
docs/build-prompts/02-conventions.md. `detail` is safe to show a user; anything sensitive
goes to logs keyed by correlation_id. Never a bare string, never a leaked stack trace.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sarana_shared.telemetry.logging import get_logger

logger = get_logger()


class FieldError(BaseModel):
    field: str
    code: str


class ProblemDetail(BaseModel):
    type: str  # "https://sarana.lk/errors/{slug}"
    title: str
    status: int
    detail: str
    instance: str | None = None
    correlation_id: UUID | None = None
    errors: list[FieldError] = []


class SaranaError(Exception):
    """Base for every domain error a service raises. Subclass per failure mode, don't
    reuse one generic exception with a message — the `type` slug is part of the API
    contract, not an implementation detail."""

    status: int = 500
    type_slug: str = "internal-error"
    title: str = "Internal error"

    def __init__(
        self,
        detail: str,
        *,
        instance: str | None = None,
        errors: list[FieldError] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.instance = instance
        self.errors = errors or []

    def to_problem_detail(self, *, correlation_id: UUID | None = None) -> ProblemDetail:
        return ProblemDetail(
            type=f"https://sarana.lk/errors/{self.type_slug}",
            title=self.title,
            status=self.status,
            detail=self.detail,
            instance=self.instance,
            correlation_id=correlation_id,
            errors=self.errors,
        )


class ValidationFailed(SaranaError):
    status = 422
    type_slug = "validation-failed"
    title = "Validation failed"


class NotFound(SaranaError):
    status = 404
    type_slug = "not-found"
    title = "Not found"


class Forbidden(SaranaError):
    status = 403
    type_slug = "forbidden"
    title = "Forbidden"


class Unauthorized(SaranaError):
    status = 401
    type_slug = "unauthorized"
    title = "Unauthorized"


class Conflict(SaranaError):
    status = 409
    type_slug = "conflict"
    title = "Conflict"


class RateLimited(SaranaError):
    status = 429
    type_slug = "rate-limited"
    title = "Rate limited"


def _correlation_id_from(request: Request) -> UUID | None:
    raw = request.headers.get("X-Correlation-Id") or request.state.__dict__.get("correlation_id")
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def register_exception_handlers(app: FastAPI) -> None:
    """Call once per service, in main.py's app factory."""

    @app.exception_handler(SaranaError)
    async def _handle_sarana_error(request: Request, exc: SaranaError) -> JSONResponse:
        correlation_id = _correlation_id_from(request)
        problem = exc.to_problem_detail(correlation_id=correlation_id)
        if exc.status >= 500:
            logger.error(
                "unhandled_domain_error", type=exc.type_slug, correlation_id=str(correlation_id)
            )
        return JSONResponse(
            status_code=exc.status,
            content=problem.model_dump(mode="json", exclude_none=True),
            media_type="application/problem+json",
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = _correlation_id_from(request)
        # Never leak the exception message or a stack trace to the client — log it
        # keyed by correlation_id instead, where an operator can look it up.
        logger.error(
            "unhandled_exception",
            exception_type=type(exc).__name__,
            correlation_id=str(correlation_id),
        )
        problem = ProblemDetail(
            type="https://sarana.lk/errors/internal-error",
            title="Internal error",
            status=500,
            detail="An unexpected error occurred. Reference the correlation id when reporting this.",
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=500,
            content=problem.model_dump(mode="json", exclude_none=True),
            media_type="application/problem+json",
        )


__all__ = [
    "Conflict",
    "FieldError",
    "Forbidden",
    "NotFound",
    "ProblemDetail",
    "RateLimited",
    "SaranaError",
    "Unauthorized",
    "ValidationFailed",
    "register_exception_handlers",
]
