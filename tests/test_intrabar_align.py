from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.intrabar_align import (
    align_htf_to_intrabar,
    intrabar_bars_per_htf,
)


def _make_intrabar(start: str, count: int, step_min: int = 5) -> pd.DataFrame:
    ts = pd.date_range(start, periods=count, freq=f"{step_min}min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        }
    )


def _make_htf(start: str, count: int, hours: int = 1) -> pd.DataFrame:
    ts = pd.date_range(start, periods=count, freq=f"{hours}h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": 100.0,
            "high": 102.0,
            "low": 98.0,
            "close": 100.0,
            "volume": 10.0,
        }
    )


def test_intrabar_bars_per_htf_1h_5m() -> None:
    assert intrabar_bars_per_htf("1h", "5m") == 12


def test_align_trims_htf_without_full_intrabar() -> None:
    htf = _make_htf("2026-01-01 10:00", 3)
    # только 2 часа полностью покрыты (24 пятиминутки)
    ib = _make_intrabar("2026-01-01 10:00", 24 + 6)
    aligned_htf, aligned_ib, stats = align_htf_to_intrabar(
        htf, ib, htf_timeframe="1h", sub_timeframe="5m"
    )
    assert stats.htf_bars_before == 3
    assert stats.htf_bars_after == 2
    assert stats.dropped_htf_bars == 1
    assert len(aligned_ib) == 24
    assert aligned_htf["timestamp"].iloc[0] == pd.Timestamp("2026-01-01 10:00", tz="UTC")
    assert aligned_htf["timestamp"].iloc[-1] == pd.Timestamp("2026-01-01 11:00", tz="UTC")


def test_align_raises_when_no_coverage() -> None:
    htf = _make_htf("2026-01-01 10:00", 2)
    ib = _make_intrabar("2026-01-01 10:00", 6)
    with pytest.raises(ValueError, match="Нет HTF-баров"):
        align_htf_to_intrabar(htf, ib, htf_timeframe="1h", sub_timeframe="5m")
