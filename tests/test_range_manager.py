from __future__ import annotations

import tomllib

from utils.range_manager import RangeManager


def test_range_manager_loads_nested_indicator_param_tables(tmp_path):
    ranges_path = tmp_path / "indicator_ranges.toml"
    ranges_path.write_text(
        """
[rsi.period]
min = 7
max = 21
step = 1
default = 14
description = "RSI period"

[volume_oscillator.method]
options = ["ema", "sma"]
default = "ema"
description = "MA method"
""".strip(),
        encoding="utf-8",
    )

    manager = RangeManager(ranges_path)

    assert manager.get_all_categories() == ["rsi", "volume_oscillator"]
    assert manager.get_category_params("rsi") == ["period"]
    assert manager.get_range("rsi", "period").default == 14
    assert manager.get_range("volume_oscillator", "method").options == ["ema", "sma"]


def test_range_manager_save_preserves_nested_indicator_param_tables(tmp_path):
    ranges_path = tmp_path / "indicator_ranges.toml"
    ranges_path.write_text(
        """
[rsi.period]
min = 7
max = 21
step = 1
default = 14
description = "RSI period"
""".strip(),
        encoding="utf-8",
    )
    manager = RangeManager(ranges_path)

    manager.update_range("rsi", "period", default=10)
    manager.save_ranges(backup=False)

    with ranges_path.open("rb") as handle:
        data = tomllib.load(handle)

    assert "rsi.period" not in data
    assert data["rsi"]["period"]["default"] == 10
