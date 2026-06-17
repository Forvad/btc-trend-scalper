#!/usr/bin/env python3
"""Быстрый live-like 1h перебор (урезанная сетка)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tabulate import tabulate

from scripts.tune_symbol import live_cfg, run_bt, score
from src.backtest.intrabar_align import fetch_intrabar_for_htf, prepare_live_like_data
from src.config import (
    BollingerConfig,
    EnhancementConfig,
    StrategyConfig,
    SupertrendConfig,
    TrailSlConfig,
    load_config,
)
from src.data import fetch_ohlcv_max

TRAIL = TrailSlConfig(enabled=True, trail_start_at_pct=1.5, trail_step_pct=0.3, take_profit_bb=True)


def candidates() -> list[tuple[str, StrategyConfig]]:
    out: list[tuple[str, StrategyConfig]] = []
    for ema_f, ema_s in ((9, 21), (12, 26), (20, 50)):
        for st_p, st_m in ((7, 2.5), (10, 2.5), (10, 3.0), (10, 3.5)):
            for vol in (14, 20):
                s = StrategyConfig(
                    ema_fast=ema_f,
                    ema_slow=ema_s,
                    supertrend=SupertrendConfig(period=st_p, multiplier=st_m),
                    bollinger=BollingerConfig(period=20, std_dev=2.5),
                    volume_sma_period=vol,
                    enhancements=EnhancementConfig(enabled=False),
                    trail_sl=TRAIL,
                )
                out.append((f"ema{ema_f}/{ema_s} st{st_p}x{st_m} v{vol}", s))
    return out


def main() -> None:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC/USDC:USDC"
    cfg = load_config()
    cfg.exchange.symbol = symbol
    live = live_cfg(cfg)

    df = fetch_ohlcv_max(symbol, "1h", cfg.exchange.id)
    ib = fetch_intrabar_for_htf(symbol, df, htf_timeframe="1h", sub_timeframe="5m", exchange_id=cfg.exchange.id)
    df, ib, _ = prepare_live_like_data(df, ib, htf_timeframe="1h", sub_timeframe="5m")

    base = StrategyConfig(enhancements=EnhancementConfig(enabled=False), trail_sl=TRAIL)
    b = run_bt(df, base, live, timeframe="1h", intrabar_df=ib)
    print(f"{symbol} baseline live 1h: {b['ret']:+.1f}% | {b['trades']} tr | DD {b['dd']:.1f}%\n")

    rows = []
    for tag, strategy in candidates():
        m = run_bt(df, strategy, live, timeframe="1h", intrabar_df=ib)
        sc = score(m["ret"], m["dd"], m["trades"], max(b["trades"], 5))
        rows.append((sc, tag, m))

    rows.sort(key=lambda x: x[0], reverse=True)
    print(tabulate(
        [[i + 1, r[1], f"{r[2]['ret']:+.1f}%", r[2]["trades"], f"{r[2]['dd']:.1f}%"] for i, r in enumerate(rows[:10])],
        headers=["#", "Config", "1h live", "tr", "DD"],
        tablefmt="simple",
    ))
    best = rows[0]
    print(f"\nBEST: {best[1]} -> {best[2]['ret']:+.1f}%")


if __name__ == "__main__":
    main()
