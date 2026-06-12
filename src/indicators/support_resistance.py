from __future__ import annotations

import numpy as np
import pandas as pd


def _cluster_levels(prices: np.ndarray, tolerance_pct: float) -> list[float]:
    if len(prices) == 0:
        return []
    sorted_prices = np.sort(prices)
    clusters: list[list[float]] = [[float(sorted_prices[0])]]
    for price in sorted_prices[1:]:
        cluster_mean = float(np.mean(clusters[-1]))
        if abs(price - cluster_mean) / cluster_mean * 100 <= tolerance_pct:
            clusters[-1].append(float(price))
        else:
            clusters.append([float(price)])
    return [float(np.mean(c)) for c in clusters]


def add_support_resistance(
    df: pd.DataFrame,
    *,
    lookback: int = 100,
    pivot_window: int = 3,
    cluster_pct: float = 0.5,
) -> pd.DataFrame:
    """
    Находит ближайшие уровни поддержки/сопротивления через локальные экстремумы.
    """
    result = df.copy()
    lows = result["low"].values
    highs = result["high"].values
    n = len(result)

    support = np.full(n, np.nan)
    resistance = np.full(n, np.nan)
    near_support = np.zeros(n, dtype=bool)
    near_resistance = np.zeros(n, dtype=bool)

    for i in range(lookback, n):
        window_start = max(0, i - lookback)
        pivot_lows: list[float] = []
        pivot_highs: list[float] = []

        for j in range(window_start + pivot_window, i - pivot_window + 1):
            local_low = lows[j - pivot_window : j + pivot_window + 1]
            local_high = highs[j - pivot_window : j + pivot_window + 1]
            if lows[j] == local_low.min():
                pivot_lows.append(float(lows[j]))
            if highs[j] == local_high.max():
                pivot_highs.append(float(highs[j]))

        close = float(result["close"].iloc[i])
        sup_levels = _cluster_levels(np.array(pivot_lows), cluster_pct)
        res_levels = _cluster_levels(np.array(pivot_highs), cluster_pct)

        if sup_levels:
            nearest_sup = min(sup_levels, key=lambda lvl: abs(close - lvl))
            support[i] = nearest_sup
            near_support[i] = abs(close - nearest_sup) / close * 100 <= cluster_pct

        if res_levels:
            nearest_res = min(res_levels, key=lambda lvl: abs(close - lvl))
            resistance[i] = nearest_res
            near_resistance[i] = abs(close - nearest_res) / close * 100 <= cluster_pct

    result["sr_support"] = support
    result["sr_resistance"] = resistance
    result["near_support"] = near_support
    result["near_resistance"] = near_resistance
    return result
