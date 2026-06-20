#!/usr/bin/env python3
"""Сравнение ADX-фильтра на 1h HYPE (live_like)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tabulate import tabulate

from src.backtest.engine import BacktestEngine
from src.backtest.intrabar_align import fetch_intrabar_for_backtest, prepare_live_like_data
from src.config import AdxFilterConfig, load_config
from src.data import fetch_ohlcv, fetch_ohlcv_max


def run_bt(cfg, df, ib, tf: str, strategy):
    return BacktestEngine(
        strategy, cfg.backtest, cfg.exchange.fees, live_config=cfg.live
    ).run(df, timeframe=tf, intrabar_df=ib)


def main() -> None:
    cfg = load_config()
    tf = "1h"
    cache: dict[str, tuple] = {}

    def data(max_hist: bool):
        key = "max" if max_hist else "41d"
        if key not in cache:
            df = (
                fetch_ohlcv_max(cfg.symbol, tf, cfg.exchange.id)
                if max_hist
                else fetch_ohlcv(cfg.symbol, tf, cfg.backtest.candles_limit, cfg.exchange.id)
            )
            ib = fetch_intrabar_for_backtest(cfg, df, htf_timeframe=tf)
            df, ib, al = prepare_live_like_data(df, ib, htf_timeframe=tf, sub_timeframe="5m")
            cache[key] = (df, ib, al)
        return cache[key]

    variants: list[tuple[str, AdxFilterConfig]] = [
        ("ADX>=22", AdxFilterConfig(enabled=True, min_for_entry=22)),
        ("ADX>=22 + rising", AdxFilterConfig(enabled=True, min_for_entry=22, require_rising=True)),
        ("ADX>=24 + rising", AdxFilterConfig(enabled=True, min_for_entry=24, require_rising=True)),
    ]

    for max_hist, period in [(False, "41d"), (True, "MAX 208d")]:
        df, ib, al = data(max_hist)
        print(f"\n=== {period} | {al.days}d | momentum ON ===\n")
        rows = []
        for name, adx_cfg in variants:
            c = copy.deepcopy(cfg)
            s = copy.deepcopy(c.strategy_for_timeframe(tf))
            s.adx_filter = adx_cfg
            c.strategy_by_timeframe = {**c.strategy_by_timeframe, tf: s}
            r = run_bt(c, df, ib, tf, s)
            rows.append([
                name,
                f"{r.total_return_pct:+.1f}%",
                f"{r.max_drawdown_pct:.1f}%",
                r.total_trades,
                f"{r.win_rate:.0f}%",
                r.long_trades,
                r.short_trades,
            ])
        print(tabulate(
            rows,
            headers=["ADX filter", "Return", "MaxDD", "Trades", "WR", "L", "S"],
            tablefmt="simple",
        ))


if __name__ == "__main__":
    main()
