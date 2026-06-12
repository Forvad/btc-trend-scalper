from unittest.mock import MagicMock, patch

from src.config import TelegramConfig
from src.notifications.telegram import TelegramNotifier


@patch.dict(
    "os.environ",
    {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "12345"},
)
@patch("src.notifications.telegram.requests.post")
def test_notify_trade_open(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())

    notifier = TelegramNotifier(TelegramConfig())
    assert notifier.enabled

    ok = notifier._send("test")
    assert ok is True
    mock_post.assert_called_once()
    payload = mock_post.call_args.kwargs["json"]
    assert payload["chat_id"] == "12345"
    assert payload["text"] == "test"


def test_balance_line_shows_equity_primary() -> None:
    line = TelegramNotifier._balance_line(800.0, 950.0)
    assert "Balance: $950.00" in line
    assert "available: $800.00" in line


def test_balance_line_single_value() -> None:
    line = TelegramNotifier._balance_line(100.2, 100.2)
    assert line == "\nBalance: $100.20"


@patch("src.notifications.telegram.load_dotenv")
@patch("src.notifications.telegram.os.getenv", return_value="")
def test_disabled_without_token(_getenv: MagicMock, _dotenv: MagicMock) -> None:
    notifier = TelegramNotifier(TelegramConfig())
    assert not notifier.enabled
    assert notifier._send("test") is False


@patch.dict(
    "os.environ",
    {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "12345"},
)
@patch("src.notifications.telegram.requests.post")
def test_notify_error(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())
    notifier = TelegramNotifier(TelegramConfig())

    notifier.notify_error(
        mode="LIVE",
        symbol="HYPE/USDC:USDC",
        timeframe="15m",
        error="market orders require price",
        context="tick",
    )

    payload = mock_post.call_args.kwargs["json"]
    assert "Bot ERROR" in payload["text"]
    assert "market orders require price" in payload["text"]
    assert "Context: tick" in payload["text"]


@patch.dict(
    "os.environ",
    {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "12345"},
)
@patch("src.notifications.telegram.requests.post")
def test_notify_error_disabled_by_config(mock_post: MagicMock) -> None:
    notifier = TelegramNotifier(TelegramConfig(notify_on_error=False))
    notifier.notify_error(
        mode="LIVE",
        symbol="BTC/USDC:USDC",
        timeframe="1h",
        error="boom",
    )
    mock_post.assert_not_called()
