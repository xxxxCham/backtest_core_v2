"""Objective generation and market recommendation for the Strategy Builder.

Extracted from ``agents.strategy_builder`` to reduce module size while keeping
public wrappers compatible in the original module.
"""

from __future__ import annotations

import random
import re
import uuid
from collections.abc import Callable
from typing import Any

from agents.builder_ast_utils import _extract_json_from_response
from agents.builder_objective_parser import (
    _canonicalize_indicator_name,
    _extract_objective_indicator_names,
    _looks_like_prompt_instruction_leakage,
    sanitize_objective_text,
)
from agents.builder_text_utils import _normalize_llm_text
from agents.indicator_context import (
    build_compact_indicator_catalog,
    build_model_demand_indicator_notes,
    shuffle_indicator_presentation_order,
)
from agents.llm_client import LLMMessage
from agents.strategy_builder import _build_deterministic_fallback_code
from config.market_selection import (
    get_strategy_requirements,
    infer_strategy_type,
    is_strategy_timeframe_compatible,
    rank_tokens_for_strategy,
)
from indicators.registry import list_indicators
from utils.observability import get_obs_logger

logger = get_obs_logger(__name__)

# ---------------------------------------------------------------------------
# Générateurs d'objectifs pour le mode autonome
# ---------------------------------------------------------------------------

# Groupes d'indicateurs par famille de stratégie (combinaisons cohérentes)
_INDICATOR_FAMILIES: dict[str, dict[str, Any]] = {
    "trend-following": {
        "label": "Trend-following",
        "primary": [
            "ema",
            "sma",
            "macd",
            "supertrend",
            "adx",
            "psar",
            "ichimoku",
            "vortex",
            "aroon",
            "directional_bias",
            "markov_switching",
        ],
        "entry_templates": [
            "Entrée long quand {ind1} confirme une tendance haussière et {ind2} valide le momentum.",
            "Entrée sur croisement haussier de {ind1} avec filtre de tendance {ind2}.",
            "Position dans le sens de la tendance détectée par {ind1}, confirmée par {ind2}.",
        ],
        "exit_templates": [
            "Sortie sur retournement de {ind1} ou signal contraire de {ind2}.",
            "Sortie quand la tendance s'essouffle (divergence {ind1}/{ind2}).",
        ],
    },
    "mean-reversion": {
        "label": "Mean-reversion",
        "primary": [
            "bollinger",
            "rsi",
            "stochastic",
            "cci",
            "williams_r",
            "stoch_rsi",
            "keltner",
            "mfi",
            "obv",
            "fvg",
            "swing",
            "pivot_points",
        ],
        "entry_templates": [
            "Entrée quand le prix touche la bande extrême de {ind1} avec {ind2} en zone de survente/surachat.",
            "Achat en survente ({ind1} < seuil) avec confirmation {ind2}, vente en surachat.",
            "Entrée contrariante quand {ind1} atteint un extrême et {ind2} montre un retournement.",
        ],
        "exit_templates": [
            "Sortie quand le prix revient vers la moyenne ({ind1} neutre).",
            "Take-profit au retour à la bande médiane, stop si {ind2} continue dans la tendance.",
        ],
    },
    "momentum": {
        "label": "Momentum",
        "primary": [
            "rsi",
            "macd",
            "momentum",
            "roc",
            "stochastic",
            "mfi",
            "coppock_curve",
            "tsi",
            "trix",
            "force_index",
            "kst",
        ],
        "entry_templates": [
            "Entrée quand {ind1} dépasse son seuil de momentum avec confirmation {ind2}.",
            "Position quand le momentum ({ind1}) accélère et {ind2} est aligné.",
            "Entrée sur divergence haussière/baissière entre {ind1} et {ind2}.",
        ],
        "exit_templates": [
            "Sortie quand le momentum ({ind1}) s'épuise ou diverge du prix.",
            "Take-profit sur perte de momentum, stop basé sur ATR.",
        ],
    },
    "breakout": {
        "label": "Breakout",
        "primary": [
            "bollinger",
            "donchian",
            "keltner",
            "atr",
            "supertrend",
            "adx",
            "choppiness_index",
            "pivot_points",
            "psar",
            "ichimoku",
            "amplitude_hunter",
            "fvg",
            "swing",
            "directional_bias",
            "volume_oscillator",
        ],
        "entry_templates": [
            "Entrée sur cassure de la bande supérieure/inférieure de {ind1} avec volume confirmé.",
            "Position quand le prix sort du range {ind1} avec {ind2} montrant une expansion de volatilité.",
            "Entrée sur breakout validé par {ind1} et force de tendance ({ind2}).",
        ],
        "exit_templates": [
            "Sortie si le prix réintègre le range ou trailing stop basé sur ATR.",
            "Take-profit en multiple d'ATR, stop si faux breakout ({ind1} se contracte).",
        ],
    },
    "scalping": {
        "label": "Scalping",
        "primary": ["ema", "macd", "rsi", "stochastic", "stoch_rsi", "vwap", "bollinger"],
        "entry_templates": [
            "Entrée rapide sur signal {ind1} avec confirmation {ind2} sur timeframe court.",
            "Scalp quand {ind1} croise en zone extrême avec {ind2} aligné.",
            "Entrée quand prix croise {ind1} avec {ind2} en confirmation, objectif serré.",
        ],
        "exit_templates": [
            "Sortie rapide : take-profit serré (1-1.5x ATR), stop-loss serré (0.5-1x ATR).",
            "Sortie sur premier signal de retournement de {ind1}.",
        ],
    },
    "multi-factor": {
        "label": "Multi-factor",
        "primary": [
            "ema",
            "rsi",
            "macd",
            "bollinger",
            "adx",
            "supertrend",
            "stochastic",
            "obv",
            "vwap",
            "cmf",
            "directional_bias",
            "amplitude_hunter",
            "markov_switching",
            "coppock_curve",
            "fvg",
            "trix",
            "vix",
            "choppiness_index",
        ],
        "entry_templates": [
            "Entrée quand au moins 3 facteurs sont alignés : tendance ({ind1}), momentum ({ind2}), volatilité ({ind3}).",
            "Signal composite : {ind1} + {ind2} + {ind3} doivent tous confirmer la direction.",
        ],
        "exit_templates": [
            "Sortie quand plus de la moitié des facteurs se retournent.",
            "Sortie progressive : réduction quand {ind1} diverge, clôture si {ind2} se retourne.",
        ],
    },
    "regime-adaptive": {
        "label": "Regime-adaptatif",
        "primary": [
            "markov_switching",
            "directional_bias",
            "adx",
            "atr",
            "bollinger",
            "keltner",
            "supertrend",
            "rsi",
            "vwap",
            "obv",
            "ema",
            "amplitude_hunter",
            "standard_deviation",
            "vix",
            "choppiness_index",
            "fvg",
            "swing",
            "volume_oscillator",
        ],
        "entry_templates": [
            "Entrée en mode tendance si {ind1} signale un regime fort, sinon bascule en mode reversion avec {ind2}.",
            "Signal adaptatif : si volatilite elevee ({ind1}), suivre la cassure ; sinon trader le retour a la moyenne via {ind2}.",
            "Déclencher uniquement quand {ind1} et {ind2} confirment le meme regime de marche.",
        ],
        "exit_templates": [
            "Sortie lors d'un changement de regime detecte par {ind1}.",
            "Sortie adaptative : TP agressif en tendance, TP prudent en range.",
        ],
    },
}

# Templates de risk management
_RISK_TEMPLATES = [
    "Stop-loss = {sl_mult}x ATR, take-profit = {tp_mult}x ATR.",
    "Stop-loss dynamique basé sur ATR ({sl_mult}x), ratio risk/reward {rr}:1.",
    "Trailing stop à {sl_mult}x ATR, take-profit à {tp_mult}x ATR.",
    "Stop serré {sl_mult}x ATR pour limiter le drawdown, TP à {tp_mult}x ATR.",
]

# Cache global pour éviter de répéter les mêmes indicateurs et familles
_RECENT_INDICATORS: list[str] = []
_MAX_RECENT_INDICATORS = 8  # Évite de réutiliser les 8 derniers indicateurs principaux
_RECENT_FAMILIES: list[str] = []
_MAX_RECENT_FAMILIES = 3  # Évite de réutiliser les 3 dernières familles

# Pool d'axes de différenciation — pioche aléatoire dans `_build_objective_prompt_focus`
# pour casser le biais structurel "trend/breakout" ressenti sur 1d/4h.
_OBJECTIVE_FOCUS_AXES_POOL: list[str] = [
    "continuite de tendance avec stop trailing adaptatif",
    "breakout filtre par expansion ATR ou volume anormal",
    "retour a la moyenne sur extremes statistiques (Bollinger, Keltner)",
    "momentum confirme avec divergence prix/oscillateur",
    "regime adaptatif tendance vs range detecte par volatilite",
    "structure de marche (pivots, swings, niveaux Fibonacci) comme support de decision",
    "pression d'achat/vente lue via OBV, MFI ou volume oscillator",
    "trading de canal (range) entre supports et resistances stables",
    "filtre anti faux signaux simple et lisible",
    "logique multi-facteurs avec vote majoritaire d'indicateurs",
    "exit asymetrique avec take-profit en multiple ATR > stop",
    "biais directionnel issu d'un indicateur de tendance long terme",
    "entree contrariante sur extreme statistique avec confirmation",
]

