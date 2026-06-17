#!/usr/bin/env python3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from src.config import load_config
from src.exchange.hyperliquid_client import create_hyperliquid_exchange, fetch_account_balances
from src.live.trade_analytics import fetch_exchange_fills, parse_closed_trades

load_dotenv()

ex = create_hyperliquid_exchange()
symbol = "HYPE/USDC:USDC"
since = int((datetime.now(timezone.utc) - timedelta(days=10)).timestamp() * 1000)
fills = fetch_exchange_fills(ex, symbol, since_ms=since, limit=1000)

print(f"=== Last fills ({len(fills)}) ===")
for f in fills[-30:]:
    ts = datetime.fromtimestamp(f["timestamp"] / 1000, tz=timezone.utc)
    info = f.get("info") or {}
    print(
        f"{ts} | {info.get('dir','?'):12} | "
        f"{f.get('side')} {f.get('amount')} @ {f.get('price')} | "
        f"closedPnl={info.get('closedPnl')} fee={(f.get('fee') or {}).get('cost')}"
    )

trades = parse_closed_trades(fills)
longs = [t for t in trades if t.side == "long"]
print("\n=== Closed longs ===")
for t in longs[-5:]:
    print(
        f"{t.entry_time} @ {t.entry_price:.3f} -> {t.exit_time} @ {t.exit_price:.3f} | "
        f"gross=${t.pnl_usd:+.2f} net=${t.net_pnl_usd:+.2f} ({t.pnl_pct:+.2f}%) fees=${t.fees_usd:.2f}"
    )

if longs:
    last = longs[-1]
    print("\n=== LAST LONG (closed) ===")
    print(f"Entry:  {last.entry_time} @ {last.entry_price:.4f}")
    print(f"Exit:   {last.exit_time} @ {last.exit_price:.4f}")
    print(f"Hold:   {(last.exit_time - last.entry_time).total_seconds()/3600:.1f}h")
    print(f"Move:   {last.pnl_pct:+.2f}% | net ${last.net_pnl_usd:+.2f}")

print("\n=== Open position ===")
for p in ex.fetch_positions([symbol]):
    contracts = float(p.get("contracts") or 0)
    if contracts:
        info = p.get("info", {}).get("position", {})
        print(f"side={p.get('side')} size={contracts} entry={p.get('entryPrice')} upnl={p.get('unrealizedPnl')}")

_, equity = fetch_account_balances(ex)
print(f"equity=${equity:.2f}")
