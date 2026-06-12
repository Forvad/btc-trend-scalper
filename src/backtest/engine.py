from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from src.backtest.intrabar_align import IntrabarAlignStats, align_htf_to_intrabar
from src.backtest.live_like import (
    bar_duration,
    entry_price_with_slippage,
    htf_bar_intrabar_fallback,
    simulate_htf_bar_intrabar,
)
from src.config import BacktestConfig, EnhancementConfig, LiveConfig, StrategyConfig
from src.exchange.fees import FeeConfig
from src.strategy import TrendScalperStrategy
from src.config import TrailSlConfig
from src.strategy.exits import smart_tp_valid
from src.strategy.trail_sl import (
    stop_hit,
    trail_sl_exit_reason,
    trail_sl_stop_price,
    trail_take_profit_bb,
    update_peak_profit_pct,
)

PositionSide = Literal["long", "short"]


@dataclass
class Trade:
    side: PositionSide
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    pnl_pct: float | None = None
    pnl_usd: float | None = None
    entry_fee_usd: float | None = None
    exit_fee_usd: float | None = None


@dataclass
class OpenPosition:
    side: PositionSide
    entry_time: pd.Timestamp
    entry_price: float
    size_usd: float
    mark_price: float
    unrealized_pnl_usd: float
    unrealized_pnl_pct: float
    entry_fee_usd: float


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    initial_balance: float = 10_000.0
    final_balance: float = 10_000.0
    cash_balance: float = 10_000.0
    open_position_at_end: bool = False
    open_position: OpenPosition | None = None
    total_return_pct: float = 0.0
    win_rate: float = 0.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0
    long_trades: int = 0
    short_trades: int = 0
    total_fees_usd: float = 0.0


@dataclass
class _Position:
    side: PositionSide
    entry_price: float
    entry_time: pd.Timestamp
    size_usd: float
    entry_fee_usd: float
    partial_taken: bool = False
    trailing_stop: float | None = None
    peak_profit_pct: float = 0.0


def calc_exit_proceeds(
    side: PositionSide,
    entry_price: float,
    exit_price: float,
    position_size_usd: float,
    exit_fee_rate: float,
) -> tuple[float, float, float, float]:
    """Возвращает (net_proceeds, net_pnl, pnl_pct, exit_fee_usd)."""
    if side == "long":
        gross_proceeds = position_size_usd * (exit_price / entry_price)
        pnl_pct = (exit_price - entry_price) / entry_price * 100
    else:
        gross_proceeds = position_size_usd * (2 - exit_price / entry_price)
        pnl_pct = (entry_price - exit_price) / entry_price * 100

    exit_fee_usd = gross_proceeds * exit_fee_rate
    net_proceeds = gross_proceeds - exit_fee_usd
    net_pnl = net_proceeds - position_size_usd
    return net_proceeds, net_pnl, pnl_pct, exit_fee_usd


def mark_to_market_equity(
    balance: float,
    side: PositionSide | None,
    entry_price: float,
    size_usd: float,
    close: float,
) -> float:
    """Свободный кэш + оценка открытой позиции по close (без комиссии выхода)."""
    if side is None or size_usd <= 0:
        return balance
    if side == "long":
        return balance + size_usd * (close / entry_price)
    return balance + size_usd * (2 - close / entry_price)


def update_drawdown(equity: float, peak: float, max_drawdown: float) -> tuple[float, float]:
    peak = max(peak, equity)
    drawdown = (peak - equity) / peak * 100 if peak else 0.0
    return peak, max(max_drawdown, drawdown)


def open_position_snapshot(pos: _Position, mark_price: float) -> OpenPosition:
    if pos.side == "long":
        unrealized_pct = (mark_price - pos.entry_price) / pos.entry_price * 100
        mtm = pos.size_usd * (mark_price / pos.entry_price)
    else:
        unrealized_pct = (pos.entry_price - mark_price) / pos.entry_price * 100
        mtm = pos.size_usd * (2 - mark_price / pos.entry_price)
    return OpenPosition(
        side=pos.side,
        entry_time=pos.entry_time,
        entry_price=pos.entry_price,
        size_usd=pos.size_usd,
        mark_price=mark_price,
        unrealized_pnl_usd=mtm - pos.size_usd,
        unrealized_pnl_pct=unrealized_pct,
        entry_fee_usd=pos.entry_fee_usd,
    )


