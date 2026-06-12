from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import pandas as pd

from src.config import TrailSlConfig
from src.live.hyperliquid_orders import (
    bracket_levels,
    resolve_bracket_tp,
    should_update_bracket_leg,
    validate_bracket,
)
from src.strategy.trail_sl import (
    trail_bb_tp_level,
    trail_sl_exit_reason,
    trail_sl_stop_price,
    update_peak_profit_pct,
)

if TYPE_CHECKING:
    from src.config import LiveConfig
    from src.strategy import TrendScalperStrategy

PositionSide = Literal["long", "short"]


def bar_duration(timeframe: str) -> pd.Timedelta:
    unit = timeframe[-1]
    value = int(timeframe[:-1])
    if unit == "m":
        return pd.Timedelta(minutes=value)
    if unit == "h":
        return pd.Timedelta(hours=value)
    if unit == "d":
        return pd.Timedelta(days=value)
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def entry_price_with_slippage(side: PositionSide, price: float, slippage: float) -> float:
    if side == "long":
        return price * (1 + slippage)
    return price * (1 - slippage)


def estimate_tick_size(price: float) -> float:
    if price >= 1000:
        return 0.1
    if price >= 100:
        return 0.01
    if price >= 10:
        return 0.001
    return 0.0001


def check_bracket_fill(
    side: PositionSide,
    *,
    sl: float | None,
    tp: float | None,
    bar_high: float,
    bar_low: float,
    sl_reason: str = "stop_supertrend",
) -> tuple[float, str] | None:
    """Проверка срабатывания bracket SL/TP внутри бара (как на бирже)."""
    if side == "long":
        if tp is not None and bar_high >= tp:
            return tp, "take_profit_bb"
        if sl is not None and bar_low <= sl:
            return sl, sl_reason
    else:
        if tp is not None and bar_low <= tp:
            return tp, "take_profit_bb"
        if sl is not None and bar_high >= sl:
            return sl, sl_reason
    return None


def update_tracked_brackets(
    side: PositionSide,
    signal: dict,
    mark: float,
    *,
    sl: float | None,
    tp: float | None,
    min_tp_change_pct: float,
    min_tp_change_ticks: int,
    tick_size: float,
    tp_mode: str = "tighten",
) -> tuple[float | None, float | None]:
    stop_raw, tp_raw = bracket_levels(side, signal)
    new_sl, new_tp = validate_bracket(side, mark, stop_raw, tp_raw)

    if new_sl is not None:
        if sl is None or should_update_bracket_leg("sl", sl, new_sl):
            sl = new_sl

    if new_tp is not None:
        new_tp = resolve_bracket_tp(side, new_tp, tp, tp_mode)
        if tp is None or should_update_bracket_leg(
            "tp",
            tp,
            new_tp,
            min_tp_change_pct=min_tp_change_pct,
            min_tp_change_ticks=min_tp_change_ticks,
            tick_size=tick_size,
        ):
            tp = new_tp

    return sl, tp


