"""Module-ID: agents.builder_code_repair

Purpose: Builder generated-code repair subsystem.
"""

from __future__ import annotations

import ast
import re
import textwrap

from agents.builder_ast_utils import (
    _drop_obvious_non_python_lines,
    _indicator_name_from_hint_expression,
    _normalize_required_indicator_names,
    _salvage_complex_ast_syntax,
    _sanitize_python_list_markers,
)
from agents.builder_code_validation import (
    _AST_PARSE_RECOVERABLE_EXCEPTIONS,
    _BUILDER_ALLOWED_WRITE_DF_COLUMNS,
    _DICT_INDICATOR_ALLOWED_KEYS,
    _DICT_INDICATOR_NAMES,
    _INDICATOR_ALIAS_HINTS,
    GENERATED_CLASS_NAME,
    _collect_bound_names,
    _collect_indicator_names,
    _collect_indicator_names_in_class,
    _collect_name_load_store_sets,
    _get_known_indicator_names,
    _iter_generate_signals_functions,
)
from agents.indicator_context import (
    get_indicator_builder_access_example,
    get_indicator_builder_stable_alias_map,
)
from indicators.schema import (
    DERIVED_SIGNAL_BINDINGS,
    INDICATOR_ACCESS_ALIASES,
    INVALID_DICT_SUBKEY_REWRITE_HINTS as SCHEMA_INVALID_DICT_SUBKEY_REWRITE_HINTS,
    OUTPUT_KEY_ALIASES,
    PARAMETER_ALIAS_ACCESS,
    SAFE_DICT_INDICATOR_ASSIGNMENT_ALIASES,
    SAFE_DICT_INDICATOR_KEYS,
    SEMANTIC_INDICATOR_ALIASES,
    SEMANTIC_STRING_COMPARISON_REWRITES,
    parse_parameterized_indicator_instance,
)

_DICT_INDICATOR_SAFE_SCALAR_KEYS: dict[str, str] = {
    "adx": "adx",
    "amplitude_hunter": "score",
    "supertrend": "supertrend",
    "directional_bias": "net_bias",
    "markov_switching": "regime",
}

_DICT_INDICATOR_SAFE_SCALAR_ASSIGNMENT_ALIASES: dict[str, set[str]] = {
    "adx": {"adx_val", "adx_value"},
    "amplitude_hunter": {
        "amp_score",
        "amplitude_score",
        "amplitude_hunter_score",
        "score",
        "vol_expansion_score",
        "volatility_expansion_score",
    },
    "directional_bias": {"directional_bias_net", "net_bias"},
    "markov_switching": {"markov_regime", "regime"},
    "supertrend": {"supertrend_value", "supertrend_level"},
}

# Fast-path pre-scan compilé à l'import.
# Détecte si le code contient des variables nues d'indicateurs dict (ex. keltner, bollinger)
# non précédées d'un guillemet → seul cas où les 164 re.sub du step 11 sont nécessaires.
_BARE_DICT_IND_SCAN: re.Pattern[str] = re.compile(
    r"(?<!['\"])\b(?:"
    + "|".join(re.escape(k) for k in sorted(_DICT_INDICATOR_ALLOWED_KEYS, key=len, reverse=True))
    + r")\b",
)

# Détecte si le code contient np.nan_to_num() appliqué à un indicateur DICT (pas un array).
# Ex. : np.nan_to_num(indicators["bollinger"]) → match ; np.nan_to_num(indicators["ema"]) → pas de match.
# Utilisé pour gater le step 4 (42 re.sub évités si absent, cas fréquent sur modèles capables).
_NAN_TO_NUM_DICT_SCAN: re.Pattern[str] = re.compile(
    r"np\.nan_to_num\(\s*(?:indicators\s*\[\s*|indicators\.get\(\s*)['\"](?:"
    + "|".join(re.escape(k) for k in sorted(_DICT_INDICATOR_NAMES, key=len, reverse=True))
    + r")['\"]",
)

# Alias courts utilisés dans les exemples d'accès Builder (bb→bollinger, kelt→keltner…).
# Quand le LLM écrit bb.upper ou kelt.lower, step 12b doit les réécrire également.
_DOT_ALIAS_TO_INDICATOR: dict[str, str] = {
    "bb": "bollinger",
    "kelt": "keltner",
    "dc": "donchian",
    "adx_d": "adx",
    "ar": "aroon",
    "ich": "ichimoku",
    "macd_d": "macd",
    "psar_d": "psar",
    "stoch": "stochastic",
    "srsi": "stoch_rsi",
    "st": "supertrend",
    "vx": "vortex",
    "pp": "pivot_points",
    "sw": "swing",
    "bias": "directional_bias",
    "mk": "markov_switching",
    "legs": "smart_legs",
    "amp": "amplitude_hunter",
    # Alias tronqués observés dans les archives live (LLM coupe les noms longs)
    "linger": "bollinger",
    "ollinger": "bollinger",
    "inger": "bollinger",
    "olinger": "bollinger",
    # fvg : alias == nom canonique, déjà couvert par la boucle canonique step 12b.
}

# Pré-scan compilé : détecte les patterns `name.subkey` qui nécessitent step 12b.
# Couvre noms canons ET alias courts pour éviter les faux-négatifs sur code LLM "propre".
_DOT_ACCESS_SUBKEYS: frozenset = frozenset(sk for subkeys in _DICT_INDICATOR_ALLOWED_KEYS.values() for sk in subkeys)
_DOT_ACCESS_NAMES: frozenset = frozenset(_DICT_INDICATOR_ALLOWED_KEYS.keys()) | frozenset(_DOT_ALIAS_TO_INDICATOR)
_DOT_ACCESS_DICT_SCAN: re.Pattern[str] = re.compile(
    r"\b(?:" + "|".join(re.escape(n) for n in sorted(_DOT_ACCESS_NAMES, key=len, reverse=True)) + r")\s*\."
    r"\s*(?:" + "|".join(re.escape(s) for s in sorted(_DOT_ACCESS_SUBKEYS, key=len, reverse=True)) + r")\b",
)


_SEMANTIC_INDICATOR_ALIAS_HINTS = {
    "upper_bollinger": "indicators['bollinger']['upper']",
    "middle_bollinger": "indicators['bollinger']['middle']",
    "mid_bollinger": "indicators['bollinger']['middle']",
    "lower_bollinger": "indicators['bollinger']['lower']",
    "higher_bollinger": "indicators['bollinger']['upper']",
    "midline_bollinger": "indicators['bollinger']['middle']",
}


_INDICATOR_ACCESS_REWRITE_HINTS = {
    "adx_d": "indicators['adx']",
    "bear_score": "indicators['directional_bias']['bear_score']",
    "bb": "indicators['bollinger']",
    "bull_score": "indicators['directional_bias']['bull_score']",
    "donchian_band": "indicators['donchian']",
    "directional_bias_net": "indicators['directional_bias']['net_bias']",
    "fib_levels": "indicators['fibonacci_levels']",
    "fibonacci": "indicators['fibonacci_levels']",
    "klt": "indicators['keltner']",
    "net_bias": "indicators['directional_bias']['net_bias']",
    "obvi": "indicators['obv']",
    "plus_di": "indicators['adx']['plus_di']",
    "minus_di": "indicators['adx']['minus_di']",
    "aroon_up": "indicators['aroon']['aroon_up']",
    "aroon_down": "indicators['aroon']['aroon_down']",
    "pivot": "indicators['pivot_points']['pivot']",
    "st_direction": "indicators['supertrend']['direction']",
    "direction": "indicators['supertrend']['direction']",
    "rsi_arr": "indicators['rsi']",
    "rsi_data": "indicators['rsi']",
    "atr_14": "indicators['atr']",
    "volume_osc": "indicators['volume_oscillator']",
    # Archives live : LLM confond paramètres et indicateurs, ou utilise des noms de variables
    "amplitude_hunter_score": "indicators['amplitude_hunter']['score']",
    "average_true_range": "indicators['atr']",
    "coppock": "indicators['coppock_curve']",
    "dmi": "indicators['adx']",
    "donchian_breakout": "indicators['donchian']",
    "donchian_channels": "indicators['donchian']",
    "ema_fast": "indicators['ema']",
    "ema_slow": "indicators['ema']",
    "stoch": "indicators['stochastic']",
    "stochastic_k": "indicators['stochastic']['stoch_k']",
    "stochastic_d": "indicators['stochastic']['stoch_d']",
    "stochastic_rsi": "indicators['stoch_rsi']",
    "sar": "indicators['psar']['sar']",
    "super_trend": "indicators['supertrend']",
    "adx_val": "indicators['adx']",
    "adx_value": "indicators['adx']",
    "adx_plus": "indicators['adx']['plus_di']",
    "adx_minus": "indicators['adx']['minus_di']",
    "adx_dplus": "indicators['adx']['plus_di']",
    "adx_dminus": "indicators['adx']['minus_di']",
    "adx_d_plus": "indicators['adx']['plus_di']",
    "adx_d_minus": "indicators['adx']['minus_di']",
    "rsi_value": "indicators['rsi']",
    "mfi_val": "indicators['mfi']",
    "mfi_value": "indicators['mfi']",
    "cci_val": "indicators['cci']",
    "cci_value": "indicators['cci']",
    "cmf_val": "indicators['cmf']",
    "atr_val": "indicators['atr']",
    "atr_value": "indicators['atr']",
    "macd_line": "indicators['macd']['macd']",
    "macd_signal": "indicators['macd']['signal']",
    "macd_histogram": "indicators['macd']['histogram']",
    "vortex_plus": "indicators['vortex']['vi_plus']",
    "vortex_minus": "indicators['vortex']['vi_minus']",
    "fvg_bullish": "indicators['fvg']['fvg_bullish']",
    "fvg_bearish": "indicators['fvg']['fvg_bearish']",
    "markov": "indicators['markov_switching']",
    "markov_regime": "indicators['markov_switching']['regime']",
    "swing_high": "indicators['swing']['swing_high']",
    "swing_low": "indicators['swing']['swing_low']",
    "smart_leg_bullish": "indicators['smart_legs']['smart_leg_bullish']",
    "smart_leg_bearish": "indicators['smart_legs']['smart_leg_bearish']",
    "market_volatility": "indicators['vix']",
    "volatility": "indicators['vix']",
    "vix_proxy": "indicators['vix']",
    "implied_volatility_proxy": "indicators['vix']",
    "mci": "indicators['choppiness_index']",
    "chop": "indicators['choppiness_index']",
    "choppiness": "indicators['choppiness_index']",
    "market_choppiness_index": "indicators['choppiness_index']",
    "trix_line": "indicators['trix']",
    "trix_value": "indicators['trix']",
}

