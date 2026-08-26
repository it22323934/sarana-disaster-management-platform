from datetime import date

from sarana_shared.domain.ids import is_valid_short_code, short_code, uuid7


def test_uuid7_is_unique_and_time_ordered() -> None:
    a = uuid7()
    b = uuid7()
    assert a != b
    # UUIDv7's first bits are a millisecond timestamp, so successive ids sort ascending.
    assert str(a) < str(b)


def test_short_code_format() -> None:
    code = short_code("INC", when=date(2026, 9, 1))
    assert code.startswith("INC-260901-")
    prefix, yymmdd, suffix = code.split("-")
    assert prefix == "INC"
    assert yymmdd == "260901"
    assert len(suffix) == 6


def test_short_code_is_valid_round_trips() -> None:
    code = short_code("CLM", when=date(2026, 9, 1))
    assert is_valid_short_code(code, prefix="CLM")
    assert not is_valid_short_code(code, prefix="INC")
    assert not is_valid_short_code("not-a-code", prefix="CLM")
    assert not is_valid_short_code("CLM-260901", prefix="CLM")  # missing suffix
