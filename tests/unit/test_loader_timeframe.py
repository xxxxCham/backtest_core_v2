import pandas as pd
import pytest

from data.loader import _timeframe_to_timedelta


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