_INVALID_DICT_SUBKEY_REWRITE_HINTS: dict[tuple[str, str], str] = {
    ("bollinger", "close"): "np.nan_to_num(df['close'].values.astype(np.float64))",
    ("donchian", "close"): "np.nan_to_num(df['close'].values.astype(np.float64))",
    ("keltner", "close"): "np.nan_to_num(df['close'].values.astype(np.float64))",
    ("bollinger", "std"): (
        "(np.nan_to_num(indicators['bollinger']['upper']) "
        "- np.nan_to_num(indicators['bollinger']['middle']))"
    ),
    ("bollinger", "width"): (
        "(np.nan_to_num(indicators['bollinger']['upper']) "
        "- np.nan_to_num(indicators['bollinger']['lower']))"
    ),
    ("donchian", "width"): (
        "(np.nan_to_num(indicators['donchian']['upper']) "
        "- np.nan_to_num(indicators['donchian']['lower']))"
    ),
    ("keltner", "width"): (
        "(np.nan_to_num(indicators['keltner']['upper']) "
        "- np.nan_to_num(indicators['keltner']['lower']))"
    ),
    ("donchian", "supertrend"): "indicators['supertrend']['supertrend']",
    ("fvg", "fvg_bullish_gap"): "indicators['fvg']['fvg_bullish']",
    ("fvg", "fvg_bearish_gap"): "indicators['fvg']['fvg_bearish']",
}


# Pre-compilation : un regex par cle de SEMANTIC_STRING_COMPARISON_REWRITES.
# Capture les deux sens (var == 'literal' et 'literal' == var) avec equality (==) ou
# is (`is 'bullish'` arrive parfois en sortie LLM).
def _build_semantic_string_comparison_patterns() -> list[tuple[re.Pattern[str], str]]:
    patterns: list[tuple[re.Pattern[str], str]] = []
    for (var_name, literal_value), replacement in SEMANTIC_STRING_COMPARISON_REWRITES.items():
        v = re.escape(var_name)
        lit = re.escape(literal_value)
        # var == 'literal'  /  var == "literal"  /  var is 'literal'
        patterns.append(
            (re.compile(rf"\b{v}\s*(?:==|is)\s*['\"]{lit}['\"]"), replacement),
        )
        # 'literal' == var  /  "literal" == var
        patterns.append(
            (re.compile(rf"['\"]{lit}['\"]\s*(?:==|is)\s*\b{v}\b"), replacement),
        )
    return patterns


_SEMANTIC_STRING_COMPARISON_PATTERNS = _build_semantic_string_comparison_patterns()


def _rewrite_semantic_string_comparisons(code: str) -> str:
    """Reecrit les comparaisons LLM `<var> == 'bullish'` vers les sorties int correctes.

    Cible les patterns courants ou le LLM imagine que les sorties dict (supertrend,
    markov_switching) sont des strings 'bullish'/'bearish' alors que ce sont des
    int 1/-1 (supertrend.direction) ou 0/1 (markov.regime). Table source :
    indicators.schema.SEMANTIC_STRING_COMPARISON_REWRITES.

    Une comparaison directe sur l'array float retournerait False partout,
    produisant 'signal_always_false' -> 0 trade -> precheck bloquant.
    """
    if not code or "==" not in code and " is " not in code:
        return code
    rewritten = code
    for pattern, replacement in _SEMANTIC_STRING_COMPARISON_PATTERNS:
        rewritten = pattern.sub(replacement, rewritten)
    return rewritten


_PARAM_ACCESS_REWRITE_HINTS = {
    "warmup": "params.get('warmup', 50)",
    "leverage": "params.get('leverage', 1)",
    "atr_period": "params.get('atr_period', 14)",
    "stop_atr_mult": "params.get('stop_atr_mult', 1.5)",
    "tp_atr_mult": "params.get('tp_atr_mult', 3.0)",
    "sl_factor": "params.get('stop_atr_mult', 1.5)",
    "tp_factor": "params.get('tp_atr_mult', 3.0)",
    # Archives live : LLM utilise des noms de paramètres comme variables nues
    "adx_threshold": "params.get('adx_threshold', 25)",
    "adx_filter": "params.get('adx_filter', 25)",
    "adx_min": "params.get('adx_min', 20)",
    "mfi_threshold_high": "params.get('mfi_threshold_high', 70)",
    "mfi_threshold_low": "params.get('mfi_threshold_low', 30)",
    "mfi_high": "params.get('mfi_threshold_high', 70)",
    "mfi_low": "params.get('mfi_threshold_low', 30)",
    "sl_mult": "params.get('stop_atr_mult', 1.5)",
    "tp_mult": "params.get('tp_atr_mult', 3.0)",
    "atr_stop_mult": "params.get('stop_atr_mult', 1.5)",
    "atr_tp_mult": "params.get('tp_atr_mult', 3.0)",
    "cmf_threshold": "params.get('cmf_threshold', 0.0)",
    "bias_min": "params.get('bias_min', 0.5)",
    "trend_filter": "params.get('trend_filter', 0.3)",
    "rsi_overbought": "params.get('rsi_overbought', 70)",
    "rsi_oversold": "params.get('rsi_oversold', 30)",
    "rsi_period": "params.get('rsi_period', 14)",
    "bias_strength_filter": "params.get('bias_strength_filter', 0.5)",
}

# Active source of truth: indicators.schema. The local literals above remain
# as compatibility fallback, then schema values override the runtime mappings.
_DICT_INDICATOR_SAFE_SCALAR_KEYS = dict(SAFE_DICT_INDICATOR_KEYS)
_DICT_INDICATOR_SAFE_SCALAR_ASSIGNMENT_ALIASES = {
    name: set(aliases)
    for name, aliases in SAFE_DICT_INDICATOR_ASSIGNMENT_ALIASES.items()
}
_SEMANTIC_INDICATOR_ALIAS_HINTS = dict(SEMANTIC_INDICATOR_ALIASES)
_INDICATOR_ACCESS_REWRITE_HINTS = dict(INDICATOR_ACCESS_ALIASES)
_PARAM_ACCESS_REWRITE_HINTS = dict(PARAMETER_ALIAS_ACCESS)
_INVALID_DICT_SUBKEY_REWRITE_HINTS.update(SCHEMA_INVALID_DICT_SUBKEY_REWRITE_HINTS)

_INDICATOR_ACCESS_ALIAS_SCAN: re.Pattern[str] = re.compile(
    r"(?:indicators\s*\[\s*|indicators\.get\(\s*)['\"](?:"
    + "|".join(
        re.escape(k)
        for k in sorted(
            set(_INDICATOR_ACCESS_REWRITE_HINTS) | set(_PARAM_ACCESS_REWRITE_HINTS),
            key=len,
            reverse=True,
        )
    )
    + r")['\"]",
    re.IGNORECASE,
)


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
    # --- FR existants + nouveaux ---
    r"voici|voici le code|voici la version|code corrig[ée]|code modifi[ée]|"
    r"corrig[ée]|correction|ci-dessous|ci-dessus|modifi[ée]|changement|ajout|"
    r"suggestion|proposition|en r[ée]sum[ée]|en bref|"
    r"explication|remarque|analyse|analysis|r[ée]sum[ée]|strat[ée]gie|"
    # --- EN existants ---
    r"here(?:'s|\s+is)?|sure|corrected code|explanation|note|strategy|"
    # --- EN reasoning-chain (real archives: 3824 NL lines) ---
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


