from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.live.hyperliquid_orders import (
    bracket_legs_to_update,
    bracket_levels,
    build_bracket_params,
    close_order_side,
    is_bracket_sl_valid,
    is_stop_loss_order,
    is_take_profit_order,
    merge_bracket_prices,
    parse_ccxt_position,
    resolve_bracket_tp,
    round_amount,
    should_refresh_bracket,
    should_update_bracket_leg,
    validate_bracket,
)


def test_validate_bracket_short() -> None:
    sl, tp = validate_bracket("short", 73.0, 72.31, 66.5)
    assert sl is None
    assert tp == 66.5


def test_is_bracket_sl_valid_short() -> None:
    signal = {"supertrend": 72.31, "bb_upper": 80.0, "bb_lower": 66.5}
    assert is_bracket_sl_valid("short", signal, 73.0) == (False, 72.31, 66.5)
    assert is_bracket_sl_valid("short", signal, 71.0) == (True, 72.31, 66.5)


def test_is_bracket_sl_valid_long() -> None:
    signal = {"supertrend": 95.0, "bb_upper": 110.0, "bb_lower": 90.0}
    assert is_bracket_sl_valid("long", signal, 100.0) == (True, 95.0, 110.0)
    assert is_bracket_sl_valid("long", signal, 94.0) == (False, 95.0, 110.0)


def test_bracket_levels_long() -> None:
    signal = {"supertrend": 95.0, "bb_upper": 110.0, "bb_lower": 90.0}
    assert bracket_levels("long", signal) == (95.0, 110.0)


def test_bracket_levels_short() -> None:
    signal = {"supertrend": 105.0, "bb_upper": 110.0, "bb_lower": 90.0}
    assert bracket_levels("short", signal) == (105.0, 90.0)


def test_validate_bracket_long() -> None:
    stop, tp = validate_bracket("long", mark_price=100.0, stop_price=95.0, tp_price=108.0)
    assert stop == 95.0
    assert tp == 108.0

    stop, tp = validate_bracket("long", mark_price=100.0, stop_price=101.0, tp_price=99.0)
    assert stop is None
    assert tp is None


def test_build_bracket_params() -> None:
    exchange = MagicMock()
    exchange.price_to_precision = lambda _s, p: round(p, 2)
    signal = {"supertrend": 95.0, "bb_upper": 110.0, "bb_lower": 90.0}
    params = build_bracket_params(exchange, "HYPE/USDC:USDC", "long", signal, 100.0)
    assert params["stopLoss"]["triggerPrice"] == 95.0
    assert params["takeProfit"]["triggerPrice"] == 110.0


def test_parse_ccxt_position_short_uses_szi_sign() -> None:
    exchange = MagicMock()
    exchange.amount_to_precision = lambda _s, a: a
    pos = {
        "side": "short",
        "contracts": 1.7,
        "entryPrice": 55.0,
        "info": {"position": {"szi": "-1.7", "entryPx": "55.0"}},
    }
    parsed = parse_ccxt_position(pos, exchange, "HYPE/USDC:USDC")
    assert parsed is not None
    side, amount, entry = parsed
    assert side == "short"
    assert amount == 1.7
    assert entry == 55.0


def test_should_refresh_bracket() -> None:
    assert should_refresh_bracket(0, 10, orders_missing=True) is True
    assert should_refresh_bracket(5, 10, orders_missing=False) is False
    assert should_refresh_bracket(10, 10, orders_missing=False) is True
    assert should_refresh_bracket(20, 10, orders_missing=False) is True
    assert should_refresh_bracket(10, 0, orders_missing=False) is False


def test_close_order_side() -> None:
    assert close_order_side("long") == "sell"
    assert close_order_side("short") == "buy"


def test_should_update_bracket_leg_sl_any_change() -> None:
    assert should_update_bracket_leg("sl", 95.0, 95.0) is False
    assert should_update_bracket_leg("sl", 95.0, 96.0) is True
    assert should_update_bracket_leg("sl", None, 96.0) is True


