#!/usr/bin/env python3
"""Сравнение бэктеста: trail SL vs bracket SL+TP на одном периоде."""

from __future__ import annotations

import copy
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tabulate import tabulate

from src.backtest import BacktestEngine, BacktestResult
from src.backtest.intrabar_align import (
    IntrabarAlignStats,
    fetch_intrabar_for_htf,
    prepare_live_like_data,
)
from src.config import load_config
from src.data import fetch_ohlcv


@dataclass
class VariantSummary:
    name: str
    days: int
    range_start: str
    range_end: str
    return_pct: float
    final_balance: float
    trades: int
    win_rate: float
    max_dd_pct: float
    fees_usd: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    exit_reasons: dict[str, int]
    long_trades: int
    short_trades: int


def _summarize(name: str, result: BacktestResult, align: IntrabarAlignStats) -> VariantSummary:
    wins = [t for t in result.trades if t.pnl_usd > 0]
    losses = [t for t in result.trades if t.pnl_usd <= 0]
    gross_win = sum(t.pnl_usd for t in wins)
    gross_loss = abs(sum(t.pnl_usd for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    return VariantSummary(
        name=name,
        days=align.days,
        range_start=str(align.range_start),
        range_end=str(align.range_end),
        return_pct=result.total_return_pct,
        final_balance=result.final_balance,
        trades=result.total_trades,
        win_rate=result.win_rate,
        max_dd_pct=result.max_drawdown_pct,
        fees_usd=result.total_fees_usd,
        avg_win_pct=sum(t.pnl_pct for t in wins) / len(wins) if wins else 0.0,
        avg_loss_pct=sum(t.pnl_pct for t in losses) / len(losses) if losses else 0.0,
        profit_factor=pf,
        exit_reasons=dict(Counter(t.exit_reason for t in result.trades)),
        long_trades=result.long_trades,
        short_trades=result.short_trades,
    )


def _run_variant(
    config,
    strategy,
    df,
    htf_df,
    intrabar_df,
    timeframe: str,
) -> BacktestResult:
    engine = BacktestEngine(
        strategy,
        config.backtest,
        config.exchange.fees,
        live_config=config.live,
    )
    return engine.run(df.copy(), htf_df, timeframe=timeframe, intrabar_df=intrabar_df.copy())


def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    config = load_config(config_path)
    timeframe = sys.argv[2] if len(sys.argv) > 2 else config.default_timeframe

    print(f"\n=== Trail SL vs Bracket | {config.symbol} | {timeframe} ===\n")

    df = fetch_ohlcv(
        symbol=config.symbol,
        timeframe=timeframe,
        limit=config.backtest.candles_limit,
        exchange_id=config.exchange.id,
    )
    sub_tf = config.backtest.intrabar_timeframe
    intrabar_df = fetch_intrabar_for_htf(
        config.symbol,
        df,
        htf_timeframe=timeframe,
        sub_timeframe=sub_tf,
        exchange_id=config.exchange.id,
    )
    df, intrabar_df, align = prepare_live_like_data(
        df, intrabar_df, htf_timeframe=timeframe, sub_timeframe=sub_tf
    )

    print(
        f"Общий период: {align.range_start} — {align.range_end} | "
        f"{align.days} d. | {align.htf_bars_after} x {timeframe} | "
        f"{align.intrabar_bars_after} x {sub_tf}\n"
    )

    htf_df = None
    base_strategy = config.strategy_for_timeframe(timeframe)

    trail_strategy = copy.deepcopy(base_strategy)
    trail_strategy.trail_sl.enabled = True

    bracket_strategy = copy.deepcopy(base_strategy)
    bracket_strategy.trail_sl.enabled = False

    trail_result = _run_variant(config, trail_strategy, df, htf_df, intrabar_df, timeframe)
    bracket_result = _run_variant(config, bracket_strategy, df, htf_df, intrabar_df, timeframe)

    trail = _summarize("Trail SL", trail_result, align)
    bracket = _summarize("Bracket SL+TP", bracket_result, align)

    rows = [
        ["Доходность %", f"{trail.return_pct:+.2f}", f"{bracket.return_pct:+.2f}"],
        ["Баланс $", f"{trail.final_balance:.2f}", f"{bracket.final_balance:.2f}"],
        ["Сделок", trail.trades, bracket.trades],
        ["Long / Short", f"{trail.long_trades}/{trail.short_trades}", f"{bracket.long_trades}/{bracket.short_trades}"],
        ["Win rate %", f"{trail.win_rate:.1f}", f"{bracket.win_rate:.1f}"],
        ["Max DD %", f"{trail.max_dd_pct:.2f}", f"{bracket.max_dd_pct:.2f}"],
        ["Комиссии $", f"{trail.fees_usd:.2f}", f"{bracket.fees_usd:.2f}"],
        ["Ср. выигрыш %", f"{trail.avg_win_pct:+.2f}", f"{bracket.avg_win_pct:+.2f}"],
        ["Ср. проигрыш %", f"{trail.avg_loss_pct:+.2f}", f"{bracket.avg_loss_pct:+.2f}"],
        ["Profit factor", f"{trail.profit_factor:.2f}", f"{bracket.profit_factor:.2f}"],
    ]
    print(tabulate(rows, headers=["Метрика", trail.name, bracket.name], tablefmt="simple"))

    print("\n--- Причины выхода ---")
    all_reasons = sorted(set(trail.exit_reasons) | set(bracket.exit_reasons))
    reason_rows = [
        [r, trail.exit_reasons.get(r, 0), bracket.exit_reasons.get(r, 0)] for r in all_reasons
    ]
    print(tabulate(reason_rows, headers=["Причина", trail.name, bracket.name], tablefmt="simple"))

    delta_ret = trail.return_pct - bracket.return_pct
    delta_dd = trail.max_dd_pct - bracket.max_dd_pct
    print("\n--- Вывод ---")
    if delta_ret > 0.5:
        winner = "Trail SL"
    elif delta_ret < -0.5:
        winner = "Bracket SL+TP"
    else:
        winner = "примерно равны"

    print(f"Доходность: trail {delta_ret:+.2f} п.п. относительно bracket.")
    print(f"Просадка: trail {delta_dd:+.2f} п.п. (меньше — лучше).")

    if winner == "Trail SL":
        print(
            f"На {align.days} дн. лучше Trail SL: выше доходность "
            f"({trail.return_pct:+.2f}% vs {bracket.return_pct:+.2f}%)."
        )
    elif winner == "Bracket SL+TP":
        print(
            f"На {align.days} дн. лучше Bracket SL+TP: выше доходность "
            f"({bracket.return_pct:+.2f}% vs {trail.return_pct:+.2f}%)."
        )
    else:
        print(
            f"На {align.days} дн. разница минимальна "
            f"({trail.return_pct:+.2f}% vs {bracket.return_pct:+.2f}%)."
        )

    if trail.max_dd_pct < bracket.max_dd_pct - 0.5:
        print(f"Trail SL даёт меньшую просадку ({trail.max_dd_pct:.1f}% vs {bracket.max_dd_pct:.1f}%).")
    elif bracket.max_dd_pct < trail.max_dd_pct - 0.5:
        print(f"Bracket даёт меньшую просадку ({bracket.max_dd_pct:.1f}% vs {trail.max_dd_pct:.1f}%).")

    if trail.trades != bracket.trades:
        print(
            f"Число сделок: trail {trail.trades}, bracket {bracket.trades} "
            f"({'больше стопов' if trail.trades > bracket.trades else 'чаще держит до TP'})."
        )


if __name__ == "__main__":
    main()
