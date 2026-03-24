"""
Module-ID: backtest.storage

Purpose: Persister et indexer les résultats de backtests pour rechargement/recherche rapide.

Role in pipeline: persistence / reporting

Key components: ResultStorage, StoredResultMetadata, get_storage

Inputs: RunResult, run_id, auto_cleanup flag

Outputs: Fichiers JSON/Parquet dans backtest_results/{run_id}/, index.json

Dependencies: pandas, pathlib, json, optionnel: pyarrow (Parquet)

Conventions: Structure run_id/metadata.json + equity.parquet + trades.parquet; index.json catalogue; auto_cleanup garde N derniers runs.

Read-if: Persistance résultats, recherche historique, ou gestion stockage.

Skip-if: Backtests ponctuels sans sauvegarde.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from backtest.engine import RunResult
from backtest.result_store import get_results_root_dir
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
)


# =============================================================================
# TEMP DIR FIX (sandbox compatibility)
# =============================================================================

def _ensure_writable_tempdir() -> None:
    """
    Assure que tempfile utilise un répertoire writable dans les environnements sandbox.
    """
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

    def _safe_mkdtemp(suffix: Optional[str] = None, prefix: Optional[str] = None, dir: Optional[str] = None) -> str:
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

def _safe_to_parquet(
    df: pd.DataFrame,
    path: Path,
    *,
    compression: Optional[str] = None,
    index: Optional[bool] = None,
) -> None:
    try:
        if index is None:
            index = True
        df.to_parquet(path, compression=compression, index=index)
    except Exception as e:
        logger.warning(f"⚠️ Parquet non écrit ({path.name}): {e}")


def _write_series_csv(series: pd.Series, path: Path, name: str) -> None:
    df = series.to_frame(name=name)
    df.to_csv(path, index=True, encoding="utf-8")


def _write_dataframe_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8")


def _load_json_file(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload if isinstance(payload, dict) else {}


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


def _dump_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_as_jsonable(payload), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _extract_result_extra_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    extra: Dict[str, Any] = {}
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


def _is_native_stored_metadata(meta: Dict[str, Any]) -> bool:
    return "timestamp" in meta and isinstance(meta.get("metrics"), dict)


def _native_run_missing_files(run_dir: Path) -> List[str]:
    missing: List[str] = []
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
    params: Dict[str, Any]
    metrics: PerformanceMetricsPct
    n_bars: int
    n_trades: int
    period_start: str
    period_end: str
    duration_sec: float
    mode: str = "backtest"
    status: str = "ok"
    extra_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dict pour sérialisation."""
        payload = asdict(self)
        payload["metrics"] = normalize_metrics(self.metrics, "pct")
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StoredResultMetadata":
        """Crée depuis un dict."""
        metrics = normalize_metrics(data.get("metrics", {}), "pct")
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


# =============================================================================
# STORAGE ENGINE
# =============================================================================

