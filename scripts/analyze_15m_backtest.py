#!/usr/bin/env python3
"""Статистика бэктеста 15m HYPE (1000 свечей + MAX)."""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tabulate import tabulate

from src.backtest.engine import BacktestEngine
from src.backtest.intrabar_align import fetch_intrabar_for_backtest, prepare_live_like_data
from src.config import load_config
from src.data import fetch_ohlcv, fetch_ohlcv_max


def run_period(cfg, tf: str, *, max_history: bool) -> None:
    if max_history:
        df = fetch_ohlcv_max(cfg.symbol, tf, cfg.exchange.id)
        label = "MAX"
    else:
        df = fetch_ohlcv(cfg.symbol, tf, cfg.backtest.candles_limit, cfg.exchange.id)
        label = f"{cfg.backtest.candles_limit} (~10d)"

    sub_tf = cfg.backtest.intrabar_timeframe
    ib = fetch_intrabar_for_backtest(cfg, df, htf_timeframe=tf)
    df, ib, al = prepare_live_like_data(df, ib, htf_timeframe=tf, sub_timeframe=sub_tf)
    s = cfg.strategy_for_timeframe(tf)

    print(f"\n=== 15m {label} | {al.days}d | {al.range_start} — {al.range_end} ===")
    print(
        f"Фильтры: momentum={s.momentum_filter.enabled}, "
        f"adx={s.adx_filter.enabled} (min={s.adx_filter.min_for_entry}, rising={s.adx_filter.require_rising})"
    )
    print(f"ST {s.supertrend.period}x{s.supertrend.multiplier} | vol {s.volume_sma_period}")

    r = BacktestEngine(s, cfg.backtest, cfg.exchange.fees, live_config=cfg.live).run(
        df, timeframe=tf, intrabar_df=ib
    )
    print(
        f"Return {r.total_return_pct:+.1f}% | DD {r.max_drawdown_pct:.1f}% | "
        f"{r.total_trades} tr (L{r.long_trades}/S{r.short_trades}) | WR {r.win_rate:.0f}% | fees ${r.total_fees_usd:.2f}"
    )

    by_m: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "n": 0, "w": 0})
    for t in r.trades:
        if not t.exit_time or t.pnl_usd is None:
            continue
        k = t.exit_time.strftime("%Y-%m-%d")
        m = by_m[k]
        m["pnl"] += t.pnl_usd
        m["n"] += 1
        m["w"] += int(t.pnl_usd > 0)

    if by_m:
        rows = [
            [k, v["n"], f"{100 * v['w'] / v['n']:.0f}%", f"${v['pnl']:+.2f}"]
            for k, v in sorted(by_m.items())[-14:]
        ]
        print("\nПо дням (последние 14):")
        print(tabulate(rows, headers=["День", "N", "WR", "PnL"], tablefmt="simple"))

    reasons = Counter(t.exit_reason for t in r.trades)
    trail_l = [t for t in r.trades if t.exit_reason == "trail_sl" and (t.pnl_usd or 0) < 0]
    trail_w = [t for t in r.trades if t.exit_reason == "trail_sl" and (t.pnl_usd or 0) > 0]
    tp = [t for t in r.trades if t.exit_reason == "take_profit_bb"]
    print(f"\nВыходы: {dict(reasons)}")
    print(f"trail_sl −: {len(trail_l)} → ${sum(t.pnl_usd for t in trail_l):.2f}")
    print(f"trail_sl +: {len(trail_w)} → ${sum(t.pnl_usd for t in trail_w):.2f}")
    print(f"TP BB: {len(tp)} → ${sum(t.pnl_usd or 0 for t in tp):.2f}")

    print("\nХудшие 5:")
    for t in sorted(r.trades, key=lambda x: x.pnl_usd or 0)[:5]:
        print(
            f"  {t.exit_time} {t.side.upper():5} ${t.pnl_usd:+.2f} ({t.pnl_pct:+.1f}%) {t.exit_reason}"
        )


def main() -> None:
    cfg = load_config()
    run_period(cfg, "15m", max_history=False)
    run_period(cfg, "15m", max_history=True)


if __name__ == "__main__":
    main()
