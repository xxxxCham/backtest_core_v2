"""Module-ID: agents.simple_builder

Purpose: Builder de strategies mono-LLM canonique avec pipeline 9 etapes
explicites, JSON DSL strict, et zero generation de code Python par le LLM.

Le LLM ne produit qu'un JSON descriptif (indicateurs + conditions DSL).
Un interpreteur deterministe assemble les signaux et execute le backtest.

Pipeline (par iteration) :
    1. propose         (LLM)        -> JSON brut
    2. validate_json   (deterministe) -> schema strict
    3. check_indicators (deterministe) -> registry strict
    4. compile_strategy (deterministe) -> StrategyBase concret
    5. validate_strategy (deterministe) -> dry-run signaux
    6. run_backtest    (deterministe) -> RunResult
    7. diagnose        (deterministe) -> verdict chiffre
    8. decide          (deterministe) -> accept / reject / retry / stop
    9. log             (deterministe) -> NDJSON ligne par ligne

Skip-if: Vous utilisez le builder historique (StrategyBuilder).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from agents.llm_client import LLMClient, LLMConfig, LLMMessage, create_llm_client
from backtest.engine import BacktestEngine
from indicators.registry import calculate_indicator, get_indicator, list_indicators
from strategies.base import StrategyBase
from utils.observability import get_obs_logger

logger = get_obs_logger(__name__)


# =============================================================================
# Exceptions typees (jamais "except Exception" dans ce module)
# =============================================================================


class SimpleBuilderError(Exception):
    """Erreur metier du SimpleBuilder. Toujours typee."""

    code: str = "ERR_BUILDER"


class LLMOutputError(SimpleBuilderError):
    code = "ERR_LLM_OUTPUT"


class JsonValidationError(SimpleBuilderError):
    code = "ERR_JSON_SCHEMA"


class IndicatorNotFoundError(SimpleBuilderError):
    code = "ERR_INDICATOR_UNKNOWN"


class DslCompileError(SimpleBuilderError):
    code = "ERR_DSL_COMPILE"


class StrategyValidationError(SimpleBuilderError):
    code = "ERR_STRATEGY_VALIDATE"


class BacktestExecutionError(SimpleBuilderError):
    code = "ERR_BACKTEST"


# =============================================================================
# DSL strict : un dict JSON, pas de Python execute
# =============================================================================
# Atome :
#   - number : 1.0, 30, -2
#   - column : "open" | "high" | "low" | "close" | "volume"
#   - indicator alias : "rsi14", "bb.upper"
# Comparateur (binaire) :
#   ["lt"|"gt"|"le"|"ge"|"eq"|"crosses_above"|"crosses_below", left, right]
# Combinateur (n-aire) :
#   ["all"|"any"|"not", [...]]

_OHLCV_COLS = {"open", "high", "low", "close", "volume"}
_BIN_OPS = {"lt", "gt", "le", "ge", "eq", "crosses_above", "crosses_below"}
_LOGICAL_OPS = {"all", "any", "not"}


# =============================================================================
# Schemas et constantes
# =============================================================================


_REQUIRED_TOP_KEYS = {"strategy_name", "indicators", "entry_long", "exit_long"}
_OPTIONAL_TOP_KEYS = {"hypothesis", "stop_loss_pct", "take_profit_pct"}
_ALLOWED_TOP_KEYS = _REQUIRED_TOP_KEYS | _OPTIONAL_TOP_KEYS

# Critere d'acceptation strict (et explicite, pas de "0% return ok")
DEFAULT_ACCEPT_CRITERIA: dict[str, float] = {
    "min_trades": 20.0,
    "min_total_return_pct": 5.0,    # plus exigeant que l'historique (0%)
    "min_sharpe": 0.5,
    "max_drawdown_pct": 30.0,
    "min_profit_factor": 1.10,
}

# Limites canoniques de l'iteration
DEFAULT_MAX_ITERATIONS = 5
DEFAULT_RETRY_ON_INVALID_JSON = 1  # une seule retry par iteration
DEFAULT_LLM_TIMEOUT_S = 180


# =============================================================================
# Dataclasses de sortie
# =============================================================================


@dataclass
class IterationOutcome:
    """Resultat d'une iteration. Toujours structure, jamais None silencieux."""

    iteration: int
    status: str                      # "accepted" | "rejected" | "failed" | "retried"
    phase_reached: str               # phase ou ca a termine ou casse
    reason: str
    error_code: str = ""             # ERR_* si failed
    proposal: dict[str, Any] = field(default_factory=dict)
    llm_latency_s: float = 0.0
    backtest_latency_s: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    diagnosis: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""


