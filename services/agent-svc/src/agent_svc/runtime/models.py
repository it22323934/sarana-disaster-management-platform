"""Model routing, budgets, and the one file that changes when models move.

**Never hardcode a model string outside this module.** Six agents referencing a model name
directly is six places to edit when a model is deprecated, and the one that gets missed is
found in production.

## The routing rule, and why it is this way round

Everything defaults to `VOLUME` and is upgraded deliberately. Most nodes in this system are
extraction and classification — pulling a hazard type out of an SMS, deciding whether two
reports describe the same collapsed house — not reasoning. Defaulting to a reasoning tier
and downgrading the cheap cases is how a platform ends up with a model bill that has to be
explained to a ministry.

Three things upgrade a call to `STANDARD`, and each is a case where cheap output is
measurably worse:

  **Low confidence.** The node's own previous confidence was under threshold, so the easy
  path already tried and was unsure.
  **Multilingual or code-switched input.** Sinhala and Tamil are low-resource languages
  (ADR-007) and a message that switches between them mid-sentence is the hardest input this
  platform receives — and the most likely to come from somebody in trouble.
  **A life-safety field.** People-at-risk counts, hazard type, whether somebody is trapped.
  Getting these cheap and wrong is not a cost saving.

`ESCALATED` is reserved and stays reserved: supervisor adjudication of conflicting agent
outputs, anomaly rationale, and any case a human has already rejected once. If a fourth
reason appears, it belongs in this docstring before it belongs in the code.

## Budgets are refusals, not warnings

Every call declares a token budget and a latency budget. Exceeding the latency budget falls
back to the deterministic path — a triage score that arrives after the crew has left is
worse than a rule-based one that arrived in time. Exceeding the daily spend cap drops every
tier to `VOLUME` and then to degraded paths, with an alert.

Cost must not be able to page somebody at 3 a.m. during a cyclone.

## Prompt caching

The system prompt and tool definitions are a stable prefix so cache reads apply. Nothing
here interpolates a timestamp, a correlation id or a run id into a system prompt: one
varying character at the front of the prefix costs the cache hit on every call behind it.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

import structlog

from agent_svc.runtime.errors import (
    DEFAULT_RETRY,
    RETRYABLE_STATUSES,
    BudgetExceeded,
    ModelUnavailable,
    RetryPolicy,
)

_log = structlog.get_logger(__name__)


class ModelTier(StrEnum):
    """Which model a node runs on.

    Named for the job rather than the model, so a provider's renaming is one edit here and
    nothing anywhere else.
    """

    VOLUME = "VOLUME"
    STANDARD = "STANDARD"
    ESCALATED = "ESCALATED"


# The model behind each tier. Build file 12 names these; they are configurable per
# deployment (`SARANA_AGENT_MODEL_*`) because a model identifier is a fact about the
# provider's catalogue on a given day, not a fact about this platform.
#
# Verify these against the provider's current catalogue before the first live call. A
# hardcoded identifier that quietly 404s is an outage that looks like a bug in the agent.
DEFAULT_MODELS: Final[dict[ModelTier, str]] = {
    ModelTier.VOLUME: "gpt-5.6-luna",
    ModelTier.STANDARD: "gpt-5.6-terra",
    ModelTier.ESCALATED: "gpt-5.6-sol",
}

# Below this, a node's own answer is not trusted enough to act on and the call is retried
# one tier up. Calibrated against the labelled fixtures in file 28 - an uncalibrated
# threshold is a number that looks like a gate and is not one.
CONFIDENCE_UPGRADE_THRESHOLD: Final = 0.70

# Fields whose extraction is never done cheaply. Getting a people-at-risk count wrong by an
# order of magnitude decides how many vehicles are sent.
LIFE_SAFETY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "people_at_risk",
        "incident_type",
        "severity",
        "trapped",
        "casualties",
        "hazard_type",
        "evacuation_required",
    }
)


@dataclass(frozen=True, slots=True)
class Budget:
    """What one call is allowed to spend.

    Both limits are refusals. A latency budget that only logs is a latency budget that
    gets exceeded during the one event where it mattered.
    """

    tokens: int = 4_000
    latency_ms: int = 20_000

    def __post_init__(self) -> None:
        if self.tokens <= 0 or self.latency_ms <= 0:
            raise ValueError("a budget of zero is a call that cannot happen; omit it instead")


# The default budget for a node that does not declare one. Deliberately modest: a node
# that needs more should say so, and saying so is where somebody notices the cost.
DEFAULT_BUDGET: Final = Budget()


@dataclass(frozen=True, slots=True)
class RoutingContext:
    """What the router knows about this call.

    Everything here is a fact the caller already has. The router does no I/O and makes no
    model call of its own to decide which model to call - that would be the most expensive
    possible way to save money.
    """

    node: str
    prior_confidence: float | None = None
    languages: tuple[str, ...] = ()
    extracting: tuple[str, ...] = ()
    previously_rejected: bool = False
    adjudicating: bool = False

    @property
    def is_multilingual(self) -> bool:
        """Whether the input mixes languages.

        Code-switching is normal in Sri Lanka and it is the hardest input this platform
        receives. It is also disproportionately likely to come from somebody who is not
        writing carefully, which during a cyclone is everybody.
        """
        return len(set(self.languages)) > 1

    @property
    def touches_life_safety(self) -> bool:
        return bool(set(self.extracting) & LIFE_SAFETY_FIELDS)


def route(context: RoutingContext) -> ModelTier:
    """Which tier this call runs on.

    Pure and cheap. The reasons are checked in order of severity so the log line names the
    most important one rather than whichever matched first alphabetically.
    """
    if context.adjudicating or context.previously_rejected:
        return ModelTier.ESCALATED

    if (
        context.touches_life_safety
        or context.is_multilingual
        or (
            context.prior_confidence is not None
            and context.prior_confidence < CONFIDENCE_UPGRADE_THRESHOLD
        )
    ):
        return ModelTier.STANDARD

    return ModelTier.VOLUME


def explain(context: RoutingContext) -> str:
    """Why this call routed where it did, for the audit log and the eval report.

    A routing decision nobody can explain is one nobody can tune. This string goes next to
    the cost figure in the eval report, which is what makes "why is this agent expensive?"
    answerable.
    """
    if context.adjudicating:
        return "adjudicating conflicting agent outputs"
    if context.previously_rejected:
        return "a human rejected this subject before"
    if context.touches_life_safety:
        fields = sorted(set(context.extracting) & LIFE_SAFETY_FIELDS)
        return f"extracting life-safety fields: {', '.join(fields)}"
    if context.is_multilingual:
        return f"code-switched input: {', '.join(sorted(set(context.languages)))}"
    if (
        context.prior_confidence is not None
        and context.prior_confidence < CONFIDENCE_UPGRADE_THRESHOLD
    ):
        return f"prior confidence {context.prior_confidence:.2f} below threshold"
    return "default tier: extraction or classification"


@dataclass
class SpendTracker:
    """The daily cap, and what happens when it is reached.

    Not a hard stop. Reaching the cap drops every tier to `VOLUME`, and reaching it again
    at that tier drops to the degraded paths. The platform keeps working and somebody gets
    an alert; it does not stop warning people because a budget line was hit.
    """

    daily_cap_usd: float
    spent_usd: float = 0.0
    _degraded_since: float | None = field(default=None, init=False)

    @property
    def over_cap(self) -> bool:
        return self.spent_usd >= self.daily_cap_usd

    def record(self, cost_usd: float) -> None:
        self.spent_usd += cost_usd
        if self.over_cap and self._degraded_since is None:
            self._degraded_since = time.monotonic()
            _log.error(
                "agent_spend_cap_reached",
                spent_usd=round(self.spent_usd, 4),
                cap_usd=self.daily_cap_usd,
                impact="every tier drops to VOLUME and then to the deterministic paths; "
                "the platform keeps running and nobody is paged",
            )

    def effective_tier(self, requested: ModelTier) -> ModelTier:
        """The tier this call actually gets."""
        return ModelTier.VOLUME if self.over_cap else requested

    def reset(self) -> None:
        """Start a new day."""
        self.spent_usd = 0.0
        self._degraded_since = None


async def with_retries[T](
    call: Callable[[], Awaitable[T]],
    *,
    budget: Budget = DEFAULT_BUDGET,
    policy: RetryPolicy = DEFAULT_RETRY,
    node: str = "unknown",
) -> T:
    """Run one model call under its budget and retry policy.

    Raises:
        BudgetExceeded: if the latency budget is exhausted. The caller routes to its
            deterministic path - a triage score that arrives after the crew has left is
            worse than a rule-based one that arrived in time.
        ModelUnavailable: after the retries are spent. Transient by kind, so the agent
            degrades rather than dead-ends.
    """
    deadline = time.monotonic() + budget.latency_ms / 1000.0
    last: BaseException | None = None

    for attempt in range(1, policy.attempts + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BudgetExceeded(
                f"{node}: the {budget.latency_ms}ms latency budget was exhausted after "
                f"{attempt - 1} attempts. Falling back to the deterministic path."
            )

        try:
            return await asyncio.wait_for(call(), timeout=remaining)
        except TimeoutError as error:
            last = error
            _log.warning("model_call_timed_out", node=node, attempt=attempt)
        except Exception as error:  # classified below and re-raised, never swallowed
            last = error
            if not _is_retryable(error):
                raise
            _log.warning(
                "model_call_retrying",
                node=node,
                attempt=attempt,
                error=type(error).__name__,
            )

        if attempt < policy.attempts:
            delay = policy.delay_for(attempt, retry_after=_retry_after(last))
            # Jittered: a national fan-out means many agents hitting one rate limit in the
            # same second, and retrying in lockstep turns one 429 into a herd.
            await asyncio.sleep(delay * (1 + random.uniform(0, policy.jitter)))  # noqa: S311

    raise ModelUnavailable(
        f"{node}: the model provider did not answer after {policy.attempts} attempts. "
        "The agent's deterministic path runs instead."
    ) from last


def _is_retryable(error: BaseException) -> bool:
    """Whether asking again might work.

    Reads a status off the exception if the provider's client put one there, and treats a
    connection failure as retryable. Anything else is not: retrying a malformed request
    three times just spends the budget slower.
    """
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    if isinstance(status, int):
        return status in RETRYABLE_STATUSES
    return isinstance(error, ConnectionError | TimeoutError)


def _retry_after(error: BaseException | None) -> float | None:
    """The provider's own `Retry-After`, if it sent one.

    Honoured over the computed backoff whenever it is longer. Ignoring it is how a client
    gets rate-limited harder than it already was.
    """
    if error is None:
        return None
    headers = getattr(getattr(error, "response", None), "headers", None)
    if not headers:
        return None
    try:
        return float(headers.get("retry-after", ""))
    except (TypeError, ValueError):
        return None


def model_for(tier: ModelTier, overrides: dict[ModelTier, str] | None = None) -> str:
    """The model identifier for a tier.

    The only function in the codebase that turns a tier into a model string.
    """
    return (overrides or {}).get(tier) or DEFAULT_MODELS[tier]


def build_client(
    tier: ModelTier,
    *,
    api_key: str | None,
    overrides: dict[ModelTier, str] | None = None,
    **kwargs: Any,
) -> Any:
    """Construct a chat client for one tier.

    Imported lazily so importing this module - which the routing tests and the eval
    harness do - does not require `langchain_openai` or an API key. A platform whose unit
    tests need a model provider is one nobody runs the tests for.
    """
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model_for(tier, overrides), api_key=api_key, **kwargs)
