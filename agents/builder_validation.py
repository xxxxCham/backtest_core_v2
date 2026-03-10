"""Validation helpers extracted from strategy_builder.

This module centralises all code-validation, text-sanitisation, AST-analysis
and dataset-quality functions used by the Strategy Builder agent.
"""

from __future__ import annotations

import ast
import json
import os
import re
import textwrap
import traceback
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from agents.builder_constants import (
    GENERATED_CLASS_NAME,
    ERR_AST, ERR_CLASS, ERR_IND, ERR_PARAM, ERR_SANDBOX, ERR_SIG, ERR_WARM,
    MIN_BUILDER_BARS,
    SAFE_PATH_MODE_ENV,
    _DICT_INDICATOR_NAMES,
    _DICT_INDICATOR_ALLOWED_KEYS,
    _INDICATOR_ALIAS_HINTS,
    _BUILDER_ALLOWED_WRITE_DF_COLUMNS,
    _LOG_PREFIX_RE, _PIPE_LOG_PREFIX_RE, _TRACEBACK_LINE_RE, _WINDOWS_PATH_LINE_RE,
)
from indicators.registry import list_indicators
from utils.observability import get_obs_logger

logger = get_obs_logger(__name__)


# ---------------------------------------------------------------------------
# Section 1: Sandbox helpers
# ---------------------------------------------------------------------------


def _err(code: str, message: str) -> str:
    """Formate un message d'erreur avec code stable."""
    return f"[{code}] {message}"


def _safe_path_mode() -> str:
    """Retourne le mode safe-path normalisé: off|prefer|strict."""
    raw = os.getenv(SAFE_PATH_MODE_ENV, "off").strip().lower()
    if raw in {"prefer", "strict", "off"}:
        return raw
    if raw in {"1", "true", "yes", "on"}:
        return "prefer"
    return "off"


def _is_allowed_import(module_name: str) -> bool:
    """Allowlist stricte des imports dans le code généré."""
    root = (module_name or "").split(".")[0]
    return root in {"typing", "numpy", "pandas", "strategies", "utils"}


