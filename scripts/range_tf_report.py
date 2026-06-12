"""Сводка Range v2 по таймфреймам."""
from tabulate import tabulate

from src.backtest.range_engine import RangeBacktestEngine
from src.config import load_config
from src.data import fetch_ohlcv, fetch_ohlcv_max

config = load_config()
rows = []

for tf in ["15m", "1h", "4h", "1d"]:
    for label, fetcher in [("1000", False), ("MAX", True)]:
        if fetcher:
            df = fetch_ohlcv_max(config.symbol, tf, config.exchange.id)
        else:
            df = fetch_ohlcv(
                config.symbol, tf, config.backtest.candles_limit, config.exchange.id
            )
        r = RangeBacktestEngine(config.range_strategy, config.backtest, config.exchange.fees).run(
            df
        )
        days = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).days
        rows.append(
            {
                "TF": tf,
                "Data": label,
                "Days": days,
                "Return%": f"{r.total_return_pct:+.2f}",
                "Trades": r.total_trades,
                "Win%": f"{r.win_rate:.1f}",
                "MaxDD%": f"{r.max_drawdown_pct:.2f}",
                "Fees$": f"{r.total_fees_usd:.2f}",
                "Final$": f"{r.final_balance:.2f}",
            }
        )

print("\n=== RANGE v2 |", config.symbol, "===\n")
print(tabulate(rows, headers="keys", tablefmt="simple"))
