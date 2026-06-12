from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from src.backtest.engine import (
    BacktestResult,
    Trade,
    _Position,
    build_backtest_result,
    mark_to_market_equity,
    try_trend_full_exit,
    try_trend_partial_tp,
    update_drawdown,
    update_trend_trailing,
)
from src.backtest.range_engine import RangeBacktestEngine, _RangePosition
from src.config import AppConfig, BacktestConfig, HybridConfig
from src.exchange.fees import FeeConfig
from src.strategy.range_reversion import RangeReversionStrategy, compute_stop_price
from src.strategy.trend_scalper import TrendScalperStrategy

PositionSide = Literal["long", "short"]
BotSource = Literal["trend", "range"]


@dataclass
class _HybridPosition(_Position):
    source: BotSource = "trend"
    stop_price: float = 0.0
    partial_taken: bool = False
    trailing_stop: float | None = None


def merge_signals(df: pd.DataFrame, config: AppConfig, htf_df: pd.DataFrame | None = None) -> pd.DataFrame:
    trend = TrendScalperStrategy(config.strategy).generate_signals(df, htf_df)
    rng = RangeReversionStrategy(config.range_strategy).generate_signals(df)

    merged = trend.copy()
    for col in rng.columns:
        if col in ("timestamp", "open", "high", "low", "close", "volume"):
            continue
        merged[f"rng_{col}"] = rng[col].values

    merged["adx"] = rng["adx"].values
    return merged


def analyze_signal_overlap(data: pd.DataFrame, hybrid: HybridConfig) -> dict:
    adx = data["adx"]
    trend_regime = adx >= hybrid.trend_adx_min
    range_regime = adx <= hybrid.range_adx_max
    dead_zone = ~(trend_regime | range_regime)

    t_long = data["long_signal"].fillna(False)
    t_short = data["short_signal"].fillna(False)
    r_long = data["rng_long_signal"].fillna(False)
    r_short = data["rng_short_signal"].fillna(False)

    both_long = t_long & r_long
    both_short = t_short & r_short
    conflict = (t_long & r_short) | (t_short & r_long)

    return {
        "trend_long": int(t_long.sum()),
        "trend_short": int(t_short.sum()),
        "range_long": int(r_long.sum()),
        "range_short": int(r_short.sum()),
        "both_long": int(both_long.sum()),
        "both_short": int(both_short.sum()),
        "conflict": int(conflict.sum()),
        "dead_zone_bars": int(dead_zone.sum()),
        "trend_regime_bars": int(trend_regime.sum()),
        "range_regime_bars": int(range_regime.sum()),
    }


