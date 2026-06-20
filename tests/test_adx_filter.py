import pandas as pd

from src.config import AdxFilterConfig, StrategyConfig
from src.strategy import TrendScalperStrategy


def test_adx_filter_blocks_low_trend_entries() -> None:
    n = 40
    prices = [50.0 + (i % 3) * 0.2 for i in range(n)]
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC"),
            "open": prices,
            "high": [p + 0.5 for p in prices],
            "low": [p - 0.5 for p in prices],
            "close": prices,
            "volume": [5000.0] * n,
        }
    )
    cfg_off = StrategyConfig(adx_filter=AdxFilterConfig(enabled=False))
    cfg_on = StrategyConfig(
        adx_filter=AdxFilterConfig(enabled=True, period=14, min_for_entry=25.0),
    )
    out_off = TrendScalperStrategy(cfg_off).generate_signals(df)
    out_on = TrendScalperStrategy(cfg_on).generate_signals(df)
    assert "adx" in out_on.columns
    entries_off = int(out_off["long_signal"].sum() + out_off["short_signal"].sum())
    entries_on = int(out_on["long_signal"].sum() + out_on["short_signal"].sum())
    assert entries_on <= entries_off


def test_adx_rising_blocks_falling_trend() -> None:
    n = 30
    prices = [50.0 + i * 0.5 for i in range(n)]
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC"),
            "open": prices,
            "high": [p + 1 for p in prices],
            "low": [p - 1 for p in prices],
            "close": prices,
            "volume": [8000.0] * n,
        }
    )
    cfg_flat = StrategyConfig(
        adx_filter=AdxFilterConfig(enabled=True, min_for_entry=20.0, require_rising=False),
    )
    cfg_rise = StrategyConfig(
        adx_filter=AdxFilterConfig(enabled=True, min_for_entry=20.0, require_rising=True),
    )
    out_flat = TrendScalperStrategy(cfg_flat).generate_signals(df)
    out_rise = TrendScalperStrategy(cfg_rise).generate_signals(df)
    flat_n = int(out_flat["long_signal"].sum() + out_flat["short_signal"].sum())
    rise_n = int(out_rise["long_signal"].sum() + out_rise["short_signal"].sum())
    assert rise_n <= flat_n
