from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.live_like import (
    check_bracket_fill,
    entry_price_with_slippage,
    htf_bar_intrabar_fallback,
    simulate_htf_bar_intrabar,
)
from src.config import LiveConfig, StrategyConfig, TrailSlConfig


class _BracketStrategy:
    def __init__(self) -> None:
        self.config = StrategyConfig()
        self.allow_short_entry = False
        self.tp = 53.62
        self.sl = 58.0

    def latest_signal(self, df: pd.DataFrame, htf_df: pd.DataFrame | None = None) -> dict:
        last = df.iloc[-1]
        return {
            "timestamp": last["timestamp"],
            "close": float(last["close"]),
            "supertrend": self.sl,
            "bb_upper": 60.0,
            "bb_lower": self.tp,
            "long_signal": False,
            "short_signal": self.allow_short_entry,
            "long_exit_stop": False,
            "long_exit_tp": False,
            "short_exit_stop": False,
            "short_exit_tp": False,
        }


def test_entry_slippage_long() -> None:
    assert entry_price_with_slippage("long", 100.0, 0.005) == pytest.approx(100.5)


def test_check_bracket_fill_short_tp() -> None:
    fill = check_bracket_fill("short", sl=58.0, tp=53.62, bar_high=54.0, bar_low=53.5)
    assert fill == (53.62, "take_profit_bb")


def test_check_bracket_fill_long_tp_before_sl() -> None:
    fill = check_bracket_fill("long", sl=95.0, tp=110.0, bar_high=111.0, bar_low=94.0)
    assert fill == (110.0, "take_profit_bb")


def test_simulate_intrabar_short_tp_exit() -> None:
    raw = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-06-10 16:00", periods=3, freq="1h", tz="UTC"),
            "open": [56.0, 55.0, 54.0],
            "high": [56.5, 55.5, 54.5],
            "low": [55.0, 52.5, 53.0],
            "close": [55.7, 53.2, 53.5],
            "volume": [1000.0, 1000.0, 1000.0],
        }
    )
    sub = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-06-10 17:00", periods=3, freq="5min", tz="UTC"),
            "open": [54.0, 53.8, 53.5],
            "high": [54.1, 53.9, 53.7],
            "low": [53.9, 53.4, 53.2],
            "close": [53.95, 53.5, 53.3],
            "volume": [100.0, 100.0, 100.0],
        }
    )
    strategy = _BracketStrategy()
    live = LiveConfig(slippage=0.0, bracket_tp_min_change_pct=0.0)

    side, sl, tp, entry, exit_ev, _peak = simulate_htf_bar_intrabar(
        strategy,
        raw,
        1,
        sub,
        None,
        pos_side="short",
        bracket_sl=58.0,
        bracket_tp=53.62,
        live=live,
    )

    assert side is None
    assert exit_ev is not None
    assert exit_ev["reason"] == "take_profit_bb"
    assert exit_ev["price"] == pytest.approx(53.62)


def test_trail_fallback_ignores_bb_tp() -> None:
    row = pd.Series(
        {
            "high": 109.0,
            "low": 105.0,
            "supertrend": 95.0,
            "bb_upper": 108.0,
            "bb_lower": 92.0,
        }
    )
    trail = TrailSlConfig(enabled=True, trail_step_pct=1.0)
    fill = htf_bar_intrabar_fallback(
        "long",
        row,
        bracket_sl=None,
        bracket_tp=None,
        trail_sl=trail,
        entry_price=100.0,
        peak_profit_pct=0.0,
    )
    assert fill is None


def test_trail_fallback_exit_reason() -> None:
    row = pd.Series(
        {
            "high": 101.0,
            "low": 94.0,
            "supertrend": 95.0,
            "bb_upper": 110.0,
            "bb_lower": 90.0,
        }
    )
    trail = TrailSlConfig(enabled=True, trail_step_pct=1.0)
    fill = htf_bar_intrabar_fallback(
        "long",
        row,
        bracket_sl=96.0,
        bracket_tp=None,
        trail_sl=trail,
        entry_price=100.0,
        peak_profit_pct=1.0,
    )
    assert fill == (96.0, "trail_sl")
