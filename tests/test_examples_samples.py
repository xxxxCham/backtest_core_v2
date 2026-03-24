from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = ROOT / "examples" / "end_to_end"


def test_sample_ohlcv_csv_files_are_parseable() -> None:
    for name in ("ohlcv_BTCUSDT_1h.csv", "ohlcv_ETHUSDT_4h.csv"):
        df = pd.read_csv(EXAMPLES_ROOT / "data" / name)
        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
        assert len(df) == 8


def test_native_result_sample_contains_expected_fields() -> None:
    metadata_path = EXAMPLES_ROOT / "stores" / "result_storage_native" / "native_run_btc_1h" / "metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "native_run_btc_1h"
    assert payload["metrics"]["sharpe_ratio"] == 1.28
    assert payload["extra_metadata"]["builder_session_id"] == "demo-sess-btc-1h"


def test_v3_result_sample_contains_schema_version_and_index_exports() -> None:
    metadata_path = EXAMPLES_ROOT / "stores" / "result_store_v3" / "runs" / "v3_run_eth_4h" / "metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] >= 3
    index_df = pd.read_csv(EXAMPLES_ROOT / "stores" / "result_store_v3" / "index.csv")
    assert "run_id" in index_df.columns
    assert "artifact_path" in index_df.columns


def test_legacy_manifest_sample_contains_sidecars() -> None:
    run_dir = EXAMPLES_ROOT / "stores" / "legacy_runner_manifest" / "run_manifest_btc_1h"
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    config = json.loads((run_dir / "config_snapshot.json").read_text(encoding="utf-8"))
    assert metadata["run_id"] == "run_manifest_btc_1h"
    assert metrics["total_return_pct"] == 0.48
    assert config["params"]["fast_period"] == 12