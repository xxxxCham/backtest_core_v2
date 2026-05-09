"""
Module-ID: agents.builder_ast_utils

Purpose: Utilitaires AST et parsing LLM extraits de strategy_builder.

Role in pipeline: Inspection, traversée et extraction de code Python/JSON
depuis des réponses LLM et du code généré.

Skip-if: Vous n'utilisez pas le Strategy Builder.
"""

from __future__ import annotations

import ast
import json
import logging
import re
import textwrap
from typing import Any, Dict, List, Optional

from agents.builder_constants import (
    _AST_PARSE_RECOVERABLE_EXCEPTIONS,
    GENERATED_CLASS_NAME,
)

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Regex patterns pour le nettoyage des réponses LLM
# -------------------------------------------------------------------
_LOG_PREFIX_RE = re.compile(r"^\s*\d{2}:\d{2}:\d{2}\s*\|\s*\w+\s*\|", re.IGNORECASE)
_PIPE_LOG_PREFIX_RE = re.compile(
    r"^\s*\|\s*(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*\|",
    re.IGNORECASE,
)
_TRACEBACK_LINE_RE = re.compile(r'^\s*File\s+"[^"]+",\s*line\s+\d+', re.IGNORECASE)
_WINDOWS_PATH_LINE_RE = re.compile(r"^\s*[A-Za-z]:\\")
_PYTHONISH_LINE_RE = re.compile(
    r"^\s*(from\s+|import\s+|class\s+|def\s+|@|if\s+|elif\s+|else\s*:|for\s+|while\s+|try\s*:|except\b|finally\s*:|return\b|signals\b|[A-Za-z_][A-Za-z0-9_]*\s*=)",
    re.IGNORECASE,
)
_NATURAL_LANGUAGE_LINE_RE = re.compile(
    r"^\s*("
    # --- FR ---
    r"voici|voici le code|voici la version|code corrig[ée]|code modifi[ée]|"
    r"corrig[ée]|correction|ci-dessous|ci-dessus|modifi[ée]|changement|ajout|"
    r"suggestion|proposition|en r[ée]sum[ée]|en bref|"
    r"explication|remarque|analyse|analysis|r[ée]sum[ée]|strat[ée]gie|"
    # --- EN ---
    r"here(?:'s|\s+is)?|sure|corrected code|explanation|note|strategy|"
    # --- EN reasoning-chain (real archives) ---
    r"the user|i need to|so perhaps|i should|but in the|"
    r"wait[,.]?\s*(?:no|maybe)|let me (?:think|start)|okay[,.]?\s*i|"
    r"looking (?:back|at)|first[,.]?\s*(?:the|i)|now[,.]?\s*(?:the|i|let)|"
    r"next[,.]?\s*(?:the|i)|additionally|these are just|"
    r"perhaps also|note that this|the (?:strategy|focus)|so the required|"
    r"so maybe i should|so in the|for example[,.]?\s*if|"
    r"but let me|i have included|i don'?t see|"
    r"from the problem|the (?:required|sample|above)|in the (?:sample|example)|"
    r"so required|so maybe|the focus is"
    r")\b",
    re.IGNORECASE,
)


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
    return isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "params"


def _is_scalar_cast_call(node: ast.AST) -> bool:
    """Vérifie si le noeud est un cast scalaire (float/int/bool)."""
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"float", "int", "bool"}