# Pool de comportements / cadrage — sample aleatoire idem.
_OBJECTIVE_BEHAVIORS_POOL: list[str] = [
    "preferer une seule logique principale avec un seul filtre de confirmation",
    "varier la famille d'indicateurs par rapport aux dernieres sessions",
    "explorer une logique non-classique (range, regime, divergence) si l'univers s'y prete",
    "privilegier robustesse et lisibilite avant originalite",
    "envisager un exit asymetrique (TP > SL en multiple ATR)",
    "eviter les approches multi-timeframe floues",
    "preferer un ensemble compact d'indicateurs (2 a 4 max)",
    "donner la priorite a une hypothese testable et falsifiable",
    "eviter d'empiler des pseudo-filtres exotiques",
]

# Contraintes dures par TF — restent stables, ne sont PAS randomisees.
_OBJECTIVE_TF_CONSTRAINTS_SHORT: tuple[str, ...] = (
    "filtre de liquidite ou de volume simple et explicitement codable",
    "gestion du risque ATR courte et non ambigue",
    "privilegier 2 a 3 indicateurs maximum",
)
_OBJECTIVE_TF_CONSTRAINTS_LONG: tuple[str, ...] = (
    "horizon swing ou tendance multi-bars coherent avec le timeframe",
    "eviter les filtres microstructure ou horaires",
)


def _family_is_compatible_with_timeframe(family_key: str, timeframe: str) -> bool:
    if "{" in str(timeframe or "") or "}" in str(timeframe or ""):
        return True
    strategy_type = "scalping" if family_key == "scalping" else ""
    return is_strategy_timeframe_compatible(strategy_type, timeframe) if strategy_type else True


