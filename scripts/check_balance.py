"""Диагностика баланса Hyperliquid (не коммитить с секретами)."""
from __future__ import annotations

import os

from dotenv import load_dotenv

from src.exchange.hyperliquid_client import create_hyperliquid_exchange, fetch_account_balances


def main() -> None:
    load_dotenv()
    wallet = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "").strip()
    print(f"Configured wallet: {wallet}")

    ex = create_hyperliquid_exchange()

    try:
        abstraction = ex.publicPostInfo({"type": "userAbstraction", "user": wallet})
        print(f"userAbstraction: {abstraction}")
    except Exception as exc:
        print(f"userAbstraction error: {exc}")

    for unified in (None, True, False):
        params: dict = {}
        if unified is not None:
            params["enableUnifiedMargin"] = unified
        try:
            balance = ex.fetch_balance(params)
            info = balance.get("info") or {}
            margin = info.get("marginSummary") or {}
            print(
                f"fetch_balance(unified={unified}): "
                f"accountValue={margin.get('accountValue')} "
                f"withdrawable={info.get('withdrawable')} "
                f"USDC={balance.get('USDC')}"
            )
        except Exception as exc:
            print(f"fetch_balance(unified={unified}) error: {exc}")

    available, equity = fetch_account_balances(ex)
    print(f"fetch_account_balances: available={available}, equity={equity}")


if __name__ == "__main__":
    main()
