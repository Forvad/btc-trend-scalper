from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import StrategyConfig
from src.strategy import TrendScalperStrategy


def _trending_up_df(n: int = 120) -> pd.DataFrame:
    prices = np.linspace(50000, 55000, n)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC"),
            "open": prices,
            "high": prices + 100,
            "low": prices - 50,
            "close": prices + 50,
            "volume": np.full(n, 1000.0),
        }
    )


def _trending_down_df(n: int = 120) -> pd.DataFrame:
    prices = np.linspace(55000, 50000, n)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC"),
            "open": prices,
            "high": prices + 50,
            "low": prices - 100,
            "close": prices - 50,
            "volume": np.full(n, 1000.0),
        }
    )


def test_strategy_produces_long_and_short_columns() -> None:
    strategy = TrendScalperStrategy(StrategyConfig())
    data = strategy.generate_signals(_trending_up_df())

    for col in (
        "long_signal",
        "short_signal",
        "long_exit_stop",
        "long_exit_tp",
        "long_exit_partial",
        "short_exit_stop",
        "short_exit_tp",
        "short_exit_partial",
        "bb_lower",
        "bb_middle",
    ):
        assert col in data.columns


def test_short_exit_tp_uses_lower_band() -> None:
    strategy = TrendScalperStrategy(StrategyConfig())
    data = strategy.generate_signals(_trending_down_df())

    tp_rows = data[data["short_exit_tp"]]
    if not tp_rows.empty:
        assert (tp_rows["low"] <= tp_rows["bb_lower"]).all()


def test_long_and_short_signals_are_mutually_exclusive_on_entry() -> None:
    strategy = TrendScalperStrategy(StrategyConfig())
    up = strategy.generate_signals(_trending_up_df())
    down = strategy.generate_signals(_trending_down_df())

    assert not (up["long_signal"] & up["short_signal"]).any()
    assert not (down["long_signal"] & down["short_signal"]).any()
