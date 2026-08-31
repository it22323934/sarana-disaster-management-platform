"""The Warning Dissemination agent.

Turns "these six GN divisions reach major impact within eighteen hours" into a trilingual,
CAP-compliant alert on the right channels, and then into an honest statement of who
probably did not get it.

**The model does not write alert text.** Alert text comes from a template a named Sinhala
reviewer and a named Tamil reviewer have each signed (file 09). What this agent does is
select the template, fill typed parameters from structured data, choose the targeting, and
decide the channel mix. That is a meaningful, hard job. Generating warning copy at dispatch
time is not a job this platform is willing to give a model: a hallucinated instruction in an
evacuation order is an unrecoverable harm, and it is unrecoverable precisely because the
people acting on it have the least time to check.

Where a model *is* used, its answer is constrained on the way out rather than in the
prompt: it cannot choose a template less severe than the rules require, it cannot supply a
parameter value that is not already a structured fact, and it can only widen the channel
mix, never narrow it.

If nothing fits, the agent does not improvise. `no_suitable_template` is a review item for
a DMC operator, who either picks a template or authors the alert - and free text goes
through the soft human gate on its way out, enforced in three independent places.
"""

from agent_svc.agents.warning.graph import SPEC, build, subject_for

__all__ = ["SPEC", "build", "subject_for"]
