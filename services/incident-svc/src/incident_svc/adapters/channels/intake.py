"""The one command every channel converges on.

Five ways in - app, SMS, USSD, LoRa mesh, and a scanned paper form - and exactly one
`ReportIntake` out. Nothing past this module knows which channel a report arrived on,
except logging and delivery-proof accounting.

That constraint is what keeps a citizen's experience from depending on their phone. A
report typed into the app and the same report shouted into a USSD menu produce the same
record, get the same triage, and land in the same queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sarana_shared.domain.time import utc_now

# The channels the schema allows. Kept as a reference here rather than re-declared: a
# channel the database will not store is not a channel this service can accept.
from incident_svc.repo.base import INTAKE_CHANNELS, LOCATION_SOURCES


class UnsupportedChannel(ValueError):
    """A channel the schema does not know."""


@dataclass(frozen=True, slots=True)
class ReportIntake:
    """One citizen report, however it arrived.

    Deliberately permissive about what is missing. A report with no location, no language
    and no structure is still a report - somebody is in trouble and typed what they could.
    Enrichment happens later; refusing it here would lose it.
    """

    channel: str
    correlation_id: str
    received_at: datetime = field(default_factory=utc_now)

    raw_text: str | None = None
    reported_language: str | None = None

    # Resolved by the caller against core-api, not by the adapter.
    lon: float | None = None
    lat: float | None = None
    location_accuracy_m: int | None = None
    location_source: str | None = None

    # The sender is resolved to a household by HMAC, never by decrypting a number.
    sender_msisdn_hash: str | None = None

    incident_type: str | None = None
    people_at_risk: int | None = None

    media_keys: tuple[str, ...] = ()
    channel_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.channel not in INTAKE_CHANNELS:
            raise UnsupportedChannel(
                f"{self.channel!r} is not a known intake channel; "
                f"expected one of {', '.join(sorted(INTAKE_CHANNELS))}"
            )
        if self.location_source is not None and self.location_source not in LOCATION_SOURCES:
            raise ValueError(
                f"{self.location_source!r} is not a known location source; "
                f"expected one of {', '.join(sorted(LOCATION_SOURCES))}"
            )

    @property
    def has_location(self) -> bool:
        return self.lon is not None and self.lat is not None
