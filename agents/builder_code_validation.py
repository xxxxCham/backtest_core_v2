"""Module-ID: agents.builder_code_validation

Purpose: Builder generated-code validation subsystem.
"""

from __future__ import annotations

import ast
import builtins
import re
from typing import Any

from agents.builder_ast_utils import (
    _collect_bound_names,
    _collect_indicator_names,
    _collect_indicator_names_in_class,
    _collect_module_level_bound_names,
    _collect_name_load_store_sets,
    _const_value,
    _indicator_name_from_get_call,
    _indicator_name_from_subscript,
    _is_np_nan_to_num_call,
    _is_numeric_nonbool_constant,
    _is_params_get_call,
    _is_params_subscript,
    _is_scalar_cast_call,
    _iter_generate_signals_functions,
    _iter_generated_class_methods,
)
from agents.builder_constants import GENERATED_CLASS_NAME
from indicators.registry import list_indicators

ERR_CLASS = "CLASS001"


ERR_AST = "AST001"


ERR_IND = "IND001"


ERR_SIG = "SIG001"


ERR_WARM = "WARM001"


ERR_PARAM = "PARAM001"


ERR_SANDBOX = "SANDBOX001"


_DICT_INDICATOR_NAMES = {
    "bollinger",
    "macd",
    "stochastic",
    "adx",
    "amplitude_hunter",
    "supertrend",
    "ichimoku",
    "psar",
    "vortex",
    "stoch_rsi",
    "aroon",
    "donchian",
    "keltner",
    "pivot_points",
    "fibonacci",
    "fibonacci_levels",
    "fvg",
    "swing",
    "smart_legs",
    "directional_bias",
    "markov_switching",
}


_DICT_INDICATOR_ALLOWED_KEYS: dict[str, set[str]] = {
    "bollinger": {"upper", "middle", "lower"},
    "macd": {"macd", "signal", "histogram"},
    "stochastic": {"stoch_k", "stoch_d"},
    "adx": {"adx", "plus_di", "minus_di"},
    "amplitude_hunter": {"range_pct", "score"},
    "supertrend": {"supertrend", "direction"},
    "ichimoku": {"tenkan", "kijun", "senkou_a", "senkou_b", "chikou", "cloud_position"},
    "psar": {"sar", "trend", "signal"},
    "vortex": {"vi_plus", "vi_minus", "signal", "oscillator"},
    "stoch_rsi": {"k", "d", "signal"},
    "aroon": {"aroon_up", "aroon_down"},
    "donchian": {"upper", "middle", "lower"},
    "keltner": {"middle", "upper", "lower"},
    "pivot_points": {"pivot", "r1", "s1", "r2", "s2", "r3", "s3"},
    "fibonacci_levels": {"high", "low"},
    "fvg": {"fvg_bullish", "fvg_bearish"},
    "swing": {"swing_high", "swing_low"},
    "smart_legs": {"smart_leg_bullish", "smart_leg_bearish"},
    "directional_bias": {"bull_score", "bear_score", "net_bias"},
    "markov_switching": {"regime", "prob_regime_0", "prob_regime_1", "prob_regime_2", "prob_regime_3"},
}


