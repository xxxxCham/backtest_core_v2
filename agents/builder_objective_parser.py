"""
Module-ID: agents.builder_objective_parser

Purpose: Parsing et nettoyage des objectifs Builder, canonicalisation
des noms d'indicateurs et extraction d'indicateurs depuis du texte libre.

Role in pipeline: Pré-traitement des objectifs avant génération de code LLM.

Skip-if: Vous n'utilisez pas le Strategy Builder.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import logging

from agents.builder_ast_utils import (
    _LOG_PREFIX_RE,
    _PIPE_LOG_PREFIX_RE,
    _TRACEBACK_LINE_RE,
    _WINDOWS_PATH_LINE_RE,
)
from indicators import list_indicators

logger = logging.getLogger(__name__)

_INDICATOR_CANONICAL_ALIASES = {
    "adx_value": "adx",
    "bear_score": "directional_bias",
    "bbands": "bollinger",
    "bull_score": "directional_bias",
    "directional_bias_net": "directional_bias",
    "fib_level": "fibonacci_levels",
    "fib_levels": "fibonacci_levels",
    "fibonacci": "fibonacci_levels",
    "fibonacci_level": "fibonacci_levels",
    "keltner_channel": "keltner",
    "klt": "keltner",
    "net_bias": "directional_bias",
    "obvi": "obv",
    "pivot": "pivot_points",
    "pivot_point": "pivot_points",
    "pivotpoints": "pivot_points",
    "pivots": "pivot_points",
    "rsci": "rsi",
    "stochrsi": "stoch_rsi",
    "super_trend": "supertrend",
    "vol_oscillator": "volume_oscillator",
    "volume_osc": "volume_oscillator",
    "volumeoscillator": "volume_oscillator",
    "williams": "williams_r",
    "williamsr": "williams_r",
}

_OBJECTIVE_PROMPT_SENTENCE_RE = re.compile(
    r"^\s*(?:"
    r"e?vite|"
    r"tu dois|"
    r"le style doit|"
    r"format attendu|"
    r"exemple de format(?: acceptable| correct| rejet[ée])?|"
    r"en tant qu['’]assistant|"
    r"okay, let'?s dive|"
    r"first, i need|"
    r"i need to figure out|"
    r"r[ée]ponse(?: style)?|"
    r"je vais|"
    r"commen[cç]ons|"
    r"d['’]abord|"
    r"premi[eè]rement|"
    r"voici ma|"
    r"laissez-moi|"
    r"permettez-moi|"
    r"il faut|"
    r"n['']oublie pas|"
    # Archives live : EN reasoning-chain starters (3824 NL lines)
    r"the user|"
    r"i should|"
    r"let me think|"
    r"let me start|"
    r"so perhaps|"
    r"so maybe|"
    r"looking back|"
    r"wait[,.]?\s*(?:no|maybe)|"
    r"additionally|"
    r"but let me|"
    # Archives live : FR supplémentaires
    r"réfléchissons|"
    r"voyons|"
    r"attendez|"
    r"regardons|"
    r"il semble que|"
    r"dans ce cas"
    r")\b",
    re.IGNORECASE,
)

_OBJECTIVE_START_PATTERNS = (
    re.compile(r"(Strat[ée]gie(?:\s+de\s+[^.:\n]+)?\s+sur\b.*)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(Objectif(?:\s+de)?\s+Strat[ée]g(?:ique)?(?:\s+de\s+Trading)?\b.*)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(\[[^\]]+\]\s+sur\b.*)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(Objectif\s+sur\b.*)", re.IGNORECASE | re.DOTALL),
)


def sanitize_objective_text(objective: Any, *, enable_leakage_filter: bool = True) -> str:
    """Nettoie un objectif utilisateur et retire les contaminations de logs.

    Cas traités:
    - Collage accidentel de logs complets (INFO/WARNING/Traceback)
    - Objectif imbriqué dans une ligne de log `... objective='...' indicators=...`
    - Bruit visuel (lignes de séparation terminal)
    """
    text = str(objective or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""

    # Nettoyage résidus modèles de raisonnement
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL).strip()

    # Si un objectif est imbriqué dans des logs, récupérer la dernière occurrence
    lower = text.lower()
    marker = "objective='"
    last_idx = lower.rfind(marker)
    if last_idx >= 0:
        start = last_idx + len(marker)
        end = lower.find("' indicators=", start)
        if end == -1:
            end = lower.find("'\n", start)
        if end == -1:
            end = lower.find("'", start)
        if end > start:
            embedded = text[start:end].strip()
            if len(embedded) >= 20:
                text = embedded

    cleaned_lines: List[str] = []
    in_traceback_block = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue

        lower_line = line.lower()
        if "traceback (most recent call last)" in lower_line:
            in_traceback_block = True
            continue
        if in_traceback_block:
            continue

        if _LOG_PREFIX_RE.match(line):
            continue
        if _PIPE_LOG_PREFIX_RE.match(line):
            continue
        if lower_line.startswith("traceback"):
            continue
        if lower_line.startswith("during handling of the above exception"):
            continue
        if _TRACEBACK_LINE_RE.match(line):
            continue
        if _WINDOWS_PATH_LINE_RE.match(line):
            continue
        if line.startswith("PS "):
            continue
        if line.startswith("❱"):
            continue
        if re.match(r"^\d+\s*$", line):
            continue
        if "streamlitapiexception" in lower_line:
            continue
        if "site-packages\\streamlit" in lower_line:
            continue
        if lower_line.startswith("files\\python"):
            continue
        if re.match(r"^[═━\-]{10,}$", line):
            continue
        if re.match(r"^\^+$", line):
            continue

        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    if enable_leakage_filter:
        cleaned = _strip_objective_prompt_leakage(cleaned)
    cleaned = cleaned.strip("`'\" \n\t")
    if len(cleaned) > 4000:
        cleaned = cleaned[:4000].rstrip()
    return cleaned

def _strip_objective_prompt_leakage(text: str) -> str:
    """Retire les restes de méta-consignes quand le LLM recopie le prompt."""
    if not text:
        return ""

    normalized = re.sub(r"[*`#]+", "", str(text or "")).strip()
    if not normalized:
        return ""

    anchored = normalized
    anchor_found = False
    best_start: Optional[int] = None
    best_value = normalized
    for pattern in _OBJECTIVE_START_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        start = match.start(1)
        if best_start is None or start < best_start:
            best_start = start
            best_value = match.group(1).strip()
            anchor_found = True
    anchored = best_value

    kept_sentences: List[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", anchored):
        line = str(sentence or "").strip()
        if not line:
            continue
        if _OBJECTIVE_PROMPT_SENTENCE_RE.match(line):
            continue
        kept_sentences.append(line)

    cleaned = " ".join(kept_sentences).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned:
        return cleaned
    if anchor_found:
        return re.sub(r"\s+", " ", anchored).strip()
    return ""

def _looks_like_prompt_instruction_leakage(text: str) -> bool:
    """Détecte si un objectif ressemble encore à une réponse de prompt contaminée."""
    normalized = str(text or "").strip()
    if not normalized:
        return False
    lower = normalized.lower()
    if "okay, let's dive" in lower or "first, i need" in lower:
        return True
    if "en tant qu'assistant" in lower or "en tant qu’assistant" in lower:
        return True
    if "je vais" in lower and ("analyser" in lower or "commencer" in lower or "répondre" in lower):
        return True
    if "laissez-moi" in lower or "permettez-moi" in lower:
        return True
    # EN reasoning-chain (archives live : 1123 occurrences de fuite de prompt)
    if "the user" in lower and ("must be able" in lower or "provided" in lower or "wants" in lower):
        return True
    if "i need to" in lower and ("create" in lower or "figure" in lower or "understand" in lower):
        return True
    if "let me think" in lower or "let me start" in lower:
        return True
    if "so perhaps" in lower or "so maybe i should" in lower:
        return True
    if "looking back" in lower or "looking at the" in lower:
        return True
    if "wait, no" in lower or "wait, maybe" in lower:
        return True
    # FR supplémentaires (archives live)
    if "réfléchissons" in lower or "voyons" in lower or "attendez" in lower:
        return True
    if "regardons" in lower or "il semble que" in lower or "dans ce cas" in lower:
        return True
    if _OBJECTIVE_PROMPT_SENTENCE_RE.match(normalized):
        return True
    return False

def _canonicalize_indicator_name(
    name: Any,
    *,
    known: Optional[set[str]] = None,
) -> Optional[str]:
    """Ramène les alias fréquents Builder vers un nom d'indicateur du registre."""
    raw = str(name or "").strip().lower()
    if not raw:
        return None

    normalized = raw.replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    candidate = _INDICATOR_CANONICAL_ALIASES.get(normalized, normalized)

    if known is None:
        return candidate
    if candidate in known:
        return candidate
    if normalized in known:
        return normalized
    return None