@dataclass
class SessionOutcome:
    """Resultat d'une session complete."""

    session_id: str
    objective: str
    final_status: str                # "accepted" | "exhausted" | "stopped"
    iterations: list[IterationOutcome] = field(default_factory=list)
    accepted_iteration: int = 0      # 0 si aucune
    started_at: str = ""
    finished_at: str = ""

    def best_metrics(self) -> dict[str, Any]:
        accepted = [it for it in self.iterations if it.status == "accepted"]
        if accepted:
            return dict(accepted[-1].metrics)
        if self.iterations:
            ranked = sorted(
                self.iterations,
                key=lambda it: float(it.metrics.get("total_return_pct", 0.0) or 0.0),
                reverse=True,
            )
            return dict(ranked[0].metrics)
        return {}


# =============================================================================
# DSL : compilateur deterministe vers expressions vectorielles
# =============================================================================


_VALUE_LIKE_TOKENS = {"value", "values", "default", "out", "output", "result"}


def _normalize_atom(atom: Any, *, series_by_alias: dict[str, pd.Series]) -> Any:
    """Normalise les formes LLM courantes vers la forme canonique du DSL.

    Tolerances appliquees AVANT _resolve_atom (jamais silencieuses cote logs : seul
    le format est ramene a la forme canonique, la semantique reste stricte) :

      ['rsi14', 'value']         -> 'rsi14'         (alias mono-output + token 'value')
      ['bb', 'upper']             -> 'bb.upper'      (alias multi-output explicit)
      {'$ref': 'rsi14'}           -> 'rsi14'        (notation JSON-Schema observee)

    Tout autre tuple / objet non reconnu est laisse tel quel : _resolve_atom levera
    l'exception typee correspondante.
    """
    if isinstance(atom, dict):
        ref = atom.get("$ref") or atom.get("alias") or atom.get("name")
        if isinstance(ref, str):
            return ref
        return atom

    if not isinstance(atom, list):
        return atom

    if len(atom) == 2 and isinstance(atom[0], str) and isinstance(atom[1], str):
        head, tail = atom[0], atom[1]
        # ['rsi14', 'value'] -> 'rsi14' si l'alias est mono-output
        if tail.lower() in _VALUE_LIKE_TOKENS and head in series_by_alias:
            return head
        # ['bb', 'upper'] -> 'bb.upper' si la notation pointee existe
        candidate = f"{head}.{tail}"
        if candidate in series_by_alias:
            return candidate
    # Toute autre liste reste invalide ; on retourne tel quel pour erreur typee.
    return atom


def _resolve_atom(
    atom: Any,
    *,
    df: pd.DataFrame,
    series_by_alias: dict[str, pd.Series],
) -> pd.Series | float:
    """Resout un atome (nombre, colonne, alias d'indicateur)."""
    atom = _normalize_atom(atom, series_by_alias=series_by_alias)
    if isinstance(atom, bool):
        # bool est subclass de int -> on le rejette explicitement.
        raise DslCompileError(f"atome booleen non supporte: {atom!r}")
    if isinstance(atom, (int, float)):
        return float(atom)
    if not isinstance(atom, str):
        raise DslCompileError(f"atome inattendu: {atom!r}")
    key = atom.strip()
    if not key:
        raise DslCompileError("atome vide")
    if key in _OHLCV_COLS:
        if key not in df.columns:
            raise DslCompileError(f"colonne OHLCV absente du DataFrame: {key!r}")
        return df[key]
    if key in series_by_alias:
        return series_by_alias[key]
    raise DslCompileError(
        f"alias inconnu: {key!r}. "
        f"Aliases connus: {sorted(series_by_alias.keys()) or '(aucun)'}"
    )


def _eval_binary(
    op: str,
    left: pd.Series | float,
    right: pd.Series | float,
) -> pd.Series:
    """Evalue un operateur binaire vectoriellement."""
    if op == "lt":
        return left < right
    if op == "gt":
        return left > right
    if op == "le":
        return left <= right
    if op == "ge":
        return left >= right
    if op == "eq":
        return left == right
    if op in ("crosses_above", "crosses_below"):
        if not isinstance(left, pd.Series):
            raise DslCompileError(f"{op} attend une serie a gauche")
        right_series = right if isinstance(right, pd.Series) else pd.Series(
            float(right), index=left.index,
        )
        prev_left = left.shift(1)
        prev_right = right_series.shift(1)
        if op == "crosses_above":
            return (prev_left <= prev_right) & (left > right_series)
        return (prev_left >= prev_right) & (left < right_series)
    raise DslCompileError(f"operateur binaire inconnu: {op!r}")