def _strict_sandbox_enabled() -> bool:
    """Active/désactive la sandbox runtime stricte."""
    raw = os.getenv("BACKTEST_BUILDER_STRICT_SANDBOX", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _sandbox_safe_builtins() -> Dict[str, Any]:
    """Construit un set minimal de builtins autorisés dans la sandbox."""
    return {
        "__build_class__": __build_class__,
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "Exception": Exception,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "object": object,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "pow": pow,
        "property": property,
        "range": range,
        "set": set,
        "staticmethod": staticmethod,
        "super": super,
        "sum": sum,
        "tuple": tuple,
        "type": type,
        "zip": zip,
        "isinstance": isinstance,
    }


def _sandbox_import(name: str, global_ns=None, local_ns=None, fromlist=(), level=0):
    """Import guard pour sandbox runtime."""
    if not _is_allowed_import(name):
        raise ImportError(_err(ERR_SANDBOX, f"Import runtime interdit: '{name}'"))
    return __import__(name, global_ns, local_ns, fromlist, level)


def _validate_signal_loop_and_warmup(tree: ast.AST) -> tuple[bool, str]:
    """Valide des patterns signaux/warmup dangereux.

    - Interdit les boucles indexées qui écrivent `signals.iloc[i]`
    - Interdit warmup destructif (`signals.iloc[x:] = 0`, `signals[:] = 0`)
    """
    for fn in _iter_generate_signals_functions(tree):
        for node in ast.walk(fn):
            if isinstance(node, ast.For):
                if (
                    isinstance(node.target, ast.Name)
                    and isinstance(node.iter, ast.Call)
                    and isinstance(node.iter.func, ast.Name)
                    and node.iter.func.id == "range"
                ):
                    return False, _err(
                        ERR_SIG,
                        "Boucle `for i in range(...)` interdite dans generate_signals. "
                        "Utiliser une logique vectorisée.",
                    )
                for sub in ast.walk(node):
                    if not isinstance(sub, ast.Subscript):
                        continue
                    # signals.iloc[i] = ...
                    if (
                        isinstance(sub.value, ast.Attribute)
                        and sub.value.attr == "iloc"
                        and isinstance(sub.value.value, ast.Name)
                        and sub.value.value.id == "signals"
                    ):
                        return False, _err(
                            ERR_SIG,
                            "Boucle indexée avec `signals.iloc[i]` interdite. "
                            "Utiliser des masques vectorisés.",
                        )

            # Warmup checks sur assignations
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for tgt in targets:
                    if not isinstance(tgt, ast.Subscript):
                        continue

                    # Pattern signals[...] ou signals.iloc[...]
                    is_signals_sub = (
                        isinstance(tgt.value, ast.Name) and tgt.value.id == "signals"
                    )
                    is_signals_iloc_sub = (
                        isinstance(tgt.value, ast.Attribute)
                        and tgt.value.attr == "iloc"
                        and isinstance(tgt.value.value, ast.Name)
                        and tgt.value.value.id == "signals"
                    )
                    if not (is_signals_sub or is_signals_iloc_sub):
                        continue

                    sl = tgt.slice
                    if isinstance(sl, ast.Slice):
                        lower = _const_value(sl.lower) if sl.lower is not None else None
                        upper = _const_value(sl.upper) if sl.upper is not None else None
                        # Autorisé: [:N] = 0 (warmup préfixe), N constant ou variable
                        if lower is None and sl.upper is not None:
                            continue
                        # Interdit: [N:] / [:] / [N:M]
                        return False, _err(
                            ERR_WARM,
                            "Warmup invalide: seule la forme `signals.iloc[:N] = 0.0` "
                            "(ou `signals[:N] = 0.0`) est autorisée.",
                        )

            if isinstance(node, ast.While):
                return False, _err(
                    ERR_SIG,
                    "Boucle `while` interdite dans generate_signals. "
                    "Utiliser une logique vectorisée.",
                )

    return True, ""


# ---------------------------------------------------------------------------
# Section 2: validate_generated_code
# ---------------------------------------------------------------------------


def validate_generated_code(code: str) -> tuple[bool, str]:
    """
    Valide le code Python généré avant écriture/exécution.

    Vérifie :
    1. Syntaxe Python valide (ast.parse)
    2. Présence de la classe BuilderGeneratedStrategy
    3. Présence de generate_signals
    4. Absence d'imports dangereux (os.system, subprocess, eval, exec)

    Returns:
        (is_valid, error_message)
    """
    # 1. Syntaxe
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, _err(ERR_AST, f"Erreur de syntaxe ligne {e.lineno}: {e.msg}")

    # 1b. Sécurité sandbox prioritaire
    dangerous_patterns = [
        "os.system", "subprocess", "eval(", "exec(",
        "__import__", "shutil.rmtree", "open(",
    ]
    code_lower = code.lower()
    for pattern in dangerous_patterns:
        if pattern.lower() in code_lower:
            return False, _err(ERR_SANDBOX, f"Import/appel dangereux détecté: '{pattern}'")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _is_allowed_import(alias.name):
                    return False, _err(
                        ERR_SANDBOX,
                        f"Import interdit en sandbox: '{alias.name}'.",
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if not _is_allowed_import(mod):
                return False, _err(
                    ERR_SANDBOX,
                    f"Import interdit en sandbox: 'from {mod} import ...'.",
                )

    # 2. Vérifier la classe attendue
    class_names = [
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    ]
    if GENERATED_CLASS_NAME not in class_names:
        return False, _err(
            ERR_CLASS,
            f"Classe '{GENERATED_CLASS_NAME}' absente. Classes trouvées: {class_names}",
        )

    # 3. Vérifier generate_signals (dans la classe attendue)
    generate_fns = _iter_generate_signals_functions(tree)
    if not generate_fns:
        return False, _err(ERR_CLASS, "Méthode 'generate_signals' absente.")

    # 3a. Héritage strict StrategyBase (après vérif structure minimale)
    class_node = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == GENERATED_CLASS_NAME
        ),
        None,
    )
    if class_node is not None:
        base_names = {
            getattr(base, "id", None)
            for base in class_node.bases
            if isinstance(base, ast.Name)
        }
        base_names.update(
            getattr(base, "attr", None)
            for base in class_node.bases
            if isinstance(base, ast.Attribute)
        )
        if "StrategyBase" not in base_names:
            return False, _err(
                ERR_CLASS,
                "La classe générée doit hériter explicitement de StrategyBase.",
            )

    # 3b. Signature minimale (évite TypeError runtime)
    fn = generate_fns[0]
    if len(fn.args.args) < 4 and fn.args.vararg is None:
        return (
            False,
            _err(
                ERR_CLASS,
                "Signature invalide: generate_signals doit accepter "
                "(self, df, indicators, params).",
            ),
        )

    # 3c. default_params doit retourner un dict concret (pas une variable globale implicite)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != GENERATED_CLASS_NAME:
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name != "default_params":
                continue
            arg_names = {a.arg for a in item.args.args}
            arg_names.update(a.arg for a in item.args.kwonlyargs)
            _, store_names = _collect_name_load_store_sets(item)
            for sub in ast.walk(item):
                if not isinstance(sub, ast.Return):
                    continue
                if isinstance(sub.value, ast.Name):
                    name_id = sub.value.id
                    if name_id not in arg_names and name_id not in store_names:
                        return (
                            False,
                            _err(
                                ERR_PARAM,
                                "default_params invalide: `return "
                                f"{name_id}` référence un nom non défini. "
                                "Retourner un dict explicite (ex: {'leverage': 1, ...}) "
                                "ou un attribut `self.<...>`."
                            ),
                        )
        break

    # 3d. NameError probable: variables coeur utilisées sans définition
    #     (fréquent quand le LLM renomme l'argument `df` mais garde `df[...]` dans le corps)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != GENERATED_CLASS_NAME:
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            arg_names = {a.arg for a in item.args.args}
            arg_names.update(a.arg for a in item.args.kwonlyargs)
            load_names, store_names = _collect_name_load_store_sets(item)
            core_names = ("df", "indicators", "params")
            if item.name == "generate_signals":
                core_names = ("df", "indicators", "params", "warmup")
            for core in core_names:
                if core in load_names and core not in arg_names and core not in store_names:
                    return (
                        False,
                        _err(
                            ERR_CLASS,
                            f"NameError probable: `{core}` utilisé dans `{item.name}` "
                            "mais non défini (paramètre manquant ou variable non assignée).",
                        ),
                    )
        break

    # 3f. Verrouillage required_indicators: lecture seule (pas d'assignation)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr == "required_indicators"
            ):
                return False, _err(
                    ERR_CLASS,
                    "required_indicators est en lecture seule: assignation interdite.",
                )

    # 3f-bis. Éviter l'écrasement des aliases d'import numpy/pandas.
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != GENERATED_CLASS_NAME:
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(item):
                if isinstance(sub, ast.Assign):
                    targets = sub.targets
                elif isinstance(sub, ast.AnnAssign):
                    targets = [sub.target]
                elif isinstance(sub, ast.AugAssign):
                    targets = [sub.target]
                else:
                    continue
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {"np", "pd"}:
                        return False, _err(
                            ERR_CLASS,
                            f"Alias réservé `{target.id}` écrasé dans `{item.name}`. "
                            f"Ne jamais réassigner `{target.id}`.",
                        )
        break

    # 3g. Écriture df limitée aux colonnes SL/TP autorisées
    ohlcv_cols = {"open", "high", "low", "close", "volume"}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            continue
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        else:
            targets = [node.target]
        for target in targets:
            if not isinstance(target, ast.Subscript):
                continue
            is_df = isinstance(target.value, ast.Name) and target.value.id == "df"
            is_df_loc = (
                isinstance(target.value, ast.Attribute)
                and target.value.attr == "loc"
                and isinstance(target.value.value, ast.Name)
                and target.value.value.id == "df"
            )
            if not (is_df or is_df_loc):
                continue
            col = _const_value(target.slice)
            if col is None and is_df_loc and isinstance(target.slice, ast.Tuple):
                items = list(target.slice.elts)
                if len(items) >= 2:
                    col = _const_value(items[1])
            if not isinstance(col, str):
                continue
            low = col.lower()
            if low in ohlcv_cols:
                return False, _err(
                    ERR_IND,
                    f"Écriture interdite dans df['{col}'] (OHLCV read-only).",
                )
            if col not in _BUILDER_ALLOWED_WRITE_DF_COLUMNS:
                hint = ""
                if "signal" in col.lower():
                    hint = " Use the `signals` variable instead of df columns for signal values."
                return False, _err(
                    ERR_IND,
                    f"Écriture df['{col}'] non autorisée. Colonnes autorisées: "
                    f"{', '.join(sorted(_BUILDER_ALLOWED_WRITE_DF_COLUMNS))}."
                    f"{hint}",
                )

    # 3e. Interdictions structurées signaux/warmup
    flow_ok, flow_err = _validate_signal_loop_and_warmup(tree)
    if not flow_ok:
        return False, flow_err

    # 4. Imports dangereux
    # 5. Accès invalide aux indicateurs via df[...] au lieu de indicators[...]
    try:
        known_indicators = {ind.lower() for ind in list_indicators()}
    except Exception:
        known_indicators = set()

    # 5b. Indicateurs inconnus via indicators[...] / indicators.get(...)
    used_indicators = _collect_indicator_names(tree) | _collect_indicator_names_in_class(tree)
    if known_indicators and used_indicators:
        unknown = sorted(
            {
                name for name in used_indicators
                if name.lower() not in known_indicators
            }
        )
        if unknown:
            ohlcv_and_runtime_cols = {
                "open", "high", "low", "close", "volume",
                *_BUILDER_ALLOWED_WRITE_DF_COLUMNS,
            }
            wrong_df_cols = [name for name in unknown if name.lower() in ohlcv_and_runtime_cols]
            if wrong_df_cols:
                return (
                    False,
                    _err(
                        ERR_IND,
                        "Colonnes de prix/runtime utilisées via `indicators[...]`: "
                        f"{wrong_df_cols}. Utiliser `df['colonne']` pour OHLCV/SL-TP.",
                    ),
                )
            hints = [
                f"{name} -> {_INDICATOR_ALIAS_HINTS[name.lower()]}"
                for name in unknown
                if name.lower() in _INDICATOR_ALIAS_HINTS
            ]
            hint_suffix = (
                f" Corrections possibles: {', '.join(hints)}."
                if hints
                else ""
            )
            return (
                False,
                "Indicateur(s) inconnu(s) via indicators détecté(s): "
                f"{unknown}. Utiliser uniquement les noms du registre."
                f"{hint_suffix}",
            )

    df_indexed = re.findall(r"df\s*\[\s*['\"]([^'\"]+)['\"]\s*\]", code)
    bad_df_cols = sorted(
        {col for col in df_indexed if col.lower() in known_indicators}
    )
    if bad_df_cols:
        return (
            False,
            _err(
                ERR_IND,
                "Accès indicateur invalide via df[...] détecté: "
                f"{bad_df_cols}. Utiliser indicators['name'].",
            ),
        )

    # 6. Mauvais usage de np.nan_to_num sur indicateurs dict (bollinger, macd, ...)
    for ind in _DICT_INDICATOR_NAMES:
        bad_pattern = (
            r"np\.nan_to_num\(\s*indicators\s*\[\s*['\"]"
            + re.escape(ind)
            + r"['\"]\s*\]\s*\)"
        )
        if re.search(bad_pattern, code):
            return (
                False,
                _err(
                    ERR_IND,
                    f"Usage invalide: np.nan_to_num(indicators['{ind}']) (dict). "
                    "Appliquer np.nan_to_num sur ses sous-clés.",
                ),
            )

    # 7. Validation sémantique AST (usage indicateurs/arrays)
    semantics_ok, semantics_err = _validate_indicator_usage_semantics(code)
    if not semantics_ok:
        return False, _err(ERR_IND, semantics_err)

    # 8. Validation légère ParameterSpec: rejeter aliases/typos source de dérive
    forbidden_paramspec_keys = (
        "min_value=",
        "max_value=",
        "minimum=",
        "maximum=",
        "paramtype=",
    )
    for key in forbidden_paramspec_keys:
        if key in code_lower:
            return False, _err(
                ERR_PARAM,
                "ParameterSpec invalide: utiliser min_val/max_val/param_type/step.",
            )

    return True, ""


