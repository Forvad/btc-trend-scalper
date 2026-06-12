from __future__ import annotations

import html
import os
import traceback
from datetime import datetime, timezone
from typing import Literal

import requests
from dotenv import load_dotenv

from src.config import TelegramConfig

PositionSide = Literal["long", "short"]


class TelegramNotifier:
    def __init__(self, config: TelegramConfig) -> None:
        self.config = config
        load_dotenv()
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    @property
    def enabled(self) -> bool:
        return self.config.enabled and bool(self.token) and bool(self.chat_id)

    @staticmethod
    def _balance_line(balance_usd: float | None, equity_usd: float | None = None) -> str:
        if balance_usd is None and equity_usd is None:
            return ""
        # equity = accountValue на HL; balance_usd = доступно для торговли
        equity = equity_usd if equity_usd is not None else balance_usd
        available = balance_usd if balance_usd is not None else equity
        if equity is None:
            return ""
        line = f"\nBalance: ${equity:,.2f}"
        if available is not None and abs(available - equity) > 0.01 and available > 0:
            line += f" (available: ${available:,.2f})"
        return line

    def _send(self, text: str) -> bool:
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            response = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            from loguru import logger

            logger.bind(component="TG").warning(f"send failed: {exc}")
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
        text = (
            f"<b>Bot started</b>\n"
            f"Mode: {mode}\n"
            f"Exchange: {exchange}\n"
            f"Pair: {symbol}\n"
            f"TF: {timeframe}"
            f"{self._balance_line(balance_usd, equity_usd)}"
        )
        self._send(text)

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
        emoji = "🟢" if side == "long" else "🔴"
        size_line = ""
        if size_usd is not None:
            size_line = f"\nSize: ${size_usd:,.2f}"
        if amount is not None:
            size_line += f"\nAmount: {amount}"
        text = (
            f"{emoji} <b>Trade OPEN</b>\n"
            f"Mode: {mode}\n"
            f"Side: {side.upper()}\n"
            f"Pair: {symbol} ({timeframe})\n"
            f"Entry: {price:,.2f}"
            f"{size_line}"
            f"{self._balance_line(balance_usd, equity_usd)}"
        )
        self._send(text)

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
            emoji = "✅"
        elif pnl_usd is not None:
            emoji = "❌"
        else:
            emoji = "🏁"

        pnl_line = ""
        if pnl_usd is not None and pnl_pct is not None:
            pnl_line = f"\nPnL: {pnl_usd:+,.2f} USD ({pnl_pct:+.2f}%)"

        text = (
            f"{emoji} <b>Trade CLOSE</b>\n"
            f"Mode: {mode}\n"
            f"Side: {side.upper()}\n"
            f"Pair: {symbol} ({timeframe})\n"
            f"Entry: {entry_price:,.2f}\n"
            f"Exit: {exit_price:,.2f}\n"
            f"Reason: {reason}"
            f"{pnl_line}"
            f"{self._balance_line(balance_usd, equity_usd)}"
        )
        self._send(text)

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
        context_line = f"\nContext: {html.escape(context)}" if context else ""
        safe_error = html.escape(error[:3500])
        text = (
            f"⚠️ <b>Bot ERROR</b>\n"
            f"Time: {ts}\n"
            f"Mode: {mode}\n"
            f"Pair: {symbol} ({timeframe})"
            f"{context_line}\n"
            f"\n<code>{safe_error}</code>"
        )
        self._send(text)

    def notify_info(self, title: str, body: str) -> None:
        if not self.enabled:
            return
        text = f"<b>{html.escape(title)}</b>\n{html.escape(body)}"
        self._send(text)

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
