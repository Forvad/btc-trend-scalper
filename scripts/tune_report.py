#!/usr/bin/env python3
"""Сравнение старых (20/50) vs оптимизированных настроек HYPE."""

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


def old_strategy() -> StrategyConfig:
    return StrategyConfig(
        ema_fast=20,
        ema_slow=50,
        supertrend=SupertrendConfig(period=10, multiplier=3.0),
        bollinger=BollingerConfig(period=20, std_dev=2.0),
        volume_sma_period=20,
        enhancements=EnhancementConfig(enabled=False),
    )


def main() -> None:
    cfg = load_config()
    tfs = ["15m", "1h", "4h", "1d"]
    rows = []
    print(f"\n=== HYPE: старый конфиг vs оптимизированный ({cfg.symbol}) ===\n")
    for tf in tfs:
        df = fetch_ohlcv_max(cfg.symbol, tf, cfg.exchange.id)
        old = BacktestEngine(old_strategy(), cfg.backtest, cfg.exchange.fees).run(df)
        new = BacktestEngine(
            cfg.strategy_for_timeframe(tf), cfg.backtest, cfg.exchange.fees
        ).run(df)
        rows.append([
            tf,
            f"{old.total_return_pct:+.1f}%",
            f"{new.total_return_pct:+.1f}%",
            f"{new.total_return_pct - old.total_return_pct:+.1f}%",
            old.total_trades,
            new.total_trades,
            f"{old.max_drawdown_pct:.1f}%",
            f"{new.max_drawdown_pct:.1f}%",
        ])
    print(
        tabulate(
            rows,
            headers=["TF", "Old", "New", "Delta", "Old#", "New#", "Old DD", "New DD"],
            tablefmt="simple",
        )
    )


if __name__ == "__main__":
    main()
