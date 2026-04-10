"""Objective generation and market recommendation for the Strategy Builder.

Extracted from ``agents.strategy_builder`` to reduce module size while keeping
public wrappers compatible in the original module.
"""

from __future__ import annotations

import random
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from agents.llm_client import LLMMessage
from config.market_selection import (
    get_strategy_requirements,
    infer_strategy_type,
    rank_tokens_for_strategy,
)
from indicators.registry import list_indicators
from utils.observability import get_obs_logger
from agents.strategy_builder import (
    _build_deterministic_fallback_code,
    _canonicalize_indicator_name,
    _extract_json_from_response,
    _looks_like_prompt_instruction_leakage,
    _normalize_llm_text,
    sanitize_objective_text,
)

logger = get_obs_logger(__name__)

# ---------------------------------------------------------------------------
# Générateurs d'objectifs pour le mode autonome
# ---------------------------------------------------------------------------

# Groupes d'indicateurs par famille de stratégie (combinaisons cohérentes)
_INDICATOR_FAMILIES: Dict[str, Dict[str, Any]] = {
    "trend-following": {
        "label": "Trend-following",
        "primary": ["ema", "sma", "macd", "supertrend", "adx", "ichimoku", "vortex", "aroon"],
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
        "primary": ["bollinger", "rsi", "stochastic", "cci", "williams_r", "stoch_rsi", "keltner", "mfi", "obv"],
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
        "primary": ["rsi", "macd", "momentum", "roc", "stochastic", "mfi"],
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
        "primary": ["bollinger", "donchian", "keltner", "atr", "supertrend", "adx", "pivot_points", "psar", "ichimoku"],
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
        "primary": ["ema", "macd", "rsi", "stochastic", "vwap", "bollinger"],
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
        "primary": ["ema", "rsi", "macd", "bollinger", "adx", "supertrend", "stochastic", "obv"],
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
        "primary": ["adx", "atr", "bollinger", "keltner", "supertrend", "rsi", "vwap", "obv", "ema"],
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
_RECENT_INDICATORS: List[str] = []
_MAX_RECENT_INDICATORS = 8  # Évite de réutiliser les 8 derniers indicateurs principaux
_RECENT_FAMILIES: List[str] = []
_MAX_RECENT_FAMILIES = 3  # Évite de réutiliser les 3 dernières familles


def generate_random_objective(
    symbol: "str | List[str]" = "BTCUSDC",
    timeframe: "str | List[str]" = "1h",
    available_indicators: Optional[List[str]] = None,
) -> str:
    """Génère un objectif de stratégie aléatoire à partir de templates.

    Accepte des listes de symboles/timeframes : un couple est choisi
    aléatoirement pour diversifier les objectifs en mode autonome.

    Combine une famille de stratégie, des indicateurs du registry,
    des conditions d'entrée/sortie et du risk management.

    Returns:
        Objectif structuré en français prêt à être passé au StrategyBuilder.
    """
    global _RECENT_INDICATORS, _RECENT_FAMILIES

    # Normaliser listes → valeur unique (choix aléatoire)
    if isinstance(symbol, list):
        symbol = random.choice(symbol) if symbol else "BTCUSDC"
    if isinstance(timeframe, list):
        timeframe = random.choice(timeframe) if timeframe else "1h"

    if available_indicators is None:
        available_indicators = list_indicators()

    avail_lower = {ind.lower() for ind in available_indicators}

    # 🎯 Choisir une famille en évitant les récentes
    all_families = list(_INDICATOR_FAMILIES.keys())
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
        ind1=ind1, ind2=ind2, ind3=ind3,
    )
    exit_rule = random.choice(family["exit_templates"]).format(
        ind1=ind1, ind2=ind2, ind3=ind3,
    )

    # Risk management
    sl_mult = round(random.uniform(1.0, 2.5), 1)
    tp_mult = round(sl_mult * random.uniform(1.5, 3.0), 1)
    rr = round(tp_mult / sl_mult, 1)
    risk = random.choice(_RISK_TEMPLATES).format(
        sl_mult=sl_mult, tp_mult=tp_mult, rr=rr,
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
    available_indicators: List[str],
) -> str:
    """Nettoie le bloc `Indicateurs:` pour ne garder que des noms calculables."""
    text = str(objective or "")
    if not text:
        return text

    allowed = [
        str(ind or "").strip().lower()
        for ind in (available_indicators or [])
        if str(ind or "").strip()
    ]
    if not allowed:
        return text
    allowed_set = set(allowed)

    preferred_fallback = [
        name
        for name in ("ema", "rsi", "bollinger", "macd", "stochastic", "adx", "atr")
        if name in allowed_set
    ]

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

    extracted = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw_block)
    selected: List[str] = []
    for token in extracted:
        normalized = _canonicalize_indicator_name(token, known=allowed_set)
        if normalized and normalized not in selected:
            selected.append(normalized)

    if "atr" in allowed_set and "atr" not in selected:
        selected.append("atr")

    if len(selected) < 2:
        for candidate in preferred_fallback:
            if candidate not in selected:
                selected.append(candidate)
            if len(selected) >= 3:
                break

    if not selected:
        return text

    rebuilt = f"{prefix}{' + '.join(ind.upper() for ind in selected[:4])}{suffix}"
    start, end = match.span()
    return f"{text[:start]}{rebuilt}{text[end:]}"


