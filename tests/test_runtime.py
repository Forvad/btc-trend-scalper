import time

import pytest

from src.utils.runtime import call_with_timeout


def test_call_with_timeout_returns_value() -> None:
    assert call_with_timeout(lambda: 42, 5) == 42


def test_call_with_timeout_raises_on_slow_call() -> None:
    def slow() -> None:
        time.sleep(0.2)

    with pytest.raises(TimeoutError, match="timed out"):
        call_with_timeout(slow, 0.05)