def build_backtest_result(
    *,
    trades: list[Trade],
    initial_balance: float,
    balance: float,
    pos: _Position | None,
    last_mark: float,
    total_fees: float,
    max_drawdown: float,
) -> BacktestResult:
    final_equity = mark_to_market_equity(
        balance,
        pos.side if pos else None,
        pos.entry_price if pos else 0.0,
        pos.size_usd if pos else 0.0,
        last_mark,
    )
    wins = sum(1 for t in trades if t.pnl_usd and t.pnl_usd > 0)
    total_trades = len(trades)
    win_rate = (wins / total_trades * 100) if total_trades else 0.0
    total_return = (final_equity - initial_balance) / initial_balance * 100
    open_pos = open_position_snapshot(pos, last_mark) if pos else None

    return BacktestResult(
        trades=trades,
        initial_balance=initial_balance,
        final_balance=final_equity,
        cash_balance=balance,
        open_position_at_end=pos is not None,
        open_position=open_pos,
        total_return_pct=total_return,
        win_rate=win_rate,
        max_drawdown_pct=max_drawdown,
        total_trades=total_trades,
        long_trades=sum(1 for t in trades if t.side == "long"),
        short_trades=sum(1 for t in trades if t.side == "short"),
        total_fees_usd=total_fees,
    )


def update_trend_trailing(enh: EnhancementConfig, pos: _Position, row: pd.Series) -> None:
    if not enh.enabled or enh.trailing_activate_pct <= 0 or pos.partial_taken:
        return

    activate = enh.trailing_activate_pct / 100
    if pos.side == "long" and float(row["high"]) >= pos.entry_price * (1 + activate):
        pos.trailing_stop = pos.entry_price
    elif pos.side == "short" and float(row["low"]) <= pos.entry_price * (1 - activate):
        pos.trailing_stop = pos.entry_price


def try_trend_partial_tp(
    enh: EnhancementConfig,
    fees: FeeConfig,
    pos: _Position,
    row: pd.Series,
    balance: float,
    total_fees: float,
) -> tuple[Trade, float, float, _Position | None] | None:
    if not enh.enabled or not enh.exit_partial_trail or pos.partial_taken or enh.partial_tp_pct <= 0:
        return None

    if enh.partial_at_middle:
        if pos.side == "long":
            if not row.get("long_exit_partial", False):
                return None
            tp_price = float(row["bb_middle"])
        else:
            if not row.get("short_exit_partial", False):
                return None
            tp_price = float(row["bb_middle"])
    elif pos.side == "long":
        if not row["long_exit_tp"]:
            return None
        tp_price = float(row["bb_upper"])
    else:
        if not row["short_exit_tp"]:
            return None
        tp_price = float(row["bb_lower"])

    if enh.smart_tp and not smart_tp_valid(pos.side, pos.entry_price, tp_price, enh.min_potential_pct):
        return None

    partial_size = pos.size_usd * enh.partial_tp_pct
    exit_fee_rate = fees.exit_rate("take_profit_bb")
    net_proceeds, net_pnl, pnl_pct, exit_fee = calc_exit_proceeds(
        pos.side, pos.entry_price, tp_price, partial_size, exit_fee_rate
    )

    trade = Trade(
        side=pos.side,
        entry_time=pos.entry_time,
        entry_price=pos.entry_price,
        exit_time=row["timestamp"],
        exit_price=tp_price,
        exit_reason="take_profit_bb_partial",
        pnl_pct=pnl_pct,
        pnl_usd=net_pnl,
        entry_fee_usd=pos.entry_fee_usd * enh.partial_tp_pct,
        exit_fee_usd=exit_fee,
    )

    balance += net_proceeds
    total_fees += exit_fee
    pos.size_usd -= partial_size
    pos.partial_taken = True

    if enh.trail_breakeven_after_partial:
        pos.trailing_stop = pos.entry_price

    if pos.size_usd < 1.0:
        return trade, balance, total_fees, None

    return trade, balance, total_fees, pos