def _build_objective_prompt_focus(
    timeframes: list[str],
    *,
    recent_families: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Construit (axes, behaviors) en piochant aleatoirement dans des pools.

    Garde une contrainte TF dure (intraday / swing) mais randomise les axes
    pour casser le biais structurel vers trend/breakout.

    `recent_families` (familles d'indicateurs vues recemment) sert a sous-ponderer
    les axes correspondants, sans les exclure totalement.
    """
    normalized_timeframes = {
        str(timeframe or "").strip().lower()
        for timeframe in (timeframes or [])
        if str(timeframe or "").strip()
    }
    short_timeframes = {"1m", "3m", "5m"}
    long_timeframes = {"1d", "1w"}

    if normalized_timeframes and normalized_timeframes.issubset(short_timeframes):
        tf_axes: list[str] = list(_OBJECTIVE_TF_CONSTRAINTS_SHORT)
        tf_behaviors: list[str] = []
        n_axes_extra = 1
        n_behaviors = 2
    elif normalized_timeframes & long_timeframes:
        tf_axes = list(_OBJECTIVE_TF_CONSTRAINTS_LONG)
        tf_behaviors = []
        n_axes_extra = 2
        n_behaviors = 2
    else:
        tf_axes = []
        tf_behaviors = []
        n_axes_extra = 3
        n_behaviors = 2

    # Mapping famille -> mots-cles d'axes a sous-ponderer (best-effort).
    family_axis_keywords: dict[str, tuple[str, ...]] = {
        "trend-following": ("tendance", "trailing"),
        "breakout": ("breakout", "expansion"),
        "mean-reversion": ("retour a la moyenne", "extremes"),
        "momentum": ("momentum",),
        "scalping": ("liquidite",),
        "multi-factor": ("multi-facteurs",),
        "regime-adaptive": ("regime adaptatif",),
    }
    recent_set = {str(fam or "").strip().lower() for fam in (recent_families or []) if str(fam or "").strip()}
    discouraged_keywords: set[str] = set()
    for fam in recent_set:
        for kw in family_axis_keywords.get(fam, ()):  # type: ignore[arg-type]
            discouraged_keywords.add(kw)

    pool = list(_OBJECTIVE_FOCUS_AXES_POOL)
    primary, secondary = [], []
    for axis in pool:
        axis_lower = axis.lower()
        if any(kw in axis_lower for kw in discouraged_keywords):
            secondary.append(axis)
        else:
            primary.append(axis)
    random.shuffle(primary)
    random.shuffle(secondary)
    ordered_pool = primary + secondary

    extra_axes = ordered_pool[: max(0, n_axes_extra)]
    sampled_behaviors = random.sample(
        _OBJECTIVE_BEHAVIORS_POOL,
        k=min(n_behaviors, len(_OBJECTIVE_BEHAVIORS_POOL)),
    )

    selected_axes = tf_axes + extra_axes
    selected_behaviors = tf_behaviors + sampled_behaviors
    return selected_axes, selected_behaviors


def _pick_objective_style_hint(
    timeframes: list[str],
    recent_families: list[str] | None = None,
) -> tuple[str, str]:
    """Choisit un (family_key, label) compatible avec le TF, en evitant les recents.

    Combine `_RECENT_FAMILIES` (cache process) et `recent_families` (historique
    inter-sessions) pour eviter de re-suggerer 3 fois de suite la meme famille.
    """
    tf_text = ""
    if timeframes:
        for candidate in timeframes:
            tf_candidate = str(candidate or "").strip()
            if tf_candidate:
                tf_text = tf_candidate
                break

    compatible = [
        family_key
        for family_key in _INDICATOR_FAMILIES
        if _family_is_compatible_with_timeframe(family_key, tf_text)
    ] or list(_INDICATOR_FAMILIES.keys())

    avoid: set[str] = set(_RECENT_FAMILIES)
    avoid.update(str(fam or "").strip().lower() for fam in (recent_families or []) if str(fam or "").strip())

    fresh = [family_key for family_key in compatible if family_key not in avoid]
    if not fresh:
        fresh = compatible

    chosen = random.choice(fresh)
    label = str(_INDICATOR_FAMILIES[chosen].get("label") or chosen)
    return chosen, label


def generate_random_objective(
    symbol: str | list[str] = "BTCUSDC",
    timeframe: str | list[str] = "1h",
    available_indicators: list[str] | None = None,
) -> str:
    """Génère un objectif de stratégie aléatoire à partir de templates.

    Accepte des listes de symboles/timeframes : un couple est choisi
    aléatoirement pour diversifier les objectifs en mode autonome.

    Combine une famille de stratégie, des indicateurs du registry,
    des conditions d'entrée/sortie et du risk management.

    Returns:
        Objectif structuré en français prêt à être passé au StrategyBuilder.

    """
    # Normaliser listes → valeur unique (choix aléatoire)
    if isinstance(symbol, list):
        symbol = random.choice(symbol) if symbol else "BTCUSDC"
    if isinstance(timeframe, list):
        timeframe = random.choice(timeframe) if timeframe else "1h"

    if available_indicators is None:
        available_indicators = list_indicators()

    avail_lower = {ind.lower() for ind in available_indicators}

    # 🎯 Choisir une famille en évitant les récentes
    all_families = [
        family_key
        for family_key in _INDICATOR_FAMILIES
        if _family_is_compatible_with_timeframe(family_key, str(timeframe or ""))
    ] or list(_INDICATOR_FAMILIES.keys())
    fresh_families = [f for f in all_families if f not in _RECENT_FAMILIES]

    # Si toutes les familles ont été utilisées récemment, réinitialiser
    if not fresh_families:
        fresh_families = all_families
        _RECENT_FAMILIES.clear()

    family_key = random.choice(fresh_families)
    family = _INDICATOR_FAMILIES[family_key]

    # Mettre à jour le cache des familles récentes
    _RECENT_FAMILIES.append(family_key)
    if len(_RECENT_FAMILIES) > _MAX_RECENT_FAMILIES:
        _RECENT_FAMILIES.pop(0)

    # Filtrer les indicateurs disponibles dans cette famille
    valid_primary = [ind for ind in family["primary"] if ind.lower() in avail_lower]
    if len(valid_primary) < 2:
        valid_primary = [ind for ind in available_indicators if ind.lower() != "atr"]

    # 🎯 Anti-répétition : retirer les indicateurs récemment utilisés
    recent_lower = {ind.lower() for ind in _RECENT_INDICATORS}
    fresh_indicators = [ind for ind in valid_primary if ind.lower() not in recent_lower]

    # Si tous les indicateurs ont été utilisés récemment, on réinitialise
    if len(fresh_indicators) < 2:
        fresh_indicators = valid_primary
        _RECENT_INDICATORS.clear()

    # Sélectionner 2-3 indicateurs parmi les frais
    n_indicators = random.randint(2, min(3, len(fresh_indicators)))
    selected = random.sample(fresh_indicators, n_indicators)

    # 🎯 Mettre à jour le cache des indicateurs récents
    for ind in selected:
        if ind.lower() != "atr":  # ATR n'est pas compté car toujours présent
            _RECENT_INDICATORS.append(ind)
            if len(_RECENT_INDICATORS) > _MAX_RECENT_INDICATORS:
                _RECENT_INDICATORS.pop(0)  # FIFO
    if "atr" not in [s.lower() for s in selected] and "atr" in avail_lower:
        selected.append("atr")

    # Générer l'entrée
    ind1 = selected[0].upper()
    ind2 = selected[1].upper() if len(selected) > 1 else selected[0].upper()
    ind3 = selected[2].upper() if len(selected) > 2 else ind1

    entry = random.choice(family["entry_templates"]).format(
        ind1=ind1,
        ind2=ind2,
        ind3=ind3,
    )
    exit_rule = random.choice(family["exit_templates"]).format(
        ind1=ind1,
        ind2=ind2,
        ind3=ind3,
    )

    # Risk management
    sl_mult = round(random.uniform(1.0, 2.5), 1)
    tp_mult = round(sl_mult * random.uniform(1.5, 3.0), 1)
    rr = round(tp_mult / sl_mult, 1)
    risk = random.choice(_RISK_TEMPLATES).format(
        sl_mult=sl_mult,
        tp_mult=tp_mult,
        rr=rr,
    )
    indicators_str = " + ".join(ind.upper() for ind in selected)

    objective = (
        f"Stratégie de {family['label']} sur {symbol} {timeframe}. "
        f"Indicateurs : {indicators_str}. "
        f"{entry} "
        f"{exit_rule} "
        f"{risk}"
    )

    return objective


def _sanitize_objective_indicators_section(
    objective: str,
    available_indicators: list[str],
) -> str:
    """Nettoie le bloc `Indicateurs:` pour ne garder que des noms calculables."""
    text = str(objective or "")
    if not text:
        return text

    allowed = [str(ind or "").strip().lower() for ind in (available_indicators or []) if str(ind or "").strip()]
    if not allowed:
        return text
    allowed_set = set(allowed)

    match = re.search(
        r"(Indicateurs?\s*:\s*)(.+?)(\.\s|\n|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return text

    prefix = str(match.group(1) or "")
    raw_block = str(match.group(2) or "")
    suffix = str(match.group(3) or "")

    selected = _extract_objective_indicator_names(
        raw_block,
        available_indicators=available_indicators,
    )

    if not selected:
        extracted = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw_block)
        for token in extracted:
            normalized = _canonicalize_indicator_name(token, known=allowed_set)
            if normalized and normalized not in selected:
                selected.append(normalized)

    if not selected:
        # Fallback: tirage aleatoire dans les indicateurs disponibles plutot
        # que de retomber sur le noyau canonique (qui amplifiait le biais).
        sample_pool = [name for name in allowed if name != "atr"]
        if sample_pool:
            random.shuffle(sample_pool)
            selected = sample_pool[:2]
        if "atr" in allowed_set and "atr" not in selected:
            selected.append("atr")

    if not selected:
        return text

    rebuilt = f"{prefix}{' + '.join(ind.upper() for ind in selected[:4])}{suffix}"
    start, end = match.span()
    return f"{text[:start]}{rebuilt}{text[end:]}"


def _sanitize_objective_indicator_candidates(
    raw_indicators: Any,
    available_indicators: list[str],
) -> list[str]:
    """Normalise une liste d'indicateurs issus d'un payload structuré."""
    allowed = [str(ind or "").strip().lower() for ind in (available_indicators or []) if str(ind or "").strip()]
    allowed_set = set(allowed)
    if not allowed_set:
        return []

    raw_tokens: list[str] = []
    if isinstance(raw_indicators, str):
        raw_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw_indicators)
    elif isinstance(raw_indicators, (list, tuple, set)):
        raw_tokens = [str(item or "") for item in raw_indicators]

    selected: list[str] = []
    for token in raw_tokens:
        normalized = _canonicalize_indicator_name(token, known=allowed_set)
        if normalized and normalized not in selected:
            selected.append(normalized)

    if not selected:
        # Fallback: echantillonnage aleatoire au lieu du noyau canonique.
        sample_pool = [name for name in allowed if name != "atr"]
        if sample_pool:
            random.shuffle(sample_pool)
            selected = sample_pool[:2]
        if "atr" in allowed_set and "atr" not in selected:
            selected.append("atr")

    return selected[:4]


def _request_structured_objective_payload(
    llm_client: Any,
    *,
    system_prompt: str,
    user_prompt: str,
    stream_callback: Callable[[str, str], None] | None,
    max_tokens: int,
) -> tuple[dict[str, Any], str]:
    """Demande un handoff JSON pour la génération d'objectif."""
    messages = [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_prompt),
    ]
    if stream_callback and hasattr(llm_client, "chat_stream"):
        raw = llm_client.chat_stream(
            messages,
            on_chunk=lambda c: stream_callback("objective_gen", c),
            max_tokens=max_tokens,
            json_mode=True,
        )
    else:
        raw = llm_client.chat(messages, max_tokens=max_tokens, json_mode=True)

    raw_text = str(getattr(raw, "content", raw) or "").strip()
    return _extract_json_from_response(raw_text), raw_text


def _resolve_structured_objective_market(
    payload: dict[str, Any],
    *,
    market_auto_selection: bool,
    symbols_list: list[str],
    timeframes_list: list[str],
) -> tuple[str, str]:
    if market_auto_selection:
        return "{symbol}", "{timeframe}"

    symbol_value = str(payload.get("symbol", "") or "").strip().upper()
    timeframe_value = str(payload.get("timeframe", "") or "").strip()

    if symbols_list:
        allowed_symbols = {str(item or "").strip().upper() for item in symbols_list}
        if symbol_value not in allowed_symbols:
            symbol_value = str(symbols_list[0] or "").strip().upper()
    if timeframes_list:
        allowed_timeframes = {str(item or "").strip() for item in timeframes_list}
        if timeframe_value not in allowed_timeframes:
            timeframe_value = str(timeframes_list[0] or "").strip()

    return symbol_value, timeframe_value


def _structured_objective_to_text(
    payload: dict[str, Any],
    *,
    available_indicators: list[str],
    market_auto_selection: bool,
    symbols_list: list[str],
    timeframes_list: list[str],
) -> str:
    """Reconstruit un objectif lisible depuis un payload JSON."""
    if not isinstance(payload, dict) or not payload:
        return ""

    if not any(
        str(payload.get(key, "") or "").strip()
        for key in ("objective", "style", "entry_logic", "exit_logic", "risk_management", "hypothesis")
    ) and not payload.get("used_indicators"):
        return ""

    objective = sanitize_objective_text(
        _normalize_llm_text(payload.get("objective"), max_len=320),
    )
    if objective and _looks_like_prompt_instruction_leakage(objective):
        objective = ""

    symbol_value, timeframe_value = _resolve_structured_objective_market(
        payload,
        market_auto_selection=market_auto_selection,
        symbols_list=symbols_list,
        timeframes_list=timeframes_list,
    )
    style = _normalize_llm_text(payload.get("style"), max_len=80) or "Stratégie"
    entry_logic = _normalize_llm_text(payload.get("entry_logic"), max_len=260)
    exit_logic = _normalize_llm_text(payload.get("exit_logic"), max_len=260)
    risk_management = _normalize_llm_text(payload.get("risk_management"), max_len=220)
    hypothesis = _normalize_llm_text(payload.get("hypothesis"), max_len=220)
    indicators = _sanitize_objective_indicator_candidates(
        payload.get("used_indicators"),
        available_indicators,
    )

    if not any([style, entry_logic, exit_logic, risk_management, hypothesis, indicators]) and objective:
        return objective

    if not hypothesis and objective:
        lowered_objective = objective.lower()
        looks_like_full_structured_text = any(
            marker in lowered_objective
            for marker in (
                "indicateurs :",
                "entrées :",
                "sorties :",
                "risk management :",
                "hypothèse :",
                "hypothesis:",
            )
        )
        if not looks_like_full_structured_text:
            hypothesis = objective

    parts: list[str] = []
    market_label = f"{symbol_value} {timeframe_value}".strip()
    parts.append(f"[{style}] sur {market_label}.")
    if indicators:
        parts.append(f"Indicateurs : {' + '.join(ind.upper() for ind in indicators)}.")
    if hypothesis:
        parts.append(f"Hypothèse : {hypothesis}.")
    if entry_logic:
        parts.append(f"Entrées : {entry_logic}.")
    if exit_logic:
        parts.append(f"Sorties : {exit_logic}.")
    if risk_management:
        parts.append(f"Risk management : {risk_management}.")

    return " ".join(part.strip() for part in parts if part.strip()).strip()


def align_objective_market_context(objective: str, *, symbol: str, timeframe: str) -> str:
    """Aligne le texte d'objectif sur le marché effectivement retenu."""
    text = sanitize_objective_text(objective)
    target_symbol = str(symbol or "").strip().upper()
    target_timeframe = str(timeframe or "").strip()
    if not text or not target_symbol:
        return text

    text = text.replace("{symbol}", target_symbol).replace("{timeframe}", target_timeframe)

    symbol_pattern = re.compile(r"\b[A-Z0-9]{2,24}(?:USDC|USDT|BUSD|FDUSD)\b")

    def _replace_symbol(match: re.Match[str]) -> str:
        found = str(match.group(0) or "").upper()
        return target_symbol if found != target_symbol else match.group(0)

    text = symbol_pattern.sub(_replace_symbol, text)
    if target_timeframe:
        text = re.sub(
            rf"(\b{re.escape(target_symbol)}\s+)(\d{{1,2}}[mhdwM])\b",
            rf"\g<1>{target_timeframe}",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            rf"(\b{re.escape(target_symbol)}\s+en\s+)(\d{{1,2}}[mhdwM])\b",
            rf"\g<1>{target_timeframe}",
            text,
            flags=re.IGNORECASE,
        )
    return sanitize_objective_text(text)


def generate_llm_objective(
    llm_client: Any,
    symbol: str | list[str] | None = "BTCUSDC",
    timeframe: str | list[str] | None = "1h",
    available_indicators: list[str] | None = None,
    stream_callback: Callable[[str, str], None] | None = None,
    recent_markets: list[tuple[str, str]] | None = None,
) -> str:
    """Génère un objectif de stratégie via un appel LLM.

    Accepte des listes de symboles/timeframes : le LLM est invité à
    choisir le couple le plus pertinent pour sa stratégie.

    Returns:
        Objectif en texte libre généré par le LLM.

    """
    if available_indicators is None:
        available_indicators = list_indicators()

    # Catalogue shuffle (uuid4) + descriptions compactes pour casser le biais
    # alphabetique et exposer les indicateurs moins evidents au LLM.
    catalog_seed = f"objective:{uuid.uuid4().hex}"
    shuffled_indicators = shuffle_indicator_presentation_order(
        available_indicators,
        session_seed=catalog_seed,
    )
    indicator_catalog_lines = build_compact_indicator_catalog(shuffled_indicators)
    indicator_catalog_text = "\n".join(indicator_catalog_lines)
    model_demand_lines = build_model_demand_indicator_notes(shuffled_indicators)
    model_demand_text = "\n".join(model_demand_lines)
    indicator_names_inline = ", ".join(shuffled_indicators)

    # Normaliser en listes pour construire le prompt multi-marché.
    # IMPORTANT : si None est passé, ne pas fallback sur BTCUSDC/1h.
    market_auto_selection = symbol is None or timeframe is None

    if market_auto_selection:
        # Mode auto : le marché sera choisi plus tard via recommend_market_context.
        # L'objectif doit rester neutre et utiliser les placeholders.
        market_instruction = (
            "Le marché (token + timeframe) est sélectionné automatiquement par une étape dédiée.\n"
            "Tu DOIS utiliser exactement les placeholders `{symbol}` et `{timeframe}` dans l'objectif.\n"
            "N'écris AUCUN token réel (BTCUSDC, ETHUSDC...) ni timeframe réel (1h, 15m...).\n\n"
        )
        symbols_list = []
        timeframes_list = []
    else:
        # Mode manuel ou multi-marché : comportement normal
        symbols_list = _unique_non_empty(
            symbol if isinstance(symbol, list) else [symbol],
            upper=True,
        ) or ["BTCUSDC"]
        timeframes_list = _unique_non_empty(
            timeframe if isinstance(timeframe, list) else [timeframe],
        ) or ["1h"]

        # Construire l'instruction marché selon l'univers disponible
        if len(symbols_list) > 1 or len(timeframes_list) > 1:
            market_instruction = (
                f"Symboles disponibles (SEULS autorisés) : {', '.join(symbols_list)}\n"
                f"Timeframes disponibles (SEULS autorisés) : {', '.join(timeframes_list)}\n"
                "CHOISIS le symbole et le timeframe les plus adaptés à ta stratégie. "
                "Tu ne DOIS utiliser QUE des symboles et timeframes de ces listes. "
                "N'invente AUCUN timeframe (pas de 3m, 5m, 2h, etc. s'ils ne sont pas listés). "
                "Ne te limite pas à BTC si un autre actif de cette liste convient clairement mieux.\n\n"
            )
            # Injecter l'historique récent pour forcer la diversité
            if recent_markets:
                recent_str = ", ".join(f"{s} {tf}" for s, tf in recent_markets[-6:])
                market_instruction += (
                    f"IMPORTANT — Les marchés suivants ont DÉJÀ été utilisés récemment : {recent_str}. "
                    "Privilégie un couple différent si cela reste cohérent avec la stratégie.\n\n"
                )
        else:
            market_instruction = f"Marché : {symbols_list[0]} en {timeframes_list[0]}.\n\n"

    # Historique inter-sessions (best-effort) pour contraindre la diversite.
    history_recent_inds: list[str] = []
    history_recent_families: list[str] = []
    history_banned: set[str] = set()
    try:
        from config.indicator_history import (  # noqa: PLC0415,I001
            get_banned_indicators,
            get_recent_families,
            get_recent_indicators,
        )

        history_recent_inds = get_recent_indicators(n_runs=5) or []
        history_recent_families = get_recent_families() or []
        history_banned = get_banned_indicators() or set()
    except Exception:  # pragma: no cover - lecture historique non bloquante
        pass

    selected_axes, selected_behaviors = _build_objective_prompt_focus(
        timeframes_list,
        recent_families=history_recent_families,
    )
    style_hint_key, style_hint_label = _pick_objective_style_hint(
        timeframes_list,
        recent_families=history_recent_families,
    )
    system_prompt = (
        "Tu es un quant designer specialise en strategies de trading crypto. "
        "Tu dois produire un handoff STRUCTURE et exploitable par un Builder. "
        "Reponds UNIQUEMENT avec un objet JSON valide, sans markdown ni commentaire."
    )
    if market_auto_selection:
        market_contract = "- symbol MUST be exactly `{symbol}`.\n- timeframe MUST be exactly `{timeframe}`.\n"
    else:
        allowed_symbols = ", ".join(symbols_list)
        allowed_timeframes = ", ".join(timeframes_list)
        market_contract = (
            f"- symbol MUST be one of: {allowed_symbols}.\n- timeframe MUST be one of: {allowed_timeframes}.\n"
        )

    diversity_lines: list[str] = [
        f"- Style suggere pour CETTE session: {style_hint_label}. "
        "Tu peux devier si l'univers s'y prete clairement mieux, mais ne reproduis pas "
        "passivement un trend/breakout par defaut.",
    ]
    if history_recent_families:
        diversity_lines.append(
            "- Familles deja explorees dans les runs recents (varier si possible): "
            f"{', '.join(history_recent_families[:8])}.",
        )
    if history_recent_inds:
        diversity_lines.append(
            "- Indicateurs sur-representes recemment (a eviter sauf pertinence forte): "
            f"{', '.join(history_recent_inds[:10])}.",
        )
    if history_banned:
        banned_sorted = sorted(history_banned)
        diversity_lines.append(
            "- Indicateurs bannis temporairement (NE PAS utiliser): "
            f"{', '.join(banned_sorted)}.",
        )
    diversity_block = "\n".join(diversity_lines) + "\n"

    user_prompt = (
        "Genere un objectif de strategie de trading sous forme de JSON.\n\n"
        f"{market_instruction}"
        "## CATALOGUE D'INDICATEURS DISPONIBLES\n"
        "(ordre randomise pour CETTE session — explore au-dela des indicateurs habituels)\n"
        f"{indicator_catalog_text}\n\n"
        + (
            "## INDICATEURS SOUVENT DEMANDES SOUS ALIAS PAR LES MODELES\n"
            "Ces lignes ne creent aucun nouveau nom autorise: utilise toujours le nom canonique de la liste.\n"
            f"{model_demand_text}\n\n"
            if model_demand_text
            else ""
        )
        + f"Liste canonique (rappel, meme ordre): {indicator_names_inline}\n\n"
        "Contraintes de diversite:\n"
        f"{diversity_block}"
        "\n"
        "Contraintes de stabilite:\n"
        "- Priorite absolue: produire une strategie claire, implementable et testable avant toute originalite.\n"
        "- Garde une logique principale + au plus un filtre de confirmation + un risk management ATR explicite.\n"
        f"- Si une differenciation est utile, choisis-la parmi: {', '.join(selected_axes)}.\n"
        f"- Garde ce cadrage de conception: {', '.join(selected_behaviors)}.\n"
        "- Evite les formulations generiques de type 'RSI<30/RSI>70' sans filtre additionnel.\n"
        "- Propose une hypothese testable et falsifiable.\n"
        "- Evite d'empiler des filtres exotiques, des pseudo-features ou des approches multi-timeframe floues.\n"
        "- Coherence style/timeframe: n'utilise le style scalping que sur 1m, 3m ou 5m. "
        "Hors scalping, tous les autres styles (trend, breakout, mean-reversion, momentum, "
        "regime-adaptive, multi-factor, range) sont legitimes selon le contexte.\n"
        "- used_indicators doit contenir entre 1 et 5 indicateurs.\n"
        "- objective doit etre un texte court de 2 a 4 phrases maximum.\n"
        f"{market_contract}"
        "- Tous les indicateurs doivent provenir strictement de la liste disponible.\n\n"
        "Retourne EXACTEMENT ce schema JSON:\n"
        "{\n"
        '  "objective": "texte final lisible par un humain",\n'
        '  "style": "nom court de la logique",\n'
        '  "symbol": "marche cible",\n'
        '  "timeframe": "timeframe cible",\n'
        '  "used_indicators": ["indicator_1", "indicator_2"],\n'
        '  "entry_logic": "condition d entree",\n'
        '  "exit_logic": "condition de sortie",\n'
        '  "risk_management": "resume du risk management",\n'
        '  "hypothesis": "pourquoi cette strategie peut fonctionner"\n'
        "}"
    )

    payload, raw_text = _request_structured_objective_payload(
        llm_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        stream_callback=stream_callback,
        max_tokens=420,
    )
    objective = _structured_objective_to_text(
        payload,
        available_indicators=available_indicators,
        market_auto_selection=market_auto_selection,
        symbols_list=symbols_list,
        timeframes_list=timeframes_list,
    )
    if not objective:
        objective = sanitize_objective_text(raw_text)
    if _looks_like_prompt_instruction_leakage(objective):
        logger.warning(
            "generate_llm_objective: contamination de prompt detectee, fallback template",
        )
        objective = ""

    # Fallback si le LLM retourne du vide
    if not objective or len(objective) < 20:
        logger.warning("generate_llm_objective: résultat LLM vide, fallback template")
        if market_auto_selection:
            return generate_random_objective(
                symbol="{symbol}",
                timeframe="{timeframe}",
                available_indicators=available_indicators,
            )
        return generate_random_objective(symbol, timeframe, available_indicators)

    if market_auto_selection:
        # Nettoyage défensif : retire toute fuite de token/TF hardcodé.
        objective = _remove_hardcoded_tokens(objective)
        objective = _remove_hardcoded_timeframes(objective)

        # Garantit la présence des placeholders attendus.
        if "{symbol}" not in objective or "{timeframe}" not in objective:
            objective = re.sub(
                r"\bsur\s+crypto\b",
                "sur {symbol} {timeframe}",
                objective,
                flags=re.IGNORECASE,
            )
        if "{symbol}" not in objective or "{timeframe}" not in objective:
            objective = f"Stratégie sur {{symbol}} {{timeframe}}. {objective}"

        objective = _sanitize_objective_indicators_section(
            objective,
            available_indicators,
        )
        _record_recent_family(style_hint_key)
        return sanitize_objective_text(objective)

    # ── Post-validation : remplacer les TF/tokens hallucinés ──
    tf_pattern = re.compile(r"\b(\d{1,2}[mhdwM])\b")
    found_tfs = tf_pattern.findall(objective)
    if timeframes_list:
        for found_tf in found_tfs:
            if found_tf not in timeframes_list:
                replacement = random.choice(timeframes_list)
                objective = objective.replace(found_tf, replacement, 1)
                logger.info(
                    "generate_llm_objective: TF halluciné '%s' → '%s'",
                    found_tf,
                    replacement,
                )

    sym_upper_set = {s.upper() for s in symbols_list}
    # Vérifier que le symbole mentionné est valide
    sym_pattern = re.compile(r"\b([A-Z]{2,10}USDC)\b")
    found_syms = sym_pattern.findall(objective.upper())
    if symbols_list:
        for found_sym in found_syms:
            if found_sym not in sym_upper_set:
                replacement = random.choice(symbols_list)
                objective = re.sub(
                    re.escape(found_sym),
                    replacement,
                    objective,
                    count=1,
                    flags=re.IGNORECASE,
                )
                logger.info(
                    "generate_llm_objective: token halluciné '%s' → '%s'",
                    found_sym,
                    replacement,
                )

    objective = _sanitize_objective_indicators_section(
        objective,
        available_indicators,
    )
    _record_recent_family(style_hint_key)
    return objective


def _record_recent_family(family_key: str) -> None:
    """Memorise la famille suggeree pour la rotation inter-runs (cache process)."""
    key = str(family_key or "").strip().lower()
    if not key:
        return
    if key in _RECENT_FAMILIES:
        _RECENT_FAMILIES.remove(key)
    _RECENT_FAMILIES.append(key)
    while len(_RECENT_FAMILIES) > _MAX_RECENT_FAMILIES:
        _RECENT_FAMILIES.pop(0)


def generate_llm_objective_from_seed(
    llm_client: Any,
    *,
    seed_objective: str,
    symbol: str | list[str] = "BTCUSDC",
    timeframe: str | list[str] = "1h",
    available_indicators: list[str] | None = None,
    family: str = "",
    direction: str = "",
    risk_profile: str = "",
    novelty_angle: str = "",
    tags: list[str] | None = None,
    stream_callback: Callable[[str, str], None] | None = None,
    recent_markets: list[tuple[str, str]] | None = None,
) -> str:
    """Raffine une piste catalogue en objectif LLM plus adapté au setup étudié."""
    if available_indicators is None:
        available_indicators = list_indicators()

    seed_text = sanitize_objective_text(seed_objective)
    if not seed_text:
        return generate_llm_objective(
            llm_client,
            symbol=symbol,
            timeframe=timeframe,
            available_indicators=available_indicators,
            stream_callback=stream_callback,
            recent_markets=recent_markets,
        )

    indicators_list = ", ".join(sorted(available_indicators))
    market_auto_selection = symbol is None or timeframe is None

    if market_auto_selection:
        market_instruction = (
            "Le marché (token + timeframe) est sélectionné automatiquement par une étape dédiée.\n"
            "Tu DOIS utiliser exactement les placeholders `{symbol}` et `{timeframe}` dans l'objectif final.\n"
            "N'écris AUCUN token réel ni timeframe réel.\n\n"
        )
        symbols_list: list[str] = []
        timeframes_list: list[str] = []
    else:
        symbols_list = symbol if isinstance(symbol, list) else [symbol]
        timeframes_list = timeframe if isinstance(timeframe, list) else [timeframe]
        symbols_list = _unique_non_empty(symbols_list, upper=True) or ["BTCUSDC"]
        timeframes_list = _unique_non_empty(timeframes_list) or ["1h"]
        if len(symbols_list) > 1 or len(timeframes_list) > 1:
            market_instruction = (
                f"Symboles disponibles (SEULS autorisés) : {', '.join(symbols_list)}\n"
                f"Timeframes disponibles (SEULS autorisés) : {', '.join(timeframes_list)}\n"
                "Choisis le couple le plus pertinent pour étudier cette stratégie. "
                "N'utilise QUE ces symboles/timeframes.\n\n"
            )
            if recent_markets:
                recent_str = ", ".join(f"{s} {tf}" for s, tf in recent_markets[-6:])
                market_instruction += (
                    f"Les marchés suivants ont déjà été testés récemment : {recent_str}. "
                    "Privilégie un couple différent si cela reste cohérent.\n\n"
                )
        else:
            market_instruction = f"Marché à étudier : {symbols_list[0]} {timeframes_list[0]}.\n\n"

    seed_context = [
        f"Piste catalogue de départ : {seed_text}",
        f"Famille cible : {family or 'n/a'}",
        f"Direction visée : {direction or 'n/a'}",
        f"Profil de risque : {risk_profile or 'n/a'}",
        f"Angle de nouveauté : {novelty_angle or 'n/a'}",
    ]
    clean_tags = [str(tag or "").strip() for tag in (tags or []) if str(tag or "").strip()]
    if clean_tags:
        seed_context.append(f"Tags utiles : {', '.join(clean_tags)}")

    if market_auto_selection:
        market_contract = "- symbol MUST be exactly `{symbol}`.\n- timeframe MUST be exactly `{timeframe}`.\n"
    else:
        market_contract = (
            f"- symbol MUST be one of: {', '.join(symbols_list)}.\n"
            f"- timeframe MUST be one of: {', '.join(timeframes_list)}.\n"
        )

    system_prompt = (
        "Tu es un quant designer. On te donne une piste catalogue brute. "
        "Ta tache est de la transformer en un objectif de recherche plus precis, plus robuste "
        "et mieux adapte au setup etudie, tout en conservant l intention strategique generale. "
        "Reponds UNIQUEMENT avec un objet JSON valide."
    )
    user_prompt = (
        f"{market_instruction}"
        f"{chr(10).join(seed_context)}\n\n"
        f"Indicateurs disponibles : {indicators_list}\n\n"
        "Contraintes :\n"
        "- Priorite a une strategie claire, stable et directement codable plutot qu'a une surenchere de filtres.\n"
        "- Garde une logique principale + au plus un filtre de confirmation + un risk management explicite.\n"
        "- Pars de la piste catalogue, mais reformule-la pour en faire une hypothese testable et falsifiable.\n"
        "- Choisis les indicateurs les plus coherents avec cette strategie.\n"
        "- N'utilise QUE des indicateurs disponibles.\n"
        "- used_indicators doit contenir entre 1 et 5 indicateurs.\n"
        "- objective doit rester en 2 a 4 phrases.\n"
        "- Evite les formulations generiques et les signaux trop triviaux.\n"
        f"{market_contract}"
        "Retourne EXACTEMENT ce schema JSON:\n"
        "{\n"
        '  "objective": "texte final lisible par un humain",\n'
        '  "style": "nom court de la logique",\n'
        '  "symbol": "marche cible",\n'
        '  "timeframe": "timeframe cible",\n'
        '  "used_indicators": ["indicator_1", "indicator_2"],\n'
        '  "entry_logic": "condition d entree",\n'
        '  "exit_logic": "condition de sortie",\n'
        '  "risk_management": "resume du risk management",\n'
        '  "hypothesis": "pourquoi cette strategie peut fonctionner"\n'
        "}"
    )

    payload, raw_text = _request_structured_objective_payload(
        llm_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        stream_callback=stream_callback,
        max_tokens=440,
    )
    objective = _structured_objective_to_text(
        payload,
        available_indicators=available_indicators,
        market_auto_selection=market_auto_selection,
        symbols_list=symbols_list,
        timeframes_list=timeframes_list,
    )
    if not objective:
        objective = sanitize_objective_text(raw_text)
    if _looks_like_prompt_instruction_leakage(objective):
        logger.warning(
            "generate_llm_objective_from_seed: contamination de prompt detectee, fallback seed",
        )
        objective = ""
    if not objective or len(objective) < 20:
        logger.warning("generate_llm_objective_from_seed: résultat LLM vide, fallback seed")
        objective = seed_text

    if market_auto_selection:
        objective = _remove_hardcoded_tokens(objective)
        objective = _remove_hardcoded_timeframes(objective)
        if "{symbol}" not in objective or "{timeframe}" not in objective:
            objective = f"Stratégie sur {{symbol}} {{timeframe}}. {objective}"
        objective = _sanitize_objective_indicators_section(
            objective,
            available_indicators,
        )
        return sanitize_objective_text(objective)

    tf_pattern = re.compile(r"\b(\d{1,2}[mhdwM])\b")
    found_tfs = tf_pattern.findall(objective)
    for found_tf in found_tfs:
        if found_tf not in timeframes_list:
            replacement = random.choice(timeframes_list)
            objective = objective.replace(found_tf, replacement, 1)

    sym_upper_set = {s.upper() for s in symbols_list}
    sym_pattern = re.compile(r"\b([A-Z]{2,10}USDC)\b")
    found_syms = sym_pattern.findall(objective.upper())
    for found_sym in found_syms:
        if found_sym not in sym_upper_set:
            replacement = random.choice(symbols_list)
            objective = re.sub(
                re.escape(found_sym),
                replacement,
                objective,
                count=1,
                flags=re.IGNORECASE,
            )

    objective = _sanitize_objective_indicators_section(
        objective,
        available_indicators,
    )
    return objective


def _unique_non_empty(values: list[str], *, upper: bool = False) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        val = str(raw or "").strip()
        if not val:
            continue
        if upper:
            val = val.upper()
        if val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


def _find_objective_market_hints(
    objective_text: str,
    *,
    allowed_symbols: list[str],
    allowed_timeframes: list[str],
) -> tuple[str | None, str | None]:
    """Extrait les indices explicites symbol/timeframe présents dans l'objectif."""
    text = sanitize_objective_text(objective_text)
    if not text:
        return None, None

    text_upper = text.upper()

    symbol_hits: list[tuple[int, str]] = []
    for symbol in allowed_symbols:
        match = re.search(
            rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])",
            text_upper,
        )
        if match:
            symbol_hits.append((match.start(), symbol))

    timeframe_hits: list[tuple[int, str]] = []
    for timeframe in allowed_timeframes:
        tf = str(timeframe or "").strip()
        if not tf:
            continue
        if re.fullmatch(r"\d+[mhdwM]", tf):
            match = re.search(
                rf"(?<![A-Za-z0-9]){re.escape(tf[:-1])}\s*{re.escape(tf[-1])}(?![A-Za-z0-9])",
                text,
                flags=re.IGNORECASE,
            )
        else:
            match = re.search(
                rf"(?<![A-Za-z0-9]){re.escape(tf)}(?![A-Za-z0-9])",
                text,
                flags=re.IGNORECASE,
            )
        if match:
            timeframe_hits.append((match.start(), tf))

    hinted_symbol = min(symbol_hits, key=lambda x: x[0])[1] if symbol_hits else None
    hinted_timeframe = min(timeframe_hits, key=lambda x: x[0])[1] if timeframe_hits else None
    return hinted_symbol, hinted_timeframe


