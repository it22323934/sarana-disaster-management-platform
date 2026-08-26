from collections.abc import Callable

import pytest
from sarana_shared.domain.admin import (
    AdminCodeError,
    district_code_of,
    district_code_of_gn,
    ds_code_of,
    validate_district_code,
    validate_ds_code,
    validate_gn_code,
)


def test_valid_codes_pass() -> None:
    assert validate_district_code("LK-21") == "LK-21"
    assert validate_ds_code("LK-21-05") == "LK-21-05"
    assert validate_gn_code("LK-21-05-014") == "LK-21-05-014"


@pytest.mark.parametrize(
    "validator,code",
    [
        (validate_district_code, "Kandy"),  # free-text place name — exactly what's banned
        (validate_district_code, "LK-1"),
        (validate_ds_code, "LK-21"),
        (validate_gn_code, "LK-21-05"),
    ],
)
def test_invalid_codes_are_rejected(validator: Callable[[str], str], code: str) -> None:
    with pytest.raises(AdminCodeError):
        validator(code)


def test_code_derivation_chain() -> None:
    gn = "LK-21-05-014"
    assert ds_code_of(gn) == "LK-21-05"
    assert district_code_of(ds_code_of(gn)) == "LK-21"
    assert district_code_of_gn(gn) == "LK-21"