def try_trend_full_exit(
    enh: EnhancementConfig,
    fees: FeeConfig,
    pos: _Position,
    row: pd.Series,
    balance: float,
    total_fees: float,
    *,
    trail_sl: TrailSlConfig | None = None,
) -> tuple[Trade, float, float] | None:
    exit_price = None
    exit_reason = None
    trail_cfg = trail_sl or TrailSlConfig()
    use_trail_sl = trail_cfg.enabled
    use_partial_trail = enh.enabled and enh.exit_partial_trail and not use_trail_sl
    bar_high = float(row["high"])
    bar_low = float(row["low"])
    supertrend = float(row["supertrend"])

    if use_trail_sl:
        pos.peak_profit_pct = update_peak_profit_pct(
            pos.side, pos.entry_price, pos.peak_profit_pct, bar_high, bar_low
        )
        tp_fill = trail_take_profit_bb(
            pos.side,
            float(row["bb_upper"]),
            float(row["bb_lower"]),
            bar_high,
            bar_low,
            trail_cfg,
        )
        if tp_fill is not None:
            exit_price, exit_reason = tp_fill
        else:
            stop_level = trail_sl_stop_price(
                pos.side, pos.entry_price, pos.peak_profit_pct, supertrend, trail_cfg
            )
            if stop_hit(pos.side, stop_level, bar_high, bar_low):
                exit_price = stop_level
                exit_reason = trail_sl_exit_reason(pos.peak_profit_pct, trail_cfg)
    elif pos.side == "long":
        stop_level = supertrend
        if pos.trailing_stop is not None:
            stop_level = max(stop_level, pos.trailing_stop)

        if not use_partial_trail:
            tp = float(row["bb_upper"])
            if bar_high >= tp:
                if enh.enabled and enh.smart_tp and not pos.partial_taken:
                    if smart_tp_valid(pos.side, pos.entry_price, tp, enh.min_potential_pct):
                        exit_price, exit_reason = tp, "take_profit_bb"
                else:
                    exit_price, exit_reason = tp, "take_profit_bb"

        if exit_price is None and bar_low <= stop_level:
            exit_price, exit_reason = stop_level, "stop_supertrend"
    else:
        stop_level = supertrend
        if pos.trailing_stop is not None:
            stop_level = min(stop_level, pos.trailing_stop)

        if not use_partial_trail:
            tp = float(row["bb_lower"])
            if bar_low <= tp:
                if enh.enabled and enh.smart_tp and not pos.partial_taken:
                    if smart_tp_valid(pos.side, pos.entry_price, tp, enh.min_potential_pct):
                        exit_price, exit_reason = tp, "take_profit_bb"
                else:
                    exit_price, exit_reason = tp, "take_profit_bb"

        if exit_price is None and bar_high >= stop_level:
            exit_price, exit_reason = stop_level, "stop_supertrend"

    if exit_price is None:
        return None

    exit_fee_rate = fees.exit_rate(exit_reason)
    net_proceeds, net_pnl, pnl_pct, exit_fee = calc_exit_proceeds(
        pos.side, pos.entry_price, exit_price, pos.size_usd, exit_fee_rate
    )

    entry_fee_share = pos.entry_fee_usd
    if pos.partial_taken:
        entry_fee_share = pos.entry_fee_usd * (1 - enh.partial_tp_pct)

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


