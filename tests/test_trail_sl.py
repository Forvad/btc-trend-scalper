from __future__ import annotations

import pytest

from src.config import TrailSlConfig
from src.strategy.trail_sl import (
    stop_hit,
    trail_offset_pct,
    trail_sl_exit_reason,
    trail_sl_stop_price,
    trail_take_profit_bb,
    update_peak_profit_pct,
)


def test_trail_sl_before_first_step_uses_supertrend() -> None:
    cfg = TrailSlConfig(enabled=True, trail_step_pct=1.0)
    assert trail_sl_stop_price("long", 100.0, 0.9, 95.0, cfg) == 95.0


def test_trail_sl_first_step_offsets_from_supertrend() -> None:
    cfg = TrailSlConfig(enabled=True, trail_step_pct=1.0)
    assert trail_sl_stop_price("long", 100.0, 1.0, 95.0, cfg) == pytest.approx(96.0)
    assert trail_sl_stop_price("short", 100.0, 1.0, 105.0, cfg) == pytest.approx(104.0)


def test_trail_sl_steps_each_1_pct_from_supertrend() -> None:
    cfg = TrailSlConfig(enabled=True, trail_step_pct=1.0)
    assert trail_sl_stop_price("long", 100.0, 1.9, 95.0, cfg) == pytest.approx(96.0)
    assert trail_sl_stop_price("long", 100.0, 2.0, 95.0, cfg) == pytest.approx(97.0)
    assert trail_sl_stop_price("short", 100.0, 2.0, 105.0, cfg) == pytest.approx(103.0)


def test_trail_sl_small_step_0_1_pct() -> None:
    cfg = TrailSlConfig(enabled=True, trail_step_pct=0.1)
    assert trail_offset_pct(0.09, cfg) == 0.0
    assert trail_sl_stop_price("long", 100.0, 0.1, 95.0, cfg) == pytest.approx(95.1)
    assert trail_sl_stop_price("long", 100.0, 0.25, 95.0, cfg) == pytest.approx(95.2)
    assert trail_sl_stop_price("long", 100.0, 0.2, 95.0, cfg) == pytest.approx(95.2)


def test_peak_profit_tracks_intrabar_high() -> None:
    peak = update_peak_profit_pct("long", 100.0, 0.0, 104.0, 99.0)
    assert peak == pytest.approx(4.0)


def test_trail_exit_reason() -> None:
    cfg = TrailSlConfig(enabled=True, trail_step_pct=1.0)
    assert trail_sl_exit_reason(0.9, cfg) == "trail_sl"
    assert trail_sl_exit_reason(1.0, cfg) == "trail_sl"


def test_stop_hit_long() -> None:
    assert stop_hit("long", 101.0, 102.0, 100.5) is True
    assert stop_hit("long", 101.0, 102.0, 101.5) is False


def test_breakeven_floor_at_threshold() -> None:
    cfg = TrailSlConfig(enabled=True, breakeven_at_pct=3.0, trail_step_pct=0.3)
    # до порога — supertrend + шаги
    assert trail_sl_stop_price("long", 100.0, 2.9, 95.0, cfg) == pytest.approx(97.7)
    # на пороге — минимум вход
    assert trail_sl_stop_price("long", 100.0, 3.0, 95.0, cfg) == pytest.approx(100.0)
    assert trail_sl_stop_price("short", 100.0, 3.0, 105.0, cfg) == pytest.approx(100.0)


def test_breakeven_trail_steps_after_threshold() -> None:
    cfg = TrailSlConfig(enabled=True, breakeven_at_pct=3.0, trail_step_pct=0.3)
    # +3.3%: один шаг сверх порога → вход + 0.3%
    assert trail_sl_stop_price("long", 100.0, 3.3, 95.0, cfg) == pytest.approx(100.3)
    assert trail_sl_stop_price("long", 100.0, 3.59, 95.0, cfg) == pytest.approx(100.3)
    assert trail_sl_stop_price("long", 100.0, 3.6, 95.0, cfg) == pytest.approx(100.6)
    assert trail_sl_stop_price("short", 100.0, 3.6, 105.0, cfg) == pytest.approx(99.4)


def test_breakeven_disabled_preserves_supertrend_only() -> None:
    cfg = TrailSlConfig(enabled=True, breakeven_at_pct=0.0, trail_step_pct=1.0)
    assert trail_sl_stop_price("long", 100.0, 5.0, 95.0, cfg) == pytest.approx(100.0)


def test_trail_start_delays_offset_until_threshold() -> None:
    cfg = TrailSlConfig(enabled=True, trail_start_at_pct=1.5, trail_step_pct=0.3)
    assert trail_sl_stop_price("long", 100.0, 1.4, 95.0, cfg) == 95.0
    assert trail_sl_stop_price("long", 100.0, 1.7, 95.0, cfg) == 95.0
    assert trail_sl_stop_price("long", 100.0, 1.8, 95.0, cfg) == pytest.approx(95.3)


def test_trail_take_profit_bb_long() -> None:
    cfg = TrailSlConfig(enabled=True, take_profit_bb=True)
    hit = trail_take_profit_bb("long", 110.0, 90.0, 111.0, 100.0, cfg)
    assert hit == (110.0, "take_profit_bb")


def test_trail_take_profit_bb_disabled() -> None:
    cfg = TrailSlConfig(enabled=True, take_profit_bb=False)
    assert trail_take_profit_bb("long", 110.0, 90.0, 111.0, 100.0, cfg) is None