_INDICATOR_ALIAS_HINTS = {
    "bollinger_upper": "indicators['bollinger']['upper']",
    "bollinger_middle": "indicators['bollinger']['middle']",
    "bollinger_lower": "indicators['bollinger']['lower']",
    "upper_bollinger": "indicators['bollinger']['upper']",
    "middle_bollinger": "indicators['bollinger']['middle']",
    "mid_bollinger": "indicators['bollinger']['middle']",
    "lower_bollinger": "indicators['bollinger']['lower']",
    "higher_bollinger": "indicators['bollinger']['upper']",
    "midline_bollinger": "indicators['bollinger']['middle']",
    "bb_upper": "indicators['bollinger']['upper']",
    "bb_middle": "indicators['bollinger']['middle']",
    "bb_lower": "indicators['bollinger']['lower']",
    "bb_mid": "indicators['bollinger']['middle']",
    "bb_std": "indicators['bollinger']['upper']",
    "macd_line": "indicators['macd']['macd']",
    "macd_signal": "indicators['macd']['signal']",
    "macd_histogram": "indicators['macd']['histogram']",
    "keltner_upper": "indicators['keltner']['upper']",
    "keltner_middle": "indicators['keltner']['middle']",
    "keltner_lower": "indicators['keltner']['lower']",
    "kelt_upper": "indicators['keltner']['upper']",
    "kelt_middle": "indicators['keltner']['middle']",
    "kelt_lower": "indicators['keltner']['lower']",
    "donchian_upper": "indicators['donchian']['upper']",
    "donchian_middle": "indicators['donchian']['middle']",
    "donchian_lower": "indicators['donchian']['lower']",
    "dc_upper": "indicators['donchian']['upper']",
    "dc_middle": "indicators['donchian']['middle']",
    "dc_lower": "indicators['donchian']['lower']",
    "cci_value": "indicators['cci']",
    "cci_values": "indicators['cci']",
    "ichimoku_tenkan": "indicators['ichimoku']['tenkan']",
    "ichimoku_kijun": "indicators['ichimoku']['kijun']",
    "ichimoku_senkou_a": "indicators['ichimoku']['senkou_a']",
    "ichimoku_senkou_b": "indicators['ichimoku']['senkou_b']",
    "ichimoku_chikou": "indicators['ichimoku']['chikou']",
    "ichimoku_cloud": "indicators['ichimoku']['cloud_position']",
    "psar_sar": "indicators['psar']['sar']",
    "psar_trend": "indicators['psar']['trend']",
    "psar_signal": "indicators['psar']['signal']",
    "parabolic_sar": "indicators['psar']['sar']",
    "vortex_vi_plus": "indicators['vortex']['vi_plus']",
    "vortex_vi_minus": "indicators['vortex']['vi_minus']",
    "vortex_signal": "indicators['vortex']['signal']",
    "vortex_oscillator": "indicators['vortex']['oscillator']",
    "vi_plus": "indicators['vortex']['vi_plus']",
    "vi_minus": "indicators['vortex']['vi_minus']",
    "aroon_up": "indicators['aroon']['aroon_up']",
    "aroon_down": "indicators['aroon']['aroon_down']",
    "aroon_upper": "indicators['aroon']['aroon_up']",
    "aroon_lower": "indicators['aroon']['aroon_down']",
    "pivot_points_pivot": "indicators['pivot_points']['pivot']",
    "pivot_points_r1": "indicators['pivot_points']['r1']",
    "pivot_points_s1": "indicators['pivot_points']['s1']",
    "pivot_points_r2": "indicators['pivot_points']['r2']",
    "pivot_points_s2": "indicators['pivot_points']['s2']",
    "pivot_points_r3": "indicators['pivot_points']['r3']",
    "pivot_points_s3": "indicators['pivot_points']['s3']",
    "adx_value": "indicators['adx']['adx']",
    "plus_di": "indicators['adx']['plus_di']",
    "minus_di": "indicators['adx']['minus_di']",
    "supertrend_value": "indicators['supertrend']['supertrend']",
    "supertrend_direction": "indicators['supertrend']['direction']",
    "stoch_k": "indicators['stochastic']['stoch_k']",
    "stoch_d": "indicators['stochastic']['stoch_d']",
    "stoch_rsi_k": "indicators['stoch_rsi']['k']",
    "stoch_rsi_d": "indicators['stoch_rsi']['d']",
    "stoch_rsi_signal": "indicators['stoch_rsi']['signal']",
    "srsi_k": "indicators['stoch_rsi']['k']",
    "srsi_d": "indicators['stoch_rsi']['d']",
    "fibonacci_levels_high": "indicators['fibonacci_levels']['high']",
    "fibonacci_levels_low": "indicators['fibonacci_levels']['low']",
}


_BUILDER_ALLOWED_WRITE_DF_COLUMNS = {
    "bb_stop_long",
    "bb_tp_long",
    "bb_stop_short",
    "bb_tp_short",
    "sl_level",
    "tp_level",
}


_AST_PARSE_RECOVERABLE_EXCEPTIONS = (
    SyntaxError,
    ValueError,
    KeyError,
    RuntimeError,
    AttributeError,
    TypeError,
    IndexError,
)


def _err(code: str, message: str) -> str:
    """Formate un message d'erreur avec code stable."""
    return f"[{code}] {message}"


