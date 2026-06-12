from pathlib import Path

import yaml

from src.config import load_config


def test_load_config_ignores_unknown_live_keys(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        yaml.dump(
            {
                "live": {
                    "leverage": 5,
                    "use_leverage_for_sizing": True,
                    "future_unknown_option": 123,
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(cfg_file)

    assert config.live.leverage == 5
    assert config.live.use_leverage_for_sizing is True
    assert not hasattr(config.live, "future_unknown_option")