_CODE_LINE_STARTS = (
    "def ",
    "class ",
    "@",
    "return ",
    "import ",
    "from ",
    "self.",
    "super(",
    "if ",
    "for ",
    "while ",
    "try:",
    "with ",
    "raise ",
    "yield ",
    "assert ",
    "pass",
    "break",
    "continue",
    "signals",
    "result",
    "n =",
    "n=",
)


def _strip_docstrings(code: str) -> str:
    """Supprime tous les blocs triple-quoted, y compris non terminés.

    Utilise une heuristique pour détecter la fin d'un docstring non terminé:
    si une ligne ressemble à du code Python (def, class, @, return, ...),
    on considère que le docstring est terminé et on préserve la ligne.
    """
    lines = code.split("\n")
    result = []
    in_docstring = False

    for line in lines:
        stripped = line.strip()

        if in_docstring:
            # Fermeture explicite du docstring
            if '"""' in stripped or "'''" in stripped:
                in_docstring = False
                continue
            # Heuristique: si la ligne ressemble à du code, le docstring
            # non terminé est considéré comme fini → préserver la ligne
            if stripped.startswith(_CODE_LINE_STARTS):
                in_docstring = False
                result.append(line)
                continue
            # Toujours dans le docstring → ignorer
            continue

        # Détecter l'ouverture d'un triple-quote
        for tq in ['"""', "'''"]:
            if tq in stripped:
                cnt = stripped.count(tq)
                if cnt >= 2:
                    # Docstring fermé sur la même ligne → ignorer la ligne
                    break
                # Docstring multi-ligne ouvert → commencer à ignorer
                in_docstring = True
                break
        else:
            # Pas de triple-quote → conserver la ligne
            result.append(line)

    return "\n".join(result)


def _fix_class_name(code: str) -> str:
    """Renomme la première sous-classe StrategyBase en GENERATED_CLASS_NAME."""
    if re.search(rf"\bclass\s+{GENERATED_CLASS_NAME}\s*\(", code):
        return code
    # Chercher une sous-classe de StrategyBase
    match = re.search(r"class\s+(\w+)\s*\([^)]*StrategyBase[^)]*\)", code)
    if match:
        old_name = match.group(1)
        if old_name != GENERATED_CLASS_NAME:
            code = re.sub(rf"\b{re.escape(old_name)}\b", GENERATED_CLASS_NAME, code)
        return code
    # Pas de StrategyBase — renommer la première classe
    match = re.search(r"class\s+(\w+)\s*\(", code)
    if match:
        old_name = match.group(1)
        code = re.sub(
            rf"class\s+{re.escape(old_name)}\s*\(",
            f"class {GENERATED_CLASS_NAME}(",
            code,
            count=1,
        )
    return code


def _infer_required_indicator_names_from_code(
    code: str,
    required_indicators: list[str] | None = None,
) -> list[str]:
    """Infère les indicateurs réellement nécessaires à partir du code et des alias connus."""
    known = _get_known_indicator_names()
    inferred = _normalize_required_indicator_names(required_indicators)
    inferred_set = set(inferred)

    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        tree = None

    if tree is not None:
        for name in _collect_indicator_names(tree) | _collect_indicator_names_in_class(tree):
            normalized_name = str(name or "").strip().lower()
            instance = parse_parameterized_indicator_instance(normalized_name)
            if instance is not None and instance.alias not in inferred_set:
                inferred.append(instance.alias)
                inferred_set.add(instance.alias)
            elif normalized_name in known and normalized_name not in inferred_set:
                inferred.append(normalized_name)
                inferred_set.add(normalized_name)

    search_space = [
        *_INDICATOR_ALIAS_HINTS.items(),
        *_INDICATOR_ACCESS_REWRITE_HINTS.items(),
    ]
    for alias, hint in search_space:
        if not re.search(rf"\b{re.escape(alias)}\b", code, flags=re.IGNORECASE):
            continue
        indicator_name = _indicator_name_from_hint_expression(hint)
        if indicator_name and indicator_name in known and indicator_name not in inferred_set:
            inferred.append(indicator_name)
            inferred_set.add(indicator_name)

    for indicator_name in sorted(known):
        if (
            re.search(
                rf"\b{re.escape(indicator_name)}_(?:arr|array|data|values?)\b",
                code,
                flags=re.IGNORECASE,
            )
            and indicator_name not in inferred_set
        ):
            inferred.append(indicator_name)
            inferred_set.add(indicator_name)

    return inferred


def _build_generate_signals_indicator_binding_groups(
    required_indicators: list[str] | None,
) -> list[tuple[str, list[str], list[str]]]:
    """Construit les lignes de binding par indicateur en séparant base et alias.

    Les lignes de base extraient l'indicateur depuis `indicators[...]`.
    Les alias dérivés (`rsi_arr = rsi`, `bollinger_upper = upper`, etc.) ne sont
    sûrs que si la base est injectée au même endroit ou déjà disponible avant.
    """
    groups: list[tuple[str, list[str], list[str]]] = []

    for indicator_name in _normalize_required_indicator_names(required_indicators):
        base_lines: list[str] = []
        alias_lines: list[str] = []
        seen_local: set[str] = set()

        if indicator_name in _DICT_INDICATOR_NAMES:
            access_example = get_indicator_builder_access_example(indicator_name)
            raw_lines = re.split(r";\s*|\n+", access_example)
            candidate_lines = [line.strip() for line in raw_lines if line.strip()]
        else:
            candidate_lines = [
                f"{indicator_name} = np.nan_to_num(indicators['{indicator_name}'])",
            ]

        for line in candidate_lines:
            normalized_line = line
            if re.match(r"^value\s*=", normalized_line):
                normalized_line = re.sub(r"^value\b", indicator_name, normalized_line)
            base_lines.append(normalized_line)
            match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", normalized_line)
            if match:
                seen_local.add(match.group(1))

        if indicator_name in _DICT_INDICATOR_NAMES:
            stable_alias_map = get_indicator_builder_stable_alias_map(indicator_name)
            for lhs_name in list(seen_local):
                if lhs_name == indicator_name:
                    continue
                stable_alias_name = stable_alias_map.get(lhs_name, f"{indicator_name}_{lhs_name}")
                alias_lines.append(f"{stable_alias_name} = {lhs_name}")
        else:
            alias_lines.extend(
                [
                    f"{indicator_name}_arr = {indicator_name}",
                    f"{indicator_name}_data = {indicator_name}",
                ],
            )

        groups.append((indicator_name, base_lines, alias_lines))

    return groups


def _resolve_derived_signal_lines(
    code: str,
    available_indicators: set[str],
) -> list[str]:
    """Detecte les references aux signaux derives (DERIVED_SIGNAL_BINDINGS) et
    retourne les lignes de calcul a injecter (avec resolution des dependances).

    Une reference est consideree comme presente si le nom de signal apparait
    dans le code en tant qu'identifier autonome (mot complet, non-string).
    Pas de double-injection : on dedoublonne les lignes deja presentes.
    """
    if not DERIVED_SIGNAL_BINDINGS:
        return []

    # Detection rapide : presence du nom comme word boundary (peut etre false positive sur string)
    referenced: list[str] = []
    for signal_name, spec in DERIVED_SIGNAL_BINDINGS.items():
        if not re.search(rf"\b{re.escape(signal_name)}\b", code):
            continue
        # Skip si toutes les lignes deja presentes (re-injection a chaque iteration possible)
        spec_lines = spec.get("lines", ())
        if all(line in code for line in spec_lines):
            continue
        # Skip si l'indicateur source n'est pas disponible
        required = set(spec.get("requires_indicators", ()))
        if required and not required.issubset(available_indicators):
            continue
        referenced.append(signal_name)

    if not referenced:
        return []

    # Resolution des dependances (requires_derived) en ordre topologique simple
    resolved: list[str] = []
    seen: set[str] = set()

    def visit(signal: str) -> None:
        if signal in seen:
            return
        seen.add(signal)
        spec = DERIVED_SIGNAL_BINDINGS.get(signal, {})
        for dep in spec.get("requires_derived", ()):
            if dep in DERIVED_SIGNAL_BINDINGS and dep not in seen:
                visit(dep)
        resolved.append(signal)

    for sig in referenced:
        visit(sig)

    # Aplatir les lignes (sans dedoublonnage strict pour preserver l'ordre des deps)
    output_lines: list[str] = []
    emitted: set[str] = set()
    for signal in resolved:
        for line in DERIVED_SIGNAL_BINDINGS[signal].get("lines", ()):
            if line in emitted or line in code:
                continue
            output_lines.append(line)
            emitted.add(line)
    return output_lines