class BacktestEngine:
    def __init__(
        self,
        strategy_config: StrategyConfig,
        backtest_config: BacktestConfig,
        fee_config: FeeConfig | None = None,
        *,
        live_config: LiveConfig | None = None,
    ) -> None:
        self.strategy = TrendScalperStrategy(strategy_config)
        self.config = backtest_config
        self.fees = fee_config or FeeConfig()
        self.enh = strategy_config.enhancements
        self.live = live_config or LiveConfig()

    def run(
        self,
        df: pd.DataFrame,
        htf_df: pd.DataFrame | None = None,
        *,
        timeframe: str = "1h",
        intrabar_df: pd.DataFrame | None = None,
    ) -> BacktestResult:
        if self.config.live_like:
            df, intrabar_df, _ = self._align_intrabar(df, intrabar_df, timeframe)
            return self._run_live_like(df, htf_df, timeframe=timeframe, intrabar_df=intrabar_df)
        return self._run_bar_close(df, htf_df)

    def _align_intrabar(
        self,
        df: pd.DataFrame,
        intrabar_df: pd.DataFrame | None,
        timeframe: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame | None, IntrabarAlignStats | None]:
        if intrabar_df is None or intrabar_df.empty:
            return df, intrabar_df, None
        aligned_htf, aligned_ib, stats = align_htf_to_intrabar(
            df,
            intrabar_df,
            htf_timeframe=timeframe,
            sub_timeframe=self.config.intrabar_timeframe,
        )
        return aligned_htf, aligned_ib, stats

    def _run_bar_close(self, df: pd.DataFrame, htf_df: pd.DataFrame | None = None) -> BacktestResult:
        data = self.strategy.generate_signals(df, htf_df)
        balance = self.config.initial_balance
        peak_balance = balance
        max_drawdown = 0.0
        total_fees = 0.0
        trades: list[Trade] = []
        pos: _Position | None = None
        entry_fee_rate = self.fees.entry_rate()

        warmup = max(
            self.strategy.config.ema_slow,
            self.strategy.config.bollinger.period,
            self.strategy.config.volume_sma_period,
            self.strategy.config.supertrend.period,
        ) + 5

        for i in range(warmup, len(data)):
            row = data.iloc[i]
            close = float(row["close"])

            if pos is None:
                if row["long_signal"]:
                    pos = self._open_position("long", row, balance, entry_fee_rate)
                    balance -= pos.size_usd + pos.entry_fee_usd
                    total_fees += pos.entry_fee_usd
                elif row["short_signal"]:
                    pos = self._open_position("short", row, balance, entry_fee_rate)
                    balance -= pos.size_usd + pos.entry_fee_usd
                    total_fees += pos.entry_fee_usd
            else:
                pos, balance, total_fees, new_trades = self._manage_position(
                    pos, row, balance, total_fees
                )
                trades.extend(new_trades)

            equity = self._equity(balance, pos, close)
            peak_balance, max_drawdown = update_drawdown(equity, peak_balance, max_drawdown)

        last_close = float(data.iloc[-1]["close"])
        return build_backtest_result(
            trades=trades,
            initial_balance=self.config.initial_balance,
            balance=balance,
            pos=pos,
            last_mark=last_close,
            total_fees=total_fees,
            max_drawdown=max_drawdown,
        )

    def _equity(self, balance: float, pos: _Position | None, close: float) -> float:
        if pos is None:
            return balance
        return mark_to_market_equity(balance, pos.side, pos.entry_price, pos.size_usd, close)

    def _open_position(
        self,
        side: PositionSide,
        row: pd.Series,
        balance: float,
        entry_fee_rate: float,
    ) -> _Position:
        size = balance * self.config.position_size_pct
        return _Position(
            side=side,
            entry_price=float(row["close"]),
            entry_time=row["timestamp"],
            size_usd=size,
            entry_fee_usd=size * entry_fee_rate,
        )

    def _manage_position(
        self,
        pos: _Position,
        row: pd.Series,
        balance: float,
        total_fees: float,
    ) -> tuple[_Position | None, float, float, list[Trade]]:
        trades: list[Trade] = []
        trail_cfg = self.strategy.config.trail_sl
        if not trail_cfg.enabled:
            update_trend_trailing(self.enh, pos, row)

        partial_trade = None
        if not trail_cfg.enabled:
            partial_trade = try_trend_partial_tp(self.enh, self.fees, pos, row, balance, total_fees)
        if partial_trade:
            trade, balance, total_fees, pos = partial_trade
            trades.append(trade)
            if pos is None:
                return None, balance, total_fees, trades

        exit_trade = try_trend_full_exit(
            self.enh, self.fees, pos, row, balance, total_fees, trail_sl=trail_cfg
        )
        if exit_trade:
            trade, balance, total_fees = exit_trade
            trades.append(trade)
            return None, balance, total_fees, trades

        return pos, balance, total_fees, trades

    def _run_live_like(
        self,
        raw_df: pd.DataFrame,
        htf_df: pd.DataFrame | None,
        *,
        timeframe: str,
        intrabar_df: pd.DataFrame | None,
    ) -> BacktestResult:
        data = self.strategy.generate_signals(raw_df, htf_df)
        balance = self.config.initial_balance
        peak_balance = balance
        max_drawdown = 0.0
        total_fees = 0.0
        trades: list[Trade] = []
        pos: _Position | None = None
        entry_fee_rate = self.fees.entry_rate()
        bracket_sl: float | None = None
        bracket_tp: float | None = None

        warmup = max(
            self.strategy.config.ema_slow,
            self.strategy.config.bollinger.period,
            self.strategy.config.volume_sma_period,
            self.strategy.config.supertrend.period,
        ) + 5

        bar_delta = bar_duration(timeframe)
        sub_df = (
            intrabar_df.sort_values("timestamp").reset_index(drop=True)
            if intrabar_df is not None and len(intrabar_df) > 0
            else None
        )

        for i in range(warmup, len(raw_df)):
            row = data.iloc[i]
            bar_start = raw_df.iloc[i]["timestamp"]
            bar_end = bar_start + bar_delta
            close = float(row["close"])

            sub_bars = pd.DataFrame()
            if sub_df is not None:
                sub_bars = sub_df[
                    (sub_df["timestamp"] >= bar_start) & (sub_df["timestamp"] < bar_end)
                ]

            if sub_bars.empty:
                if pos is None:
                    if row["long_signal"]:
                        entry = entry_price_with_slippage("long", close, self.live.slippage)
                        pos = self._open_position_at("long", bar_start, entry, balance, entry_fee_rate)
                        balance -= pos.size_usd + pos.entry_fee_usd
                        total_fees += pos.entry_fee_usd
                        bracket_sl = bracket_tp = None
                    elif row["short_signal"]:
                        entry = entry_price_with_slippage("short", close, self.live.slippage)
                        pos = self._open_position_at("short", bar_start, entry, balance, entry_fee_rate)
                        balance -= pos.size_usd + pos.entry_fee_usd
                        total_fees += pos.entry_fee_usd
                        bracket_sl = bracket_tp = None
                else:
                    pos, balance, total_fees, new_trades = self._manage_position(
                        pos, row, balance, total_fees
                    )
                    trades.extend(new_trades)
                    if pos is None:
                        bracket_sl = bracket_tp = None
            else:
                pos_side = pos.side if pos else None
                trail_cfg = self.strategy.config.trail_sl
                pos_side, bracket_sl, bracket_tp, entry_event, exit_event, peak = (
                    simulate_htf_bar_intrabar(
                        self.strategy,
                        raw_df,
                        i,
                        sub_bars,
                        htf_df,
                        pos_side=pos_side,
                        bracket_sl=bracket_sl,
                        bracket_tp=bracket_tp,
                        live=self.live,
                        entry_price=pos.entry_price if pos else None,
                        peak_profit_pct=pos.peak_profit_pct if pos else 0.0,
                        trail_sl=trail_cfg,
                    )
                )
                if pos is not None:
                    pos.peak_profit_pct = peak

                if entry_event and pos is None:
                    pos = self._open_position_at(
                        entry_event["side"],
                        entry_event["time"],
                        entry_event["price"],
                        balance,
                        entry_fee_rate,
                    )
                    pos.peak_profit_pct = 0.0
                    balance -= pos.size_usd + pos.entry_fee_usd
                    total_fees += pos.entry_fee_usd

                if exit_event and pos is not None:
                    trade, balance, total_fees = self._finalize_exit(
                        pos,
                        exit_event["price"],
                        exit_event["reason"],
                        exit_event["time"],
                        balance,
                        total_fees,
                    )
                    trades.append(trade)
                    pos = None
                    bracket_sl = bracket_tp = None

                if pos is not None and exit_event is None:
                    fallback = htf_bar_intrabar_fallback(
                        pos.side,
                        row,
                        bracket_sl=bracket_sl,
                        bracket_tp=bracket_tp,
                        trail_sl=trail_cfg,
                        entry_price=pos.entry_price,
                        peak_profit_pct=pos.peak_profit_pct,
                    )
                    if fallback:
                        exit_price, reason = fallback
                        trade, balance, total_fees = self._finalize_exit(
                            pos,
                            exit_price,
                            reason,
                            bar_end - pd.Timedelta(seconds=1),
                            balance,
                            total_fees,
                        )
                        trades.append(trade)
                        pos = None
                        bracket_sl = bracket_tp = None

            equity = self._equity(balance, pos, close)
            peak_balance, max_drawdown = update_drawdown(equity, peak_balance, max_drawdown)

        last_close = float(raw_df.iloc[-1]["close"])
        return build_backtest_result(
            trades=trades,
            initial_balance=self.config.initial_balance,
            balance=balance,
            pos=pos,
            last_mark=last_close,
            total_fees=total_fees,
            max_drawdown=max_drawdown,
        )

    def _open_position_at(
        self,
        side: PositionSide,
        entry_time: pd.Timestamp,
        entry_price: float,
        balance: float,
        entry_fee_rate: float,
    ) -> _Position:
        size = balance * self.config.position_size_pct
        return _Position(
            side=side,
            entry_price=entry_price,
            entry_time=entry_time,
            size_usd=size,
            entry_fee_usd=size * entry_fee_rate,
        )

    def _finalize_exit(
        self,
        pos: _Position,
        exit_price: float,
        exit_reason: str,
        exit_time: pd.Timestamp,
        balance: float,
        total_fees: float,
    ) -> tuple[Trade, float, float]:
        exit_fee_rate = self.fees.exit_rate(exit_reason)
        net_proceeds, net_pnl, pnl_pct, exit_fee = calc_exit_proceeds(
            pos.side, pos.entry_price, exit_price, pos.size_usd, exit_fee_rate
        )
        entry_fee_share = pos.entry_fee_usd
        if pos.partial_taken:
            entry_fee_share = pos.entry_fee_usd * (1 - self.enh.partial_tp_pct)

        trade = Trade(
            side=pos.side,
            entry_time=pos.entry_time,
            entry_price=pos.entry_price,
            exit_time=exit_time,
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
