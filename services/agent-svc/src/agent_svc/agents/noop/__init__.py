"""The reference agent: the smallest thing that exercises the whole runtime.

Three purposes, and it earns its place on all three.

**It is the definition-of-done target.** `python -m agent_svc.runtime.eval --agent noop`
runs end to end without a model provider, an API key or a network, so the runtime's own
plumbing can be proved before any real agent exists to confuse the result.

**It is the shape files 13-18 copy.** A `StateGraph`, a deterministic path written first, a
node wrapped in `with_confidence`, an interrupt for the human gate, and a spec that says
what happens in a blackout. An agent author starts here rather than from the LangGraph
documentation, which is still full of the deprecated 1.0 patterns.

**It is the smoke test in a deployment.** Running it against a live service proves the
checkpointer is durable, the thread ids are derived correctly and the approval inbox
populates, without touching a citizen's report.

It deliberately makes no model call at all. An agent that needs a provider to prove the
runtime works cannot prove the runtime works when the provider is down.
"""

from agent_svc.agents.noop.graph import SPEC, build

__all__ = ["SPEC", "build"]