def _inject_generate_signals_indicator_bindings(
    code: str,
    required_indicators: list[str] | None = None,
) -> str:
    """Injecte un préambule de bindings indicateurs dans generate_signals.

    Inclut depuis 2026-05-18 l'auto-injection des signaux derives connus
    (DERIVED_SIGNAL_BINDINGS) referenced dans le code mais non calcules.
    Permet au LLM d'utiliser des noms comme `tsi_crosses_above_signal`
    sans hallucinations de sous-cles dans indicators[...].
    """
    indicator_names = _infer_required_indicator_names_from_code(code, required_indicators)
    if not indicator_names:
        return code

    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return code

    fns = _iter_generate_signals_functions(tree)
    if not fns:
        return code

    binding_groups = _build_generate_signals_indicator_binding_groups(indicator_names)
    available_indicators_set = {n.lower() for n in indicator_names}
    derived_signal_lines = _resolve_derived_signal_lines(code, available_indicators_set)

    if not binding_groups and not derived_signal_lines:
        return code

    lines = code.split("\n")
    insertions: list[tuple[int, list[str]]] = []

    for fn in fns:
        fn_start = max(0, int(fn.lineno) - 1)
        fn_end = max(fn_start, int(getattr(fn, "end_lineno", fn.lineno)))
        fn_source = "\n".join(lines[fn_start:fn_end])

        binding_lines: list[str] = []
        for _indicator_name, base_lines, alias_lines in binding_groups:
            existing_base = any(line in fn_source for line in base_lines)
            if existing_base:
                continue
            binding_lines.extend(line for line in base_lines if line not in fn_source)
            binding_lines.extend(line for line in alias_lines if line not in fn_source)

        # Ajout des derived signals references mais non calcules (tsi_crosses_above_signal, etc.)
        if derived_signal_lines:
            binding_lines.extend(line for line in derived_signal_lines if line not in fn_source)

        if not binding_lines:
            continue

        if fn.body:
            first_stmt = fn.body[0]
            if (
                isinstance(first_stmt, ast.Expr)
                and isinstance(getattr(first_stmt, "value", None), ast.Constant)
                and isinstance(first_stmt.value.value, str)
            ):
                end = getattr(first_stmt, "end_lineno", None) or first_stmt.lineno
                insert_lineno = int(end) + 1
            else:
                insert_lineno = int(first_stmt.lineno)
        else:
            insert_lineno = int((getattr(fn, "end_lineno", None) or fn.lineno) + 1)

        insert_idx = max(0, min(len(lines), insert_lineno - 1))
        if 0 <= insert_idx < len(lines) and lines:
            indent = re.match(r"^(\s*)", lines[insert_idx]).group(1)
        else:
            def_line_idx = max(0, min(len(lines) - 1, int(fn.lineno) - 1)) if lines else 0
            def_indent = re.match(r"^(\s*)", lines[def_line_idx]).group(1) if lines else ""
            indent = def_indent + "    "

        insertions.append((insert_idx, [indent + line for line in binding_lines]))

    if not insertions:
        return code

    for idx, new_lines in sorted(insertions, key=lambda x: x[0], reverse=True):
        lines[idx:idx] = new_lines

    return "\n".join(lines)


def _inject_generate_signals_indicator_aliases(code: str) -> str:
    """Injecte des alias d'indicateurs nus dans generate_signals quand l'intention est claire."""
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return code

    fns = _iter_generate_signals_functions(tree)
    if not fns:
        return code

    known_indicators = _get_known_indicator_names()
    if not known_indicators:
        return code

    lines = code.split("\n")
    insertions: list[tuple[int, list[str]]] = []

    for fn in fns:
        load_names, _store_names = _collect_name_load_store_sets(fn)
        bound_names = _collect_bound_names(fn)
        missing_indicator_names = sorted(
            {name for name in load_names if name in known_indicators and name not in bound_names},
        )
        if not missing_indicator_names:
            continue

        alias_raw: list[str] = []
        for indicator_name in missing_indicator_names:
            if indicator_name in _DICT_INDICATOR_NAMES:
                alias_raw.append(
                    f"{indicator_name} = indicators['{indicator_name}']",
                )
            else:
                alias_raw.append(
                    f"{indicator_name} = np.nan_to_num(indicators['{indicator_name}'])",
                )

        if fn.body:
            first_stmt = fn.body[0]
            if (
                isinstance(first_stmt, ast.Expr)
                and isinstance(getattr(first_stmt, "value", None), ast.Constant)
                and isinstance(first_stmt.value.value, str)
            ):
                end = getattr(first_stmt, "end_lineno", None) or first_stmt.lineno
                insert_lineno = int(end) + 1
            else:
                insert_lineno = int(first_stmt.lineno)
        else:
            insert_lineno = int((getattr(fn, "end_lineno", None) or fn.lineno) + 1)

        insert_idx = max(0, min(len(lines), insert_lineno - 1))
        if 0 <= insert_idx < len(lines) and lines:
            indent = re.match(r"^(\s*)", lines[insert_idx]).group(1)
        else:
            def_line_idx = max(0, min(len(lines) - 1, int(fn.lineno) - 1)) if lines else 0
            def_indent = re.match(r"^(\s*)", lines[def_line_idx]).group(1) if lines else ""
            indent = def_indent + "    "

        insertions.append((insert_idx, [indent + line for line in alias_raw]))

    if not insertions:
        return code

    for idx, new_lines in sorted(insertions, key=lambda x: x[0], reverse=True):
        lines[idx:idx] = new_lines

    return "\n".join(lines)


def _inject_generate_signals_core_param_aliases(code: str) -> str:
    """Injecte des alias pour éviter des NameError de variables coeur.

    Cas fréquent: `def generate_signals(self, data, indicators, params):` mais le
    corps fait `signals = ... index=df.index` / `close = df["close"]...`.
    On insère alors `df = data` en tête de méthode (idem pour `indicators/params`).
    """
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return code

    fns = _iter_generate_signals_functions(tree)
    if not fns:
        return code

    lines = code.split("\n")
    insertions: list[tuple[int, list[str]]] = []

    for fn in fns:
        args = [a.arg for a in fn.args.args]
        if len(args) < 4:
            continue

        df_arg, ind_arg, params_arg = args[1], args[2], args[3]
        load_names, store_names = _collect_name_load_store_sets(fn)

        alias_raw: list[str] = []
        if "df" in load_names and "df" not in args and "df" not in store_names and df_arg != "df":
            alias_raw.append(f"df = {df_arg}")
        if (
            "indicators" in load_names
            and "indicators" not in args
            and "indicators" not in store_names
            and ind_arg != "indicators"
        ):
            alias_raw.append(f"indicators = {ind_arg}")
        if "params" in load_names and "params" not in args and "params" not in store_names and params_arg != "params":
            alias_raw.append(f"params = {params_arg}")
        if "warmup" in load_names and "warmup" not in args and "warmup" not in store_names:
            warmup_source = "params"
            if params_arg and params_arg in args and params_arg != "params":
                warmup_source = params_arg
            alias_raw.append(f"warmup = int({warmup_source}.get('warmup', 50))")

        for param_name, replacement in _PARAM_ACCESS_REWRITE_HINTS.items():
            if param_name == "warmup":
                continue
            if param_name in load_names and param_name not in args and param_name not in store_names:
                alias_raw.append(f"{param_name} = {replacement}")

        for ohlcv_col in ("open", "high", "low", "close", "volume"):
            if ohlcv_col in load_names and ohlcv_col not in args and ohlcv_col not in store_names:
                alias_raw.append(
                    f"{ohlcv_col} = np.nan_to_num(df['{ohlcv_col}'].values.astype(np.float64))",
                )
        if "price" in load_names and "price" not in args and "price" not in store_names:
            if not any(line.startswith("close = ") for line in alias_raw):
                alias_raw.append("close = np.nan_to_num(df['close'].values.astype(np.float64))")
            alias_raw.append("price = close")

        if not alias_raw:
            continue

        insert_lineno: int
        if fn.body:
            first_stmt = fn.body[0]
            if (
                isinstance(first_stmt, ast.Expr)
                and isinstance(getattr(first_stmt, "value", None), ast.Constant)
                and isinstance(first_stmt.value.value, str)
            ):
                end = getattr(first_stmt, "end_lineno", None) or first_stmt.lineno
                insert_lineno = int(end) + 1
            else:
                insert_lineno = int(first_stmt.lineno)
        else:
            insert_lineno = int((getattr(fn, "end_lineno", None) or fn.lineno) + 1)

        insert_idx = max(0, min(len(lines), insert_lineno - 1))

        # Indentation = indentation de la première ligne de body (ou fallback def+4)
        indent = ""
        if 0 <= insert_idx < len(lines) and lines:
            indent = re.match(r"^(\s*)", lines[insert_idx]).group(1)
        else:
            def_line_idx = max(0, min(len(lines) - 1, int(fn.lineno) - 1)) if lines else 0
            def_indent = re.match(r"^(\s*)", lines[def_line_idx]).group(1) if lines else ""
            indent = def_indent + "    "

        insertions.append((insert_idx, [indent + line for line in alias_raw]))

    if not insertions:
        return code

    # Appliquer en reverse pour préserver les index
    for idx, new_lines in sorted(insertions, key=lambda x: x[0], reverse=True):
        lines[idx:idx] = new_lines

    return "\n".join(lines)


