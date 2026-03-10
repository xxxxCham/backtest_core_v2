"""Objective generation and market recommendation for the StrategyBuilder.

Extracted from ``agents.strategy_builder`` to reduce module size.
Public API:
    - generate_random_objective
    - generate_llm_objective
    - recommend_market_context
"""
from __future__ import annotations

import json
import random
import re
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

from indicators.registry import list_indicators
from utils.observability import get_obs_logger

logger = get_obs_logger(__name__)
# ── DIAG: Force INFO level temporairement ──
import logging
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Constants
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
        "primary": ["bollinger", "rsi", "stochastic", "cci", "williams_r", "stoch_rsi", "keltner", "donchian"],
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
        "primary": ["bollinger", "donchian", "keltner", "atr", "supertrend", "adx"],
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

# ---------------------------------------------------------------------------
# Objective generation
# ---------------------------------------------------------------------------


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
    # Import classification tokens/TF
    try:
        from data.token_classification import (
            get_recommended_timeframes,
            get_recommended_token_profile,
            get_tokens_by_profile,
            get_preferred_timeframe,
        )
        use_recommendations = True
    except ImportError:
        logger.warning("Module token_classification non disponible, fallback aléatoire")
        use_recommendations = False

    # Détecter l'archetype de stratégie depuis family_key
    archetype_map = {
        "trend-following": "trend_following",
        "mean-reversion": "mean_reversion",
        "momentum": "day_trading",
        "breakout": "breakout",
        "volatility": "scalping",
    }

    # Normaliser listes → valeur unique avec recommandations
    if isinstance(symbol, list):
        if use_recommendations and family_key in archetype_map:
            # Utiliser recommandations basées sur archetype
            archetype = archetype_map[family_key]
            token_profile = get_recommended_token_profile(archetype)
            recommended_tokens = get_tokens_by_profile(token_profile, fallback_to_all=True)

            # Intersection avec tokens disponibles
            valid_tokens = [t for t in recommended_tokens if t in symbol] if symbol else recommended_tokens
            symbol = random.choice(valid_tokens) if valid_tokens else random.choice(symbol) if symbol else "BTCUSDC"
        else:
            symbol = random.choice(symbol) if symbol else "BTCUSDC"

    if isinstance(timeframe, list):
        if use_recommendations and family_key in archetype_map:
            # Utiliser TF recommandés pour cet archetype
            archetype = archetype_map[family_key]
            recommended_tfs = get_recommended_timeframes(archetype)

            # Intersection avec TFs disponibles
            valid_tfs = [tf for tf in recommended_tfs if tf in timeframe] if timeframe else recommended_tfs
            timeframe = random.choice(valid_tfs) if valid_tfs else get_preferred_timeframe(archetype)
        else:
            timeframe = random.choice(timeframe) if timeframe else "1h"

    if available_indicators is None:
        available_indicators = list_indicators()

    avail_lower = {ind.lower() for ind in available_indicators}

    # Choisir une famille
    family_key = random.choice(list(_INDICATOR_FAMILIES.keys()))
    family = _INDICATOR_FAMILIES[family_key]

    # Filtrer les indicateurs disponibles dans cette famille
    valid_primary = [ind for ind in family["primary"] if ind.lower() in avail_lower]
    if len(valid_primary) < 2:
        valid_primary = [ind for ind in available_indicators if ind.lower() != "atr"]

    # Sélectionner 2-3 indicateurs + ATR pour le risk management
    n_indicators = random.randint(2, min(3, len(valid_primary)))
    selected = random.sample(valid_primary, n_indicators)
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


