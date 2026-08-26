"""UUIDv7 keys, public short codes and the correlation chain."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sarana_shared.domain.ids import (
    ensure_correlation_id,
    get_correlation_id,
    reset_correlation_id,
    short_code,
    uuid7,
    uuid7_timestamp,
)


def test_uuid7_is_version_7() -> None:
    assert uuid7().version == 7


def test_uuid7_is_monotonic_within_a_millisecond() -> None:
    """Sort order is the reason for choosing v7; a burst must not break it."""
    minted = [uuid7() for _ in range(2000)]

    assert minted == sorted(minted)
    assert len(set(minted)) == len(minted)


def test_uuid7_carries_its_creation_time() -> None:
    before = datetime.now(UTC)
    value = uuid7()
    after = datetime.now(UTC)

    embedded = uuid7_timestamp(value)

    # The embedded stamp is millisecond-truncated, so allow one millisecond either side.
    assert (before - embedded).total_seconds() < 0.002
    assert (embedded - after).total_seconds() < 0.002


def test_uuid7_timestamp_rejects_another_version() -> None:
    from uuid import uuid4

    with pytest.raises(ValueError, match="version 4"):
        uuid7_timestamp(uuid4())


def test_short_code_shape_is_stable() -> None:
    code = short_code("INC", at=datetime(2025, 11, 28, 4, 30, tzinfo=UTC))

    assert code.startswith("INC-251128-")
    assert len(code) == len("INC-251128-XXXXXX")


def test_short_code_omits_ambiguous_letters() -> None:
    """Codes are read aloud over a phone line and typed off a printed docket.

    I, L, O and U are excluded so a code cannot be confused with 1, 0 or V.
    """
    codes = "".join(short_code("CLM") for _ in range(200))
    suffixes = "".join(code.split("-")[2] for code in codes.split("CLM")[1:] if code)

    assert not set(suffixes) & set("ILOU")


def test_short_code_rejects_a_lowercase_prefix() -> None:
    with pytest.raises(ValueError, match="uppercase"):
        short_code("inc")


def test_short_code_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        short_code("INC", at=datetime(2025, 11, 28, 4, 30))  # noqa: DTZ001 - the point of the test


def test_correlation_id_is_minted_once_and_reused() -> None:
    reset_correlation_id()

    first = ensure_correlation_id()

    assert ensure_correlation_id() == first
    assert get_correlation_id() == first