def _is_numeric_nonbool_constant(node: ast.AST) -> bool:
    """True si le noeud est une constante numérique non-bool."""
    if not isinstance(node, ast.Constant):
        return False
    return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def _iter_generated_class_methods(tree: ast.AST):
    """Yield each method (FunctionDef/AsyncFunctionDef) in the generated class body."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == GENERATED_CLASS_NAME:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield item
            return


def _iter_generate_signals_functions(tree: ast.AST) -> List[ast.FunctionDef]:
    """Extrait les méthodes generate_signals de BuilderGeneratedStrategy."""
    return [
        m
        for m in _iter_generated_class_methods(tree)
        if isinstance(m, ast.FunctionDef) and m.name == "generate_signals"
    ]


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


def _collect_bound_names(fn: ast.AST) -> set[str]:
    """Collecte les noms localement définis dans une fonction/méthode."""
    bound: set[str] = set()

    args = getattr(getattr(fn, "args", None), "args", []) or []
    bound.update(arg.arg for arg in args if getattr(arg, "arg", None))
    kwonlyargs = getattr(getattr(fn, "args", None), "kwonlyargs", []) or []
    bound.update(arg.arg for arg in kwonlyargs if getattr(arg, "arg", None))

    _load_names, store_names = _collect_name_load_store_sets(fn)
    bound.update(store_names)

    for node in ast.walk(fn):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) or (
            isinstance(node, ast.ExceptHandler) and isinstance(node.name, str)
        ):
            bound.add(node.name)
        elif isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])

    return bound


def _collect_module_level_bound_names(tree: ast.AST) -> set[str]:
    """Collecte les noms disponibles au scope module pour éviter les faux NameError."""
    bound: set[str] = set()

    for node in getattr(tree, "body", []) or []:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bound.add(node.target.id)

    return bound


def _normalize_required_indicator_names(required_indicators: Optional[List[str]]) -> List[str]:
    normalized: List[str] = []
    if not required_indicators:
        return normalized
    for item in required_indicators:
        if not isinstance(item, str):
            continue
        indicator_name = item.strip().lower()
        if indicator_name and indicator_name not in normalized:
            normalized.append(indicator_name)
    return normalized


def _indicator_name_from_hint_expression(expr: str) -> Optional[str]:
    """Extrait le nom d'indicateur d'une expression hint."""
    match = re.search(r"indicators\[['\"]([A-Za-z0-9_]+)['\"]\]", str(expr or ""))
    if not match:
        return None
    return str(match.group(1)).strip().lower() or None


def _strip_leading_list_marker(line: str) -> str:
    """Retire `1.`/`-` au début d'une ligne en conservant l'indentation utile."""
    match = re.match(r"^(\s*)(?:[-*]|\d+[\.)])(.*)$", line)
    if not match:
        return line
    leading_ws, remainder = match.groups()
    if remainder.startswith((" ", "\t")):
        remainder = remainder[1:]
    return leading_ws + remainder


def _sanitize_python_list_markers(code: str) -> str:
    """Supprime les marqueurs de liste LLM devant des lignes Python valides."""
    fixed_lines: List[str] = []
    for line in str(code or "").splitlines():
        candidate = _strip_leading_list_marker(line)
        if candidate != line and (_PYTHONISH_LINE_RE.match(candidate.lstrip()) or candidate.lstrip().startswith("#")):
            fixed_lines.append(candidate)
        else:
            fixed_lines.append(line)
    return "\n".join(fixed_lines)


def _drop_obvious_non_python_lines(code: str) -> str:
    """Supprime les lignes manifestement non Python après extraction."""
    kept_lines: List[str] = []
    for line in str(code or "").splitlines():
        stripped = line.strip()
        if not stripped:
            kept_lines.append(line)
            continue
        if stripped.startswith("```") or stripped.lower() == "python":
            continue
        if _NATURAL_LANGUAGE_LINE_RE.match(stripped) and not _PYTHONISH_LINE_RE.match(stripped):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines)


def _balance_brackets_outside_strings(code: str) -> str:
    """Rééquilibre prudemment les parenthèses/crochets/accolades hors chaînes."""
    open_to_close = {"(": ")", "[": "]", "{": "}"}
    closing_to_open = {")": "(", "]": "[", "}": "{"}
    stack: List[str] = []
    output: List[str] = []
    in_single = False
    in_double = False
    escape = False

    for ch in str(code or ""):
        if escape:
            output.append(ch)
            escape = False
            continue
        if ch == "\\":
            output.append(ch)
            escape = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            output.append(ch)
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            output.append(ch)
            continue
        if in_single or in_double:
            output.append(ch)
            continue
        if ch in open_to_close:
            stack.append(ch)
            output.append(ch)
            continue
        if ch in closing_to_open:
            expected_open = closing_to_open[ch]
            if stack and stack[-1] == expected_open:
                stack.pop()
                output.append(ch)
            else:
                continue
            continue
        output.append(ch)

    while stack:
        output.append(open_to_close[stack.pop()])

    return "".join(output)


def _strip_non_python_noise(text: str) -> str:
    """Retire le bruit fréquent des réponses LLM autour du code Python."""
    raw_lines = str(text or "").splitlines()
    cleaned_lines: List[str] = []
    seen_code = False

    for line in raw_lines:
        stripped = line.strip()

        if not stripped:
            if seen_code:
                cleaned_lines.append("")
            continue

        if stripped.startswith("```"):
            continue
        if stripped.lower() == "python":
            continue
        if _LOG_PREFIX_RE.match(line) or _PIPE_LOG_PREFIX_RE.match(line):
            continue
        if _TRACEBACK_LINE_RE.match(line) or _WINDOWS_PATH_LINE_RE.match(line):
            continue

        candidate = _strip_leading_list_marker(line)
        candidate_stripped = candidate.strip()

        if not seen_code:
            if _NATURAL_LANGUAGE_LINE_RE.match(candidate_stripped):
                continue
            if _PYTHONISH_LINE_RE.match(candidate_stripped) or candidate_stripped.startswith("#"):
                seen_code = True
                cleaned_lines.append(candidate)
            continue

        if _NATURAL_LANGUAGE_LINE_RE.match(candidate_stripped) and not _PYTHONISH_LINE_RE.match(candidate_stripped):
            continue
        cleaned_lines.append(candidate)

    if cleaned_lines:
        while cleaned_lines and not cleaned_lines[-1].strip():
            cleaned_lines.pop()
        if cleaned_lines:
            return "\n".join(cleaned_lines)
    return ""


def _extract_json_from_response(text: str) -> Dict[str, Any]:
    """Extrait un bloc JSON depuis une réponse LLM (gère ```json ... ```, <think>, etc.)."""

    def _parse_json_dict(payload: str) -> Dict[str, Any]:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    # Nettoyer les tags <think> des modèles de raisonnement (qwen3, deepseek-r1, gemma4, etc.)
    # Garder le contenu brut en réserve pour salvage si la réponse hors-think est vide.
    raw_text = text
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    text = text.strip()

    if not text:
        # Salvage : tenter d'extraire du JSON depuis l'intérieur des blocs <think>
        think_match = re.search(r"<think>(.*?)(?:</think>|$)", raw_text, re.DOTALL)
        if think_match:
            think_body = think_match.group(1).strip()
            brace = re.search(r"\{.*\}", think_body, re.DOTALL)
            if brace:
                parsed = _parse_json_dict(brace.group(0))
                if parsed:
                    logger.info("extract_json: JSON salvagé depuis un bloc <think>")
                    return parsed
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
    raw_text = text
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    text = text.strip()
    if not text:
        # Salvage : tenter d'extraire du Python depuis l'intérieur des blocs <think>
        think_match = re.search(r"<think>(.*?)(?:</think>|$)", raw_text, re.DOTALL)
        if think_match:
            think_body = think_match.group(1)
            code_match = re.search(r"```(?:python)?\s*\n(.*?)\n```", think_body, re.DOTALL)
            if code_match:
                salvaged = _strip_non_python_noise(code_match.group(1)).strip()
                if salvaged:
                    logger.info("extract_python: code salvagé depuis un bloc <think>")
                    return salvaged
        return ""
    match = re.search(r"```(?:python)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return _strip_non_python_noise(match.group(1)).strip()
    # Fallback : le texte entier
    return _strip_non_python_noise(text).strip()


def _salvage_complex_ast_syntax(code: str) -> str:
    """Tente des réparations syntaxiques conservatrices avant fallback.

    Objectif: corriger le bruit de sortie LLM et les déséquilibres simples qui
    empêchent `ast.parse` de construire l'arbre, sans réécrire la logique métier.
    """
    candidate = _strip_non_python_noise(code)
    candidate = _drop_obvious_non_python_lines(candidate)
    candidate = _sanitize_python_list_markers(candidate)

    attempts = [
        candidate,
        textwrap.dedent(candidate),
        _balance_brackets_outside_strings(candidate),
        _balance_brackets_outside_strings(textwrap.dedent(candidate)),
    ]

    seen: set[str] = set()
    for attempt in attempts:
        attempt = attempt.strip("\n")
        if not attempt or attempt in seen:
            continue
        seen.add(attempt)
        try:
            ast.parse(attempt)
            return attempt
        except SyntaxError:
            continue

    return candidate
def _extract_declared_required_indicators(code: str) -> List[str]:
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "required_indicators":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Return) or not isinstance(stmt.value, ast.List):
                continue
            items: List[str] = []
            for elt in stmt.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    items.append(str(elt.value))
            return _normalize_required_indicator_names(items)
    return []


def _extract_generate_signals_logic_block(code: str) -> str:
    """Extrait le bloc logique de generate_signals depuis une réponse LLM."""
    candidates: List[str] = []
    direct = str(code or "")
    salvaged = _salvage_complex_ast_syntax(direct)
    extracted = _extract_python_from_response(direct)
    for candidate in (direct, salvaged, extracted):
        candidate = str(candidate or "")
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        try:
            tree = ast.parse(candidate)
        except (
            SyntaxError,
            IndentationError,
            ValueError,
            KeyError,
            RuntimeError,
            AttributeError,
            TypeError,
            IndexError,
        ):
            continue

        lines = candidate.splitlines()
        for fn in _iter_generate_signals_functions(tree):
            if not fn.body:
                continue
            start = int(fn.body[0].lineno) - 1
            end = int(getattr(fn.body[-1], "end_lineno", fn.body[-1].lineno))
            block_lines = lines[start:end]
            stripped: List[str] = []
            for line in block_lines:
                s = line.strip()
                if not s:
                    stripped.append(line)
                    continue
                if re.match(r"^(signals|n|warmup)\s*=", s):
                    continue
                if s == "return signals":
                    continue
                stripped.append(line)
            return textwrap.dedent("\n".join(stripped)).strip()
    return ""


def _extract_required_indicators_signature(code: str) -> tuple[str, ...]:
    """Retourne une signature stable des required_indicators depuis le code."""
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return tuple()

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == GENERATED_CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "required_indicators":
                    for stmt in item.body:
                        if isinstance(stmt, ast.Return):
                            try:
                                value = ast.literal_eval(stmt.value)  # type: ignore[arg-type]
                            except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
                                return tuple()
                            if isinstance(value, (list, tuple)):
                                normalized = [str(v) for v in value]
                                return tuple(sorted(normalized))
    return tuple()


def _extract_generate_signals_signature(code: str) -> str:
    """Retourne une signature AST du corps de generate_signals."""
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return ""

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == GENERATED_CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "generate_signals":
                    return ast.dump(
                        ast.Module(body=item.body, type_ignores=[]),
                        include_attributes=False,
                    )
    return ""


def _extract_default_params_signature(code: str) -> Dict[str, Any]:
    """Retourne le dict literal de default_params depuis le code généré."""
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == GENERATED_CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "default_params":
                    for stmt in item.body:
                        if isinstance(stmt, ast.Return):
                            try:
                                value = ast.literal_eval(stmt.value)  # type: ignore[arg-type]
                            except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
                                return {}
                            if isinstance(value, dict):
                                return value
    return {}
