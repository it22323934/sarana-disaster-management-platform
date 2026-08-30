"""Typed failures, and what the runtime does about each one.

The rule this file exists to enforce: **a node that fails does not fail the graph.** It
routes to human review with the failure attached. A graph that dies takes its checkpoint
with it and leaves a citizen's report in limbo; a graph that pauses can be picked up by a
person.

Three kinds of failure, and they are handled differently on purpose:

  **Transient** — a 429, a 5xx, a timeout. Retried with backoff, then degraded.
  **Degraded** — the model is unreachable or over budget. The agent runs its deterministic
  path and labels the output as such. Never silently: a rule-based triage score presented
  as a model's is a lie about how the decision was made.
  **Terminal** — a malformed structured output, a tool that refused, a guard that failed.
  No retry helps. Routes to review.

`BudgetExceeded` is the odd one out and deserves its own note. Cost must not be able to
page somebody at 3 a.m. during a cyclone, so exceeding the daily cap drops every tier to
`VOLUME` and then to the degraded paths. It is an alert, not an outage.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from sarana_shared.errors import SaranaError


class FailureKind(StrEnum):
    """What kind of failure this is, and therefore what to do about it."""

    TRANSIENT = "TRANSIENT"
    DEGRADED = "DEGRADED"
    TERMINAL = "TERMINAL"

    @property
    def retryable(self) -> bool:
        return self is FailureKind.TRANSIENT


class AgentError(SaranaError):
    """Base of every runtime failure. 503, so an uncaught one degrades rather than 500s."""

    slug = "agent-failed"
    title = "Agent run failed"
    status = 503
    kind: FailureKind = FailureKind.TERMINAL


class ModelUnavailable(AgentError):
    """The model provider could not be reached, or refused, after retries.

    Transient by kind, which is what routes the agent to its degraded path rather than to
    a dead end. The platform must produce an answer during a provider outage.
    """

    slug = "model-unavailable"
    title = "Model provider unavailable"
    kind = FailureKind.TRANSIENT


class BudgetExceeded(AgentError):
    """A token, latency or spend budget was exceeded.

    Not an error the caller did anything about. It is the runtime refusing to spend more,
    and the agent falls back to its deterministic path with the output labelled degraded.
    """

    slug = "agent-budget-exceeded"
    title = "Agent budget exceeded"
    kind = FailureKind.DEGRADED


class StructuredOutputInvalid(AgentError):
    """The model returned something the output schema will not accept.

    Terminal: retrying a model that has just produced malformed JSON against a strict
    schema usually produces malformed JSON again, and the retry budget is better spent
    elsewhere. Routes to review with the raw output attached.
    """

    slug = "structured-output-invalid"
    title = "Model output did not match its schema"
    kind = FailureKind.TERMINAL


class GuardFailed(AgentError):
    """A declarative precondition did not hold.

    Named rather than raised into the void, so the graph routes somewhere a person can
    look at rather than stopping with a stack trace nobody reads.
    """

    slug = "agent-guard-failed"
    title = "Agent precondition failed"
    kind = FailureKind.TERMINAL


class HumanGateMissing(AgentError):
    """A tool requiring human approval was called without one.

    409 rather than 503: this is a refusal, not an outage, and the caller needs to know
    the difference. It is the third of three independent layers over the same property -
    the API gate, the database trigger, and this - because a machine releasing money or
    committing a dispatch is the failure the whole platform's credibility rests on.
    """

    slug = "human-gate-required"
    title = "Human approval required"
    status = 409
    kind = FailureKind.TERMINAL


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How many times, and how long to wait.

    Jittered because a national fan-out means many agents hitting the same rate limit in
    the same second; retrying in lockstep turns one 429 into a thundering herd.
    """

    attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    jitter: float = 0.25

    def delay_for(self, attempt: int, *, retry_after: float | None = None) -> float:
        """How long to wait before attempt number `attempt`, counting from 1.

        `Retry-After` from the provider wins over the computed backoff whenever it is
        longer. Ignoring it is how a client gets rate-limited harder.
        """
        computed: float = min(
            self.base_delay_seconds * (2 ** (attempt - 1)), self.max_delay_seconds
        )
        if retry_after is not None:
            computed = max(computed, retry_after)
        return computed


DEFAULT_RETRY: Final = RetryPolicy()

# HTTP statuses worth retrying. 408 and 409 are absent: a timeout the provider reports
# rather than one we observed, and a conflict, are not fixed by asking again immediately.
RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})


def classify(error: BaseException) -> FailureKind:
    """What kind of failure this is.

    Anything the runtime does not recognise is TERMINAL. Guessing TRANSIENT on an unknown
    error means retrying something that will never succeed, three times, while a citizen's
    report waits.
    """
    if isinstance(error, AgentError):
        return error.kind
    if isinstance(error, TimeoutError | ConnectionError):
        return FailureKind.TRANSIENT
    return FailureKind.TERMINAL
