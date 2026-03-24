"""
Module-ID: backtest.store_v3

Production-ready V3 backtest store based on SQLite + atomic artifact writes.
"""

from __future__ import annotations

import json
import math
import os
import secrets
import shutil
import sqlite3
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

import pandas as pd

from .store_metadata import (
    build_store_row_from_metadata,
    derive_migration_status,
    find_run_artifacts,
    list_missing_run_artifacts,
    load_metadata_payload,
)


STORE_SCHEMA_VERSION = 3
DEFAULT_ROOT_DIR = "backtest_results"
RUNS_SUBDIR = "runs"
DB_FILENAME = "index.sqlite3"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Series):
        return value.to_dict()
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return str(value)


def _to_json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default)


def _normalize_root(root: str | Path) -> Path:
    return Path(root).expanduser().resolve()


def _coerce_iso_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, pd.Timestamp):
        dt = value.to_pydatetime()
    elif value:
        text = str(value).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return _utc_now_iso()
    else:
        return _utc_now_iso()

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _coerce_metrics(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        try:
            data = value.to_dict()
            if isinstance(data, dict):
                return dict(data)
        except Exception:
            pass
    try:
        return dict(value)
    except Exception:
        return {}


def _coerce_dataframe(value: Any, *, default_column: str, index_name: Optional[str] = None) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if isinstance(value, pd.Series):
        name = value.name or default_column
        df = value.to_frame(name=name)
        if index_name and df.index.name is None:
            df.index.name = index_name
        return df
    if isinstance(value, list):
        return pd.DataFrame(value)
    return pd.DataFrame(value)


def _coerce_equity_series(value: Any) -> pd.Series:
    if value is None:
        return pd.Series(dtype="float64", name="equity")
    if isinstance(value, pd.Series):
        series = value.copy()
        if not series.name:
            series.name = "equity"
        return series
    if isinstance(value, pd.DataFrame):
        if value.empty:
            return pd.Series(dtype="float64", name="equity")
        if "equity" in value.columns:
            return value["equity"].copy()
        return value.iloc[:, 0].copy().rename("equity")
    return pd.Series(value, name="equity")


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except Exception:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None


def _normalize_status(status: Any) -> str:
    text = str(status or "").strip().lower()
    if text in {"", "ok", "success"}:
        return "success"
    if text in {"invalid", "failed_validation"}:
        return "invalid"
    return text


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.{secrets.token_hex(4)}.tmp"
    try:
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def _atomic_write_json(path: Path, payload: Any) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))