def _is_allowed_import(module_name: str) -> bool:
    """Allowlist stricte des imports dans le code généré."""
    root = (module_name or "").split(".")[0]
    return root in {"typing", "numpy", "pandas", "strategies", "utils"}


def _get_known_indicator_names() -> set[str]:
    """Retourne les noms d'indicateurs du registre, en minuscules."""
    try:
        return {str(ind or "").strip().lower() for ind in list_indicators() if str(ind or "").strip()}
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
        return set(_DICT_INDICATOR_NAMES)


def _extract_required_indicators_from_ast(tree: ast.AST) -> set[str]:
    """Extrait les noms déclarés dans la propriété ``required_indicators``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != GENERATED_CLASS_NAME:
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef):
                continue
            if item.name != "required_indicators":
                continue
            for sub in ast.walk(item):
                if not isinstance(sub, ast.Return):
                    continue
                if isinstance(sub.value, ast.List):
                    return {_const_value(elt) for elt in sub.value.elts if isinstance(_const_value(elt), str)}
    return set()


def _has_warmup_guard(tree: ast.AST) -> bool:
    """Vérifie qu'un warmup ``signals[:N] = 0`` est présent dans generate_signals."""
    for fn in _iter_generate_signals_functions(tree):
        for node in ast.walk(fn):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tgt in targets:
                if not isinstance(tgt, ast.Subscript):
                    continue
                is_signals = isinstance(tgt.value, ast.Name) and tgt.value.id == "signals"
                is_signals_iloc = (
                    isinstance(tgt.value, ast.Attribute)
                    and tgt.value.attr == "iloc"
                    and isinstance(tgt.value.value, ast.Name)
                    and tgt.value.value.id == "signals"
                )
                if not (is_signals or is_signals_iloc):
                    continue
                sl = tgt.slice
                if isinstance(sl, ast.Slice) and sl.lower is None and sl.upper is not None:
                    return True
    return False


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


