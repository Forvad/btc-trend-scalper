from __future__ import annotations

import pandas as pd

from src.config import StrategyConfig
from src.strategy.htf import merge_htf_bias
from src.strategy.momentum import overheated_mask, rise_pct
from src.strategy.prepare import prepare_dataframe


class TrendScalperStrategy:
    """EMA cloud breakout + Supertrend + Volume filter (long & short)."""

    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    def generate_signals(
        self,
        df: pd.DataFrame,
        htf_df: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        data = prepare_dataframe(df, self.config)
        enh = self.config.enhancements

        if enh.needs_htf() and htf_df is not None and len(htf_df) > 0:
            data = merge_htf_bias(data, htf_df, self.config)

        prev_close = data["close"].shift(1)
        cloud_top_prev = data["ema_cloud_top"].shift(1)
        cloud_bottom_prev = data["ema_cloud_bottom"].shift(1)

        cloud_breakout_up = (data["close"] > data["ema_cloud_top"]) & (
            prev_close <= cloud_top_prev
        )
        cloud_breakout_down = (data["close"] < data["ema_cloud_bottom"]) & (
            prev_close >= cloud_bottom_prev
        )

        supertrend_bull = data["supertrend_direction"] == 1
        supertrend_bear = data["supertrend_direction"] == -1
        volume_spike = data["volume"] > data["volume_sma"]

        long_signal = cloud_breakout_up & supertrend_bull & volume_spike
        short_signal = cloud_breakout_down & supertrend_bear & volume_spike

        if enh.enabled and enh.entry_filter:
            long_potential = (data["bb_upper"] - data["close"]) / data["close"] * 100
            short_potential = (data["close"] - data["bb_lower"]) / data["close"] * 100
            long_signal &= long_potential >= enh.min_potential_pct
            short_signal &= short_potential >= enh.min_potential_pct

            if enh.require_ema_aligned:
                long_signal &= data["ema_fast"] > data["ema_slow"]
                short_signal &= data["ema_fast"] < data["ema_slow"]

        if enh.needs_adx() and "adx" in data.columns:
            long_signal &= data["adx"] >= enh.min_adx
            short_signal &= data["adx"] >= enh.min_adx

        if enh.needs_htf() and "htf_bull" in data.columns:
            long_signal &= data["htf_bull"].fillna(False)
            short_signal &= data["htf_bear"].fillna(False)

        mf = self.config.momentum_filter
        data["momentum_rise_pct"] = rise_pct(data["close"], mf.lookback_bars)
        if mf.enabled and mf.lookback_bars > 0 and mf.max_rise_pct > 0:
            hot = overheated_mask(
                data["close"],
                lookback_bars=mf.lookback_bars,
                max_rise_pct=mf.max_rise_pct,
            )
            data["overheated"] = hot.fillna(False)
            long_signal &= ~data["overheated"]
        else:
            data["overheated"] = False

        data["long_signal"] = long_signal
        data["short_signal"] = short_signal

        data["long_exit_stop"] = data["close"] < data["supertrend"]
        data["long_exit_tp"] = data["high"] >= data["bb_upper"]
        data["long_exit_partial"] = data["high"] >= data["bb_middle"]
        data["short_exit_stop"] = data["close"] > data["supertrend"]
        data["short_exit_tp"] = data["low"] <= data["bb_lower"]
        data["short_exit_partial"] = data["low"] <= data["bb_middle"]

        data["buy_signal"] = data["long_signal"]
        data["exit_stop"] = data["long_exit_stop"]
        data["exit_tp"] = data["long_exit_tp"]

        return data

    def latest_signal(self, df: pd.DataFrame, htf_df: pd.DataFrame | None = None) -> dict:
        data = self.generate_signals(df, htf_df)
        last = data.iloc[-1]
        prev = data.iloc[-2] if len(data) > 1 else last

        return {
            "timestamp": last["timestamp"],
            "close": float(last["close"]),
            "ema_fast": float(last["ema_fast"]),
            "ema_slow": float(last["ema_slow"]),
            "supertrend": float(last["supertrend"]),
            "supertrend_bull": bool(last["supertrend_direction"] == 1),
            "supertrend_bear": bool(last["supertrend_direction"] == -1),
            "bb_upper": float(last["bb_upper"]),
            "bb_lower": float(last["bb_lower"]),
            "volume": float(last["volume"]),
            "volume_sma": float(last["volume_sma"]),
            "adx": float(last["adx"]) if "adx" in data.columns else None,
            "long_signal": bool(last["long_signal"]),
            "short_signal": bool(last["short_signal"]),
            "overheated": bool(last.get("overheated", False)),
            "momentum_rise_pct": float(last.get("momentum_rise_pct", 0.0) or 0.0),
            "long_exit_stop": bool(last["long_exit_stop"]),
            "long_exit_tp": bool(last["long_exit_tp"]),
            "short_exit_stop": bool(last["short_exit_stop"]),
            "short_exit_tp": bool(last["short_exit_tp"]),
            "buy_signal": bool(last["long_signal"]),
            "exit_stop": bool(last["long_exit_stop"]),
            "exit_tp": bool(last["long_exit_tp"]),
            "prev_close": float(prev["close"]),
        }