# ---------------------------------------------------------------------------
# Section 3: Text sanitization
# ---------------------------------------------------------------------------


def sanitize_objective_text(objective: Any) -> str:
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
        if line.startswith("\u2771"):
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
    cleaned = cleaned.strip("`'\" \n\t")
    if len(cleaned) > 4000:
        cleaned = cleaned[:4000].rstrip()
    return cleaned


def _normalize_llm_text(value: Any, *, fallback: str = "", max_len: int = 1200) -> str:
    """Normalise un payload LLM potentiellement structuré en texte affichable."""
    text = ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list, tuple, set)):
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
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
    """
    Formate une exception sans passer par traceback.format_exc/format_exception.

    Évite les crashs secondaires Python 3.12 quand le moteur de suggestion
    d'erreur évalue des propriétés qui relèvent elles-mêmes des exceptions.
    """
    try:
        tb = exc.__traceback__
    except Exception:
        tb = None

    lines: List[str] = []
    if tb is not None:
        try:
            for frame in traceback.extract_tb(tb):
                code_line = (frame.line or "").strip()
                lines.append(
                    f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}'
                )
                if code_line:
                    lines.append(f"    {code_line}")
        except Exception:
            lines = []

    header = f"{type(exc).__name__}: {exc}"
    if lines:
        return (
            "Traceback (most recent call last):\n"
            + "\n".join(lines)
            + f"\n{header}"
        )
    return header