def _build_positive_objective_bias_instruction(max_items: int = 3) -> str:
    """Construit une instruction de prompt à partir des objectifs historiquement positifs."""
    try:
        from agents.strategy_builder import _get_exploration_tracker

        tracker = _get_exploration_tracker()
        summary = tracker.get_positive_bias_summary(limit=max_items)
    except Exception:
        return ""

    positive_count = int(summary.get("positive_count", 0) or 0)
    if positive_count <= 0:
        return ""

    def _extract_names(items: List[Dict[str, Any]]) -> List[str]:
        names: List[str] = []
        for item in items[:max(1, max_items)]:
            name = str(item.get("name", "")).strip()
            if name:
                names.append(name)
        return names

    family_names = _extract_names(cast(List[Dict[str, Any]], summary.get("top_families", [])))
    indicator_patterns = _extract_names(cast(List[Dict[str, Any]], summary.get("top_indicator_patterns", [])))
    novelty_names = _extract_names(cast(List[Dict[str, Any]], summary.get("top_novelty_angles", [])))

    lines = ["Ancrages performants issus des sessions precedentes:"]
    if family_names:
        lines.append(f"- Familles robustes detectees: {', '.join(family_names)}.")
    if indicator_patterns:
        lines.append(
            "- Combinaisons indicateurs deja positives: "
            f"{', '.join(indicator_patterns)}."
        )
    if novelty_names:
        lines.append(f"- Angles de nouveaute deja prometteurs: {', '.join(novelty_names)}.")
    lines.append(
        "- Reutilise au moins un ancrage positif, mais MUTER au moins deux dimensions "
        "(direction, filtre, risk management, ou contexte marche) pour eviter la copie."
    )
    return "\n".join(lines) + "\n\n"


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
    from agents.llm_client import LLMMessage
    from agents.strategy_builder import sanitize_objective_text

    if available_indicators is None:
        available_indicators = list_indicators()

    indicators_list = ", ".join(sorted(available_indicators))

    # Normaliser en listes pour construire le prompt multi-marché
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
        # ── DIAG: Prompt LLM pour génération objectif ──
        logger.info(
            "🔍 [DIAG] generate_llm_objective | "
            "Shuffled symbols: %s | Shuffled timeframes: %s | "
            "Recent markets (%d): %s",
            ", ".join(shuffled_symbols[:10]) + ("..." if len(shuffled_symbols) > 10 else ""),
            ", ".join(shuffled_timeframes),
            len(recent_markets) if recent_markets else 0,
            recent_markets[-6:] if recent_markets else "NONE",
        )
    else:
        market_instruction = f"Marché : {symbols_list[0]} en {timeframes_list[0]}.\n\n"





    system_msg = LLMMessage(
        role="system",
        content=(
            "Tu es un quant designer spécialisé en stratégies de trading crypto. "
            "Génère UN objectif de stratégie original et précis. "
            "Réponds UNIQUEMENT avec l'objectif, sans explication ni formatage markdown."
        ),
    )
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
    positive_bias_instruction = _build_positive_objective_bias_instruction(max_items=3)

    user_msg = LLMMessage(
        role="user",
        content=(
            f"Génère un objectif de stratégie de trading.\n\n"
            f"{market_instruction}"
            f"Indicateurs disponibles : {indicators_list}\n\n"
            f"{positive_bias_instruction}"
            "Contraintes de diversification:\n"
            f"- Intègre au moins un axe 'hors sentiers battus' parmi: {', '.join(selected_axes)}.\n"
            f"- Comportements aleatoires imposes pour cette generation: {', '.join(selected_behaviors)}.\n"
            "- Evite les formulations generiques de type 'RSI<30/RSI>70' sans filtre additionnel.\n"
            "- Propose une hypothese testable et falsifiable.\n\n"
            "Format attendu :\n"
            "[Style] sur [marché] [timeframe]. "
            "Indicateurs : [ind1] + [ind2] + [ind3]. "
            "Entrées : [conditions]. "
            "Sorties : [conditions]. "
            "Risk management : [SL/TP].\n\n"
            "Sois créatif : explore des combinaisons inhabituelles, "
            "des filtres originaux, des approches multi-timeframe conceptuelles. "
            "L'objectif doit faire 2-4 phrases."
        ),
    )

    if stream_callback and hasattr(llm_client, "chat_stream"):
        result = llm_client.chat_stream(
            [system_msg, user_msg],
            on_chunk=lambda c: stream_callback("objective_gen", c),
            max_tokens=300,
        )
    else:
        result = llm_client.chat([system_msg, user_msg], max_tokens=300)

    # Extraire .content si LLMResponse, sinon str()
    objective = str(getattr(result, "content", result) or "").strip()
    # Nettoyer les tags <think> si présents
    objective = re.sub(r"<think>.*?</think>", "", objective, flags=re.DOTALL).strip()
    objective = re.sub(r"<think>.*", "", objective, flags=re.DOTALL).strip()
    objective = sanitize_objective_text(objective)

    # Fallback si le LLM retourne du vide
    if not objective or len(objective) < 20:
        logger.warning("generate_llm_objective: résultat LLM vide, fallback template")
        return generate_random_objective(symbol, timeframe, available_indicators)

    # ── Post-validation : remplacer les TF/tokens hallucinés ──
    tf_pattern = re.compile(r"\b(\d{1,2}[mhdwM])\b")
    found_tfs = tf_pattern.findall(objective)
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

    return objective


