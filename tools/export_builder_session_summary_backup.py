"""Export Builder session summaries into a Git-friendly backup artifact.

The canonical source remains one ``session_summary.json`` per Builder session:

    <artifacts_root>/_builder_sessions/<session_id>/session_summary.json

This script keeps that one-record-per-session structure in a compressed NDJSON
file and writes a CSV manifest for quick inspection from GitHub.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.result_store import get_builder_sessions_dir

DEFAULT_OUTPUT_DIR = Path("github_backups") / "builder_session_summaries"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object JSON in {path}")
    return payload


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _summary_row(path: Path, payload: dict[str, Any], digest: str, size_bytes: int, index: int) -> dict[str, Any]:
    session_dir = path.parent
    session_id = str(payload.get("session_id") or session_dir.name)
    generation_stats = payload.get("generation_stats") if isinstance(payload.get("generation_stats"), dict) else {}
    return {
        "record_index": index,
        "session_id": session_id,
        "source_path": str(path),
        "source_dir": str(session_dir),
        "sha256": digest,
        "size_bytes": size_bytes,
        "start_time": payload.get("start_time", ""),
        "end_time": payload.get("end_time", ""),
        "status": payload.get("status", ""),
        "model_name": payload.get("model_name", ""),
        "symbol": payload.get("symbol", ""),
        "timeframe": payload.get("timeframe", ""),
        "total_iterations": payload.get("total_iterations", ""),
        "canonical_rate": generation_stats.get("canonical_rate", ""),
        "best_sharpe": payload.get("best_sharpe", ""),
        "best_score": payload.get("best_score", ""),
        "git_commit": payload.get("git_commit", ""),
    }


def export_builder_session_summary_backup(source_root: Path, output_dir: Path) -> dict[str, Any]:
    source_root = source_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_paths = sorted(source_root.glob("*/session_summary.json"))
    manifest_path = output_dir / "manifest.csv"
    archive_path = output_dir / "session_summaries.ndjson.gz"
    checksum_path = output_dir / "session_summaries.ndjson.gz.sha256"
    readme_path = output_dir / "README.md"

    rows: list[dict[str, Any]] = []
    exported = 0
    skipped: list[dict[str, str]] = []

    with gzip.open(archive_path, "wt", encoding="utf-8", newline="\n") as archive:
        for path in summary_paths:
            try:
                raw = path.read_bytes()
                payload = _read_json(path)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                skipped.append({"path": str(path), "error": str(exc)})
                continue

            exported += 1
            digest = _sha256_bytes(raw)
            row = _summary_row(path, payload, digest, len(raw), exported)
            rows.append(row)
            archive.write(
                json.dumps(
                    {
                        "record_index": exported,
                        "session_id": row["session_id"],
                        "source_path": row["source_path"],
                        "sha256": digest,
                        "payload": payload,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                )
                + "\n",
            )

    fieldnames = [
        "record_index",
        "session_id",
        "source_path",
        "source_dir",
        "sha256",
        "size_bytes",
        "start_time",
        "end_time",
        "status",
        "model_name",
        "symbol",
        "timeframe",
        "total_iterations",
        "canonical_rate",
        "best_sharpe",
        "best_score",
        "git_commit",
    ]
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    archive_digest = _sha256_bytes(archive_path.read_bytes())
    checksum_path.write_text(f"{archive_digest}  {archive_path.name}\n", encoding="utf-8")

    generated_at = datetime.now().isoformat(timespec="seconds")
    readme_path.write_text(
        "\n".join(
            [
                "# Builder Session Summary GitHub Backup",
                "",
                f"- Generated at: `{generated_at}`",
                f"- Canonical source root: `{source_root}`",
                "- Canonical source shape: one `session_summary.json` per Builder session directory.",
                f"- Exported summaries: `{exported}`",
                f"- Skipped summaries: `{len(skipped)}`",
                f"- Archive: `{archive_path.name}`",
                f"- Manifest: `{manifest_path.name}`",
                f"- Archive SHA256: `{archive_digest}`",
                "",
                "The compressed NDJSON archive stores one JSON object per source session summary.",
                "Each object contains `record_index`, `session_id`, `source_path`, `sha256`, and the original `payload`.",
                "",
                "To inspect quickly:",
                "",
                "```powershell",
                "python - <<'PY'",
                "import gzip, json",
                f"path = r'{archive_path}'",
                "with gzip.open(path, 'rt', encoding='utf-8') as handle:",
                "    first = json.loads(next(handle))",
                "print(first['session_id'])",
                "PY",
                "```",
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    skipped_path = output_dir / "skipped.json"
    if skipped:
        skipped_path.write_text(json.dumps(skipped, indent=2, ensure_ascii=False), encoding="utf-8")
    elif skipped_path.exists():
        skipped_path.unlink()

    return {
        "source_root": str(source_root),
        "output_dir": str(output_dir),
        "exported": exported,
        "skipped": len(skipped),
        "archive_path": str(archive_path),
        "manifest_path": str(manifest_path),
        "archive_sha256": archive_digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=get_builder_sessions_dir(),
        help="Builder sessions root containing */session_summary.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where Git-friendly backup files will be written.",
    )
    args = parser.parse_args()
    result = export_builder_session_summary_backup(args.source_root, args.output_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
