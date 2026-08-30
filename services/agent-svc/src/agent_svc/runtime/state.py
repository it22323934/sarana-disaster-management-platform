"""The state every SARANA graph carries, and the output shape every LLM call returns.

Two things live here and both are contracts rather than conveniences.

**`AgentOutput` is what every model call that feeds a decision must return.** Structured
output via `with_structured_output(..., method="json_schema", strict=True)`, never free text
parsed with a regex. `confidence` is used by real gates, so it has to mean something: it is
calibrated against the labelled fixtures and the eval report prints the calibration error.
An uncalibrated confidence used as a gate is worse than no gate — it looks like a safety
property and is not one.

**`AgentState` is what a checkpoint holds.** Two rules about what may go in it:

  *References, not blobs.* An S3 URI for the audio, never base64 audio. A checkpoint row
  stays under 64KB, and a row that does not is a row that makes every resume slow and every
  debugging session miserable.

  *Nothing that identifies a person.* Checkpoints outlive the run, get read during
  debugging, and go into a trace exporter that leaves the country (ADR-011). Ids and
  division codes, never a name, a NIC, a phone number or an exact coordinate.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

# How a run ended, from the outside. `INTERRUPTED` is the interesting one: the graph is
# alive, paused on a human decision, and the ops console's approval inbox is a query for
# exactly this value.
type RunStatus = Literal["RUNNING", "INTERRUPTED", "COMPLETED", "FAILED"]

# How an answer was produced. Carried on every output because a rule-based triage score
# presented as a model's is a lie about how the decision was made - and the person reading
# it decides differently depending on which it was.
type Provenance = Literal["MODEL", "DETERMINISTIC", "HUMAN"]


class AgentOutput(BaseModel):
    """What every LLM call that feeds a downstream decision returns.

    Subclassed per agent with the fields that agent extracts. The four fields here are
    mandatory everywhere, because every one of them is read by something outside the agent:
    the gates read `confidence`, the audit log reads `reasoning`, the review queue reads
    `needs_human_review` and `review_reason`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="How sure the model is. Used by real gates, so it is calibrated "
        "against labelled fixtures and its calibration error is in the eval report.",
    )
    reasoning: str = Field(
        max_length=2000,
        description="Short, for the audit log and the UI. Not a chain of thought - a "
        "sentence an officer can read while deciding whether to agree.",
    )
    needs_human_review: bool
    review_reason: str | None = Field(
        default=None,
        description="Why, in words. A review flag with no reason is a queue item nobody "
        "can triage.",
    )

    provenance: Provenance = Field(
        default="MODEL",
        description="How this was produced. A deterministic fallback says so, always: an "
        "output that hides which path made it cannot be audited.",
    )

    def model_post_init(self, _context: Any) -> None:
        if self.needs_human_review and not (self.review_reason or "").strip():
            raise ValueError(
                "needs_human_review is set with no review_reason. A review queue item "
                "nobody can triage is one that sits there."
            )


class Budgets(TypedDict, total=False):
    """What this run has spent so far. Accumulated across nodes."""

    tokens: int
    cost_usd: float
    model_calls: int
    latency_ms: int


class AgentState(TypedDict, total=False):
    """The state base every SARANA graph extends.

    A `TypedDict` rather than a Pydantic model because LangGraph merges partial updates
    from each node, and a total model would require every node to return every field.

    `total=False` throughout: a node returns only what it changed.
    """

    # Which run this is, and what it is about. `thread_id` follows
    # `{agent}:{subject_type}:{subject_id}` so a resume never has to search for its thread.
    thread_id: str
    agent: str
    subject_type: str
    subject_id: str
    correlation_id: str

    # The chain from the original citizen report. Never broken: it is what lets somebody
    # trace a disbursement back to the SMS that started it.
    causation_id: str | None

    status: RunStatus

    # What the agent concluded. One dict rather than typed per-agent fields, because the
    # state base is shared and each agent's output model is its own.
    output: dict[str, Any]

    # Accumulated, not replaced. `operator.add` on the list so two nodes appending in the
    # same superstep both survive - the default would silently keep one.
    notes: Annotated[list[str], operator.add]

    # Every failure that happened, in order. Kept rather than raised so a run that
    # degraded can explain what it tried first.
    failures: Annotated[list[dict[str, Any]], operator.add]

    budgets: Budgets

    # Set when a node called `interrupt()`. The payload is what the ops console renders in
    # the approval inbox, so it is JSON-serialisable and free of personal data.
    interrupt_payload: dict[str, Any] | None

    # What a human decided, once they did. Written by the resume, read by the gated tool
    # registry - which refuses to run a gated tool unless this names the same subject.
    human_decision: dict[str, Any] | None


def initial_state(
    *,
    agent: str,
    subject_type: str,
    subject_id: str,
    correlation_id: str,
    causation_id: str | None = None,
) -> AgentState:
    """A fresh run's state.

    Every field a node might read is present, so no node has to guard against a key that
    has never been written. Missing-key handling scattered through fifteen nodes is how a
    graph acquires behaviour nobody intended.
    """
    return AgentState(
        thread_id=thread_id_for(agent, subject_type, subject_id),
        agent=agent,
        subject_type=subject_type,
        subject_id=subject_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        status="RUNNING",
        output={},
        notes=[],
        failures=[],
        budgets=Budgets(tokens=0, cost_usd=0.0, model_calls=0, latency_ms=0),
        interrupt_payload=None,
        human_decision=None,
    )


def thread_id_for(agent: str, subject_type: str, subject_id: str) -> str:
    """The thread id for one agent working on one subject.

    Deterministic — `dispatch:incident:018f...` — so a resume never has to search for its
    thread, and so the domain row can store it and the API can resume without a lookup
    table.

    It is also the idempotency key in practice: starting the same agent on the same subject
    twice lands on the same thread, and the second call resumes rather than forking.
    """
    return f"{agent}:{subject_type}:{subject_id}"
