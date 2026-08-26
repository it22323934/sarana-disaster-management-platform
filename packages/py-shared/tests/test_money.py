from sarana_shared.domain.money import add, apply_cap, apply_rate, format_lkr, to_lkr_cents


def test_to_lkr_cents_parses_string_exactly() -> None:
    assert to_lkr_cents("1250.50") == 125050
    assert to_lkr_cents("1,250.50") == 125050
    assert to_lkr_cents("0") == 0
    assert to_lkr_cents("-100.25") == -10025


def test_to_lkr_cents_pads_missing_fraction() -> None:
    assert to_lkr_cents("100") == 10000
    assert to_lkr_cents("100.5") == 10050


def test_format_lkr() -> None:
    assert format_lkr(to_lkr_cents("1250.50")) == "Rs. 1,250.50"
    assert format_lkr(to_lkr_cents("-1250.50")) == "-Rs. 1,250.50"
    assert format_lkr(to_lkr_cents("0")) == "Rs. 0.00"


def test_add() -> None:
    total = add(to_lkr_cents("100"), to_lkr_cents("50.50"), to_lkr_cents("0.50"))
    assert total == to_lkr_cents("151")


def test_apply_rate_rounds_half_up() -> None:
    base = to_lkr_cents("100")
    assert apply_rate(base, 0.6) == to_lkr_cents("60")


def test_apply_cap() -> None:
    amount = to_lkr_cents("1250000")
    cap = to_lkr_cents("1000000")
    capped, was_capped = apply_cap(amount, cap)
    assert was_capped is True
    assert capped == cap

    under_cap, was_capped = apply_cap(to_lkr_cents("500"), cap)
    assert was_capped is False
    assert under_cap == to_lkr_cents("500")

    no_cap, was_capped = apply_cap(amount, None)
    assert was_capped is False
    assert no_cap == amount