def _sanitize_objective_indicator_candidates(
    raw_indicators: Any,
    available_indicators: List[str],
) -> List[str]:
    """Normalise une liste d'indicateurs issus d'un payload structuré."""
    allowed = [
        str(ind or "").strip().lower()
        for ind in (available_indicators or [])
        if str(ind or "").strip()
    ]
    allowed_set = set(allowed)
    if not allowed_set:
        return []

    raw_tokens: List[str] = []
    if isinstance(raw_indicators, str):
        raw_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw_indicators)
    elif isinstance(raw_indicators, (list, tuple, set)):
        raw_tokens = [str(item or "") for item in raw_indicators]

    selected: List[str] = []
    for token in raw_tokens:
        normalized = _canonicalize_indicator_name(token, known=allowed_set)
        if normalized and normalized not in selected:
            selected.append(normalized)

    if len(selected) < 2:
        preferred = [
            name
            for name in ("ema", "rsi", "bollinger", "macd", "stochastic", "adx", "atr")
            if name in allowed_set and name not in selected
        ]
        for candidate in preferred:
            selected.append(candidate)
            if len(selected) >= 3:
                break

    return selected[:4]


def _request_structured_objective_payload(
    llm_client: Any,
    *,
    system_prompt: str,
    user_prompt: str,
    stream_callback: Optional[Callable[[str, str], None]],
    max_tokens: int,
) -> tuple[Dict[str, Any], str]:
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
    payload: Dict[str, Any],
    *,
    market_auto_selection: bool,
    symbols_list: List[str],
    timeframes_list: List[str],
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
    payload: Dict[str, Any],
    *,
    available_indicators: List[str],
    market_auto_selection: bool,
    symbols_list: List[str],
    timeframes_list: List[str],
) -> str:
    """Reconstruit un objectif lisible depuis un payload JSON."""
    if not isinstance(payload, dict) or not payload:
        return ""

    if not any(
        str(payload.get(key, "") or "").strip()
        for key in ("objective", "style", "entry_logic", "exit_logic", "risk_management", "hypothesis")
    ) and not payload.get("used_indicators"):
        return ""

    objective = _normalize_llm_text(payload.get("objective"), max_len=900)
    objective = sanitize_objective_text(objective)
    if objective and not _looks_like_prompt_instruction_leakage(objective):
        return objective

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

    parts: List[str] = []
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


