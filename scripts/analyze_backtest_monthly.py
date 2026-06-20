#!/usr/bin/env python3
"""Помесячный разбор бэктеста 1h HYPE."""

from __future__ import annotations

import copy
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tabulate import tabulate

from src.backtest.engine import BacktestEngine
from src.backtest.intrabar_align import fetch_intrabar_for_backtest, prepare_live_like_data
from src.config import load_config
from src.data import fetch_ohlcv, fetch_ohlcv_max


def load_data(cfg, tf: str, max_history: bool):
    df = (
        fetch_ohlcv_max(cfg.symbol, tf, cfg.exchange.id)
        if max_history
        else fetch_ohlcv(cfg.symbol, tf, cfg.backtest.candles_limit, cfg.exchange.id)
    )
    sub_tf = cfg.backtest.intrabar_timeframe
    ib = fetch_intrabar_for_backtest(cfg, df, htf_timeframe=tf)
    df, ib, align = prepare_live_like_data(df, ib, htf_timeframe=tf, sub_timeframe=sub_tf)
    return df, ib, align


def monthly_stats(trades) -> list[list]:
    by_month: dict[str, dict] = defaultdict(lambda: {
        "pnl": 0.0, "n": 0, "wins": 0, "long_pnl": 0.0, "short_pnl": 0.0, "long_n": 0, "short_n": 0
    })
    for t in trades:
        if not t.exit_time or t.pnl_usd is None:
            continue
        key = t.exit_time.strftime("%Y-%m")
        m = by_month[key]
        m["pnl"] += t.pnl_usd
        m["n"] += 1
        if t.pnl_usd > 0:
            m["wins"] += 1
        if t.side == "long":
            m["long_pnl"] += t.pnl_usd
            m["long_n"] += 1
        else:
            m["short_pnl"] += t.pnl_usd
            m["short_n"] += 1
    rows = []
    for month in sorted(by_month):
        m = by_month[month]
        wr = 100 * m["wins"] / m["n"] if m["n"] else 0
        rows.append([
            month,
            m["n"],
            f"{wr:.0f}%",
            f"${m['pnl']:+.2f}",
            f"${m['long_pnl']:+.2f} ({m['long_n']})",
            f"${m['short_pnl']:+.2f} ({m['short_n']})",
        ])
    return rows


def run(cfg, df, ib, tf: str):
    return BacktestEngine(
        cfg.strategy_for_timeframe(tf),
        cfg.backtest,
        cfg.exchange.fees,
        live_config=cfg.live,
    ).run(df, timeframe=tf, intrabar_df=ib)


def main() -> None:
    cfg = load_config()
    tf = "1h"

    print("\n=== MAX 208d — помесячно ===\n")
    df_max, ib_max, align_max = load_data(cfg, tf, max_history=True)
    r_max = run(cfg, df_max, ib_max, tf)
    print(f"Период: {align_max.range_start} — {align_max.range_end} ({align_max.days}d)")
    print(f"Итого: {r_max.total_return_pct:+.1f}% | DD {r_max.max_drawdown_pct:.1f}% | "
          f"{r_max.total_trades} сделок | WR {r_max.win_rate:.0f}%\n")
    print(tabulate(
        monthly_stats(r_max.trades),
        headers=["Месяц", "Сделок", "WR", "PnL$", "Long", "Short"],
        tablefmt="simple",
    ))

    # split: first 167d vs last 41d (approx)
    split_ts = df_max["timestamp"].iloc[-1000]
    early = df_max[df_max["timestamp"] < split_ts].copy()
    late = df_max[df_max["timestamp"] >= split_ts].copy()
    ib_early = ib_max[ib_max["timestamp"] < split_ts + __import__("pandas").Timedelta(hours=1)]
    ib_late = ib_max[ib_max["timestamp"] >= split_ts]

    r_early = run(cfg, early, ib_early, tf)
    r_late = run(cfg, late, ib_late, tf)
    print(f"\n=== Разрез MAX: до {split_ts} vs последние ~41d ===\n")
    print(tabulate([
        ["Ранний период", len(early), f"{r_early.total_return_pct:+.1f}%", f"{r_early.max_drawdown_pct:.1f}%",
         r_early.total_trades, f"{r_early.win_rate:.0f}%"],
        ["Последние 41d", len(late), f"{r_late.total_return_pct:+.1f}%", f"{r_late.max_drawdown_pct:.1f}%",
         r_late.total_trades, f"{r_late.win_rate:.0f}%"],
    ], headers=["Окно", "Баров", "Return", "MaxDD", "Сделок", "WR"], tablefmt="simple"))

    # momentum filter
    print("\n=== Momentum filter ON vs OFF (MAX) ===\n")
    mf_rows = []
    for enabled, name in [(True, "ON"), (False, "OFF")]:
        c = copy.deepcopy(cfg)
        s = copy.deepcopy(c.strategy_for_timeframe(tf))
        s.momentum_filter.enabled = enabled
        c.strategy_by_timeframe = {**c.strategy_by_timeframe, tf: s}
        r = run(c, df_max, ib_max, tf)
        long_pnl = sum(t.pnl_usd or 0 for t in r.trades if t.side == "long")
        short_pnl = sum(t.pnl_usd or 0 for t in r.trades if t.side == "short")
        mf_rows.append([name, f"{r.total_return_pct:+.1f}%", f"{r.max_drawdown_pct:.1f}%",
                        r.total_trades, f"{r.win_rate:.0f}%", f"${long_pnl:+.1f}", f"${short_pnl:+.1f}"])
    print(tabulate(mf_rows, headers=["Filter", "Return", "DD", "Trades", "WR", "PnL L", "PnL S"], tablefmt="simple"))

    # trail_sl losses count
    from collections import Counter
    reasons = Counter(t.exit_reason for t in r_max.trades)
    trail_losses = [t for t in r_max.trades if t.exit_reason == "trail_sl" and (t.pnl_usd or 0) < 0]
    tp_wins = [t for t in r_max.trades if t.exit_reason == "take_profit_bb" and (t.pnl_usd or 0) > 0]
    print(f"\n=== Выходы MAX ===\n{dict(reasons)}")
    print(f"trail_sl убытки: {len(trail_losses)} сделок, ${sum(t.pnl_usd for t in trail_losses):.2f}")
    print(f"TP BB прибыль: {len(tp_wins)} сделок, ${sum(t.pnl_usd for t in tp_wins):.2f}")
    big_losses = sorted([t for t in r_max.trades if (t.pnl_usd or 0) < -3], key=lambda t: t.pnl_usd)[:10]
    print("\nКрупные убытки (>$3):")
    for t in big_losses:
        print(f"  {t.exit_time} {t.side.upper()} ${t.pnl_usd:+.2f} | entry {t.entry_time} @ {t.entry_price:.2f}")


if __name__ == "__main__":
    main()
