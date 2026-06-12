from __future__ import annotations

import os
import traceback
from datetime import datetime, timezone
from typing import Literal

import requests
from dotenv import load_dotenv

from src.config import NotificationsConfig

PositionSide = Literal["long", "short"]


class NtfyNotifier:
    """Уведомления через ntfy.sh (топик = логин из приложения, см. NTFY_TOPIC в .env)."""

    def __init__(self, config: NotificationsConfig) -> None:
        self.config = config
        load_dotenv()
        self.topic = os.getenv("NTFY_TOPIC", "").strip()
        server = os.getenv("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/")
        self.server = server or "https://ntfy.sh"

    @property
    def enabled(self) -> bool:
        return self.config.enabled and bool(self.topic)

    @staticmethod
    def _balance_line(balance_usd: float | None, equity_usd: float | None = None) -> str:
        if balance_usd is None and equity_usd is None:
            return ""
        equity = equity_usd if equity_usd is not None else balance_usd
        available = balance_usd if balance_usd is not None else equity
        if equity is None:
            return ""
        line = f"\nBalance: ${equity:,.2f}"
        if available is not None and abs(available - equity) > 0.01 and available > 0:
            line += f" (available: ${available:,.2f})"
        return line

    def _send(self, title: str, body: str, *, priority: str = "default") -> bool:
        if not self.enabled:
            return False
        url = f"{self.server}/{self.topic}"
        headers = {
            "Title": title,
            "Priority": priority,
            "Tags": "chart_with_upwards_trend",
        }
        try:
            response = requests.post(
                url,
                data=body.encode("utf-8"),
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            from loguru import logger

            logger.bind(component="NTFY").warning(f"send failed: {exc}")
            return False

    def notify_bot_started(
        self,
        *,
        mode: str,
        symbol: str,
        timeframe: str,
        exchange: str,
        balance_usd: float | None = None,
        equity_usd: float | None = None,
    ) -> None:
        if not self.config.notify_on_start:
            return
        body = (
            f"Mode: {mode}\n"
            f"Exchange: {exchange}\n"
            f"Pair: {symbol}\n"
            f"TF: {timeframe}"
            f"{self._balance_line(balance_usd, equity_usd)}"
        )
        self._send("Bot started", body)

    def notify_trade_open(
        self,
        *,
        mode: str,
        side: PositionSide,
        symbol: str,
        timeframe: str,
        price: float,
        size_usd: float | None = None,
        amount: float | None = None,
        balance_usd: float | None = None,
        equity_usd: float | None = None,
    ) -> None:
        if not self.config.notify_on_trade:
            return
        emoji = "LONG" if side == "long" else "SHORT"
        size_line = ""
        if size_usd is not None:
            size_line = f"\nSize: ${size_usd:,.2f}"
        if amount is not None:
            size_line += f"\nAmount: {amount}"
        body = (
            f"Mode: {mode}\n"
            f"Side: {side.upper()}\n"
            f"Pair: {symbol} ({timeframe})\n"
            f"Entry: {price:,.2f}"
            f"{size_line}"
            f"{self._balance_line(balance_usd, equity_usd)}"
        )
        self._send(f"Trade OPEN {emoji}", body, priority="high")

    def notify_trade_close(
        self,
        *,
        mode: str,
        side: PositionSide,
        symbol: str,
        timeframe: str,
        entry_price: float,
        exit_price: float,
        reason: str,
        pnl_usd: float | None = None,
        pnl_pct: float | None = None,
        balance_usd: float | None = None,
        equity_usd: float | None = None,
    ) -> None:
        if not self.config.notify_on_trade:
            return
        if pnl_usd is not None and pnl_usd >= 0:
            title = "Trade CLOSE +"
        elif pnl_usd is not None:
            title = "Trade CLOSE -"
        else:
            title = "Trade CLOSE"

        pnl_line = ""
        if pnl_usd is not None and pnl_pct is not None:
            pnl_line = f"\nPnL: {pnl_usd:+,.2f} USD ({pnl_pct:+.2f}%)"

        body = (
            f"Mode: {mode}\n"
            f"Side: {side.upper()}\n"
            f"Pair: {symbol} ({timeframe})\n"
            f"Entry: {entry_price:,.2f}\n"
            f"Exit: {exit_price:,.2f}\n"
            f"Reason: {reason}"
            f"{pnl_line}"
            f"{self._balance_line(balance_usd, equity_usd)}"
        )
        self._send(title, body, priority="high")

    def notify_error(
        self,
        *,
        mode: str,
        symbol: str,
        timeframe: str,
        error: str,
        context: str | None = None,
    ) -> None:
        if not self.config.notify_on_error:
            return
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        context_line = f"\nContext: {context}" if context else ""
        safe_error = error[:3500]
        body = (
            f"Time: {ts}\n"
            f"Mode: {mode}\n"
            f"Pair: {symbol} ({timeframe})"
            f"{context_line}\n\n"
            f"{safe_error}"
        )
        self._send("Bot ERROR", body, priority="urgent")

    def notify_info(self, title: str, body: str) -> None:
        if not self.enabled:
            return
        self._send(title, body)

    def notify_exception(
        self,
        *,
        mode: str,
        symbol: str,
        timeframe: str,
        exc: BaseException,
        context: str | None = None,
    ) -> None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.notify_error(
            mode=mode,
            symbol=symbol,
            timeframe=timeframe,
            error=tb,
            context=context,
        )
