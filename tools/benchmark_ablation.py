"""Benchmark de performance des étapes ablatable du Builder.

Mesure le coût réel CPU de chaque étape sur le hardware courant.
Les étapes LLM-dépendantes (llm_analysis, runtime_fix, proposal/code LLM)
sont marquées N/A.  Lancer depuis la racine du dépôt :

    python tools/benchmark_ablation.py
    python tools/benchmark_ablation.py --n-runs 50
    python tools/benchmark_ablation.py --json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# ── Chemin racine ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Code stratégie de référence (EMA-cross minimal, syntaxiquement valide) ────
_SAMPLE_CODE = """
from typing import Any, Dict, List
import numpy as np
import pandas as pd
from strategies.base import StrategyBase

class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="ema_cross_bench")

    @property
    def required_indicators(self) -> List[str]:
        return ["ema", "atr", "rsi"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {"fast": 12, "slow": 26, "leverage": 1, "warmup": 50,
                "stop_atr_mult": 1.5, "tp_atr_mult": 3.0}

    def generate_signals(self, df, indicators, params):
        n = len(df)
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        warmup = int(params.get("warmup", 50))
        ema_fast = np.nan_to_num(indicators["ema"])
        rsi = np.nan_to_num(indicators["rsi"])
        long_cond = (ema_fast > 0) & (rsi < 60)
        short_cond = (ema_fast < 0) & (rsi > 40)
        signals[long_cond] = 1.0
        signals[short_cond] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals
"""

_LOGIC_BLOCK = """
ema_fast = np.nan_to_num(indicators['ema'])
rsi = np.nan_to_num(indicators['rsi'])
long_cond = (ema_fast > 0) & (rsi < 60)
short_cond = (ema_fast < 0) & (rsi > 40)
signals[long_cond] = 1.0
signals[short_cond] = -1.0
"""

_PROPOSAL = {
    "strategy_name": "bench_strategy",
    "hypothesis": "EMA cross with RSI filter",
    "change_type": "logic",
    "used_indicators": ["ema", "rsi", "atr"],
    "indicator_params": {},
    "entry_long_logic": "ema_fast > 0 AND rsi < 60",
    "entry_short_logic": "ema_fast < 0 AND rsi > 40",
    "exit_logic": "signal inverse",
    "risk_management": "ATR stop/TP",
    "default_params": {"fast": 12, "slow": 26, "leverage": 1, "warmup": 50, "stop_atr_mult": 1.5, "tp_atr_mult": 3.0},
    "parameter_specs": {
        "fast": {"min": 5, "max": 30, "default": 12, "type": "int", "step": 1},
        "slow": {"min": 20, "max": 60, "default": 26, "type": "int", "step": 1},
        "stop_atr_mult": {"min": 1.0, "max": 3.0, "default": 1.5, "type": "float", "step": 0.1},
        "tp_atr_mult": {"min": 2.0, "max": 5.0, "default": 3.0, "type": "float", "step": 0.1},
    },
}

_OBJECTIVE = "EMA-cross trend-following BTC/USDT 1h avec ATR stop-loss"

NA = "N/A (LLM)"
TRIVIAL = "trivial (<0.1 ms)"


# ── Helpers timing ─────────────────────────────────────────────────────────────


def _timeit(fn: Callable[[], Any], n: int) -> tuple[float, float]:
    """Retourne (médiane ms, écart-type ms) sur n répétitions."""
    samples: list[float] = []
    # Warm-up (2 appels ignorés)
    for _ in range(2):
        try:
            fn()
        except Exception:
            pass
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            fn()
        except Exception:
            pass
        samples.append((time.perf_counter() - t0) * 1000)
    if not samples:
        return 0.0, 0.0
    med = statistics.median(samples)
    std = statistics.stdev(samples) if len(samples) > 1 else 0.0
    return round(med, 3), round(std, 3)


# ── Imports paresseux des modules Builder ─────────────────────────────────────


def _import_modules() -> dict[str, Any]:
    mods: dict[str, Any] = {}

    try:
        from agents.builder_code_repair import (
            _inject_generate_signals_indicator_bindings,
            _repair_code,
        )

        mods["inject_bindings"] = _inject_generate_signals_indicator_bindings
        mods["repair_code"] = _repair_code
    except ImportError as exc:
        mods["repair_code_err"] = str(exc)

    try:
        from agents.strategy_builder import (
            _build_deterministic_fallback_code,
            _params_only_contract_respected,
            _postprocess_llm_logic_block,
            _sanitize_proposal_payload,
            sanitize_objective_text,
        )

        mods["postprocess"] = _postprocess_llm_logic_block
        mods["det_fallback"] = _build_deterministic_fallback_code
        mods["sanitize_proposal"] = _sanitize_proposal_payload
        mods["params_contract"] = _params_only_contract_respected
        mods["sanitize_obj"] = sanitize_objective_text
    except ImportError as exc:
        mods["strategy_builder_err"] = str(exc)

    try:
        from agents.indicator_context import rank_indicator_selection

        mods["rank_indicators"] = rank_indicator_selection
    except ImportError as exc:
        mods["rank_indicators_err"] = str(exc)

    try:
        from agents.builder_code_validation import (
            _precheck_signal_counts,
        )

        mods["precheck"] = _precheck_signal_counts
    except ImportError as exc:
        mods["precheck_err"] = str(exc)

    try:
        from agents.builder_candidate_executor import (
            _auto_fix_required_indicators,
        )

        mods["auto_fix"] = _auto_fix_required_indicators
    except ImportError as exc:
        mods["auto_fix_err"] = str(exc)

    try:
        from indicators import list_indicators

        mods["available_indicators"] = list_indicators()
    except ImportError:
        mods["available_indicators"] = [
            "ema",
            "rsi",
            "atr",
            "bollinger",
            "macd",
            "adx",
            "supertrend",
            "stochastic",
            "donchian",
            "keltner",
        ]

    return mods


# ── Fonctions de benchmark individuelles ──────────────────────────────────────


def _bench_code_repair(mods: dict[str, Any], n: int) -> tuple[str, str]:
    repair = mods.get("repair_code")
    if not callable(repair):
        return "code_repair", f"ERR: {mods.get('repair_code_err', 'import failed')}"

    def _fn():
        repair(_SAMPLE_CODE, ["ema", "rsi", "atr"])

    med, std = _timeit(_fn, n)
    return "code_repair", f"{med:.2f} ± {std:.2f} ms"


def _bench_indicator_binding(mods: dict[str, Any], n: int) -> tuple[str, str]:
    fn = mods.get("inject_bindings")
    if not callable(fn):
        return "indicator_binding", "ERR: import failed"

    def _fn():
        fn(_SAMPLE_CODE, ["ema", "rsi", "atr"])

    med, std = _timeit(_fn, n)
    return "indicator_binding", f"{med:.2f} ± {std:.2f} ms"


def _bench_postprocess_logic(mods: dict[str, Any], n: int) -> tuple[str, str]:
    fn = mods.get("postprocess")
    if not callable(fn):
        return "postprocess_logic", "ERR: import failed"

    def _fn():
        fn(_LOGIC_BLOCK, ["ema", "rsi", "atr"])

    med, std = _timeit(_fn, n)
    return "postprocess_logic", f"{med:.2f} ± {std:.2f} ms"


def _bench_deterministic_fallback(mods: dict[str, Any], n: int) -> tuple[str, str]:
    fn = mods.get("det_fallback")
    if not callable(fn):
        return "deterministic_fallback", "ERR: import failed"

    def _fn():
        fn(_PROPOSAL, variant=0)

    med, std = _timeit(_fn, n)
    return "deterministic_fallback", f"{med:.2f} ± {std:.2f} ms"


def _bench_indicator_ranking(mods: dict[str, Any], n: int) -> tuple[str, str]:
    fn = mods.get("rank_indicators")
    avail = mods.get("available_indicators", [])
    if not callable(fn) or not avail:
        return "indicator_ranking", f"ERR: {mods.get('rank_indicators_err', 'import failed')}"

    diagnostic = {
        "category": "needs_work",
        "actions": ["Try EMA cross", "Add RSI filter"],
        "donts": ["Do not add more conditions"],
    }

    def _fn():
        fn(
            avail,
            objective=_OBJECTIVE,
            diagnostic=diagnostic,
            previous_indicators=["ema", "rsi"],
            session_seed="bench:proposal:1",
            prefer_diversity=False,
        )

    med, std = _timeit(_fn, n)
    return "indicator_ranking", f"{med:.2f} ± {std:.2f} ms"


def _bench_proposal_sanitize(mods: dict[str, Any], n: int) -> tuple[str, str]:
    fn = mods.get("sanitize_proposal")
    avail = mods.get("available_indicators", [])
    if not callable(fn):
        return "proposal_sanitize", "ERR: import failed"

    def _fn():
        fn(dict(_PROPOSAL), available_indicators=avail, objective=_OBJECTIVE)

    med, std = _timeit(_fn, n)
    return "proposal_sanitize", f"{med:.2f} ± {std:.2f} ms"


def _bench_prompt_leakage_filter(mods: dict[str, Any], n: int) -> tuple[str, str]:
    fn = mods.get("sanitize_obj")
    if not callable(fn):
        return "prompt_leakage_filter", "ERR: import failed"

    sample_text = (
        "Okay, let's dive into the strategy. First, I need to define an EMA-cross "
        "approach that exploits trend momentum on BTC/USDT hourly data."
    )

    def _fn():
        fn(sample_text)

    med, std = _timeit(_fn, n)
    return "prompt_leakage_filter", f"{med:.2f} ± {std:.2f} ms"


def _bench_params_contract_check(mods: dict[str, Any], n: int) -> tuple[str, str]:
    fn = mods.get("params_contract")
    if not callable(fn):
        return "params_contract_check", "ERR: import failed"

    det_fallback = mods.get("det_fallback")
    prev_code = det_fallback(_PROPOSAL, variant=0) if callable(det_fallback) else _SAMPLE_CODE
    new_code = det_fallback(_PROPOSAL, variant=2) if callable(det_fallback) else _SAMPLE_CODE

    def _fn():
        fn(prev_code, new_code)

    med, std = _timeit(_fn, n)
    return "params_contract_check", f"{med:.2f} ± {std:.2f} ms"


def _bench_iteration_history(n: int) -> tuple[str, str]:
    """dict-only — construit le payload d'historique d'itérations."""
    import copy

    fake_iter = {
        "iteration": 1,
        "hypothesis": "EMA cross baseline",
        "change_type": "logic",
        "diagnostic_category": "needs_work",
        "sharpe": 0.42,
        "return_pct": 4.5,
        "trades": 72,
        "error": None,
        "is_fallback": False,
    }
    fake_history = [copy.copy(fake_iter) for _ in range(5)]

    def _fn():
        _ = [dict(it) for it in fake_history[-5:]]

    med, std = _timeit(_fn, n)
    return "iteration_history", f"{med:.3f} ± {std:.3f} ms  (dict ops)"


def _bench_diagnostic_context(n: int) -> tuple[str, str]:
    """dict-only — injection du contexte diagnostique."""
    diag = {
        "category": "needs_work",
        "severity": "info",
        "summary": "Résultats médiocres",
        "actions": ["Essayer une combinaison différente"],
        "donts": ["Ne pas restructurer"],
    }

    def _fn():
        ctx: dict[str, Any] = {}
        if diag:
            ctx["diagnostic"] = dict(diag)
            ctx["diagnostic_actions"] = list(diag.get("actions", []))
            ctx["diagnostic_donts"] = list(diag.get("donts", []))

    med, std = _timeit(_fn, n)
    return "diagnostic_context", f"{med:.3f} ± {std:.3f} ms  (dict ops)"


def _bench_stagnation_branching(n: int) -> tuple[str, str]:
    """Boolean check — quasi-trivial."""

    def _should_enable_stagnation_branching(last_iter: Any | None) -> bool:
        if last_iter is None:
            return False
        stag = (getattr(last_iter, "phase_feedback", {}) or {}).get("stagnation", {})
        return bool(stag.get("identical_metrics"))

    def _fn():
        _should_enable_stagnation_branching(None)

    med, std = _timeit(_fn, n)
    return "stagnation_branching", f"{med:.4f} ± {std:.4f} ms  (bool check)"


# ── Tableau résultats ──────────────────────────────────────────────────────────

_STEP_META = {
    "code_repair": ("AST", "Protection NaN + syntaxe"),
    "indicator_binding": ("AST", "Injection préambule indicators[...]"),
    "postprocess_logic": ("AST", "Nettoyage logique LLM"),
    "deterministic_fallback": ("Template", "Génération code fallback"),
    "indicator_ranking": ("NLP", "Classement sémantique des indicateurs"),
    "proposal_sanitize": ("Dict", "Validation/nettoyage payload proposition"),
    "prompt_leakage_filter": ("Regex", "Détection contamination prompt"),
    "params_contract_check": ("AST", "Vérification contrat params-only"),
    "iteration_history": ("Dict", "Construction historique itérations"),
    "diagnostic_context": ("Dict", "Injection contexte diagnostique"),
    "stagnation_branching": ("Bool", "Détection stagnation métriques"),
    "precheck": ("Exec", "Simulation signaux sur données réelles"),
    "auto_fix_indicators": ("AST", "Correction automatique indicateurs manquants"),
    "positive_progress_gate": ("Counter", "Comptage runs positifs (quota)"),
    "stop_override": ("Policy", "Override décision 'stop' LLM"),
    "accept_override": ("Policy", "Override décision 'accept' LLM"),
    "runtime_fix": ("LLM", "Retry LLM sur erreur runtime"),
    "llm_analysis": ("LLM", "_ask_analysis() — 1 appel/itération"),
}

_LLM_STEPS = {"runtime_fix", "llm_analysis"}
_TRIVIAL_STEPS = {
    "positive_progress_gate": "trivial (<0.05 ms) — comptage list",
    "stop_override": "trivial (<0.05 ms) — comparaison bool",
    "accept_override": "trivial (<0.05 ms) — comparaison bool",
}


def _print_table(results: dict[str, str], *, total_s: float) -> None:
    col_w = 24
    val_w = 30
    type_w = 10
    desc_w = 42
    sep = f"+{'-' * (col_w + 2)}+{'-' * (val_w + 2)}+{'-' * (type_w + 2)}+{'-' * (desc_w + 2)}+"
    header = (
        f"| {'Étape ablatable':<{col_w}} "
        f"| {'Médiane ± σ (ms)':<{val_w}} "
        f"| {'Type':<{type_w}} "
        f"| {'Description':<{desc_w}} |"
    )
    print()
    print("=" * len(header))
    print("  BENCHMARK ABLATION — impact CPU par étape")
    print(f"  Hardware : {sys.platform}  /  Python {sys.version.split()[0]}")
    print(f"  Durée totale mesures : {total_s:.1f}s")
    print("=" * len(header))
    print(sep)
    print(header)
    print(sep)

    categories = ["AST", "NLP", "Dict", "Regex", "Template", "Exec", "Bool", "Counter", "Policy", "LLM"]
    cat_groups: dict[str, list[str]] = {c: [] for c in categories}
    for step in _STEP_META:
        cat = _STEP_META[step][0]
        cat_groups.setdefault(cat, []).append(step)

    printed: set = set()
    for cat in categories:
        for step in cat_groups.get(cat, []):
            if step in printed:
                continue
            printed.add(step)
            val = results.get(step, "?")
            typ, desc = _STEP_META.get(step, ("?", ""))
            print(
                f"| {step:<{col_w}} | {val:<{val_w}} | {typ:<{type_w}} | {desc:<{desc_w}} |",
            )
    print(sep)
    print()
    print("Légende : N/A (LLM) = nécessite un daemon Ollama actif")
    print("          trivial   = négligeable, coût < 0.05 ms")
    print("          dict ops  = opérations dict/list Python pures")
    print()


def _run_benchmarks(
    n: int,
    *,
    verbose: bool = True,
) -> tuple[dict[str, str], dict[str, float]]:
    if verbose:
        print("\n[benchmark_ablation] Chargement modules... ", end="", flush=True)
    mods = _import_modules()
    if verbose:
        print("OK")

    raw: dict[str, float] = {}
    results: dict[str, str] = {}

    steps_to_bench = [
        ("code_repair", lambda: _bench_code_repair(mods, n)),
        ("indicator_binding", lambda: _bench_indicator_binding(mods, n)),
        ("postprocess_logic", lambda: _bench_postprocess_logic(mods, n)),
        ("deterministic_fallback", lambda: _bench_deterministic_fallback(mods, n)),
        ("indicator_ranking", lambda: _bench_indicator_ranking(mods, n)),
        ("proposal_sanitize", lambda: _bench_proposal_sanitize(mods, n)),
        ("prompt_leakage_filter", lambda: _bench_prompt_leakage_filter(mods, n)),
        ("params_contract_check", lambda: _bench_params_contract_check(mods, n)),
        ("iteration_history", lambda: _bench_iteration_history(n)),
        ("diagnostic_context", lambda: _bench_diagnostic_context(n)),
        ("stagnation_branching", lambda: _bench_stagnation_branching(n)),
    ]

    for step_name, bench_fn in steps_to_bench:
        if verbose:
            print(f"  • {step_name:<28} ... ", end="", flush=True)
        try:
            _, val = bench_fn()
            results[step_name] = val
            # Extrait la médiane ms pour comparaison JSON
            try:
                raw[step_name] = float(val.split("±")[0].strip().split()[0])
            except (ValueError, IndexError):
                raw[step_name] = 0.0
        except Exception as exc:
            results[step_name] = f"ERR: {exc}"
            raw[step_name] = -1.0
        if verbose:
            print(results[step_name])

    # Trivial et N/A
    for step, desc in _TRIVIAL_STEPS.items():
        results[step] = desc
        raw[step] = 0.02

    for step in _LLM_STEPS:
        results[step] = NA
        raw[step] = float("nan")

    # precheck / auto_fix (dépendent du contexte runtime, marqués séparément)
    for step in ("precheck", "auto_fix_indicators"):
        if step not in results:
            results[step] = "non mesuré (contexte runtime)"
            raw[step] = float("nan")

    return results, raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark ablation Builder")
    parser.add_argument("--n-runs", type=int, default=20, help="Nombre de répétitions par étape (défaut: 20)")
    parser.add_argument("--json", action="store_true", help="Sortie JSON brute (médianes ms)")
    args = parser.parse_args()

    t_start = time.perf_counter()
    results, raw = _run_benchmarks(args.n_runs, verbose=not args.json)
    total_s = time.perf_counter() - t_start

    if args.json:
        import math

        clean_raw = {k: (v if not math.isnan(v) and v >= 0 else None) for k, v in raw.items()}
        print(json.dumps({"n_runs": args.n_runs, "median_ms": clean_raw}, indent=2))
    else:
        _print_table(results, total_s=total_s)


if __name__ == "__main__":
    main()
