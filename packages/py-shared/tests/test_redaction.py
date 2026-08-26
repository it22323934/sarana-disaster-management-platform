"""PII redaction. The deny-list and the regex sweep, applied at the handler."""

from __future__ import annotations

from sarana_shared.telemetry.logging import REDACTED, redact, redact_text, redaction_processor


def test_legacy_nic_is_removed() -> None:
    assert redact_text("applicant 912345678V filed a claim") == f"applicant {REDACTED} filed a claim"


def test_modern_twelve_digit_nic_is_removed() -> None:
    assert REDACTED in redact_text("NIC 200012345678")


def test_local_and_international_phone_numbers_are_removed() -> None:
    assert "0712345678" not in redact_text("call 0712345678")
    assert "+94 71 234 5678" not in redact_text("call +94 71 234 5678")


def test_household_coordinates_are_removed() -> None:
    """Non-negotiable #3: an exact household coordinate is personal data."""
    assert REDACTED in redact_text("located at 6.92710, 79.86120")


def test_denied_keys_are_dropped_whatever_the_value() -> None:
    redacted = redact(
        {
            "applicant_nic": "912345678V",
            "contact_phone": "0712345678",
            "bank_account_number": "1234567890",
            "full_name": "A name",
            "lat": 6.9271,
            "lon": 79.8612,
        }
    )

    assert set(redacted.values()) == {REDACTED}


def test_operational_keys_survive() -> None:
    """Redaction that eats the correlation ID makes an incident undiagnosable."""
    redacted = redact(
        {"correlation_id": "018f-abc", "gn_division_id": "LK-11-03-045", "latency_ms": 42}
    )

    assert redacted["correlation_id"] == "018f-abc"
    assert redacted["gn_division_id"] == "LK-11-03-045"
    assert redacted["latency_ms"] == 42


def test_nested_structures_are_swept() -> None:
    redacted = redact({"report": {"notes": ["reached on 0712345678"], "gn": "LK-11-03-045"}})

    assert REDACTED in redacted["report"]["notes"][0]
    assert redacted["report"]["gn"] == "LK-11-03-045"


def test_deeply_nested_input_degrades_rather_than_hanging() -> None:
    deep: dict[str, object] = {"level": "leaf"}
    for _ in range(20):
        deep = {"level": deep}

    assert redact(deep) is not None


def test_the_processor_applies_to_every_bound_value() -> None:
    """A third-party library must not be able to emit an unredacted line."""
    event = redaction_processor(None, "info", {"event": "call", "phone": "0712345678"})

    assert event["phone"] == REDACTED
    assert event["event"] == "call"
