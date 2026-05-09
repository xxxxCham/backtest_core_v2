"""Module-ID: agents.builder_diagnostics

Purpose: Fonctions de diagnostic déterministe et scoring Builder, extraites
         de strategy_builder.py. Source de vérité unique pour les helpers de
         métriques, le score de télémétrie, les critères d'acceptation et
         compute_diagnostic().

Role in pipeline: diagnostic / scoring

Dependencies: agents.builder_constants

Read-if: Modification du scoring, des critères d'acceptation ou du diagnostic.

Skip-if: Vous ne touchez pas à la boucle itérative du builder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agents.builder_constants import (
    ELITE_MIN_TRADES,
    ELITE_SHARPE_BONUS_RATIO,
    MAX_DRAWDOWN_PCT_FOR_ACCEPT,
    MAX_POSITIVE_FALLBACK_COUNT,
    MIN_PROFIT_FACTOR_FOR_ACCEPT,
    MIN_RETURN_PCT_FOR_ACCEPT,
    MIN_TRADES_FOR_ACCEPT,
    MIN_TRADES_FOR_POSITIVE_PROGRESS,
    POSITIVE_PROGRESS_GATE_CHECKPOINTS,
    SHARPE_TOLERANCE_RATIO,
    TOLERANT_MAX_DRAWDOWN_PCT,
    TOLERANT_MIN_PROFIT_FACTOR,
)

if TYPE_CHECKING:
    from agents.builder_state import BuilderIteration


_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "total_trades": ("trades",),
    "win_rate_pct": ("win_rate",),
}


# ---------------------------------------------------------------------------
# Helpers de métriques
# ---------------------------------------------------------------------------


def _metric_float(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
    """Lecture float robuste d'une métrique sans écraser les zéros valides."""
    value = metrics.get(key, default)
    if value is default:
        for alias in _METRIC_ALIASES.get(key, ()):
            if alias in metrics:
                value = metrics.get(alias, default)
                break
    if value is None:
        return float(default)
    try:
        return float(value)
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
        return float(default)


def _metric_int(metrics: dict[str, Any], key: str, default: int = 0) -> int:
    """Lecture int robuste d'une métrique sans crasher sur des chaînes."""
    value = metrics.get(key, default)
    if value is default:
        for alias in _METRIC_ALIASES.get(key, ()):
            if alias in metrics:
                value = metrics.get(alias, default)
                break
    if value is None:
        return int(default)
    try:
        return int(float(value))
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
        return int(default)


def _is_ruined_metrics(metrics: dict[str, Any]) -> bool:
    """Détecte une configuration ruinée à partir des métriques de backtest."""
    ret = _metric_float(metrics, "total_return_pct", 0.0)
    max_dd = abs(_metric_float(metrics, "max_drawdown_pct", 0.0))
    account_ruined = bool(metrics.get("account_ruined", False))
    return account_ruined or ret <= -90.0 or max_dd >= 90.0


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


# ---------------------------------------------------------------------------
# Score de télémétrie Builder
# ---------------------------------------------------------------------------


