from __future__ import annotations

import pandas as pd

from src.config import StrategyConfig
from src.strategy.prepare import prepare_dataframe

HTF_MAP = {"15m": "1h", "1h": "4h", "5m": "15m"}


def htf_for_timeframe(timeframe: str) -> str:
    return HTF_MAP.get(timeframe, "4h")


def merge_htf_bias(
    ltf: pd.DataFrame,
    htf: pd.DataFrame,
    config: StrategyConfig,
) -> pd.DataFrame:
    htf_data = prepare_dataframe(htf, config)
    bias = htf_data[["timestamp", "supertrend_direction", "ema_fast", "ema_slow"]].copy()
    bias["htf_bull"] = (bias["supertrend_direction"] == 1) & (bias["ema_fast"] > bias["ema_slow"])
    bias["htf_bear"] = (bias["supertrend_direction"] == -1) & (bias["ema_fast"] < bias["ema_slow"])
    bias = bias[["timestamp", "htf_bull", "htf_bear"]].sort_values("timestamp")

    merged = pd.merge_asof(
        ltf.sort_values("timestamp"),
        bias,
        on="timestamp",
        direction="backward",
    )
    return merged
