#!/usr/bin/env python3
"""Сравнение бэктеста с/без momentum_filter (перегрев)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tabulate import tabulate

from src.backtest.engine import BacktestEngine
from src.backtest.intrabar_align import fetch_intrabar_for_htf, prepare_live_like_data
from src.config import MomentumFilterConfig, load_config
from src.data import fetch_ohlcv_max


def run_bt(df, intrabar, strategy, cfg, tf):
    r = BacktestEngine(
        strategy, cfg.backtest, cfg.exchange.fees, live_config=cfg.live
    ).run(df, timeframe=tf, intrabar_df=intrabar)
    return {
        "ret": r.total_return_pct,
        "trades": r.total_trades,
        "wr": r.win_rate,
        "dd": r.max_drawdown_pct,
        "long": r.long_trades,
        "short": r.short_trades,
    }


def main() -> None:
    cfg = load_config()
    tfs = ["15m", "1h", "4h"]
    data = {tf: fetch_ohlcv_max(cfg.symbol, tf, cfg.exchange.id) for tf in tfs}
    intrabar = {}
    sub_tf = cfg.backtest.intrabar_timeframe
    for tf in tfs:
        ib = fetch_intrabar_for_htf(
            cfg.symbol, data[tf], htf_timeframe=tf, sub_timeframe=sub_tf, exchange_id=cfg.exchange.id
        )
        _, intrabar[tf], _ = prepare_live_like_data(data[tf], ib, htf_timeframe=tf, sub_timeframe=sub_tf)

    variants = [("OFF", MomentumFilterConfig(enabled=False))]
    for rise in (8.0, 10.0, 12.0, 15.0, 18.0):
        for lb in (24, 48, 72):
            variants.append((f"lb{lb}/{rise:.0f}%", MomentumFilterConfig(enabled=True, lookback_bars=lb, max_rise_pct=rise)))

    print(f"\n=== Momentum filter compare | {cfg.symbol} | live_like ===\n")

    for tf in tfs:
        print(f"--- {tf} ---")
        base_strategy = copy.deepcopy(cfg.strategy_for_timeframe(tf))
        base = run_bt(data[tf], intrabar[tf], base_strategy, cfg, tf)
        rows = []
        for name, mf in variants:
            s = copy.deepcopy(cfg.strategy_for_timeframe(tf))
            s.momentum_filter = copy.deepcopy(mf)
            m = run_bt(data[tf], intrabar[tf], s, cfg, tf)
            sc = m["ret"] - m["dd"] * 0.55
            rows.append([name, f"{m['ret']:+.1f}%", m["trades"], f"{m['wr']:.0f}%", f"{m['dd']:.1f}%", m["long"], m["short"], f"{sc:.0f}"])
        rows.sort(key=lambda r: float(r[-1]), reverse=True)
        print(f"baseline OFF: {base['ret']:+.1f}% | {base['trades']} tr | DD {base['dd']:.1f}%")
        print(tabulate(rows[:8], headers=["Filter", "Ret", "Tr", "WR", "DD", "L", "S", "Score"], tablefmt="simple"))
        print()


if __name__ == "__main__":
    main()