def apply_partial_ohlc(
    raw_df: pd.DataFrame,
    bar_index: int,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> pd.DataFrame:
    frame = raw_df.iloc[: bar_index + 1].copy()
    frame.iat[bar_index, frame.columns.get_loc("open")] = open_
    frame.iat[bar_index, frame.columns.get_loc("high")] = high
    frame.iat[bar_index, frame.columns.get_loc("low")] = low
    frame.iat[bar_index, frame.columns.get_loc("close")] = close
    frame.iat[bar_index, frame.columns.get_loc("volume")] = volume
    return frame


def simulate_htf_bar_intrabar(
    strategy: TrendScalperStrategy,
    raw_df: pd.DataFrame,
    bar_index: int,
    intrabar_bars: pd.DataFrame,
    htf_df: pd.DataFrame | None,
    *,
    pos_side: PositionSide | None,
    bracket_sl: float | None,
    bracket_tp: float | None,
    live: LiveConfig,
    entry_price: float | None = None,
    peak_profit_pct: float = 0.0,
    trail_sl: TrailSlConfig | None = None,
) -> tuple[
    PositionSide | None,
    float | None,
    float | None,
    dict | None,
    dict | None,
    float,
]:
    """
    Симуляция одного HTF-бара по sub-TF свечам (как live poll + bracket).

    Returns:
        (pos_side, bracket_sl, bracket_tp, entry_event, exit_event)
        entry_event: {side, price, time}
        exit_event: {price, reason, time}
    """
    trail_cfg = trail_sl or TrailSlConfig()
    peak = peak_profit_pct

    if intrabar_bars.empty:
        return pos_side, bracket_sl, bracket_tp, None, None, peak

    bar_open = float(intrabar_bars.iloc[0]["open"])
    running_high = bar_open
    running_low = bar_open
    running_vol = 0.0

    entry_event: dict | None = None
    exit_event: dict | None = None

    for _, sub in intrabar_bars.iterrows():
        sub_high = float(sub["high"])
        sub_low = float(sub["low"])
        sub_close = float(sub["close"])
        running_high = max(running_high, sub_high)
        running_low = min(running_low, sub_low)
        running_vol += float(sub["volume"])

        slice_raw = apply_partial_ohlc(
            raw_df,
            bar_index,
            open_=bar_open,
            high=running_high,
            low=running_low,
            close=sub_close,
            volume=running_vol,
        )
        signal = strategy.latest_signal(slice_raw, htf_df)
        tick_size = estimate_tick_size(sub_close)

        if pos_side is None:
            if signal["long_signal"]:
                entry_event = {
                    "side": "long",
                    "price": entry_price_with_slippage("long", sub_close, live.slippage),
                    "time": sub["timestamp"],
                }
                pos_side = "long"
                entry_price = entry_event["price"]
                bracket_sl = bracket_tp = None
                peak = 0.0
            elif signal["short_signal"]:
                entry_event = {
                    "side": "short",
                    "price": entry_price_with_slippage("short", sub_close, live.slippage),
                    "time": sub["timestamp"],
                }
                pos_side = "short"
                entry_price = entry_event["price"]
                bracket_sl = bracket_tp = None
                peak = 0.0
        elif entry_price is not None:
            if trail_cfg.enabled:
                peak = update_peak_profit_pct(
                    pos_side, entry_price, peak, sub_high, sub_low
                )
                bracket_sl = trail_sl_stop_price(
                    pos_side,
                    entry_price,
                    peak,
                    float(signal["supertrend"]),
                    trail_cfg,
                )
                bracket_tp = trail_bb_tp_level(
                    pos_side,
                    float(signal["bb_upper"]),
                    float(signal["bb_lower"]),
                    trail_cfg,
                )
            else:
                bracket_sl, bracket_tp = update_tracked_brackets(
                    pos_side,
                    signal,
                    sub_close,
                    sl=bracket_sl,
                    tp=bracket_tp,
                    min_tp_change_pct=live.bracket_tp_min_change_pct,
                    min_tp_change_ticks=live.bracket_tp_min_change_ticks,
                    tick_size=tick_size,
                    tp_mode=live.bracket_tp_mode,
                )

            if trail_cfg.enabled:
                fill_tp = bracket_tp if trail_cfg.take_profit_bb else None
            else:
                fill_tp = bracket_tp
            fill = check_bracket_fill(
                pos_side,
                sl=bracket_sl,
                tp=fill_tp,
                bar_high=sub_high,
                bar_low=sub_low,
                sl_reason=trail_sl_exit_reason(peak, trail_cfg)
                if trail_cfg.enabled
                else "stop_supertrend",
            )
            if fill:
                exit_price, reason = fill
                exit_event = {
                    "price": exit_price,
                    "reason": reason,
                    "time": sub["timestamp"],
                }
                pos_side = None
                bracket_sl = bracket_tp = None
                peak = 0.0

    return pos_side, bracket_sl, bracket_tp, entry_event, exit_event, peak


def htf_bar_intrabar_fallback(
    pos_side: PositionSide,
    row: pd.Series,
    *,
    bracket_sl: float | None,
    bracket_tp: float | None,
    trail_sl: TrailSlConfig | None = None,
    entry_price: float | None = None,
    peak_profit_pct: float = 0.0,
) -> tuple[float, str] | None:
    """Fallback: bracket на HTF-баре по high/low, если нет sub-TF данных."""
    trail_cfg = trail_sl or TrailSlConfig()
    bar_high = float(row["high"])
    bar_low = float(row["low"])

    if trail_cfg.enabled and entry_price is not None:
        peak = update_peak_profit_pct(
            pos_side, entry_price, peak_profit_pct, bar_high, bar_low
        )
        sl = bracket_sl
        if sl is None:
            sl = trail_sl_stop_price(
                pos_side,
                entry_price,
                peak,
                float(row["supertrend"]),
                trail_cfg,
            )
        tp = trail_bb_tp_level(
            pos_side,
            float(row["bb_upper"]),
            float(row["bb_lower"]),
            trail_cfg,
        )
        return check_bracket_fill(
            pos_side,
            sl=sl,
            tp=tp,
            bar_high=bar_high,
            bar_low=bar_low,
            sl_reason="trail_sl",
        )

    return check_bracket_fill(
        pos_side,
        sl=bracket_sl if bracket_sl is not None else float(row["supertrend"]),
        tp=bracket_tp
        if bracket_tp is not None
        else (float(row["bb_upper"]) if pos_side == "long" else float(row["bb_lower"])),
        bar_high=bar_high,
        bar_low=bar_low,
    )