def test_should_update_bracket_leg_tp_threshold() -> None:
    assert should_update_bracket_leg("tp", 100.0, 100.4, min_tp_change_pct=0.5) is False
    assert should_update_bracket_leg("tp", 100.0, 100.6, min_tp_change_pct=0.5) is True
    assert should_update_bracket_leg(
        "tp", 100.0, 100.2, min_tp_change_pct=0.5, min_tp_change_ticks=3, tick_size=0.1
    ) is True


def test_resolve_bracket_tp_tighten_short() -> None:
    assert resolve_bracket_tp("short", 53.0, 54.0, "tighten") == 54.0
    assert resolve_bracket_tp("short", 55.0, 54.0, "tighten") == 54.0


def test_resolve_bracket_tp_freeze() -> None:
    assert resolve_bracket_tp("long", 120.0, 110.0, "freeze") == 110.0


def test_resolve_bracket_tp_dynamic_long_follows_bb_up() -> None:
    assert resolve_bracket_tp("long", 59.31, 59.06, "dynamic") == 59.31
    assert resolve_bracket_tp("long", 58.90, 59.06, "dynamic") == 58.90


def test_bracket_legs_to_update() -> None:
    update_sl, update_tp = bracket_legs_to_update(
        "long",
        95.0,
        110.0,
        95.0,
        110.3,
        reason="update",
        min_tp_change_pct=0.5,
        min_tp_change_ticks=0,
        tick_size=0.01,
    )
    assert update_sl is False
    assert update_tp is False

    update_sl, update_tp = bracket_legs_to_update(
        "long",
        95.0,
        110.0,
        96.0,
        111.0,
        reason="update",
        min_tp_change_pct=0.5,
        min_tp_change_ticks=0,
        tick_size=0.01,
        tp_mode="dynamic",
    )
    assert update_sl is True
    assert update_tp is True

    update_sl, update_tp = bracket_legs_to_update(
        "short",
        58.0,
        54.0,
        58.0,
        52.0,
        reason="update",
        min_tp_change_pct=0.0,
        min_tp_change_ticks=0,
        tick_size=0.01,
        tp_mode="tighten",
    )
    assert update_tp is False

    update_sl, update_tp = bracket_legs_to_update(
        "long",
        None,
        None,
        95.0,
        110.0,
        reason="restore",
        min_tp_change_pct=0.5,
        min_tp_change_ticks=0,
        tick_size=0.01,
    )
    assert update_sl is True
    assert update_tp is True


def test_bracket_sl_none_keeps_existing_on_update() -> None:
    """SHORT: supertrend ниже mark → new_sl=None, старый SL на бирже не трогаем."""
    update_sl, update_tp = bracket_legs_to_update(
        "short",
        74.0,
        66.0,
        None,
        66.5,
        reason="update",
        min_tp_change_pct=0.15,
        min_tp_change_ticks=3,
        tick_size=0.001,
        tp_mode="dynamic",
    )
    assert update_sl is False
    assert update_tp is True


def test_should_update_bracket_leg_rejects_none_candidate() -> None:
    assert should_update_bracket_leg("sl", 72.0, None) is False
    assert should_update_bracket_leg("sl", None, 72.0) is True
    merged = merge_bracket_prices(
        (95.0, 110.0),
        {"takeProfit": {"triggerPrice": 112.0}},
    )
    assert merged == (95.0, 112.0)


def test_order_type_detection() -> None:
    assert is_stop_loss_order({"info": {"orderType": "Stop Market"}, "type": "market"}) is True
    assert is_take_profit_order({"info": {"orderType": "Take Profit Limit"}, "type": "limit"}) is True
    assert is_stop_loss_order({"takeProfitPrice": 110.0}) is False


def test_round_amount_rejects_zero() -> None:
    exchange = MagicMock()
    exchange.amount_to_precision = lambda _s, a: 0.0
    exchange.market.return_value = {"limits": {"amount": {"min": 0.0}}}
    with pytest.raises(ValueError):
        round_amount(exchange, "HYPE/USDC:USDC", 0.001)