def _rewrite_generate_signals_param_source_aliases(code: str) -> str:
    """Normalise `parameters/default_params.get(...)` vers le contrat runtime `params`."""
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return code

    fns = _iter_generate_signals_functions(tree)
    if not fns:
        return code

    lines = code.split("\n")
    replacements: list[tuple[int, int, list[str]]] = []
    pattern = re.compile(r"\b(?:parameters|default_params)\s*(?=\.get\s*\(|\[)")
    for fn in fns:
        start_idx = max(0, int(fn.lineno) - 1)
        end_idx = max(start_idx, int(getattr(fn, "end_lineno", fn.lineno)))
        segment = "\n".join(lines[start_idx:end_idx])
        fixed_segment = pattern.sub("params", segment)
        if fixed_segment != segment:
            replacements.append((start_idx, end_idx, fixed_segment.split("\n")))

    for start_idx, end_idx, fixed_lines in sorted(replacements, key=lambda item: item[0], reverse=True):
        lines[start_idx:end_idx] = fixed_lines

    return "\n".join(lines)


def _normalize_generate_signals_mask_aliases(code: str) -> str:
    """Corrige les alias inversés `mask_long/mask_short` quand `long_mask/short_mask` existe."""
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return code

    fns = _iter_generate_signals_functions(tree)
    if not fns:
        return code

    aliases_to_rewrite: set[str] = set()
    for fn in fns:
        load_names, store_names = _collect_name_load_store_sets(fn)
        if "mask_long" in load_names and "mask_long" not in store_names and "long_mask" in store_names:
            aliases_to_rewrite.add("mask_long")
        if "mask_short" in load_names and "mask_short" not in store_names and "short_mask" in store_names:
            aliases_to_rewrite.add("mask_short")

    if not aliases_to_rewrite:
        return code

    fixed = code
    if "mask_long" in aliases_to_rewrite:
        fixed = re.sub(r"\bmask_long\b", "long_mask", fixed)
    if "mask_short" in aliases_to_rewrite:
        fixed = re.sub(r"\bmask_short\b", "short_mask", fixed)
    return fixed


def _repair_invalid_warmup_zero_slices(code: str) -> str:
    """Réécrit les warmups destructifs courants vers `signals.iloc[:warmup] = 0.0`."""
    fixed_lines: list[str] = []
    pattern = re.compile(
        r"^(?P<indent>\s*)signals(?:\.iloc)?\s*\[\s*(?:warmup\s*:\s*|:\s*)\]\s*="
        r"\s*(?:0(?:\.0+)?|np\.nan)\s*(?P<comment>#.*)?$",
    )
    for line in str(code or "").splitlines():
        match = pattern.match(line)
        if not match:
            fixed_lines.append(line)
            continue
        comment = f" {match.group('comment').strip()}" if match.group("comment") else ""
        fixed_lines.append(f"{match.group('indent')}signals.iloc[:warmup] = 0.0{comment}")
    return "\n".join(fixed_lines)


_ATR_VALUE_EXPR_PATTERN = (
    r"\b(?:atr|atr_arr|atr_data|atr_val|atr_value|average_true_range)\b(?:\s*\[[^\]\n]+\])?"
    r"|indicators\s*\[\s*['\"]atr['\"]\s*\](?:\s*\[[^\]\n]+\])?"
    r"|np\.nan_to_num\(\s*indicators\s*\[\s*['\"]atr['\"]\s*\]\s*\)(?:\s*\[[^\]\n]+\])?"
)
_ATR_NUMERIC_LITERAL_PATTERN = r"\b(?:[1-9]\d*(?:\.\d+)?|\d+\.\d+)\b"
_ATR_THEN_LITERAL_RISK_PATTERN = re.compile(
    rf"(?P<atr>{_ATR_VALUE_EXPR_PATTERN})\s*\*\s*{_ATR_NUMERIC_LITERAL_PATTERN}",
)
_LITERAL_THEN_ATR_RISK_PATTERN = re.compile(
    rf"{_ATR_NUMERIC_LITERAL_PATTERN}\s*\*\s*(?P<atr>{_ATR_VALUE_EXPR_PATTERN})",
)


def _rewrite_hardcoded_atr_risk_multipliers(code: str) -> str:
    """Remplace les multiplicateurs ATR fixes des colonnes SL/TP par les params Builder.

    Des archives Builder contiennent des stratégies avec `stop_atr_mult` et
    `tp_atr_mult` dans `default_params`, mais des stops effectifs codés en dur
    (`atr_val * 2`, `atr_val * 4`) dans `bb_stop_*`/`bb_tp_*`. Ce repair garde
    l'intention de risque paramétrable et laisse `_inject_generate_signals_core_param_aliases`
    injecter ensuite les alias `stop_atr_mult`/`tp_atr_mult` depuis `params`.
    """
    rewritten_lines: list[str] = []
    target_cols = {
        "bb_stop_long": "stop_atr_mult",
        "bb_stop_short": "stop_atr_mult",
        "bb_tp_long": "tp_atr_mult",
        "bb_tp_short": "tp_atr_mult",
    }

    for raw_line in str(code or "").splitlines():
        line = raw_line
        rhs_start = line.find("=")
        if rhs_start < 0:
            rewritten_lines.append(line)
            continue

        lhs = line[:rhs_start]
        param_name = next((param for col, param in target_cols.items() if col in lhs), "")
        if not param_name or "atr" not in line.lower():
            rewritten_lines.append(line)
            continue

        def _replace(match: re.Match[str], param: str = param_name) -> str:
            atr_expr = match.group("atr") or "atr"
            return f"{param} * {atr_expr}"

        line = _ATR_THEN_LITERAL_RISK_PATTERN.sub(_replace, line)
        line = _LITERAL_THEN_ATR_RISK_PATTERN.sub(_replace, line)
        rewritten_lines.append(line)

    return "\n".join(rewritten_lines)


def _rewrite_invalid_dict_indicator_subkeys(code: str) -> str:
    """Répare quelques sous-clés dict hallucinées quand la cible sûre est déterministe."""
    fixed = code
    for indicator_name, aliases in OUTPUT_KEY_ALIASES.items():
        for alias, canonical_key in aliases.items():
            if alias == canonical_key:
                continue
            fixed = re.sub(
                rf"indicators\s*\[\s*['\"]{re.escape(indicator_name)}['\"]\s*\]"
                rf"\s*\[\s*['\"]{re.escape(alias)}['\"]\s*\]",
                f"indicators['{indicator_name}']['{canonical_key}']",
                fixed,
                flags=re.IGNORECASE,
            )
            fixed = re.sub(
                rf"indicators\.get\(\s*['\"]{re.escape(indicator_name)}['\"]\s*(?:,\s*[^)]*)?\)"
                rf"\s*\[\s*['\"]{re.escape(alias)}['\"]\s*\]",
                f"indicators['{indicator_name}']['{canonical_key}']",
                fixed,
                flags=re.IGNORECASE,
            )
    for (indicator_name, subkey), replacement in _INVALID_DICT_SUBKEY_REWRITE_HINTS.items():
        fixed = re.sub(
            rf"indicators\s*\[\s*['\"]{re.escape(indicator_name)}['\"]\s*\]"
            rf"\s*\[\s*['\"]{re.escape(subkey)}['\"]\s*\]",
            replacement,
            fixed,
            flags=re.IGNORECASE,
        )
        fixed = re.sub(
            rf"indicators\.get\(\s*['\"]{re.escape(indicator_name)}['\"]\s*(?:,\s*[^)]*)?\)"
            rf"\s*\[\s*['\"]{re.escape(subkey)}['\"]\s*\]",
            replacement,
            fixed,
            flags=re.IGNORECASE,
        )
    return fixed


