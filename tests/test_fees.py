import pytest

from src.exchange.fees import get_fee_preset


def test_hyperliquid_preset() -> None:
    fees = get_fee_preset("hyperliquid")
    assert fees.maker_pct == 0.015
    assert fees.taker_pct == 0.045
    assert fees.entry == "taker"
    assert fees.exit_tp == "maker"


def test_exit_rate_differs_for_stop_and_tp() -> None:
    fees = get_fee_preset("hyperliquid")
    assert fees.exit_rate("stop_supertrend") == pytest.approx(0.00045)
    assert fees.exit_rate("take_profit_bb") == pytest.approx(0.00015)
