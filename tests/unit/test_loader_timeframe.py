from pathlib import Path

import pandas as pd
import pytest

from cli.commands import _resolve_data_path
from data.loader import _scan_data_files_for_dir, _timeframe_to_timedelta
from utils.config import _default_data_dir


@pytest.mark.parametrize(
    "timeframe,expected",
    [
        ("1m", pd.Timedelta(minutes=1)),
        ("15m", pd.Timedelta(minutes=15)),
        ("1h", pd.Timedelta(hours=1)),
        ("4h", pd.Timedelta(hours=4)),
        ("1d", pd.Timedelta(days=1)),
        ("1w", pd.Timedelta(weeks=1)),
        ("1M", pd.Timedelta(days=30)),
        ("3M", pd.Timedelta(days=90)),
    ],
)
def test_timeframe_to_timedelta_valid_units(timeframe: str, expected: pd.Timedelta) -> None:
    assert _timeframe_to_timedelta(timeframe) == expected


@pytest.mark.parametrize(
    "timeframe",
    ["", "M", "0h", "-1h", "1ME", "abc", "1q", None],
)
def test_timeframe_to_timedelta_invalid_values(timeframe: str) -> None:
    with pytest.raises(ValueError):
        _timeframe_to_timedelta(timeframe)  # type: ignore[arg-type]


def test_default_data_dir_uses_loader_resolution_when_env_is_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    resolved_dir = tmp_path / "resolved_data"
    resolved_dir.mkdir()

    monkeypatch.setenv("TRADX_DATA_ROOT", str(tmp_path / "missing_tradx_root"))
    monkeypatch.setattr("data.loader._get_data_dir", lambda: resolved_dir)

    assert _default_data_dir() == resolved_dir


def test_resolve_data_path_uses_loader_resolved_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    resolved_dir = tmp_path / "resolved_data"
    resolved_dir.mkdir()
    target_file = resolved_dir / "BTCUSDC_1h.parquet"
    target_file.write_text("stub", encoding="utf-8")

    monkeypatch.delenv("BACKTEST_DATA_DIR", raising=False)
    monkeypatch.setattr("data.loader._get_data_dir", lambda: resolved_dir)

    assert _resolve_data_path("BTCUSDC_1h.parquet") == target_file


def test_scan_data_files_for_dir_ignores_non_market_artifacts(tmp_path: Path) -> None:
    valid = tmp_path / "BTCUSDC_1h.parquet"
    valid.write_text("stub", encoding="utf-8")

    ignored_vscode_dir = tmp_path / ".vscode"
    ignored_vscode_dir.mkdir()
    (ignored_vscode_dir / "extensions.json").write_text("{}", encoding="utf-8")

    ignored_misc = tmp_path / "notes.json"
    ignored_misc.write_text("{}", encoding="utf-8")

    invalid_name = tmp_path / "BTCUSDC_backup.parquet"
    invalid_name.write_text("stub", encoding="utf-8")

    assert _scan_data_files_for_dir(str(tmp_path)) == (valid,)
