#!/usr/bin/env python3
"""Перебор базовых параметров trend-стратегии (без enhancements) для HYPE."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tabulate import tabulate

from src.backtest.engine import BacktestEngine
from src.config import (
    BollingerConfig,
    EnhancementConfig,
    StrategyConfig,
    SupertrendConfig,
    load_config,
)
from src.data import fetch_ohlcv_max


def score(ret: float, dd: float, trades: int, base_trades: int) -> float:
    if trades < base_trades * 0.4:
        return -9999
    return ret - dd * 0.55


def main() -> None:
    cfg = load_config()
    tfs = ["15m", "1h", "4h", "1d"]
    data = {tf: fetch_ohlcv_max(cfg.symbol, tf, cfg.exchange.id) for tf in tfs}

    baselines = {}
    for tf in tfs:
        s = StrategyConfig(enhancements=EnhancementConfig(enabled=False))
        r = BacktestEngine(s, cfg.backtest, cfg.exchange.fees).run(data[tf])
        baselines[tf] = {"ret": r.total_return_pct, "trades": r.total_trades, "dd": r.max_drawdown_pct}

    grid: list[tuple[str, StrategyConfig]] = []
    for ema_f, ema_s in ((12, 26), (15, 40), (20, 50), (21, 55), (9, 21)):
        for st_p, st_m in ((7, 2.5), (10, 2.5), (10, 3.0), (10, 3.5), (14, 3.0), (10, 4.0)):
            for bb_p, bb_std in ((20, 2.0), (20, 2.5), (14, 2.0)):
                for vol in (14, 20, 30):
                    s = StrategyConfig(
                        ema_fast=ema_f,
                        ema_slow=ema_s,
                        supertrend=SupertrendConfig(period=st_p, multiplier=st_m),
                        bollinger=BollingerConfig(period=bb_p, std_dev=bb_std),
                        volume_sma_period=vol,
                        enhancements=EnhancementConfig(enabled=False),
                    )
                    tag = f"ema{ema_f}/{ema_s} st{st_p}x{st_m} bb{bb_p}/{bb_std} v{vol}"
                    grid.append((tag, s))

    print(f"\n=== Core params tune: {cfg.symbol} ({len(grid)} configs) ===\n")

    results: list[dict] = []
    for tag, strategy in grid:
        per_tf = {}
        scores = []
        for tf in tfs:
            r = BacktestEngine(strategy, cfg.backtest, cfg.exchange.fees).run(data[tf])
            b = baselines[tf]
            sc = score(r.total_return_pct, r.max_drawdown_pct, r.total_trades, b["trades"])
            per_tf[tf] = r
            scores.append(sc)
        results.append({
            "tag": tag,
            "strategy": strategy,
            "avg_score": sum(scores) / len(scores),
            "per_tf": per_tf,
        })

    results.sort(key=lambda x: x["avg_score"], reverse=True)

    print("=== TOP 10 (avg score all TF) ===\n")
    print(
        tabulate(
            [
                [
                    i + 1,
                    r["tag"],
                    f"{r['avg_score']:.0f}",
                    f"{r['per_tf']['15m'].total_return_pct:+.0f}%",
                    f"{r['per_tf']['1h'].total_return_pct:+.0f}%",
                    f"{r['per_tf']['4h'].total_return_pct:+.0f}%",
                    f"{r['per_tf']['1d'].total_return_pct:+.0f}%",
                ]
                for i, r in enumerate(results[:10])
            ],
            headers=["#", "Config", "Score", "15m", "1h", "4h", "1d"],
            tablefmt="simple",
        )
    )

    print("\n=== BEST PER TF ===\n")
    per_tf_table = []
    for tf in tfs:
        tf_best = sorted(
            results,
            key=lambda r: score(
                r["per_tf"][tf].total_return_pct,
                r["per_tf"][tf].max_drawdown_pct,
                r["per_tf"][tf].total_trades,
                baselines[tf]["trades"],
            ),
            reverse=True,
        )
        b = baselines[tf]
        best = tf_best[0]
        br = best["per_tf"][tf]
        per_tf_table.append([
            tf,
            f"{b['ret']:+.0f}%",
            f"{br.total_return_pct:+.0f}%",
            best["tag"],
            br.total_trades,
            f"{br.max_drawdown_pct:.1f}%",
        ])
        print(f"{tf} top3:")
        for row in tf_best[:3]:
            rr = row["per_tf"][tf]
            print(f"  {row['tag']}: {rr.total_return_pct:+.1f}% ({rr.total_trades} tr, DD {rr.max_drawdown_pct:.1f}%)")
        print()

    print(tabulate(per_tf_table, headers=["TF", "Base", "Best", "Config", "Trades", "DD"], tablefmt="simple"))

    best = results[0]["strategy"]
    print(f"\n=== Рекомендуемый общий конфиг: {results[0]['tag']} ===")
    print(f"  ema_fast/slow: {best.ema_fast} / {best.ema_slow}")
    print(f"  supertrend: period={best.supertrend.period}, multiplier={best.supertrend.multiplier}")
    print(f"  bollinger: period={best.bollinger.period}, std_dev={best.bollinger.std_dev}")
    print(f"  volume_sma_period: {best.volume_sma_period}")
    print("  enhancements: disabled")


if __name__ == "__main__":
    main()