def _fill_empty_python_blocks_with_pass(code: str) -> str:
    """Ajoute `pass` dans les blocs vides produits par le LLM pour récupérer l'AST."""
    lines = str(code or "").splitlines()
    if not lines:
        return code

    fixed_lines: list[str] = []
    for idx, line in enumerate(lines):
        fixed_lines.append(line)
        stripped = line.strip()
        if not stripped.endswith(":"):
            continue

        current_indent = len(line) - len(line.lstrip(" "))
        block_has_statement = False
        for next_line in lines[idx + 1 :]:
            next_stripped = next_line.strip()
            if not next_stripped or next_stripped.startswith("#"):
                continue
            next_indent = len(next_line) - len(next_line.lstrip(" "))
            block_has_statement = next_indent > current_indent
            break
        if not block_has_statement:
            fixed_lines.append(" " * (current_indent + 4) + "pass")

    return "\n".join(fixed_lines)


def _rewrite_invalid_indicator_accesses(text: str) -> str:
    fixed = text
    for alias, replacement in _INDICATOR_ACCESS_REWRITE_HINTS.items():
        fixed = re.sub(
            rf"indicators\s*\[\s*['\"]{re.escape(alias)}['\"]\s*\]",
            replacement,
            fixed,
            flags=re.IGNORECASE,
        )
        fixed = re.sub(
            rf"indicators\.get\(\s*['\"]{re.escape(alias)}['\"]\s*(?:,\s*[^)]*)?\)",
            replacement,
            fixed,
            flags=re.IGNORECASE,
        )
    for name, replacement in _PARAM_ACCESS_REWRITE_HINTS.items():
        fixed = re.sub(
            rf"indicators\s*\[\s*['\"]{re.escape(name)}['\"]\s*\]",
            replacement,
            fixed,
            flags=re.IGNORECASE,
        )
        fixed = re.sub(
            rf"indicators\.get\(\s*['\"]{re.escape(name)}['\"]\s*(?:,\s*[^)]*)?\)",
            replacement,
            fixed,
            flags=re.IGNORECASE,
        )
    return fixed


def _rewrite_safe_dict_indicator_comparisons(code: str) -> str:
    """Réécrit quelques comparaisons directes ambiguës sur indicateurs dict quand la sous-clé sûre est connue."""
    compare_ops = r"(==|!=|>=|<=|>|<)"
    rewritten_lines: list[str] = []
    for raw_line in str(code or "").splitlines():
        line = raw_line
        for indicator_name, subkey in _DICT_INDICATOR_SAFE_SCALAR_KEYS.items():
            scalar_expr = f"np.nan_to_num(indicators['{indicator_name}']['{subkey}'])"
            indicator_expr = rf"indicators\s*\[\s*['\"]{re.escape(indicator_name)}['\"]\s*\](?!\s*\[)"
            get_expr = rf"indicators\.get\(\s*['\"]{re.escape(indicator_name)}['\"]\s*(?:,\s*[^)]*)?\)(?!\s*\[)"
            for expr in (indicator_expr, get_expr):
                line = re.sub(
                    rf"({expr})\s*{compare_ops}",
                    lambda m, replacement=scalar_expr: f"{replacement} {m.group(2)}",
                    line,
                )
                line = re.sub(
                    rf"{compare_ops}\s*({expr})",
                    lambda m, replacement=scalar_expr: f"{m.group(1)} {replacement}",
                    line,
                )
        rewritten_lines.append(line)
    return "\n".join(rewritten_lines)


def _rewrite_safe_dict_indicator_scalar_assignments(code: str) -> str:
    """Réécrit les affectations scalaires évidentes qui capturent un indicator dict complet.

    Le LLM écrit parfois `net_bias = indicators['directional_bias']` ou
    `amp_score = indicators['amplitude_hunter']`, puis compare ces variables à un seuil.
    Dans ces cas, le nom de variable révèle la sous-clé attendue et on peut préserver la
    logique exploratoire sans basculer en fallback déterministe.
    """
    rewritten_lines: list[str] = []
    for raw_line in str(code or "").splitlines():
        line = raw_line
        for indicator_name, aliases in _DICT_INDICATOR_SAFE_SCALAR_ASSIGNMENT_ALIASES.items():
            subkey = _DICT_INDICATOR_SAFE_SCALAR_KEYS.get(indicator_name)
            if not subkey:
                continue
            alias_group = "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True))
            if not alias_group:
                continue
            direct_expr = (
                rf"(?:indicators\s*\[\s*['\"]{re.escape(indicator_name)}['\"]\s*\]"
                rf"|indicators\.get\(\s*['\"]{re.escape(indicator_name)}['\"]\s*(?:,\s*[^)]*)?\))"
                rf"(?!\s*\[)"
            )
            line = re.sub(
                rf"^(?P<indent>\s*)(?P<lhs>{alias_group})\s*=\s*{direct_expr}\s*(?P<comment>#.*)?$",
                lambda m, ind=indicator_name, key=subkey: (
                    f"{m.group('indent')}{m.group('lhs')} = "
                    f"np.nan_to_num(indicators['{ind}']['{key}'])"
                    f"{(' ' + m.group('comment').strip()) if m.group('comment') else ''}"
                ),
                line,
                flags=re.IGNORECASE,
            )
        rewritten_lines.append(line)
    return "\n".join(rewritten_lines)


def _rewrite_signals_loc_assignments(code: str) -> str:
    """Réécrit les patterns `signals.loc[mask, 'long'/'short'] = ...` vers une série 1D."""

    def _replacement(match: re.Match[str]) -> str:
        mask_expr = str(match.group("mask") or "").strip()
        side = str(match.group("side") or "").strip().lower()
        raw_value = str(match.group("value") or "").strip()
        normalized_value = raw_value
        if side == "short":
            if re.fullmatch(r"0(?:\.0+)?", raw_value):
                normalized_value = "0.0"
            else:
                normalized_value = "-1.0"
        elif side == "long":
            if re.fullmatch(r"0(?:\.0+)?", raw_value):
                normalized_value = "0.0"
            else:
                normalized_value = "1.0"
        elif re.fullmatch(r"1(?:\.0+)?", raw_value):
            normalized_value = "1.0"
        elif re.fullmatch(r"-1(?:\.0+)?", raw_value):
            normalized_value = "-1.0"
        elif re.fullmatch(r"0(?:\.0+)?", raw_value):
            normalized_value = "0.0"
        return f"signals[{mask_expr}] = {normalized_value}"

    return re.sub(
        r"signals\s*\.loc\s*\[\s*(?P<mask>[^,\]\n]+)\s*,\s*['\"](?P<side>long|short)['\"]\s*\]\s*=\s*(?P<value>[^\n#]+)",
        _replacement,
        code,
        flags=re.IGNORECASE,
    )


def _rewrite_base_strategy_aliases(code: str) -> str:
    """Normalise l'ancien alias BaseStrategy vers StrategyBase."""
    fixed = re.sub(
        r"from\s+strategies\.base_strategy\s+import\s+BaseStrategy\b",
        "from strategies.base import StrategyBase",
        code,
    )
    fixed = re.sub(r"\bBaseStrategy\b", "StrategyBase", fixed)
    return fixed


def _repair_generate_signals_body_indentation(code: str) -> str:
    """Réindente le corps de generate_signals quand des lignes ont fui au niveau module."""
    lines = code.split("\n")
    in_generate_signals = False
    def_indent = ""
    body_indent = ""
    class_indent_len = 0

    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]

        if not in_generate_signals:
            if re.match(r"^\s*def\s+generate_signals\s*\(", line):
                in_generate_signals = True
                def_indent = indent
                body_indent = def_indent + "    "
                class_indent_len = max(len(def_indent) - 4, 0)
            continue

        if not stripped:
            continue

        indent_len = len(indent)
        is_class_or_method_boundary = indent_len <= class_indent_len and (
            stripped.startswith("def ") or stripped.startswith("class ") or stripped.startswith("@")
        )
        if is_class_or_method_boundary:
            in_generate_signals = False
            if re.match(r"^\s*def\s+generate_signals\s*\(", line):
                in_generate_signals = True
                def_indent = indent
                body_indent = def_indent + "    "
                class_indent_len = max(len(def_indent) - 4, 0)
            continue

        if indent_len < len(body_indent):
            lines[idx] = body_indent + stripped

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Auto-repair vectorisation (AST + regex) — appelé après _repair_code
# ---------------------------------------------------------------------------


class _VectorizeTransformer(ast.NodeTransformer):
    """Remplace les opérateurs scalaires ``and``/``or`` par ``&``/``|`` sur
    des nœuds contenant au moins une comparaison (heuristique de masque
    vectorisé).  Les nœuds ``BoolOp(And/Or, [Compare, …])`` deviennent
    ``BinOp(left, BitAnd/BitOr, right)``.
    """

    def __init__(self) -> None:
        self.fix_count: int = 0

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        if not isinstance(node.op, (ast.And, ast.Or)):
            return node
        has_compare = any(isinstance(v, ast.Compare) for v in node.values)
        if not has_compare or len(node.values) < 2:
            return node
        bit_op_cls = ast.BitAnd if isinstance(node.op, ast.And) else ast.BitOr
        result: ast.expr = node.values[0]
        for val in node.values[1:]:
            result = ast.BinOp(left=result, op=bit_op_cls(), right=val)
            ast.copy_location(result, node)
        self.fix_count += 1
        return ast.fix_missing_locations(result)