def _atomic_write_parquet(df: pd.DataFrame, path: Path, *, compression: str = "snappy", index: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.{secrets.token_hex(4)}.tmp"
    try:
        df.to_parquet(tmp_path, compression=compression, index=index)
        os.replace(tmp_path, path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


class BacktestStoreV3:
    def __init__(self, root_dir: Path | str | None = None, roots: list[Path] | None = None) -> None:
        base_root = _normalize_root(root_dir or DEFAULT_ROOT_DIR)
        root_candidates = [_normalize_root(root) for root in (roots or [base_root])]
        deduped_roots: list[Path] = []
        seen: set[str] = set()
        for root in root_candidates:
            key = str(root).lower()
            if key in seen:
                continue
            seen.add(key)
            deduped_roots.append(root)

        self.primary_root = base_root if root_dir is not None else deduped_roots[0]
        if str(self.primary_root).lower() not in {str(root).lower() for root in deduped_roots}:
            deduped_roots.insert(0, self.primary_root)
        self.roots = deduped_roots

        for root in self.roots:
            root.mkdir(parents=True, exist_ok=True)
            (root / RUNS_SUBDIR).mkdir(parents=True, exist_ok=True)

        self.db_path = self.primary_root / DB_FILENAME
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    n_trades INTEGER NOT NULL,
                    total_return_pct REAL,
                    sharpe_ratio REAL,
                    max_drawdown_pct REAL,
                    period_start TEXT,
                    period_end TEXT,
                    duration_sec REAL,
                    params_json TEXT NOT NULL,
                    extra_json TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    schema_version INTEGER NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_strategy ON runs(strategy);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_symbol ON runs(symbol);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_timeframe ON runs(timeframe);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_sharpe ON runs(sharpe_ratio DESC);")
            conn.commit()

    def _choose_root(self) -> Path:
        best_root = self.roots[0]
        best_free = -1
        for root in self.roots:
            try:
                free_bytes = shutil.disk_usage(root).free
            except OSError:
                free_bytes = -1
            if free_bytes > best_free:
                best_root = root
                best_free = free_bytes
        return best_root

    def _generate_run_id(self) -> str:
        prefix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{secrets.token_hex(4)}"

    def _create_run_dir(self, root: Path, requested_run_id: str | None = None) -> tuple[str, Path]:
        base_run_id = str(requested_run_id or "").strip()
        for _ in range(64):
            run_id = base_run_id or self._generate_run_id()
            run_dir = root / RUNS_SUBDIR / run_id
            try:
                run_dir.mkdir(parents=True, exist_ok=False)
                return run_id, run_dir
            except FileExistsError:
                if base_run_id:
                    base_run_id = f"{requested_run_id}_{secrets.token_hex(2)}"
                    continue
        raise FileExistsError("Unable to allocate a unique run directory after 64 attempts")

    def _validate_run(
        self,
        *,
        equity: pd.Series,
        trades: pd.DataFrame,
        metrics: dict[str, Any],
        extra: dict[str, Any],
        incoming_status: str,
    ) -> tuple[str, dict[str, Any]]:
        validation_errors: list[str] = []

        if equity.empty:
            validation_errors.append("missing_equity")
        else:
            numeric_equity = pd.to_numeric(equity, errors="coerce")
            if numeric_equity.isna().any():
                validation_errors.append("equity_contains_nan")

        total_return_pct = _safe_float(metrics.get("total_return_pct"))
        sharpe_ratio = _safe_float(metrics.get("sharpe_ratio"))
        max_drawdown_pct = _safe_float(metrics.get("max_drawdown_pct"))
        total_trades_metric = _safe_int(metrics.get("total_trades"))

        if metrics and total_return_pct is None:
            validation_errors.append("invalid_total_return_pct")
        if metrics and "sharpe_ratio" in metrics and sharpe_ratio is None:
            validation_errors.append("invalid_sharpe_ratio")
        if metrics and "max_drawdown_pct" in metrics and max_drawdown_pct is None:
            validation_errors.append("invalid_max_drawdown_pct")
        if total_trades_metric is not None and total_trades_metric < 0:
            validation_errors.append("negative_total_trades")
        if not trades.empty and total_trades_metric is not None and total_trades_metric != len(trades):
            validation_errors.append("trades_count_mismatch")

        merged_extra = dict(extra or {})
        if validation_errors:
            merged_extra["validation_errors"] = validation_errors
            merged_extra.setdefault("reason", "; ".join(validation_errors))
            return "invalid", merged_extra

        return _normalize_status(incoming_status), merged_extra

    def save_run(
        self,
        result: Any = None,
        *,
        run_id: str | None = None,
        created_at: Any = None,
        mode: str = "backtest",
        status: str = "success",
        strategy: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        metrics: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        equity: Any = None,
        trades: Any = None,
        returns: Any = None,
        period_start: Any = None,
        period_end: Any = None,
        duration_sec: Any = None,
        extra: dict[str, Any] | None = None,
        write_metadata_json: bool = True,
    ) -> dict[str, Any]:
        meta = {}
        if result is not None:
            meta = dict(getattr(result, "meta", {}) or {})
            strategy = strategy or str(meta.get("strategy") or "unknown")
            symbol = symbol or str(meta.get("symbol") or "unknown")
            timeframe = timeframe or str(meta.get("timeframe") or "unknown")
            params = params or dict(meta.get("params") or {})
            metrics = metrics or _coerce_metrics(getattr(result, "metrics", {}))
            equity = equity if equity is not None else getattr(result, "equity", None)
            trades = trades if trades is not None else getattr(result, "trades", None)
            returns = returns if returns is not None else getattr(result, "returns", None)
            created_at = created_at or meta.get("created_at") or meta.get("timestamp")
            period_start = period_start or meta.get("period_start")
            period_end = period_end or meta.get("period_end")
            duration_sec = duration_sec if duration_sec is not None else meta.get("duration_sec")
            run_id = run_id or meta.get("run_id")
            extra = {**dict(meta), **dict(extra or {})}

        strategy = str(strategy or "unknown")
        symbol = str(symbol or "unknown")
        timeframe = str(timeframe or "unknown")
        params = dict(params or {})
        metrics = _coerce_metrics(metrics)
        extra = dict(extra or {})

        created_at_iso = _coerce_iso_timestamp(created_at)
        selected_root = self._choose_root()
        allocated_run_id, run_dir = self._create_run_dir(selected_root, run_id)

        equity_series = _coerce_equity_series(equity)
        trades_df = _coerce_dataframe(trades, default_column="trade")
        returns_df = _coerce_dataframe(returns, default_column="returns", index_name="timestamp")

        normalized_status, normalized_extra = self._validate_run(
            equity=equity_series,
            trades=trades_df,
            metrics=metrics,
            extra=extra,
            incoming_status=status,
        )

        artifact_files: dict[str, str] = {}

        try:
            if not equity_series.empty:
                equity_df = equity_series.to_frame(name=equity_series.name or "equity")
                _atomic_write_parquet(equity_df, run_dir / "equity.parquet", index=True)
                artifact_files["equity"] = "equity.parquet"

            if not trades_df.empty:
                _atomic_write_parquet(trades_df, run_dir / "trades.parquet", index=False)
                artifact_files["trades"] = "trades.parquet"

            if not returns_df.empty:
                _atomic_write_parquet(returns_df, run_dir / "returns.parquet", index=True)
                artifact_files["returns"] = "returns.parquet"

            metadata_payload = {
                "run_id": allocated_run_id,
                "created_at": created_at_iso,
                "mode": str(mode or "backtest"),
                "status": normalized_status,
                "strategy": strategy,
                "symbol": symbol,
                "timeframe": timeframe,
                "n_trades": int(len(trades_df)),
                "total_return_pct": _safe_float(metrics.get("total_return_pct")),
                "sharpe_ratio": _safe_float(metrics.get("sharpe_ratio")),
                "max_drawdown_pct": _safe_float(metrics.get("max_drawdown_pct")),
                "period_start": None if period_start in (None, "") else str(period_start),
                "period_end": None if period_end in (None, "") else str(period_end),
                "duration_sec": _safe_float(duration_sec),
                "params": params,
                "extra": normalized_extra,
                "schema_version": STORE_SCHEMA_VERSION,
                "artifacts": artifact_files,
            }
            if write_metadata_json:
                _atomic_write_json(run_dir / "metadata.json", metadata_payload)

            row = {
                "run_id": allocated_run_id,
                "created_at": created_at_iso,
                "mode": str(mode or "backtest"),
                "status": normalized_status,
                "strategy": strategy,
                "symbol": symbol,
                "timeframe": timeframe,
                "n_trades": int(len(trades_df)),
                "total_return_pct": _safe_float(metrics.get("total_return_pct")),
                "sharpe_ratio": _safe_float(metrics.get("sharpe_ratio")),
                "max_drawdown_pct": _safe_float(metrics.get("max_drawdown_pct")),
                "period_start": None if period_start in (None, "") else str(period_start),
                "period_end": None if period_end in (None, "") else str(period_end),
                "duration_sec": _safe_float(duration_sec),
                "params_json": _to_json_text(params),
                "extra_json": _to_json_text(normalized_extra),
                "artifact_path": str(run_dir),
                "schema_version": STORE_SCHEMA_VERSION,
            }

            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO runs (
                        run_id,
                        created_at,
                        mode,
                        status,
                        strategy,
                        symbol,
                        timeframe,
                        n_trades,
                        total_return_pct,
                        sharpe_ratio,
                        max_drawdown_pct,
                        period_start,
                        period_end,
                        duration_sec,
                        params_json,
                        extra_json,
                        artifact_path,
                        schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["run_id"],
                        row["created_at"],
                        row["mode"],
                        row["status"],
                        row["strategy"],
                        row["symbol"],
                        row["timeframe"],
                        row["n_trades"],
                        row["total_return_pct"],
                        row["sharpe_ratio"],
                        row["max_drawdown_pct"],
                        row["period_start"],
                        row["period_end"],
                        row["duration_sec"],
                        row["params_json"],
                        row["extra_json"],
                        row["artifact_path"],
                        row["schema_version"],
                    ),
                )
                conn.commit()

            return {
                **row,
                "params": params,
                "extra": normalized_extra,
                "root": str(selected_root),
                "artifacts": artifact_files,
            }
        except Exception:
            try:
                if run_dir.exists():
                    shutil.rmtree(run_dir)
            except OSError:
                pass
            raise

    def query_runs(
        self,
        *,
        strategy: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        min_sharpe: float | None = None,
        limit: int = 500,
        status: str | None = "success",
    ) -> pd.DataFrame:
        clauses: list[str] = []
        params: list[Any] = []

        if strategy:
            clauses.append("strategy = ?")
            params.append(str(strategy))
        if symbol:
            clauses.append("symbol = ?")
            params.append(str(symbol))
        if timeframe:
            clauses.append("timeframe = ?")
            params.append(str(timeframe))
        if min_sharpe is not None:
            clauses.append("sharpe_ratio >= ?")
            params.append(float(min_sharpe))
        if status:
            clauses.append("status = ?")
            params.append(_normalize_status(status))

        sql = "SELECT * FROM runs"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        if limit and int(limit) > 0:
            sql += " LIMIT ?"
            params.append(int(limit))

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        payload = [dict(row) for row in rows]
        df = pd.DataFrame(payload)
        if df.empty:
            return df

        for column in ("params_json", "extra_json"):
            if column in df.columns:
                parsed_name = column.replace("_json", "")
                df[parsed_name] = df[column].apply(
                    lambda value: json.loads(value) if isinstance(value, str) and value.strip() else {}
                )
        return df

    def _run_exists(self, run_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM runs WHERE run_id = ? LIMIT 1", (str(run_id),)).fetchone()
        return row is not None

    def merge_run_extra(self, run_id: str, extra_updates: dict[str, Any]) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT extra_json FROM runs WHERE run_id = ? LIMIT 1", (str(run_id),)).fetchone()
            if row is None:
                return False
            try:
                extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
            except Exception:
                extra = {}
            if not isinstance(extra, dict):
                extra = {}
            extra.update(dict(extra_updates or {}))
            conn.execute(
                "UPDATE runs SET extra_json = ? WHERE run_id = ?",
                (_to_json_text(extra), str(run_id)),
            )
            conn.commit()
        return True

    def _insert_existing_run_row(self, row: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id,
                    created_at,
                    mode,
                    status,
                    strategy,
                    symbol,
                    timeframe,
                    n_trades,
                    total_return_pct,
                    sharpe_ratio,
                    max_drawdown_pct,
                    period_start,
                    period_end,
                    duration_sec,
                    params_json,
                    extra_json,
                    artifact_path,
                    schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["run_id"],
                    row["created_at"],
                    row["mode"],
                    row["status"],
                    row["strategy"],
                    row["symbol"],
                    row["timeframe"],
                    row["n_trades"],
                    row["total_return_pct"],
                    row["sharpe_ratio"],
                    row["max_drawdown_pct"],
                    row["period_start"],
                    row["period_end"],
                    row["duration_sec"],
                    _to_json_text(row.get("params", {})),
                    _to_json_text(row.get("extra", {})),
                    row["artifact_path"],
                    row.get("schema_version", STORE_SCHEMA_VERSION),
                ),
            )
            conn.commit()

    @staticmethod
    def _load_index_csv_hints(index_path: Path) -> dict[str, dict[str, Any]]:
        if not index_path.exists():
            return {}
        try:
            df = pd.read_csv(index_path)
        except Exception:
            return {}

        hints: dict[str, dict[str, Any]] = {}
        if df.empty or "run_id" not in df.columns:
            return hints

        for record in df.to_dict(orient="records"):
            run_id = str(record.get("run_id") or "").strip()
            if not run_id:
                continue
            hints[run_id] = {k: v for k, v in record.items() if v == v}
        return hints

    @staticmethod
    def _load_index_json_hints(index_path: Path) -> dict[str, dict[str, Any]]:
        if not index_path.exists():
            return {}

        try:
            raw_payload = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if isinstance(raw_payload, list):
            payload = {
                str(item.get("run_id")): item
                for item in raw_payload
                if isinstance(item, dict) and item.get("run_id")
            }
        elif isinstance(raw_payload, dict):
            payload = raw_payload
        else:
            return {}

        hints: dict[str, dict[str, Any]] = {}
        for run_id, meta in payload.items():
            if not isinstance(meta, dict):
                continue
            hints[str(run_id)] = dict(meta)
        return hints

    @staticmethod
    def _load_sidecar_payload(path: Path) -> dict[str, Any]:
        return load_metadata_payload(path) if path.exists() else {}

    def _iter_legacy_candidate_dirs(self, root: Path) -> Iterable[Path]:
        if not root.exists():
            return []
        ignored = {RUNS_SUBDIR, "_analysis", "_catalog", "__pycache__"}
        candidates: list[Path] = []
        for item in root.iterdir():
            if not item.is_dir() or item.name in ignored:
                continue
            if (item / "metadata.json").exists():
                candidates.append(item)
        return candidates

    def _iter_canonical_candidate_dirs(self, root: Path) -> Iterable[Path]:
        runs_dir = root / RUNS_SUBDIR
        if not runs_dir.exists():
            return []
        return [item for item in runs_dir.iterdir() if item.is_dir() and (item / "metadata.json").exists()]

    def _build_migrated_row(
        self,
        *,
        run_dir: Path,
        index_csv_hints: dict[str, dict[str, Any]],
        index_json_hints: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        metadata_path = run_dir / "metadata.json"
        metadata_payload = load_metadata_payload(metadata_path)
        if not metadata_payload:
            return None

        run_id = str(metadata_payload.get("run_id") or run_dir.name)
        combined_hints: dict[str, Any] = {}
        combined_hints.update(index_csv_hints.get(run_id, {}))
        combined_hints.update(index_json_hints.get(run_id, {}))

        row = build_store_row_from_metadata(
            metadata_payload,
            run_id_hint=run_id,
            artifact_path=str(run_dir),
            index_row=combined_hints,
            metrics_payload=self._load_sidecar_payload(run_dir / "metrics.json"),
            config_payload=self._load_sidecar_payload(run_dir / "config_snapshot.json"),
        )
        if not row.get("run_id"):
            return None

        missing_artifacts = list_missing_run_artifacts(run_dir)
        row["status"] = derive_migration_status(
            row.get("status"),
            missing_artifacts=missing_artifacts,
            metadata_valid=bool(row.get("strategy") and row.get("symbol") and row.get("timeframe")),
        )
        row["artifact_path"] = str(run_dir)
        row["schema_version"] = STORE_SCHEMA_VERSION
        extra = dict(row.get("extra", {}) or {})
        extra.setdefault("migrated_from_schema", row.get("source_schema"))
        extra.setdefault("migrated_from_path", str(run_dir))
        extra.setdefault("artifact_files", {name: path.name for name, path in find_run_artifacts(run_dir).items()})
        if missing_artifacts:
            extra["missing_artifacts"] = missing_artifacts
        row["extra"] = extra
        return row

    def migrate_from_legacy(
        self,
        *,
        root_dir: str | Path | None = None,
        include_index_csv: bool = True,
        include_index_json: bool = True,
        include_canonical_runs: bool = True,
        include_legacy_runs: bool = True,
        export_indexes: bool = True,
    ) -> dict[str, Any]:
        source_root = _normalize_root(root_dir or self.primary_root)
        index_csv_hints = self._load_index_csv_hints(source_root / "index.csv") if include_index_csv else {}
        index_json_hints = self._load_index_json_hints(source_root / "index.json") if include_index_json else {}

        candidates: list[Path] = []
        if include_canonical_runs:
            candidates.extend(self._iter_canonical_candidate_dirs(source_root))
        if include_legacy_runs:
            candidates.extend(self._iter_legacy_candidate_dirs(source_root))

        unique_candidates: dict[str, Path] = {}
        for run_dir in candidates:
            unique_candidates.setdefault(str(run_dir.resolve()).lower(), run_dir)

        summary: dict[str, Any] = {
            "source_root": str(source_root),
            "detected_runs": len(unique_candidates),
            "migrated_runs": 0,
            "skipped_existing": 0,
            "invalid_runs": 0,
            "partial_runs": 0,
            "success_runs": 0,
            "errors": [],
        }

        for run_dir in unique_candidates.values():
            try:
                row = self._build_migrated_row(
                    run_dir=run_dir,
                    index_csv_hints=index_csv_hints,
                    index_json_hints=index_json_hints,
                )
                if not row:
                    summary["errors"].append({"run_dir": str(run_dir), "error": "metadata_unreadable"})
                    continue

                if self._run_exists(row["run_id"]):
                    summary["skipped_existing"] += 1
                    continue

                self._insert_existing_run_row(row)
                summary["migrated_runs"] += 1
                if row["status"] == "success":
                    summary["success_runs"] += 1
                elif row["status"] == "partial":
                    summary["partial_runs"] += 1
                else:
                    summary["invalid_runs"] += 1
            except Exception as exc:
                summary["errors"].append({"run_dir": str(run_dir), "error": str(exc)})

        if export_indexes:
            self.export_index_csv(source_root / "index.csv")
            self.export_index_json(source_root / "index.json")

        return summary

    def export_index_csv(self, path: Path | str) -> Path:
        output_path = Path(path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df = self.query_runs(limit=0, status=None)
        df.to_csv(output_path, index=False, encoding="utf-8")
        return output_path

    def export_index_json(self, path: Path | str) -> Path:
        output_path = Path(path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df = self.query_runs(limit=0, status=None)
        records = {
            str(record.get("run_id")): record
            for record in (df.to_dict(orient="records") if not df.empty else [])
            if record.get("run_id")
        }
        _atomic_write_json(output_path, records)
        return output_path


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BacktestStoreV3 utilities")
    parser.add_argument("--root-dir", help="Racine backtest_results a migrer ou utiliser", default=None)
    parser.add_argument("--migrate", action="store_true", help="Importer index.csv/index.json et les runs legacy")
    args = parser.parse_args(argv)

    store = BacktestStoreV3(root_dir=args.root_dir)
    if args.migrate:
        summary = store.migrate_from_legacy(root_dir=args.root_dir)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    parser.print_help()
    return 0


__all__ = ["BacktestStoreV3", "STORE_SCHEMA_VERSION"]


if __name__ == "__main__":
    raise SystemExit(_main())
