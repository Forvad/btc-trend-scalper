from __future__ import annotations

from tabulate import tabulate

from src.backtest.engine import BacktestEngine
from src.backtest.hybrid_engine import HybridBacktestEngine, analyze_signal_overlap, merge_signals
from src.backtest.range_engine import RangeBacktestEngine
from src.config import AppConfig
from src.data import fetch_ohlcv, fetch_ohlcv_max


def _stats(label: str, result, days: int) -> dict:
    trend_trades = sum(1 for t in result.trades if getattr(t, "source", None) == "trend")
    return {
        "Mode": label,
        "Days": days,
        "Return%": f"{result.total_return_pct:+.2f}",
        "Trades": result.total_trades,
        "Win%": f"{result.win_rate:.1f}",
        "MaxDD%": f"{result.max_drawdown_pct:.2f}",
        "Fees$": f"{result.total_fees_usd:.2f}",
        "Final$": f"{result.final_balance:.2f}",
    }


def run_hybrid_compare(config: AppConfig, *, max_history: bool = False) -> None:
    print(f"\n=== Hybrid vs separate | {config.symbol} ===")
    print(
        f"ADX zones: RANGE <= {config.hybrid.range_adx_max} | "
        f"dead zone | TREND >= {config.hybrid.trend_adx_min}\n"
    )

    rows = []
    overlap_rows = []

    for tf in ["15m", "1h", "4h", "1d"]:
        if max_history:
            df = fetch_ohlcv_max(config.symbol, tf, config.exchange.id)
        else:
            df = fetch_ohlcv(config.symbol, tf, config.backtest.candles_limit, config.exchange.id)

        days = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).days
        merged = merge_signals(df, config)

        ov = analyze_signal_overlap(merged, config.hybrid)
        overlap_rows.append({"TF": tf, **ov})

        trend_r = BacktestEngine(config.strategy, config.backtest, config.exchange.fees).run(df)
        range_r = RangeBacktestEngine(
            config.range_strategy, config.backtest, config.exchange.fees
        ).run(df)
        hybrid_r = HybridBacktestEngine(config).run(df)

        for label, result in [
            ("TREND only", trend_r),
            ("RANGE only", range_r),
            ("HYBRID", hybrid_r),
        ]:
            row = _stats(label, result, days)
            row["TF"] = tf
            rows.append(row)

    print("--- Backtest results ---")
    print(tabulate(rows, headers="keys", tablefmt="simple"))
    print("\n--- Signal overlap (same bars) ---")
    print(tabulate(overlap_rows, headers="keys", tablefmt="simple"))