def _indicator_phrase_pattern(phrase: str) -> str:
    normalized = str(phrase or "").strip().lower().replace("-", "_").replace(" ", "_")
    parts = [re.escape(part) for part in normalized.split("_") if part]
    if not parts:
        return ""
    return r"(?<![A-Za-z0-9])" + r"[\s_\-]*".join(parts) + r"(?![A-Za-z0-9])"

def _extract_indicator_names_from_text(
    text: Any,
    *,
    available_indicators: Optional[List[str]] = None,
) -> List[str]:
    raw_text = str(text or "")
    if not raw_text.strip():
        return []

    known_names = [
        str(ind or "").strip().lower()
        for ind in (
            available_indicators
            if available_indicators is not None
            else list_indicators()
        )
        if str(ind or "").strip()
    ]
    known_set = set(known_names)
    if not known_set:
        return []

    lowered = raw_text.lower()
    hits: List[Tuple[int, str]] = []
    candidates = set(known_set) | set(_INDICATOR_CANONICAL_ALIASES.keys())
    for candidate in candidates:
        normalized = _canonicalize_indicator_name(candidate, known=known_set)
        if not normalized:
            continue
        pattern = _indicator_phrase_pattern(candidate)
        if not pattern:
            continue
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        if match:
            hits.append((match.start(), normalized))

    ordered: List[str] = []
    for _position, indicator_name in sorted(hits, key=lambda item: (item[0], item[1])):
        if indicator_name not in ordered:
            ordered.append(indicator_name)
    return ordered