def _compile_expr(
    expr: Any,
    *,
    df: pd.DataFrame,
    series_by_alias: dict[str, pd.Series],
) -> pd.Series:
    """Compile une expression DSL vers une pd.Series booleenne."""
    if not isinstance(expr, list) or not expr:
        raise DslCompileError(f"expression DSL invalide: {expr!r}")
    head = expr[0]
    if not isinstance(head, str):
        raise DslCompileError(f"tete d'expression doit etre un operateur string: {expr!r}")
    op = head.strip().lower()
    if op in _BIN_OPS:
        if len(expr) != 3:
            raise DslCompileError(f"{op} attend 2 arguments, recu {len(expr) - 1}")
        left = _resolve_atom(expr[1], df=df, series_by_alias=series_by_alias)
        right = _resolve_atom(expr[2], df=df, series_by_alias=series_by_alias)
        return _eval_binary(op, left, right).fillna(False).astype(bool)
    if op in _LOGICAL_OPS:
        if op == "not":
            if len(expr) != 2:
                raise DslCompileError("'not' attend 1 argument")
            return ~_compile_expr(expr[1], df=df, series_by_alias=series_by_alias)
        if len(expr) != 2 or not isinstance(expr[1], list):
            raise DslCompileError(f"{op} attend une liste d'expressions")
        children = [
            _compile_expr(child, df=df, series_by_alias=series_by_alias)
            for child in expr[1]
        ]
        if not children:
            raise DslCompileError(f"{op} ne peut pas etre vide")
        result = children[0]
        for nxt in children[1:]:
            result = (result & nxt) if op == "all" else (result | nxt)
        return result.fillna(False).astype(bool)
    raise DslCompileError(f"operateur DSL inconnu: {op!r}")


# =============================================================================
# Adapter StrategyBase compile depuis le DSL
# =============================================================================


class _DslStrategy(StrategyBase):
    """Strategie adaptable compile depuis le DSL JSON.

    Cette classe N'EST PAS enregistree dans le registry global. Elle
    est instanciee a la volee par le SimpleBuilder pour chaque iteration.
    """

    def __init__(
        self,
        *,
        strategy_name: str,
        indicator_specs: list[dict[str, Any]],
        entry_long_dsl: list[Any],
        exit_long_dsl: list[Any],
        stop_loss_pct: float | None,
        take_profit_pct: float | None,
    ):
        super().__init__(name=strategy_name)
        self._indicator_specs = indicator_specs
        self._entry_long_dsl = entry_long_dsl
        self._exit_long_dsl = exit_long_dsl
        self._stop_loss_pct = stop_loss_pct
        self._take_profit_pct = take_profit_pct
        self._aliases = [str(spec["alias"]) for spec in indicator_specs]

    @property
    def required_indicators(self) -> list[str]:
        # Le moteur de backtest utilise cette liste pour calculer les indicateurs.
        # On retourne les noms canoniques (pas les alias).
        seen: set[str] = set()
        ordered: list[str] = []
        for spec in self._indicator_specs:
            base = str(spec["name"]).lower()
            if base not in seen:
                seen.add(base)
                ordered.append(base)
        return ordered

    @property
    def default_params(self) -> dict[str, Any]:
        # Aplatit les params en {prefix_param: value} pour le moteur historique.
        flat: dict[str, Any] = {}
        for spec in self._indicator_specs:
            base = str(spec["name"]).lower()
            for k, v in (spec.get("params") or {}).items():
                flat[f"{base}_{k}"] = v
        if self._stop_loss_pct is not None:
            flat["sl_pct"] = float(self._stop_loss_pct)
        if self._take_profit_pct is not None:
            flat["tp_pct"] = float(self._take_profit_pct)
        return flat

    def _calc_aliased_series(
        self,
        df: pd.DataFrame,
    ) -> dict[str, pd.Series]:
        """Calcule chaque indicateur avec ses params explicites et le materialise en series."""
        out: dict[str, pd.Series] = {}
        index = df.index
        for spec in self._indicator_specs:
            alias = str(spec["alias"])
            base = str(spec["name"]).lower()
            params = dict(spec.get("params") or {})
            outputs = list(spec.get("outputs") or [])
            try:
                value = calculate_indicator(base, df, params)
            except ValueError as exc:
                raise DslCompileError(
                    f"echec calcul indicateur {base!r} (alias {alias!r}): {exc}",
                ) from exc

            if isinstance(value, tuple):
                if not outputs:
                    raise DslCompileError(
                        f"indicateur {base!r} retourne un tuple; "
                        f"specifier 'outputs' pour l'alias {alias!r}",
                    )
                if len(outputs) != len(value):
                    raise DslCompileError(
                        f"outputs ({len(outputs)}) != tuple ({len(value)}) pour {alias!r}",
                    )
                for sub_name, arr in zip(outputs, value):
                    series = _to_series(arr, index=index)
                    out[f"{alias}.{sub_name}"] = series
            else:
                series = _to_series(value, index=index)
                out[alias] = series
        return out

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: dict[str, Any],
        params: dict[str, Any],
    ) -> pd.Series:
        del indicators, params  # on utilise notre propre calcul aliase
        try:
            series_by_alias = self._calc_aliased_series(df)
            entry_mask = _compile_expr(
                self._entry_long_dsl, df=df, series_by_alias=series_by_alias,
            )
            exit_mask = _compile_expr(
                self._exit_long_dsl, df=df, series_by_alias=series_by_alias,
            )
        except DslCompileError:
            raise
        except (ValueError, KeyError, TypeError) as exc:
            raise DslCompileError(f"erreur DSL inattendue: {exc}") from exc

        signals = pd.Series(0, index=df.index, dtype=int)
        signals[entry_mask.fillna(False).astype(bool)] = 1
        signals[exit_mask.fillna(False).astype(bool)] = -1
        return signals