def generate_llm_objective(
    llm_client: Any,
    symbol: "str | List[str]" = "BTCUSDC",
    timeframe: "str | List[str]" = "1h",
    available_indicators: Optional[List[str]] = None,
    stream_callback: Optional[Callable[[str, str], None]] = None,
    recent_markets: Optional[List[Tuple[str, str]]] = None,
) -> str:
    """Génère un objectif de stratégie via un appel LLM.

    Accepte des listes de symboles/timeframes : le LLM est invité à
    choisir le couple le plus pertinent pour sa stratégie.

    Returns:
        Objectif en texte libre généré par le LLM.
    """
    if available_indicators is None:
        available_indicators = list_indicators()

    indicators_list = ", ".join(sorted(available_indicators))

    # Normaliser en listes pour construire le prompt multi-marché.
    # IMPORTANT : si None est passé, ne pas fallback sur BTCUSDC/1h.
    market_auto_selection = (symbol is None or timeframe is None)

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
        symbols_list = symbol if isinstance(symbol, list) else [symbol]
        timeframes_list = timeframe if isinstance(timeframe, list) else [timeframe]
        symbols_list = [s for s in symbols_list if s] or ["BTCUSDC"]
        timeframes_list = [t for t in timeframes_list if t] or ["1h"]

        # Construire l'instruction marché selon l'univers disponible
        if len(symbols_list) > 1 or len(timeframes_list) > 1:
            # Mélanger pour réduire le biais de position (BTC toujours 1er)
            shuffled_symbols = symbols_list.copy()
            random.shuffle(shuffled_symbols)
            shuffled_timeframes = timeframes_list.copy()
            random.shuffle(shuffled_timeframes)

            market_instruction = (
                f"Symboles disponibles (SEULS autorisés) : {', '.join(shuffled_symbols)}\n"
                f"Timeframes disponibles (SEULS autorisés) : {', '.join(shuffled_timeframes)}\n"
                "CHOISIS le symbole et le timeframe les plus adaptés à ta stratégie. "
                "Tu ne DOIS utiliser QUE des symboles et timeframes de ces listes. "
                "N'invente AUCUN timeframe (pas de 3m, 5m, 2h, etc. s'ils ne sont pas listés). "
                "Ne te limite pas à BTC — explore les altcoins si ta stratégie s'y prête mieux.\n\n"
            )
            # Injecter l'historique récent pour forcer la diversité
            if recent_markets:
                recent_str = ", ".join(f"{s} {tf}" for s, tf in recent_markets[-6:])
                market_instruction += (
                    f"IMPORTANT — Les marchés suivants ont DÉJÀ été utilisés récemment : {recent_str}. "
                    "Tu DOIS choisir un couple symbol/timeframe DIFFÉRENT de ceux-ci. "
                    "Varie les tokens ET les timeframes.\n\n"
                )
        else:
            market_instruction = f"Marché : {symbols_list[0]} en {timeframes_list[0]}.\n\n"

    novelty_axes = [
        "asymetrie long/short (seuils differents)",
        "adaptation de regime (trend vs range)",
        "filtre anti-faux-signaux (confirmation inverse partielle)",
        "filtre horaire de liquidite",
        "gestion du risque non lineaire (SL/TP adaptes a la volatilite)",
        "gating par volatilite implicite/realisee",
        "combinaison de signaux contradictoires avec vote majoritaire",
    ]
    random.shuffle(novelty_axes)
    selected_axes = novelty_axes[:4]

    random_behaviors = [
        "mode_offbeat: prioriser des paires d'indicateurs rarement combinees",
        "mode_inverse: tester une logique inversee puis filtrer par regime",
        "mode_microstructure: ajouter un filtre de session/horaire et liquidite",
        "mode_risk_rotation: alterner profile risque serre/large selon volatilite",
        "mode_counter_consensus: exiger une confirmation contrarienne partielle",
    ]
    random.shuffle(random_behaviors)
    selected_behaviors = random_behaviors[:2]
    system_prompt = (
        "Tu es un quant designer specialise en strategies de trading crypto. "
        "Tu dois produire un handoff STRUCTURE et exploitable par un Builder. "
        "Reponds UNIQUEMENT avec un objet JSON valide, sans markdown ni commentaire."
    )
    if market_auto_selection:
        market_contract = (
            "- symbol MUST be exactly `{symbol}`.\n"
            "- timeframe MUST be exactly `{timeframe}`.\n"
        )
    else:
        allowed_symbols = ", ".join(symbols_list)
        allowed_timeframes = ", ".join(timeframes_list)
        market_contract = (
            f"- symbol MUST be one of: {allowed_symbols}.\n"
            f"- timeframe MUST be one of: {allowed_timeframes}.\n"
        )

    user_prompt = (
        "Genere un objectif de strategie de trading sous forme de JSON.\n\n"
        f"{market_instruction}"
        f"Indicateurs disponibles : {indicators_list}\n\n"
        "Contraintes de diversification:\n"
        f"- Integre au moins un axe 'hors sentiers battus' parmi: {', '.join(selected_axes)}.\n"
        f"- Comportements aleatoires imposes pour cette generation: {', '.join(selected_behaviors)}.\n"
        "- Evite les formulations generiques de type 'RSI<30/RSI>70' sans filtre additionnel.\n"
        "- Propose une hypothese testable et falsifiable.\n"
        "- Explore des combinaisons inhabituelles, des filtres originaux, des approches multi-timeframe conceptuelles.\n"
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
                    found_tf, replacement,
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
                    re.escape(found_sym), replacement, objective,
                    count=1, flags=re.IGNORECASE,
                )
                logger.info(
                    "generate_llm_objective: token halluciné '%s' → '%s'",
                    found_sym, replacement,
                )

    objective = _sanitize_objective_indicators_section(
        objective,
        available_indicators,
    )
    return objective


