from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from src.backtest.engine import calc_exit_proceeds
from src.config import AppConfig
from src.data import fetch_ohlcv
from src.exchange.hyperliquid_client import create_public_exchange
from src.notifications import NtfyNotifier
from src.strategy import TrendScalperStrategy
from src.strategy.htf import htf_for_timeframe
from src.utils.log import Log, setup_logging
from src.utils.runtime import call_with_timeout

PositionSide = Literal["long", "short"]


@dataclass
class PaperPosition:
    side: PositionSide
    entry_price: float
    entry_time: datetime
    size_usd: float
    quantity: float
    entry_fee_usd: float


@dataclass
class PaperState:
    balance: float
    position: PaperPosition | None = None
    trades: list[dict] = field(default_factory=list)
    total_fees_usd: float = 0.0


class PaperTrader:
    def __init__(self, config: AppConfig, timeframe: str = "15m") -> None:
        self.config = config
        self.timeframe = timeframe
        self.strategy = TrendScalperStrategy(config.strategy_for_timeframe(timeframe))
        self.fees = config.exchange.fees
        self.notifier = NtfyNotifier(config.notifications)
        self.state = PaperState(balance=config.paper.initial_balance)
        self._public_exchange = create_public_exchange(
            config.exchange.id,
            timeout_sec=config.paper.api_timeout_sec,
        )
        self._last_heartbeat = time.monotonic()
        self.log = Log("PAPER")

    def _log(self, message: str) -> None:
        self.log.smart(message)

    def _maybe_heartbeat(self) -> None:
        now = time.monotonic()
        if now - self._last_heartbeat < self.config.paper.heartbeat_interval_sec:
            return
        self._last_heartbeat = now
        self._log("HEARTBEAT — bot is running")

    def _reconnect_public_exchange(self) -> None:
        self._log("Reconnecting market data feed after timeout...")
        self._public_exchange = create_public_exchange(
            self.config.exchange.id,
            timeout_sec=self.config.paper.api_timeout_sec,
        )

    def _report_error(self, exc: BaseException, *, context: str | None = None) -> None:
        self._log(f"Error: {exc}")
        self.notifier.notify_exception(
            mode="PAPER",
            symbol=self.config.symbol,
            timeframe=self.timeframe,
            exc=exc,
            context=context,
        )

    def _equity(self, price: float) -> float:
        equity = self.state.balance
        if self.state.position:
            pos = self.state.position
            if pos.side == "long":
                equity += pos.quantity * price
            else:
                equity += pos.size_usd + pos.quantity * (pos.entry_price - price)
        return equity

    def _open_position(self, side: PositionSide, signal: dict) -> None:
        size_usd = self.state.balance * self.config.paper.position_size_pct
        price = signal["close"]
        entry_fee = size_usd * self.fees.entry_rate()
        quantity = (size_usd - entry_fee) / price

        self.state.position = PaperPosition(
            side=side,
            entry_price=price,
            entry_time=signal["timestamp"].to_pydatetime(),
            size_usd=size_usd,
            quantity=quantity,
            entry_fee_usd=entry_fee,
        )
        self.state.balance -= size_usd + entry_fee
        self.state.total_fees_usd += entry_fee

        label = "LONG" if side == "long" else "SHORT"
        self._log(
            f"{label} {self.config.symbol} @ {price:.2f} | "
            f"size=${size_usd:.2f} | fee=${entry_fee:.2f} | ST={signal['supertrend']:.2f}"
        )
        self.notifier.notify_trade_open(
            mode="PAPER",
            side=side,
            symbol=self.config.symbol,
            timeframe=self.timeframe,
            price=price,
            size_usd=size_usd,
            amount=quantity,
            balance_usd=self.state.balance,
            equity_usd=self._equity(price),
        )

    def _close_position(self, signal: dict, exit_price: float, exit_reason: str) -> None:
        pos = self.state.position
        if pos is None:
            return

        exit_fee_rate = self.fees.exit_rate(exit_reason)
        net_proceeds, net_pnl, pnl_pct, exit_fee = calc_exit_proceeds(
            pos.side, pos.entry_price, exit_price, pos.size_usd, exit_fee_rate
        )
        self.state.balance += net_proceeds
        self.state.total_fees_usd += exit_fee

        trade = {
            "side": pos.side,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "entry_time": pos.entry_time.isoformat(),
            "exit_time": signal["timestamp"].isoformat(),
            "reason": exit_reason,
            "pnl_usd": net_pnl,
            "pnl_pct": pnl_pct,
            "fees_usd": pos.entry_fee_usd + exit_fee,
        }
        self.state.trades.append(trade)
        self.state.position = None

        label = "CLOSE LONG" if pos.side == "long" else "CLOSE SHORT"
        self._log(
            f"{label} {self.config.symbol} @ {exit_price:.2f} | "
            f"reason={exit_reason} | fee=${exit_fee:.2f} | "
            f"PnL={net_pnl:+.2f} USD ({pnl_pct:+.2f}%)"
        )
        self.notifier.notify_trade_close(
            mode="PAPER",
            side=pos.side,
            symbol=self.config.symbol,
            timeframe=self.timeframe,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            reason=exit_reason,
            pnl_usd=net_pnl,
            pnl_pct=pnl_pct,
            balance_usd=self.state.balance,
            equity_usd=self.state.balance,
        )

    def tick(self) -> dict:
        df = fetch_ohlcv(
            symbol=self.config.symbol,
            timeframe=self.timeframe,
            limit=self.config.backtest.candles_limit,
            exchange=self._public_exchange,
        )
        htf_df = None
        if self.strategy.config.enhancements.needs_htf():
            htf_df = fetch_ohlcv(
                symbol=self.config.symbol,
                timeframe=htf_for_timeframe(self.timeframe),
                limit=self.config.backtest.candles_limit,
                exchange=self._public_exchange,
            )
        signal = self.strategy.latest_signal(df, htf_df)
        action = "hold"

        if self.state.position is None:
            if signal["long_signal"]:
                self._open_position("long", signal)
                action = "long"
            elif signal["short_signal"]:
                self._open_position("short", signal)
                action = "short"
        else:
            pos = self.state.position
            exit_price = None
            exit_reason = None

            if pos.side == "long":
                if signal["long_exit_tp"]:
                    exit_price = signal["bb_upper"]
                    exit_reason = "take_profit_bb"
                elif signal["long_exit_stop"]:
                    exit_price = signal["supertrend"]
                    exit_reason = "stop_supertrend"
            else:
                if signal["short_exit_tp"]:
                    exit_price = signal["bb_lower"]
                    exit_reason = "take_profit_bb"
                elif signal["short_exit_stop"]:
                    exit_price = signal["supertrend"]
                    exit_reason = "stop_supertrend"

            if exit_price is not None:
                self._close_position(signal, exit_price, exit_reason)
                action = "close"

        price = signal["close"]
        equity = self._equity(price)

        return {
            "action": action,
            "signal": signal,
            "balance": self.state.balance,
            "equity": equity,
            "position": self.state.position is not None,
            "position_side": self.state.position.side if self.state.position else None,
            "trades_count": len(self.state.trades),
            "total_fees_usd": self.state.total_fees_usd,
        }

    def run(self) -> None:
        setup_logging()
        try:
            fees = self.fees
            self._log(
                f"Paper-trading | {self.config.exchange.id} | {self.config.symbol} {self.timeframe} | "
                f"fees: maker={fees.maker_pct}% taker={fees.taker_pct}% | "
                f"balance=${self.state.balance:.2f}"
            )
            self.notifier.notify_bot_started(
                mode="PAPER",
                symbol=self.config.symbol,
                timeframe=self.timeframe,
                exchange=self.config.exchange.id,
                balance_usd=self.state.balance,
                equity_usd=self.state.balance,
            )
            while True:
                tick_started = time.monotonic()
                try:
                    status = call_with_timeout(self.tick, self.config.paper.tick_timeout_sec)
                    side = status["position_side"] or "FLAT"
                    elapsed = time.monotonic() - tick_started
                    self._log(
                        f"Price={status['signal']['close']:.2f} | "
                        f"Equity=${status['equity']:.2f} | "
                        f"Fees=${status['total_fees_usd']:.2f} | "
                        f"Position={side} | tick={elapsed:.1f}s"
                    )
                except TimeoutError as exc:
                    self._report_error(exc, context="tick timeout")
                    self._reconnect_public_exchange()
                except Exception as exc:
                    self._report_error(exc, context="tick")
                self._maybe_heartbeat()
                time.sleep(self.config.paper.poll_interval_sec)
        except Exception as exc:
            self._report_error(exc, context="run")
            raise