def _to_series(value: Any, *, index: pd.Index) -> pd.Series:
    """Coerce un array/list/Series en pd.Series alignee sur index."""
    if isinstance(value, pd.Series):
        if len(value) != len(index):
            raise DslCompileError(
                f"indicateur retourne longueur {len(value)} != df {len(index)}",
            )
        out = value.copy()
        out.index = index
        return out
    arr = np.asarray(value)
    if arr.ndim != 1:
        raise DslCompileError(f"indicateur multi-dim non supporte: shape={arr.shape}")
    if len(arr) != len(index):
        raise DslCompileError(
            f"indicateur retourne longueur {len(arr)} != df {len(index)}",
        )
    return pd.Series(arr, index=index)


# =============================================================================
# Validation JSON
# =============================================================================


def validate_proposal_schema(payload: Any) -> dict[str, Any]:
    """Valide la structure d'une proposition LLM. Aucun fallback silencieux."""
    if not isinstance(payload, dict):
        raise JsonValidationError(f"payload non-dict: type={type(payload).__name__}")
    keys = set(payload.keys())
    missing = _REQUIRED_TOP_KEYS - keys
    if missing:
        raise JsonValidationError(f"cles requises manquantes: {sorted(missing)}")
    unknown = keys - _ALLOWED_TOP_KEYS
    if unknown:
        raise JsonValidationError(f"cles inconnues (non autorisees): {sorted(unknown)}")

    name = payload["strategy_name"]
    if not isinstance(name, str) or not name.strip():
        raise JsonValidationError("strategy_name doit etre une string non-vide")

    indicators = payload["indicators"]
    if not isinstance(indicators, list) or not indicators:
        raise JsonValidationError("indicators doit etre une liste non-vide")

    aliases: set[str] = set()
    for idx, spec in enumerate(indicators):
        if not isinstance(spec, dict):
            raise JsonValidationError(f"indicators[{idx}] non-dict")
        if "alias" not in spec or "name" not in spec:
            raise JsonValidationError(
                f"indicators[{idx}] doit avoir 'alias' et 'name'",
            )
        alias = str(spec["alias"]).strip()
        if not alias or alias in aliases:
            raise JsonValidationError(
                f"indicators[{idx}].alias invalide ou duplique: {alias!r}",
            )
        aliases.add(alias)
        if not isinstance(spec.get("params") or {}, dict):
            raise JsonValidationError(f"indicators[{idx}].params doit etre un dict")
        outputs = spec.get("outputs")
        if outputs is not None and not (
            isinstance(outputs, list) and all(isinstance(o, str) for o in outputs)
        ):
            raise JsonValidationError(f"indicators[{idx}].outputs doit etre list[str]")

    for key in ("entry_long", "exit_long"):
        if not isinstance(payload[key], list) or not payload[key]:
            raise JsonValidationError(f"{key} doit etre une expression DSL non-vide")

    if "stop_loss_pct" in payload:
        sl = payload["stop_loss_pct"]
        if not (isinstance(sl, (int, float)) and 0 < float(sl) < 100):
            raise JsonValidationError("stop_loss_pct doit etre dans (0, 100)")
    if "take_profit_pct" in payload:
        tp = payload["take_profit_pct"]
        if not (isinstance(tp, (int, float)) and 0 < float(tp) < 1000):
            raise JsonValidationError("take_profit_pct doit etre dans (0, 1000)")

    return payload


def check_indicators_against_registry(payload: dict[str, Any]) -> None:
    """Verifie que chaque indicateur reference existe dans le registry."""
    available = {n.lower() for n in list_indicators()}
    for spec in payload["indicators"]:
        base = str(spec["name"]).lower()
        if base not in available:
            raise IndicatorNotFoundError(
                f"indicateur inconnu du registry: {base!r}. "
                f"Disponibles: {sorted(available)}",
            )
        info = get_indicator(base)
        if info is None:
            raise IndicatorNotFoundError(f"get_indicator({base!r}) -> None")


# =============================================================================
# Compilation strategy
# =============================================================================