# ---------------------------------------------------------------------------
# Section 4: AST helpers
# ---------------------------------------------------------------------------


def _const_value(node: ast.AST) -> Any:
    """Extrait une valeur constante AST (str/int/float) si possible."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Str):  # pragma: no cover - compat py<3.8
        return node.s
    return None


def _indicator_name_from_subscript(node: ast.AST) -> Optional[str]:
    """Retourne le nom d'indicateur pour indicators['name']."""
    if not isinstance(node, ast.Subscript):
        return None
    if not isinstance(node.value, ast.Name) or node.value.id != "indicators":
        return None
    key = _const_value(node.slice)
    if isinstance(key, str):
        return key
    return None


def _indicator_name_from_get_call(node: ast.AST) -> Optional[str]:
    """Retourne le nom d'indicateur pour indicators.get('name', ...)."""
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "get":
        return None
    if not isinstance(node.func.value, ast.Name) or node.func.value.id != "indicators":
        return None
    if not node.args:
        return None
    key = _const_value(node.args[0])
    if isinstance(key, str):
        return key
    return None


def _is_np_nan_to_num_call(node: ast.AST) -> bool:
    """Vérifie si le noeud est un appel np.nan_to_num(...)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "np"
        and node.func.attr == "nan_to_num"
    )


def _is_params_get_call(node: ast.AST) -> bool:
    """Vérifie si le noeud est un appel params.get(...)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "params"
        and node.func.attr == "get"
    )


