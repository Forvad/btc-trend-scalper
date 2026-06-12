from __future__ import annotations

import math
from typing import Literal

from src.config import TrailSlConfig

PositionSide = Literal["long", "short"]


def _locked_step_pct(excess: float, step: float) -> float:
    if step <= 0:
        return 0.0
    excess = round(excess, 8)
    if excess < step:
        return 0.0
    return math.floor(excess / step) * step


def favorable_move_pct(
    side: PositionSide,
    entry_price: float,
    bar_high: float,
    bar_low: float,
) -> float:
    if side == "long":
        return (bar_high - entry_price) / entry_price * 100
    return (entry_price - bar_low) / entry_price * 100


def update_peak_profit_pct(
    side: PositionSide,
    entry_price: float,
    current_peak: float,
    bar_high: float,
    bar_low: float,
) -> float:
    return max(current_peak, favorable_move_pct(side, entry_price, bar_high, bar_low))


def trail_offset_pct(peak_profit_pct: float, cfg: TrailSlConfig) -> float:
    """
    Сколько % от цены входа добавить к supertrend после trail_start_at_pct.

    До trail_start_at_pct — offset 0 (чистый supertrend).
    """
    if not cfg.enabled or cfg.trail_step_pct <= 0:
        return 0.0
    if peak_profit_pct < cfg.trail_start_at_pct:
        return 0.0
    excess = peak_profit_pct - cfg.trail_start_at_pct
    return _locked_step_pct(excess, cfg.trail_step_pct)


def supertrend_trail_stop(
    side: PositionSide,
    entry_price: float,
    peak_profit_pct: float,
    supertrend: float,
    cfg: TrailSlConfig,
) -> float:
    offset_pct = trail_offset_pct(peak_profit_pct, cfg)
    if offset_pct <= 0:
        return supertrend
    offset = entry_price * offset_pct / 100
    if side == "long":
        return supertrend + offset
    return supertrend - offset


def breakeven_trail_stop(
    side: PositionSide,
    entry_price: float,
    peak_profit_pct: float,
    cfg: TrailSlConfig,
) -> float | None:
    """
    После breakeven_at_pct: пол на входе, далее +trail_step_pct за каждый шаг
    сверх порога (от цены входа).
    """
    if cfg.breakeven_at_pct <= 0 or peak_profit_pct < cfg.breakeven_at_pct:
        return None

    excess = peak_profit_pct - cfg.breakeven_at_pct
    locked_pct = _locked_step_pct(excess, cfg.trail_step_pct)

    offset = entry_price * locked_pct / 100
    if side == "long":
        return entry_price + offset
    return entry_price - offset


def trail_bb_tp_level(side: PositionSide, bb_upper: float, bb_lower: float, cfg: TrailSlConfig) -> float | None:
    if not cfg.enabled or not cfg.take_profit_bb:
        return None
    if side == "long":
        return bb_upper
    return bb_lower


def trail_take_profit_bb(
    side: PositionSide,
    bb_upper: float,
    bb_lower: float,
    bar_high: float,
    bar_low: float,
    cfg: TrailSlConfig,
) -> tuple[float, str] | None:
    tp = trail_bb_tp_level(side, bb_upper, bb_lower, cfg)
    if tp is None:
        return None
    if side == "long" and bar_high >= tp:
        return tp, "take_profit_bb"
    if side == "short" and bar_low <= tp:
        return tp, "take_profit_bb"
    return None


def trail_sl_active(peak_profit_pct: float, cfg: TrailSlConfig) -> bool:
    if trail_offset_pct(peak_profit_pct, cfg) > 0:
        return True
    return cfg.breakeven_at_pct > 0 and peak_profit_pct >= cfg.breakeven_at_pct


def trail_sl_stop_price(
    side: PositionSide,
    entry_price: float,
    peak_profit_pct: float,
    supertrend: float,
    cfg: TrailSlConfig,
) -> float:
    """
    До trail_start_at_pct: supertrend.
    После: supertrend + шаги; breakeven_at_pct — пол на входе + шаги сверх порога.
    """
    if not cfg.enabled:
        return supertrend

    st_stop = supertrend_trail_stop(
        side, entry_price, peak_profit_pct, supertrend, cfg
    )
    be_stop = breakeven_trail_stop(side, entry_price, peak_profit_pct, cfg)
    if be_stop is None:
        return st_stop

    if side == "long":
        return max(st_stop, be_stop)
    return min(st_stop, be_stop)


def trail_sl_exit_reason(peak_profit_pct: float, cfg: TrailSlConfig) -> str:
    _ = peak_profit_pct
    return "trail_sl" if cfg.enabled else "stop_supertrend"


def stop_hit(side: PositionSide, stop_level: float, bar_high: float, bar_low: float) -> bool:
    if side == "long":
        return bar_low <= stop_level
    return bar_high >= stop_level
