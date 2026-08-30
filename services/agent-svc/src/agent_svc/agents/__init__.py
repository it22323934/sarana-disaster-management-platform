"""The agents themselves. Each one is a `StateGraph` over the shared runtime.

Every agent has a documented degraded path that produces a usable, clearly-labelled
deterministic result with no model call at all. Write that path first: the platform has to
work during a blackout at the model provider, and an agent whose degraded path was an
afterthought does not have one.
"""
