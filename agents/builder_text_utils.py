"""Module-ID: agents.builder_text_utils

Purpose: Utilitaires texte purs du Strategy Builder, sans dépendance métier.

Role in pipeline: utilitaires / formatage

Dependencies: stdlib uniquement
"""

from __future__ import annotations

import json
import pprint
import re
import traceback
from typing import Any


def _err(code: str, message: str) -> str:
    """Formate un message d'erreur avec code stable."""
    return f"[{code}] {message}"


def _normalize_llm_text(value: Any, *, fallback: str = "", max_len: int = 1200) -> str:
    """Normalise un payload LLM potentiellement structuré en texte affichable."""
    text = ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list, tuple, set)):
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
            text = str(value)
    elif value is None:
        text = ""
    else:
        text = str(value)

    text = text.strip()
    if not text:
        text = str(fallback or "").strip()
    if not text:
        return ""
    if len(text) > max_len:
        text = text[:max_len].rstrip()
    return text


def _looks_like_log_pollution(text: str) -> bool:
    """Heuristique simple pour détecter un collage de logs/traceback."""
    if not text:
        return False
    lower = text.lower()
    if "traceback (most recent call last)" in lower:
        return True
    if "streamlitapiexception" in lower:
        return True
    if re.search(r"^\s*\d{2}:\d{2}:\d{2}\s*\|\s*\w+\s*\|", text, re.MULTILINE):
        return True
    if re.search(
        r"^\s*\|\s*(debug|info|warning|error|critical)\s*\|",
        text,
        re.MULTILINE | re.IGNORECASE,
    ):
        return True
    return False


def _safe_format_exception(exc: BaseException) -> str:
    """Formate une exception sans passer par traceback.format_exc/format_exception.

    Évite les crashs secondaires Python 3.12 quand le moteur de suggestion
    d'erreur évalue des propriétés qui relèvent elles-mêmes des exceptions.
    """
    try:
        tb = exc.__traceback__
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
        tb = None

    lines: list[str] = []
    if tb is not None:
        try:
            for frame in traceback.extract_tb(tb):
                code_line = (frame.line or "").strip()
                lines.append(
                    f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}',
                )
                if code_line:
                    lines.append(f"    {code_line}")
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
            lines = []

    header = f"{type(exc).__name__}: {exc}"
    if lines:
        return "Traceback (most recent call last):\n" + "\n".join(lines) + f"\n{header}"
    return header


def _format_python_dict_literal(data: dict[str, Any]) -> str:
    """Formate un dict Python de manière stable pour insertion dans le code."""
    return pprint.pformat(data, width=88, sort_dicts=True, compact=False)