class ResultStorage:
    """
    Gestionnaire de stockage des résultats de backtests.

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
        storage_dir: Optional[Union[str, Path]] = None,
        auto_save: bool = True,
        compress: bool = False,
    ):
        """
        Initialise le gestionnaire de stockage.

        Args:
            storage_dir: Répertoire de stockage (défaut: backtest_results/)
            auto_save: Activer la sauvegarde automatique
            compress: Compresser les fichiers Parquet
        """
        _ensure_writable_tempdir()

        self.storage_dir = get_results_root_dir(storage_dir)
        self.auto_save = auto_save
        self.compress = compress

        # Créer le répertoire si nécessaire
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Chemin de l'index
        self.index_path = self.storage_dir / "index.json"

        # Charger ou créer l'index
        self._index: Dict[str, StoredResultMetadata] = self._load_index()

        logger.info(f"ResultStorage initialisé: {self.storage_dir} ({len(self._index)} résultats)")

    # =========================================================================
    # SAUVEGARDE
    # =========================================================================

    def save_result(
        self,
        result: RunResult,
        run_id: Optional[str] = None,
        auto_cleanup: bool = False,
    ) -> str:
        """
        Sauvegarde un résultat de backtest.

        Args:
            result: RunResult à sauvegarder
            run_id: ID personnalisé (sinon utilise result.meta['run_id'])
            auto_cleanup: Nettoyer les anciens résultats si trop nombreux

        Returns:
            run_id du résultat sauvegardé
        """
        # Récupérer ou générer le run_id
        if run_id is None:
            run_id = result.meta.get("run_id", f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

        # Créer le répertoire du run
        run_dir = self.storage_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Sauvegarder les métadonnées
            metrics_pct = normalize_metrics(result.metrics, "pct")
            meta_n_bars = result.meta.get("n_bars")
            try:
                n_bars = int(meta_n_bars) if meta_n_bars is not None else int(len(result.equity))
            except (TypeError, ValueError):
                n_bars = int(len(result.equity))

            meta_n_trades = result.meta.get("n_trades")
            try:
                n_trades = int(meta_n_trades) if meta_n_trades is not None else int(len(result.trades))
            except (TypeError, ValueError):
                n_trades = int(len(result.trades))

            extra_metadata = _extract_result_extra_metadata(result.meta)
            mode = str(result.meta.get("mode") or result.meta.get("origin") or "backtest")
            status = "partial" if extra_metadata.get("ui_partial_run") else str(result.meta.get("status") or "ok")

            metadata = StoredResultMetadata(
                run_id=run_id,
                timestamp=datetime.now().isoformat(),
                strategy=result.meta.get("strategy", "unknown"),
                symbol=result.meta.get("symbol", "unknown"),
                timeframe=result.meta.get("timeframe", "unknown"),
                params=result.meta.get("params", {}),
                metrics=metrics_pct,
                n_bars=n_bars,
                n_trades=n_trades,
                period_start=result.meta.get("period_start", ""),
                period_end=result.meta.get("period_end", ""),
                duration_sec=result.meta.get("duration_sec", 0.0),
                mode=mode,
                status=status,
                extra_metadata=extra_metadata,
            )

            metadata_path = run_dir / "metadata.json"
            _dump_json(metadata_path, metadata.to_dict())

            # 2. Sauvegarder la courbe d'équité
            equity_path = run_dir / "equity.parquet"
            equity_df = result.equity.to_frame(name="equity")
            _safe_to_parquet(
                equity_df,
                equity_path,
                compression="snappy" if self.compress else None,
                index=True,
            )
            _write_series_csv(result.equity, run_dir / "equity.csv", "equity")

            # 3. Sauvegarder les trades
            trades_path = run_dir / "trades.parquet"
            _safe_to_parquet(
                result.trades,
                trades_path,
                compression="snappy" if self.compress else None,
                index=False,
            )
            _write_dataframe_csv(result.trades, run_dir / "trades.csv")

            # 4. Sauvegarder les returns
            returns_path = run_dir / "returns.parquet"
            returns_df = result.returns.to_frame(name="returns")
            _safe_to_parquet(
                returns_df,
                returns_path,
                compression="snappy" if self.compress else None,
                index=True,
            )
            _write_series_csv(result.returns, run_dir / "returns.csv", "returns")

            # 4b. Rapport JSON/MD (artefacts unifiés)
            report_payload = {
                "run_id": run_id,
                "timestamp": metadata.timestamp,
                "strategy": metadata.strategy,
                "symbol": metadata.symbol,
                "timeframe": metadata.timeframe,
                "params": metadata.params,
                "metrics": metadata.to_dict().get("metrics", metrics_pct),
                "n_bars": metadata.n_bars,
                "n_trades": metadata.n_trades,
                "period_start": metadata.period_start,
                "period_end": metadata.period_end,
                "duration_sec": metadata.duration_sec,
                "mode": metadata.mode,
                "status": metadata.status,
                "extra_metadata": metadata.extra_metadata,
            }
            report_json_path = run_dir / "report.json"
            _dump_json(report_json_path, report_payload)

            report_md_path = run_dir / "report.md"
            report_lines = [
                "# Rapport Backtest",
                "",
                f"- Run ID: `{run_id}`",
                f"- Stratégie: **{metadata.strategy}**",
                f"- Symbole: **{metadata.symbol}**",
                f"- Timeframe: **{metadata.timeframe}**",
                f"- Période: {metadata.period_start} → {metadata.period_end}",
                f"- Trades: {metadata.n_trades}",
                "",
                "## Métriques clés",
                "",
                f"- Return %: {metrics_pct.get('total_return_pct', 0):.2f}%",
                f"- Sharpe: {metrics_pct.get('sharpe_ratio', 0):.2f}",
                f"- Max DD %: {metrics_pct.get('max_drawdown_pct', metrics_pct.get('max_drawdown', 0)):.2f}%",
            ]
            report_md_path.write_text("\n".join(report_lines), encoding="utf-8")

            # 5. Mettre à jour l'index
            self._index[run_id] = metadata
            self._save_index()

            # NOTE: build_catalogs() n'est PAS appelé automatiquement ici pour préserver
            # les performances. Appelez-le manuellement ou via UI si nécessaire.

            logger.info(f"✅ Résultat sauvegardé: {run_id} ({metadata.strategy})")

            # Nettoyage optionnel
            if auto_cleanup:
                self._cleanup_old_results()

            return run_id

        except Exception as e:
            logger.error(f"❌ Erreur lors de la sauvegarde: {e}")
            # Nettoyer en cas d'erreur
            if run_dir.exists():
                shutil.rmtree(run_dir)
            raise

    def save_sweep_results(
        self,
        sweep_results: SweepResults,
        sweep_id: Optional[str] = None,
    ) -> str:
        """
        Sauvegarde les résultats d'un sweep.

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
            _dump_json(summary_path, summary)

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
        """
        Charge un résultat de backtest.

        Args:
            run_id: ID du run à charger

        Returns:
            RunResult reconstruit

        Raises:
            FileNotFoundError: Si le run_id n'existe pas
        """
        run_dir = self.storage_dir / run_id

        if not run_dir.exists():
            raise FileNotFoundError(f"Run inexistant: {run_id}")

        try:
            # 1. Charger les métadonnées
            metadata_path = run_dir / "metadata.json"
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata_dict = json.load(f)
            metadata = StoredResultMetadata.from_dict(metadata_dict)

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
                    "params": metadata.params,
                    "n_bars": metadata.n_bars,
                    "period_start": metadata.period_start,
                    "period_end": metadata.period_end,
                    "duration_sec": metadata.duration_sec,
                    "mode": metadata.mode,
                    "status": metadata.status,
                    "loaded_from_storage": True,
                    "loaded_at": datetime.now().isoformat(),
                }
            )
            if metadata.extra_metadata:
                result.meta.update(metadata.extra_metadata)

            logger.info(f"✅ Résultat chargé: {run_id}")
            return result

        except Exception as e:
            logger.error(f"❌ Erreur lors du chargement de {run_id}: {e}")
            raise

    def load_sweep_results(self, sweep_id: str) -> Dict[str, Any]:
        """
        Charge les résultats d'un sweep.

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
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
            summary["best_metrics"] = normalize_metrics(
                summary.get("best_metrics", {}), "pct"
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
        limit: Optional[int] = None,
        sort_by: str = "timestamp",
        reverse: bool = True,
    ) -> List[StoredResultMetadata]:
        """
        Liste tous les résultats disponibles.

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
                reverse=reverse
            )
        elif sort_by == "total_return":
            results.sort(
                key=lambda x: x.metrics.get("total_return_pct", 0),
                reverse=reverse
            )

        # Limite
        if limit:
            results = results[:limit]

        return results

    def search_results(
        self,
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        min_sharpe: Optional[float] = None,
        max_drawdown: Optional[float] = None,
        min_trades: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[StoredResultMetadata]:
        """
        Recherche des résultats avec filtres.

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
            results = [
                r for r in results
                if r.metrics.get("sharpe_ratio", 0) >= min_sharpe
            ]

        if max_drawdown is not None:
            results = [
                r for r in results
                if r.metrics.get("max_drawdown_pct", 100) <= max_drawdown
            ]

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
    ) -> List[StoredResultMetadata]:
        """
        Retourne les N meilleurs résultats selon une métrique.

        Args:
            n: Nombre de résultats
            metric: Métrique de tri

        Returns:
            Liste des meilleurs résultats
        """
        results = list(self._index.values())
        results.sort(
            key=lambda x: x.metrics.get(metric, float("-inf")),
            reverse=True
        )
        return results[:n]

    # =========================================================================
    # GESTION
    # =========================================================================

    def delete_result(self, run_id: str) -> bool:
        """
        Supprime un résultat.

        Args:
            run_id: ID du run à supprimer

        Returns:
            True si supprimé, False sinon
        """
        run_dir = self.storage_dir / run_id

        if not run_dir.exists():
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
        """
        Nettoie les anciens résultats pour éviter l'accumulation.

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
        """
        Supprime TOUS les résultats (attention!).

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

    def _load_index(self) -> Dict[str, StoredResultMetadata]:
        """Charge l'index depuis le disque."""
        if not self.index_path.exists():
            return {}

        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)

            # Reconstruire les objets StoredResultMetadata
            index = {}
            for run_id, meta_dict in index_data.items():
                try:
                    index[run_id] = StoredResultMetadata.from_dict(meta_dict)
                except Exception as e:
                    logger.warning(f"⚠️ Métadonnée corrompue pour {run_id}: {e}")

            return index

        except Exception as e:
            logger.error(f"❌ Erreur lors du chargement de l'index: {e}")
            return {}

    def _save_index(self) -> None:
        """Sauvegarde l'index sur le disque."""
        try:
            index_data = {
                run_id: meta.to_dict()
                for run_id, meta in self._index.items()
            }

            _dump_json(self.index_path, index_data)

        except Exception as e:
            logger.error(f"❌ Erreur lors de la sauvegarde de l'index: {e}")

    def rebuild_index(self) -> int:
        """
        Reconstruit l'index en scannant tous les répertoires.

        Utile en cas de corruption ou si des fichiers ont été ajoutés manuellement.

        Returns:
            Nombre de résultats indexés
        """
        logger.info("🔄 Reconstruction de l'index...")

        self._index = {}
        count = 0

        for run_dir in self.storage_dir.iterdir():
            if not run_dir.is_dir():
                continue

            metadata_path = run_dir / "metadata.json"
            if not metadata_path.exists():
                continue

            try:
                meta_dict = _load_json_file(metadata_path)
                if not _is_native_stored_metadata(meta_dict):
                    continue

                metadata = StoredResultMetadata.from_dict(meta_dict)
                self._index[metadata.run_id] = metadata
                count += 1

            except Exception as e:
                logger.warning(f"⚠️ Impossible de charger {run_dir.name}: {e}")

        self._save_index()
        logger.info(f"✅ Index reconstruit: {count} résultats")

        return count

    def _iter_metadata_dirs(self):
        for metadata_path in self.storage_dir.rglob("metadata.json"):
            rel_parts = metadata_path.relative_to(self.storage_dir).parts
            if "_catalog" in rel_parts or "__pycache__" in rel_parts:
                continue
            yield metadata_path.parent

    def _build_unified_entry(self, run_dir: Path) -> Dict[str, Any]:
        rel_path = str(run_dir.relative_to(self.storage_dir)).replace("\\", "/")
        parent_scope = rel_path.split("/", 1)[0] if "/" in rel_path else "."
        metadata_path = run_dir / "metadata.json"
        meta_dict = _load_json_file(metadata_path)

        if _is_native_stored_metadata(meta_dict):
            metadata = StoredResultMetadata.from_dict(meta_dict)
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

        issues: List[str] = []
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

    def audit_storage(self, write_report: bool = True) -> Dict[str, Any]:
        catalog_dir = self.storage_dir / "_catalog"
        catalog_dir.mkdir(parents=True, exist_ok=True)

        entries = [self._build_unified_entry(run_dir) for run_dir in self._iter_metadata_dirs()]
        containers: List[str] = []
        unknown_directories: List[str] = []

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
            _dump_json(report_path, report)

        return report

    def build_catalogs(self, force: bool = False) -> Path:
        """
        Génère des catalogues CSV pour exploration rapide des résultats.

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
            row = {
                "type": "run",
                "id": run_id,
                "run_id": run_id,
                "path": run_id,
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
            }

            for key, value in (metadata.params or {}).items():
                row[f"params_{key}"] = value

            for key, value in (metadata.metrics or {}).items():
                row[f"metrics_{key}"] = value

            for key, value in (metadata.extra_metadata or {}).items():
                row[f"extra_{key}"] = value

            row["flags_account_ruined"] = bool(metadata.metrics.get("account_ruined", False))
            rows.append(row)

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
                ]
            )

        df.to_csv(overview_path, index=False, encoding="utf-8")

        audit_report = self.audit_storage(write_report=True)
        unified_rows = []
        for entry in audit_report["entries"]:
            row = {
                "artifact_type": entry.get("artifact_type"),
                "schema": entry.get("schema"),
                "path": entry.get("path"),
                "parent_scope": entry.get("parent_scope"),
                "run_id": entry.get("run_id"),
                "timestamp": entry.get("timestamp"),
                "mode": entry.get("mode"),
                "status": entry.get("status"),
                "strategy": entry.get("strategy"),
                "symbol": entry.get("symbol"),
                "timeframe": entry.get("timeframe"),
                "loadable": entry.get("loadable"),
                "n_bars": entry.get("n_bars"),
                "n_trades": entry.get("n_trades"),
                "duration_sec": entry.get("duration_sec"),
                "period_start": entry.get("period_start"),
                "period_end": entry.get("period_end"),
                "issues": "; ".join(entry.get("issues", [])),
            }
            for key, value in (entry.get("params", {}) or {}).items():
                row[f"params_{key}"] = value
            for key, value in (entry.get("metrics", {}) or {}).items():
                row[f"metrics_{key}"] = value
            for key, value in (entry.get("extra_metadata", {}) or {}).items():
                row[f"extra_{key}"] = value
            unified_rows.append(row)

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

    def validate_integrity(self, auto_fix: bool = True) -> Dict[str, List[str]]:
        """
        Valide la cohérence du stockage et répare si nécessaire.

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

        errors: List[str] = []
        warnings: List[str] = []
        fixed: List[str] = []

        # 1. Vérifier que l'index existe
        if not self.index_path.exists():
            warnings.append("Index.json manquant")
            if auto_fix:
                self._save_index()
                fixed.append("Index.json créé")

        # 2. Scanner les dossiers racine réellement gérés par ResultStorage
        actual_dirs = set()
        container_dirs = set()
        for item in self.storage_dir.iterdir():
            if not item.is_dir() or item.name in ["_catalog", "__pycache__"]:
                continue
            metadata_path = item / "metadata.json"
            if metadata_path.exists():
                try:
                    meta_dict = _load_json_file(metadata_path)
                except Exception as e:
                    errors.append(f"Impossible de lire metadata.json dans {item.name}: {e}")
                    continue
                if _is_native_stored_metadata(meta_dict):
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
                    metadata_path = self.storage_dir / dir_name / "metadata.json"
                    if metadata_path.exists():
                        meta_dict = _load_json_file(metadata_path)
                        metadata = StoredResultMetadata.from_dict(meta_dict)
                        self._index[metadata.run_id] = metadata
                        fixed.append(f"Ajouté à l'index: {dir_name}")
                    else:
                        warnings.append(f"Pas de metadata.json dans {dir_name}")
                except Exception as e:
                    errors.append(f"Impossible d'indexer {dir_name}: {e}")

        # 4. Vérifier les fichiers requis pour chaque run indexé
        for run_id in list(self._index.keys()):
            run_dir = self.storage_dir / run_id
            if not run_dir.exists():
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
            f"Validation terminée: {len(errors)} erreurs, "
            f"{len(warnings)} avertissements, {len(fixed)} réparations"
        )

        return {
            "errors": errors,
            "warnings": warnings,
            "fixed": fixed,
        }


# =============================================================================
# INSTANCE GLOBALE
# =============================================================================

_storage_instance: Optional[ResultStorage] = None


def get_storage(
    storage_dir: Optional[Union[str, Path]] = None,
    auto_save: bool = True,
    compress: bool = False,
) -> ResultStorage:
    """
    Retourne l'instance globale de ResultStorage (singleton).

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


__all__ = [
    "ResultStorage",
    "StoredResultMetadata",
    "get_storage",
]


# Docstring update summary
# - Docstring de module normalisée (LLM-friendly) centrée sur persistance/indexation
# - Conventions structure répertoires et index.json explicitées
# - Read-if/Skip-if ajoutés pour tri rapide
