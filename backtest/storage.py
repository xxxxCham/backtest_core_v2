"""Module-ID: backtest.storage

Purpose: Persister et indexer les résultats de backtests pour rechargement/recherche rapide.

Role in pipeline: persistence / reporting

Key components: ResultStorage, StoredResultMetadata, get_storage

Inputs: RunResult, run_id, auto_cleanup flag

Outputs: Fichiers JSON/Parquet dans backtest_results/runs/{run_id}/, index.json dérivé

Dependencies: pandas, pathlib, json, optionnel: pyarrow (Parquet)

Conventions: Structure runs/run_id/metadata.json + equity.parquet + trades.parquet; fallback lecture legacy backtest_results/{run_id}/; index.json catalogue dérivé; auto_cleanup garde N derniers runs.

Read-if: Persistance résultats, recherche historique, ou gestion stockage.

Skip-if: Backtests ponctuels sans sauvegarde.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.engine import RunResult
from backtest.result_store import get_results_root_dir
from backtest.store_metadata import (
    as_jsonable,
    build_store_row_from_metadata,
    dump_json_payload,
    is_native_result_metadata,
    is_v3_result_metadata,
    load_metadata_payload,
    normalize_status_for_legacy,
    normalize_status_for_store,
)
from backtest.store_v3 import BacktestStoreV3
from backtest.sweep import SweepResults
from metrics_types import PerformanceMetricsPct, normalize_metrics
from utils.log import get_logger

logger = get_logger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_STORAGE_DIR = get_results_root_dir()
MAX_RESULTS_TO_KEEP = 1000  # Nombre maximum de résultats à garder
_TEMPDIR_READY = False
_NATIVE_EXTRA_METADATA_KEYS = (
    "origin",
    "ui_partial_run",
    "ui_partial_reason",
    "ui_completed_runs",
    "ui_planned_runs",
    "ui_completion_pct",
    "builder_session_id",
    "builder_iteration",
    "builder_objective",
    "universe_mode",
    "universe_purpose",
    "universe_strategy_type",
)
_CATALOG_METADATA_FIELDS = (
    "timestamp", "mode", "status", "strategy", "symbol", "timeframe",
    "n_bars", "n_trades", "duration_sec", "period_start", "period_end",
)
_UNIFIED_ENTRY_FIELDS = (
    "artifact_type", "schema", "path", "parent_scope", "run_id", "timestamp",
    "mode", "status", "strategy", "symbol", "timeframe", "loadable",
    "n_bars", "n_trades", "duration_sec", "period_start", "period_end",
)


# =============================================================================
# TEMP DIR FIX (sandbox compatibility)
# =============================================================================


def _ensure_writable_tempdir() -> None:
    """Assure que tempfile utilise un répertoire writable dans les environnements sandbox."""
    global _TEMPDIR_READY
    if _TEMPDIR_READY:
        return

    def _set_local_temp() -> Path:
        fallback = Path.cwd() / ".tmp"
        fallback.mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = str(fallback)
        os.environ["TMP"] = str(fallback)
        os.environ["TEMP"] = str(fallback)
        return fallback

    def _safe_mkdtemp(suffix: str | None = None, prefix: str | None = None, dir: str | None = None) -> str:
        base = Path(dir or tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        prefix_val = prefix or "tmp"
        suffix_val = suffix or ""
        for _ in range(1000):
            name = f"{prefix_val}{uuid.uuid4().hex}{suffix_val}"
            candidate = base / name
            try:
                candidate.mkdir()
                return str(candidate)
            except FileExistsError:
                continue
        raise FileExistsError("Unable to create temporary directory")

    try:
        temp_root = Path(tempfile.gettempdir())
        temp_root.mkdir(parents=True, exist_ok=True)

        probe_dir = Path(tempfile.mkdtemp(dir=temp_root))
        nested = probe_dir / "nested_probe"
        nested.mkdir(parents=True, exist_ok=True)
        test_path = nested / "write_test.txt"
        test_path.write_text("ok", encoding="utf-8")
        test_path.unlink(missing_ok=True)
        nested.rmdir()
        probe_dir.rmdir()
    except Exception:
        temp_root = _set_local_temp()

    # Vérifier que mkdtemp crée un dossier réellement writable
    try:
        probe_dir = Path(tempfile.mkdtemp(dir=temp_root))
        test_path = probe_dir / "write_test.txt"
        test_path.write_text("ok", encoding="utf-8")
        test_path.unlink(missing_ok=True)
        probe_dir.rmdir()
    except Exception:
        tempfile.mkdtemp = _safe_mkdtemp

    _TEMPDIR_READY = True


# =============================================================================
# HELPERS
# =============================================================================


def _load_json_file(path: Path) -> dict[str, Any]:
    return load_metadata_payload(path)


def _extract_result_extra_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    for key in _NATIVE_EXTRA_METADATA_KEYS:
        value = meta.get(key)
        if value is None or value == "":
            continue
        extra[key] = value
    return extra


def _has_any_child_metadata(directory: Path) -> bool:
    try:
        next(directory.rglob("metadata.json"))
        return True
    except StopIteration:
        return False


def _is_native_stored_metadata(meta: dict[str, Any]) -> bool:
    return is_native_result_metadata(meta)


def _is_v3_stored_metadata(meta: dict[str, Any]) -> bool:
    return is_v3_result_metadata(meta)


def _status_from_store(status: Any) -> str:
    return normalize_status_for_legacy(status)


def _status_to_store(status: Any) -> str:
    return normalize_status_for_store(status)


def _coerce_metric_number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _sanitize_pct_metrics_payload(
    payload: dict[str, Any],
    *,
    run_id_hint: str | None = None,
    context: str,
) -> dict[str, Any]:
    sanitized = dict(payload or {})
    bounded_keys = (
        ("win_rate_pct", 0.0, 100.0),
        ("max_drawdown_pct", -100.0, 0.0),
    )
    for key, lo, hi in bounded_keys:
        numeric = _coerce_metric_number(sanitized.get(key))
        if numeric is None:
            sanitized.pop(key, None)
            continue
        bounded = min(hi, max(lo, numeric))
        if bounded != numeric:
            logger.warning(
                "storage_metric_clamped run=%s context=%s key=%s raw=%s bounded=%s",
                run_id_hint or "<unknown>",
                context,
                key,
                numeric,
                bounded,
            )
        sanitized[key] = bounded
    return sanitized


def _stored_metadata_from_payload(meta: dict[str, Any], run_id_hint: str | None = None) -> StoredResultMetadata:
    if not (_is_native_stored_metadata(meta) or _is_v3_stored_metadata(meta)):
        raise ValueError("Unsupported stored metadata schema")

    row = build_store_row_from_metadata(meta, run_id_hint=run_id_hint)
    metrics = normalize_metrics(
        _sanitize_pct_metrics_payload(
            {
                "total_return_pct": row.get("total_return_pct"),
                "sharpe_ratio": row.get("sharpe_ratio"),
                "max_drawdown_pct": row.get("max_drawdown_pct"),
                "total_trades": row.get("n_trades"),
            },
            run_id_hint=run_id_hint,
            context="_stored_metadata_from_payload",
        ),
        "pct",
    )
    extra_metadata = dict(row.get("extra", {}) or {})
    return StoredResultMetadata(
        run_id=str(row.get("run_id") or run_id_hint or ""),
        timestamp=str(row.get("created_at") or datetime.now().isoformat()),
        strategy=str(row.get("strategy") or "unknown"),
        symbol=str(row.get("symbol") or "unknown"),
        timeframe=str(row.get("timeframe") or "unknown"),
        params=dict(row.get("params", {}) or {}),
        metrics=metrics,
        n_bars=int(extra_metadata.get("n_bars") or 0),
        n_trades=int(row.get("n_trades") or 0),
        period_start=str(row.get("period_start") or ""),
        period_end=str(row.get("period_end") or ""),
        duration_sec=float(row.get("duration_sec") or 0.0),
        mode=str(row.get("mode") or "backtest"),
        status=_status_from_store(row.get("status")),
        extra_metadata=extra_metadata,
    )


def _native_run_missing_files(run_dir: Path) -> list[str]:
    missing: list[str] = []
    if not (run_dir / "metadata.json").exists():
        missing.append("metadata.json")
    if not ((run_dir / "equity.parquet").exists() or (run_dir / "equity.csv").exists()):
        missing.append("equity.(parquet|csv)")
    if not ((run_dir / "trades.parquet").exists() or (run_dir / "trades.csv").exists()):
        missing.append("trades.(parquet|csv)")
    if not ((run_dir / "returns.parquet").exists() or (run_dir / "returns.csv").exists()):
        missing.append("returns.(parquet|csv)")
    return missing


# =============================================================================
# DATACLASSES
# =============================================================================


@dataclass
class StoredResultMetadata:
    """Métadonnées d'un résultat sauvegardé."""

    run_id: str
    timestamp: str
    strategy: str
    symbol: str
    timeframe: str
    params: dict[str, Any]
    metrics: PerformanceMetricsPct
    n_bars: int
    n_trades: int
    period_start: str
    period_end: str
    duration_sec: float
    mode: str = "backtest"
    status: str = "ok"
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convertit en dict pour sérialisation."""
        payload = asdict(self)
        payload["metrics"] = normalize_metrics(self.metrics, "pct")
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoredResultMetadata:
        """Crée depuis un dict."""
        metrics = normalize_metrics(
            _sanitize_pct_metrics_payload(
                dict(data.get("metrics", {}) or {}),
                run_id_hint=str(data.get("run_id") or ""),
                context="StoredResultMetadata.from_dict",
            ),
            "pct",
        )
        return cls(
            run_id=data["run_id"],
            timestamp=data["timestamp"],
            strategy=data["strategy"],
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            params=data.get("params", {}),
            metrics=metrics,
            n_bars=data["n_bars"],
            n_trades=data["n_trades"],
            period_start=data.get("period_start", ""),
            period_end=data.get("period_end", ""),
            duration_sec=data.get("duration_sec", 0.0),
            mode=str(data.get("mode", "backtest") or "backtest"),
            status=str(data.get("status", "ok") or "ok"),
            extra_metadata=dict(data.get("extra_metadata", {}) or {}),
        )


def _extend_prefixed(row: dict[str, Any], prefix: str, values: dict[str, Any] | None) -> None:
    for key, value in (values or {}).items():
        row[f"{prefix}_{key}"] = value


def _build_native_catalog_row(metadata: StoredResultMetadata) -> dict[str, Any]:
    row = {
        "type": "run",
        "id": metadata.run_id,
        "run_id": metadata.run_id,
        "path": metadata.run_id,
        "storage_path": f"runs/{metadata.run_id}",
        **{field: getattr(metadata, field) for field in _CATALOG_METADATA_FIELDS},
    }
    _extend_prefixed(row, "params", metadata.params)
    _extend_prefixed(row, "metrics", metadata.metrics)
    _extend_prefixed(row, "extra", metadata.extra_metadata)
    row["flags_account_ruined"] = bool(metadata.metrics.get("account_ruined", False))
    return row


def _build_unified_catalog_row(entry: dict[str, Any]) -> dict[str, Any]:
    row = {field: entry.get(field) for field in _UNIFIED_ENTRY_FIELDS}
    row["issues"] = "; ".join(entry.get("issues", []))
    _extend_prefixed(row, "params", entry.get("params", {}) or {})
    _extend_prefixed(row, "metrics", entry.get("metrics", {}) or {})
    _extend_prefixed(row, "extra", entry.get("extra_metadata", {}) or {})
    return row


# =============================================================================
# STORAGE ENGINE
# =============================================================================


class ResultStorage:
    """Gestionnaire de stockage des résultats de backtests.

    Features:
    - Sauvegarde automatique avec structure organisée
    - Index pour recherche rapide
    - Compression optionnelle
    - Nettoyage automatique des anciens résultats

    Example:
        >>> storage = ResultStorage()
        >>>
        >>> # Sauvegarder un résultat
        >>> storage.save_result(run_result)
        >>>
        >>> # Lister tous les résultats
        >>> all_results = storage.list_results()
        >>>
        >>> # Rechercher
        >>> best_runs = storage.search_results(min_sharpe=2.0)
        >>>
        >>> # Charger un résultat spécifique
        >>> result = storage.load_result(run_id)

    """

    def __init__(
        self,
        storage_dir: str | Path | None = None,
        auto_save: bool = True,
        compress: bool = False,
    ):
        """Initialise le gestionnaire de stockage.

        Args:
            storage_dir: Répertoire de stockage (défaut: backtest_results/)
            auto_save: Activer la sauvegarde automatique
            compress: Compresser les fichiers Parquet

        """
        _ensure_writable_tempdir()

        self.storage_dir = get_results_root_dir(storage_dir)
        self.runs_dir = self.storage_dir / "runs"
        self.auto_save = auto_save
        self.compress = compress
        self._store_v3 = BacktestStoreV3(root_dir=self.storage_dir)

        # Créer le répertoire si nécessaire
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

        # Chemin de l'index
        self.index_path = self.storage_dir / "index.json"

        # Charger ou créer l'index
        self._index: dict[str, StoredResultMetadata] = self._load_index()

        logger.info(f"ResultStorage initialisé: {self.storage_dir} ({len(self._index)} résultats)")

    def _canonical_run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def _legacy_run_dir(self, run_id: str) -> Path:
        return self.storage_dir / run_id

    def _resolve_run_dir(self, run_id: str) -> Path:
        canonical_dir = self._canonical_run_dir(run_id)
        if canonical_dir.exists():
            return canonical_dir

        legacy_dir = self._legacy_run_dir(run_id)
        if legacy_dir.exists():
            return legacy_dir

        raise FileNotFoundError(f"Run inexistant: {run_id}")

    def _metadata_from_v3_row(self, row: dict[str, Any]) -> StoredResultMetadata:
        metrics = normalize_metrics(
            _sanitize_pct_metrics_payload(
                {
                    "total_return_pct": row.get("total_return_pct"),
                    "sharpe_ratio": row.get("sharpe_ratio"),
                    "max_drawdown_pct": row.get("max_drawdown_pct"),
                    "total_trades": row.get("n_trades"),
                },
                run_id_hint=str(row.get("run_id") or ""),
                context="_metadata_from_v3_row",
            ),
            "pct",
        )
        extra_metadata = dict(row.get("extra", {}) or {})
        return StoredResultMetadata(
            run_id=str(row.get("run_id", "")),
            timestamp=str(row.get("created_at", datetime.now().isoformat())),
            strategy=str(row.get("strategy", "unknown")),
            symbol=str(row.get("symbol", "unknown")),
            timeframe=str(row.get("timeframe", "unknown")),
            params=dict(row.get("params", {}) or {}),
            metrics=metrics,
            n_bars=int(extra_metadata.get("n_bars") or 0),
            n_trades=int(row.get("n_trades") or 0),
            period_start=str(row.get("period_start") or ""),
            period_end=str(row.get("period_end") or ""),
            duration_sec=float(row.get("duration_sec") or 0.0),
            mode=str(row.get("mode") or "backtest"),
            status=_status_from_store(row.get("status")),
            extra_metadata=extra_metadata,
        )

    def _iter_legacy_run_dirs(self):
        for item in self.storage_dir.iterdir():
            if not item.is_dir() or item.name in {"_catalog", "__pycache__", "runs"}:
                continue
            metadata_path = item / "metadata.json"
            if not metadata_path.exists():
                continue
            try:
                meta_dict = _load_json_file(metadata_path)
            except Exception:
                continue
            if _is_native_stored_metadata(meta_dict):
                yield item

    def _iter_canonical_run_dirs(self):
        if not self.runs_dir.exists():
            return
        for item in self.runs_dir.iterdir():
            if not item.is_dir():
                continue
            metadata_path = item / "metadata.json"
            if not metadata_path.exists():
                continue
            try:
                meta_dict = _load_json_file(metadata_path)
            except Exception:
                continue
            if _is_native_stored_metadata(meta_dict) or _is_v3_stored_metadata(meta_dict):
                yield item

    def _build_stored_metadata(self, run_dir: Path) -> StoredResultMetadata:
        return _stored_metadata_from_payload(_load_json_file(run_dir / "metadata.json"), run_id_hint=run_dir.name)

    def _refresh_index_cache(self) -> dict[str, StoredResultMetadata]:
        index: dict[str, StoredResultMetadata] = {}

        try:
            v3_df = self._store_v3.query_runs(limit=0, status=None)
        except Exception as e:
            logger.warning(f"⚠️ Impossible de lire l'index v3: {e}")
            v3_df = pd.DataFrame()

        if not v3_df.empty:
            for row in v3_df.to_dict(orient="records"):
                try:
                    metadata = self._metadata_from_v3_row(row)
                    index[metadata.run_id] = metadata
                except Exception as e:
                    logger.warning(f"⚠️ Ligne v3 ignorée pour {row.get('run_id')}: {e}")

        for run_dir in self._iter_canonical_run_dirs() or []:
            if run_dir.name in index:
                continue
            try:
                index[run_dir.name] = self._build_stored_metadata(run_dir)
            except Exception as e:
                logger.warning(f"⚠️ Run canonique non indexé {run_dir.name}: {e}")

        for run_dir in self._iter_legacy_run_dirs():
            if run_dir.name in index:
                continue
            try:
                index[run_dir.name] = self._build_stored_metadata(run_dir)
            except Exception as e:
                logger.warning(f"⚠️ Run legacy non indexé {run_dir.name}: {e}")

        return index

    # =========================================================================
    # SAUVEGARDE
    # =========================================================================

    def save_result(
        self,
        result: RunResult,
        run_id: str | None = None,
        auto_cleanup: bool = False,
    ) -> str:
        """Sauvegarde un résultat de backtest.

        Args:
            result: RunResult à sauvegarder
            run_id: ID personnalisé (sinon utilise result.meta['run_id'])
            auto_cleanup: Nettoyer les anciens résultats si trop nombreux

        Returns:
            run_id du résultat sauvegardé

        """
        try:
            metrics_pct = normalize_metrics(result.metrics, "pct")
            meta_n_bars = result.meta.get("n_bars")
            try:
                n_bars = int(meta_n_bars) if meta_n_bars is not None else len(result.equity)
            except (TypeError, ValueError):
                n_bars = len(result.equity)

            meta_n_trades = result.meta.get("n_trades")
            try:
                n_trades = int(meta_n_trades) if meta_n_trades is not None else len(result.trades)
            except (TypeError, ValueError):
                n_trades = len(result.trades)

            extra_metadata = _extract_result_extra_metadata(result.meta)
            mode = str(result.meta.get("mode") or result.meta.get("origin") or "backtest")
            status = "partial" if extra_metadata.get("ui_partial_run") else str(result.meta.get("status") or "ok")
            period_start = as_jsonable(result.meta.get("period_start", ""))
            period_end = as_jsonable(result.meta.get("period_end", ""))
            saved = self._store_v3.save_run(
                run_id=run_id or result.meta.get("run_id"),
                mode=mode,
                status=_status_to_store(status),
                strategy=result.meta.get("strategy", "unknown"),
                symbol=result.meta.get("symbol", "unknown"),
                timeframe=result.meta.get("timeframe", "unknown"),
                metrics=result.metrics,
                params=result.meta.get("params", {}),
                equity=result.equity,
                trades=result.trades,
                returns=result.returns,
                period_start=period_start,
                period_end=period_end,
                duration_sec=result.meta.get("duration_sec", 0.0),
                extra={**dict(result.meta or {}), "n_bars": n_bars, **extra_metadata},
            )

            metadata = StoredResultMetadata(
                run_id=saved["run_id"],
                timestamp=str(saved.get("created_at") or datetime.now().isoformat()),
                strategy=result.meta.get("strategy", "unknown"),
                symbol=result.meta.get("symbol", "unknown"),
                timeframe=result.meta.get("timeframe", "unknown"),
                params=result.meta.get("params", {}),
                metrics=metrics_pct,
                n_bars=n_bars,
                n_trades=n_trades,
                period_start=str(period_start),
                period_end=str(period_end),
                duration_sec=result.meta.get("duration_sec", 0.0),
                mode=mode,
                status=_status_from_store(saved.get("status")),
                extra_metadata=extra_metadata,
            )

            self._index[metadata.run_id] = metadata
            self._save_index()

            # NOTE: build_catalogs() n'est PAS appelé automatiquement ici pour préserver
            # les performances. Appelez-le manuellement ou via UI si nécessaire.

            logger.info(f"✅ Résultat sauvegardé: {metadata.run_id} ({metadata.strategy})")

            # Nettoyage optionnel
            if auto_cleanup:
                self._cleanup_old_results()

            return metadata.run_id

        except Exception as e:
            logger.error(f"❌ Erreur lors de la sauvegarde: {e}")
            raise

    def save_sweep_results(
        self,
        sweep_results: SweepResults,
        sweep_id: str | None = None,
    ) -> str:
        """Sauvegarde les résultats d'un sweep.

        Args:
            sweep_results: SweepResults à sauvegarder
            sweep_id: ID personnalisé du sweep

        Returns:
            sweep_id

        """
        if sweep_id is None:
            sweep_id = f"sweep_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        sweep_dir = self.storage_dir / sweep_id
        sweep_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Sauvegarder le résumé
            summary = {
                "sweep_id": sweep_id,
                "timestamp": datetime.now().isoformat(),
                "n_completed": sweep_results.n_completed,
                "n_failed": sweep_results.n_failed,
                "total_time": sweep_results.total_time,
                "best_params": sweep_results.best_params,
                "best_metrics": normalize_metrics(sweep_results.best_metrics, "pct"),
                "resource_stats": sweep_results.resource_stats,
            }

            summary_path = sweep_dir / "summary.json"
            dump_json_payload(summary_path, summary)

            # Sauvegarder tous les résultats en DataFrame
            results_df = sweep_results.to_dataframe()
            results_path = sweep_dir / "all_results.parquet"
            results_df.to_parquet(
                results_path,
                compression="snappy" if self.compress else None,
                index=False,
            )

            logger.info(f"✅ Sweep sauvegardé: {sweep_id} ({sweep_results.n_completed} résultats)")

            return sweep_id

        except Exception as e:
            logger.error(f"❌ Erreur lors de la sauvegarde du sweep: {e}")
            if sweep_dir.exists():
                shutil.rmtree(sweep_dir)
            raise

    # =========================================================================
    # CHARGEMENT
    # =========================================================================

    def load_result(self, run_id: str) -> RunResult:
        """Charge un résultat de backtest.

        Args:
            run_id: ID du run à charger

        Returns:
            RunResult reconstruit

        Raises:
            FileNotFoundError: Si le run_id n'existe pas

        """
        run_dir = self._resolve_run_dir(run_id)

        try:
            # 1. Charger les métadonnées
            metadata_path = run_dir / "metadata.json"
            metadata_dict = _load_json_file(metadata_path)
            metadata = _stored_metadata_from_payload(metadata_dict, run_id_hint=run_id)

            # 2. Charger l'équité
            equity_path = run_dir / "equity.parquet"
            if equity_path.exists():
                equity_df = pd.read_parquet(equity_path)
                equity = equity_df["equity"]
            else:
                equity_csv = run_dir / "equity.csv"
                equity_df = pd.read_csv(equity_csv, index_col=0)
                equity = equity_df["equity"]

            # 3. Charger les trades
            trades_path = run_dir / "trades.parquet"
            if trades_path.exists():
                trades = pd.read_parquet(trades_path)
            else:
                trades = pd.read_csv(run_dir / "trades.csv")

            # 4. Charger les returns
            returns_path = run_dir / "returns.parquet"
            if returns_path.exists():
                returns_df = pd.read_parquet(returns_path)
                returns = returns_df["returns"]
            else:
                returns_df = pd.read_csv(run_dir / "returns.csv", index_col=0)
                returns = returns_df["returns"]

            # 5. Reconstruire le RunResult
            result = RunResult(
                equity=equity,
                returns=returns,
                trades=trades,
                metrics=metadata.metrics,
                meta={
                    "run_id": metadata.run_id,
                    "strategy": metadata.strategy,
                    "symbol": metadata.symbol,
                    "timeframe": metadata.timeframe,
                    "timestamp": metadata.timestamp,
                    "params": metadata.params,
                    "n_bars": metadata.n_bars,
                    "period_start": metadata.period_start,
                    "period_end": metadata.period_end,
                    "duration_sec": metadata.duration_sec,
                    "mode": metadata.mode,
                    "status": metadata.status,
                    "loaded_from_storage": True,
                    "loaded_at": datetime.now().isoformat(),
                },
            )
            if metadata.extra_metadata:
                result.meta.update(metadata.extra_metadata)

            logger.info(f"✅ Résultat chargé: {run_id}")
            return result

        except Exception as e:
            logger.error(f"❌ Erreur lors du chargement de {run_id}: {e}")
            raise

    def load_sweep_results(self, sweep_id: str) -> dict[str, Any]:
        """Charge les résultats d'un sweep.

        Args:
            sweep_id: ID du sweep

        Returns:
            Dict avec summary et results_df

        """
        sweep_dir = self.storage_dir / sweep_id

        if not sweep_dir.exists():
            raise FileNotFoundError(f"Sweep inexistant: {sweep_id}")

        try:
            # Charger le résumé
            summary_path = sweep_dir / "summary.json"
            with open(summary_path, encoding="utf-8") as f:
                summary = json.load(f)
            summary["best_metrics"] = normalize_metrics(
                summary.get("best_metrics", {}),
                "pct",
            )

            # Charger les résultats
            results_path = sweep_dir / "all_results.parquet"
            results_df = pd.read_parquet(results_path)

            logger.info(f"✅ Sweep chargé: {sweep_id}")

            return {
                "summary": summary,
                "results_df": results_df,
                "sweep_id": sweep_id,
            }

        except Exception as e:
            logger.error(f"❌ Erreur lors du chargement du sweep {sweep_id}: {e}")
            raise

    # =========================================================================
    # RECHERCHE & LISTAGE
    # =========================================================================

    def list_results(
        self,
        limit: int | None = None,
        sort_by: str = "timestamp",
        reverse: bool = True,
    ) -> list[StoredResultMetadata]:
        """Liste tous les résultats disponibles.

        Args:
            limit: Limiter le nombre de résultats
            sort_by: Champ de tri (timestamp, sharpe_ratio, etc.)
            reverse: Tri descendant

        Returns:
            Liste de métadonnées

        """
        results = list(self._index.values())

        # Tri
        if sort_by == "timestamp":
            results.sort(key=lambda x: x.timestamp, reverse=reverse)
        elif sort_by == "sharpe_ratio":
            results.sort(
                key=lambda x: x.metrics.get("sharpe_ratio", 0),
                reverse=reverse,
            )
        elif sort_by == "total_return":
            results.sort(
                key=lambda x: x.metrics.get("total_return_pct", 0),
                reverse=reverse,
            )

        # Limite
        if limit:
            results = results[:limit]

        return results

    def search_results(
        self,
        strategy: str | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        min_sharpe: float | None = None,
        max_drawdown: float | None = None,
        min_trades: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[StoredResultMetadata]:
        """Recherche des résultats avec filtres.

        Args:
            strategy: Nom de la stratégie
            symbol: Symbole
            timeframe: Timeframe
            min_sharpe: Sharpe ratio minimum
            max_drawdown: Drawdown maximum (%)
            min_trades: Nombre minimum de trades
            date_from: Date minimum (ISO format)
            date_to: Date maximum (ISO format)

        Returns:
            Liste de métadonnées filtrées

        """
        results = list(self._index.values())

        # Filtres
        if strategy:
            results = [r for r in results if r.strategy == strategy]

        if symbol:
            results = [r for r in results if r.symbol == symbol]

        if timeframe:
            results = [r for r in results if r.timeframe == timeframe]

        if min_sharpe is not None:
            results = [r for r in results if r.metrics.get("sharpe_ratio", 0) >= min_sharpe]

        if max_drawdown is not None:
            results = [r for r in results if r.metrics.get("max_drawdown_pct", 100) <= max_drawdown]

        if min_trades is not None:
            results = [r for r in results if r.n_trades >= min_trades]

        if date_from:
            results = [r for r in results if r.timestamp >= date_from]

        if date_to:
            results = [r for r in results if r.timestamp <= date_to]

        return results

    def get_best_results(
        self,
        n: int = 10,
        metric: str = "sharpe_ratio",
    ) -> list[StoredResultMetadata]:
        """Retourne les N meilleurs résultats selon une métrique.

        Args:
            n: Nombre de résultats
            metric: Métrique de tri

        Returns:
            Liste des meilleurs résultats

        """
        results = list(self._index.values())
        results.sort(
            key=lambda x: x.metrics.get(metric, float("-inf")),
            reverse=True,
        )
        return results[:n]

    # =========================================================================
    # GESTION
    # =========================================================================

    def delete_result(self, run_id: str) -> bool:
        """Supprime un résultat.

        Args:
            run_id: ID du run à supprimer

        Returns:
            True si supprimé, False sinon

        """
        try:
            run_dir = self._resolve_run_dir(run_id)
        except FileNotFoundError:
            logger.warning(f"⚠️ Run inexistant: {run_id}")
            return False

        try:
            shutil.rmtree(run_dir)

            if run_id in self._index:
                del self._index[run_id]
                self._save_index()

            logger.info(f"🗑️ Résultat supprimé: {run_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Erreur lors de la suppression: {e}")
            return False

    def _cleanup_old_results(self, keep_last: int = MAX_RESULTS_TO_KEEP) -> int:
        """Nettoie les anciens résultats pour éviter l'accumulation.

        Args:
            keep_last: Nombre de résultats à garder

        Returns:
            Nombre de résultats supprimés

        """
        results = list(self._index.values())
        results.sort(key=lambda x: x.timestamp, reverse=True)

        to_delete = results[keep_last:]
        deleted_count = 0

        for result in to_delete:
            if self.delete_result(result.run_id):
                deleted_count += 1

        if deleted_count > 0:
            logger.info(f"🧹 Nettoyage: {deleted_count} anciens résultats supprimés")

        return deleted_count

    def clear_all(self) -> bool:
        """Supprime TOUS les résultats (attention!).

        Returns:
            True si succès

        """
        try:
            if self.storage_dir.exists():
                shutil.rmtree(self.storage_dir)
                self.storage_dir.mkdir(parents=True, exist_ok=True)

            self._index = {}
            self._save_index()

            logger.warning("🧹 TOUS les résultats ont été supprimés")
            return True

        except Exception as e:
            logger.error(f"❌ Erreur lors du nettoyage: {e}")
            return False

    # =========================================================================
    # INDEX
    # =========================================================================

    def _load_index(self) -> dict[str, StoredResultMetadata]:
        """Charge l'index dérivé depuis SQLite v3 avec fallback legacy."""
        try:
            index = self._refresh_index_cache()
            if index:
                return index
        except Exception as e:
            logger.error(f"❌ Erreur lors du chargement dérivé de l'index: {e}")

        if not self.index_path.exists():
            return {}

        try:
            index_data = _load_json_file(self.index_path)
            index: dict[str, StoredResultMetadata] = {}
            for run_id, meta_dict in index_data.items():
                try:
                    metadata = _stored_metadata_from_payload(meta_dict, run_id_hint=run_id)
                    index[run_id] = metadata
                except Exception as e:
                    logger.warning(f"⚠️ Métadonnée corrompue pour {run_id}: {e}")
            return index
        except Exception as e:
            logger.error(f"❌ Erreur lors du fallback index.json: {e}")
            return {}

    def _save_index(self) -> None:
        """Sauvegarde l'index dérivé sur le disque."""
        try:
            index_data = {run_id: meta.to_dict() for run_id, meta in self._index.items()}

            dump_json_payload(self.index_path, index_data)

        except Exception as e:
            logger.error(f"❌ Erreur lors de la sauvegarde de l'index: {e}")

    def rebuild_index(self) -> int:
        """Reconstruit l'index en scannant tous les répertoires.

        Utile en cas de corruption ou si des fichiers ont été ajoutés manuellement.

        Returns:
            Nombre de résultats indexés

        """
        logger.info("🔄 Reconstruction de l'index...")

        self._index = self._refresh_index_cache()
        count = len(self._index)

        self._save_index()
        logger.info(f"✅ Index reconstruit: {count} résultats")

        return count

    def _iter_metadata_dirs(self):
        for metadata_path in self.storage_dir.rglob("metadata.json"):
            rel_parts = metadata_path.relative_to(self.storage_dir).parts
            if "_catalog" in rel_parts or "__pycache__" in rel_parts:
                continue
            yield metadata_path.parent

    def _build_unified_entry(self, run_dir: Path) -> dict[str, Any]:
        rel_path = str(run_dir.relative_to(self.storage_dir)).replace("\\", "/")
        parent_scope = rel_path.split("/", 1)[0] if "/" in rel_path else "."
        metadata_path = run_dir / "metadata.json"
        meta_dict = _load_json_file(metadata_path)

        if _is_native_stored_metadata(meta_dict) or _is_v3_stored_metadata(meta_dict):
            metadata = _stored_metadata_from_payload(meta_dict, run_id_hint=run_dir.name)
            issues = _native_run_missing_files(run_dir)
            return {
                "artifact_type": "saved_run",
                "schema": "native_saved_run",
                "path": rel_path,
                "parent_scope": parent_scope,
                "run_id": metadata.run_id,
                "timestamp": metadata.timestamp,
                "mode": metadata.mode,
                "status": metadata.status,
                "strategy": metadata.strategy,
                "symbol": metadata.symbol,
                "timeframe": metadata.timeframe,
                "n_bars": metadata.n_bars,
                "n_trades": metadata.n_trades,
                "duration_sec": metadata.duration_sec,
                "period_start": metadata.period_start,
                "period_end": metadata.period_end,
                "params": metadata.params,
                "metrics": metadata.metrics,
                "extra_metadata": metadata.extra_metadata,
                "loadable": len(issues) == 0,
                "issues": issues,
            }

        metrics_path = run_dir / "metrics.json"
        metrics = _load_json_file(metrics_path) if metrics_path.exists() else {}
        extra_metadata = dict(meta_dict.get("extra", {}) or {})
        n_trades = meta_dict.get("n_trades", metrics.get("total_trades", 0))
        try:
            n_trades = int(n_trades)
        except (TypeError, ValueError):
            n_trades = 0

        issues: list[str] = []
        if not metrics_path.exists():
            issues.append("metrics.json")

        return {
            "artifact_type": "external_run",
            "schema": "runner_manifest",
            "path": rel_path,
            "parent_scope": parent_scope,
            "run_id": str(meta_dict.get("run_id", run_dir.name)),
            "timestamp": str(meta_dict.get("created_at", "")),
            "mode": str(meta_dict.get("mode", "unknown") or "unknown"),
            "status": str(meta_dict.get("status", "unknown") or "unknown"),
            "strategy": str(meta_dict.get("strategy", "unknown") or "unknown"),
            "symbol": str(meta_dict.get("symbol", "unknown") or "unknown"),
            "timeframe": str(meta_dict.get("timeframe", "unknown") or "unknown"),
            "n_bars": int(meta_dict.get("n_bars", 0) or 0),
            "n_trades": n_trades,
            "duration_sec": float(meta_dict.get("duration_sec", 0.0) or 0.0),
            "period_start": str(meta_dict.get("period_start", "")),
            "period_end": str(meta_dict.get("period_end", "")),
            "params": dict(meta_dict.get("params", {}) or {}),
            "metrics": dict(metrics or {}),
            "extra_metadata": extra_metadata,
            "loadable": False,
            "issues": issues,
        }

    def audit_storage(self, write_report: bool = True) -> dict[str, Any]:
        catalog_dir = self.storage_dir / "_catalog"
        catalog_dir.mkdir(parents=True, exist_ok=True)

        entries = [self._build_unified_entry(run_dir) for run_dir in self._iter_metadata_dirs()]
        containers: list[str] = []
        unknown_directories: list[str] = []

        for item in self.storage_dir.iterdir():
            if not item.is_dir() or item.name in {"_catalog", "__pycache__"}:
                continue
            if (item / "metadata.json").exists():
                continue
            if _has_any_child_metadata(item):
                containers.append(item.name)
            else:
                unknown_directories.append(item.name)

        invalid_entries = [entry for entry in entries if entry.get("issues")]
        report = {
            "summary": {
                "entries": len(entries),
                "loadable_entries": sum(1 for entry in entries if entry.get("loadable")),
                "native_entries": sum(1 for entry in entries if entry.get("schema") == "native_saved_run"),
                "external_entries": sum(1 for entry in entries if entry.get("schema") == "runner_manifest"),
                "invalid_entries": len(invalid_entries),
                "containers": len(containers),
                "unknown_directories": len(unknown_directories),
            },
            "containers": sorted(containers),
            "unknown_directories": sorted(unknown_directories),
            "invalid_entries": invalid_entries,
            "entries": entries,
        }

        if write_report:
            report_path = catalog_dir / "storage_audit.json"
            dump_json_payload(report_path, report)

        return report

    def build_catalogs(self, force: bool = False) -> Path:
        """Génère des catalogues CSV pour exploration rapide des résultats.

        `overview.csv` couvre les runs natifs chargeables via `ResultStorage`.
        `unified_overview.csv` consolide aussi les artefacts trouvés récursivement
        (ex: `backtest_results/runs/*`) pour offrir une vue transversale du stock.
        """
        catalog_dir = self.storage_dir / "_catalog"
        catalog_dir.mkdir(parents=True, exist_ok=True)

        overview_path = catalog_dir / "overview.csv"
        unified_path = catalog_dir / "unified_overview.csv"

        if not force and overview_path.exists() and unified_path.exists():
            catalog_mtime = min(overview_path.stat().st_mtime, unified_path.stat().st_mtime)
            index_mtime = self.index_path.stat().st_mtime if self.index_path.exists() else 0
            if catalog_mtime > index_mtime:
                logger.info("✅ Catalogues déjà à jour (lazy skip)")
                return overview_path

        logger.info("📊 Génération des catalogues CSV...")

        rows = []
        for run_id, metadata in self._index.items():
            rows.append(_build_native_catalog_row(metadata))

        if rows:
            df = pd.DataFrame(rows)
            if "timestamp" in df.columns:
                df = df.sort_values("timestamp", ascending=False)
        else:
            logger.warning("⚠️ Aucun résultat natif à cataloguer")
            df = pd.DataFrame(
                columns=[
                    "type",
                    "id",
                    "run_id",
                    "timestamp",
                    "mode",
                    "status",
                    "strategy",
                    "symbol",
                    "timeframe",
                    "flags_account_ruined",
                ],
            )

        df.to_csv(overview_path, index=False, encoding="utf-8")

        audit_report = self.audit_storage(write_report=True)
        unified_rows = []
        for entry in audit_report["entries"]:
            unified_rows.append(_build_unified_catalog_row(entry))

        unified_df = pd.DataFrame(unified_rows)
        if not unified_df.empty and "timestamp" in unified_df.columns:
            unified_df = unified_df.sort_values("timestamp", ascending=False, na_position="last")
        unified_df.to_csv(unified_path, index=False, encoding="utf-8")

        logger.info(
            "✅ Catalogues générés: %s (%s natifs) | %s (%s entrées unifiées)",
            overview_path,
            len(rows),
            unified_path,
            len(unified_rows),
        )

        return overview_path

    def validate_integrity(self, auto_fix: bool = True) -> dict[str, list[str]]:
        """Valide la cohérence du stockage et répare si nécessaire.

        Vérifications:
        - Index.json cohérent avec les dossiers réels
        - Fichiers Parquet requis présents (equity, trades, returns)
        - Métadonnées valides

        Args:
            auto_fix: Tenter de réparer automatiquement les problèmes

        Returns:
            Dict avec clés:
            - errors: Liste des erreurs critiques
            - warnings: Liste des avertissements
            - fixed: Liste des problèmes réparés

        Example:
            >>> storage = get_storage()
            >>> report = storage.validate_integrity()
            >>> if report["errors"]:
            ...     print(f"Erreurs: {report['errors']}")

        """
        logger.info("🔍 Validation de l'intégrité du stockage...")

        errors: list[str] = []
        warnings: list[str] = []
        fixed: list[str] = []

        # 1. Vérifier que l'index existe
        if not self.index_path.exists():
            warnings.append("Index.json manquant")
            if auto_fix:
                self._save_index()
                fixed.append("Index.json créé")

        # 2. Scanner les dossiers réellement gérés par ResultStorage
        actual_dirs = set()
        container_dirs = set()
        for item in self.storage_dir.iterdir():
            if not item.is_dir() or item.name in ["_catalog", "__pycache__"]:
                continue
            if item.name == "runs":
                container_dirs.add(item.name)
                for run_dir in self._iter_canonical_run_dirs() or []:
                    actual_dirs.add(run_dir.name)
                continue
            metadata_path = item / "metadata.json"
            if metadata_path.exists():
                try:
                    meta_dict = _load_json_file(metadata_path)
                except Exception as e:
                    errors.append(f"Impossible de lire metadata.json dans {item.name}: {e}")
                    continue
                if _is_native_stored_metadata(meta_dict) or _is_v3_stored_metadata(meta_dict):
                    actual_dirs.add(item.name)
                else:
                    container_dirs.add(item.name)
            elif _has_any_child_metadata(item):
                container_dirs.add(item.name)

        # 3. Comparer index vs dossiers réels
        indexed_runs = set(self._index.keys())

        # Runs dans l'index mais dossier manquant
        missing_dirs = indexed_runs - actual_dirs
        for run_id in missing_dirs:
            warnings.append(f"Dossier manquant pour run_id indexé: {run_id}")
            if auto_fix:
                del self._index[run_id]
                fixed.append(f"Supprimé de l'index: {run_id}")

        # Dossiers présents mais non indexés
        unindexed_dirs = actual_dirs - indexed_runs
        for dir_name in unindexed_dirs:
            warnings.append(f"Dossier non indexé: {dir_name}")
            if auto_fix:
                # Tenter de charger et indexer
                try:
                    metadata_path = self._canonical_run_dir(dir_name) / "metadata.json"
                    if not metadata_path.exists():
                        metadata_path = self._legacy_run_dir(dir_name) / "metadata.json"
                    if metadata_path.exists():
                        meta_dict = _load_json_file(metadata_path)
                        metadata = _stored_metadata_from_payload(meta_dict, run_id_hint=dir_name)
                        self._index[metadata.run_id] = metadata
                        fixed.append(f"Ajouté à l'index: {dir_name}")
                    else:
                        warnings.append(f"Pas de metadata.json dans {dir_name}")
                except Exception as e:
                    errors.append(f"Impossible d'indexer {dir_name}: {e}")

        # 4. Vérifier les fichiers requis pour chaque run indexé
        for run_id in list(self._index.keys()):
            try:
                run_dir = self._resolve_run_dir(run_id)
            except FileNotFoundError:
                continue  # Déjà traité ci-dessus

            missing_files = _native_run_missing_files(run_dir)
            for filename in missing_files:
                warnings.append(f"{run_id}: Fichier manquant {filename}")

        # 5. Sauvegarder l'index si des corrections ont été apportées
        if fixed and auto_fix:
            self._save_index()
            logger.info("✅ Index mis à jour après réparation")

        # Rapport final
        logger.info(
            f"Validation terminée: {len(errors)} erreurs, {len(warnings)} avertissements, {len(fixed)} réparations",
        )

        return {
            "errors": errors,
            "warnings": warnings,
            "fixed": fixed,
        }

    def migrate_legacy_layout_to_runs_dir(self, delete_legacy: bool = True) -> int:
        """Migre manuellement les runs legacy racine vers le layout canonique runs/<run_id>."""
        migrated = 0

        for legacy_dir in list(self._iter_legacy_run_dirs()):
            run_id = legacy_dir.name
            if self._canonical_run_dir(run_id).exists():
                logger.warning(f"⚠️ Migration ignorée, cible déjà présente: {run_id}")
                continue

            result = self.load_result(run_id)
            self.save_result(result, run_id=run_id)
            migrated += 1

            if delete_legacy and legacy_dir.exists():
                shutil.rmtree(legacy_dir)

        if migrated:
            self._index = self._refresh_index_cache()
            self._save_index()

        return migrated


