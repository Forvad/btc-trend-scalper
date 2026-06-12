from __future__ import annotations

from tabulate import tabulate

from src.backtest.engine import BacktestEngine
from src.backtest.range_engine import RangeBacktestEngine
from src.config import AppConfig
from src.data import fetch_ohlcv, fetch_ohlcv_max


def _run_bot(
    config: AppConfig,
    df,
    bot: str,
) -> dict:
    if bot == "range":
        engine = RangeBacktestEngine(config.range_strategy, config.backtest, config.exchange.fees)
        result = engine.run(df)
        label = "RANGE (BB+RSI+ADX)"
    else:
        engine = BacktestEngine(config.strategy, config.backtest, config.exchange.fees)
        result = engine.run(df)
        label = "TREND (EMA+ST+Vol)"

    days = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).days
    return {
        "label": label,
        "days": days,
        "candles": len(df),
        "return_pct": result.total_return_pct,
        "trades": result.total_trades,
        "long": result.long_trades,
        "short": result.short_trades,
        "win_rate": result.win_rate,
        "fees": result.total_fees_usd,
        "max_dd": result.max_drawdown_pct,
        "final": result.final_balance,
    }


def run_compare_bots(config: AppConfig, *, max_history: bool = False) -> None:
    print(f"\n=== Compare bots | {config.exchange.id} | {config.symbol} ===\n")

    rows = []
    for tf in config.timeframes:
        if max_history:
            df = fetch_ohlcv_max(config.symbol, tf, config.exchange.id)
        else:
            df = fetch_ohlcv(
                config.symbol,
                tf,
                config.backtest.candles_limit,
                config.exchange.id,
            )

        for bot in ("trend", "range"):
            stats = _run_bot(config, df, bot)
            rows.append(
                {
                    "TF": tf,
                    "Bot": stats["label"],
                    "Days": stats["days"],
                    "Return%": f"{stats['return_pct']:+.2f}",
                    "Trades": stats["trades"],
                    "L/S": f"{stats['long']}/{stats['short']}",
                    "Win%": f"{stats['win_rate']:.1f}",
                    "Fees$": f"{stats['fees']:.2f}",
                    "MaxDD%": f"{stats['max_dd']:.2f}",
                    "Final$": f"{stats['final']:.2f}",
                }
            )

    print(
        tabulate(
            rows,
            headers="keys",
            tablefmt="simple",
        )
    )
