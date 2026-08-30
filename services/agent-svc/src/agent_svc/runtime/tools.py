"""The tool registry, and the refusal that is the point of it.

Every tool declares whether it has side effects, and whether those side effects need a
human to have said yes.

```python
@tool(side_effect=False)
async def get_gn_division(gn_division_id: UUID) -> GNDivision: ...

@tool(side_effect=True, requires_human_gate=True)
async def release_dispatch(plan_id: UUID) -> DispatchResult: ...
```

**The runtime refuses to execute a `requires_human_gate=True` tool unless the graph state
carries a verified human approval for that exact subject id.** Not "an approval". Not "an
approval for something". That subject.

This is the third of three independent layers over the same property:

  1. the API gate — `Scope.DISBURSEMENT_RELEASE` and `Scope.DISPATCH_COMMIT` are refused to
     every machine principal, at the token,
  2. the database — `aid.disbursement` is append-only and `released_by` is NOT NULL,
  3. this.

Three layers for one property looks like paranoia until you consider what it protects: an
agent, running unattended at 3 a.m., moving public money or sending a crew somewhere,
with nobody accountable for the decision. The whole platform's credibility rests on that
being impossible, and one layer is one bug away from not being impossible.

**A subject mismatch is the attack this actually catches.** An approval for incident A
being carried into a tool call about incident B is the realistic failure — a state key
copied between runs, a resume against the wrong thread, a supervisor batching decisions.
Comparing the ids is what makes an approval specific rather than ambient.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final

import structlog

from agent_svc.runtime.errors import HumanGateMissing
from agent_svc.runtime.state import AgentState

_log = structlog.get_logger(__name__)

# What a human decision must contain to count. A dict missing any of these is not a
# decision - it is something that was put in the state and looks like one.
REQUIRED_DECISION_FIELDS: Final[frozenset[str]] = frozenset(
    {"subject_id", "decided_by", "decided_at", "approved"}
)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One tool, and what it is allowed to do.

    `side_effect` and `requires_human_gate` are separate because they are different
    questions. Writing an audit entry has a side effect and needs no human; releasing money
    has one and needs a named person. A tool that needs a gate but is not marked
    side-effecting is a contradiction and is refused at registration.
    """

    name: str
    fn: Callable[..., Awaitable[Any]]
    side_effect: bool
    requires_human_gate: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if self.requires_human_gate and not self.side_effect:
            raise ValueError(
                f"{self.name}: a tool needing human approval must be marked "
                "side_effect=True. A gate over something that changes nothing is a gate "
                "somebody will remove as pointless."
            )


@dataclass
class ToolRegistry:
    """Every tool an agent may call, and the gate in front of the dangerous ones."""

    tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self.tools:
            raise ValueError(
                f"{spec.name} is registered twice. Two tools with one name means the "
                "graph calls whichever was registered last, which is not a decision "
                "anybody made."
            )
        self.tools[spec.name] = spec
        return spec

    def tool(
        self,
        *,
        side_effect: bool,
        requires_human_gate: bool = False,
        name: str | None = None,
    ) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
        """Declare a tool.

        `side_effect` has no default. A tool author has to state it, because the one that
        gets it wrong by omission is the one that sends an SMS during a replay.
        """

        def decorate(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            self.register(
                ToolSpec(
                    name=name or fn.__name__,
                    fn=fn,
                    side_effect=side_effect,
                    requires_human_gate=requires_human_gate,
                    description=(fn.__doc__ or "").strip().split("\n")[0],
                )
            )
            return fn

        return decorate

    async def invoke(self, name: str, state: AgentState, /, **kwargs: Any) -> Any:
        """Call a tool, refusing a gated one without a matching human approval.

        Raises:
            KeyError: for a tool that is not registered. Not a soft failure: a graph
                calling a tool that does not exist is a bug, not a degraded condition.
            HumanGateMissing: for a gated tool with no approval, an approval for a
                different subject, or a refusal.
        """
        spec = self.tools[name]

        if spec.requires_human_gate:
            assert_human_gate(spec.name, state)

        return await spec.fn(**kwargs)

    def gated(self) -> list[str]:
        """Every tool behind a human gate.

        Exposed so a test can assert the list, and so a security review has one place to
        read rather than a grep.
        """
        return sorted(name for name, spec in self.tools.items() if spec.requires_human_gate)

    def side_effecting(self) -> list[str]:
        """Every tool that changes something outside the graph."""
        return sorted(name for name, spec in self.tools.items() if spec.side_effect)


def assert_human_gate(tool_name: str, state: AgentState) -> dict[str, Any]:
    """Refuse unless a person approved *this* subject.

    Four ways to fail, and they are checked separately so the message says which:

      no decision at all — the agent reached a gated tool without pausing for one;
      a malformed decision — something was written into the state that is not a decision;
      a decision about a different subject — the realistic failure, and the reason this
      compares ids rather than checking a boolean;
      a refusal — a person said no, which is a decision and must not be treated as absence.

    Returns the decision so a caller can record who approved what.
    """
    decision = state.get("human_decision")
    subject_id = str(state.get("subject_id", ""))

    if not decision:
        raise HumanGateMissing(
            f"{tool_name} needs a human decision and this run has none. The graph must "
            "interrupt for approval before calling it."
        )

    missing = REQUIRED_DECISION_FIELDS - set(decision)
    if missing:
        raise HumanGateMissing(
            f"{tool_name}: the recorded decision is missing {sorted(missing)}. A decision "
            "that does not name who made it, when, and about what is not one."
        )

    if str(decision["subject_id"]) != subject_id:
        # The one this exists to catch: an approval for incident A carried into a tool
        # call about incident B, by a copied state key or a resume on the wrong thread.
        _log.error(
            "human_gate_subject_mismatch",
            tool=tool_name,
            approved_subject=str(decision["subject_id"]),
            called_for_subject=subject_id,
            impact="an approval for one subject was presented for another; refused",
        )
        raise HumanGateMissing(
            f"{tool_name}: the human decision approves subject "
            f"{decision['subject_id']}, but this run is about {subject_id}. An approval "
            "is for one thing, not for whatever is in front of it."
        )

    if not decision["approved"]:
        raise HumanGateMissing(
            f"{tool_name}: a person reviewed this and said no. A refusal is a decision, "
            "not an absence, and it is not retried."
        )

    _log.info(
        "human_gate_satisfied",
        tool=tool_name,
        subject_id=subject_id,
        decided_by=str(decision["decided_by"]),
    )
    return dict(decision)


# The registry every agent shares. One per process: two registries means a tool registered
# in one is invisible to a graph built against the other, and the failure is an
# AttributeError a long way from the cause.
REGISTRY: Final = ToolRegistry()
tool = REGISTRY.tool