# ---------------------------------------------------------------------------
# Market recommendation
# ---------------------------------------------------------------------------


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
    déterministe est appliqué.
    """
    from agents.llm_client import LLMMessage
    from agents.strategy_builder import (
        _extract_json_from_response,
        sanitize_objective_text,
    )

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

    symbols = _unique_non_empty(
        [*candidate_symbols, default_symbol or "BTCUSDC"],
        upper=True,
    )
    symbols = [s for s in symbols if symbol_re.match(s)]

    timeframes = _unique_non_empty(
        [*candidate_timeframes, default_timeframe or "1h"],
        upper=False,
    )
    timeframes = [tf for tf in timeframes if timeframe_re.match(tf)]

    fallback_symbol = (
        str(default_symbol).strip().upper()
        if str(default_symbol).strip().upper() in symbols
        else (symbols[0] if symbols else "BTCUSDC")
    )
    fallback_timeframe = (
        str(default_timeframe).strip()
        if str(default_timeframe).strip() in timeframes
        else (timeframes[0] if timeframes else "1h")
    )

    if not symbols or not timeframes:
        return {
            "symbol": fallback_symbol,
            "timeframe": fallback_timeframe,
            "confidence": 0.0,
            "reason": "Univers marché incomplet, fallback par défaut.",
            "source": "fallback_no_candidates",
        }

    clean_objective = sanitize_objective_text(objective)
    if not clean_objective:
        clean_objective = str(objective or "").strip()

    hinted_symbol, hinted_timeframe = _find_objective_market_hints(
        clean_objective,
        allowed_symbols=symbols,
        allowed_timeframes=timeframes,
    )

    # ── DIAG: Extraction hints ──
    logger.info(
        f"🔍 [DIAG] _find_objective_market_hints\n"
        f"Objective: {clean_objective[:100]}\n"
        f"Hinted symbol: {hinted_symbol or '❌ NONE'} | Hinted TF: {hinted_timeframe or '❌ NONE'}"
    )

    # Si l'objectif contient déjà un couple explicite valide, on le respecte
    # (les templates/catalogue injectent ce couple en amont).
    if hinted_symbol and hinted_timeframe:
        return {
            "symbol": hinted_symbol,
            "timeframe": hinted_timeframe,
            "confidence": 1.0,
            "reason": (
                "Couple token/timeframe explicitement présent dans l'objectif; "
                "priorité donnée à cette instruction."
            ),
            "source": "objective_hint",
        }

    # Mélanger pour réduire le biais de position
    shuffled_symbols = symbols.copy()
    random.shuffle(shuffled_symbols)
    shuffled_timeframes = timeframes.copy()
    random.shuffle(shuffled_timeframes)

    diversity_instruction = ""
    if recent_markets:
        recent_str = ", ".join(f"{s} {tf}" for s, tf in recent_markets[-6:])
        diversity_instruction = (
            f"\n- DÉJÀ UTILISÉS récemment : {recent_str}. "
            "Tu DOIS choisir un couple DIFFÉRENT. Varie tokens ET timeframes."
        )

    # ── DIAG: Prompt LLM pour sélection marché ──
    logger.info(
        "🔍 [DIAG] recommend_market_context | "
        "Shuffled symbols: %s | Shuffled timeframes: %s | "
        "Recent markets (%d): %s | Diversity instruction: %s",
        ", ".join(shuffled_symbols[:10]) + ("..." if len(shuffled_symbols) > 10 else ""),
        ", ".join(shuffled_timeframes),
        len(recent_markets) if recent_markets else 0,
        recent_markets[-6:] if recent_markets else "NONE",
        "YES" if diversity_instruction else "NO",
    )

    objective_hint_instruction = ""
    hint_lines: List[str] = []
    if hinted_symbol:
        hint_lines.append(
            f"- L'objectif mentionne explicitement le symbole `{hinted_symbol}` : "
            "conserve ce symbole."
        )
    if hinted_timeframe:
        hint_lines.append(
            f"- L'objectif mentionne explicitement le timeframe `{hinted_timeframe}` : "
            "conserve ce timeframe."
        )
    if hint_lines:
        objective_hint_instruction = "\n" + "\n".join(hint_lines)

    system_msg = LLMMessage(
        role="system",
        content=(
            "Tu es un analyste quant. Choisis UN seul couple symbole/timeframe "
            "le plus pertinent pour l'objectif. Réponds en JSON strict uniquement."
        ),
    )
    user_msg = LLMMessage(
        role="user",
        content=(
            "Objectif:\n"
            f"{clean_objective}\n\n"
            "Contraintes:\n"
            f"- symbol MUST be one of: {', '.join(shuffled_symbols)}\n"
            f"- timeframe MUST be one of: {', '.join(shuffled_timeframes)}\n"
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
    except Exception as exc:
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
    except Exception:
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    reason = str(payload.get("reason", "") or "").strip()

    # ── DIAG: Choix brut du LLM ──
    logger.info(
        "🔍 [DIAG] LLM raw choice → symbol=%s, timeframe=%s, confidence=%.2f | "
        "Valid symbol: %s | Valid TF: %s",
        symbol or "EMPTY",
        timeframe or "EMPTY",
        confidence,
        "YES" if symbol in symbols else f"NO (not in {symbols[:5]}...)",
        "YES" if timeframe in timeframes else f"NO (not in {timeframes})",
    )

    source = "llm"
    if symbol not in symbols:
        source = "fallback_out_of_universe"
        symbol = fallback_symbol
    if timeframe not in timeframes:
        source = "fallback_out_of_universe"
        timeframe = fallback_timeframe

    if not payload:
        source = "fallback_invalid_json"
        symbol = fallback_symbol
        timeframe = fallback_timeframe
        confidence = 0.0
        if not reason:
            reason = "Réponse LLM non parseable en JSON. Fallback appliqué."

    hint_overrides: List[str] = []
    if hinted_symbol and symbol != hinted_symbol:
        symbol = hinted_symbol
        hint_overrides.append(f"symbol={hinted_symbol}")
    if hinted_timeframe and timeframe != hinted_timeframe:
        timeframe = hinted_timeframe
        hint_overrides.append(f"timeframe={hinted_timeframe}")
    if hint_overrides:
        source = "llm_with_objective_hint" if source == "llm" else "objective_hint_fallback"
        confidence = max(confidence, 0.85)
        applied = ", ".join(hint_overrides)
        if reason:
            reason = f"{reason} Contraintes objectif appliquées ({applied})."
        else:
            reason = f"Contraintes objectif appliquées ({applied})."

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