def _rank_and_select_market_candidates(
    *,
    clean_objective: str,
    symbols: list[str],
    timeframes: list[str],
    recent_markets: list[tuple[str, str]] | None,
    _initial_fallback_symbol: str,
    _initial_fallback_timeframe: str,
) -> dict[str, Any]:
    """Phases 4-10 : détection type stratégie, ranking, hints, fallbacks, diversité."""
    hinted_symbol, hinted_timeframe = _find_objective_market_hints(
        clean_objective,
        allowed_symbols=symbols,
        allowed_timeframes=timeframes,
    )
    detected_strategy_type = infer_strategy_type(objective=clean_objective)
    if detected_strategy_type == "unknown":
        detected_strategy_type = None

    ranked_symbols: list[str] = []
    if detected_strategy_type:
        symbols_for_ranking = symbols.copy()
        ranked_symbols = rank_tokens_for_strategy(symbols_for_ranking, detected_strategy_type)
        shuffled_symbols = ranked_symbols.copy()
        logger.info(
            "Market selection: strategy_type=%s, ranked_tokens=%s, prompt_tokens_shuffled=NO",
            detected_strategy_type,
            ", ".join(ranked_symbols[:5]),
        )
    else:
        shuffled_symbols = symbols.copy()
        logger.info("Market selection: strategy_type=UNKNOWN, tokens=ordered")

    shuffled_timeframes = timeframes.copy()

    if not detected_strategy_type:
        logger.info(
            "Market selection: strategy_type=NONE → using hints, symbol=%s, timeframe=%s",
            hinted_symbol or "NONE",
            hinted_timeframe or "NONE",
        )
    else:
        hint_status = "compatible" if hinted_timeframe and is_strategy_timeframe_compatible(detected_strategy_type, hinted_timeframe) else "absent_or_incompatible"
        logger.info(
            "Market selection: strategy_type=%s → objective hints=%s, symbol=%s, timeframe=%s",
            detected_strategy_type,
            hint_status,
            hinted_symbol or "NONE",
            hinted_timeframe or "NONE",
        )

    recent_symbol_set = {str(s or "").strip().upper() for s, _ in (recent_markets or []) if str(s or "").strip()}

    hinted_market_is_strategy_compatible = (
        not detected_strategy_type
        or not hinted_timeframe
        or is_strategy_timeframe_compatible(detected_strategy_type, hinted_timeframe)
    )

    if hinted_symbol and hinted_symbol in symbols and hinted_market_is_strategy_compatible:
        fallback_symbol = hinted_symbol
    elif detected_strategy_type and ranked_symbols:
        fallback_pool = ranked_symbols[: min(5, len(ranked_symbols))]
        non_recent_pool = [s for s in fallback_pool if s not in recent_symbol_set]
        if non_recent_pool:
            fallback_pool = non_recent_pool
        fallback_symbol = fallback_pool[0] if fallback_pool else ranked_symbols[0]
    else:
        fallback_symbol = shuffled_symbols[0] if shuffled_symbols else _initial_fallback_symbol

    if hinted_timeframe and hinted_timeframe in timeframes and hinted_market_is_strategy_compatible:
        fallback_timeframe = hinted_timeframe
    elif detected_strategy_type:
        try:
            reqs = get_strategy_requirements(detected_strategy_type)
            recommended_tfs = reqs.get("timeframes", ["1h"])
            recommended_available = [tf for tf in recommended_tfs if tf in timeframes]
            if recommended_available:
                fallback_timeframe = recommended_available[0]
            else:
                fallback_timeframe = shuffled_timeframes[0] if shuffled_timeframes else _initial_fallback_timeframe
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
            fallback_timeframe = shuffled_timeframes[0] if shuffled_timeframes else _initial_fallback_timeframe
    else:
        fallback_timeframe = shuffled_timeframes[0] if shuffled_timeframes else _initial_fallback_timeframe

    logger.info(
        "Market selection: fallback=%s %s (source=%s)",
        fallback_symbol,
        fallback_timeframe,
        "strategy_optimized" if detected_strategy_type else "default",
    )

    diversity_instruction = ""
    if recent_markets:
        from config.market_selection import get_diversity_min_alternatives

        available_combos = [(s, tf) for s in symbols for tf in timeframes]
        recent_window = recent_markets[-6:]
        unused_combos = [c for c in available_combos if c not in recent_window]
        min_alts = get_diversity_min_alternatives()

        if len(unused_combos) >= min_alts:
            recent_str = ", ".join(f"{s} {tf}" for s, tf in recent_window)
            diversity_instruction = (
                f"\n- DÉJÀ UTILISÉS récemment : {recent_str}. "
                "Tu DOIS choisir un couple DIFFÉRENT. Varie tokens ET timeframes."
            )
            logger.info(
                "Market selection: diversity=ACTIVE, excluded_count=%d, alternatives=%d, recent=%s",
                len(recent_window),
                len(unused_combos),
                recent_str,
            )
        else:
            logger.warning(
                "Market selection: diversity=DISABLED, reason=Univers restreint (%d alternatives < %d min), "
                "recent_count=%d",
                len(unused_combos),
                min_alts,
                len(recent_window),
            )

    objective_hint_instruction = ""
    hint_lines: list[str] = []

    if hinted_symbol and hinted_timeframe and recent_markets:
        hinted_combo = (hinted_symbol, hinted_timeframe)
        recent_window = recent_markets[-6:]
        if hinted_combo in recent_window:
            logger.warning(
                "Market selection: CONFLICT hints vs diversity, hinted=%s %s (already in recent_markets), "
                "priority=diversity → hints IGNORED",
                hinted_symbol,
                hinted_timeframe,
            )
            hinted_symbol = None
            hinted_timeframe = None

    if hinted_symbol:
        hint_lines.append(
            f"- L'objectif mentionne le symbole `{hinted_symbol}` : "
            "considère-le comme une préférence, pas comme une contrainte absolue.",
        )
    if hinted_timeframe:
        hint_lines.append(
            f"- L'objectif mentionne le timeframe `{hinted_timeframe}` : "
            "considère-le comme une préférence, pas comme une contrainte absolue.",
        )

    if hint_lines:
        objective_hint_instruction = "\n" + "\n".join(hint_lines)
        from config.market_selection import get_hints_confidence_boost

        boost = get_hints_confidence_boost()
        logger.info(
            "Market selection: hints_detected=YES, symbol=%s, timeframe=%s, boost=+%.2f confidence",
            hinted_symbol or "NONE",
            hinted_timeframe or "NONE",
            boost if (hinted_symbol or hinted_timeframe) else 0.0,
        )

    return {
        "detected_strategy_type": detected_strategy_type,
        "ranked_symbols": ranked_symbols,
        "shuffled_symbols": shuffled_symbols,
        "shuffled_timeframes": shuffled_timeframes,
        "hinted_symbol": hinted_symbol,
        "hinted_timeframe": hinted_timeframe,
        "fallback_symbol": fallback_symbol,
        "fallback_timeframe": fallback_timeframe,
        "diversity_instruction": diversity_instruction,
        "objective_hint_instruction": objective_hint_instruction,
    }


