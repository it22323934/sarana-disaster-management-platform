"""The Supervisor: the agent that coordinates the other five and owns every human gate.

**This is where the platform's safety story is either real or theatre.**

It is an event-driven router with a durable state machine, a conflict escalation path, and
the sole owner of gate enforcement inside agent-svc. It is *not* an LLM deciding which agent
to call: routing is a deterministic table keyed on event type and subject state, because an
LLM that picks agents is non-deterministic, untestable, and adds nothing to a problem this
simple - and because somebody investigating why a household was never visited needs to read
the rule that should have sent somebody.

Three things carry the design:

**The resume payload is client input.** `gates.verify_approval_record` re-reads the approval
from the database and checks it names this subject, this approver, and a second factor
verified inside the window. A graph that read `decision["approved"]` and committed would
have authenticated a JSON field.

**A sequencing violation refuses.** An incident cannot reach triage before intake verified
and deduplicated it; an entitlement cannot reach disbursement before both approvals exist.
A violated constraint raises, audits, and routes to human review - never "just this once".

**Conflicts escalate, never resolve.** The supervisor pauses the subject, assembles both
positions with their evidence, and puts them in front of a person. A model may propose, its
proposal is labelled as one, and a recommendation that cannot say why the other position
might be right is suppressed.
"""

from agent_svc.agents.supervisor.graph import SPEC, build

__all__ = ["SPEC", "build"]
