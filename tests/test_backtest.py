from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.engine import (
    BacktestEngine,
    calc_exit_proceeds,
    mark_to_market_equity,
    update_drawdown,
)
from src.config import BacktestConfig, EnhancementConfig, StrategyConfig, v2_enhancement_config
from src.exchange.fees import FeeConfig


def _zero_fees() -> FeeConfig:
    return FeeConfig(maker_pct=0.0, taker_pct=0.0)


def _make_signal_df(rows: list[dict]) -> pd.DataFrame:
    base = {
        "timestamp": pd.Timestamp("2026-01-01", tz="UTC"),
        "open": 100.0,
        "high": 100.0,
        "low": 100.0,
        "close": 100.0,
        "volume": 1000.0,
        "long_signal": False,
        "short_signal": False,
        "long_exit_stop": False,
        "long_exit_tp": False,
        "short_exit_stop": False,
        "short_exit_tp": False,
        "bb_upper": 110.0,
        "bb_middle": 100.0,
        "bb_lower": 90.0,
        "long_exit_partial": False,
        "short_exit_partial": False,
        "supertrend": 95.0,
    }
    data = []
    for i, row in enumerate(rows):
        item = base.copy()
        item.update(row)
        item["timestamp"] = pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(hours=i)
        data.append(item)
    return pd.DataFrame(data)


class FixedStrategy:
    def __init__(self, df: pd.DataFrame) -> None:
        self.config = StrategyConfig()
        self._df = df

    def generate_signals(self, _df: pd.DataFrame, _htf_df: pd.DataFrame | None = None) -> pd.DataFrame:
        return self._df


def test_long_profit_calculation() -> None:
    proceeds, pnl, pnl_pct, fee = calc_exit_proceeds("long", 100.0, 110.0, 1000.0, 0.0)
    assert proceeds == pytest.approx(1100.0)
    assert pnl == pytest.approx(100.0)
    assert pnl_pct == pytest.approx(10.0)
    assert fee == pytest.approx(0.0)


def test_short_profit_calculation() -> None:
    proceeds, pnl, pnl_pct, fee = calc_exit_proceeds("short", 100.0, 90.0, 1000.0, 0.0)
    assert proceeds == pytest.approx(1100.0)
    assert pnl == pytest.approx(100.0)
    assert pnl_pct == pytest.approx(10.0)
    assert fee == pytest.approx(0.0)


def test_short_loss_calculation() -> None:
    proceeds, pnl, pnl_pct, _fee = calc_exit_proceeds("short", 100.0, 110.0, 1000.0, 0.0)
    assert proceeds == pytest.approx(900.0)
    assert pnl == pytest.approx(-100.0)
    assert pnl_pct == pytest.approx(-10.0)


def test_hyperliquid_fees_on_round_trip() -> None:
    fees = FeeConfig()  # HL defaults: taker entry, maker TP
    position = 10_000.0
    entry_fee = position * fees.entry_rate()
    proceeds, pnl, _pct, exit_fee = calc_exit_proceeds(
        "long", 100_000.0, 100_500.0, position, fees.exit_rate("take_profit_bb")
    )
    # +0.5% move, taker entry 0.045%, maker exit 0.015%
    assert entry_fee == pytest.approx(4.5)
    assert exit_fee == pytest.approx(1.5076, rel=1e-3)
    assert pnl == pytest.approx(48.49, rel=1e-2)


def test_backtest_long_trade() -> None:
    df = _make_signal_df(
        [
            {"long_signal": True, "close": 100.0},
            {"long_exit_tp": True, "close": 105.0, "high": 109.0, "bb_upper": 108.0},
        ]
    )
    warmup = _make_signal_df([{} for _ in range(60)])
    full_df = pd.concat([warmup, df], ignore_index=True)

    engine = BacktestEngine(
        StrategyConfig(),
        BacktestConfig(initial_balance=1000.0, position_size_pct=1.0, live_like=False),
        _zero_fees(),
    )
    engine.strategy = FixedStrategy(full_df)
    result = engine.run(full_df)

    assert result.total_trades == 1
    assert result.long_trades == 1
    assert result.trades[0].pnl_usd == pytest.approx(80.0)


def test_backtest_short_trade() -> None:
    df = _make_signal_df(
        [
            {"short_signal": True, "close": 100.0},
            {"short_exit_tp": True, "close": 95.0, "low": 91.0, "bb_lower": 92.0},
        ]
    )
    warmup = _make_signal_df([{} for _ in range(60)])
    full_df = pd.concat([warmup, df], ignore_index=True)

    engine = BacktestEngine(
        StrategyConfig(),
        BacktestConfig(initial_balance=1000.0, position_size_pct=1.0, live_like=False),
        _zero_fees(),
    )
    engine.strategy = FixedStrategy(full_df)
    result = engine.run(full_df)

    assert result.short_trades == 1
    assert result.trades[0].pnl_usd == pytest.approx(80.0)


