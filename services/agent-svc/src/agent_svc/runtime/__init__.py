"""The shared runtime every SARANA agent runs on.

Model routing, durable checkpointing, typed failures, the reusable nodes, and the tool
registry that refuses a gated tool without a human's approval.

Read `models.py` before writing an agent: the routing rules there are the reason this
platform's model bill is a line item rather than a surprise, and the reason a blackout at
the model provider degrades the platform instead of stopping it.
"""