def _finalize_market_result(
    *,
    symbol: str,
    timeframe: str,
    confidence: float,
    reason: str,
    source: str,
    payload: dict[str, Any],
    symbols: list[str],
    timeframes: list[str],
    strict_fallback_symbol: str,
    strict_fallback_timeframe: str,
    recent_markets: list[tuple[str, str]] | None,
    hinted_symbol: str | None,
    hinted_timeframe: str | None,
) -> dict[str, Any]:
    """Phases 13-16 : validation univers, override diversité, bonus hints, finalisation."""
    if symbol not in symbols:
        source = "fallback_out_of_universe"
        symbol = strict_fallback_symbol
    if timeframe not in timeframes:
        source = "fallback_out_of_universe"
        timeframe = strict_fallback_timeframe

    if not payload:
        source = "fallback_invalid_json"
        symbol = strict_fallback_symbol
        timeframe = strict_fallback_timeframe
        confidence = 0.0
        if not reason:
            reason = "Réponse LLM non parseable en JSON. Fallback appliqué."

    if recent_markets:
        recent_order = [
            (str(s or "").upper(), str(tf or "").strip())
            for s, tf in recent_markets
            if str(s or "").strip() and str(tf or "").strip()
        ]
        recent_pairs = set(recent_order)
        all_pairs = [(s, tf) for s in symbols for tf in timeframes]
        selected_pair = (symbol, timeframe)

        if selected_pair in recent_pairs and len(all_pairs) > 1:
            alternatives = [p for p in all_pairs if p not in recent_pairs]
            candidate_pool = alternatives

            if not candidate_pool:
                last_seen: dict[tuple[str, str], int] = dict.fromkeys(all_pairs, -1)
                for idx, pair in enumerate(recent_order):
                    if pair in last_seen:
                        last_seen[pair] = idx
                candidate_pool = sorted(
                    [p for p in all_pairs if p != selected_pair],
                    key=lambda p: (last_seen.get(p, -1), p[0], p[1]),
                )

            preferred = candidate_pool
            if hinted_symbol and hinted_timeframe:
                same_symbol = [p for p in candidate_pool if p[0] == hinted_symbol]
                same_timeframe = [p for p in candidate_pool if p[1] == hinted_timeframe]
                preferred = same_symbol or same_timeframe or candidate_pool
            elif hinted_symbol:
                by_symbol = [p for p in candidate_pool if p[0] == hinted_symbol]
                preferred = by_symbol or candidate_pool
            elif hinted_timeframe:
                by_timeframe = [p for p in candidate_pool if p[1] == hinted_timeframe]
                preferred = by_timeframe or candidate_pool

            if preferred:
                symbol, timeframe = random.choice(preferred)
                source = f"{source}_diversity_override" if source != "llm" else "llm_diversity_override"
                confidence = min(confidence, 0.75)
                if reason:
                    reason = f"{reason} Couple récent évité automatiquement ({selected_pair[0]} {selected_pair[1]})."
                else:
                    reason = f"Couple récent évité automatiquement ({selected_pair[0]} {selected_pair[1]})."

    hint_matches: list[str] = []
    if hinted_symbol and symbol == hinted_symbol:
        hint_matches.append(f"symbol={hinted_symbol}")
    if hinted_timeframe and timeframe == hinted_timeframe:
        hint_matches.append(f"timeframe={hinted_timeframe}")
    if hint_matches:
        source = "llm_with_objective_hint" if source == "llm" else source
        confidence = max(confidence, 0.8)
        matched = ", ".join(hint_matches)
        if reason:
            reason = f"{reason} Hints objectif alignés ({matched})."
        else:
            reason = f"Hints objectif alignés ({matched})."

    if not reason:
        if source == "llm":
            reason = "Choix basé sur style de stratégie, volatilité attendue et fréquence des signaux."
        else:
            reason = "Choix par défaut suite à une réponse LLM non exploitable."
    if len(reason) > 280:
        reason = reason[:280].rstrip()

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "confidence": confidence,
        "reason": reason,
        "source": source,
    }