def _is_params_subscript(node: ast.AST) -> bool:
    """Vérifie si le noeud est params['x']."""
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "params"
    )


def _is_scalar_cast_call(node: ast.AST) -> bool:
    """Vérifie si le noeud est un cast scalaire (float/int/bool)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"float", "int", "bool"}
    )


def _is_numeric_nonbool_constant(node: ast.AST) -> bool:
    """True si le noeud est une constante numérique non-bool."""
    if not isinstance(node, ast.Constant):
        return False
    return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def _iter_generate_signals_functions(tree: ast.AST) -> List[ast.FunctionDef]:
    """Extrait les méthodes generate_signals de BuilderGeneratedStrategy."""
    out: List[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == GENERATED_CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "generate_signals":
                    out.append(item)
    return out


def _iter_child_nodes_excluding_nested_scopes(node: ast.AST) -> Any:
    """Itère récursivement sur les noeuds en excluant les scopes imbriqués.

    Objectif: analyser les Name Load/Store d'une méthode sans descendre dans
    des `def`/`class` internes (closures), qui ont leurs propres variables.
    """
    stack = list(ast.iter_child_nodes(node))
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(cur))


def _collect_name_load_store_sets(fn: ast.AST) -> tuple[set[str], set[str]]:
    """Collecte les noms utilisés (Load) et assignés (Store/Del) dans un noeud.

    Ne descend pas dans les scopes imbriqués (closures) pour éviter les faux
    positifs sur les variables capturées.
    """
    load: set[str] = set()
    store: set[str] = set()
    for node in _iter_child_nodes_excluding_nested_scopes(fn):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                load.add(node.id)
            elif isinstance(node.ctx, (ast.Store, ast.Del)):
                store.add(node.id)
    return load, store


def _collect_indicator_names(tree: ast.AST) -> set[str]:
    """Collecte les noms d'indicateurs référencés dans generate_signals."""
    names: set[str] = set()
    for fn in _iter_generate_signals_functions(tree):
        for node in ast.walk(fn):
            sub = _indicator_name_from_subscript(node)
            if sub:
                names.add(sub)
            got = _indicator_name_from_get_call(node)
            if got:
                names.add(got)
    return names