def _auto_repair_vectorize(code: str) -> tuple[str, int]:
    """Répare les anti-patterns de vectorisation détectables par AST et regex.

    Corrections :
    1. ``and``/``or`` sur masques vectorisés → ``&``/``|`` (AST)
    2. ``signals.loc[mask]`` → ``signals[mask]`` (1D write/read)
    3. ``signals.isnull()``/``notnull()`` → ``(signals == 0)``/``(signals != 0)``
    4. ``ParameterSpec(min=`` → ``min_val=``, ``max=`` → ``max_val=``
    5. ``np.diff(x)`` sans ``np.insert`` → ``np.insert(np.diff(x), 0, 0.0)``

    Returns
    -------
    (repaired_code, fix_count)

    """
    fix_count = 0

    # 1. AST : and/or → &/| sur masques vectorisés
    try:
        tree = ast.parse(code)
        transformer = _VectorizeTransformer()
        new_tree = transformer.visit(tree)
        if transformer.fix_count > 0:
            code = ast.unparse(new_tree)
            fix_count += transformer.fix_count
    except SyntaxError:
        pass

    # 2a. signals.loc[mask] = val → signals[mask] = val  (écriture 1D)
    #     Note : le cas 2D (mask, 'long'/'short') est déjà traité par
    #     _rewrite_signals_loc_assignments() dans _repair_code.
    new_code, n = re.subn(
        r"signals\.loc\[\s*([^,\]\n]+?)\s*\](\s*=)",
        r"signals[\1]\2",
        code,
    )
    if n:
        code = new_code
        fix_count += n

    # 2b. signals.loc[mask] lecture → signals[mask]
    new_code, n = re.subn(
        r"signals\.loc\[\s*([^\]\n]+?)\s*\]",
        r"signals[\1]",
        code,
    )
    if n:
        code = new_code
        fix_count += n

    # 3. signals.isnull()/isna() → (signals == 0), notnull()/notna() → (signals != 0)
    for method, replacement in [
        ("isnull", "(signals == 0)"),
        ("isna", "(signals == 0)"),
        ("notnull", "(signals != 0)"),
        ("notna", "(signals != 0)"),
    ]:
        new_code, n = re.subn(
            rf"signals\.{method}\(\s*\)",
            replacement,
            code,
        )
        if n:
            code = new_code
            fix_count += n

    # 4. ParameterSpec(min= → min_val=, max= → max_val=, paramtype= → param_type=)
    for old_kw, new_kw in [
        ("min=", "min_val="),
        ("max=", "max_val="),
        ("paramtype=", "param_type="),
    ]:
        new_code, n = re.subn(
            rf"(ParameterSpec\([^)]*?)\b{re.escape(old_kw)}",
            rf"\1{new_kw}",
            code,
        )
        if n:
            code = new_code
            fix_count += n

    # 5. np.diff(x) → np.insert(np.diff(x), 0, 0.0) quand np.insert absent
    if "np.diff(" in code and "np.insert" not in code and "np.concatenate" not in code:
        new_code, n = re.subn(
            r"np\.diff\(([^)]+)\)",
            r"np.insert(np.diff(\1), 0, 0.0)",
            code,
        )
        if n:
            code = new_code
            fix_count += n

    return code, fix_count


