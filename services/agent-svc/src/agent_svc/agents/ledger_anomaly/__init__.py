"""The Aid Ledger & Anomaly agent.

Aggregates damage assessments into the sector figures that make a recovery legible, and
surfaces statistical patterns that warrant human audit - without ever accusing anyone.

**Read ADR-009 before changing anything in this package.** This is the agent with the
highest potential to do harm, and the harm is not technical. A flag against a GN officer can
end a career on a statistical artifact, and the divisions that were genuinely hit hardest
will legitimately look like outliers: their assessments *should* be higher, more numerous
and faster. That is the damage speaking, not the officer.

Four boundaries, each enforced by structure rather than by discipline:

- **it does not calculate entitlements** - that is deterministic code in ledger-svc, and
  there is no port here through which a value could be computed;
- **it never releases money** - there is no disbursement port in this package;
- **a flag is not a finding** - `redaction` checks every string at any depth against a
  shipped deny-list and a set of conclusive grammatical shapes;
- **no output names an individual, and officer identity is not a feature** - `Assessment`
  carries no assessor, approver or user field, so no detector can group by person even by
  accident, and the proxy is closed too: the unit is the GN division per day.

`normalisation` is what makes the whole thing defensible. Every detector compares a division
against its own impact forecast, never against its peers.
"""

from agent_svc.agents.ledger_anomaly.graph import SPEC, build

__all__ = ["SPEC", "build"]
