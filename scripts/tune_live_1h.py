#!/usr/bin/env python3
"""Live-like 1h pick among candidate strategies."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tabulate import tabulate

from scripts.tune_symbol import core_grid, live_cfg, run_bt, score
from src.backtest.intrabar_align import fetch_intrabar_for_backtest, prepare_live_like_data
from src.config import EnhancementConfig, StrategyConfig, TrailSlConfig, load_config
from src.data import fetch_ohlcv_max


def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC/USDC:USDC"
    cfg = load_config()
    cfg.exchange.symbol = symbol
    live = live_cfg(cfg)

    df = fetch_ohlcv_max(symbol, "1h", cfg.exchange.id)
    ib = fetch_intrabar_for_backtest(cfg, df, htf_timeframe="1h")
    df, ib, _ = prepare_live_like_data(df, ib, htf_timeframe="1h", sub_timeframe="5m")

    base = StrategyConfig(
        enhancements=EnhancementConfig(enabled=False),
        trail_sl=TrailSlConfig(enabled=True, trail_start_at_pct=1.5, trail_step_pct=0.3, take_profit_bb=True),
    )
    b = run_bt(df, base, live, timeframe="1h", intrabar_df=ib)
    print(f"baseline live 1h: {b['ret']:+.1f}% {b['trades']} tr DD {b['dd']:.1f}%")

    rows = []
    for tag, strategy in core_grid():
        m = run_bt(df, strategy, live, timeframe="1h", intrabar_df=ib)
        sc = score(m["ret"], m["dd"], m["trades"], b["trades"])
        rows.append((sc, tag, m))

    rows.sort(key=lambda x: x[0], reverse=True)
    print(tabulate(
        [[r[1], f"{r[2]['ret']:+.1f}%", r[2]["trades"], f"{r[2]['dd']:.1f}%", f"{r[0]:.0f}"] for r in rows[:15]],
        headers=["Config", "1h live", "tr", "DD", "score"],
        tablefmt="simple",
    ))


if __name__ == "__main__":
    main()
