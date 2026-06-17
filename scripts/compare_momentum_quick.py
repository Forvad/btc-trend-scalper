#!/usr/bin/env python3
"""Быстрое сравнение momentum filter на 1h (live_like)."""

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

tf = "1h"
cfg = load_config()
df = fetch_ohlcv_max(cfg.symbol, tf, cfg.exchange.id)
ib = fetch_intrabar_for_htf(cfg.symbol, df, htf_timeframe=tf, sub_timeframe="5m", exchange_id=cfg.exchange.id)
df, ib, _ = prepare_live_like_data(df, ib, htf_timeframe=tf, sub_timeframe="5m")

variants = [
    ("OFF", MomentumFilterConfig(enabled=False)),
    ("lb48/12%", MomentumFilterConfig(enabled=True, lookback_bars=48, max_rise_pct=12.0)),
    ("lb48/15%", MomentumFilterConfig(enabled=True, lookback_bars=48, max_rise_pct=15.0)),
    ("lb24/12%", MomentumFilterConfig(enabled=True, lookback_bars=24, max_rise_pct=12.0)),
    ("lb72/12%", MomentumFilterConfig(enabled=True, lookback_bars=72, max_rise_pct=12.0)),
]

rows = []
for name, mf in variants:
    s = copy.deepcopy(cfg.strategy_for_timeframe(tf))
    s.momentum_filter = mf
    r = BacktestEngine(s, cfg.backtest, cfg.exchange.fees, live_config=cfg.live).run(
        df, timeframe=tf, intrabar_df=ib
    )
    rows.append([
        name,
        f"{r.total_return_pct:+.1f}%",
        r.total_trades,
        f"{r.win_rate:.0f}%",
        f"{r.max_drawdown_pct:.1f}%",
        r.long_trades,
        r.short_trades,
        f"{r.total_return_pct - r.max_drawdown_pct * 0.55:.0f}",
    ])

print(f"\n=== {cfg.symbol} {tf} live_like ===\n")
print(tabulate(rows, headers=["Filter", "Ret", "Tr", "WR", "DD", "L", "S", "Score"], tablefmt="simple"))
