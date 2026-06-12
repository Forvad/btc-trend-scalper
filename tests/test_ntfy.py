from unittest.mock import MagicMock, patch

from src.config import NotificationsConfig
from src.notifications.ntfy import NtfyNotifier


@patch.dict("os.environ", {"NTFY_TOPIC": "mylogin"})
@patch("src.notifications.ntfy.requests.post")
def test_send_posts_to_ntfy_topic(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())

    notifier = NtfyNotifier(NotificationsConfig())
    assert notifier.enabled

    ok = notifier._send("Test title", "hello body")
    assert ok is True
    mock_post.assert_called_once()
    assert mock_post.call_args.args[0] == "https://ntfy.sh/mylogin"
    assert mock_post.call_args.kwargs["data"] == b"hello body"
    assert mock_post.call_args.kwargs["headers"]["Title"] == "Test title"


def test_balance_line_shows_equity_primary() -> None:
    line = NtfyNotifier._balance_line(800.0, 950.0)
    assert "Balance: $950.00" in line
    assert "available: $800.00" in line


def test_balance_line_single_value() -> None:
    line = NtfyNotifier._balance_line(100.2, 100.2)
    assert line == "\nBalance: $100.20"


@patch("src.notifications.ntfy.load_dotenv")
@patch("src.notifications.ntfy.os.getenv", return_value="")
def test_disabled_without_topic(_getenv: MagicMock, _dotenv: MagicMock) -> None:
    notifier = NtfyNotifier(NotificationsConfig())
    assert not notifier.enabled
    assert notifier._send("t", "b") is False


@patch.dict("os.environ", {"NTFY_TOPIC": "mylogin", "NTFY_SERVER": "https://ntfy.example.com"})
@patch("src.notifications.ntfy.requests.post")
def test_custom_server(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())
    notifier = NtfyNotifier(NotificationsConfig())
    notifier._send("t", "b")
    assert mock_post.call_args.args[0] == "https://ntfy.example.com/mylogin"


@patch.dict("os.environ", {"NTFY_TOPIC": "mylogin"})
@patch("src.notifications.ntfy.requests.post")
def test_notify_error(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())
    notifier = NtfyNotifier(NotificationsConfig())

    notifier.notify_error(
        mode="LIVE",
        symbol="HYPE/USDC:USDC",
        timeframe="15m",
        error="market orders require price",
        context="tick",
    )

    body = mock_post.call_args.kwargs["data"].decode()
    assert "market orders require price" in body
    assert "Context: tick" in body
    assert mock_post.call_args.kwargs["headers"]["Priority"] == "urgent"


@patch.dict("os.environ", {"NTFY_TOPIC": "mylogin"})
@patch("src.notifications.ntfy.requests.post")
def test_notify_error_disabled_by_config(mock_post: MagicMock) -> None:
    notifier = NtfyNotifier(NotificationsConfig(notify_on_error=False))
    notifier.notify_error(
        mode="LIVE",
        symbol="BTC/USDC:USDC",
        timeframe="1h",
        error="boom",
    )
    mock_post.assert_not_called()