def compute_builder_telemetry_score(
    metrics: dict[str, Any],
    *,
    target_sharpe: float = 1.0,
) -> dict[str, Any]:
    """Score composite de télémétrie Builder.

    Ce score reste purement informatif: il n'oriente plus l'acceptation, la
    promotion d'itération ni le routing des modèles. Il sert uniquement à
    l'observabilité et au diagnostic.
    """
    sharpe = _metric_float(metrics, "sharpe_ratio", 0.0)
    ret = _metric_float(metrics, "total_return_pct", 0.0)
    max_dd = abs(_metric_float(metrics, "max_drawdown_pct", 0.0))
    profit_factor = _metric_float(metrics, "profit_factor", 1.0)
    trades = int(metrics.get("total_trades", 0) or 0)
    win_rate = _metric_float(metrics, "win_rate_pct", 35.0)
    ruined = _is_ruined_metrics(metrics)

    target = max(float(target_sharpe or 1.0), 0.5)

    components = {
        "sharpe": _clamp(sharpe / target, -1.5, 2.0) * 28.0,
        "return": _clamp(ret / 20.0, -1.5, 2.0) * 22.0,
        "profit_factor": _clamp((profit_factor - 1.0) / 0.35, -1.5, 2.0) * 16.0,
        "trades_confidence": _clamp(trades / 60.0, 0.0, 1.0) * 10.0,
        "win_rate": _clamp((win_rate - 35.0) / 20.0, -1.0, 1.5) * 6.0,
    }

    drawdown_excess_pct = max(0.0, max_dd - MAX_DRAWDOWN_PCT_FOR_ACCEPT)
    penalties = {
        "drawdown_pressure": _clamp((max_dd - 20.0) / 30.0, 0.0, 2.0) * 20.0,
        "drawdown_excess": _clamp(drawdown_excess_pct / 12.0, 0.0, 2.0) * 10.0,
        "insufficient_trades": 8.0 if trades < MIN_TRADES_FOR_ACCEPT else 0.0,
        "non_positive_return": 12.0 if ret <= 0.0 else 0.0,
        "ruined": 80.0 if ruined else 0.0,
    }

    raw_total = float(sum(components.values()) - sum(penalties.values()))
    score = _clamp(raw_total, -100.0, 100.0)

    return {
        "score": score,
        "components": components,
        "penalties": penalties,
        "drawdown_excess_pct": drawdown_excess_pct,
        "ruined": ruined,
    }


def compute_continuous_builder_score(
    metrics: dict[str, Any],
    *,
    target_sharpe: float = 1.0,
) -> dict[str, Any]:
    """Alias de compatibilité vers ``compute_builder_telemetry_score()``."""
    return compute_builder_telemetry_score(
        metrics,
        target_sharpe=target_sharpe,
    )


def _telemetry_score_from_metrics(
    metrics: dict[str, Any],
    *,
    target_sharpe: float = 1.0,
) -> float:
    """Score composite de télémétrie dérivé des métriques brutes."""
    return float(
        compute_builder_telemetry_score(
            metrics,
            target_sharpe=target_sharpe,
        ).get("score", -100.0),
    )


# ---------------------------------------------------------------------------
# Ranking et sélection d'itérations
# ---------------------------------------------------------------------------
def _builder_iteration_selection_key(
    metrics: dict[str, Any],
    *,
    is_fallback: bool = False,
    target_sharpe: float = 1.0,
) -> tuple[Any, ...]:
    """Clé lexicographique explicite pour comparer deux runs Builder.

    Priorités, de la plus importante à la moins importante :
    1. run non-fallback
    2. métriques non ruinées
    3. rendement positif
    4. profit factor acceptable
    5. nombre minimum de trades atteint
    6. target Sharpe atteinte
    7. Sharpe plus élevé
    8. rendement plus élevé
    9. profit factor plus élevé
    10. drawdown plus faible
    11. plus de trades
    12. meilleur win rate
    """
    sharpe = _metric_float(metrics, "sharpe_ratio", float("-inf"))
    ret = _metric_float(metrics, "total_return_pct", float("-inf"))
    max_dd = abs(_metric_float(metrics, "max_drawdown_pct", float("inf")))
    profit_factor = _metric_float(metrics, "profit_factor", 0.0)
    trades = int(metrics.get("total_trades", 0) or 0)
    win_rate = _metric_float(metrics, "win_rate_pct", 0.0)
    ruined = _is_ruined_metrics(metrics)

    return (
        0 if is_fallback else 1,
        0 if ruined else 1,
        1 if ret > MIN_RETURN_PCT_FOR_ACCEPT else 0,
        1 if profit_factor >= MIN_PROFIT_FACTOR_FOR_ACCEPT else 0,
        1 if trades >= MIN_TRADES_FOR_ACCEPT else 0,
        1 if sharpe >= target_sharpe else 0,
        sharpe,
        ret,
        profit_factor,
        -max_dd,
        trades,
        win_rate,
    )