def compile_strategy_from_proposal(payload: dict[str, Any]) -> _DslStrategy:
    """Construit l'adapter StrategyBase depuis le JSON valide."""
    try:
        return _DslStrategy(
            strategy_name=str(payload["strategy_name"]).strip(),
            indicator_specs=list(payload["indicators"]),
            entry_long_dsl=list(payload["entry_long"]),
            exit_long_dsl=list(payload["exit_long"]),
            stop_loss_pct=(
                float(payload["stop_loss_pct"]) if "stop_loss_pct" in payload else None
            ),
            take_profit_pct=(
                float(payload["take_profit_pct"]) if "take_profit_pct" in payload else None
            ),
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise DslCompileError(f"compile_strategy: {exc}") from exc


def dry_run_strategy(strategy: _DslStrategy, df: pd.DataFrame) -> dict[str, Any]:
    """Execute generate_signals sur df pour valider la strategie sans backtester."""
    try:
        signals = strategy.generate_signals(df, indicators={}, params={})
    except DslCompileError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise StrategyValidationError(f"dry_run echec: {exc}") from exc

    if not isinstance(signals, pd.Series):
        raise StrategyValidationError(
            f"signals doit etre pd.Series, recu {type(signals).__name__}",
        )
    if len(signals) != len(df):
        raise StrategyValidationError(
            f"len(signals)={len(signals)} != len(df)={len(df)}",
        )
    n_entries = int((signals == 1).sum())
    n_exits = int((signals == -1).sum())
    # Note: 0 signal n'est pas une erreur de compilation. C'est une info qui sera
    # capturee par le diagnostic (min_trades) apres backtest. La compilation
    # reussie + le shape/dtype corrects suffisent ici.
    return {"n_entries_long": n_entries, "n_exits_long": n_exits}


# =============================================================================
# LLM prompt minimaliste et strict
# =============================================================================


def build_system_prompt() -> str:
    return (
        "Tu generes une strategie de trading sous forme de JSON UNIQUEMENT. "
        "Pas de prose, pas de markdown, pas de balises <think>. "
        "Le JSON doit respecter exactement le schema fourni par l'utilisateur."
    )


def build_user_prompt(
    *,
    objective: str,
    available_indicators: list[str],
    last_failure_reason: str | None = None,
) -> str:
    # Exemple complet et minimal, pour ancrer le format attendu cote LLM.
    example_simple = {
        "strategy_name": "rsi_oversold_bounce",
        "indicators": [
            {"alias": "rsi14", "name": "rsi", "params": {"period": 14}},
            {"alias": "ema50", "name": "ema", "params": {"period": 50}},
        ],
        "entry_long": ["all", [
            ["lt", "rsi14", 30],
            ["gt", "close", "ema50"],
        ]],
        "exit_long": ["any", [
            ["gt", "rsi14", 70],
        ]],
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
    }
    # Exemple multi-output pour bollinger.
    example_bb = {
        "strategy_name": "bollinger_breakout",
        "indicators": [
            {
                "alias": "bb",
                "name": "bollinger",
                "params": {"period": 20, "std_dev": 2.0},
                "outputs": ["upper", "middle", "lower"],
            },
        ],
        "entry_long": ["all", [["gt", "close", "bb.upper"]]],
        "exit_long": ["any", [["lt", "close", "bb.middle"]]],
    }

    forbidden_examples = [
        '"entry_long": ["all", [["lt", ["rsi14", "value"], 30]]]   ← FAUX',
        '"entry_long": ["all", [["lt", ["outputs", 0, "rsi14"], 30]]]   ← FAUX',
        '"entry_long": [["lt", "rsi14", 30]]   ← FAUX (manque "all")',
        '"entry_long": "rsi14 < 30"   ← FAUX (pas de string libre)',
    ]

    parts = [
        f"OBJECTIF : {objective}",
        "FORMAT : tu produis EXCLUSIVEMENT un objet JSON, conforme au schema ci-dessous. "
        "Pas de prose, pas de markdown, pas de balises <think>, pas de commentaires.",
        f"INDICATEURS DISPONIBLES (registry) : {', '.join(sorted(available_indicators))}.",
        # Reglement DSL strict avec exemples
        "REGLES DSL :",
        "  1. Chaque expression est une LISTE dont le PREMIER element est un operateur "
        "string parmi : lt, gt, le, ge, eq, crosses_above, crosses_below, all, any, not.",
        "  2. Operateurs binaires (lt, gt, le, ge, eq, crosses_*) attendent EXACTEMENT 2 arguments.",
        "  3. Operateurs n-aires (all, any) attendent UNE liste d'expressions enfants.",
        "  4. Un atome est SOIT un nombre, SOIT une string : "
        "colonne OHLCV ('open','high','low','close','volume') OU alias d'indicateur.",
        "  5. Un alias est juste son nom, ex : 'rsi14'. JAMAIS ['rsi14','value'] ou autre tuple.",
        "  6. Pour un indicateur multi-output (ex: bollinger), reference le sous-output via "
        "la notation 'alias.nom_output' (ex: 'bb.upper'). C'est une string entiere.",
        "  7. 'entry_long' et 'exit_long' DOIVENT commencer par 'all' ou 'any' suivi d'une liste.",
        "  8. stop_loss_pct doit etre dans (0, 100). take_profit_pct dans (0, 1000).",
        "EXEMPLE 1 (simple, mono-output) :",
        json.dumps(example_simple, ensure_ascii=False, indent=2),
        "EXEMPLE 2 (multi-output bollinger) :",
        json.dumps(example_bb, ensure_ascii=False, indent=2),
        "FORMES INTERDITES (a NE PAS reproduire) :",
        "\n".join(f"  - {ex}" for ex in forbidden_examples),
        "Reponds UNIQUEMENT avec le JSON. Pas de texte avant ou apres.",
    ]
    if last_failure_reason:
        parts.append(
            f"L'ITERATION PRECEDENTE A ETE REFUSEE. Raison exacte : {last_failure_reason}\n"
            "Corrige PRECISEMENT cette erreur dans le nouveau JSON. "
            "Ne reproduis pas la meme forme.",
        )
    return "\n\n".join(parts)


# =============================================================================
# Diagnostic et decision
# =============================================================================


def diagnose(metrics: dict[str, Any], criteria: dict[str, float]) -> dict[str, Any]:
    """Compare metrics vs criteria. Retourne un verdict explicite."""
    def _f(key: str) -> float:
        try:
            return float(metrics.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    n_trades = _f("n_trades") or float(metrics.get("n_trades", 0) or 0)
    total_return_pct = _f("total_return_pct")
    sharpe = _f("sharpe_ratio")
    max_dd = abs(_f("max_drawdown_pct") or _f("max_drawdown"))
    profit_factor = _f("profit_factor")

    checks = {
        "min_trades": n_trades >= criteria["min_trades"],
        "min_total_return_pct": total_return_pct >= criteria["min_total_return_pct"],
        "min_sharpe": sharpe >= criteria["min_sharpe"],
        "max_drawdown_pct": max_dd <= criteria["max_drawdown_pct"],
        "min_profit_factor": profit_factor >= criteria["min_profit_factor"],
    }
    all_passed = all(checks.values())
    failed = [k for k, ok in checks.items() if not ok]
    return {
        "passed": all_passed,
        "failed_checks": failed,
        "values": {
            "n_trades": n_trades,
            "total_return_pct": total_return_pct,
            "sharpe_ratio": sharpe,
            "max_drawdown_pct": max_dd,
            "profit_factor": profit_factor,
        },
    }


def decide(
    diagnosis: dict[str, Any],
    *,
    iteration: int,
    max_iterations: int,
) -> tuple[str, str]:
    """Retourne (status, reason) parmi accepted/rejected/stop."""
    if diagnosis["passed"]:
        return "accepted", "all criteria met"
    if iteration >= max_iterations:
        return "stop", f"max_iterations={max_iterations} atteinte sans acceptation"
    return "rejected", f"echecs criteres: {diagnosis['failed_checks']}"


# =============================================================================
# Logging NDJSON deterministe
# =============================================================================


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class _NdjsonLogger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, **payload: Any) -> None:
        record = {"ts": _utc_now_iso(), "event": event, **payload}
        try:
            line = json.dumps(record, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            line = json.dumps(
                {"ts": record["ts"], "event": event, "error": "json_dumps_failed"},
                ensure_ascii=False,
            )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        # Aussi visible dans le logger Python
        logger.info("simple_builder %s %s", event, line)


# =============================================================================
# SimpleBuilder : orchestrateur du pipeline 9 etapes
# =============================================================================


class SimpleBuilder:
    """Builder mono-LLM canonique. Aucune relance externe, aucun fallback silencieux."""

    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        llm_config: LLMConfig | None = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        retry_on_invalid_json: int = DEFAULT_RETRY_ON_INVALID_JSON,
        accept_criteria: dict[str, float] | None = None,
        sessions_dir: Path | str | None = None,
        engine: BacktestEngine | None = None,
        initial_capital: float = 10000.0,
    ):
        if llm_client is not None:
            self.llm = llm_client
        else:
            self.llm = create_llm_client(llm_config or LLMConfig.from_env())
        self.max_iterations = int(max_iterations)
        self.retry_on_invalid_json = int(retry_on_invalid_json)
        self.criteria = dict(accept_criteria or DEFAULT_ACCEPT_CRITERIA)
        self.engine = engine or BacktestEngine(initial_capital=initial_capital)
        self.initial_capital = float(initial_capital)
        sdir = Path(sessions_dir) if sessions_dir else (
            Path(os.environ.get("BACKTEST_RESULTS_DIR") or "backtest_results")
            / "_builder_sessions"
            / "_simple_builder"
        )
        self._sessions_dir = sdir

    # ---- LLM ----------------------------------------------------------------

    def _ask_llm_for_proposal(
        self,
        *,
        objective: str,
        available_indicators: list[str],
        last_failure_reason: str | None,
    ) -> tuple[dict[str, Any], float]:
        """Etape 1 : LLM. Retourne (payload_dict, latency_s)."""
        system = build_system_prompt()
        user = build_user_prompt(
            objective=objective,
            available_indicators=available_indicators,
            last_failure_reason=last_failure_reason,
        )
        messages = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]
        t0 = time.perf_counter()
        response = self.llm.chat(messages, json_mode=True)
        latency = time.perf_counter() - t0
        if not response.is_valid:
            raise LLMOutputError(
                f"reponse LLM invalide: parse_error={response.parse_error!r} "
                f"content_len={len(response.content or '')}",
            )
        parsed = response.parse_json()
        if parsed is None:
            raise LLMOutputError(
                f"impossible de parser le JSON: parse_error={response.parse_error!r}",
            )
        return parsed, latency

    # ---- Pipeline iteration --------------------------------------------------

    def _run_iteration(
        self,
        *,
        iteration: int,
        objective: str,
        data: pd.DataFrame,
        last_failure_reason: str | None,
        ndjson: _NdjsonLogger,
        symbol: str,
        timeframe: str,
    ) -> IterationOutcome:
        outcome = IterationOutcome(
            iteration=iteration,
            status="failed",
            phase_reached="init",
            reason="not started",
            started_at=_utc_now_iso(),
        )
        available = sorted(list_indicators())
        proposal: dict[str, Any] = {}

        # -- Steps 1+2 : LLM + JSON validation, avec UNE retry contractuelle --
        attempts = self.retry_on_invalid_json + 1
        last_attempt_error: str | None = last_failure_reason
        for attempt in range(1, attempts + 1):
            outcome.phase_reached = f"propose(attempt={attempt})"
            ndjson.emit("phase_start", iteration=iteration, phase="propose", attempt=attempt)
            try:
                proposal, llm_latency = self._ask_llm_for_proposal(
                    objective=objective,
                    available_indicators=available,
                    last_failure_reason=last_attempt_error,
                )
                outcome.llm_latency_s += llm_latency
            except LLMOutputError as exc:
                last_attempt_error = f"LLMOutputError: {exc}"
                ndjson.emit(
                    "llm_output_error", iteration=iteration, attempt=attempt,
                    error=str(exc),
                )
                if attempt < attempts:
                    continue
                outcome.error_code = exc.code
                outcome.reason = str(exc)
                outcome.finished_at = _utc_now_iso()
                ndjson.emit("iteration_failed", **asdict(outcome))
                return outcome

            try:
                proposal = validate_proposal_schema(proposal)
                outcome.proposal = proposal
                ndjson.emit(
                    "proposal_valid", iteration=iteration, attempt=attempt,
                    strategy_name=proposal.get("strategy_name"),
                    indicators=[s.get("alias") for s in proposal.get("indicators", [])],
                )
                break
            except JsonValidationError as exc:
                last_attempt_error = f"JsonValidationError: {exc}"
                ndjson.emit(
                    "json_validation_error", iteration=iteration, attempt=attempt,
                    error=str(exc),
                )
                if attempt < attempts:
                    continue
                outcome.error_code = exc.code
                outcome.reason = str(exc)
                outcome.finished_at = _utc_now_iso()
                ndjson.emit("iteration_failed", **asdict(outcome))
                return outcome

        # -- Step 3 : registry check ------------------------------------------
        outcome.phase_reached = "check_indicators"
        ndjson.emit("phase_start", iteration=iteration, phase="check_indicators")
        try:
            check_indicators_against_registry(proposal)
        except IndicatorNotFoundError as exc:
            outcome.error_code = exc.code
            outcome.reason = str(exc)
            outcome.finished_at = _utc_now_iso()
            ndjson.emit("iteration_failed", **asdict(outcome))
            return outcome

        # -- Step 4 : compile strategy ----------------------------------------
        outcome.phase_reached = "compile"
        ndjson.emit("phase_start", iteration=iteration, phase="compile")
        try:
            strategy = compile_strategy_from_proposal(proposal)
        except DslCompileError as exc:
            outcome.error_code = exc.code
            outcome.reason = str(exc)
            outcome.finished_at = _utc_now_iso()
            ndjson.emit("iteration_failed", **asdict(outcome))
            return outcome

        # -- Step 5 : dry-run validate ----------------------------------------
        outcome.phase_reached = "validate"
        ndjson.emit("phase_start", iteration=iteration, phase="validate")
        try:
            dry = dry_run_strategy(strategy, data)
            ndjson.emit("dry_run_ok", iteration=iteration, **dry)
        except (DslCompileError, StrategyValidationError) as exc:
            outcome.error_code = getattr(exc, "code", "ERR_STRATEGY")
            outcome.reason = str(exc)
            outcome.finished_at = _utc_now_iso()
            ndjson.emit("iteration_failed", **asdict(outcome))
            return outcome

        # -- Step 6 : run backtest --------------------------------------------
        outcome.phase_reached = "backtest"
        ndjson.emit("phase_start", iteration=iteration, phase="backtest")
        t0 = time.perf_counter()
        try:
            run_result = self.engine.run(
                df=data, strategy=strategy, params=None,
                symbol=symbol, timeframe=timeframe, silent_mode=True,
                fast_metrics=True,
            )
        except (ValueError, KeyError, TypeError, RuntimeError, ArithmeticError) as exc:
            outcome.error_code = BacktestExecutionError.code
            outcome.reason = f"backtest exception: {exc}"
            outcome.backtest_latency_s = time.perf_counter() - t0
            outcome.finished_at = _utc_now_iso()
            ndjson.emit("iteration_failed", **asdict(outcome))
            return outcome
        outcome.backtest_latency_s = time.perf_counter() - t0
        outcome.metrics = dict(run_result.metrics)
        outcome.metrics["n_trades"] = int(len(run_result.trades))

        # -- Step 7+8 : diagnose + decide ------------------------------------
        outcome.phase_reached = "diagnose"
        outcome.diagnosis = diagnose(outcome.metrics, self.criteria)
        status, reason = decide(
            outcome.diagnosis, iteration=iteration, max_iterations=self.max_iterations,
        )
        outcome.status = status
        outcome.reason = reason
        outcome.finished_at = _utc_now_iso()

        # -- Step 9 : log ----------------------------------------------------
        ndjson.emit("iteration_done", **asdict(outcome))
        return outcome

    # ---- API publique --------------------------------------------------------

    def build(
        self,
        *,
        objective: str,
        data: pd.DataFrame,
        symbol: str = "UNKNOWN",
        timeframe: str = "1m",
    ) -> SessionOutcome:
        """Lance une session complete. Aucune relance externe, jamais."""
        if not isinstance(data, pd.DataFrame) or data.empty:
            raise BacktestExecutionError("data doit etre un DataFrame non-vide")
        for col in ("open", "high", "low", "close"):
            if col not in data.columns:
                raise BacktestExecutionError(f"colonne OHLCV manquante: {col!r}")

        session_id = (
            datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            + f"_simple_{uuid.uuid4().hex[:8]}"
        )
        session = SessionOutcome(
            session_id=session_id, objective=objective,
            final_status="exhausted", started_at=_utc_now_iso(),
        )
        ndjson_path = self._sessions_dir / f"{session_id}.ndjson"
        ndjson = _NdjsonLogger(ndjson_path)
        ndjson.emit(
            "session_start", session_id=session_id, objective=objective,
            symbol=symbol, timeframe=timeframe, n_bars=len(data),
            criteria=self.criteria, max_iterations=self.max_iterations,
        )

        last_reason: str | None = None
        for i in range(1, self.max_iterations + 1):
            outcome = self._run_iteration(
                iteration=i, objective=objective, data=data,
                last_failure_reason=last_reason, ndjson=ndjson,
                symbol=symbol, timeframe=timeframe,
            )
            session.iterations.append(outcome)
            if outcome.status == "accepted":
                session.final_status = "accepted"
                session.accepted_iteration = i
                break
            if outcome.status == "stop":
                session.final_status = "stopped"
                break
            last_reason = (
                f"iteration {i} status={outcome.status} reason={outcome.reason}"
            )

        session.finished_at = _utc_now_iso()
        ndjson.emit(
            "session_end", session_id=session_id,
            final_status=session.final_status,
            accepted_iteration=session.accepted_iteration,
            best_metrics=session.best_metrics(),
        )
        return session


__all__ = [
    "BacktestExecutionError",
    "DslCompileError",
    "IndicatorNotFoundError",
    "IterationOutcome",
    "JsonValidationError",
    "LLMOutputError",
    "SessionOutcome",
    "SimpleBuilder",
    "SimpleBuilderError",
    "StrategyValidationError",
    "DEFAULT_ACCEPT_CRITERIA",
    "compile_strategy_from_proposal",
    "validate_proposal_schema",
    "check_indicators_against_registry",
    "diagnose",
    "decide",
]
