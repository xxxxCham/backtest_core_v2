"""
Module-ID: ui.log_taps

Purpose: Capture et suit le meilleur PnL des logs de backtest.

Role in pipeline: monitoring / metrics

Key components: BestPnlTracker

Inputs: Logs de backtest

Outputs: Meilleur PnL tracké

Dependencies: logging

Conventions: PnL en devise de base

Read-if: Tracking PnL en temps réel

Skip-if: Pas besoin de monitoring PnL
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Optional, Tuple

_BEST_PNL_TRACKER = None


class BestPnlTracker(logging.Handler):
    """
    Tracker du meilleur PnL de backtest (PnL total du meilleur run).
    Note: Capture le PnL TOTAL du backtest, pas le meilleur trade individuel.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.best_backtest_pnl: Optional[float] = None
        self.best_run_id: Optional[str] = None
        self._lock = threading.Lock()
        self._pnl_pattern = re.compile(
            r"\bpnl\s*=\s*[^0-9-+]*([-+]?\d+(?:\.\d+)?)",
            re.IGNORECASE,
        )

    def emit(self, record: logging.LogRecord) -> None:
        if record.name != "backtest.engine":
            return
        msg = record.getMessage()

        # Ignorer les logs qui ne sont pas des résultats de backtest complets
        if "pnl" not in msg.lower():
            return

        # Capturer uniquement le log final du backtest (pipeline_end)
        # qui contient le PnL TOTAL du backtest
        if "pipeline_end" not in msg and "duration_ms" not in msg:
            return

        match = self._pnl_pattern.search(msg)
        if not match:
            return
        try:
            pnl = float(match.group(1))
        except ValueError:
            return
        with self._lock:
            if self.best_backtest_pnl is None or pnl > self.best_backtest_pnl:
                self.best_backtest_pnl = pnl
                self.best_run_id = getattr(record, "run_id", None)

    def get_best(self) -> Tuple[Optional[float], Optional[str]]:
        with self._lock:
            return self.best_backtest_pnl, self.best_run_id


def install_best_pnl_tracker() -> BestPnlTracker:
    global _BEST_PNL_TRACKER
    if _BEST_PNL_TRACKER is not None:
        return _BEST_PNL_TRACKER
    logger = logging.getLogger("backtest")
    for handler in logger.handlers:
        if isinstance(handler, BestPnlTracker):
            _BEST_PNL_TRACKER = handler
            return handler
    tracker = BestPnlTracker()
    logger.addHandler(tracker)
    _BEST_PNL_TRACKER = tracker
    return tracker