def _is_accept_candidate(
    metrics: dict[str, Any],
    *,
    target_sharpe: float,
) -> tuple[bool, str]:
    """Vérifie si une itération est suffisamment robuste pour terminer en succès."""
    sharpe = _metric_float(metrics, "sharpe_ratio", 0.0)
    trades = int(metrics.get("total_trades", 0) or 0)
    ret = _metric_float(metrics, "total_return_pct", 0.0)
    max_dd = abs(_metric_float(metrics, "max_drawdown_pct", 0.0))
    # If profit_factor is missing/None, treat as missing (not as the floor),
    # so we don't punish strategies whose backtest didn't compute it.
    pf_raw = metrics.get("profit_factor")
    pf_present = pf_raw is not None and not (
        isinstance(pf_raw, str) and pf_raw.strip().lower() in {"", "n/a", "na", "nan", "none"}
    )
    profit_factor = _metric_float(metrics, "profit_factor", 0.0) if pf_present else None

    if _is_ruined_metrics(metrics):
        return False, "ruined_metrics"
    # Elite path: very strong sharpe with at least ELITE_MIN_TRADES trades is
    # accepted. Otherwise apply the standard floor.
    elite_trades_ok = trades >= ELITE_MIN_TRADES and sharpe >= float(target_sharpe) * float(ELITE_SHARPE_BONUS_RATIO)
    if trades < MIN_TRADES_FOR_ACCEPT and not elite_trades_ok:
        return False, "insufficient_trades"
    if ret <= MIN_RETURN_PCT_FOR_ACCEPT:
        return False, "non_positive_return"
    if profit_factor is not None and profit_factor < MIN_PROFIT_FACTOR_FOR_ACCEPT:
        return False, "profit_factor_too_low"
    if max_dd > (MAX_DRAWDOWN_PCT_FOR_ACCEPT + 25.0):
        return False, "drawdown_extreme"
    # Tolerant Sharpe gate: accept if sharpe >= target * tolerance ratio
    # AND profit factor (when known) and drawdown are stronger than nominal.
    tolerance_floor = float(target_sharpe) * float(SHARPE_TOLERANCE_RATIO)
    if sharpe < tolerance_floor:
        return False, "target_sharpe_not_reached"
    if sharpe < target_sharpe:
        # Tolerant gate when sharpe between [tolerance_floor, target_sharpe[
        if max_dd > TOLERANT_MAX_DRAWDOWN_PCT:
            return False, "target_sharpe_not_reached"
        # Profit factor only enforced when it was actually computed.
        if profit_factor is not None and profit_factor < TOLERANT_MIN_PROFIT_FACTOR:
            return False, "target_sharpe_not_reached"
    return True, "ok"


def resolve_builder_completion_status(
    session: Any,
    *,
    fallback_status: str = "max_iterations",
) -> tuple[str, str]:
    """Résout le statut terminal d'une session depuis son meilleur candidat.

    Le statut brut de boucle indique pourquoi la boucle s'arrête. Cette fonction
    répond à une autre question: est-ce qu'une itération backtestée mérite quand
    même le statut ``success`` selon le même contrat que l'acceptation runtime ?
    """
    target_sharpe = _metric_float(
        {"target_sharpe": getattr(session, "target_sharpe", 1.0)},
        "target_sharpe",
        1.0,
    )
    iterations = list(getattr(session, "iterations", []) or [])
    best_iteration = getattr(session, "best_iteration", None)
    if best_iteration is not None and all(best_iteration is not item for item in iterations):
        iterations.append(best_iteration)

    best_metrics: dict[str, Any] = {}
    best_key: tuple[Any, ...] | None = None
    for iteration in iterations:
        backtest_result = getattr(iteration, "backtest_result", None)
        metrics = getattr(backtest_result, "metrics", None)
        if not isinstance(metrics, dict) or not metrics:
            continue
        candidate_key = _builder_iteration_selection_key(
            metrics,
            is_fallback=bool(getattr(iteration, "is_fallback", False)),
            target_sharpe=target_sharpe,
        )
        if best_key is None or candidate_key > best_key:
            best_key = candidate_key
            best_metrics = metrics

    if not best_metrics:
        return fallback_status, "no_backtest_metrics"

    accepted, reason = _is_accept_candidate(
        best_metrics,
        target_sharpe=target_sharpe,
    )
    if accepted:
        return "success", "best_iteration_accept_candidate"
    return fallback_status, reason