def _extract_objective_indicator_names(
    objective: Any,
    *,
    available_indicators: Optional[List[str]] = None,
) -> List[str]:
    text = sanitize_objective_text(objective, enable_leakage_filter=False)
    if not text:
        text = str(objective or "").strip()
    if not text:
        return []

    section_match = re.search(
        r"(Indicateurs?\s*:\s*)(.+?)(\.\s|\n|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if section_match:
        section_indicators = _extract_indicator_names_from_text(
            section_match.group(2),
            available_indicators=available_indicators,
        )
        if section_indicators:
            return section_indicators
    return _extract_indicator_names_from_text(
        text,
        available_indicators=available_indicators,
    )

def _build_indicator_override_reason(
    objective_indicators: List[str],
    proposal_indicators: List[str],
) -> str:
    objective_set = set(objective_indicators)
    proposal_set = set(proposal_indicators)
    added = [ind for ind in proposal_indicators if ind not in objective_set]
    removed = [ind for ind in objective_indicators if ind not in proposal_set]
    if added and removed:
        return (
            "semi_open_replace:"
            f" removed={','.join(removed)} added={','.join(added)}"
        )
    if added:
        return f"semi_open_add: added={','.join(added)}"
    if removed:
        return f"semi_open_remove: removed={','.join(removed)}"
    return ""

