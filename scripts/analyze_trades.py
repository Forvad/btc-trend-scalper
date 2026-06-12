from src.config import load_config
from src.data import fetch_ohlcv
from src.backtest import BacktestEngine

config = load_config()
fees = config.exchange.fees
print(f"Exchange: {config.exchange.id} | {config.symbol}")
print(f"Fees: maker={fees.maker_pct}% taker={fees.taker_pct}%")

for tf in ["15m", "1h"]:
    df = fetch_ohlcv(
        config.symbol, tf, config.backtest.candles_limit, config.exchange.id
    )
    r = BacktestEngine(config.strategy, config.backtest, fees).run(df)
    wins = [t for t in r.trades if t.pnl_usd and t.pnl_usd > 0]
    losses = [t for t in r.trades if t.pnl_usd and t.pnl_usd <= 0]
    avg_win = sum(t.pnl_usd for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.pnl_usd for t in losses) / len(losses) if losses else 0
    gross = sum(t.pnl_usd for t in r.trades if t.pnl_usd)

    print(f"\n=== {tf} ===")
    print(f"Win rate: {r.win_rate:.1f}%  Return: {r.total_return_pct:+.2f}%")
    print(f"Avg win: {avg_win:.2f} USD  Avg loss: {avg_loss:.2f} USD")
    print(f"Sum trade net PnL: {gross:.2f} USD  Total fees: {r.total_fees_usd:.2f} USD")
