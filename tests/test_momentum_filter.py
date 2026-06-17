import pandas as pd
import pytest

from src.config import MomentumFilterConfig, StrategyConfig
from src.strategy import TrendScalperStrategy
from src.strategy.momentum import rise_pct


def test_rise_pct() -> None:
    close = pd.Series([100.0, 105.0, 112.0, 115.0])
    out = rise_pct(close, 2)
    assert out.iloc[3] == pytest.approx(9.5238, rel=1e-3)


def test_overheated_column_blocks_long_signals() -> None:
    n = 70
    prices = [50.0] * 30 + list(range(50, 90))
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC"),
            "open": prices,
            "high": [p + 1 for p in prices],
            "low": [p - 1 for p in prices],
            "close": prices,
            "volume": [1000.0] * n,
        }
    )
    cfg = StrategyConfig(
        momentum_filter=MomentumFilterConfig(enabled=True, lookback_bars=24, max_rise_pct=10.0),
    )
    out = TrendScalperStrategy(cfg).generate_signals(df)
    assert bool(out["overheated"].iloc[-1])
    assert not out.loc[out["overheated"].fillna(False), "long_signal"].any()
