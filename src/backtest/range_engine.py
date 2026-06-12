from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from src.backtest.engine import (
    BacktestResult,
    Trade,
    _Position,
    build_backtest_result,
    calc_exit_proceeds,
    mark_to_market_equity,
    update_drawdown,
)
from src.config import BacktestConfig, RangeStrategyConfig
from src.exchange.fees import FeeConfig
from src.strategy.range_reversion import RangeReversionStrategy, compute_stop_price

PositionSide = Literal["long", "short"]


@dataclass
class _RangePosition(_Position):
    stop_price: float = 0.0
    partial_taken: bool = False


class RangeBacktestEngine:
    def __init__(
        self,
        strategy_config: RangeStrategyConfig,
        backtest_config: BacktestConfig,
        fee_config: FeeConfig | None = None,
    ) -> None:
        self.strategy = RangeReversionStrategy(strategy_config)
        self.config = strategy_config
        self.backtest = backtest_config
        self.fees = fee_config or FeeConfig()

    def run(self, df: pd.DataFrame) -> BacktestResult:
        data = self.strategy.generate_signals(df)
        balance = self.backtest.initial_balance
        peak_balance = balance
        max_drawdown = 0.0
        total_fees = 0.0
        trades: list[Trade] = []
        pos: _RangePosition | None = None
        entry_fee_rate = self.fees.entry_rate()
        cooldown_until = 0

        warmup = max(
            self.config.bollinger.period,
            self.config.rsi.period,
            self.config.adx.period,
            self.config.swing_lookback,
        ) + 5

        for i in range(warmup, len(data)):
            row = data.iloc[i]
            close = float(row["close"])

            if pos is None:
                if i >= cooldown_until:
                    if row["long_signal"]:
                        window = data.iloc[max(0, i - self.config.swing_lookback) : i + 1]
                        stop = compute_stop_price("long", close, window, self.config)
                        pos = self._open_position("long", row, balance, entry_fee_rate, stop)
                        balance -= pos.size_usd + pos.entry_fee_usd
                        total_fees += pos.entry_fee_usd
                    elif row["short_signal"]:
                        window = data.iloc[max(0, i - self.config.swing_lookback) : i + 1]
                        stop = compute_stop_price("short", close, window, self.config)
                        pos = self._open_position("short", row, balance, entry_fee_rate, stop)
                        balance -= pos.size_usd + pos.entry_fee_usd
                        total_fees += pos.entry_fee_usd
            else:
                pos, balance, total_fees, new_trades, closed = self._manage_position(
                    pos, row, balance, total_fees
                )
                trades.extend(new_trades)
                if closed:
                    pos = None
                    cooldown_until = i + self.config.cooldown_bars

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

    def _equity(self, balance: float, pos: _RangePosition | None, close: float) -> float:
        if pos is None:
            return balance
        return mark_to_market_equity(balance, pos.side, pos.entry_price, pos.size_usd, close)

    def _open_position(
        self,
        side: PositionSide,
        row: pd.Series,
        balance: float,
        entry_fee_rate: float,
        stop_price: float,
    ) -> _RangePosition:
        size = balance * self.backtest.position_size_pct
        return _RangePosition(
            side=side,
            entry_price=float(row["close"]),
            entry_time=row["timestamp"],
            size_usd=size,
            entry_fee_usd=size * entry_fee_rate,
            stop_price=stop_price,
        )

    def _manage_position(
        self,
        pos: _RangePosition,
        row: pd.Series,
        balance: float,
        total_fees: float,
    ) -> tuple[_RangePosition | None, float, float, list[Trade], bool]:
        trades: list[Trade] = []

        if (
            self.config.partial_at_middle_pct > 0
            and not pos.partial_taken
        ):
            partial = self._try_partial_middle(pos, row, balance, total_fees)
            if partial:
                trade, balance, total_fees, pos = partial
                trades.append(trade)
                if pos is None:
                    return None, balance, total_fees, trades, True

        exit_trade = self._try_full_exit(pos, row, balance, total_fees)
        if exit_trade:
            trade, balance, total_fees = exit_trade
            trades.append(trade)
            return None, balance, total_fees, trades, True

        return pos, balance, total_fees, trades, False

    def _try_partial_middle(
        self,
        pos: _RangePosition,
        row: pd.Series,
        balance: float,
        total_fees: float,
    ) -> tuple[Trade, float, float, _RangePosition | None] | None:
        if pos.side == "long":
            if not row["long_exit_tp_middle"]:
                return None
            tp_price = float(row["bb_middle"])
        else:
            if not row["short_exit_tp_middle"]:
                return None
            tp_price = float(row["bb_middle"])

        partial_size = pos.size_usd * self.config.partial_at_middle_pct
        exit_fee_rate = self.fees.exit_rate("take_profit_bb")
        net_proceeds, net_pnl, pnl_pct, exit_fee = calc_exit_proceeds(
            pos.side, pos.entry_price, tp_price, partial_size, exit_fee_rate
        )

        trade = Trade(
            side=pos.side,
            entry_time=pos.entry_time,
            entry_price=pos.entry_price,
            exit_time=row["timestamp"],
            exit_price=tp_price,
            exit_reason="take_profit_middle_partial",
            pnl_pct=pnl_pct,
            pnl_usd=net_pnl,
            entry_fee_usd=pos.entry_fee_usd * self.config.partial_at_middle_pct,
            exit_fee_usd=exit_fee,
        )
        balance += net_proceeds
        total_fees += exit_fee
        pos.size_usd -= partial_size
        pos.partial_taken = True
        pos.stop_price = pos.entry_price

        if pos.size_usd < 1.0:
            return trade, balance, total_fees, None
        return trade, balance, total_fees, pos

    def _resolve_tp(
        self,
        pos: _RangePosition,
        row: pd.Series,
        *,
        skip_middle: bool = False,
    ) -> tuple[float, str] | None:
        tp_mode = self.config.take_profit

        if pos.side == "long":
            if (
                not skip_middle
                and tp_mode in ("middle", "either", "middle_first")
                and row["long_exit_tp_middle"]
            ):
                return float(row["bb_middle"]), "take_profit_middle"
            if tp_mode in ("opposite", "either", "middle_first") and row["long_exit_tp_opposite"]:
                return float(row["bb_upper"]), "take_profit_opposite"
            if float(row["close"]) <= pos.stop_price:
                return pos.stop_price, "stop_loss"
        else:
            if (
                not skip_middle
                and tp_mode in ("middle", "either", "middle_first")
                and row["short_exit_tp_middle"]
            ):
                return float(row["bb_middle"]), "take_profit_middle"
            if tp_mode in ("opposite", "either", "middle_first") and row["short_exit_tp_opposite"]:
                return float(row["bb_lower"]), "take_profit_opposite"
            if float(row["close"]) >= pos.stop_price:
                return pos.stop_price, "stop_loss"

        return None

    def _try_full_exit(
        self,
        pos: _RangePosition,
        row: pd.Series,
        balance: float,
        total_fees: float,
    ) -> tuple[Trade, float, float] | None:
        if row["adx_emergency"]:
            exit_price = float(row["close"])
            exit_reason = "emergency_adx"
        else:
            resolved = self._resolve_tp(pos, row, skip_middle=pos.partial_taken)
            if resolved is None:
                return None
            exit_price, exit_reason = resolved

        is_tp = exit_reason.startswith("take_profit")
        fee_key = "take_profit_bb" if is_tp else "stop_supertrend"
        if exit_reason == "emergency_adx":
            fee_key = "stop_supertrend"

        exit_fee_rate = self.fees.exit_rate(fee_key)
        net_proceeds, net_pnl, pnl_pct, exit_fee = calc_exit_proceeds(
            pos.side, pos.entry_price, exit_price, pos.size_usd, exit_fee_rate
        )

        entry_fee_share = 0.0 if pos.partial_taken else pos.entry_fee_usd
        if pos.partial_taken:
            entry_fee_share = pos.entry_fee_usd * (1 - self.config.partial_at_middle_pct)

        trade = Trade(
            side=pos.side,
            entry_time=pos.entry_time,
            entry_price=pos.entry_price,
            exit_time=row["timestamp"],
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl_pct=pnl_pct,
            pnl_usd=net_pnl,
            entry_fee_usd=entry_fee_share,
            exit_fee_usd=exit_fee,
        )
        balance += net_proceeds
        total_fees += exit_fee
        return trade, balance, total_fees
