"""Which agents exist, and how the HTTP surface finds one.

A graph is compiled once per process and reused. Compiling per request would rebuild the
whole `StateGraph` on the hot path and — worse — hand each request its own checkpointer
binding, so two calls about the same subject would not see each other's state.

`AgentSpec` carries three things beyond the builder:

**`subject_type`** — what this agent works on. Half of the thread id, and the reason a
resume never has to search: `dispatch:incident:018f…` is derivable from the request.

**`gated`** — whether this agent can reach a tool that needs a human. Declared here rather
than discovered at runtime, so `GET /agents` tells an operator which agents can pause on
them before anybody has to read the graph.

**`degraded_note`** — one sentence on what this agent does when the model provider is
unreachable. Every SARANA agent has a deterministic path; requiring the sentence here is
what stops one shipping without it. Build file 12 is explicit: write the degraded path
first, then the agent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

import structlog

_log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """One agent: what it is called, what it works on, and how it fails."""

    name: str
    subject_type: str
    build: Callable[[Any], Any]
    description: str
    degraded_note: str
    gated: bool = False

    # How to compile this agent for the evaluation harness, when running it for real needs
    # dependencies an eval cannot have. The forecast agent is the case: its graph talks to
    # the Met Department, NBRO and core-api, and a harness that had to stand all three up
    # would be a harness nobody runs before pushing.
    #
    # An agent supplying one is saying "this is the part of me with a confidence worth
    # calibrating". None means the ordinary graph is evaluable as it stands.
    eval_build: Callable[[Any], Any] | None = None

    # Extra markdown for this agent's evaluation report, built from the finished report.
    #
    # Accuracy and calibration do not capture every agent's quality. The anomaly agent is
    # the case that forced this: ADR-009 makes its **false-positive rate per detector** a
    # first-class metric, because a detection rate without one is a number designed to
    # impress rather than inform - any detector reaches 100% detection by flagging
    # everything, and the cost lands on GN officers in the worst-hit divisions.
    #
    # Optional, and the harness prints nothing extra without it.
    eval_sections: Callable[[Any], str] | None = None

    def __post_init__(self) -> None:
        if not self.degraded_note.strip():
            raise ValueError(
                f"{self.name}: every agent must say what it does when the model provider "
                "is unreachable. An agent whose degraded path was an afterthought does "
                "not have one."
            )


@dataclass
class AgentRegistry:
    """Every agent this service hosts, and its compiled graph."""

    specs: dict[str, AgentSpec] = field(default_factory=dict)
    _graphs: dict[str, Any] = field(default_factory=dict, repr=False)

    def register(self, spec: AgentSpec) -> AgentSpec:
        if spec.name in self.specs:
            raise ValueError(f"{spec.name} is registered twice")
        self.specs[spec.name] = spec
        return spec

    def compile_all(self, checkpointer: Any, *, for_eval: bool = False) -> None:
        """Build every graph once, at boot.

        Failing here is right: a graph that cannot compile should stop the service from
        coming up, not 500 on the first citizen report that reaches it.

        `for_eval` uses each spec's `eval_build` where it has one. The harness sets it; the
        service never does, so a mistake in an eval-only graph can never reach a citizen.
        """
        for name, spec in self.specs.items():
            builder = spec.eval_build if for_eval and spec.eval_build else spec.build
            self._graphs[name] = builder(checkpointer)
        _log.info("agent_graphs_compiled", agents=sorted(self.specs), for_eval=for_eval)

    def replace_graph(self, name: str, graph: Any) -> None:
        """Swap in a graph built with live dependencies.

        The forecast agent needs the Met Department, NBRO and core-api to be useful, and
        those are not available where `compile_all` runs - it is called by the eval harness
        and by tests as well as by the service. So the service builds that one again with
        its real ports and puts it here.

        Raises:
            KeyError: for an unregistered agent, because replacing a graph nobody asked for
                would leave the intended agent running its stand-ins with nothing to say so.
        """
        if name not in self.specs:
            raise KeyError(f"{name} is not registered; cannot replace its graph")
        self._graphs[name] = graph

    def graph(self, name: str) -> Any:
        """The compiled graph for one agent.

        Raises:
            KeyError: for an unknown agent. The API turns it into a 404 naming the agents
                that do exist, which is more useful than a bare "not found".
        """
        return self._graphs[name]

    def spec(self, name: str) -> AgentSpec:
        return self.specs[name]

    def names(self) -> list[str]:
        return sorted(self.specs)


# One registry per process. Two would mean an agent registered against one is invisible to
# a graph built against the other, and the failure is a KeyError a long way from the cause.
REGISTRY: Final = AgentRegistry()
