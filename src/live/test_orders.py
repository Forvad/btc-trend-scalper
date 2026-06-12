from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from src.config import AppConfig
from src.exchange.hyperliquid_client import (
    create_hyperliquid_exchange,
    fetch_account_balances,
    has_credentials,
)
from src.notifications import TelegramNotifier
from src.utils.log import Log

TestSide = Literal["long", "short", "both"]


@dataclass
class TestOrderResult:
    side: str
    amount: float
    entry_price: float
    exit_price: float
    entry_order: dict
    exit_order: dict


class LiveOrderTester:
    """Минимальные реальные ордера на бирже: открыть → закрыть."""

    def __init__(self, config: AppConfig) -> None:
        if not has_credentials():
            raise ValueError("Нужны HYPERLIQUID_PRIVATE_KEY и HYPERLIQUID_WALLET_ADDRESS в .env")
        self.config = config
        self.symbol = config.symbol
        self.live = config.live
        self.notifier = TelegramNotifier(config.telegram)
        self.exchange = create_hyperliquid_exchange(timeout_sec=self.live.api_timeout_sec)
        self.log = Log("TEST")

    def _log(self, message: str) -> None:
        self.log.smart(message)

    def _setup(self) -> None:
        self.exchange.set_leverage(
            self.live.leverage,
            self.symbol,
            params={"marginMode": self.live.margin_mode},
        )
        self._log(f"Leverage {self.live.leverage}x ({self.live.margin_mode})")

    def _reference_price(self) -> float:
        ticker = self.exchange.fetch_ticker(self.symbol)
        price = float(ticker.get("last") or ticker.get("close") or 0)
        if price <= 0:
            raise ValueError(f"Не удалось получить цену для {self.symbol}")
        return price

    def _calc_test_amount(self, price: float) -> float:
        notional = max(self.live.min_notional_usd, 10.0)
        amount = notional / price
        amount = float(self.exchange.amount_to_precision(self.symbol, amount))
        market = self.exchange.market(self.symbol)
        min_amount = float(market.get("limits", {}).get("amount", {}).get("min") or 0)
        if min_amount and amount < min_amount:
            amount = float(self.exchange.amount_to_precision(self.symbol, min_amount))
        return amount

    def _place_market(
        self,
        order_side: str,
        amount: float,
        price: float,
        *,
        reduce_only: bool = False,
        label: str,
    ) -> dict:
        params: dict = {"slippage": str(self.live.slippage)}
        if reduce_only:
            params["reduceOnly"] = True
        price_prec = float(self.exchange.price_to_precision(self.symbol, price))
        self._log(
            f"{label}: {order_side.upper()} market {amount} @ {price_prec} "
            f"(slippage {self.live.slippage * 100:.2f}%)"
        )
        return self.exchange.create_order(
            self.symbol,
            "market",
            order_side,
            amount,
            price_prec,
            params=params,
        )

    def _fetch_position_amount(self) -> tuple[str | None, float]:
        positions = self.exchange.fetch_positions([self.symbol])
        for pos in positions:
            contracts = float(pos.get("contracts") or 0)
            if contracts == 0:
                continue
            side_raw = (pos.get("side") or "").lower()
            if side_raw == "long" or contracts > 0:
                return "long", abs(contracts)
            if side_raw == "short" or contracts < 0:
                return "short", abs(contracts)
        return None, 0.0

    def _roundtrip(self, side: Literal["long", "short"]) -> TestOrderResult:
        price = self._reference_price()
        amount = self._calc_test_amount(price)
        notional = amount * price
        self._log(f"Test {side.upper()} | ~${notional:.2f} notional | amount={amount}")

        if side == "long":
            entry_side, exit_side = "buy", "sell"
        else:
            entry_side, exit_side = "sell", "buy"

        entry_order = self._place_market(
            entry_side, amount, price, label=f"OPEN {side.upper()}"
        )
        time.sleep(2)

        pos_side, pos_amount = self._fetch_position_amount()
        if pos_side != side or pos_amount <= 0:
            raise RuntimeError(
                f"Позиция после входа не найдена: expected {side}, got {pos_side} ({pos_amount})"
            )

        close_amount = float(self.exchange.amount_to_precision(self.symbol, pos_amount))
        exit_price = self._reference_price()
        exit_order = self._place_market(
            exit_side,
            close_amount,
            exit_price,
            reduce_only=True,
            label=f"CLOSE {side.upper()}",
        )
        time.sleep(2)

        pos_side_after, pos_amount_after = self._fetch_position_amount()
        if pos_amount_after > 0:
            self._log(
                f"WARNING: осталась позиция {pos_side_after} {pos_amount_after}, пробую закрыть..."
            )
            cleanup_side = "sell" if pos_side_after == "long" else "buy"
            self._place_market(
                cleanup_side,
                pos_amount_after,
                self._reference_price(),
                reduce_only=True,
                label="CLEANUP",
            )

        return TestOrderResult(
            side=side,
            amount=close_amount,
            entry_price=price,
            exit_price=exit_price,
            entry_order=entry_order,
            exit_order=exit_order,
        )

    def run(self, side: TestSide = "long") -> list[TestOrderResult]:
        self._log(f"=== Test orders | {self.symbol} | side={side} ===")
        available, equity = fetch_account_balances(self.exchange)
        self._log(f"Balance: ${equity:.2f} (available ${available:.2f})")

        if equity < self.live.min_notional_usd:
            raise ValueError(
                f"Баланс ${equity:.2f} меньше min_notional ${self.live.min_notional_usd:.2f}"
            )

        existing_side, existing_amount = self._fetch_position_amount()
        if existing_amount > 0:
            raise ValueError(
                f"Уже есть открытая позиция {existing_side} {existing_amount}. "
                "Закройте её вручную перед тестом."
            )

        self._setup()
        results: list[TestOrderResult] = []

        try:
            if side in ("long", "both"):
                results.append(self._roundtrip("long"))
            if side in ("short", "both"):
                results.append(self._roundtrip("short"))
        except Exception as exc:
            self.notifier.notify_exception(
                mode="TEST",
                symbol=self.symbol,
                timeframe="—",
                exc=exc,
                context="test-orders",
            )
            raise

        available_after, equity_after = fetch_account_balances(self.exchange)
        self._log(f"Done. Balance: ${equity_after:.2f} (was ${equity:.2f})")
        for item in results:
            self._log(
                f"  {item.side.upper()}: amount={item.amount} | "
                f"entry~{item.entry_price:.4f} exit~{item.exit_price:.4f} | "
                f"orders={item.entry_order.get('id')} -> {item.exit_order.get('id')}"
            )

        self.notifier.notify_info(
            "Test orders OK",
            (
                f"Pair: {self.symbol} | side={side}\n"
                f"Balance: ${equity:.2f} -> ${equity_after:.2f}\n"
                + "\n".join(
                    f"{r.side.upper()}: {r.amount} @ ~{r.entry_price:.4f}" for r in results
                )
            ),
        )
        return results


def run_test_orders(config: AppConfig, *, side: TestSide = "long") -> list[TestOrderResult]:
    return LiveOrderTester(config).run(side=side)
