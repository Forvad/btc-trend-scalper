#!/usr/bin/env python3
"""Сравнение бэктеста 1000 свечей vs max + разбор сделок."""

from __future__ import annotations

import copy
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tabulate import tabulate

from src.backtest.engine import BacktestEngine
from src.backtest.intrabar_align import fetch_intrabar_for_backtest, prepare_live_like_data
from src.config import load_config
from src.data import fetch_ohlcv, fetch_ohlcv_max


def run_variant(cfg, df, intrabar, tf: str, label: str) -> dict:
    engine = BacktestEngine(
        cfg.strategy_for_timeframe(tf),
        cfg.backtest,
        cfg.exchange.fees,
        live_config=cfg.live,
    )
    r = engine.run(df.copy(), timeframe=tf, intrabar_df=intrabar.copy() if intrabar is not None else None)
    trades = r.trades
    wins = [t for t in trades if t.pnl_usd and t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd and t.pnl_usd <= 0]
    reasons = Counter(t.exit_reason or "?" for t in trades)
    long_pnl = sum(t.pnl_usd or 0 for t in trades if t.side == "long")
    short_pnl = sum(t.pnl_usd or 0 for t in trades if t.side == "short")
    avg_win = sum(t.pnl_usd for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.pnl_usd for t in losses) / len(losses) if losses else 0
    worst = sorted(trades, key=lambda t: t.pnl_usd or 0)[:5]
    return {
        "label": label,
        "bars": len(df),
        "days": (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).days,
        "start": str(df["timestamp"].iloc[0]),
        "end": str(df["timestamp"].iloc[-1]),
        "return_pct": r.total_return_pct,
        "dd": r.max_drawdown_pct,
        "trades": r.total_trades,
        "wr": r.win_rate,
        "long": r.long_trades,
        "short": r.short_trades,
        "long_pnl": long_pnl,
        "short_pnl": short_pnl,
        "fees": r.total_fees_usd,
        "reasons": reasons,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "worst": worst,
        "result": r,
    }


def load_live_like(cfg, tf: str, *, max_history: bool):
    if max_history:
        df = fetch_ohlcv_max(cfg.symbol, tf, cfg.exchange.id)
    else:
        df = fetch_ohlcv(cfg.symbol, tf, cfg.backtest.candles_limit, cfg.exchange.id)
    sub_tf = cfg.backtest.intrabar_timeframe
    ib = fetch_intrabar_for_backtest(cfg, df, htf_timeframe=tf)
    df, ib, align = prepare_live_like_data(df, ib, htf_timeframe=tf, sub_timeframe=sub_tf)
    return df, ib, align


def main() -> None:
    cfg = load_config()
    tf = "1h"

    print(f"\n=== Анализ HYPE 1h | {cfg.exchange.id} HTF + {cfg.intrabar_exchange_id()} intrabar ===\n")

    rows = []
    details = []
    for max_hist, label in [(False, "1000 (~41d)"), (True, "MAX")]:
        df, ib, align = load_live_like(cfg, tf, max_history=max_hist)
        d = run_variant(cfg, df, ib, tf, label)
        rows.append([
            label,
            d["bars"],
            d["days"],
            f"{d['return_pct']:+.1f}%",
            f"{d['dd']:.1f}%",
            d["trades"],
            f"{d['wr']:.0f}%",
            d["long"],
            d["short"],
            f"${d['long_pnl']:+.2f}",
            f"${d['short_pnl']:+.2f}",
            f"${d['fees']:.2f}",
        ])
        details.append((label, d, align))
        print(f"--- {label}: {align.htf_bars_after}×{tf} + {align.intrabar_bars_after}×5m | "
              f"{align.range_start} — {align.range_end} | dropped {align.dropped_htf_bars} ---")

    print(tabulate(
        rows,
        headers=["Период", "HTF баров", "Дней", "Return", "MaxDD", "Сделок", "WR",
                 "Long", "Short", "PnL L", "PnL S", "Fees"],
        tablefmt="simple",
    ))

    for label, d, _ in details:
        print(f"\n### {label} — выходы")
        for reason, cnt in d["reasons"].most_common():
            print(f"  {reason}: {cnt}")
        print(f"  avg win ${d['avg_win']:+.2f} | avg loss ${d['avg_loss']:+.2f}")
        print("  Худшие 5:")
        for t in d["worst"]:
            print(
                f"    {t.side.upper():5} {t.entry_time} @ {t.entry_price:.2f} -> "
                f"{t.exit_time} @ {t.exit_price:.2f} | {t.exit_reason} | {t.pnl_pct:+.2f}% ${t.pnl_usd:+.2f}"
            )

    # momentum filter OFF comparison on same 41d window
    print("\n=== Momentum filter: ON vs OFF (1000 window) ===")
    df, ib, _ = load_live_like(cfg, tf, max_history=False)
    mf_rows = []
    for enabled, name in [(True, "ON (cfg)"), (False, "OFF")]:
        c = copy.deepcopy(cfg)
        s = copy.deepcopy(c.strategy_for_timeframe(tf))
        s.momentum_filter.enabled = enabled
        c.strategy_by_timeframe = {**c.strategy_by_timeframe, tf: s}
        d = run_variant(c, df, ib, tf, name)
        mf_rows.append([name, f"{d['return_pct']:+.1f}%", d["trades"], f"{d['wr']:.0f}%",
                        f"{d['dd']:.1f}%", d["long"], d["short"]])
    print(tabulate(mf_rows, headers=["Filter", "Return", "Trades", "WR", "DD", "L", "S"], tablefmt="simple"))

    # bar-close vs live-like on 41d
    print("\n=== live_like vs bar-close (1000 window) ===")
    df_raw = fetch_ohlcv(cfg.symbol, tf, cfg.backtest.candles_limit, cfg.exchange.id)
    df_ll, ib, _ = load_live_like(cfg, tf, max_history=False)
    bc_cfg = copy.deepcopy(cfg)
    bc_cfg.backtest.live_like = False
    d_bc = run_variant(bc_cfg, df_raw, None, tf, "bar-close")
    d_ll = run_variant(cfg, df_ll, ib, tf, "live-like")
    print(tabulate(
        [[d_bc["label"], f"{d_bc['return_pct']:+.1f}%", d_bc["trades"], f"{d_bc['wr']:.0f}%", f"{d_bc['dd']:.1f}%"],
         [d_ll["label"], f"{d_ll['return_pct']:+.1f}%", d_ll["trades"], f"{d_ll['wr']:.0f}%", f"{d_ll['dd']:.1f}%"]],
        headers=["Mode", "Return", "Trades", "WR", "DD"],
        tablefmt="simple",
    ))


if __name__ == "__main__":
    main()