def _is_positive_progress_iteration(metrics: dict[str, Any]) -> bool:
    """Détermine si une itération compte comme "positive" pour la progression."""
    if _is_ruined_metrics(metrics):
        return False
    ret = _metric_float(metrics, "total_return_pct", 0.0)
    trades = int(metrics.get("total_trades", 0) or 0)
    return ret > 0.0 and trades >= MIN_TRADES_FOR_POSITIVE_PROGRESS
def compute_diagnostic(
    metrics: dict[str, Any],
    iteration_history: list[dict[str, Any]],
    target_sharpe: float = 1.0,
) -> dict[str, Any]:
    """Diagnostic déterministe basé sur les métriques de backtest et l'historique.

    Classifie le problème principal, grade chaque dimension (profitabilité,
    risque, efficacité, qualité signaux), recommande le type de modification
    et fournit des actions concrètes.

    Le LLM reçoit ce diagnostic pré-calculé et se concentre sur la SOLUTION
    créative plutôt que sur l'identification du problème.
    """
    # --- Extraction sécurisée ---
    n = _metric_int(metrics, "total_trades", 0)
    sharpe = _metric_float(metrics, "sharpe_ratio", 0.0)
    sortino = _metric_float(metrics, "sortino_ratio", 0.0)
    calmar = _metric_float(metrics, "calmar_ratio", 0.0)
    ret = _metric_float(metrics, "total_return_pct", 0.0)
    dd = abs(_metric_float(metrics, "max_drawdown_pct", 0.0))
    wr = _metric_float(metrics, "win_rate_pct", 0.0)
    pf = _metric_float(metrics, "profit_factor", 0.0)
    exp = _metric_float(metrics, "expectancy", 0.0)
    avg_w = _metric_float(metrics, "avg_win", 0.0)
    avg_l = abs(_metric_float(metrics, "avg_loss", 0.0))
    vol = _metric_float(metrics, "volatility_annual", 0.0)
    _rr = _metric_float(metrics, "risk_reward_ratio", 0.0)
    precheck_skip_reason = str(metrics.get("precheck_skip_reason") or "").strip()
    precheck_signal_density = _metric_float(metrics, "precheck_signal_density", 0.0)
    precheck_transition_density = _metric_float(metrics, "precheck_transition_density", 0.0)
    precheck_repeated_same_ratio = _metric_float(metrics, "precheck_repeated_same_ratio", 0.0)

    # --- Score card A/B/C/D/F ---
    def _g(v, thresholds):
        for grade, thresh in thresholds:
            if v >= thresh:
                return grade
        return "F"

    sc = {
        "profitability": {
            "grade": _g(ret, [("A", 20), ("B", 5), ("C", 0), ("D", -20)]),
            "detail": f"Return {ret:+.1f}%, PF {pf:.2f}, Expectancy {exp:.2f}",
        },
        "risk": {
            "grade": _g(-dd, [("A", -10), ("B", -25), ("C", -40), ("D", -60)]),
            "detail": f"MaxDD {dd:.1f}%, Vol {vol:.1f}%",
        },
        "efficiency": {
            "grade": _g(sharpe, [("A", 1.5), ("B", 1.0), ("C", 0.5), ("D", 0)]),
            "detail": f"Sharpe {sharpe:.3f}, Sortino {sortino:.3f}, Calmar {calmar:.3f}",
        },
        "signal_quality": {
            "grade": _g(wr, [("A", 50), ("B", 40), ("C", 35), ("D", 25)]),
            "detail": f"WR {wr:.1f}%, Trades {n}, AvgW/L {avg_w:.2f}/{avg_l:.2f}",
        },
    }
    telemetry_score = compute_builder_telemetry_score(
        metrics,
        target_sharpe=target_sharpe,
    )

    # --- Catégorie principale (par gravité décroissante) ---
    if precheck_skip_reason == "no_trade_signal_profile":
        cat, sev, ct = "no_trades", "critical", "logic"
        summary = "Précheck bloquant — aucun signal d'entrée détecté avant backtest"
        actions = [
            "Relâcher la condition d'entrée la plus restrictive",
            "Réduire le nombre de conditions AND combinées",
            "Vérifier NaN handling: np.nan_to_num() avant comparaison",
            "Vérifier que generate_signals renvoie bien 1.0/-1.0 et non des booléens",
        ]
        donts = [
            "Ne PAS lancer un sweep de paramètres sur une logique sans signal",
            "Ne PAS ajouter plus de filtres avant d'avoir rétabli des entrées réelles",
        ]
    elif precheck_skip_reason == "pathological_signal_density":
        cat, sev, ct = "signal_always_true", "critical", "logic"
        summary = (
            "Précheck bloquant — densité de signaux pathologique "
            f"(density {precheck_signal_density:.2f}, transitions {precheck_transition_density:.2f}, "
            f"repeat {precheck_repeated_same_ratio:.2f})"
        )
        actions = [
            "URGENT: Vérifier accès indicateurs dict — utiliser indicators['bollinger']['upper'] pas bb.upper ni bollinger.upper",
            "URGENT: Vérifier que les conditions LONG et SHORT ne se déclenchent pas sur une grande majorité des barres",
            "Isoler : tester une seule condition LONG puis une seule condition SHORT sur 100 barres",
            "Ajouter np.nan_to_num() sur TOUS les indicateurs avant comparaison",
            "Réécrire la logique depuis zéro avec conditions explicites et sans alias bb/kelt/stoch",
        ]
        donts = [
            "Ne PAS garder la même logique avec des paramètres ajustés",
            "Ne PAS lancer le backtest complet tant que la densité reste pathologique au précheck",
        ]
    elif n == 0:
        cat, sev, ct = "no_trades", "critical", "logic"
        summary = "Aucun trade — conditions d'entrée trop restrictives"
        actions = [
            "Relâcher les seuils (RSI 70→65, Bollinger 2.0σ→1.5σ)",
            "Réduire le nombre de conditions AND combinées",
            "Vérifier NaN handling: np.nan_to_num() avant comparaison",
            "S'assurer que les signaux retournent 1.0/-1.0 (pas True/False)",
        ]
        donts = [
            "Ne PAS ajuster les paramètres numériques — problème structurel",
            "Ne PAS ajouter plus de conditions",
        ]
    elif n < 5:
        cat, sev, ct = "insufficient_trades", "warning", "logic"
        summary = f"Seulement {n} trade(s) — statistiquement insignifiant"
        actions = [
            "Relâcher la condition d'entrée la plus restrictive",
            "Vérifier que exit_logic ne ferme pas immédiatement",
            "Utiliser des seuils moins extrêmes (RSI 80→70, ADX 30→20)",
            "Simplifier: 1 indicateur puis ajouter filtres progressivement",
        ]
        donts = ["Ne PAS interpréter Sharpe/PF avec < 5 trades"]
    elif n > 800 and (ret < -90 or dd > 90):
        cat, sev, ct = "signal_always_true", "critical", "logic"
        summary = f"Densité signaux anormale ({n} trades, RUINED) — probable accès indicateur dict toujours vrai"
        actions = [
            "URGENT: Vérifier accès indicateurs dict — utiliser indicators['bollinger']['upper'] pas bb.upper ni bollinger.upper",
            "URGENT: Vérifier que les conditions LONG et SHORT ne se déclenchent pas sur >25% des barres chacune",
            "Isoler : tester une seule condition LONG sur 100 barres, vérifier que densité < 20%",
            "Ajouter np.nan_to_num() sur TOUS les indicateurs avant comparaison",
            "Réécrire la logique depuis zéro avec conditions explicites et sans alias bb/kelt/stoch",
        ]
        donts = [
            "Ne PAS garder la même logique avec des paramètres ajustés",
            "Ne PAS combiner LONG+SHORT dans la même expression avant d'avoir validé chacun séparément",
            "Ne PAS utiliser bb.upper, bollinger.upper, kelt.lower — toujours indicators['nom']['subkey']",
        ]
    elif ret < -90 or dd > 90:
        cat, sev, ct = "ruined", "critical", "logic"
        summary = f"Compte ruiné (Return {ret:.0f}%, DD {dd:.0f}%)"
        actions = [
            "URGENT: Réduire leverage à 1-2× max",
            "URGENT: Ajouter stop-loss ATR (1.5-2× ATR)",
            "Vérifier si signaux LONG/SHORT sont inversés",
            "Repartir d'une logique minimale avec SL/TP obligatoires",
        ]
        donts = [
            "Ne PAS garder la même structure+paramètres ajustés",
            "Ne PAS augmenter le leverage",
        ]
    elif n > 300 and wr < 35:
        cat, sev, ct = "overtrading", "warning", "logic"
        summary = f"Suractivité ({n} trades, WR {wr:.0f}%)"
        actions = [
            "Ajouter filtre tendance (ADX > 25 OU direction EMA longue)",
            "Augmenter seuils pour garder les signaux les plus forts",
            "Dédupliquer: pas de signal identique consécutif",
            "Ajouter cooldown minimum entre trades (N barres)",
        ]
        donts = ["Ne PAS juste ajuster numériquement sans filtrer"]
    elif dd > 50:
        cat, sev, ct = "high_drawdown", "warning", "logic"
        summary = f"Drawdown excessif ({dd:.0f}%)"
        actions = [
            "Ajouter/resserrer stop-loss (ATR 1.5× ou % du prix)",
            "Ajouter take-profit (ATR 2-3×)",
            "Réduire leverage si > 2×",
            "Filtre volatilité: ne pas trader si ATR > percentile_80",
        ]
        donts = ["Ne PAS ignorer le drawdown pour maximiser le rendement"]
    elif ret < -20 and n > 20:
        cat, sev, ct = "wrong_direction", "warning", "logic"
        summary = f"Direction probablement inversée (Return {ret:.0f}%, {n} trades)"
        actions = [
            "DIAGNOSTIC: signaux peut-être inversés (1.0=SHORT?)",
            "Tester: inverser tous les signaux (*= -1)",
            "Vérifier conditions LONG = attente de hausse",
            "Revoir exit_logic: positions fermées au mauvais moment?",
        ]
        donts = ["Ne PAS augmenter les params — la direction est le problème"]
    elif pf < 0.8 and n > 20:
        cat, sev, ct = "losing_per_trade", "warning", "both"
        rr_str = f"AvgWin={avg_w:.2f} vs AvgLoss={avg_l:.2f}" if avg_w > 0 else ""
        summary = f"PF faible ({pf:.2f}) — perd par trade. {rr_str}"
        actions = [
            "Améliorer ratio R/R: TP plus loin OU SL plus serré",
            "Ajouter confirmation: 2ème indicateur avant entrée",
            "Filtrer marchés en range (ADX < 20 = ne pas trader)",
            "Optimiser timing: attendre pullback après signal",
        ]
        donts = ["Ne PAS augmenter le volume de trades pour compenser"]
    elif wr < 30 and n > 20 and pf >= 0.8:
        cat, sev, ct = "low_win_rate", "info", "both"
        summary = f"WR bas ({wr:.0f}%) mais PF acceptable ({pf:.2f})"
        actions = [
            "Si PF > 1: stratégie OK malgré WR — affiner paramètres",
            "Sinon: améliorer timing entrée avec confirmation",
            "Filtre tendance pour trader dans la direction dominante",
            "Sorties plus agressives (trailing stop, break-even)",
        ]
        donts = []
    elif 0 < ret < 5 and sharpe < 0.5 and n > 20:
        cat, sev, ct = "marginal", "info", "params"
        summary = f"Rentable mais marginal (Return {ret:.1f}%, Sharpe {sharpe:.3f})"
        actions = [
            "Focus paramètres: ajuster ±20% les périodes indicateurs",
            "Optimiser ratio SL/TP (levier le plus efficace)",
            "La logique produit des résultats positifs — NE PAS la casser",
            "Tester de légers changements de seuils d'entrée",
        ]
        donts = ["Ne PAS restructurer la logique — elle fonctionne"]
    elif sharpe >= target_sharpe:
        cat, sev, ct = "target_reached", "success", "accept"
        robust = n > 20 and dd < 40
        summary = f"Cible atteinte (Sharpe {sharpe:.3f} >= {target_sharpe})"
        if not robust:
            summary += f" — robustifier ({'peu de trades' if n <= 20 else 'DD élevé'})"
        actions = ["Accepter" if robust else "Continuer pour robustifier"]
        donts = []
    elif target_sharpe > 0 and sharpe >= target_sharpe * 0.5:
        cat, sev, ct = "approaching_target", "info", "params"
        pct = sharpe / target_sharpe * 100
        summary = f"En progression ({pct:.0f}% de la cible Sharpe {target_sharpe})"
        actions = [
            "Fine-tuning UNIQUEMENT: ajuster seuils ±10-20%",
            "Optimiser SL ATR mult (tester 1.0 / 1.5 / 2.0 / 2.5)",
            "Optimiser TP ATR mult (tester 2.0 / 3.0 / 4.0)",
            "Ajuster périodes indicateurs (RSI 14→12 ou 14→16)",
        ]
        donts = [
            "Ne PAS changer la logique — elle fonctionne",
            "Ne PAS ajouter d'indicateurs (risque overfitting)",
        ]
    else:
        cat, sev, ct = "needs_work", "info", "both"
        summary = f"Résultats médiocres (Sharpe {sharpe:.3f}, Return {ret:.1f}%)"
        actions = [
            "Essayer une combinaison d'indicateurs différente",
            "Revoir logique d'entrée/sortie",
            "Simplifier: 1-2 indicateurs max avec logique claire",
        ]
        donts = []

    # --- Détection tendance historique ---
    trend, trend_detail = "first", ""

    if iteration_history:
        prev_sharpes = [float(h.get("sharpe", 0) or 0) for h in iteration_history]
        prev_cats = [h.get("diagnostic_category", "") for h in iteration_history]

        if prev_sharpes:
            delta = sharpe - prev_sharpes[-1]
            if delta > 0.05:
                trend, trend_detail = "improving", f"+{delta:.3f} vs précédent"
            elif delta < -0.05:
                trend, trend_detail = "declining", f"{delta:.3f} vs précédent"
            else:
                trend, trend_detail = "stable", f"Δ={delta:+.3f} (stagnant)"

        # Stagnation: même catégorie 3× consécutives
        recent = (prev_cats[-2:] + [cat]) if len(prev_cats) >= 2 else []
        if len(recent) == 3 and len(set(recent)) == 1 and recent[0]:
            trend = "stagnated"
            trend_detail = f"Même problème '{cat}' 3× de suite — changer d'approche"

        # Oscillation: sharpe en zigzag
        if len(prev_sharpes) >= 2:
            ds = [prev_sharpes[j + 1] - prev_sharpes[j] for j in range(len(prev_sharpes) - 1)]
            ds.append(sharpe - prev_sharpes[-1])
            if len(ds) >= 2 and all((ds[k] > 0) != (ds[k + 1] > 0) for k in range(len(ds) - 1)):
                trend = "oscillating"
                trend_detail = "Zigzag — stabiliser les modifications"

    return {
        "category": cat,
        "severity": sev,
        "change_type": ct,
        "summary": summary,
        "actions": actions,
        "donts": donts,
        "trend": trend,
        "trend_detail": trend_detail,
        "score_card": sc,
        "telemetry_score": round(float(telemetry_score.get("score", 0.0)), 2),
        "continuous_score": round(float(telemetry_score.get("score", 0.0)), 2),
        "telemetry_breakdown": {
            "components": telemetry_score.get("components", {}),
            "penalties": telemetry_score.get("penalties", {}),
            "drawdown_excess_pct": telemetry_score.get("drawdown_excess_pct", 0.0),
        },
        "score_breakdown": {
            "components": telemetry_score.get("components", {}),
            "penalties": telemetry_score.get("penalties", {}),
            "drawdown_excess_pct": telemetry_score.get("drawdown_excess_pct", 0.0),
        },
    }
