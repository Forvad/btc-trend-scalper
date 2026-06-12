import pytest

from src.strategy.exits import smart_tp_valid


def test_smart_tp_blocks_bad_long_exit() -> None:
    assert not smart_tp_valid("long", 100_000.0, 99_000.0, 0.30)


def test_smart_tp_allows_good_long_exit() -> None:
    assert smart_tp_valid("long", 100_000.0, 100_500.0, 0.30)
