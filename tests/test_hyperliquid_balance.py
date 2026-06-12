from src.exchange.hyperliquid_client import _parse_perp_balances, _parse_spot_usdc


def test_parse_perp_cross_margin_uses_account_value() -> None:
    balance = {
        "USDC": {"total": 100.2, "used": 0.0, "free": 0.0},
        "info": {
            "marginSummary": {
                "accountValue": "100.2",
                "totalMarginUsed": "0.0",
            },
            "withdrawable": "100.2",
        },
    }
    available, equity = _parse_perp_balances(balance)
    assert equity == 100.2
    assert available == 100.2


def test_parse_perp_when_free_missing_uses_equity() -> None:
    balance = {
        "USDC": {"total": 100.2, "used": 5.0},
        "info": {
            "marginSummary": {
                "accountValue": "100.2",
                "totalMarginUsed": "5.0",
            },
            "withdrawable": "0.0",
        },
    }
    available, equity = _parse_perp_balances(balance)
    assert equity == 100.2
    assert available == 95.2


def test_fetch_account_balances_no_double_count_unified() -> None:
    from unittest.mock import MagicMock

    from src.exchange.hyperliquid_client import fetch_account_balances

    spot_like = {
        "USDC": {"total": 100.2, "free": 100.2, "used": 0.0},
        "info": {
            "balances": [{"coin": "USDC", "total": "100.2", "hold": "0"}],
        },
    }
    exchange = MagicMock()
    exchange.fetch_balance.side_effect = [spot_like, spot_like]

    available, equity = fetch_account_balances(exchange)
    assert equity == 100.2
    assert available == 100.2
    assert exchange.fetch_balance.call_count == 1


def test_fetch_account_balances_adds_separate_spot() -> None:
    from unittest.mock import MagicMock

    from src.exchange.hyperliquid_client import fetch_account_balances

    perp = {
        "USDC": {"total": 80.0, "free": 0.0, "used": 20.0},
        "info": {
            "marginSummary": {
                "accountValue": "80.0",
                "totalMarginUsed": "20.0",
            },
            "withdrawable": "60.0",
        },
    }
    spot = {
        "USDC": {"total": 20.0},
        "info": {"balances": [{"coin": "USDC", "total": "20.0", "hold": "0"}]},
    }
    exchange = MagicMock()
    exchange.fetch_balance.side_effect = [perp, spot]

    available, equity = fetch_account_balances(exchange)
    assert equity == 100.0
    assert available == 80.0


def test_parse_spot_usdc_from_balances_list() -> None:
    balance = {
        "USDC": {},
        "info": {
            "balances": [{"coin": "USDC", "total": "50.5", "hold": "0"}],
        },
    }
    assert _parse_spot_usdc(balance) == 50.5
