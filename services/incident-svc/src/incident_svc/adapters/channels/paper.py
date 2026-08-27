"""Paper forms, scanned by a GN officer in the Field Companion.

The officer fills a numbered form by hand, then scans its QR code. The QR carries the form
serial and the division; the officer types what the citizen wrote.

This channel exists because it is the one that works with no phone, no signal and no
electricity, which is the situation this platform is supposed to be designed for. It is
recorded as FIELD_OFFICER because that is who submitted it - the provenance of a paper
report is the officer who transcribed it, and an audit trail that said otherwise would be
claiming a citizen used an app they never touched.
"""

from __future__ import annotations

import re
from typing import Final

from incident_svc.adapters.channels.intake import ReportIntake

CHANNEL: Final = "FIELD_OFFICER"

# `SARANA:LK-21-01-001:000431` - division code and a six-digit form serial.
_QR = re.compile(r"^SARANA:(?P<division>LK-\d{2}-\d{2}-\d{3}):(?P<serial>\d{6})$")


class UnreadableForm(ValueError):
    """The QR payload is not a SARANA form."""


def parse(
    *,
    qr_payload: str,
    text: str,
    correlation_id: str,
    incident_type: str | None = None,
    people_at_risk: int | None = None,
    language: str | None = None,
    officer_id: str | None = None,
) -> ReportIntake:
    """Turn one scanned form into a report.

    Raises:
        UnreadableForm: if the QR is not one of ours. Refusing here is right: a
            mis-scanned code would otherwise attach a report to an arbitrary division.
    """
    match = _QR.match(qr_payload.strip())
    if match is None:
        raise UnreadableForm(
            f"{qr_payload[:40]!r} is not a SARANA form code; expected "
            "SARANA:<gn-division>:<serial>"
        )

    return ReportIntake(
        channel=CHANNEL,
        correlation_id=correlation_id,
        raw_text=text.strip() or None,
        reported_language=language,
        incident_type=incident_type,
        people_at_risk=people_at_risk,
        # The division comes from the printed form, which the officer is standing in.
        location_source="manual",
        channel_metadata={
            "gn_division_code": match.group("division"),
            "form_serial": match.group("serial"),
            "officer_id": officer_id,
        },
    )


def division_of(qr_payload: str) -> str:
    """The GN division a form belongs to."""
    match = _QR.match(qr_payload.strip())
    if match is None:
        raise UnreadableForm(f"{qr_payload[:40]!r} is not a SARANA form code")
    return match.group("division")
