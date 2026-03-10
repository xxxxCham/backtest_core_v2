"""
Module-ID: agents.thought_stream

Purpose: Flux de réflexion en temps réel du Strategy Builder.
         Écrit un fichier Markdown lisible que l'utilisateur surveille en terminal.

Role in pipeline: observabilité

Usage (terminal PowerShell) :
    Get-Content sandbox_strategies\\_live_thoughts.md -Wait -Tail 50

Skip-if: Vous n'utilisez pas le Strategy Builder.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Fichier fixe — toujours le même pour la session courante
STREAM_FILE = Path(__file__).resolve().parent.parent / "sandbox_strategies" / "_live_thoughts.md"


class ThoughtStream:
    """Écrit les réflexions du Strategy Builder dans un fichier Markdown temps réel.

    Chaque méthode append une section formatée.
    Le fichier est flushé après chaque écriture et peut être
    surveillé via ``Get-Content ... -Wait`` ou ``tail -f``.
    """

    def __init__(
        self,
        session_id: str,
        objective: str,
        model: str,
        *,
        path: Optional[Path] = None,
    ):
        self.path = path or STREAM_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_header(session_id, objective, model)

    # ------------------------------------------------------------------ #
    # En-tête de session
    # ------------------------------------------------------------------ #

    def _write_header(self, session_id: str, objective: str, model: str) -> None:
        ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self._overwrite(
            f"{'═' * 59}\n"
            f"  🧠  STRATEGY BUILDER — Flux de pensée\n"
            f"{'─' * 59}\n"
            f"  📋  Objectif : {objective}\n"
            f"  🤖  Modèle   : {model}\n"
            f"  🆔  Session  : {session_id}\n"
            f"  🕐  Début    : {ts}\n"
            f"{'═' * 59}\n\n"
        )

    # ------------------------------------------------------------------ #
    # Events — appelés par StrategyBuilder.run()
    # ------------------------------------------------------------------ #

    def iteration_start(self, num: int, total: int) -> None:
        self._append(
            f"\n{'━' * 59}\n"
            f"  ⏳  ITÉRATION {num}/{total}\n"
            f"{'━' * 59}\n\n"
        )

    def proposal_sent(self, has_previous: bool = False) -> None:
        ctx = "avec résultats précédents" if has_previous else "première itération"
        self._append(f"📤  PROPOSITION → LLM…  ({ctx})\n")

    def proposal_received(
        self,
        proposal: Dict[str, Any],
        latency_s: float = 0,
    ) -> None:
        hyp = proposal.get("hypothesis", "—")
        inds = proposal.get("used_indicators", [])
        entry_l = proposal.get("entry_long_logic", "—")
        entry_s = proposal.get("entry_short_logic", "—")
        risk = proposal.get("risk_management", "—")
        ct = proposal.get("change_type", "")
        lat = f"  ({latency_s:.1f}s)" if latency_s else ""
        ct_tag = f"  [{ct.upper()}]" if ct else ""

        self._append(
            f"📥  PROPOSITION REÇUE{lat}{ct_tag}\n"
            f"    💡 Hypothèse  : {hyp}\n"
            f"    📊 Indicateurs: {', '.join(inds) if inds else '—'}\n"
            f"    🟢 LONG       : {_trunc(entry_l)}\n"
            f"    🔴 SHORT      : {_trunc(entry_s)}\n"
            f"    🛡️  Risque     : {_trunc(risk)}\n\n"
        )

    def codegen_sent(self) -> None:
        self._append("🔧  GÉNÉRATION DE CODE → LLM…\n")

    def codegen_received(self, code: str, latency_s: float = 0) -> None:
        n = len(code.strip().splitlines())
        lat = f"  ({latency_s:.1f}s)" if latency_s else ""
        self._append(f"📥  CODE REÇU{lat} — {n} lignes\n\n")

    def validation(self, is_valid: bool, error: str = "") -> None:
        if is_valid:
            self._append("✅  Validation syntaxe + sécurité : OK\n\n")
        else:
            self._append(f"❌  Validation échouée : {error}\n\n")

    def backtest_start(self) -> None:
        self._append("⚙️  Backtest en cours…\n")

    def backtest_result(self, metrics: Dict[str, Any]) -> None:
        ret = metrics.get("total_return_pct", 0) or 0
        sharpe = metrics.get("sharpe_ratio", 0) or 0
        dd = metrics.get("max_drawdown_pct", 0) or 0
        n = int(metrics.get("total_trades", 0) or 0)
        wr = metrics.get("win_rate_pct", 0) or 0
        pf = metrics.get("profit_factor", 0) or 0
        sortino = metrics.get("sortino_ratio", 0) or 0
        exp = metrics.get("expectancy", 0) or 0

        icon = "🟢" if ret > 0 else "🔴"
        self._append(
            f"{icon}  RÉSULTATS BACKTEST\n"
            f"    ┌───────────────────────────────────────────┐\n"
            f"    │ Return: {ret:+8.2f}%  │  Sharpe:  {sharpe:7.3f}  │\n"
            f"    │ MaxDD:  {dd:+8.2f}%  │  Sortino: {sortino:7.3f}  │\n"
            f"    │ Trades: {n:8d}   │  WinRate: {wr:5.1f}%   │\n"
            f"    │ PF:     {pf:8.2f}   │  Expect:  {exp:7.3f}  │\n"
            f"    └───────────────────────────────────────────┘\n\n"
        )

    def diagnostic(self, diag: Dict[str, Any]) -> None:
        cat = diag.get("category", "?")
        sev = diag.get("severity", "?")
        summary = diag.get("summary", "")
        ct = diag.get("change_type", "")
        trend = diag.get("trend", "")
        trend_detail = diag.get("trend_detail", "")
        actions = diag.get("actions", [])
        donts = diag.get("donts", [])
        sc = diag.get("score_card", {})

        sev_icon = {
            "critical": "🔴", "warning": "🟡",
            "info": "🔵", "success": "🟢",
        }.get(sev, "⚪")

        lines = ["🔍  DIAGNOSTIC AUTOMATIQUE"]
        lines.append(f"    {sev_icon}  {cat.upper()} ({sev}) → modifier : {ct}")
        lines.append(f"    {summary}")

        if sc:
            grades = "  |  ".join(
                f"{k.title()}: {v['grade']}" for k, v in sc.items()
            )
            lines.append(f"    📊  {grades}")

        if trend:
            lines.append(f"    📈  Tendance : {trend}  {trend_detail}")

        if actions:
            lines.append("    ▸ Actions :")
            for j, a in enumerate(actions, 1):
                lines.append(f"      {j}. {a}")

        if donts:
            lines.append("    ⚠️  À éviter :")
            for d in donts:
                lines.append(f"      • {d}")

        self._append("\n".join(lines) + "\n\n")

    def analysis_sent(self) -> None:
        self._append("🤔  ANALYSE → LLM…\n")

    def analysis_received(
        self,
        analysis: str,
        decision: str,
        change_type: str = "",
        latency_s: float = 0,
    ) -> None:
        lat = f"  ({latency_s:.1f}s)" if latency_s else ""
        dec_icon = {
            "accept": "🏆", "continue": "🔄", "stop": "🛑",
        }.get(decision, "❓")
        ct_tag = f"  [{change_type.upper()}]" if change_type else ""

        # Afficher l'analyse sur plusieurs lignes indentées
        if isinstance(analysis, list):
            analysis = "\n".join(str(a) for a in analysis)
        analysis_lines = analysis.strip().replace("\n", "\n    ")

        self._append(
            f"📥  ANALYSE LLM{lat}\n"
            f"    {analysis_lines}\n\n"
            f"    {dec_icon}  DÉCISION : {decision}{ct_tag}\n\n"
        )

    def best_update(self, sharpe: float, iteration: int) -> None:
        self._append(
            f"    ⭐  Nouveau meilleur Sharpe : {sharpe:.3f}"
            f"  (itération {iteration})\n\n"
        )

    def warning(self, message: str) -> None:
        self._append(f"⚠️  {message}\n")

    def retry(self, phase: str, attempt: int) -> None:
        self._append(f"🔁  RETRY {phase} (tentative {attempt})…\n")

    def circuit_breaker(self, consecutive: int, max_allowed: int) -> None:
        self._append(
            f"\n🚨  CIRCUIT BREAKER: {consecutive} échecs consécutifs "
            f"(limite: {max_allowed})\n"
            f"    → Arrêt de la session pour éviter une boucle infinie.\n\n"
        )

    def error(self, iteration: int, error_msg: str) -> None:
        short = _trunc(error_msg, 300)
        self._append(f"💥  ERREUR itération {iteration} : {short}\n\n")

    def session_end(
        self,
        status: str,
        best_sharpe: float,
        total_iters: int,
    ) -> None:
        status_icon = {
            "success": "🏆", "failed": "💀", "max_iterations": "⏰",
        }.get(status, "❓")
        ts = datetime.now().strftime("%H:%M:%S")
        self._append(
            f"\n{'═' * 59}\n"
            f"  {status_icon}  SESSION TERMINÉE — {status}\n"
            f"     Meilleur Sharpe : {best_sharpe:.3f}\n"
            f"     Itérations     : {total_iters}\n"
            f"     Fin            : {ts}\n"
            f"{'═' * 59}\n"
        )

    # ------------------------------------------------------------------ #
    # I/O helpers
    # ------------------------------------------------------------------ #

    def _overwrite(self, text: str) -> None:
        """Écrase le fichier de flux avec un nouvel en-tête."""
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()

    def _append(self, text: str) -> None:
        """Ajoute un bloc de texte au flux existant."""
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(text)
            f.flush()


# ------------------------------------------------------------------ #
# Utilitaire
# ------------------------------------------------------------------ #

def _trunc(text: str, max_len: int = 140) -> str:
    """Tronque un texte sur une seule ligne."""
    text = str(text).replace("\n", " ").strip()
    return text[:max_len] + "…" if len(text) > max_len else text