def _collect_indicator_names_in_class(tree: ast.AST) -> set[str]:
    """Collecte les indicateurs référencés dans toute la classe générée."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != GENERATED_CLASS_NAME:
            continue
        for sub in ast.walk(node):
            sub_name = _indicator_name_from_subscript(sub)
            if sub_name:
                names.add(sub_name)
            get_name = _indicator_name_from_get_call(sub)
            if get_name:
                names.add(get_name)
        break
    return names


def _dict_indicator_key_is_valid(indicator_name: str, key: Any) -> bool:
    """Valide une sous-clé pour un indicateur dict connu."""
    if not isinstance(key, str):
        return True
    name = indicator_name.lower()
    allowed = _DICT_INDICATOR_ALLOWED_KEYS.get(name)
    if not allowed:
        return True
    if key in allowed:
        return True
    if name in {"fibonacci", "fibonacci_levels"} and key.startswith("level_"):
        return True
    return False


def _dict_indicator_allowed_keys_hint(indicator_name: str) -> str:
    """Construit un hint compact des sous-clés valides."""
    name = indicator_name.lower()
    allowed = sorted(_DICT_INDICATOR_ALLOWED_KEYS.get(name, set()))
    if name in {"fibonacci", "fibonacci_levels"}:
        allowed = [*allowed, "level_XXX"]
    if not allowed:
        return "sous-clés string attendues"
    return ", ".join(allowed)


# ---------------------------------------------------------------------------
# Section 5: Indicator semantics validation
# ---------------------------------------------------------------------------


def _validate_indicator_usage_semantics(code: str) -> tuple[bool, str]:
    """Validation AST des usages indicateurs pour éviter erreurs runtime récurrentes."""
    try:
        tree = ast.parse(code)
    except Exception:
        return True, ""

    # var_name -> {"kind": "array|dict|values", "indicator": Optional[str]}
    bindings: Dict[str, Dict[str, Any]] = {}

    for fn in _iter_generate_signals_functions(tree):
        # Pass 1: collect bindings
        for node in ast.walk(fn):
            targets: List[ast.Name] = []
            value: Optional[ast.AST] = None

            if isinstance(node, ast.Assign):
                value = node.value
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        targets.append(t)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                value = node.value
                targets.append(node.target)
            else:
                continue

            if value is None or not targets:
                continue

            ind_name = _indicator_name_from_subscript(value)
            kind: Optional[str] = None
            if ind_name is not None:
                kind = "dict" if ind_name.lower() in _DICT_INDICATOR_NAMES else "array"
            elif _is_np_nan_to_num_call(value) and getattr(value, "args", None):
                arg0 = value.args[0]
                ind_name = _indicator_name_from_subscript(arg0)
                if ind_name is not None:
                    if ind_name.lower() in _DICT_INDICATOR_NAMES:
                        return (
                            False,
                            f"Usage invalide: np.nan_to_num(indicators['{ind_name}']) "
                            "(indicator dict).",
                        )
                    kind = "array"
                elif isinstance(arg0, ast.Name) and arg0.id in bindings:
                    if bindings[arg0.id]["kind"] == "dict":
                        return (
                            False,
                            f"Usage invalide: np.nan_to_num({arg0.id}) alors que "
                            f"{arg0.id} est un indicator dict.",
                        )
                    kind = "array"
            elif isinstance(value, ast.Attribute) and value.attr == "values":
                kind = "values"
            elif _is_params_get_call(value) or _is_params_subscript(value):
                kind = "scalar"
            elif _is_scalar_cast_call(value) and getattr(value, "args", None):
                arg0 = value.args[0]
                if _is_params_get_call(arg0) or _is_params_subscript(arg0):
                    kind = "scalar"
                elif isinstance(arg0, ast.Name):
                    b = bindings.get(arg0.id)
                    if b and b["kind"] == "scalar":
                        kind = "scalar"

            if kind is not None:
                for t in targets:
                    bindings[t.id] = {"kind": kind, "indicator": ind_name}

        # Pass 2: detect invalid usage
        for node in ast.walk(fn):
            # ndarray.shift(...) / ndarray.rolling(...)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if isinstance(node.func.value, ast.Name):
                    var = node.func.value.id
                    b = bindings.get(var)
                    if b and b["kind"] == "dict" and attr not in {"get"}:
                        return (
                            False,
                            f"Usage invalide: `{var}.{attr}(...)` alors que `{var}` est "
                            "un indicator dict. Extraire une sous-clé puis travailler "
                            "sur le ndarray correspondant.",
                        )
                if (
                    attr in {"shift", "rolling", "ewm"}
                    and isinstance(node.func.value, ast.Name)
                ):
                    var = node.func.value.id
                    b = bindings.get(var)
                    if b and b["kind"] in {"array", "values"}:
                        return (
                            False,
                            f"Usage invalide: {var}.{attr}(...) sur ndarray. "
                            "Utiliser pandas Series ou logique vectorisée numpy.",
                        )
                if attr in {"shift", "rolling", "ewm"}:
                    ind_name = _indicator_name_from_subscript(node.func.value)
                    if ind_name:
                        return (
                            False,
                            f"Usage invalide: indicators['{ind_name}'].{attr}(...) "
                            "sur ndarray. Utiliser une logique numpy.",
                        )

                # np.nan_to_num(var_dict)
                if _is_np_nan_to_num_call(node) and getattr(node, "args", None):
                    arg0 = node.args[0]
                    if isinstance(arg0, ast.Name):
                        b = bindings.get(arg0.id)
                        if b and b["kind"] == "dict":
                            return (
                                False,
                                f"Usage invalide: np.nan_to_num({arg0.id}) alors que "
                                f"{arg0.id} est un indicator dict.",
                            )

            # .iloc/.loc/.iat/.at sur indicateurs ndarray/dict
            if isinstance(node, ast.Attribute) and node.attr in {"iloc", "loc", "iat", "at"}:
                if isinstance(node.value, ast.Name):
                    var = node.value.id
                    b = bindings.get(var)
                    if b and b["kind"] in {"array", "values", "dict"}:
                        return (
                            False,
                            f"Usage invalide: {var}.{node.attr} sur indicateur "
                            "numpy/dict. Utiliser indexation numpy (`arr[i]`).",
                        )
                ind_name = _indicator_name_from_subscript(node.value)
                if ind_name:
                    return (
                        False,
                        f"Usage invalide: indicators['{ind_name}'].{node.attr} "
                        "n'est pas supporté. Utiliser indexation numpy (`arr[i]`).",
                    )

            # Subscript checks: multi-dim on 1D arrays, numeric key on dict indicators
            if isinstance(node, ast.Subscript):
                if isinstance(node.value, ast.Name):
                    var = node.value.id
                    b = bindings.get(var)
                    if b:
                        key = _const_value(node.slice)
                        if b["kind"] in {"array", "values"} and isinstance(node.slice, ast.Tuple):
                            return (
                                False,
                                f"Usage invalide: indexation multi-dim `{var}[..., ...]` "
                                "sur indicateur 1D.",
                            )
                        if b["kind"] in {"array", "values"} and isinstance(key, str):
                            return (
                                False,
                                f"Usage invalide: clé string `{var}['{key}']` sur "
                                "indicateur ndarray. Utiliser directement l'array.",
                            )
                        if b["kind"] == "dict" and isinstance(key, (int, float)):
                            return (
                                False,
                                f"Usage invalide: clé numérique `{var}[{key}]` sur "
                                "indicator dict; utiliser des sous-clés string.",
                            )
                        if b["kind"] == "dict" and isinstance(key, str):
                            ind = str(b.get("indicator") or "")
                            if ind and not _dict_indicator_key_is_valid(ind, key):
                                hint = _dict_indicator_allowed_keys_hint(ind)
                                return (
                                    False,
                                    f"Usage invalide: `{var}['{key}']` pour "
                                    f"indicateur dict '{ind}'. Sous-clés valides: {hint}.",
                                )

                # indicators['bollinger'][50] / indicators['ema']['ema_21']
                ind_name = _indicator_name_from_subscript(node.value)
                if ind_name:
                    key = _const_value(node.slice)
                    if ind_name.lower() in _DICT_INDICATOR_NAMES:
                        if isinstance(key, (int, float)):
                            return (
                                False,
                                f"Usage invalide: indicators['{ind_name}'][{key}] — "
                                "utiliser des sous-clés string.",
                            )
                        if isinstance(key, str) and not _dict_indicator_key_is_valid(ind_name, key):
                            hint = _dict_indicator_allowed_keys_hint(ind_name)
                            return (
                                False,
                                f"Usage invalide: indicators['{ind_name}']['{key}'] — "
                                f"sous-clé inconnue. Sous-clés valides: {hint}.",
                            )
                    elif isinstance(key, str):
                        return (
                            False,
                            f"Usage invalide: indicators['{ind_name}']['{key}'] — "
                            f"'{ind_name}' retourne un ndarray, pas un dict.",
                        )
                get_name = _indicator_name_from_get_call(node.value)
                if get_name:
                    key = _const_value(node.slice)
                    if get_name.lower() in _DICT_INDICATOR_NAMES:
                        if isinstance(key, (int, float)):
                            return (
                                False,
                                f"Usage invalide: indicators.get('{get_name}')[{key}] — "
                                "utiliser des sous-clés string.",
                            )
                        if isinstance(key, str) and not _dict_indicator_key_is_valid(get_name, key):
                            hint = _dict_indicator_allowed_keys_hint(get_name)
                            return (
                                False,
                                f"Usage invalide: indicators.get('{get_name}')['{key}'] — "
                                f"sous-clé inconnue. Sous-clés valides: {hint}.",
                            )
                    elif isinstance(key, str):
                        return (
                            False,
                            f"Usage invalide: indicators.get('{get_name}')['{key}'] — "
                            f"'{get_name}' retourne un ndarray, pas un dict.",
                        )

            # Comparaisons/arithmétiques directes sur dict indicators
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                for operand in operands:
                    if isinstance(operand, ast.Name):
                        var = operand.id
                        b = bindings.get(var)
                        if b and b["kind"] == "dict":
                            hint_key = _dict_indicator_allowed_keys_hint(
                                str(b.get("indicator") or var)
                            ).split(",")[0].strip()
                            return (
                                False,
                                f"Usage invalide: comparaison `{var} ...` alors que "
                                f"`{var}` est un indicator dict. Utiliser une sous-clé "
                                f"(ex: {var}['{hint_key}']).",
                            )

            if isinstance(node, ast.BinOp):
                for operand in (node.left, node.right):
                    if isinstance(operand, ast.Name):
                        var = operand.id
                        b = bindings.get(var)
                        if b and b["kind"] == "dict":
                            hint_key = _dict_indicator_allowed_keys_hint(
                                str(b.get("indicator") or var)
                            ).split(",")[0].strip()
                            return (
                                False,
                                f"Usage invalide: opération arithmétique sur `{var}` "
                                "qui est un indicator dict. Utiliser une sous-clé "
                                f"(ex: {var}['{hint_key}']).",
                            )

                if isinstance(node.op, (ast.BitAnd, ast.BitOr, ast.BitXor)):
                    for operand in (node.left, node.right):
                        if isinstance(operand, ast.Name):
                            b = bindings.get(operand.id)
                            if b and b["kind"] == "scalar":
                                return (
                                    False,
                                    f"Usage invalide: opérateur logique bitwise avec "
                                    f"scalaire `{operand.id}`. Comparer d'abord la valeur "
                                    "scalaire (ex: `arr > threshold`) puis combiner les masques.",
                                )
                        if _is_numeric_nonbool_constant(operand):
                            return (
                                False,
                                "Usage invalide: opérateur logique bitwise avec constante "
                                "numérique. Utiliser des comparaisons booléennes de part et d'autre.",
                            )

            if isinstance(node, ast.BoolOp):
                for operand in node.values:
                    if isinstance(operand, ast.Name):
                        var = operand.id
                        b = bindings.get(var)
                        if b and b["kind"] == "dict":
                            hint_key = _dict_indicator_allowed_keys_hint(
                                str(b.get("indicator") or var)
                            ).split(",")[0].strip()
                            return (
                                False,
                                f"Usage invalide: test booléen direct sur `{var}` "
                                "qui est un indicator dict. Utiliser une sous-clé "
                                f"(ex: {var}['{hint_key}']).",
                            )

            if isinstance(node, (ast.If, ast.While)) and isinstance(node.test, ast.Name):
                var = node.test.id
                b = bindings.get(var)
                if b and b["kind"] == "dict":
                    hint_key = _dict_indicator_allowed_keys_hint(
                        str(b.get("indicator") or var)
                    ).split(",")[0].strip()
                    return (
                        False,
                        f"Usage invalide: condition `{var}` alors que `{var}` est un "
                        f"indicator dict. Utiliser une sous-clé (ex: {var}['{hint_key}']).",
                    )

    return True, ""


# ---------------------------------------------------------------------------
# Section 6: Extraction and dataset validation
# ---------------------------------------------------------------------------


def _extract_json_from_response(text: str) -> Dict[str, Any]:
    """Extrait un bloc JSON depuis une réponse LLM (gère ```json ... ```, <think>, etc.)."""
    def _parse_json_dict(payload: str) -> Dict[str, Any]:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    # Nettoyer les tags <think> des modèles de raisonnement (qwen3, deepseek-r1, alia, etc.)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    text = text.strip()

    if not text:
        logger.warning("extract_json: réponse vide après nettoyage des tags <think>")
        return {}

    # Chercher bloc ```json ... ```
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        parsed = _parse_json_dict(match.group(1).strip())
        if parsed:
            return parsed

    # Essayer le texte brut
    parsed = _parse_json_dict(text.strip())
    if parsed:
        return parsed

    # Chercher premier { ... } englobant
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        parsed = _parse_json_dict(brace_match.group(0))
        if parsed:
            return parsed

    logger.warning(
        "extract_json: aucun JSON valide trouvé. Début réponse: %.200s",
        text[:200],
    )
    return {}


def _extract_python_from_response(text: str) -> str:
    """Extrait un bloc Python depuis une réponse LLM."""
    # Nettoyer les tags <think> des modèles de raisonnement
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    text = text.strip()
    match = re.search(r"```(?:python)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback : le texte entier
    return text.strip()


def _timeframe_to_timedelta(timeframe: str) -> Optional[pd.Timedelta]:
    """Convertit un timeframe texte en timedelta."""
    tf = str(timeframe or "").strip()
    match = re.match(r"^(\d+)([mhdwM])$", tf)
    if not match:
        return None
    n = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return pd.Timedelta(minutes=n)
    if unit == "h":
        return pd.Timedelta(hours=n)
    if unit == "d":
        return pd.Timedelta(days=n)
    if unit == "w":
        return pd.Timedelta(weeks=n)
    if unit == "M":
        return pd.Timedelta(days=30 * n)
    return None


def _max_contiguous_segment_bars(df: pd.DataFrame, timeframe: str) -> int:
    """Retourne la taille max d'un segment continu hors gaps majeurs."""
    if df.empty:
        return 0
    expected = _timeframe_to_timedelta(timeframe)
    if expected is None:
        return len(df)
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex) or len(idx) <= 1:
        return len(df)
    diffs = idx[1:] - idx[:-1]
    major_gap = diffs > (expected * 3)
    if not np.any(major_gap):
        return len(df)
    cut_positions = np.where(major_gap)[0]
    starts = [0, *[int(pos) + 1 for pos in cut_positions]]
    ends = [*[int(pos) + 1 for pos in cut_positions], len(df)]
    lengths = [end - start for start, end in zip(starts, ends)]
    return max(lengths) if lengths else len(df)


