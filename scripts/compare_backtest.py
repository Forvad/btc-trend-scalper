#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest.compare import run_compare
from src.config import load_config

if __name__ == "__main__":
    run_compare(load_config())
