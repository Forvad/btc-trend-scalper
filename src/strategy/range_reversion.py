from __future__ import annotations

import pandas as pd

from src.config import RangeStrategyConfig
from src.indicators import (
    add_adx,
    add_bollinger_bands,
    add_ema,
    add_rsi,
    add_support_resistance,
)


def prepare_range_dataframe(df: pd.DataFrame, config: RangeStrategyConfig) -> pd.DataFrame:
    result = add_bollinger_bands(
        df,
        period=config.bollinger.period,
        std_dev=config.bollinger.std_dev,
    )
    result = add_rsi(result, config.rsi.period)
    result = add_adx(result, config.adx.period)
    result = add_ema(result, 20, 50)
    if config.sr_filter.enabled:
        result = add_support_resistance(
            result,
            lookback=config.sr_filter.lookback,
            pivot_window=config.sr_filter.pivot_window,
            cluster_pct=config.sr_filter.cluster_pct,
        )
    result["bb_width_pct"] = (
        (result["bb_upper"] - result["bb_lower"]) / result["bb_middle"].replace(0, 1) * 100
    )
    return result


def compute_stop_price(
    side: str,
    entry_price: float,
    row_window: pd.DataFrame,
    config: RangeStrategyConfig,
) -> float:
    pct_stop = config.stop_loss_pct / 100
    if side == "long":
        fixed = entry_price * (1 - pct_stop)
        if not config.use_swing_stop or row_window.empty:
            return fixed
        swing_low = float(row_window["low"].min())
        swing_stop = swing_low * (1 - config.swing_buffer_pct / 100)
        return min(fixed, swing_stop)
    fixed = entry_price * (1 + pct_stop)
    if not config.use_swing_stop or row_window.empty:
        return fixed
    swing_high = float(row_window["high"].max())
    swing_stop = swing_high * (1 + config.swing_buffer_pct / 100)
    return max(fixed, swing_stop)


class RangeReversionStrategy:
    """
    Флэт v2: отскок от BB только в сжатом диапазоне,
    с подтверждением свечой, RSI hook и без входа против тренда.
    """

    def __init__(self, config: RangeStrategyConfig) -> None:
        self.config = config

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        data = prepare_range_dataframe(df, self.config)
        cfg = self.config
        adx = data["adx"]
        rsi = data["rsi"]
        prev_adx = adx.shift(1)
        prev2_adx = adx.shift(2)
        prev_rsi = rsi.shift(1)

        if cfg.max_bb_width_pct > 0:
            narrow_bb = data["bb_width_pct"] <= cfg.max_bb_width_pct
        else:
            narrow_bb = True
        flat_market = adx < cfg.adx.max_for_entry
        if cfg.require_adx_flat:
            flat_market &= adx <= prev_adx.fillna(adx)

        prev_low = data["low"].shift(1)
        prev_high = data["high"].shift(1)
        prev_close = data["close"].shift(1)
        prev_bb_lower = data["bb_lower"].shift(1)
        prev_bb_upper = data["bb_upper"].shift(1)

        if cfg.entry_mode == "touch":
            touch_lower = (data["low"] <= data["bb_lower"]) | (data["close"] <= data["bb_lower"])
            touch_upper = (data["high"] >= data["bb_upper"]) | (data["close"] >= data["bb_upper"])
            in_oversold = (rsi < cfg.rsi.oversold) | (prev_rsi < cfg.rsi.oversold)
            in_overbought = (rsi > cfg.rsi.overbought) | (prev_rsi > cfg.rsi.overbought)
            rsi_long = in_oversold
            rsi_short = in_overbought
            if cfg.require_rsi_hook:
                rsi_long &= rsi > prev_rsi.fillna(rsi)
                rsi_short &= rsi < prev_rsi.fillna(rsi)
            long_reject = touch_lower
            short_reject = touch_upper
            if cfg.require_rejection_candle:
                long_reject &= (data["low"] <= data["bb_lower"]) & (data["close"] > data["bb_lower"])
                short_reject &= (data["high"] >= data["bb_upper"]) & (data["close"] < data["bb_upper"])
                long_reject &= data["close"] >= data["open"]
                short_reject &= data["close"] <= data["open"]
        else:
            touched_lower = prev_low <= prev_bb_lower
            touched_upper = prev_high >= prev_bb_upper
            was_oversold = prev_rsi < cfg.rsi.oversold
            was_overbought = prev_rsi > cfg.rsi.overbought
            bounce_up = (data["close"] > prev_close) & (rsi > prev_rsi.fillna(rsi))
            bounce_down = (data["close"] < prev_close) & (rsi < prev_rsi.fillna(rsi))
            if cfg.require_rejection_candle:
                bounce_up &= data["close"] >= data["open"]
                bounce_down &= data["close"] <= data["open"]
            rsi_long = was_oversold & bounce_up
            rsi_short = was_overbought & bounce_down
            long_reject = touched_lower
            short_reject = touched_upper

        reward_long = (
            (data["bb_middle"] - data["close"]) / data["close"] * 100
        ) >= cfg.min_reward_to_middle_pct
        reward_short = (
            (data["close"] - data["bb_middle"]) / data["close"] * 100
        ) >= cfg.min_reward_to_middle_pct

        long_signal = narrow_bb & flat_market & long_reject & rsi_long & reward_long
        short_signal = narrow_bb & flat_market & short_reject & rsi_short & reward_short

        if cfg.block_counter_trend:
            downtrend = (data["ema_fast"] < data["ema_slow"]) & (adx > cfg.counter_trend_adx)
            uptrend = (data["ema_fast"] > data["ema_slow"]) & (adx > cfg.counter_trend_adx)
            long_signal &= ~downtrend
            short_signal &= ~uptrend

        if cfg.sr_filter.enabled:
            long_signal &= data.get("near_support", False)
            short_signal &= data.get("near_resistance", False)

        adx_rising = (adx > prev_adx) & (prev_adx > prev2_adx)
        emergency = (adx > cfg.adx.emergency_exit) | (
            (adx > cfg.adx.rising_emergency) & adx_rising
        )

        data["long_signal"] = long_signal.fillna(False)
        data["short_signal"] = short_signal.fillna(False)
        data["adx_emergency"] = emergency.fillna(False)
        data["long_exit_tp_opposite"] = data["high"] >= data["bb_upper"]
        data["long_exit_tp_middle"] = data["high"] >= data["bb_middle"]
        data["short_exit_tp_opposite"] = data["low"] <= data["bb_lower"]
        data["short_exit_tp_middle"] = data["low"] <= data["bb_middle"]

        return data

    def latest_signal(self, df: pd.DataFrame) -> dict:
        data = self.generate_signals(df)
        last = data.iloc[-1]
        return {
            "timestamp": last["timestamp"],
            "close": float(last["close"]),
            "bb_upper": float(last["bb_upper"]),
            "bb_middle": float(last["bb_middle"]),
            "bb_lower": float(last["bb_lower"]),
            "bb_width_pct": float(last["bb_width_pct"]),
            "rsi": float(last["rsi"]),
            "adx": float(last["adx"]),
            "long_signal": bool(last["long_signal"]),
            "short_signal": bool(last["short_signal"]),
            "adx_emergency": bool(last["adx_emergency"]),
            "long_exit_tp_opposite": bool(last["long_exit_tp_opposite"]),
            "long_exit_tp_middle": bool(last["long_exit_tp_middle"]),
            "short_exit_tp_opposite": bool(last["short_exit_tp_opposite"]),
            "short_exit_tp_middle": bool(last["short_exit_tp_middle"]),
        }
