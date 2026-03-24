"""
Module-ID: backtest.result_store

Lightweight v2 result store used by CLI shadow/v2 persistence mode.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)

import pandas as pd

from .store_v3 import BacktestStoreV3


ARTIFACTS_DIR_ENV_VAR = "BACKTEST_ARTIFACTS_DIR"
RESULTS_DIR_ENV_VAR = "BACKTEST_RESULTS_DIR"
DEFAULT_RESULTS_DIR_NAME = "backtest_results"
PROJECT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_DOTENV_LOADED = False


def _apply_env_file_fallback(env_path: Path, *, override: bool = False) -> bool:
    if not env_path.exists():
        return False
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.debug("Cannot read env file %s: %s", env_path, exc)
        return False

    loaded = False
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            logger.debug("Skipping invalid env line in %s: %r", env_path, raw_line)
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value
        loaded = True
    return loaded


def load_project_env(env_path: str | Path | None = None, *, override: bool = False) -> bool:
    global _DOTENV_LOADED
    if env_path is None and _DOTENV_LOADED and not override:
        return False

    resolved_env_path = Path(env_path).expanduser() if env_path is not None else PROJECT_ENV_PATH
    if env_path is None:
        _DOTENV_LOADED = True
    if not resolved_env_path.exists():
        return False

    try:
        from dotenv import load_dotenv
    except ImportError:
        return _apply_env_file_fallback(resolved_env_path, override=override)
    return bool(load_dotenv(resolved_env_path, override=override))


def _resolve_path(
    explicit_path: str | Path | None,
    *,
    env_var: str | None = None,
    default_path: str | Path | None = None,
) -> Path:
    if explicit_path is not None and str(explicit_path).strip():
        return Path(explicit_path).expanduser()
    load_project_env()
    if env_var:
        env_value = str(os.environ.get(env_var, "")).strip()
        if env_value:
            return Path(env_value).expanduser()
    if default_path is None:
        raise ValueError("default_path is required when no explicit path or env value is provided")
    return Path(default_path).expanduser()


def get_results_root_dir(root_dir: str | Path | None = None) -> Path:
    return _resolve_path(
        root_dir,
        env_var=RESULTS_DIR_ENV_VAR,
        default_path=DEFAULT_RESULTS_DIR_NAME,
    )


def get_workspace_root_dir(base_dir: str | Path | None = None) -> Path:
    if base_dir is not None and str(base_dir).strip():
        return Path(base_dir).expanduser()
    return PROJECT_ENV_PATH.parent


def get_workspace_results_root_dir(base_dir: str | Path | None = None) -> Path:
    return get_workspace_root_dir(base_dir) / DEFAULT_RESULTS_DIR_NAME


def get_workspace_results_analysis_dir(base_dir: str | Path | None = None) -> Path:
    return get_workspace_results_root_dir(base_dir) / "_analysis"


def get_artifacts_root_dir(base_dir: str | Path | None = None) -> Path:
    return _resolve_path(
        base_dir,
        env_var=ARTIFACTS_DIR_ENV_VAR,
        default_path=get_results_root_dir(),
    )


def get_results_analysis_dir(base_dir: str | Path | None = None) -> Path:
    return get_artifacts_root_dir(base_dir) / "_analysis"


def get_results_organized_dir(base_dir: str | Path | None = None) -> Path:
    return get_artifacts_root_dir(base_dir) / "_organized_results"


def get_results_archive_dir(base_dir: str | Path | None = None) -> Path:
    return get_artifacts_root_dir(base_dir) / "_archive_results"


def get_saved_runs_dir(base_dir: str | Path | None = None) -> Path:
    return get_artifacts_root_dir(base_dir) / "_saved_runs"


def get_builder_sessions_dir(base_dir: str | Path | None = None) -> Path:
    return get_artifacts_root_dir(base_dir) / "_builder_sessions"


def get_sweep_diagnostics_dir(base_dir: str | Path | None = None) -> Path:
    return get_artifacts_root_dir(base_dir) / "_diagnostics" / "sweeps"


def get_profiling_results_dir(base_dir: str | Path | None = None) -> Path:
    return get_artifacts_root_dir(base_dir) / "_profiling"


def get_output_root_dir(base_dir: str | Path | None = None) -> Path:
    return get_artifacts_root_dir(base_dir) / "_output"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_id(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip())
    sanitized = sanitized.strip("._-")
    return sanitized or "run"


def _coerce_created_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif value:
        try:
            dt = datetime.fromisoformat(str(value))
        except Exception as exc:
            logger.debug("Cannot parse created_at %r: %s", value, exc)
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Series):
        return {str(k): _as_jsonable(v) for k, v in value.to_dict().items()}
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, dict):
        return {str(k): _as_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_as_jsonable(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception as exc:
            logger.debug("item() conversion failed for %r: %s", type(value).__name__, exc)
    return str(value)


def _json_dump(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_as_jsonable(payload), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


@dataclass
class ResultRecord:
    run_id: str
    run_dir: Path
    mode: str
    strategy: str
    symbol: str
    timeframe: str
    status: str
    created_at: str


class ResultStore:
    """Filesystem store for v2 runs.

    Layout:
    - <root>/runs/<run_id>/{metadata.json,metrics.json,config_snapshot.json,versions.json,...}
    - <root>/index.csv
    - <root>/golden_runs.csv
    """

    _INDEX_COLUMNS = [
        "run_id",
        "mode",
        "status",
        "created_at",
        "strategy",
        "symbol",
        "timeframe",
        "n_trades",
        "total_return_pct",
        "sharpe_ratio",
        "parent_run_id",
    ]

    def __init__(self, root_dir: str | Path | None = None) -> None:
        self.root_dir = get_results_root_dir(root_dir)
        self.runs_dir = self.root_dir / "runs"
        self.index_path = self.root_dir / "index.csv"
        self.golden_path = self.root_dir / "golden_runs.csv"
        self._store_v3 = BacktestStoreV3(root_dir=self.root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_index_file()

    def _ensure_index_file(self) -> None:
        if not self.index_path.exists():
            self._export_index_cache(pd.DataFrame(columns=self._INDEX_COLUMNS))

    @staticmethod
    def _legacy_status(status: Any) -> Any:
        return "ok" if str(status or "").strip().lower() == "success" else status

    def _build_v3_extra(
        self,
        *,
        metadata_extra: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
        diagnostics: Any = None,
    ) -> dict[str, Any]:
        payload = dict(meta or {})
        for key, value in dict(metadata_extra or {}).items():
            if key == "params":
                continue
            payload[key] = value
        if diagnostics is not None:
            payload["diagnostics"] = diagnostics
        return payload

    def _v3_index_to_legacy(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=self._INDEX_COLUMNS)

        extra_series = df["extra"] if "extra" in df.columns else pd.Series([{}] * len(df))
        legacy = pd.DataFrame(
            {
                "run_id": df.get("run_id"),
                "mode": df.get("mode"),
                "status": df.get("status").apply(self._legacy_status) if "status" in df.columns else None,
                "created_at": df.get("created_at"),
                "strategy": df.get("strategy"),
                "symbol": df.get("symbol"),
                "timeframe": df.get("timeframe"),
                "n_trades": df.get("n_trades"),
                "total_return_pct": df.get("total_return_pct"),
                "sharpe_ratio": df.get("sharpe_ratio"),
                "parent_run_id": extra_series.apply(
                    lambda payload: payload.get("parent_run_id") if isinstance(payload, dict) else None
                ),
            }
        )
        for column in self._INDEX_COLUMNS:
            if column not in legacy.columns:
                legacy[column] = None
        return legacy[self._INDEX_COLUMNS]

    def _export_index_cache(self, df: pd.DataFrame | None = None) -> None:
        cache_df = df if df is not None else self._v3_index_to_legacy(self._store_v3.query_runs(limit=0, status=None))
        cache_df.to_csv(self.index_path, index=False, encoding="utf-8")

    def _export_golden_cache(self) -> Path:
        columns = ["run_id", "tagged_at", "reason", "priority", "notes"]
        rows: list[dict[str, Any]] = []
        try:
            df = self._store_v3.query_runs(limit=0, status=None)
        except Exception as exc:
            logger.warning("Failed to query V3 store for golden export: %s", exc)
            df = pd.DataFrame()

        if not df.empty:
            extra_series = df["extra"] if "extra" in df.columns else pd.Series([{}] * len(df))
            for run_id, extra in zip(df["run_id"], extra_series):
                if not isinstance(extra, dict):
                    continue
                golden = extra.get("golden")
                if not isinstance(golden, dict):
                    continue
                rows.append(
                    {
                        "run_id": str(run_id),
                        "tagged_at": golden.get("tagged_at", ""),
                        "reason": golden.get("reason", ""),
                        "priority": golden.get("priority", 1),
                        "notes": golden.get("notes", ""),
                    }
                )

        pd.DataFrame(rows, columns=columns).to_csv(self.golden_path, index=False, encoding="utf-8")
        return self.golden_path

    def load_index(self) -> pd.DataFrame:
        try:
            df = self._v3_index_to_legacy(self._store_v3.query_runs(limit=0, status=None))
            self._export_index_cache(df)
            return df
        except Exception as exc:
            logger.warning("Failed to load V3 index %s: %s", self._store_v3.db_path, exc)
            if not self.index_path.exists():
                return pd.DataFrame(columns=self._INDEX_COLUMNS)
            try:
                return pd.read_csv(self.index_path)
            except Exception as csv_exc:
                logger.warning("Failed to load fallback index %s: %s", self.index_path, csv_exc)
                return pd.DataFrame(columns=self._INDEX_COLUMNS)

    def migrate_legacy_store(self, *, root_dir: str | Path | None = None) -> dict[str, Any]:
        summary = self._store_v3.migrate_from_legacy(root_dir=root_dir or self.root_dir)
        self._export_index_cache()
        self._export_golden_cache()
        return summary

    def _append_index(self, row: dict[str, Any]) -> None:
        self._export_index_cache()

    def _build_base_run_id(
        self,
        *,
        strategy: str,
        symbol: str,
        timeframe: str,
        requested_run_id: str | None,
        created_at: Any,
    ) -> str:
        if requested_run_id:
            return _sanitize_id(requested_run_id)
        ts = _coerce_created_at(created_at).strftime("%Y%m%d_%H%M%S")
        return _sanitize_id(f"{strategy}_{symbol}_{timeframe}_{ts}")

    def _ensure_unique_run_id(self, base_run_id: str) -> str:
        candidate = _sanitize_id(base_run_id)
        if not (self.runs_dir / candidate).exists():
            return candidate
        rank = 1
        while True:
            with_suffix = f"{candidate}_r{rank}"
            if not (self.runs_dir / with_suffix).exists():
                return with_suffix
            rank += 1

    @staticmethod
    def _to_dataframe(value: Any, default_col: str) -> pd.DataFrame:
        if isinstance(value, pd.DataFrame):
            return value.copy()
        if isinstance(value, pd.Series):
            name = value.name or default_col
            return value.to_frame(name=name)
        if value is None:
            return pd.DataFrame(columns=[default_col])
        return pd.DataFrame(value)

    def _write_common_files(
        self,
        *,
        run_dir: Path,
        metadata: dict[str, Any],
        metrics: dict[str, Any],
        config_snapshot: dict[str, Any],
        diagnostics: Any = None,
    ) -> None:
        _json_dump(run_dir / "metadata.json", metadata)
        _json_dump(run_dir / "metrics.json", metrics)
        _json_dump(run_dir / "config_snapshot.json", config_snapshot)
        _json_dump(
            run_dir / "versions.json",
            {
                "schema_version": "2.0",
                "store": "ResultStore",
                "created_at": metadata.get("created_at") or _now_utc_iso(),
            },
        )
        if diagnostics is not None:
            _json_dump(run_dir / "diagnostics.json", diagnostics)

    def _record_from_payload(
        self,
        *,
        run_id: str,
        run_dir: Path,
        mode: str,
        strategy: str,
        symbol: str,
        timeframe: str,
        status: str,
        created_at: str,
    ) -> ResultRecord:
        return ResultRecord(
            run_id=run_id,
            run_dir=run_dir,
            mode=mode,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            status=status,
            created_at=created_at,
        )

    @staticmethod
    def _coerce_metrics(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if hasattr(value, "to_dict"):
            try:
                return dict(value.to_dict())
            except Exception as exc:
                logger.debug("to_dict() failed for %r: %s", type(value).__name__, exc)
        try:
            return dict(value)
        except Exception as exc:
            logger.debug("dict() coercion failed for %r: %s", type(value).__name__, exc)
            return {}

    def save_backtest_result(
        self,
        result: Any,
        *,
        requested_run_id: str | None = None,
        mode: str = "backtest",
        status: str = "ok",
        metadata_extra: dict[str, Any] | None = None,
        diagnostics: Any = None,
    ) -> ResultRecord:
        metadata_extra = dict(metadata_extra or {})
        meta = dict(getattr(result, "meta", {}) or {})
        created_at = _coerce_created_at(metadata_extra.get("created_at")).isoformat()
        strategy = str(meta.get("strategy") or metadata_extra.get("strategy_name") or "unknown")
        symbol = str(meta.get("symbol") or metadata_extra.get("symbol") or "unknown")
        timeframe = str(meta.get("timeframe") or metadata_extra.get("timeframe") or "unknown")
        params = dict(meta.get("params") or metadata_extra.get("params") or {})
        metrics = self._coerce_metrics(getattr(result, "metrics", {}))
        saved = self._store_v3.save_run(
            result,
            run_id=requested_run_id or meta.get("run_id"),
            created_at=created_at,
            mode=mode,
            status=status,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            metrics=metrics,
            params=params,
            period_start=meta.get("period_start") or metadata_extra.get("period_start"),
            period_end=meta.get("period_end") or metadata_extra.get("period_end"),
            duration_sec=meta.get("duration_sec") or metadata_extra.get("duration_sec"),
            extra=self._build_v3_extra(metadata_extra=metadata_extra, meta=meta, diagnostics=diagnostics),
        )
        self._export_index_cache()
        return self._record_from_payload(
            run_id=str(saved["run_id"]),
            run_dir=Path(saved["artifact_path"]),
            mode=mode,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            status=status,
            created_at=str(saved["created_at"]),
        )

    def save_summary_run(
        self,
        *,
        mode: str,
        strategy: str,
        symbol: str,
        timeframe: str,
        params: dict[str, Any],
        metrics: dict[str, Any],
        requested_run_id: str | None = None,
        metadata_extra: dict[str, Any] | None = None,
        diagnostics: Any = None,
        status: str = "ok",
    ) -> ResultRecord:
        metadata_extra = dict(metadata_extra or {})
        created_at = _coerce_created_at(metadata_extra.get("created_at")).isoformat()
        saved = self._store_v3.save_run(
            run_id=requested_run_id,
            created_at=created_at,
            mode=mode,
            status=status,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            metrics=metrics or {},
            params=params or {},
            equity=pd.Series([1.0], name="equity"),
            period_start=metadata_extra.get("period_start"),
            period_end=metadata_extra.get("period_end"),
            duration_sec=metadata_extra.get("duration_sec"),
            extra=self._build_v3_extra(metadata_extra=metadata_extra, diagnostics=diagnostics),
        )
        self._export_index_cache()
        return self._record_from_payload(
            run_id=str(saved["run_id"]),
            run_dir=Path(saved["artifact_path"]),
            mode=mode,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            status=status,
            created_at=str(saved["created_at"]),
        )

    @staticmethod
    def _iter_folds(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        if isinstance(payload.get("folds"), list):
            return payload["folds"]
        results = payload.get("results")
        if isinstance(results, dict):
            rolling = results.get("rolling")
            if isinstance(rolling, dict) and isinstance(rolling.get("folds"), list):
                return rolling["folds"]
        return []

    def save_walk_forward_folds(
        self,
        *,
        parent_run_id: str,
        strategy: str,
        symbol: str,
        timeframe: str,
        params: dict[str, Any],
        walk_forward_payload: dict[str, Any],
        metadata_extra: dict[str, Any] | None = None,
    ) -> list[ResultRecord]:
        metadata_extra = dict(metadata_extra or {})
        records: list[ResultRecord] = []
        folds = list(self._iter_folds(walk_forward_payload))
        for idx, fold in enumerate(folds):
            fold_id = fold.get("fold_id", idx)
            metrics = {
                "train_sharpe": fold.get("train_sharpe"),
                "test_sharpe": fold.get("test_sharpe"),
                "overfitting_ratio": fold.get("overfitting_ratio"),
            }
            record = self.save_summary_run(
                mode="walk_forward_fold",
                strategy=strategy,
                symbol=symbol,
                timeframe=timeframe,
                params=params,
                metrics=metrics,
                requested_run_id=f"{parent_run_id}_wf{int(fold_id):02d}",
                metadata_extra={
                    **metadata_extra,
                    "parent_run_id": parent_run_id,
                    "fold_id": fold_id,
                    "train_range": fold.get("train_range"),
                    "test_range": fold.get("test_range"),
                },
                diagnostics=fold,
                status="ok",
            )
            self._store_v3.merge_run_extra(record.run_id, {"parent_run_id": parent_run_id})
            records.append(record)
        self._export_index_cache()
        return records

    def tag_run_as_golden(
        self,
        run_id: str,
        *,
        reason: str,
        priority: int = 1,
        notes: str | None = None,
    ) -> Path:
        payload = {
            "run_id": str(run_id),
            "tagged_at": _now_utc_iso(),
            "reason": str(reason),
            "priority": int(priority),
            "notes": notes or "",
        }
        updated = self._store_v3.merge_run_extra(str(run_id), {"golden": payload})
        if not updated:
            logger.warning("Cannot tag missing run_id %s as golden", run_id)
            return self._export_golden_cache()
        return self._export_golden_cache()


__all__ = ["ResultRecord", "ResultStore"]
