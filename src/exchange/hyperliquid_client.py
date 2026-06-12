from __future__ import annotations

import os

import ccxt
from dotenv import load_dotenv


def has_credentials() -> bool:
    load_dotenv()
    return bool(os.getenv("HYPERLIQUID_PRIVATE_KEY", "").strip()) and bool(
        os.getenv("HYPERLIQUID_WALLET_ADDRESS", "").strip()
    )


def create_hyperliquid_exchange(
    *,
    require_auth: bool = True,
    timeout_sec: int = 30,
) -> ccxt.Exchange:
    load_dotenv()
    timeout_ms = timeout_sec * 1000
    common = {"enableRateLimit": True, "timeout": timeout_ms}

    private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY", "").strip()
    wallet_address = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "").strip()

    if not private_key or not wallet_address:
        if require_auth:
            raise ValueError(
                "Задайте HYPERLIQUID_PRIVATE_KEY и HYPERLIQUID_WALLET_ADDRESS в файле .env"
            )
        exchange = ccxt.hyperliquid(common)
        exchange.load_markets()
        return exchange

    exchange = ccxt.hyperliquid(
        {
            **common,
            "walletAddress": wallet_address,
            "privateKey": private_key,
        }
    )
    exchange.load_markets()
    return exchange


def create_public_exchange(exchange_id: str = "hyperliquid", *, timeout_sec: int = 30) -> ccxt.Exchange:
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True, "timeout": timeout_sec * 1000})
    exchange.load_markets()
    return exchange


def _parse_perp_balances(balance: dict) -> tuple[float, float]:
    """Парсит perp clearinghouseState: (available, equity)."""
    info = balance.get("info") or {}
    margin = info.get("marginSummary") or info.get("crossMarginSummary") or {}

    equity = float(margin.get("accountValue") or 0)
    withdrawable = float(info.get("withdrawable") or 0)
    margin_used = float(margin.get("totalMarginUsed") or 0)

    usdc = balance.get("USDC") or {}
    if not equity:
        equity = float(usdc.get("total") or 0)

    # ccxt не заполняет free для cross margin — считаем сами
    available = withdrawable
    if available <= 0 and equity > 0:
        available = max(equity - margin_used, 0)
    if available <= 0:
        available = float(usdc.get("free") or 0)
    if available <= 0 and equity > 0:
        available = equity

    return available, equity


def _parse_spot_usdc(balance: dict) -> float:
    usdc = balance.get("USDC") or {}
    total = float(usdc.get("total") or 0)
    if total > 0:
        return total

    info = balance.get("info") or {}
    for item in info.get("balances") or []:
        if (item.get("coin") or "").upper() in ("USDC", "USDC.E"):
            return float(item.get("total") or 0)
    return 0.0


def derive_api_wallet_address(private_key: str) -> str:
    """Адрес API wallet, соответствующий приватному ключу."""
    exchange = ccxt.hyperliquid()
    return exchange.privateKeyToAddress(private_key.strip())


def diagnose_wallet_setup() -> list[str]:
    """Проверяет типичные ошибки настройки Hyperliquid."""
    load_dotenv()
    private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY", "").strip()
    wallet_address = os.getenv("HYPERLIQUID_WALLET_ADDRESS", "").strip()
    warnings: list[str] = []

    if not private_key or not wallet_address:
        return warnings

    try:
        api_wallet = derive_api_wallet_address(private_key)
    except Exception:
        return warnings

    if api_wallet.lower() == wallet_address.lower():
        warnings.append(
            "HYPERLIQUID_WALLET_ADDRESS совпадает с адресом API wallet. "
            "Укажите адрес основного аккаунта (куда вы вносите USDC в приложении Hyperliquid), "
            "а не адрес API wallet из настроек API."
        )

    try:
        exchange = create_hyperliquid_exchange()
        _available, equity = fetch_account_balances(exchange)
        if equity <= 0:
            warnings.append(
                f"Баланс по адресу {wallet_address[:10]}...{wallet_address[-6:]} = $0. "
                "Проверьте, что в .env указан основной адрес аккаунта с депозитом."
            )
    except Exception:
        pass

    return warnings


def _has_perp_margin_account(balance: dict) -> bool:
    info = balance.get("info") or {}
    margin = info.get("marginSummary") or info.get("crossMarginSummary") or {}
    return bool(float(margin.get("accountValue") or 0))


def fetch_account_balances(exchange: ccxt.Exchange) -> tuple[float, float]:
    """
    Возвращает (available USDC, equity USDC).
    equity — то, что видно в UI Hyperliquid (accountValue или spot USDC).
    """
    perp = exchange.fetch_balance()
    available, equity = _parse_perp_balances(perp)

    # Unified/spot-only: default fetch_balance уже вернул spot USDC — не дублируем
    if not _has_perp_margin_account(perp):
        return available, equity

    try:
        spot = exchange.fetch_balance({"type": "spot"})
        spot_usdc = _parse_spot_usdc(spot)
        if spot_usdc > 0:
            equity += spot_usdc
            available += spot_usdc
    except Exception:
        pass

    return available, equity


def fetch_available_usdc(exchange: ccxt.Exchange) -> float:
    available, _equity = fetch_account_balances(exchange)
    return available
