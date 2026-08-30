"""The Forecast & Impact agent.

Turns "150 mm of rain in Kandy district" into "these 6 GN divisions lose road access within
18 hours; 340 of those households contain someone over 70". That translation is the whole
job, and it is the difference between a weather feed and a platform.

**There is no trained model here.** Phase 1 has no historical dataset, so scoring is a
documented rule-based threshold engine over NBRO's published rainfall thresholds and the
static exposure attributes. Every row it writes carries `method="RULE_THRESHOLD"`, the UI
shows it, and the demo says it out loud. The seam for a real model is `scoring.ImpactModel`
and it is the only thing a trained model would have to satisfy.

A model is used in exactly two places, and neither decides anything: reconciling sources
that disagree (bounded below by the most severe source), and writing the trilingual
narrative (discarded whole if it contains a number the drivers do not).
"""

from agent_svc.agents.forecast.graph import SPEC, build

__all__ = ["SPEC", "build"]
