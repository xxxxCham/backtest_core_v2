from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tools.export_builder_session_summary_backup import (
    DEFAULT_OUTPUT_DIR,
    REPO_ROOT,
    export_builder_session_summary_backup,
)


def _write_minimal_session(root: Path) -> None:
    session_dir = root / "session_001"
    session_dir.mkdir(parents=True)
    (session_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "session_id": "session_001",
                "status": "success",
                "iterations": [],
                "leaderboard": [],
            },
        ),
        encoding="utf-8",
    )


def test_default_builder_session_export_dir_is_outside_repo():
    assert not DEFAULT_OUTPUT_DIR.resolve().is_relative_to(REPO_ROOT.resolve())
    assert "backtest_results" in DEFAULT_OUTPUT_DIR.parts


def test_builder_session_export_refuses_repo_output(tmp_path):
    source_root = tmp_path / "source_sessions"
    _write_minimal_session(source_root)
    repo_output = REPO_ROOT / ".tmp_export_should_be_refused"

    with pytest.raises(ValueError, match="dépôt"):
        export_builder_session_summary_backup(source_root, repo_output)


def test_builder_session_export_writes_to_local_output_outside_repo(tmp_path):
    source_root = tmp_path / "source_sessions"
    _write_minimal_session(source_root)

    with tempfile.TemporaryDirectory(prefix="builder_session_export_") as temp_dir:
        output_dir = Path(temp_dir) / "export"
        result = export_builder_session_summary_backup(source_root, output_dir)

        assert result["exported"] == 1
        assert (output_dir / "manifest.csv").exists()
        assert (output_dir / "session_summaries.ndjson.gz").exists()