def _binding_info_for_expr(
    node: ast.AST,
    bindings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Retourne le binding connu pour une expression simple d'indicateur."""
    if isinstance(node, ast.Name):
        return bindings.get(node.id)

    indicator_name = _indicator_name_from_subscript(node)
    if indicator_name is None:
        indicator_name = _indicator_name_from_get_call(node)
    if indicator_name is not None:
        return {
            "kind": "dict" if indicator_name.lower() in _DICT_INDICATOR_NAMES else "array",
            "indicator": indicator_name,
        }

    if _is_np_nan_to_num_call(node) and getattr(node, "args", None):
        parent = _binding_info_for_expr(node.args[0], bindings)
        if parent is None:
            return None
        if parent["kind"] == "dict":
            return {
                "kind": "dict",
                "indicator": parent.get("indicator"),
            }
        return {
            "kind": "array",
            "indicator": parent.get("indicator"),
        }

    return None


def _binding_expr_label(node: ast.AST, binding: dict[str, Any] | None = None) -> str:
    """Construit un libellé court pour les messages d'erreur AST."""
    if isinstance(node, ast.Name):
        return node.id

    indicator_name = ""
    if binding is not None:
        indicator_name = str(binding.get("indicator") or "")
    if not indicator_name:
        indicator_name = _indicator_name_from_subscript(node) or _indicator_name_from_get_call(node) or ""
    if indicator_name:
        return f"indicators['{indicator_name}']"

    return "indicator expression"


def _indicator_access_hint(indicator_name: str) -> str:
    """Retourne le hint d'accès recommandé pour un indicateur donné."""
    name = str(indicator_name or "").strip().lower()
    alias_hint = _INDICATOR_ALIAS_HINTS.get(name)
    if alias_hint:
        return alias_hint
    if name in _DICT_INDICATOR_NAMES:
        keys = sorted(_DICT_INDICATOR_ALLOWED_KEYS.get(name, set()))
        if keys:
            return f"indicators['{name}']['{keys[0]}']"
        return f"indicators['{name}']"
    return f"np.nan_to_num(indicators['{name}'])"


def _validate_signal_loop_and_warmup(tree: ast.AST) -> tuple[bool, str]:
    """Valide des patterns signaux/warmup dangereux.

    Couverture SIG001 complète alignée sur GUIDE_CREATION_NOUVELLE_STRATEGIE.md :
    - Boucles indexées ``for i in range(...)`` / ``signals.iloc[i]``
    - Boucle ``while``
    - Warmup destructif (``signals[N:]``, ``signals[:]``, ``signals[N:M]``)
    - Indexation 2D interdite sur ``signals``
    - Opérateurs scalaires ``and`` / ``or`` sur masques (→ ``&`` / ``|``)
    - ``signals.loc[mask, ...]`` (→ ``signals[mask] = 1.0``)
    - ``signals.notnull()`` / ``signals.isnull()`` (→ ``signals != 0``)
    - ``np.diff`` sans ``np.insert`` (produit un array n-1)
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
                            "Boucle indexée avec `signals.iloc[i]` interdite. Utiliser des masques vectorisés.",
                        )

            # -- SIG001-and/or : opérateurs scalaires ``and``/``or`` ---
            if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
                has_compare = any(isinstance(v, ast.Compare) for v in node.values)
                if has_compare:
                    bad_op = "and" if isinstance(node.op, ast.And) else "or"
                    good_op = "&" if bad_op == "and" else "|"
                    return False, _err(
                        ERR_SIG,
                        f"Opérateur scalaire `{bad_op}` interdit sur masques vectorisés. "
                        f"Utiliser `{good_op}` avec des parenthèses autour de chaque condition.",
                    )

            # -- SIG001-loc : signals.loc[...] (toute forme) ---
            if isinstance(node, ast.Subscript):
                if (
                    isinstance(node.value, ast.Attribute)
                    and node.value.attr == "loc"
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "signals"
                ):
                    return False, _err(
                        ERR_SIG,
                        "Accès `signals.loc[...]` interdit. Utiliser `signals[mask] = 1.0` (masques vectorisés).",
                    )

            # -- SIG001-isnull/notnull ---
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"isnull", "notnull", "isna", "notna"}:
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "signals":
                        return False, _err(
                            ERR_SIG,
                            f"`signals.{node.func.attr}()` interdit. Utiliser `signals != 0` ou `signals == 0`.",
                        )

            # Warmup checks sur assignations
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for tgt in targets:
                    if not isinstance(tgt, ast.Subscript):
                        continue

                    # Pattern signals[...] ou signals.iloc[...]
                    is_signals_sub = isinstance(tgt.value, ast.Name) and tgt.value.id == "signals"
                    is_signals_loc_sub = (
                        isinstance(tgt.value, ast.Attribute)
                        and tgt.value.attr == "loc"
                        and isinstance(tgt.value.value, ast.Name)
                        and tgt.value.value.id == "signals"
                    )
                    is_signals_iloc_sub = (
                        isinstance(tgt.value, ast.Attribute)
                        and tgt.value.attr == "iloc"
                        and isinstance(tgt.value.value, ast.Name)
                        and tgt.value.value.id == "signals"
                    )
                    if not (is_signals_sub or is_signals_loc_sub or is_signals_iloc_sub):
                        continue

                    sl = tgt.slice
                    if isinstance(sl, ast.Tuple):
                        return False, _err(
                            ERR_SIG,
                            "Indexation 2D interdite sur `signals`: cette variable doit "
                            "rester une `pd.Series` 1D. Ne jamais écrire "
                            "`signals.loc[mask, 'long'/'short']`; utiliser "
                            "`signals[long_mask] = 1.0` et `signals[short_mask] = -1.0`.",
                        )
                    if isinstance(sl, ast.Slice):
                        lower = _const_value(sl.lower) if sl.lower is not None else None
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
                    "Boucle `while` interdite dans generate_signals. Utiliser une logique vectorisée.",
                )

    # -- SIG001-diff : np.diff sans np.insert (longueur n-1) ---
    code_text = ast.unparse(tree) if hasattr(ast, "unparse") else ""
    if code_text and "np.diff" in code_text:
        if "np.insert" not in code_text and "np.concatenate" not in code_text:
            return False, _err(
                ERR_SIG,
                "`np.diff()` produit un tableau de longueur n-1. "
                "Utiliser `np.insert(np.diff(arr), 0, 0.0)` pour conserver la même longueur.",
            )

    return True, ""


def _validate_indicator_usage_semantics(code: str) -> tuple[bool, str]:
    """Validation AST des usages indicateurs pour éviter erreurs runtime récurrentes."""
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return True, ""

    # var_name -> {"kind": "array|dict|values", "indicator": Optional[str]}
    bindings: dict[str, dict[str, Any]] = {}

    for fn in _iter_generate_signals_functions(tree):
        # Pass 1: collect bindings
        for node in ast.walk(fn):
            targets: list[ast.Name] = []
            value: ast.AST | None = None

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
            kind: str | None = None
            if ind_name is not None:
                kind = "dict" if ind_name.lower() in _DICT_INDICATOR_NAMES else "array"
            elif _is_np_nan_to_num_call(value) and getattr(value, "args", None):
                arg0 = value.args[0]
                ind_name = _indicator_name_from_subscript(arg0)
                if ind_name is not None:
                    if ind_name.lower() in _DICT_INDICATOR_NAMES:
                        return (
                            False,
                            f"Usage invalide: np.nan_to_num(indicators['{ind_name}']) (indicator dict).",
                        )
                    kind = "array"
                elif isinstance(arg0, ast.Name) and arg0.id in bindings:
                    if bindings[arg0.id]["kind"] == "dict":
                        return (
                            False,
                            f"Usage invalide: np.nan_to_num({arg0.id}) alors que {arg0.id} est un indicator dict.",
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
                value_binding = _binding_info_for_expr(node.func.value, bindings)
                if value_binding and value_binding["kind"] == "dict" and attr not in {"get"}:
                    label = _binding_expr_label(node.func.value, value_binding)
                    hint_key = (
                        _dict_indicator_allowed_keys_hint(
                            str(value_binding.get("indicator") or label),
                        )
                        .split(",")[0]
                        .strip()
                    )
                    if hint_key:
                        return (
                            False,
                            f"Usage invalide: `{label}.{attr}(...)` alors que `{label}` est "
                            "un indicator dict. Extraire une sous-clé puis travailler "
                            f"sur le ndarray correspondant (ex: {label}['{hint_key}']).",
                        )
                if attr in {"shift", "rolling", "ewm"} and isinstance(node.func.value, ast.Name):
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
                                f"Usage invalide: np.nan_to_num({arg0.id}) alors que {arg0.id} est un indicator dict.",
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
                                f"Usage invalide: indexation multi-dim `{var}[..., ...]` sur indicateur 1D.",
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
                                f"Usage invalide: indicators['{ind_name}'][{key}] — utiliser des sous-clés string.",
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
                                f"Usage invalide: indicators.get('{get_name}')[{key}] — utiliser des sous-clés string.",
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
                    binding = _binding_info_for_expr(operand, bindings)
                    if binding and binding["kind"] == "dict":
                        label = _binding_expr_label(operand, binding)
                        hint_key = (
                            _dict_indicator_allowed_keys_hint(
                                str(binding.get("indicator") or label),
                            )
                            .split(",")[0]
                            .strip()
                        )
                        return (
                            False,
                            f"Usage invalide: comparaison `{label} ...` alors que "
                            f"`{label}` est un indicator dict. Utiliser une sous-clé "
                            f"(ex: {label}['{hint_key}']).",
                        )

            if isinstance(node, ast.BinOp):
                for operand in (node.left, node.right):
                    binding = _binding_info_for_expr(operand, bindings)
                    if binding and binding["kind"] == "dict":
                        label = _binding_expr_label(operand, binding)
                        hint_key = (
                            _dict_indicator_allowed_keys_hint(
                                str(binding.get("indicator") or label),
                            )
                            .split(",")[0]
                            .strip()
                        )
                        return (
                            False,
                            f"Usage invalide: opération arithmétique sur `{label}` "
                            "qui est un indicator dict. Utiliser une sous-clé "
                            f"(ex: {label}['{hint_key}']).",
                        )

                if isinstance(node.op, (ast.BitAnd, ast.BitOr, ast.BitXor)):
                    for operand in (node.left, node.right):
                        binding = _binding_info_for_expr(operand, bindings)
                        if binding and binding["kind"] == "dict":
                            label = _binding_expr_label(operand, binding)
                            hint_key = (
                                _dict_indicator_allowed_keys_hint(
                                    str(binding.get("indicator") or label),
                                )
                                .split(",")[0]
                                .strip()
                            )
                            return (
                                False,
                                f"Usage invalide: opérateur logique bitwise appliqué à `{label}` "
                                "qui est un indicator dict. Comparer d'abord une sous-clé "
                                f"(ex: {label}['{hint_key}'] > seuil) puis combiner les masques.",
                            )
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
                    binding = _binding_info_for_expr(operand, bindings)
                    if binding and binding["kind"] == "dict":
                        label = _binding_expr_label(operand, binding)
                        hint_key = (
                            _dict_indicator_allowed_keys_hint(
                                str(binding.get("indicator") or label),
                            )
                            .split(",")[0]
                            .strip()
                        )
                        return (
                            False,
                            f"Usage invalide: test booléen direct sur `{label}` "
                            "qui est un indicator dict. Utiliser une sous-clé "
                            f"(ex: {label}['{hint_key}']).",
                        )

            if isinstance(node, (ast.If, ast.While)):
                binding = _binding_info_for_expr(node.test, bindings)
                if binding and binding["kind"] == "dict":
                    label = _binding_expr_label(node.test, binding)
                    hint_key = (
                        _dict_indicator_allowed_keys_hint(
                            str(binding.get("indicator") or label),
                        )
                        .split(",")[0]
                        .strip()
                    )
                    return (
                        False,
                        f"Usage invalide: condition `{label}` alors que `{label}` est un "
                        f"indicator dict. Utiliser une sous-clé (ex: {label}['{hint_key}']).",
                    )

    return True, ""


def validate_generated_code(code: str) -> tuple[bool, str]:
    """Valide le code Python généré avant écriture/exécution.

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
        "os.system",
        "subprocess",
        "eval(",
        "exec(",
        "__import__",
        "shutil.rmtree",
        "open(",
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
    class_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
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
        (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == GENERATED_CLASS_NAME),
        None,
    )
    if class_node is not None:
        base_names = {getattr(base, "id", None) for base in class_node.bases if isinstance(base, ast.Name)}
        base_names.update(getattr(base, "attr", None) for base in class_node.bases if isinstance(base, ast.Attribute))
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
                "Signature invalide: generate_signals doit accepter (self, df, indicators, params).",
            ),
        )

    # 3c. default_params doit retourner un dict concret (pas une variable globale implicite)
    for item in _iter_generated_class_methods(tree):
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
                            "ou un attribut `self.<...>`.",
                        ),
                    )

    # 3d. NameError probable: variables coeur utilisées sans définition
    #     (fréquent quand le LLM renomme l'argument `df` mais garde `df[...]` dans le corps)
    for item in _iter_generated_class_methods(tree):
        arg_names = {a.arg for a in item.args.args}
        arg_names.update(a.arg for a in item.args.kwonlyargs)
        load_names, store_names = _collect_name_load_store_sets(item)
        core_names: tuple[str, ...] = ("df", "indicators", "params")
        if item.name == "generate_signals":
            core_names: tuple[str, ...] = ("df", "indicators", "params", "warmup")
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

    # 3e. NameError probable: indicateur enregistré utilisé comme variable nue
    #     sans alias local explicite depuis indicators['...'].
    known_indicator_names = _get_known_indicator_names()
    if known_indicator_names:
        for item in _iter_generated_class_methods(tree):
            if item.name != "generate_signals":
                continue
            arg_names = {a.arg for a in item.args.args}
            arg_names.update(a.arg for a in item.args.kwonlyargs)
            load_names, _store_names = _collect_name_load_store_sets(item)
            bound_names = _collect_bound_names(item)
            missing_indicators = sorted(
                {
                    name
                    for name in load_names
                    if name in known_indicator_names and name not in arg_names and name not in bound_names
                },
            )
            if missing_indicators:
                indicator_name = missing_indicators[0]
                return (
                    False,
                    _err(
                        ERR_IND,
                        "NameError probable: indicateur "
                        f"`{indicator_name}` utilisé comme variable nue dans "
                        "`generate_signals` sans alias local. "
                        f"{_indicator_access_hint(indicator_name)}",
                    ),
                )

    # 3e-bis. Variables libres / placeholders explicites dans les méthodes.
    module_bound_names = _collect_module_level_bound_names(tree)
    builtin_names = set(dir(builtins))
    for item in _iter_generated_class_methods(tree):
        for sub in ast.walk(item):
            if isinstance(sub, ast.Constant) and sub.value is Ellipsis:
                return (
                    False,
                    _err(
                        ERR_AST,
                        f"Placeholder `...` interdit dans `{item.name}`. Fournir une logique complète.",
                    ),
                )
        load_names, _store_names = _collect_name_load_store_sets(item)
        bound_names = _collect_bound_names(item)
        allowed_names = bound_names | module_bound_names | builtin_names
        missing_names = sorted(
            {name for name in load_names if name not in allowed_names and not name.startswith("__")},
        )
        if missing_names:
            missing_name = missing_names[0]
            return (
                False,
                _err(
                    ERR_CLASS,
                    f"NameError probable: `{missing_name}` utilisé dans `{item.name}` sans définition locale.",
                ),
            )

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
    for item in _iter_generated_class_methods(tree):
        for sub in ast.walk(item):
            if isinstance(sub, ast.Assign):
                targets = sub.targets
            elif isinstance(sub, ast.AnnAssign) or isinstance(sub, ast.AugAssign):
                targets = [sub.target]
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {"np", "pd"}:
                    return False, _err(
                        ERR_CLASS,
                        f"Alias réservé `{target.id}` écrasé dans `{item.name}`. Ne jamais réassigner `{target.id}`.",
                    )

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
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
        known_indicators = set()

    # 5b. Indicateurs inconnus via indicators[...] / indicators.get(...)
    used_indicators = _collect_indicator_names(tree) | _collect_indicator_names_in_class(tree)
    if known_indicators and used_indicators:
        unknown = sorted(
            {name for name in used_indicators if name.lower() not in known_indicators},
        )
        if unknown:
            ohlcv_and_runtime_cols = {
                "open",
                "high",
                "low",
                "close",
                "volume",
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
            hint_suffix = f" Corrections possibles: {', '.join(hints)}." if hints else ""
            return (
                False,
                "Indicateur(s) inconnu(s) via indicators détecté(s): "
                f"{unknown}. Utiliser uniquement les noms du registre."
                f"{hint_suffix}",
            )

    df_indexed = re.findall(r"df\s*\[\s*['\"]([^'\"]+)['\"]\s*\]", code)
    bad_df_cols = sorted(
        {col for col in df_indexed if col.lower() in known_indicators},
    )
    if bad_df_cols:
        return (
            False,
            _err(
                ERR_IND,
                f"Accès indicateur invalide via df[...] détecté: {bad_df_cols}. Utiliser indicators['name'].",
            ),
        )

    # 5c. Cohérence required_indicators vs registre (avertissement non bloquant)
    _soft_warnings: list[str] = []
    if known_indicators:
        declared_indicators = _extract_required_indicators_from_ast(tree)
        unknown_declared = sorted(
            {name for name in declared_indicators if name.lower() not in known_indicators},
        )
        if unknown_declared:
            hints = [
                f"{name} -> {_INDICATOR_ALIAS_HINTS[name.lower()]}"
                for name in unknown_declared
                if name.lower() in _INDICATOR_ALIAS_HINTS
            ]
            hint_suffix = f" Corrections possibles: {', '.join(hints)}." if hints else ""
            _soft_warnings.append(
                _err(
                    ERR_IND,
                    "required_indicators contient des noms inconnus du registre: "
                    f"{unknown_declared}. Utiliser uniquement les noms du registre."
                    f"{hint_suffix}",
                ),
            )

    # 5d. Warmup obligatoire dans generate_signals (avertissement non bloquant)
    if not _has_warmup_guard(tree):
        _soft_warnings.append(
            _err(
                ERR_WARM,
                "generate_signals ne contient pas de warmup explicite. "
                "Ajouter: `warmup = int(params.get('warmup', 50)); signals.iloc[:warmup] = 0.0`.",
            ),
        )

    # 6. Mauvais usage de np.nan_to_num sur indicateurs dict (bollinger, macd, ...)
    for ind in _DICT_INDICATOR_NAMES:
        bad_pattern = r"np\.nan_to_num\(\s*indicators\s*\[\s*['\"]" + re.escape(ind) + r"['\"]\s*\]\s*\)"
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

    return True, "; ".join(_soft_warnings) if _soft_warnings else ""
