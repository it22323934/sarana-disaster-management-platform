"""LoRa mesh batches.

A mesh node collects reports while the cell network is down and forwards them in one
compressed batch when it next reaches a gateway. The batch may be hours old and may
contain reports the platform has already seen from another path.

Two properties follow from that, and both matter more here than on any other channel:

  - **Every entry carries its own timestamp.** The batch's arrival time says when the
    mesh reconnected, not when someone was in trouble. Using the arrival time would date
    every report in a village to the same minute and destroy the ordering.
  - **Entries are independent.** One malformed entry must not lose the rest of the batch.
    That batch may be the only copy of those reports in existence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import structlog

from incident_svc.adapters.channels.intake import ReportIntake

_log = structlog.get_logger(__name__)

CHANNEL: Final = "LORA"

# A mesh node with a full buffer. Larger than this is a malformed or hostile batch, and
# accepting it would let one request occupy the intake path indefinitely.
MAX_BATCH_ENTRIES: Final = 500


class MalformedEntry(ValueError):
    """One entry in a batch could not be read."""


def parse_entry(entry: dict[str, Any], *, correlation_id: str) -> ReportIntake:
    """Turn one mesh entry into a report.

    Raises:
        MalformedEntry: so the caller can drop this entry and keep the batch.
    """
    try:
        observed_raw = entry["observed_at"]
        observed_at = (
            observed_raw
            if isinstance(observed_raw, datetime)
            else datetime.fromisoformat(str(observed_raw).replace("Z", "+00:00"))
        )
    except (KeyError, ValueError) as error:
        raise MalformedEntry(f"entry has no readable observed_at: {error}") from error

    if observed_at.tzinfo is None:
        # A naive timestamp from a mesh node is UTC by convention. Assuming local time
        # would shift every report by hours depending on where the gateway happens to be.
        observed_at = observed_at.replace(tzinfo=UTC)

    lon = entry.get("lon")
    lat = entry.get("lat")

    return ReportIntake(
        channel=CHANNEL,
        correlation_id=correlation_id,
        received_at=observed_at,
        raw_text=(entry.get("text") or None),
        reported_language=entry.get("language"),
        incident_type=entry.get("type"),
        people_at_risk=entry.get("people_at_risk"),
        lon=float(lon) if lon is not None else None,
        lat=float(lat) if lat is not None else None,
        location_source="gps" if lon is not None and lat is not None else None,
        sender_msisdn_hash=entry.get("sender_hash"),
        channel_metadata={
            "node_id": entry.get("node_id"),
            "hops": entry.get("hops"),
            "batch_received_at": entry.get("batch_received_at"),
        },
    )


def parse_batch(
    entries: list[dict[str, Any]], *, correlation_id: str
) -> tuple[list[ReportIntake], list[str]]:
    """Parse a whole batch, returning what was read and what could not be.

    Never raises for content. The rejects come back so the response can say how many were
    dropped - a node silently losing half its buffer would look identical to a quiet night.
    """
    if len(entries) > MAX_BATCH_ENTRIES:
        raise ValueError(
            f"a LoRa batch carries at most {MAX_BATCH_ENTRIES} entries, got {len(entries)}"
        )

    parsed: list[ReportIntake] = []
    rejected: list[str] = []

    for index, entry in enumerate(entries):
        try:
            parsed.append(parse_entry(entry, correlation_id=correlation_id))
        except (MalformedEntry, ValueError, TypeError) as error:
            rejected.append(f"entry {index}: {error}")
            _log.warning("lora_entry_rejected", index=index, error=str(error))

    return parsed, rejected
