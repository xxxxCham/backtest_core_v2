"""Système de diagnostic pour sweeps multiprocess."""
import logging
import os
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


class SweepDiagnostics:
    """Logger de diagnostic pour sweeps avec journalisation fichier détaillée."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.start_time = time.perf_counter()
        self.log_dir = Path("sweep_diagnostics")
        self.log_dir.mkdir(exist_ok=True)

        # Fichier de log unique pour ce run
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"sweep_{timestamp}_{run_id}.log"

        # Logger Python
        self.logger = logging.getLogger(f"sweep_diag.{run_id}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        if self.logger.handlers:
            for handler in list(self.logger.handlers):
                self.logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

        # Handler fichier avec format détaillé
        fh = logging.FileHandler(self.log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        # Note: %f (microseconds) n'est pas supporté par time.strftime()
        # Utiliser un formateur custom ou accepter la précision à la seconde
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%H:%M:%S"
        )
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)

        # Compteurs
        self.submitted = 0
        self.completed = 0
        self.errors = 0
        self.timeouts = 0
        self.last_completion_time = time.perf_counter()

        self._log_header()

    def _log_header(self):
        """Log d'en-tête avec infos système."""
        self.logger.info("="*80)
        self.logger.info(f"SWEEP DIAGNOSTICS - Run ID: {self.run_id}")
        self.logger.info(f"Log file: {self.log_file}")
        self.logger.info(f"Python PID: {os.getpid()}")
        self.logger.info(f"Workers: {os.environ.get('BACKTEST_WORKER_THREADS', 'N/A')} threads")
        self.logger.info("="*80)

    def log_pool_start(self, n_workers: int, thread_limit: int, total_combos: int):
        """Log démarrage du pool."""
        self.logger.info(f"▶ POOL START: {n_workers} workers × {thread_limit} threads")
        self.logger.info(f"▶ Total combinaisons: {total_combos:,}")

    def log_submit(self, combo_idx: int, params: Dict[str, Any]):
        """Log soumission d'une combinaison."""
        self.submitted += 1
        elapsed = time.perf_counter() - self.start_time
        self.logger.debug(f"➤ SUBMIT #{combo_idx} ({self.submitted} total) @ {elapsed:.1f}s | {params}")

    def log_completion(self, combo_idx: int, params: Dict[str, Any], result: Dict[str, Any], duration_ms: float):
        """Log complétion normale."""
        self.completed += 1
        self.last_completion_time = time.perf_counter()
        elapsed = time.perf_counter() - self.start_time

        if "error" in result:
            self.errors += 1
            error_msg = result["error"][:100]
            self.logger.warning(f"✗ COMPLETE #{combo_idx} ERROR @ {elapsed:.1f}s ({duration_ms:.0f}ms) | {error_msg}")
        else:
            pnl = result.get("total_pnl", 0)
            sharpe = result.get("sharpe", 0)
            self.logger.debug(f"✓ COMPLETE #{combo_idx} @ {elapsed:.1f}s ({duration_ms:.0f}ms) | PnL={pnl:.2f} Sharpe={sharpe:.2f}")

    def log_timeout(self, combo_idx: int, params: Dict[str, Any], timeout_sec: float):
        """Log timeout worker."""
        self.timeouts += 1
        elapsed = time.perf_counter() - self.start_time
        self.logger.error(f"⏱ TIMEOUT #{combo_idx} @ {elapsed:.1f}s (>{timeout_sec:.0f}s) | {params}")

    def log_future_exception(self, combo_idx: int, params: Dict[str, Any], exc: Exception):
        """Log exception future."""
        self.errors += 1
        elapsed = time.perf_counter() - self.start_time
        self.logger.error(f"💥 EXCEPTION #{combo_idx} @ {elapsed:.1f}s | {type(exc).__name__}: {exc}")
        self.logger.debug(f"   Params: {params}")
        self.logger.debug(f"   Traceback:\n{traceback.format_exc()}")

    def log_pool_broken(self, reason: str, exc: Exception = None):
        """Log pool cassé."""
        elapsed = time.perf_counter() - self.start_time
        self.logger.critical(f"🔥 POOL BROKEN @ {elapsed:.1f}s | Reason: {reason}")
        if exc:
            self.logger.critical(f"   Exception: {type(exc).__name__}: {exc}")
            self.logger.debug(f"   Traceback:\n{traceback.format_exc()}")

    def log_stall(self, stall_duration: float, pending_count: int):
        """Log détection de stall."""
        elapsed = time.perf_counter() - self.start_time
        self.logger.error(f"⚠ STALL DETECTED @ {elapsed:.1f}s | No completion for {stall_duration:.0f}s | {pending_count} pending")

    def log_sequential_fallback(self, reason: str | None = None, remaining_combos: int | None = None):
        """Log bascule en séquentiel."""
        elapsed = time.perf_counter() - self.start_time
        details = []
        if reason:
            details.append(f"reason={reason}")
        if remaining_combos is not None:
            details.append(f"{remaining_combos} combos remaining")
        suffix = f" | {' | '.join(details)}" if details else ""
        self.logger.warning(f"🔄 FALLBACK SEQUENTIAL @ {elapsed:.1f}s{suffix}")

    def log_pool_shutdown(self, success: bool):
        """Log arrêt du pool."""
        elapsed = time.perf_counter() - self.start_time
        status = "SUCCESS" if success else "FAILURE"
        self.logger.info(f"⏹ POOL SHUTDOWN @ {elapsed:.1f}s | Status: {status}")
        self.logger.info(f"   Submitted: {self.submitted}")
        self.logger.info(f"   Completed: {self.completed}")
        self.logger.info(f"   Errors: {self.errors}")
        self.logger.info(f"   Timeouts: {self.timeouts}")
        self.logger.info(f"   Success rate: {self.completed/(self.submitted or 1)*100:.1f}%")

    def log_final_summary(self):
        """Log résumé final."""
        elapsed = time.perf_counter() - self.start_time
        self.logger.info("="*80)
        self.logger.info(f"SWEEP COMPLETED @ {elapsed:.1f}s")
        self.logger.info(f"Log saved to: {self.log_file}")
        self.logger.info("="*80)

    def get_stats(self) -> Dict[str, Any]:
        """Retourne stats actuelles."""
        return {
            "submitted": self.submitted,
            "completed": self.completed,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "elapsed": time.perf_counter() - self.start_time,
        }
