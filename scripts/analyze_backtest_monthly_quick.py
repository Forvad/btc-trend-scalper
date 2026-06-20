#!/usr/bin/env python3
"""Быстрый разбор одного MAX-бэктеста по месяцам."""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tabulate import tabulate

from src.backtest.engine import BacktestEngine
from src.backtest.intrabar_align import fetch_intrabar_for_backtest, prepare_live_like_data
from src.config import load_config
from src.data import fetch_ohlcv_max


def main() -> None:
    cfg = load_config()
    tf = "1h"
    print("Загрузка MAX...", flush=True)
    df = fetch_ohlcv_max(cfg.symbol, tf, cfg.exchange.id)
    ib = fetch_intrabar_for_backtest(cfg, df, htf_timeframe=tf)
    df, ib, align = prepare_live_like_data(df, ib, htf_timeframe=tf, sub_timeframe="5m")
    print(f"Период {align.range_start} — {align.range_end} ({align.days}d), баров {len(df)}", flush=True)

    print("Бэктест...", flush=True)
    r = BacktestEngine(
        cfg.strategy_for_timeframe(tf), cfg.backtest, cfg.exchange.fees, live_config=cfg.live
    ).run(df, timeframe=tf, intrabar_df=ib)

    print(f"\nИтого: {r.total_return_pct:+.1f}% | DD {r.max_drawdown_pct:.1f}% | "
          f"{r.total_trades} tr | WR {r.win_rate:.0f}% | fees ${r.total_fees_usd:.2f}\n")

    by_month: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "n": 0, "w": 0, "lp": 0.0, "sp": 0.0})
    for t in r.trades:
        if not t.exit_time or t.pnl_usd is None:
            continue
        k = t.exit_time.strftime("%Y-%m")
        m = by_month[k]
        m["pnl"] += t.pnl_usd
        m["n"] += 1
        m["w"] += int(t.pnl_usd > 0)
        if t.side == "long":
            m["lp"] += t.pnl_usd
        else:
            m["sp"] += t.pnl_usd

    rows = [[k, v["n"], f"{100*v['w']/v['n']:.0f}%", f"${v['pnl']:+.2f}", f"${v['lp']:+.2f}", f"${v['sp']:+.2f}"]
            for k, v in sorted(by_month.items())]
    print(tabulate(rows, headers=["Месяц", "N", "WR", "PnL", "Long", "Short"], tablefmt="simple"))

    reasons = Counter(t.exit_reason for t in r.trades)
    print(f"\nВыходы: {dict(reasons)}")
    trail_l = [t for t in r.trades if t.exit_reason == "trail_sl" and (t.pnl_usd or 0) < 0]
    trail_w = [t for t in r.trades if t.exit_reason == "trail_sl" and (t.pnl_usd or 0) > 0]
    tp = [t for t in r.trades if t.exit_reason == "take_profit_bb"]
    print(f"trail_sl −: {len(trail_l)} → ${sum(t.pnl_usd for t in trail_l):.2f}")
    print(f"trail_sl +: {len(trail_w)} → ${sum(t.pnl_usd for t in trail_w):.2f}")
    print(f"TP BB: {len(tp)} → ${sum(t.pnl_usd or 0 for t in tp):.2f}")

    # последние 41d по сделкам
    cut = df["timestamp"].iloc[-999]
    late = [t for t in r.trades if t.exit_time and t.exit_time >= cut]
    early = [t for t in r.trades if t.exit_time and t.exit_time < cut]
    el = sum(t.pnl_usd or 0 for t in early)
    ll = sum(t.pnl_usd or 0 for t in late)
    print(f"\nСделки до {cut}: {len(early)} → ${el:+.2f}")
    print(f"Сделки с {cut}: {len(late)} → ${ll:+.2f}")

    print("\nТоп-10 убытков:")
    for t in sorted(r.trades, key=lambda x: x.pnl_usd or 0)[:10]:
        print(f"  {t.exit_time} {t.side:5} ${t.pnl_usd:+.2f} ({t.pnl_pct:+.1f}%) {t.exit_reason}")


if __name__ == "__main__":
    main()
