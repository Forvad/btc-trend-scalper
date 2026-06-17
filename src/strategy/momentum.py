from __future__ import annotations

import pandas as pd


def rise_pct(close: pd.Series, lookback_bars: int) -> pd.Series:
    """Рост цены за lookback баров, %."""
    past = close.shift(lookback_bars)
    return (close - past) / past * 100.0


def overheated_mask(
    close: pd.Series,
    *,
    lookback_bars: int,
    max_rise_pct: float,
) -> pd.Series:
    """True, если монета выросла >= max_rise_pct за lookback баров."""
    if lookback_bars <= 0 or max_rise_pct <= 0:
        return pd.Series(False, index=close.index)
    return rise_pct(close, lookback_bars) >= max_rise_pct
