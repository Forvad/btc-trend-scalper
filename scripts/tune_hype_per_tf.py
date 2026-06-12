#!/usr/bin/env python3
"""Лучший конфиг отдельно для каждого TF на HYPE."""

from __future__ import annotations

import copy
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tabulate import tabulate

from src.backtest.engine import BacktestEngine
from src.config import (
    AppConfig,
    EnhancementConfig,
    StrategyConfig,
    SupertrendConfig,
    load_config,
)
from src.data import fetch_ohlcv_max


def run_bt(df, strategy, cfg: AppConfig) -> dict:
    r = BacktestEngine(strategy, cfg.backtest, cfg.exchange.fees).run(df)
    return {
        "ret": r.total_return_pct,
        "trades": r.total_trades,
        "wr": r.win_rate,
        "dd": r.max_drawdown_pct,
        "open": r.open_position_at_end,
    }


def configs() -> list[tuple[str, StrategyConfig]]:
    base_st = StrategyConfig()
    out: list[tuple[str, StrategyConfig]] = []

    out.append(("baseline", copy.deepcopy(base_st)))

    for pot in (0.0, 0.05, 0.08, 0.10, 0.13, 0.15):
        s = copy.deepcopy(base_st)
        s.enhancements = EnhancementConfig(
            enabled=pot > 0,
            entry_filter=pot > 0,
            min_potential_pct=max(pot, 0.05),
            exit_partial_trail=False,
        )
        out.append((f"entry{pot:.2f}", s))

    for partial, at_mid, trail_be, trail_act in itertools.product(
        (0.25, 0.35),
        (False, True),
        (False, True),
        (0.20, 0.30),
    ):
        s = copy.deepcopy(base_st)
        s.enhancements = EnhancementConfig(
            enabled=True,
            entry_filter=True,
            min_potential_pct=0.10,
            exit_partial_trail=True,
            partial_tp_pct=partial,
            partial_at_middle=at_mid,
            trail_breakeven_after_partial=trail_be,
            trailing_activate_pct=trail_act,
        )
        mid = "mid" if at_mid else "out"
        be = "be" if trail_be else "st"
        out.append((f"e10+pt{int(partial*100)}%{mid}{be}tr{trail_act:.0f}", s))

    for mult in (2.5, 3.0, 3.5):
        for pot in (0.08, 0.10):
            s = copy.deepcopy(base_st)
            s.supertrend = SupertrendConfig(period=10, multiplier=mult)
            s.enhancements = EnhancementConfig(
                enabled=True,
                entry_filter=True,
                min_potential_pct=pot,
                exit_partial_trail=False,
            )
            out.append((f"st{mult}+e{pot:.2f}", s))

    return out


def main() -> None:
    cfg = load_config()
    tfs = ["15m", "1h", "4h", "1d"]
    data = {tf: fetch_ohlcv_max(cfg.symbol, tf, cfg.exchange.id) for tf in tfs}
    grid = configs()

    print(f"\n=== Per-TF tune: {cfg.symbol} ({len(grid)} configs) ===\n")

    summary = []
    for tf in tfs:
        base_s = copy.deepcopy(cfg.strategy)
        base_s.enhancements = EnhancementConfig(enabled=False)
        base = run_bt(data[tf], base_s, cfg)

        best_name, best_m, best_score = "", base, base["ret"] - base["dd"] * 0.5
        rows = []
        for name, strategy in grid:
            m = run_bt(data[tf], strategy, cfg)
            sc = m["ret"] - m["dd"] * 0.5 - (5 if m["open"] else 0)
            if m["trades"] < max(base["trades"] * 0.3, 5):
                sc = -999
            rows.append((sc, name, m))
            if sc > best_score:
                best_score = sc
                best_name = name
                best_m = m

        rows.sort(key=lambda x: x[0], reverse=True)
        print(f"--- {tf} | baseline {base['ret']:+.1f}% {base['trades']} trades ---")
        top5 = rows[:5]
        print(
            tabulate(
                [
                    [n, f"{m['ret']:+.1f}%", m["trades"], f"{m['dd']:.1f}%", f"{m['wr']:.0f}%"]
                    for _, n, m in top5
                ],
                headers=["Config", "Return", "Trades", "DD", "WR"],
                tablefmt="simple",
            )
        )
        print(f"  >> BEST: {best_name}\n")
        summary.append([tf, f"{base['ret']:+.0f}%", f"{best_m['ret']:+.0f}%", best_name, best_m["trades"]])

    print("=== SUMMARY ===\n")
    print(
        tabulate(
            summary,
            headers=["TF", "Baseline", "Best", "Config", "Trades"],
            tablefmt="simple",
        )
    )


if __name__ == "__main__":
    main()
