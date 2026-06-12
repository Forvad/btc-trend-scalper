__all__ = ["LiveTrader", "run_test_orders"]


def __getattr__(name: str):
    if name == "LiveTrader":
        from .trader import LiveTrader

        return LiveTrader
    if name == "run_test_orders":
        from .test_orders import run_test_orders

        return run_test_orders
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