def _validate_builder_dataset_exploitability(
    data: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
) -> tuple[bool, str]:
    """Valide que le dataset/timeframe est exploitable pour le Builder."""
    n_bars = int(len(data))
    if n_bars < MIN_BUILDER_BARS:
        return (
            False,
            (
                f"Dataset insuffisant pour Builder: {n_bars} barres (< {MIN_BUILDER_BARS}) "
                f"sur {symbol}/{timeframe}."
            ),
        )

    if symbol and symbol != "UNKNOWN":
        try:
            from data.config import find_optimal_periods

            periods = find_optimal_periods([symbol], [timeframe], min_period_days=30, max_periods=1)
            if not periods:
                return (
                    False,
                    (
                        "Aucun segment exploitable sans gaps majeurs détecté "
                        f"par data.config pour {symbol}/{timeframe}."
                    ),
                )
        except Exception as exc:
            logger.warning(
                "builder_dataset_quality_check_fallback symbol=%s timeframe=%s error=%s",
                symbol,
                timeframe,
                exc,
            )

    max_segment = _max_contiguous_segment_bars(data, timeframe)
    if max_segment < MIN_BUILDER_BARS:
        return (
            False,
            (
                "Aucun segment continu exploitable détecté: "
                f"segment max={max_segment} barres (< {MIN_BUILDER_BARS}) sur {symbol}/{timeframe}."
            ),
        )

    return True, ""
