from __future__ import annotations

import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

LOG_TZ = ZoneInfo("Europe/Moscow")  # UTC+3
LOG_TZ_LABEL = "MSK"

_CONFIGURED = False


def _localize_log_time(record: dict) -> None:
    record["time"] = record["time"].astimezone(LOG_TZ)


def setup_logging(
    *,
    level: str = "INFO",
    log_dir: str | Path = "logs",
    file_logging: bool = True,
) -> None:
    """Единая настройка loguru для CLI и ботов."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    logger.remove()
    logger.configure(extra={"component": "APP"}, patcher=_localize_log_time)

    console_fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
        f"<dim>{LOG_TZ_LABEL}</dim> │ "
        "<level>{level: <8}</level> │ "
        "<cyan>{extra[component]:^8}</cyan> │ "
        "<level>{message}</level>"
    )
    logger.add(
        sys.stderr,
        format=console_fmt,
        level=level,
        colorize=True,
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )

    if file_logging:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        file_fmt = (
            f"{{time:YYYY-MM-DD HH:mm:ss}} {LOG_TZ_LABEL} | "
            "{level: <8} | {extra[component]:^8} | {message}"
        )
        logger.add(
            path / "bot_{time:YYYY-MM-DD}.log",
            format=file_fmt,
            level=level,
            rotation="00:00",
            retention="14 days",
            encoding="utf-8",
            enqueue=True,
        )

    _CONFIGURED = True


class Log:
    """Цветные категории логов для торгового бота."""

    def __init__(self, component: str) -> None:
        self._log = logger.bind(component=component)
        self.component = component

    def debug(self, message: str) -> None:
        self._log.debug(message)

    def info(self, message: str) -> None:
        self._log.info(message)

    def success(self, message: str) -> None:
        self._log.success(message)

    def warning(self, message: str) -> None:
        self._log.warning(message)

    def error(self, message: str) -> None:
        self._log.error(message)

    def section(self, title: str) -> None:
        line = f"{'═' * 3} {title} {'═' * 3}"
        self._log.opt(colors=True).info(f"\n<bold><white>{line}</white></bold>")

    def order(self, message: str) -> None:
        self._log.opt(colors=True).info(f"<yellow>▸ ORDER</yellow>   {message}")

    def trade(self, message: str) -> None:
        self._log.opt(colors=True).success(f"<green>▸ TRADE</green>   {message}")

    def bracket(self, message: str) -> None:
        self._log.opt(colors=True).info(f"<magenta>▸ BRACKET</magenta> {message}")

    def tick(self, message: str) -> None:
        self._log.opt(colors=True).info(f"<blue>▸ TICK</blue>    {message}")

    def heartbeat(self, message: str) -> None:
        self._log.opt(colors=True).debug(f"<dim>▸ PULSE</dim>    {message}")

    def data(self, message: str) -> None:
        self._log.opt(colors=True).info(f"<cyan>▸ DATA</cyan>    {message}")

    def metric(self, label: str, value: str, *, good: bool | None = None) -> None:
        if good is True:
            color = "green"
        elif good is False:
            color = "red"
        else:
            color = "white"
        self._log.opt(colors=True).info(
            f"<bold>{label}:</bold> <{color}>{value}</{color}>"
        )

    def smart(self, message: str) -> None:
        """Маршрутизация старых print-сообщений в цветные категории."""
        text = message.strip()
        upper = text.upper()

        if upper.startswith("ERROR:") or upper.startswith("ERROR "):
            self.error(text.split(":", 1)[-1].strip())
            return
        if "WARNING:" in upper or upper.startswith("WARNING"):
            self.warning(text.split(":", 1)[-1].strip())
            return
        if upper.startswith("ORDER ") or "ORDER SL" in upper or "ORDER TP" in upper:
            self.order(text.replace("ORDER ", "", 1) if text.startswith("ORDER ") else text)
            return
        if upper.startswith("CANCELED") or upper.startswith("CANCELLED"):
            self.order(text)
            return
        if "BRACKET" in upper or text.startswith("Bracket"):
            self.bracket(text)
            return
        if "HEARTBEAT" in upper or "PULSE" in upper:
            self.heartbeat(text)
            return
        if any(k in upper for k in ("OPEN LONG", "OPEN SHORT", "CLOSE LONG", "CLOSE SHORT")):
            self.trade(text)
            return
        if " filled" in text.lower() or text.endswith("filled"):
            self.trade(text)
            return
        if "PRICE=" in upper and "ACTION=" in upper:
            self.tick(text)
            return
        if "RECONNECT" in upper:
            self.warning(text)
            return
        if upper.startswith("ЗАГРУЗКА") or upper.startswith("LOADING"):
            self.data(text)
            return

        self.info(text)


# Глобальный логгер для main.py и скриптов
app_log = Log("APP")