def generate_llm_objective_from_seed(
    llm_client: Any,
    *,
    seed_objective: str,
    symbol: "str | List[str]" = "BTCUSDC",
    timeframe: "str | List[str]" = "1h",
    available_indicators: Optional[List[str]] = None,
    family: str = "",
    direction: str = "",
    risk_profile: str = "",
    novelty_angle: str = "",
    tags: Optional[List[str]] = None,
    stream_callback: Optional[Callable[[str, str], None]] = None,
    recent_markets: Optional[List[Tuple[str, str]]] = None,
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
    market_auto_selection = (symbol is None or timeframe is None)

    if market_auto_selection:
        market_instruction = (
            "Le marché (token + timeframe) est sélectionné automatiquement par une étape dédiée.\n"
            "Tu DOIS utiliser exactement les placeholders `{symbol}` et `{timeframe}` dans l'objectif final.\n"
            "N'écris AUCUN token réel ni timeframe réel.\n\n"
        )
        symbols_list: List[str] = []
        timeframes_list: List[str] = []
    else:
        symbols_list = symbol if isinstance(symbol, list) else [symbol]
        timeframes_list = timeframe if isinstance(timeframe, list) else [timeframe]
        symbols_list = [s for s in symbols_list if s] or ["BTCUSDC"]
        timeframes_list = [t for t in timeframes_list if t] or ["1h"]
        if len(symbols_list) > 1 or len(timeframes_list) > 1:
            shuffled_symbols = symbols_list.copy()
            random.shuffle(shuffled_symbols)
            shuffled_timeframes = timeframes_list.copy()
            random.shuffle(shuffled_timeframes)
            market_instruction = (
                f"Symboles disponibles (SEULS autorisés) : {', '.join(shuffled_symbols)}\n"
                f"Timeframes disponibles (SEULS autorisés) : {', '.join(shuffled_timeframes)}\n"
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
        market_contract = (
            "- symbol MUST be exactly `{symbol}`.\n"
            "- timeframe MUST be exactly `{timeframe}`.\n"
        )
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
                re.escape(found_sym), replacement, objective,
                count=1, flags=re.IGNORECASE,
            )

    objective = _sanitize_objective_indicators_section(
        objective,
        available_indicators,
    )
    return objective


def recommend_market_context(
    llm_client: Any,
    *,
    objective: str,
    candidate_symbols: List[str],
    candidate_timeframes: List[str],
    default_symbol: str = "BTCUSDC",
    default_timeframe: str = "1h",
    stream_callback: Optional[Callable[[str, str], None]] = None,
    recent_markets: Optional[List[Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    """Recommande un couple (symbol, timeframe) adapté à un objectif Builder.

    Le choix est strictement borné à l'univers fourni (`candidate_symbols`,
    `candidate_timeframes`). En cas de réponse invalide du LLM, un fallback
    robuste est appliqué.
    """

    def _unique_non_empty(values: List[str], *, upper: bool = False) -> List[str]:
        out: List[str] = []
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
        allowed_symbols: List[str],
        allowed_timeframes: List[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Extrait les indices explicites symbol/timeframe présents dans l'objectif."""
        text = sanitize_objective_text(objective_text)
        if not text:
            return None, None

        text_upper = text.upper()

        symbol_hits: List[Tuple[int, str]] = []
        for symbol in allowed_symbols:
            match = re.search(
                rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])",
                text_upper,
            )
            if match:
                symbol_hits.append((match.start(), symbol))

        timeframe_hits: List[Tuple[int, str]] = []
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
        hinted_timeframe = (
            min(timeframe_hits, key=lambda x: x[0])[1]
            if timeframe_hits else None
        )
        return hinted_symbol, hinted_timeframe

    symbol_re = re.compile(r"^[A-Za-z0-9_.-]{2,24}$")
    timeframe_re = re.compile(r"^\d+[mhdwM]$")

    # Universe-first: don't inject default symbol/timeframe when a valid universe exists.
    symbols = _unique_non_empty(candidate_symbols, upper=True)
    if not symbols:
        symbols = _unique_non_empty([default_symbol or "BTCUSDC"], upper=True)
    symbols = [s for s in symbols if symbol_re.match(s)]

    timeframes = _unique_non_empty(candidate_timeframes, upper=False)
    if not timeframes:
        timeframes = _unique_non_empty([default_timeframe or "1h"], upper=False)
    timeframes = [tf for tf in timeframes if timeframe_re.match(tf)]

    # Fallback contractuel: prioriser le couple par défaut quand il est valide.
    # Utilisé pour les cas "réponse LLM invalide / hors univers" afin de garder
    # un comportement déterministe et prévisible côté tests et UI.
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

    # Fallback initial (sera recalculé après détection du type de stratégie)
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

    # Détecter le type de stratégie AVANT d'extraire les hints
    # (car si type détecté, on ignore les hints pour privilégier le tri intelligent)
    detected_strategy_type = infer_strategy_type(objective=clean_objective)
    if detected_strategy_type == "unknown":
        detected_strategy_type = None

    # Trier les tokens selon le type de stratégie détecté
    ranked_symbols: List[str] = []
    if detected_strategy_type:
        # Mélange d'abord les candidats pour randomiser les égalités de score.
        # rank_tokens_for_strategy est stable: à score égal, l'ordre d'entrée est conservé.
        symbols_for_ranking = symbols.copy()
        random.shuffle(symbols_for_ranking)
        ranked_symbols = rank_tokens_for_strategy(symbols_for_ranking, detected_strategy_type)
        # Anti-biais de position: l'ordre envoyé au LLM est volontairement mélangé.
        # Le ranking reste conservé pour le fallback deterministic.
        shuffled_symbols = ranked_symbols.copy()
        random.shuffle(shuffled_symbols)
        logger.info(
            "Market selection: strategy_type=%s, ranked_tokens=%s, prompt_tokens_shuffled=YES",
            detected_strategy_type,
            ", ".join(ranked_symbols[:5]),  # Log top 5 ranking brut
        )
    else:
        # Fallback : shuffle aléatoire si type non détecté
        shuffled_symbols = symbols.copy()
        random.shuffle(shuffled_symbols)
        logger.info("Market selection: strategy_type=UNKNOWN, tokens=shuffled")

    # Mélanger les timeframes (pas de tri spécifique)
    shuffled_timeframes = timeframes.copy()
    random.shuffle(shuffled_timeframes)

    # Extraction des hints : SEULEMENT si aucun type de stratégie détecté
    # Si type détecté, on ignore les hints du catalogue pour privilégier le tri intelligent
    hinted_symbol = None
    hinted_timeframe = None

    if not detected_strategy_type:
        # Pas de type détecté : extraire les hints pour guider le LLM
        hinted_symbol, hinted_timeframe = _find_objective_market_hints(
            clean_objective,
            allowed_symbols=symbols,
            allowed_timeframes=timeframes,
        )
        logger.info(
            "Market selection: strategy_type=NONE → using hints, symbol=%s, timeframe=%s",
            hinted_symbol or "NONE",
            hinted_timeframe or "NONE"
        )
    else:
        # Type détecté : IGNORER les hints hardcodés pour privilégier le tri intelligent
        logger.info(
            "Market selection: strategy_type=%s → IGNORING hints from objective (prioritize intelligent ranking)",
            detected_strategy_type
        )

    recent_symbol_set = {
        str(s or "").strip().upper()
        for s, _ in (recent_markets or [])
        if str(s or "").strip()
    }

    # Fallback intelligent : éviter le biais top-1 quand plusieurs candidats sont valides.
    if hinted_symbol and hinted_symbol in symbols:
        fallback_symbol = hinted_symbol
    else:
        # Si stratégie détectée, piocher dans un pool top-N pour réduire le biais "toujours le même token".
        if detected_strategy_type and ranked_symbols:
            fallback_pool = ranked_symbols[: min(5, len(ranked_symbols))]
            non_recent_pool = [s for s in fallback_pool if s not in recent_symbol_set]
            if non_recent_pool:
                fallback_pool = non_recent_pool
            fallback_symbol = random.choice(fallback_pool) if fallback_pool else ranked_symbols[0]
        else:
            fallback_symbol = (
                shuffled_symbols[0] if shuffled_symbols else _initial_fallback_symbol
            )

    # Fallback timeframe : prioriser TF recommandés / hints / diversité.
    if detected_strategy_type:
        try:
            reqs = get_strategy_requirements(detected_strategy_type)
            recommended_tfs = reqs.get("timeframes", ["1h"])
            # Choisir un TF recommandé disponible, sans biais de position dans la liste.
            recommended_available = [tf for tf in recommended_tfs if tf in timeframes]
            if recommended_available:
                fallback_timeframe = random.choice(recommended_available)
            else:
                fallback_timeframe = (
                    shuffled_timeframes[0] if shuffled_timeframes else _initial_fallback_timeframe
                )
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
            fallback_timeframe = (
                shuffled_timeframes[0] if shuffled_timeframes else _initial_fallback_timeframe
            )
    elif hinted_timeframe and hinted_timeframe in timeframes:
        fallback_timeframe = hinted_timeframe
    else:
        fallback_timeframe = (
            shuffled_timeframes[0] if shuffled_timeframes else _initial_fallback_timeframe
        )

    logger.info(
        "Market selection: fallback=%s %s (source=%s)",
        fallback_symbol,
        fallback_timeframe,
        "strategy_optimized" if detected_strategy_type else "default"
    )

    # Validation diversité : désactiver si trop peu d'alternatives
    diversity_instruction = ""
    if recent_markets:
        from config.market_selection import get_diversity_min_alternatives

        available_combos = [(s, tf) for s in symbols for tf in timeframes]
        recent_window = recent_markets[-6:]  # Fenêtre de diversité (6 derniers)
        unused_combos = [c for c in available_combos if c not in recent_window]
        min_alts = get_diversity_min_alternatives()

        if len(unused_combos) >= min_alts:
            recent_str = ", ".join(f"{s} {tf}" for s, tf in recent_window)
            diversity_instruction = (
                f"\n- DÉJÀ UTILISÉS récemment : {recent_str}. "
                "Tu DOIS choisir un couple DIFFÉRENT. Varie tokens ET timeframes."
            )
            # Log structuré : diversité activée
            logger.info(
                "Market selection: diversity=ACTIVE, excluded_count=%d, alternatives=%d, recent=%s",
                len(recent_window),
                len(unused_combos),
                recent_str,
            )
        else:
            # Diversité désactivée : univers trop restreint
            logger.warning(
                "Market selection: diversity=DISABLED, reason=Univers restreint (%d alternatives < %d min), "
                "recent_count=%d",
                len(unused_combos),
                min_alts,
                len(recent_window),
            )
            diversity_instruction = ""  # Pas de contrainte

    objective_hint_instruction = ""
    hint_lines: List[str] = []

    # Détection conflit hints vs diversité
    if hinted_symbol and hinted_timeframe and recent_markets:
        hinted_combo = (hinted_symbol, hinted_timeframe)
        recent_window = recent_markets[-6:]
        if hinted_combo in recent_window:
            # Conflict detection done in strategy recommendation logic
            logger.warning(
                "Market selection: CONFLICT hints vs diversity, hinted=%s %s (already in recent_markets), "
                "priority=diversity → hints IGNORED",
                hinted_symbol, hinted_timeframe
            )
            # Annuler les hints (priorité à la diversité)
            hinted_symbol = None
            hinted_timeframe = None

    # Construction des instructions hints (si pas de conflit)
    if hinted_symbol:
        hint_lines.append(
            f"- L'objectif mentionne le symbole `{hinted_symbol}` : "
            "considère-le comme une préférence, pas comme une contrainte absolue."
        )
    if hinted_timeframe:
        hint_lines.append(
            f"- L'objectif mentionne le timeframe `{hinted_timeframe}` : "
            "considère-le comme une préférence, pas comme une contrainte absolue."
        )

    if hint_lines:
        objective_hint_instruction = "\n" + "\n".join(hint_lines)

        # Log structuré : hints détectés (si pas de conflit)
        from config.market_selection import get_hints_confidence_boost
        boost = get_hints_confidence_boost()
        logger.info(
            "Market selection: hints_detected=YES, symbol=%s, timeframe=%s, boost=+%.2f confidence",
            hinted_symbol or "NONE",
            hinted_timeframe or "NONE",
            boost if (hinted_symbol or hinted_timeframe) else 0.0,
        )

    system_msg = LLMMessage(
        role="system",
        content=(
            "Tu es un analyste quant. Choisis UN seul couple symbole/timeframe "
            "le plus pertinent pour l'objectif. Réponds en JSON strict uniquement."
        ),
    )
    # Enrichissement : recommandations TF/token basées sur type de stratégie détecté
    strategy_hints = ""
    try:
        if detected_strategy_type:
            reqs = get_strategy_requirements(detected_strategy_type)
            recommended_tfs = reqs.get("timeframes", ["1h"])

            # Extraire top 5 tokens recommandés (déjà triés par rank_tokens_for_strategy)
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

    try:
        if stream_callback and hasattr(llm_client, "chat_stream"):
            raw = llm_client.chat_stream(
                [system_msg, user_msg],
                on_chunk=lambda c: stream_callback("market_pick", c),
                max_tokens=180,
            )
        else:
            raw = llm_client.chat([system_msg, user_msg], max_tokens=180)
        # Extraire .content si LLMResponse, sinon str()
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

    source = "llm"
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
    # Évite de rester figé sur le même couple déjà utilisé récemment.
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

            # Si tout l'univers a déjà été vu, forcer une rotation sur le moins récent.
            if not candidate_pool:
                last_seen: Dict[Tuple[str, str], int] = {p: -1 for p in all_pairs}
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
                    reason = (
                        f"{reason} Couple récent évité automatiquement "
                        f"({selected_pair[0]} {selected_pair[1]})."
                    )
                else:
                    reason = (
                        f"Couple récent évité automatiquement "
                        f"({selected_pair[0]} {selected_pair[1]})."
                    )

    # Bonus léger si le LLM choisit spontanément les hints de l'objectif,
    # sans les forcer pour préserver la diversité multi-market.
    hint_matches: List[str] = []
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


# ---------------------------------------------------------------------------
# Public wrapper – catalog integration
# ---------------------------------------------------------------------------

def compile_proposal_to_code(proposal: Dict[str, Any], variant: int = 0) -> str:
    """Compile un proposal JSON en code Python stratégie exécutable.

    Wrapper public autour de _build_deterministic_fallback_code, destiné
    au module catalog.gating pour le mini-backtest sans LLM.
    """
    return _build_deterministic_fallback_code(proposal, variant=variant)


def _remove_hardcoded_tokens(text: str) -> str:
    """
    Retire les tokens crypto hardcodés d'un objectif (ex: "0GUSDC", "BTCUSDC").

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
    token_pattern = r'\b[A-Z0-9]{2,12}USDC\b'

    # Remplacer "sur TOKEN en/dans/..." par "sur crypto en/dans/..."
    text = re.sub(
        rf'sur\s+{token_pattern}\s+(en|dans|avec|pour)',
        r'sur crypto \1',
        text,
        flags=re.IGNORECASE
    )

    # Remplacer "TOKEN en/dans" restants par "crypto en/dans"
    text = re.sub(
        rf'{token_pattern}\s+(en|dans)',
        r'crypto \1',
        text,
        flags=re.IGNORECASE
    )

    # Filet final : remplace tout token crypto restant (ex: "sur BTCUSDC.")
    text = re.sub(
        token_pattern,
        'crypto',
        text,
        flags=re.IGNORECASE
    )

    # Nettoyer les doubles espaces
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def _remove_hardcoded_timeframes(text: str) -> str:
    """
    Retire les timeframes hardcodés d'un objectif (ex: "1h", "30m", "5m").

    Remplace les patterns comme:
    - "en 1h" → "en timeframe adapté"
    - "dans les 5m" → "dans un timeframe court"
    - "crypto 30m" → "crypto"

    Utilisé quand timeframe=None pour permettre sélection LLM intelligente.
    """
    if not text:
        return text

    # Pattern : timeframes (1m, 5m, 15m, 30m, 1h, 4h, 1d, etc.)
    tf_pattern = r'\b\d+[mhdwM]\b'

    # Remplacer "en/dans [TF]" par une description générique
    text = re.sub(
        rf'(en|dans)\s+(les?\s+)?{tf_pattern}',
        r'\1 timeframe adapté',
        text,
        flags=re.IGNORECASE
    )

    # Remplacer TF isolés restants
    text = re.sub(
        rf'\s+{tf_pattern}\b',
        '',
        text,
        flags=re.IGNORECASE
    )

    # Nettoyer les doubles espaces
    text = re.sub(r'\s+', ' ', text).strip()

    return text