class HybridBacktestEngine:
    """Одна позиция: trend при ADX>=trend_adx_min, range при ADX<=range_adx_max."""

    def __init__(self, config: AppConfig, fee_config: FeeConfig | None = None) -> None:
        self.app = config
        self.hybrid = config.hybrid
        self.backtest = config.backtest
        self.fees = fee_config or config.exchange.fees
        self.trend_enh = config.strategy.enhancements
        self.range_cfg = config.range_strategy
        self._range_engine = RangeBacktestEngine(
            config.range_strategy, config.backtest, self.fees
        )

    def run(self, df: pd.DataFrame, htf_df: pd.DataFrame | None = None) -> BacktestResult:
        data = merge_signals(df, self.app, htf_df)
        balance = self.backtest.initial_balance
        peak_balance = balance
        max_drawdown = 0.0
        total_fees = 0.0
        trades: list[Trade] = []
        pos: _HybridPosition | None = None
        cooldown_until = 0
        entry_fee_rate = self.fees.entry_rate()

        warmup = max(
            self.app.strategy.ema_slow,
            self.app.strategy.bollinger.period,
            self.range_cfg.bollinger.period,
            self.range_cfg.adx.period,
        ) + 5

        for i in range(warmup, len(data)):
            row = data.iloc[i]
            close = float(row["close"])
            adx = float(row["adx"])

            if pos is None:
                if i >= cooldown_until:
                    opened = False
                    if row["long_signal"] and self.hybrid.trend_regime(adx):
                        pos = self._open("long", "trend", row, balance, entry_fee_rate, data, i)
                        opened = True
                    elif row["short_signal"] and self.hybrid.trend_regime(adx):
                        pos = self._open("short", "trend", row, balance, entry_fee_rate, data, i)
                        opened = True
                    elif not opened and self.hybrid.range_regime(adx):
                        if row["rng_long_signal"]:
                            pos = self._open("long", "range", row, balance, entry_fee_rate, data, i)
                            opened = True
                        elif row["rng_short_signal"]:
                            pos = self._open("short", "range", row, balance, entry_fee_rate, data, i)
                            opened = True

                    if opened and pos is not None:
                        balance -= pos.size_usd + pos.entry_fee_usd
                        total_fees += pos.entry_fee_usd
            else:
                pos, balance, total_fees, new_trades, closed = self._manage(
                    pos, row, balance, total_fees
                )
                trades.extend(new_trades)
                if closed:
                    pos = None
                    if new_trades and new_trades[-1].exit_reason in (
                        "emergency_adx",
                        "stop_loss",
                        "stop_supertrend",
                    ):
                        cooldown_until = i + self.range_cfg.cooldown_bars

            equity = self._equity(balance, pos, close)
            peak_balance, max_drawdown = update_drawdown(equity, peak_balance, max_drawdown)

        last_close = float(data.iloc[-1]["close"])
        return build_backtest_result(
            trades=trades,
            initial_balance=self.backtest.initial_balance,
            balance=balance,
            pos=pos,
            last_mark=last_close,
            total_fees=total_fees,
            max_drawdown=max_drawdown,
        )

    def _open(
        self,
        side: PositionSide,
        source: BotSource,
        row: pd.Series,
        balance: float,
        entry_fee_rate: float,
        data: pd.DataFrame,
        index: int,
    ) -> _HybridPosition:
        size = balance * self.backtest.position_size_pct
        stop = 0.0
        if source == "range":
            window = data.iloc[max(0, index - self.range_cfg.swing_lookback) : index + 1]
            stop = compute_stop_price(side, float(row["close"]), window, self.range_cfg)
        return _HybridPosition(
            side=side,
            source=source,
            entry_price=float(row["close"]),
            entry_time=row["timestamp"],
            size_usd=size,
            entry_fee_usd=size * entry_fee_rate,
            stop_price=stop,
        )

    def _equity(self, balance: float, pos: _HybridPosition | None, close: float) -> float:
        if pos is None:
            return balance
        return mark_to_market_equity(balance, pos.side, pos.entry_price, pos.size_usd, close)

    def _range_row(self, row: pd.Series) -> pd.Series:
        mapped = row.copy()
        for key in (
            "adx_emergency",
            "long_exit_tp_opposite",
            "long_exit_tp_middle",
            "short_exit_tp_opposite",
            "short_exit_tp_middle",
            "bb_upper",
            "bb_middle",
            "bb_lower",
        ):
            rng_key = f"rng_{key}"
            if rng_key in row.index:
                mapped[key] = row[rng_key]
        return mapped

    def _manage(
        self,
        pos: _HybridPosition,
        row: pd.Series,
        balance: float,
        total_fees: float,
    ) -> tuple[_HybridPosition | None, float, float, list[Trade], bool]:
        if pos.source == "range":
            range_row = self._range_row(row)
            rpos = _RangePosition(
                side=pos.side,
                entry_price=pos.entry_price,
                entry_time=pos.entry_time,
                size_usd=pos.size_usd,
                entry_fee_usd=pos.entry_fee_usd,
                stop_price=pos.stop_price,
                partial_taken=pos.partial_taken,
            )
            rpos, balance, total_fees, trades, closed = self._range_engine._manage_position(
                rpos, range_row, balance, total_fees
            )
            if rpos is None:
                return None, balance, total_fees, trades, closed
            pos.size_usd = rpos.size_usd
            pos.partial_taken = rpos.partial_taken
            pos.stop_price = rpos.stop_price
            return pos, balance, total_fees, trades, False

        trades: list[Trade] = []
        update_trend_trailing(self.trend_enh, pos, row)

        partial_trade = try_trend_partial_tp(
            self.trend_enh, self.fees, pos, row, balance, total_fees
        )
        if partial_trade:
            trade, balance, total_fees, pos = partial_trade
            trades.append(trade)
            if pos is None:
                return None, balance, total_fees, trades, True

        exit_trade = try_trend_full_exit(
            self.trend_enh,
            self.fees,
            pos,
            row,
            balance,
            total_fees,
            trail_sl=self.app.strategy.trail_sl,
        )
        if exit_trade:
            trade, balance, total_fees = exit_trade
            trades.append(trade)
            return None, balance, total_fees, trades, True
        return pos, balance, total_fees, trades, False
