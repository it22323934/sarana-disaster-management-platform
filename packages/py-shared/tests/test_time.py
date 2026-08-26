from datetime import UTC, datetime

import pytest
from sarana_shared.domain.time import (
    ensure_utc,
    format_colombo,
    landfall_relative_to_absolute,
    relative_to_landfall,
)


def test_ensure_utc_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="Naive datetime"):
        ensure_utc(datetime(2026, 9, 1, 6, 0, 0))


def test_relative_to_landfall_at_landfall() -> None:
    landfall = datetime(2025, 11, 28, 12, 0, tzinfo=UTC)
    assert relative_to_landfall(landfall, landfall) == "T+0"


def test_relative_to_landfall_hours_before_and_after() -> None:
    landfall = datetime(2025, 11, 28, 12, 0, tzinfo=UTC)
    seventy_two_before = datetime(2025, 11, 25, 12, 0, tzinfo=UTC)
    six_after = datetime(2025, 11, 28, 18, 0, tzinfo=UTC)
    assert relative_to_landfall(seventy_two_before, landfall) == "T-72h"
    assert relative_to_landfall(six_after, landfall) == "T+6h"


def test_relative_to_landfall_days_beyond_72h() -> None:
    landfall = datetime(2025, 11, 28, 12, 0, tzinfo=UTC)
    fourteen_days_after = datetime(2025, 12, 12, 12, 0, tzinfo=UTC)
    assert relative_to_landfall(fourteen_days_after, landfall) == "T+14d"


def test_landfall_relative_to_absolute_round_trips() -> None:
    landfall = datetime(2025, 11, 28, 12, 0, tzinfo=UTC)
    absolute = landfall_relative_to_absolute("T-72h", landfall)
    assert relative_to_landfall(absolute, landfall) == "T-72h"


def test_format_colombo_offsets_from_utc() -> None:
    # 2026-09-01 00:30 UTC -> 06:00 in Colombo (UTC+5:30)
    moment = datetime(2026, 9, 1, 0, 30, tzinfo=UTC)
    assert format_colombo(moment) == "2026-09-01 06:00"
