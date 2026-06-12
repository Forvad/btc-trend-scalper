from unittest.mock import patch

from src.exchange.hyperliquid_client import diagnose_wallet_setup


@patch("src.exchange.hyperliquid_client.fetch_account_balances", return_value=(0.0, 0.0))
@patch("src.exchange.hyperliquid_client.create_hyperliquid_exchange")
@patch("src.exchange.hyperliquid_client.derive_api_wallet_address", return_value="0xabc")
@patch.dict(
    "os.environ",
    {
        "HYPERLIQUID_PRIVATE_KEY": "0x" + "1" * 64,
        "HYPERLIQUID_WALLET_ADDRESS": "0xabc",
    },
)
def test_warn_when_wallet_equals_api_wallet(_mock_ex, _mock_bal, _mock_derive) -> None:
    warnings = diagnose_wallet_setup()
    assert any("основного аккаунта" in w for w in warnings)


@patch("src.exchange.hyperliquid_client.fetch_account_balances", return_value=(100.2, 100.2))
@patch("src.exchange.hyperliquid_client.create_hyperliquid_exchange")
@patch("src.exchange.hyperliquid_client.derive_api_wallet_address", return_value="0xapi")
@patch.dict(
    "os.environ",
    {
        "HYPERLIQUID_PRIVATE_KEY": "0x" + "1" * 64,
        "HYPERLIQUID_WALLET_ADDRESS": "0xmaster",
    },
)
def test_no_warning_when_balance_positive(_mock_ex, _mock_bal, _mock_derive) -> None:
    warnings = diagnose_wallet_setup()
    assert warnings == []