def recommend_market_context(
    llm_client: Any,
    *,
    objective: str,
    candidate_symbols: list[str],
    candidate_timeframes: list[str],
    default_symbol: str = "BTCUSDC",
    default_timeframe: str = "1h",
    stream_callback: Callable[[str, str], None] | None = None,
    recent_markets: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Recommande un couple (symbol, timeframe) adapté à un objectif Builder.

    Le choix est strictement borné à l'univers fourni (`candidate_symbols`,
    `candidate_timeframes`). En cas de réponse invalide du LLM, un fallback
    robuste est appliqué.
    """
    # --- Phase 1-3 : normaliser univers + fallbacks --- #
    symbol_re = re.compile(r"^[A-Za-z0-9_.-]{2,24}$")
    timeframe_re = re.compile(r"^\d+[mhdwM]$")

    symbols = _unique_non_empty(candidate_symbols, upper=True)
    if not symbols:
        symbols = _unique_non_empty([default_symbol or "BTCUSDC"], upper=True)
    symbols = [s for s in symbols if symbol_re.match(s)]

    timeframes = _unique_non_empty(candidate_timeframes, upper=False)
    if not timeframes:
        timeframes = _unique_non_empty([default_timeframe or "1h"], upper=False)
    timeframes = [tf for tf in timeframes if timeframe_re.match(tf)]

    strict_fallback_symbol = (
        str(default_symbol).strip().upper()
        if str(default_symbol).strip().upper() in symbols
        else (symbols[0] if symbols else "BTCUSDC")
    )
    strict_fallback_timeframe = (
        str(default_timeframe).strip()
        if str(default_timeframe).strip() in timeframes
        else (timeframes[0] if timeframes else "1h")
    )

    _initial_fallback_symbol = (
        str(default_symbol).strip().upper()
        if str(default_symbol).strip().upper() in symbols
        else (random.choice(symbols) if symbols else "BTCUSDC")
    )
    _initial_fallback_timeframe = (
        str(default_timeframe).strip()
        if str(default_timeframe).strip() in timeframes
        else (random.choice(timeframes) if timeframes else "1h")
    )

    if not symbols or not timeframes:
        return {
            "symbol": strict_fallback_symbol,
            "timeframe": strict_fallback_timeframe,
            "confidence": 0.0,
            "reason": "Univers marché incomplet, fallback par défaut.",
            "source": "fallback_no_candidates",
        }

    clean_objective = sanitize_objective_text(objective)
    if not clean_objective:
        clean_objective = str(objective or "").strip()

    # --- Phases 4-10 : candidats, ranking, hints, diversité --- #
    ctx = _rank_and_select_market_candidates(
        clean_objective=clean_objective,
        symbols=symbols,
        timeframes=timeframes,
        recent_markets=recent_markets,
        _initial_fallback_symbol=_initial_fallback_symbol,
        _initial_fallback_timeframe=_initial_fallback_timeframe,
    )
    detected_strategy_type = ctx["detected_strategy_type"]
    shuffled_symbols: list[str] = ctx["shuffled_symbols"]
    shuffled_timeframes: list[str] = ctx["shuffled_timeframes"]
    hinted_symbol: str | None = ctx["hinted_symbol"]
    hinted_timeframe: str | None = ctx["hinted_timeframe"]
    fallback_symbol: str = ctx["fallback_symbol"]
    fallback_timeframe: str = ctx["fallback_timeframe"]
    diversity_instruction: str = ctx["diversity_instruction"]
    objective_hint_instruction: str = ctx["objective_hint_instruction"]

    # --- Phase 11 : prompt LLM --- #
    system_msg = LLMMessage(
        role="system",
        content=(
            "Tu es un analyste quant. Choisis UN seul couple symbole/timeframe "
            "le plus pertinent pour l'objectif. Réponds en JSON strict uniquement."
        ),
    )
    strategy_hints = ""
    try:
        if detected_strategy_type:
            reqs = get_strategy_requirements(detected_strategy_type)
            recommended_tfs = reqs.get("timeframes", ["1h"])
            top_tokens = shuffled_symbols[:5]
            strategy_hints = (
                f"\n📊 RECOMMANDATION STRATÉGIE: **{detected_strategy_type.replace('_', ' ').title()}** détecté\n"
                f"  → TFs optimaux: {', '.join(recommended_tfs[:3])}\n"
                f"  → Tokens candidats pertinents (ordre mélangé): {', '.join(top_tokens)}\n"
                "  → IMPORTANT: Ne choisis PAS automatiquement le premier token de la liste.\n"
                "    Évalue l'adéquation avec l'objectif + la diversité récente.\n"
            )
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
        pass  # Si détection échoue, continuer sans hints

    user_msg = LLMMessage(
        role="user",
        content=(
            "Objectif:\n"
            f"{clean_objective}\n\n"
            "Contraintes:\n"
            f"- symbol MUST be one of: {', '.join(shuffled_symbols)}\n"
            f"- timeframe MUST be one of: {', '.join(shuffled_timeframes)}\n"
            "- Anti-biais de position: ne sélectionne PAS automatiquement le premier élément des listes.\n"
            "- Si plusieurs choix sont valides, privilégie un couple moins récent (diversité).\n"
            f"{strategy_hints}"
            f"{objective_hint_instruction}\n"
            "- Retourne un JSON strict, sans markdown:\n"
            '{"symbol":"...","timeframe":"...","confidence":0.0,"reason":"..."}\n'
            f"- confidence doit être entre 0 et 1.{diversity_instruction}"
        ),
    )

    # --- Phase 12 : appel LLM --- #
    try:
        if stream_callback and hasattr(llm_client, "chat_stream"):
            raw = llm_client.chat_stream(
                [system_msg, user_msg],
                on_chunk=lambda c: stream_callback("market_pick", c),
                max_tokens=180,
            )
        else:
            raw = llm_client.chat([system_msg, user_msg], max_tokens=180)
        raw_text = str(getattr(raw, "content", raw) or "").strip()
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError) as exc:
        logger.warning("recommend_market_context: fallback exception=%s", exc)
        return {
            "symbol": fallback_symbol,
            "timeframe": fallback_timeframe,
            "confidence": 0.0,
            "reason": f"Échec appel LLM ({exc}). Fallback appliqué.",
            "source": "fallback_exception",
        }

    payload = _extract_json_from_response(raw_text)
    symbol = str(payload.get("symbol", "")).strip().upper()
    timeframe = str(payload.get("timeframe", "")).strip()

    try:
        confidence = float(payload.get("confidence", 0.5))
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    reason = str(payload.get("reason", "") or "").strip()

    # --- Phases 13-16 : validation, override diversité, bonus hints, finalisation --- #
    return _finalize_market_result(
        symbol=symbol,
        timeframe=timeframe,
        confidence=confidence,
        reason=reason,
        source="llm",
        payload=payload,
        symbols=symbols,
        timeframes=timeframes,
        strict_fallback_symbol=strict_fallback_symbol,
        strict_fallback_timeframe=strict_fallback_timeframe,
        recent_markets=recent_markets,
        hinted_symbol=hinted_symbol,
        hinted_timeframe=hinted_timeframe,
    )


# ---------------------------------------------------------------------------
# Public wrapper – catalog integration
# ---------------------------------------------------------------------------


def compile_proposal_to_code(proposal: dict[str, Any], variant: int = 0) -> str:
    """Compile un proposal JSON en code Python stratégie exécutable.

    Wrapper public autour de _build_deterministic_fallback_code, destiné
    au module catalog.gating pour le mini-backtest sans LLM.
    """
    return _build_deterministic_fallback_code(proposal, variant=variant)


def _remove_hardcoded_tokens(text: str) -> str:
    """Retire les tokens crypto hardcodés d'un objectif (ex: "0GUSDC", "BTCUSDC").

    Remplace les patterns comme:
    - "sur 0GUSDC en" → "sur crypto en"
    - "sur BTCUSDC dans" → "sur crypto dans"
    - "[Momentum] sur 0GUSDC" → "[Momentum] sur crypto"

    Utilisé quand symbol=None pour permettre sélection LLM intelligente.
    """
    if not text:
        return text

    # Pattern : tokens crypto (XXXXXUSDC où XXXXX = lettres/chiffres)
    # Exemples : 0GUSDC, BTCUSDC, ETHUSDC, 1000SATSUSDC, etc.
    token_pattern = r"\b[A-Z0-9]{2,12}USDC\b"

    # Remplacer "sur TOKEN en/dans/..." par "sur crypto en/dans/..."
    text = re.sub(rf"sur\s+{token_pattern}\s+(en|dans|avec|pour)", r"sur crypto \1", text, flags=re.IGNORECASE)

    # Remplacer "TOKEN en/dans" restants par "crypto en/dans"
    text = re.sub(rf"{token_pattern}\s+(en|dans)", r"crypto \1", text, flags=re.IGNORECASE)

    # Filet final : remplace tout token crypto restant (ex: "sur BTCUSDC.")
    text = re.sub(token_pattern, "crypto", text, flags=re.IGNORECASE)

    # Nettoyer les doubles espaces
    text = re.sub(r"\s+", " ", text).strip()

    return text


def _remove_hardcoded_timeframes(text: str) -> str:
    """Retire les timeframes hardcodés d'un objectif (ex: "1h", "30m", "5m").

    Remplace les patterns comme:
    - "en 1h" → "en timeframe adapté"
    - "dans les 5m" → "dans un timeframe court"
    - "crypto 30m" → "crypto"

    Utilisé quand timeframe=None pour permettre sélection LLM intelligente.
    """
    if not text:
        return text

    # Pattern : timeframes (1m, 5m, 15m, 30m, 1h, 4h, 1d, etc.)
    tf_pattern = r"\b\d+[mhdwM]\b"

    # Remplacer "en/dans [TF]" par une description générique
    text = re.sub(rf"(en|dans)\s+(les?\s+)?{tf_pattern}", r"\1 timeframe adapté", text, flags=re.IGNORECASE)

    # Remplacer TF isolés restants
    text = re.sub(rf"\s+{tf_pattern}\b", "", text, flags=re.IGNORECASE)

    # Nettoyer les doubles espaces
    text = re.sub(r"\s+", " ", text).strip()

    return text
