from __future__ import annotations

import pandas as pd

from indicators import registry


class _FakeBank:
    def __init__(self) -> None:
        self.calls = 0

    def get_data_hash(self, df: pd.DataFrame) -> str:
        self.calls += 1
        first_idx = str(df.index[0]) if len(df) else ""
        last_idx = str(df.index[-1]) if len(df) else ""
        return f"hash-{len(df)}-{first_idx}-{last_idx}"


def _ohlcv(n: int = 12) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "open": range(n),
            "high": range(1, n + 1),
            "low": range(n),
            "close": range(2, n + 2),
            "volume": [100.0] * n,
        },
        index=idx,
    )


def test_indicator_data_hash_reuses_only_matching_signature() -> None:
    bank = _FakeBank()
    df = _ohlcv()

    first_hash = registry._get_or_compute_data_hash(df, bank)
    second_hash = registry._get_or_compute_data_hash(df, bank)

    assert first_hash == second_hash
    assert bank.calls == 1


def test_indicator_data_hash_ignores_inherited_parent_attrs_on_slice() -> None:
    bank = _FakeBank()
    df = _ohlcv()
    full_hash = registry._get_or_compute_data_hash(df, bank)
    full_signature = df.attrs[registry._INDICATOR_DATA_HASH_SIGNATURE_ATTR]

    sliced = df.iloc[:5].copy()
    sliced.attrs[registry._INDICATOR_DATA_HASH_ATTR] = full_hash
    sliced.attrs[registry._INDICATOR_DATA_HASH_SIGNATURE_ATTR] = full_signature

    slice_hash = registry._get_or_compute_data_hash(sliced, bank)

    assert slice_hash != full_hash
    assert sliced.attrs[registry._INDICATOR_DATA_HASH_ATTR] == slice_hash
    assert sliced.attrs[registry._INDICATOR_DATA_HASH_SIGNATURE_ATTR] != full_signature
