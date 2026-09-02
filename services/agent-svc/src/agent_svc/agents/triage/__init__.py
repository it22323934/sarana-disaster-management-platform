"""The Triage & Dispatch agent.

Decides what gets rescued first and how responders get there - and then stops, because a
human commits the dispatch.

This is where the two-gate design earns its keep. The agent can be as autonomous as we like
right up to the moment a vehicle moves: it scores, ranks, checks resources, solves routes
and writes a plan entirely on its own, and then pauses indefinitely at zero cost until a
named dispatcher with a second factor verified in the last five minutes releases it.

**Nothing in this package can release a dispatch.** Four independent layers stop it: a
gated tool inside the graph, `Scope.DISPATCH_COMMIT` stripped from every machine principal
at mint time, `dispatch_gate.approve` as the only writer of `signed_off_by`, and a database
trigger that rejects RELEASED without one.

The priority score is a published weighted sum, not a model output, and every term is shown
next to the incident it ranked - a ranking a dispatcher cannot interrogate is one they will
either over-trust or ignore. Routing is OR-Tools, fully deterministic, with a labelled
greedy fallback. The only model call in the agent writes a trilingual sentence explaining a
ranking that has already been computed, so a provider outage changes the prose and nothing
else.
"""

from agent_svc.agents.triage.graph import SPEC, build

__all__ = ["SPEC", "build"]
