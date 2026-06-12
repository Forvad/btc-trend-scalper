from __future__ import annotations

import copy

from tabulate import tabulate

from src.backtest.engine import BacktestEngine
from src.config import AppConfig, EnhancementConfig, v2_enhancement_config
from src.data import fetch_ohlcv_max
from src.strategy.htf import htf_for_timeframe


def _run(df, htf_df, config: AppConfig, label: str) -> dict:
    engine = BacktestEngine(config.strategy, config.backtest, config.exchange.fees)
    htf = htf_df if config.strategy.enhancements.needs_htf() else None
    result = engine.run(df, htf)
    days = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).days
    return {
        "label": label,
        "days": days,
        "candles": len(df),
        "return_pct": result.total_return_pct,
        "trades": result.total_trades,
        "win_rate": result.win_rate,
        "fees": result.total_fees_usd,
        "max_dd": result.max_drawdown_pct,
        "final": result.final_balance,
        "open_pos": result.open_position_at_end,
    }


def entry_only_enhancement_config() -> EnhancementConfig:
    """Мягкий фильтр входа, выход как baseline."""
    cfg = v2_enhancement_config()
    cfg.exit_partial_trail = False
    return cfg


def run_compare(
    config: AppConfig,
    timeframes: list[str] | None = None,
    *,
    max_history: bool = False,
) -> None:
    timeframes = timeframes or (["15m", "1h", "4h", "1d"] if max_history else ["15m", "1h"])
    rows: list[dict] = []

    print(
        "\n=== Сравнение: BASELINE vs ENTRY-ONLY vs V2 (partial@middle + trail) ===\n"
    )

    for tf in timeframes:
        print(f"Загрузка {tf}...")
        df = fetch_ohlcv_max(config.symbol, tf, config.exchange.id)
        htf_df = fetch_ohlcv_max(
            config.symbol, htf_for_timeframe(tf), config.exchange.id
        )

        baseline = copy.deepcopy(config)
        baseline.strategy.enhancements = EnhancementConfig(enabled=False)

        entry_only = copy.deepcopy(config)
        entry_only.strategy.enhancements = entry_only_enhancement_config()

        v2 = copy.deepcopy(config)
        v2.strategy.enhancements = v2_enhancement_config()

        for cfg, label in (
            (baseline, "baseline"),
            (entry_only, "entry"),
            (v2, "v2"),
        ):
            r = _run(df, htf_df, cfg, label)
            r["timeframe"] = tf
            rows.append(r)

    table = []
    for tf in timeframes:
        b = next(r for r in rows if r["timeframe"] == tf and r["label"] == "baseline")
        e = next(r for r in rows if r["timeframe"] == tf and r["label"] == "entry")
        v = next(r for r in rows if r["timeframe"] == tf and r["label"] == "v2")
        table.append([
            tf,
            f"{b['days']}d",
            f"{b['return_pct']:+.2f}%",
            f"{e['return_pct']:+.2f}%",
            f"{v['return_pct']:+.2f}%",
            b["trades"],
            e["trades"],
            v["trades"],
            f"{e['win_rate']:.1f}%",
            f"{v['win_rate']:.1f}%",
            f"{b['max_dd']:.2f}%",
            f"{e['max_dd']:.2f}%",
        ])

    print(
        tabulate(
            table,
            headers=[
                "TF",
                "Period",
                "Base",
                "Entry",
                "V2 exit",
                "B#",
                "E#",
                "V2#",
                "E WR",
                "V2 WR",
                "B DD",
                "E DD",
            ],
            tablefmt="simple",
        )
    )
    print()
