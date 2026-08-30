"""The agents themselves. Each one is a `StateGraph` over the shared runtime.

Every agent has a documented degraded path that produces a usable, clearly-labelled
deterministic result with no model call at all. Write that path first: the platform has to
work during a blackout at the model provider, and an agent whose degraded path was an
afterthought does not have one.
"""

from typing import Final

from agent_svc.agents.noop import SPEC as NOOP_SPEC
from agent_svc.runtime.registry import AgentSpec

# Every agent this service hosts. One list, so the service, the eval harness and the
# trigger table all discover agents the same way. An agent added to `agents/` but not to
# this tuple is one that exists in the tree and nowhere else - which is a failure mode with
# no symptom at all until somebody asks why it never runs.
SPECS: Final[tuple[AgentSpec, ...]] = (NOOP_SPEC,)


def spec_named(name: str) -> AgentSpec:
    """One agent's spec by name.

    Raises:
        KeyError: naming the agents that do exist, because the caller is usually somebody
            who has just mistyped one on a command line.
    """
    for spec in SPECS:
        if spec.name == name:
            return spec
    known = ", ".join(sorted(spec.name for spec in SPECS))
    raise KeyError(f"No agent named {name!r}. Known: {known}")


__all__ = ["SPECS", "spec_named"]
