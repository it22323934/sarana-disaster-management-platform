"""The Incident Intake & Verification agent.

Turns a chaotic flood of raw citizen reports - SMS in three languages, voice notes, LoRa
batches, scanned paper - into clean, structured, geolocated, non-duplicate incidents, with
anything it cannot do confidently routed to a person rather than guessed.

During Cyclone Ditwah, FloodSupport volunteers phoned each request to verify it, handling
more than 300,000 people. **This agent is the replacement for that phone call**, and the bar
is that it has to be at least as trustworthy as a volunteer with a phone. That is a high bar
and it is worth saying plainly, because most of what is in here is a refusal to do something
a volunteer would not have done:

- it never invents a people count - every number quotes the words that justified it, and one
  whose evidence is not in the report is stripped;
- it never invents a coordinate - geocoding is a gazetteer lookup, and an ambiguous landmark
  produces a GN division with no point;
- it never quietly folds one family's emergency into another's - every uncertain duplicate
  decision produces two incidents and a flagged pair;
- it never throws away something that looked odd - plausibility flags, and a flag is not a
  rejection.

The degraded path is real and is the one the tests run: language detection is a Unicode
script test that never needed a model, extraction falls back to a trilingual keyword lexicon
below the review threshold, and dedup falls back to vector similarity with the ambiguous
band flagged rather than merged.
"""

from agent_svc.agents.intake.graph import SPEC, build

__all__ = ["SPEC", "build"]