def _repair_code(
    code: str, required_indicators: list[str] | None = None, *, enable_indicator_binding: bool = True,
) -> str:
    """Auto-repair des erreurs courantes du code genere par LLM.

    Corrige:
    - Tags <think> des modeles de raisonnement (qwen3, deepseek-r1)
    - Docstrings triple-quoted non terminées (cause #1 de crash)
    - Nom de classe incorrect (cause #2 de crash)
    - np.nan_to_num() appliqué directement sur indicateurs dict
    - .shift() / .rolling() / .ewm() sur ndarray → remplacement numpy
    - .iloc / .loc sur indicateurs ndarray → indexation numpy
    - indicators['ema']['ema_XX'] → indicators['ema'] (array, pas dict)
    """
    # 1. Retirer les tags <think> des modeles de raisonnement
    code = re.sub(r"<think>.*?</think>\s*", "", code, flags=re.DOTALL)
    code = re.sub(r"<think>.*", "", code, flags=re.DOTALL)
    code = _salvage_complex_ast_syntax(code)

    # 2. Supprimer le preamble non-Python (markdown, texte explicatif)
    #    avant la première ligne de code réelle (from/import/class/def)
    lines = code.split("\n")
    first_code_idx = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped and (stripped.startswith(("from ", "import ", "class ", "def ", "@")) or stripped.startswith("#!")):
            first_code_idx = idx
            break
    if first_code_idx > 0:
        code = "\n".join(lines[first_code_idx:])
    code = _drop_obvious_non_python_lines(code)
    code = _sanitize_python_list_markers(code)

    # 3. Supprimer docstrings si syntax error + tenter un dedent sur erreurs d'indentation
    _parse_ok = True
    try:
        ast.parse(code)
    except SyntaxError as e:
        _parse_ok = False
        msg = str(getattr(e, "msg", "") or "").lower()
        if "expected an indented block" in msg:
            code = _fill_empty_python_blocks_with_pass(code)
        if "unexpected indent" in msg or "unindent" in msg or "indentation" in msg:
            code = textwrap.dedent(code)
        code = _strip_docstrings(code)
        code = _salvage_complex_ast_syntax(code)

    # 3. Fixer le nom de classe
    code = _fix_class_name(code)
    code = _rewrite_base_strategy_aliases(code)
    code = _repair_generate_signals_body_indentation(code)
    code = _rewrite_generate_signals_param_source_aliases(code)
    code = _normalize_generate_signals_mask_aliases(code)
    code = _repair_invalid_warmup_zero_slices(code)
    code = _rewrite_invalid_dict_indicator_subkeys(code)
    code = _rewrite_hardcoded_atr_risk_multipliers(code)

    # 3a. Comparaisons string semantiques -> int (supertrend == 'bullish', etc.)
    #     Sans cette reecriture, le LLM produit du code qui passe la validation
    #     mais retourne 0 trade (signal_always_false -> precheck bloquant).
    code = _rewrite_semantic_string_comparisons(code)

    # _structurally_sound: True pour du code LLM propre (parse OK, classe présente,
    # generate_signals présent, patterns LLM problématiques absents).
    # Gate steps 3b, 4b, 5/6/7, 12b — économie mesurée ~7 ms/iter sur code propre.
    _structurally_sound = (
        _parse_ok
        and f"class {GENERATED_CLASS_NAME}" in code
        and "def generate_signals" in code
        and ".shift(" not in code
        and "from indicators import" not in code
        and "import indicators" not in code
    )

    # 3b. Gated: faux accès indicators[...] désignant des alias ou des params.
    #     Ex. indicators["warmup"] → params.get("warmup", 50).
    #     Même un code syntaxiquement propre peut contenir indicators["stoch"].
    if not _structurally_sound or _INDICATOR_ACCESS_ALIAS_SCAN.search(code):
        code = _rewrite_invalid_indicator_accesses(code)
        for alias, correct in _SEMANTIC_INDICATOR_ALIAS_HINTS.items():
            code = re.sub(
                rf"(?<!['\"\[])(?<![A-Za-z0-9_]){re.escape(alias)}(?!['\"])(?![A-Za-z0-9_])",
                correct,
                code,
            )

    # 4. np.nan_to_num(indicators["bollinger"]) → gated par _NAN_TO_NUM_DICT_SCAN.
    #    Ne touche pas np.nan_to_num(indicators["ema"]) (ema = array, pas dict).
    #    Évite ~42 re.sub no-ops quand absent du code (cas courant sur modèles capables).
    if _NAN_TO_NUM_DICT_SCAN.search(code):
        for dict_ind in _DICT_INDICATOR_NAMES:
            code = re.sub(
                r"np\.nan_to_num\(\s*indicators\s*\[\s*['\"]" + re.escape(dict_ind) + r"['\"]\s*\]\s*\)",
                f'indicators["{dict_ind}"]',
                code,
            )
            code = re.sub(
                r"np\.nan_to_num\(\s*indicators\.get\(\s*['\"]" + re.escape(dict_ind) + r"['\"]\s*\)\s*\)",
                f'indicators.get("{dict_ind}")',
                code,
            )

    if not _structurally_sound:
        # 4b. Stochastic subkey normalization.
        code = re.sub(
            r"(indicators\s*\[\s*['\"]stochastic['\"]\s*\]\s*\[\s*['\"])(stochastic|k)(['\"]\s*\])",
            r"\1stoch_k\3",
            code,
            flags=re.IGNORECASE,
        )
        code = re.sub(
            r"(indicators\s*\[\s*['\"]stochastic['\"]\s*\]\s*\[\s*['\"])(signal|d)(['\"]\s*\])",
            r"\1stoch_d\3",
            code,
            flags=re.IGNORECASE,
        )

        # 5. .shift(N) sur ndarray → np.roll(..., N)
        code = re.sub(
            r"(\b\w+)\.shift\(\s*(\d+)\s*\)",
            r"np.roll(\1, \2)",
            code,
        )
        code = re.sub(
            r"(\b\w+)\.shift\(\s*\)",
            r"np.roll(\1, 1)",
            code,
        )

        # 5b. .rolling(N) sur ndarray -> wrapper pd.Series pour permettre l'API pandas.
        # 2026-05-15 - Patch IND001: pattern observe (3 occurrences sur 49 sessions baseline),
        # ex: indicators['atr'].rolling(14).mean(). Le step 8 ci-dessous garantit `import pandas as pd`.
        # Le resultat d'une chaine .rolling().fn() est une Series - compatible avec broadcasting,
        # comparaisons, np.where, indexation.
        code = re.sub(
            r"(\bindicators\s*\[\s*['\"][^'\"\]]+['\"]\s*\](?:\s*\[\s*['\"][^'\"\]]+['\"]\s*\])?)\.rolling\(",
            r"pd.Series(\1).rolling(",
            code,
        )

        # 6. indicators['ema']['ema_XX'] → indicators['ema']
        for arr_ind in ("ema", "rsi", "atr", "sma", "cci", "mfi", "williams_r", "momentum", "obv", "roc"):
            pattern = (
                r"indicators\s*\[\s*['\"]"
                + re.escape(arr_ind)
                + r"['\"]\s*\]\s*\[\s*['\"](?P<subkey>[^'\"]+)['\"]\s*\]"
            )

            def _array_subkey_replacement(match: re.Match[str], base: str = arr_ind) -> str:
                subkey = str(match.group("subkey") or "").strip().lower()
                instance = parse_parameterized_indicator_instance(subkey)
                if instance is not None and instance.name == base:
                    return f"indicators['{instance.alias}']"
                return f'indicators["{base}"]'

            code = re.sub(pattern, _array_subkey_replacement, code)

        # 7. Supprimer les imports incorrects "from indicators import ..."
        code = re.sub(
            r"^from\s+indicators\s+import\s+[^\n]+\n?",
            "",
            code,
            flags=re.MULTILINE,
        )
        code = re.sub(
            r"^import\s+indicators\b[^\n]*\n?",
            "",
            code,
            flags=re.MULTILINE,
        )

    # 8. Garantir les imports obligatoires
    _REQUIRED_IMPORTS = [
        ("from typing import", "from typing import Any, Dict, List\n"),
        ("from strategies.base import StrategyBase", "from strategies.base import StrategyBase\n"),
        ("from utils.parameters import ParameterSpec", "from utils.parameters import ParameterSpec\n"),
        ("import numpy", "import numpy as np\n"),
        ("import pandas", "import pandas as pd\n"),
    ]
    for check_str, import_line in _REQUIRED_IMPORTS:
        if check_str not in code:
            code = import_line + code

    # 9. Garantir l'héritage StrategyBase
    #    Si la classe est définie sans parent ou avec un parent incorrect,
    #    forcer l'héritage de StrategyBase.
    code = re.sub(
        rf"class\s+{GENERATED_CLASS_NAME}\s*:\s*\n",
        f"class {GENERATED_CLASS_NAME}(StrategyBase):\n",
        code,
    )
    code = re.sub(
        rf"class\s+{GENERATED_CLASS_NAME}\s*\(\s*\)\s*:",
        f"class {GENERATED_CLASS_NAME}(StrategyBase):",
        code,
    )

    # 10. Alias variables coeur dans generate_signals (évite NameError df/indicators/params)
    code = _inject_generate_signals_core_param_aliases(code)

    # 10a. Préambule systématique des indicateurs déclarés/attendus dans generate_signals
    if enable_indicator_binding:
        code = _inject_generate_signals_indicator_bindings(code, required_indicators)

    # 10b. Alias indicateurs nus dans generate_signals (évite NameError coppock_curve, rsi, etc.)
    code = _inject_generate_signals_indicator_aliases(code)
    code = _rewrite_signals_loc_assignments(code)
    code = _rewrite_safe_dict_indicator_comparisons(code)
    code = _rewrite_safe_dict_indicator_scalar_assignments(code)

    # 11. Bare indicator variable repair — gate par pre-scan rapide.
    # 164 re.sub calls évitées si le code ne contient pas de variables nues d'indicateurs dict.
    if not _structurally_sound or _BARE_DICT_IND_SCAN.search(code):
        for dict_ind, subkeys in _DICT_INDICATOR_ALLOWED_KEYS.items():
            # Pattern A: bare_name['subkey'] → indicators['bare_name']['subkey']
            # Only match if NOT preceded by indicators[ (already correct)
            code = re.sub(
                r"(?<!\[)\b" + re.escape(dict_ind) + r"\s*\[\s*(['\"])(\w+)\1\s*\]",
                lambda m, ind=dict_ind: (
                    f'indicators["{ind}"]["{m.group(2)}"]'
                    if m.group(2) in _DICT_INDICATOR_ALLOWED_KEYS.get(ind, set())
                    else m.group(0)
                ),
                code,
            )
            # Pattern B: bare_name_subkey used as variable → np.nan_to_num(indicators['name']['subkey'])
            for subkey in sorted(subkeys, key=len, reverse=True):
                alias = f"{dict_ind}_{subkey}"
                pattern = r"\b" + re.escape(alias) + r"\b(?!\s*=)"
                replacement = f"np.nan_to_num(indicators['{dict_ind}']['{subkey}'])"
                code = re.sub(pattern, replacement, code)

    code = re.sub(
        r"indicators\s*\[\s*['\"]([A-Za-z0-9_]+)['\"]\s*\]",
        lambda m: f"indicators['{m.group(1).lower()}']",
        code,
    )
    code = re.sub(
        r"indicators\.get\(\s*['\"]([A-Za-z0-9_]+)['\"]",
        lambda m: f"indicators.get('{m.group(1).lower()}'",
        code,
    )

    # 12b. Notation dot : bollinger.upper / bb.upper → indicators['bollinger']['upper'].
    #      Gated par pre-scan _DOT_ACCESS_DICT_SCAN pour éviter ~80 re.sub inutiles quand
    #      aucun pattern dot n'est présent dans le code (chemin fréquent sur modèles capables).
    #      IMPORTANT : ne plus gater sur `_structurally_sound` — un LLM peut générer du code
    #      syntaxiquement propre (parse OK) mais utiliser `bb.upper` ou `bollinger.upper` qui
    #      produisent un AttributeError silencieux au runtime (dict n'a pas .upper/.lower).
    if not _structurally_sound or _DOT_ACCESS_DICT_SCAN.search(code):
        for dict_ind, subkeys in _DICT_INDICATOR_ALLOWED_KEYS.items():
            for subkey in subkeys:
                code = re.sub(
                    rf"\b{re.escape(dict_ind)}\s*\.\s*{re.escape(subkey)}\b",
                    f"indicators['{dict_ind}']['{subkey}']",
                    code,
                    flags=re.IGNORECASE,
                )
        # Aliases courts : bb.upper → indicators['bollinger']['upper'], kelt.lower → …
        for alias, indicator_name in _DOT_ALIAS_TO_INDICATOR.items():
            _alias_subkeys = _DICT_INDICATOR_ALLOWED_KEYS.get(indicator_name, set())
            for subkey in _alias_subkeys:
                code = re.sub(
                    rf"\b{re.escape(alias)}\s*\.\s*{re.escape(subkey)}\b",
                    f"indicators['{indicator_name}']['{subkey}']",
                    code,
                    flags=re.IGNORECASE,
                )

    df_cols = {"open", "high", "low", "close", "volume", *_BUILDER_ALLOWED_WRITE_DF_COLUMNS}
    for col in sorted(df_cols):
        code = re.sub(
            rf"indicators\s*\[\s*['\"]{re.escape(col)}['\"]\s*\]",
            f"df['{col}']",
            code,
            flags=re.IGNORECASE,
        )
        code = re.sub(
            rf"indicators\.get\(\s*['\"]{re.escape(col)}['\"]\s*(?:,\s*[^)]*)?\)",
            f"df['{col}']",
            code,
            flags=re.IGNORECASE,
        )

    for alias, correct in _SEMANTIC_INDICATOR_ALIAS_HINTS.items():
        code = re.sub(
            rf"(?<!['\"\[])(?<![A-Za-z0-9_]){re.escape(alias)}(?!['\"])(?![A-Za-z0-9_])",
            correct,
            code,
        )

    return code