# =============================================================================
# INSTANCE GLOBALE
# =============================================================================

_storage_instance: ResultStorage | None = None


def get_storage(
    storage_dir: str | Path | None = None,
    auto_save: bool = True,
    compress: bool = False,
) -> ResultStorage:
    """Retourne l'instance globale de ResultStorage (singleton).

    Args:
        storage_dir: Répertoire de stockage
        auto_save: Activer la sauvegarde automatique
        compress: Compresser les fichiers

    Returns:
        ResultStorage instance

    """
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = ResultStorage(
            storage_dir=storage_dir,
            auto_save=auto_save,
            compress=compress,
        )
    return _storage_instance


def migrate_legacy_layout_to_runs_dir(
    storage_dir: str | Path | None = None,
    delete_legacy: bool = True,
) -> int:
    """Migre manuellement les runs legacy racine vers runs/<run_id>."""
    storage = ResultStorage(storage_dir=storage_dir)
    return storage.migrate_legacy_layout_to_runs_dir(delete_legacy=delete_legacy)


__all__ = [
    "ResultStorage",
    "StoredResultMetadata",
    "get_storage",
    "migrate_legacy_layout_to_runs_dir",
]


# Docstring update summary
# - Docstring de module normalisée (LLM-friendly) centrée sur persistance/indexation
# - Conventions structure répertoires et index.json explicitées
# - Read-if/Skip-if ajoutés pour tri rapide