def test_mark_to_market_equity_long() -> None:
    equity = mark_to_market_equity(50.0, "long", 100.0, 950.0, 110.0)
    assert equity == pytest.approx(1095.0)


def test_mark_to_market_equity_short() -> None:
    equity = mark_to_market_equity(50.0, "short", 100.0, 950.0, 90.0)
    assert equity == pytest.approx(1095.0)


def test_update_drawdown_tracks_peak_and_trough() -> None:
    peak, max_dd = update_drawdown(100.0, 100.0, 0.0)
    assert peak == pytest.approx(100.0)
    assert max_dd == pytest.approx(0.0)

    peak, max_dd = update_drawdown(80.0, peak, max_dd)
    assert peak == pytest.approx(100.0)
    assert max_dd == pytest.approx(20.0)

    peak, max_dd = update_drawdown(110.0, peak, max_dd)
    assert peak == pytest.approx(110.0)
    assert max_dd == pytest.approx(20.0)


def test_backtest_final_equity_includes_open_position() -> None:
    df = _make_signal_df(
        [
            {"long_signal": True, "close": 100.0},
            {"close": 110.0},
        ]
    )
    warmup = _make_signal_df([{} for _ in range(60)])
    full_df = pd.concat([warmup, df], ignore_index=True)

    engine = BacktestEngine(
        StrategyConfig(),
        BacktestConfig(initial_balance=1000.0, position_size_pct=0.95, live_like=False),
        _zero_fees(),
    )
    engine.strategy = FixedStrategy(full_df)
    result = engine.run(full_df)

    assert result.total_trades == 0
    assert result.open_position_at_end is True
    assert result.open_position is not None
    assert result.open_position.side == "long"
    assert result.open_position.entry_price == pytest.approx(100.0)
    assert result.open_position.mark_price == pytest.approx(110.0)
    assert result.open_position.unrealized_pnl_usd == pytest.approx(95.0)
    assert result.cash_balance == pytest.approx(50.0)
    assert result.final_balance == pytest.approx(1095.0)
    assert result.total_return_pct == pytest.approx(9.5)


def test_v2_partial_at_middle_then_trail_exit() -> None:
    df = _make_signal_df(
        [
            {"long_signal": True, "close": 100.0, "bb_middle": 105.0, "bb_upper": 110.0},
            {"long_exit_partial": True, "close": 105.0, "high": 105.5, "bb_middle": 105.0},
            {"long_exit_stop": True, "close": 99.0, "supertrend": 100.0},
        ]
    )
    warmup = _make_signal_df([{} for _ in range(60)])
    full_df = pd.concat([warmup, df], ignore_index=True)

    strategy_cfg = StrategyConfig(enhancements=v2_enhancement_config())
    engine = BacktestEngine(
        strategy_cfg,
        BacktestConfig(initial_balance=1000.0, position_size_pct=1.0, live_like=False),
        _zero_fees(),
    )
    engine.strategy = FixedStrategy(full_df)
    result = engine.run(full_df)

    assert result.total_trades == 2
    assert result.trades[0].exit_reason == "take_profit_bb_partial"
    assert result.trades[0].exit_price == pytest.approx(105.0)
    assert result.trades[1].exit_reason == "stop_supertrend"


def test_v2_entry_filter_keeps_ema_alignment_only_when_enabled() -> None:
    enh = v2_enhancement_config()
    assert enh.entry_filter is True
    assert enh.min_adx == 0.0
    assert enh.htf_filter is False


def test_long_has_priority_over_short_on_same_bar() -> None:
    df = _make_signal_df(
        [
            {"long_signal": True, "short_signal": True, "close": 100.0},
            {"long_exit_tp": True, "close": 105.0, "high": 109.0, "bb_upper": 108.0},
        ]
    )
    warmup = _make_signal_df([{} for _ in range(60)])
    full_df = pd.concat([warmup, df], ignore_index=True)

    engine = BacktestEngine(
        StrategyConfig(),
        BacktestConfig(initial_balance=1000.0, position_size_pct=1.0, live_like=False),
        _zero_fees(),
    )
    engine.strategy = FixedStrategy(full_df)
    result = engine.run(full_df)

    assert result.trades[0].side == "long"
