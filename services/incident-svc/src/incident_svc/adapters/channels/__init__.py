"""One module per intake channel, all converging on `ReportIntake`.

Nothing outside this package knows which channel a report arrived on, except logging and
delivery-proof accounting. A citizen's experience must not depend on their phone.
"""

from __future__ import annotations

from incident_svc.adapters.channels.intake import ReportIntake, UnsupportedChannel

__all__ = ["ReportIntake", "UnsupportedChannel"]
