"""
Module-ID: backtest.result_store

Lightweight v2 result store used by CLI shadow/v2 persistence mode.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


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
        except Exception:
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
        except Exception:
            pass
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

    def __init__(self, root_dir: str | Path = "backtest_results") -> None:
        self.root_dir = Path(root_dir)
        self.runs_dir = self.root_dir / "runs"
        self.index_path = self.root_dir / "index.csv"
        self.golden_path = self.root_dir / "golden_runs.csv"
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_index_file()

    def _ensure_index_file(self) -> None:
        if not self.index_path.exists():
            pd.DataFrame(columns=self._INDEX_COLUMNS).to_csv(self.index_path, index=False, encoding="utf-8")

    def load_index(self) -> pd.DataFrame:
        if not self.index_path.exists():
            return pd.DataFrame(columns=self._INDEX_COLUMNS)
        try:
            return pd.read_csv(self.index_path)
        except Exception:
            return pd.DataFrame(columns=self._INDEX_COLUMNS)

    def _append_index(self, row: dict[str, Any]) -> None:
        df = self.load_index()
        row_payload = {col: _as_jsonable(row.get(col)) for col in self._INDEX_COLUMNS}
        if df.empty:
            df = pd.DataFrame([row_payload], columns=self._INDEX_COLUMNS)
        else:
            next_idx = len(df)
            for col in self._INDEX_COLUMNS:
                if col not in df.columns:
                    df[col] = None
            df.loc[next_idx, self._INDEX_COLUMNS] = [row_payload.get(col) for col in self._INDEX_COLUMNS]
        df.to_csv(self.index_path, index=False, encoding="utf-8")

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
            except Exception:
                pass
        try:
            return dict(value)
        except Exception:
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

        run_id = self._ensure_unique_run_id(
            self._build_base_run_id(
                strategy=strategy,
                symbol=symbol,
                timeframe=timeframe,
                requested_run_id=requested_run_id or meta.get("run_id"),
                created_at=created_at,
            )
        )
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        metadata = {
            "run_id": run_id,
            "mode": mode,
            "status": status,
            "created_at": created_at,
            "strategy": strategy,
            "symbol": symbol,
            "timeframe": timeframe,
            "params": params,
            "period_start": meta.get("period_start") or metadata_extra.get("period_start"),
            "period_end": meta.get("period_end") or metadata_extra.get("period_end"),
            "n_bars": meta.get("n_bars"),
            "n_trades": int(len(getattr(result, "trades", []))) if hasattr(result, "trades") else 0,
            "seed": metadata_extra.get("seed"),
            "data_source": metadata_extra.get("data_source", {}),
            "engine_settings": metadata_extra.get("engine_settings", {}),
            "extra": {k: v for k, v in metadata_extra.items() if k not in {"data_source", "engine_settings", "params"}},
        }
        config_snapshot = {
            "strategy": strategy,
            "symbol": symbol,
            "timeframe": timeframe,
            "params": params,
            "config_snapshot_extra": metadata_extra.get("config_snapshot_extra", {}),
        }
        self._write_common_files(
            run_dir=run_dir,
            metadata=metadata,
            metrics=metrics,
            config_snapshot=config_snapshot,
            diagnostics=diagnostics,
        )

        equity_df = self._to_dataframe(getattr(result, "equity", None), "equity")
        equity_df.to_csv(run_dir / "equity.csv", index=True, encoding="utf-8")
        trades_df = self._to_dataframe(getattr(result, "trades", None), "trades")
        trades_df.to_csv(run_dir / "trades.csv", index=False, encoding="utf-8")
        if hasattr(result, "returns"):
            returns_df = self._to_dataframe(getattr(result, "returns", None), "returns")
            returns_df.to_csv(run_dir / "returns.csv", index=True, encoding="utf-8")

        self._append_index(
            {
                "run_id": run_id,
                "mode": mode,
                "status": status,
                "created_at": created_at,
                "strategy": strategy,
                "symbol": symbol,
                "timeframe": timeframe,
                "n_trades": metadata.get("n_trades", 0),
                "total_return_pct": metrics.get("total_return_pct"),
                "sharpe_ratio": metrics.get("sharpe_ratio"),
                "parent_run_id": None,
            }
        )
        return self._record_from_payload(
            run_id=run_id,
            run_dir=run_dir,
            mode=mode,
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            status=status,
            created_at=created_at,
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
        run_id = self._ensure_unique_run_id(
            self._build_base_run_id(
                strategy=strategy,
                symbol=symbol,
                timeframe=timeframe,
                requested_run_id=requested_run_id,
                created_at=created_at,
            )
        )
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        metadata = {
            "run_id": run_id,
            "mode": mode,
            "status": status,
            "created_at": created_at,
            "strategy": strategy,
            "symbol": symbol,
            "timeframe": timeframe,
            "params": params or {},
            "period_start": metadata_extra.get("period_start"),
            "period_end": metadata_extra.get("period_end"),
            "seed": metadata_extra.get("seed"),
            "data_source": metadata_extra.get("data_source", {}),
            "engine_settings": metadata_extra.get("engine_settings", {}),
            "extra": {
                k: v
                for k, v in metadata_extra.items()
                if k not in {"data_source", "engine_settings"}
            },
        }
        config_snapshot = {
            "strategy": strategy,
            "symbol": symbol,
            "timeframe": timeframe,
            "params": params or {},
            "config_snapshot_extra": metadata_extra.get("config_snapshot_extra", {}),
        }
        self._write_common_files(
            run_dir=run_dir,
            metadata=metadata,
            metrics=metrics or {},
            config_snapshot=config_snapshot,
            diagnostics=diagnostics,
        )

        self._append_index(
            {
                "run_id": run_id,
                "mode": mode,
                "status": status,
                "created_at": created_at,
                "strategy": strategy,
                "symbol": symbol,
                "timeframe": timeframe,
                "n_trades": int((metrics or {}).get("total_trades", 0) or 0),
                "total_return_pct": (metrics or {}).get("total_return_pct"),
                "sharpe_ratio": (metrics or {}).get("sharpe_ratio"),
                "parent_run_id": None,
            }
        )
        return self._record_from_payload(
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
            df = self.load_index()
            if not df.empty and "run_id" in df.columns:
                match = df["run_id"].astype(str) == record.run_id
                if match.any():
                    if "parent_run_id" in df.columns:
                        df["parent_run_id"] = df["parent_run_id"].astype("object")
                    df.loc[match, "parent_run_id"] = parent_run_id
                    df.to_csv(self.index_path, index=False, encoding="utf-8")
            records.append(record)
        return records

    def tag_run_as_golden(
        self,
        run_id: str,
        *,
        reason: str,
        priority: int = 1,
        notes: str | None = None,
    ) -> Path:
        columns = ["run_id", "tagged_at", "reason", "priority", "notes"]
        if self.golden_path.exists():
            try:
                df = pd.read_csv(self.golden_path)
            except Exception:
                df = pd.DataFrame(columns=columns)
        else:
            df = pd.DataFrame(columns=columns)

        payload = {
            "run_id": str(run_id),
            "tagged_at": _now_utc_iso(),
            "reason": str(reason),
            "priority": int(priority),
            "notes": notes or "",
        }
        if "run_id" in df.columns and (df["run_id"].astype(str) == str(run_id)).any():
            mask = df["run_id"].astype(str) == str(run_id)
            for key, value in payload.items():
                df.loc[mask, key] = value
        else:
            df = pd.concat([df, pd.DataFrame([payload])], ignore_index=True)
        df.to_csv(self.golden_path, index=False, encoding="utf-8")
        return self.golden_path


__all__ = ["ResultRecord", "ResultStore"]
