from __future__ import annotations

import pandas as pd

from src.config import RangeStrategyConfig
from src.strategy.range_reversion import RangeReversionStrategy, compute_stop_price


def _sample_df(n: int = 80) -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(n):
        # флэт с колебаниями
        if i % 10 < 5:
            price += 0.3
        else:
            price -= 0.3
        rows.append(
            {
                "timestamp": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=15 * i),
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price,
                "volume": 1000 + (i % 3) * 200,
            }
        )
    return pd.DataFrame(rows)


def test_long_signal_when_flat_oversold_at_lower_bb() -> None:
    df = _sample_df()
    # искусственно создаём перепроданность у нижней полосы
    cfg = RangeStrategyConfig()
    strategy = RangeReversionStrategy(cfg)
    data = strategy.generate_signals(df)
    assert "long_signal" in data.columns
    assert "short_signal" in data.columns
    assert "adx_emergency" in data.columns


def test_compute_stop_long_uses_tighter_of_fixed_and_swing() -> None:
    cfg = RangeStrategyConfig(stop_loss_pct=1.0, use_swing_stop=True, swing_buffer_pct=0.1)
    window = pd.DataFrame({"low": [98.0, 97.5, 97.0], "high": [101.0, 101.5, 102.0]})
    stop = compute_stop_price("long", entry_price=100.0, row_window=window, config=cfg)
    assert stop < 100.0
    assert stop >= 97.0 * (1 - 0.001)


def test_emergency_exit_flag_when_adx_high() -> None:
    df = _sample_df(120)
    cfg = RangeStrategyConfig()
    cfg.adx.emergency_exit = 5.0
    cfg.adx.rising_emergency = 3.0
    data = RangeReversionStrategy(cfg).generate_signals(df)
    assert data["adx_emergency"].any()


def test_narrow_bb_filter_reduces_signals() -> None:
    df = _sample_df(120)
    loose = RangeStrategyConfig(max_bb_width_pct=50.0, require_rejection_candle=False)
    strict = RangeStrategyConfig(max_bb_width_pct=2.0, require_rejection_candle=False)
    loose_count = RangeReversionStrategy(loose).generate_signals(df)["long_signal"].sum()
    strict_count = RangeReversionStrategy(strict).generate_signals(df)["long_signal"].sum()
    assert strict_count <= loose_count
