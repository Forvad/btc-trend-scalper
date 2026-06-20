from src.config import load_config
from src.data import fetch_ohlcv
from src.backtest import BacktestEngine

config = load_config()
df = fetch_ohlcv(config.symbol, "15m", config.backtest.candles_limit, config.exchange.id)
r = BacktestEngine(config.strategy, config.backtest, config.exchange.fees).run(df)

wins = [t for t in r.trades if t.pnl_usd and t.pnl_usd > 0]
losses = [t for t in r.trades if t.pnl_usd and t.pnl_usd <= 0]
tp = [t for t in r.trades if t.exit_reason == "take_profit_bb"]
st = [t for t in r.trades if t.exit_reason == "stop_supertrend"]


def hold_min(t) -> float:
    if t.exit_time and t.entry_time:
        return (t.exit_time - t.entry_time).total_seconds() / 60
    return 0.0


print("period", df["timestamp"].iloc[0], "to", df["timestamp"].iloc[-1])
print("days", (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).days)
print("trades", r.total_trades, "long", r.long_trades, "short", r.short_trades)
print("win_rate", round(r.win_rate, 1))
print("return", round(r.total_return_pct, 2))
print("fees", round(r.total_fees_usd, 2))
print("max_dd", round(r.max_drawdown_pct, 2))
print("avg_win", round(sum(t.pnl_usd for t in wins) / len(wins), 2) if wins else 0)
print("avg_loss", round(sum(t.pnl_usd for t in losses) / len(losses), 2) if losses else 0)
print("tp_count", len(tp), "tp_pnl", round(sum(t.pnl_usd for t in tp if t.pnl_usd), 2))
print("st_count", len(st), "st_pnl", round(sum(t.pnl_usd for t in st if t.pnl_usd), 2))
print("avg_hold_min", round(sum(hold_min(t) for t in r.trades) / len(r.trades), 0))
print("best", round(max(t.pnl_usd or 0 for t in r.trades), 2))
print("worst", round(min(t.pnl_usd or 0 for t in r.trades), 2))
for t in r.trades:
    h = hold_min(t)
    print(
        f"{t.side:5} {t.entry_time.strftime('%m-%d %H:%M UTC')} "
        f"{t.entry_price:.2f}->{t.exit_price:.2f} {t.exit_reason:16} "
        f"{t.pnl_pct:+.2f}% ${t.pnl_usd:+.2f} {h:.0f}m"
    )
