"""Module-ID: tools.benchmark_system

Purpose: Benchmark complet du système de backtest pour optimisation.

🚀 UTILISATION:
    python -m tools.benchmark_system
    python -m tools.benchmark_system --full
    python -m tools.benchmark_system --parallel-only

Teste:
1. Configuration CPU/RAM détectée
2. Performance Numba (séquentiel vs parallèle)
3. Performance joblib (différents workers/backends)
4. Performance sweep complet
5. Recommandations d'optimisation
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.model_loader import normalize_model_name

# psutil pour monitoring
try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

CANONICAL_LLM_BENCHMARK_TOKENS = [
    "BTCUSDC",
    "ETHUSDC",
    "BNBUSDC",
    "SOLUSDC",
    "XRPUSDC",
    "AVAXUSDC",
    "LINKUSDC",
    "ADAUSDC",
    "DOTUSDC",
    "ATOMUSDC",
    "MATICUSDC",
    "NEARUSDC",
    "FILUSDC",
    "APTUSDC",
    "ARBUSDC",
    "OPUSDC",
    "INJUSDC",
    "SUIUSDC",
    "LTCUSDC",
    "TRXUSDC",
    "DOGEUSDC",
    "BCHUSDC",
    "UNIUSDC",
]
DEFAULT_LLM_BENCHMARK_TIMEFRAME = "1h"
DEFAULT_LLM_BENCHMARK_ALLOWED_INDICATORS = [
    "ema",
    "sma",
    "rsi",
    "macd",
    "bollinger",
    "atr",
    "adx",
    "stochastic",
    "donchian",
    "keltner",
    "supertrend",
    "cci",
    "mfi",
]
LLM_BENCHMARK_PROMPT_VERSION = "token_matrix_v2_compact"


@dataclass
class SystemInfo:
    """Informations système."""

    cpu_physical: int
    cpu_logical: int
    ram_total_gb: float
    ram_available_gb: float
    numba_threads: int
    numba_version: str
    python_version: str


@dataclass
class BenchmarkResult:
    """Résultat d'un benchmark."""

    name: str
    time_ms: float
    throughput: float  # items/sec
    cpu_usage_pct: float
    ram_usage_gb: float
    config: dict[str, Any]


def get_system_info() -> SystemInfo:
    """Récupère les informations système."""
    import platform

    cpu_physical = os.cpu_count() or 4
    cpu_logical = cpu_physical

    if HAS_PSUTIL:
        cpu_physical = psutil.cpu_count(logical=False) or cpu_physical
        cpu_logical = psutil.cpu_count(logical=True) or cpu_logical
        ram_total = psutil.virtual_memory().total / (1024**3)
        ram_available = psutil.virtual_memory().available / (1024**3)
    else:
        ram_total = 8.0
        ram_available = 4.0

    # Numba info
    try:
        import numba

        numba_version = numba.__version__
        numba_threads = numba.get_num_threads()
    except ImportError:
        numba_version = "N/A"
        numba_threads = 1

    return SystemInfo(
        cpu_physical=cpu_physical,
        cpu_logical=cpu_logical,
        ram_total_gb=ram_total,
        ram_available_gb=ram_available,
        numba_threads=numba_threads,
        numba_version=numba_version,
        python_version=platform.python_version(),
    )


def print_system_info(info: SystemInfo):
    """Affiche les informations système."""
    print("\n" + "=" * 60)
    print("🖥️  CONFIGURATION SYSTÈME")
    print("=" * 60)
    print(f"  CPU Physical cores:    {info.cpu_physical}")
    print(f"  CPU Logical cores:     {info.cpu_logical} (SMT/HT)")
    print(f"  RAM Total:             {info.ram_total_gb:.1f} GB")
    print(f"  RAM Available:         {info.ram_available_gb:.1f} GB")
    print(f"  Numba version:         {info.numba_version}")
    print(f"  Numba threads:         {info.numba_threads}")
    print(f"  Python version:        {info.python_version}")
    print("=" * 60)


def generate_test_data(n_bars: int = 10000) -> pd.DataFrame:
    """Génère des données OHLCV de test."""
    np.random.seed(42)

    # Générer des prix réalistes
    returns = np.random.randn(n_bars) * 0.02
    close = 100 * np.exp(np.cumsum(returns))

    high = close * (1 + np.abs(np.random.randn(n_bars) * 0.01))
    low = close * (1 - np.abs(np.random.randn(n_bars) * 0.01))
    open_price = low + (high - low) * np.random.rand(n_bars)
    volume = np.random.randint(1000, 100000, n_bars)

    return pd.DataFrame(
        {
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
    )


def benchmark_numba(df: pd.DataFrame) -> list[BenchmarkResult]:
    """Benchmark du sweep Numba (intégré dans backtest/sweep_numba.py)."""
    try:
        from backtest.sweep_numba import HAS_NUMBA, benchmark_sweep_numba

        if not HAS_NUMBA:
            print("\n⚠️ Numba non disponible, skip benchmark")
            return []
    except ImportError:
        print("\n⚠️ Module sweep_numba non trouvé")
        return []

    results = []

    print("\n" + "-" * 60)
    print("🔢 BENCHMARK NUMBA SWEEP (Parallélisation complète)")
    print("-" * 60)

    # Benchmark avec différentes tailles
    for n_combos, n_bars in [(100, 5000), (500, 10000), (1000, 10000)]:
        result = benchmark_sweep_numba(n_combos=n_combos, n_bars=n_bars)
        results.append(
            BenchmarkResult(
                name=f"Numba sweep ({n_combos} combos × {n_bars} bars)",
                time_ms=result["total_time"] * 1000,
                throughput=result["throughput"],
                cpu_usage_pct=0,
                ram_usage_gb=0,
                config={"n_combos": n_combos, "n_bars": n_bars},
            ),
        )

    return results


def benchmark_parallel_sweep(df: pd.DataFrame, n_combos: int = 100) -> list[BenchmarkResult]:
    """Benchmark du sweep parallèle avec différentes configurations."""
    from performance.parallel import ParallelRunner, generate_param_grid

    results = []

    # Générer grille de paramètres
    param_grid = generate_param_grid(
        {
            "bb_period": list(range(15, 35, 5)),
            "bb_std": [1.5, 2.0, 2.5],
            "atr_period": [10, 14, 21],
        },
    )[:n_combos]

    # Fonction de backtest simplifiée
    def dummy_backtest(params, data=None):
        # Simuler un backtest (~5-10ms)
        time.sleep(0.005)
        return {"params": params, "sharpe": np.random.rand()}

    # Configurations à tester
    worker_configs = [8, 16, 24, 32]

    print("\n" + "-" * 60)
    print(f"⚡ BENCHMARK SWEEP PARALLÈLE ({n_combos} combinaisons)")
    print("-" * 60)

    for n_workers in worker_configs:
        runner = ParallelRunner(
            max_workers=n_workers,
            backend="loky",
            chunk_size=50,
        )

        start = time.perf_counter()
        sweep_result = runner.run_sweep(dummy_backtest, param_grid, data=df)
        elapsed = time.perf_counter() - start

        throughput = n_combos / elapsed

        result = BenchmarkResult(
            name=f"Sweep {n_workers} workers",
            time_ms=elapsed * 1000,
            throughput=throughput,
            cpu_usage_pct=0,
            ram_usage_gb=sweep_result.memory_peak_gb or 0,
            config={"n_workers": n_workers, "n_combos": n_combos},
        )
        results.append(result)

        print(f"  {result.name}: {result.time_ms:.0f} ms ({throughput:.1f} backtests/s)")

    return results


def benchmark_real_backtest(df: pd.DataFrame, n_runs: int = 50) -> list[BenchmarkResult]:
    """Benchmark avec de vrais backtests."""
    try:
        from backtest.engine import BacktestEngine
    except ImportError as e:
        print(f"⚠️ Import backtest échoué: {e}")
        return []

    results = []

    print("\n" + "-" * 60)
    print(f"📊 BENCHMARK BACKTEST RÉEL ({n_runs} runs)")
    print("-" * 60)

    # Paramètres de test
    params = {
        "bb_period": 20,
        "bb_std": 2.0,
        "atr_period": 14,
        "leverage": 1,
    }

    # Test séquentiel
    start = time.perf_counter()
    for _ in range(n_runs):
        try:
            engine = BacktestEngine(strategy_name="bollinger_atr")
            _ = engine.run(df, params)
        except Exception as e:
            print(f"  Erreur backtest: {e}")
            break
    seq_time = time.perf_counter() - start

    if seq_time > 0:
        result = BenchmarkResult(
            name="Backtest séquentiel",
            time_ms=seq_time * 1000,
            throughput=n_runs / seq_time,
            cpu_usage_pct=0,
            ram_usage_gb=0,
            config={"n_runs": n_runs, "n_bars": len(df)},
        )
        results.append(result)
        print(f"  {result.name}: {result.time_ms:.0f} ms total ({result.throughput:.1f} runs/s)")

    return results


def print_recommendations(info: SystemInfo, results: list[BenchmarkResult]):
    """Affiche les recommandations d'optimisation."""
    print("\n" + "=" * 60)
    print("💡 RECOMMANDATIONS D'OPTIMISATION")
    print("=" * 60)

    # Recommandations CPU
    optimal_workers = min(info.cpu_logical, int(info.cpu_physical * 2.5))
    print("\n🔧 Configuration CPU recommandée:")
    print(f"   BACKTEST_CPU_MULTIPLIER=2.0  (actuellement {info.cpu_physical * 2} workers)")
    print(f"   Workers optimaux: {optimal_workers}")

    # Recommandations Numba
    if info.numba_threads < info.cpu_logical:
        print("\n🔧 Configuration Numba:")
        print(f"   NUMBA_NUM_THREADS={info.cpu_logical}  (actuellement {info.numba_threads})")

    # Recommandations RAM
    if info.ram_total_gb >= 32:
        print(f"\n🔧 Configuration RAM ({info.ram_total_gb:.0f} GB DDR5):")
        print("   JOBLIB_MAX_NBYTES=500M  (copies directes en RAM)")
        print("   Pré-chargement données en RAM recommandé")

    # Trouver la meilleure config de sweep
    sweep_results = [r for r in results if "Sweep" in r.name]
    if sweep_results:
        best = max(sweep_results, key=lambda r: r.throughput)
        print("\n🏆 Meilleure configuration sweep:")
        print(f"   {best.name}: {best.throughput:.1f} backtests/sec")

    # Variables d'environnement recommandées
    print("\n📝 Variables d'environnement (.env):")
    print("-" * 40)
    print("BACKTEST_CPU_MULTIPLIER=2.0")
    print(f"NUMBA_NUM_THREADS={info.cpu_logical}")
    print("NUMBA_CACHE_DIR=.numba_cache")
    print("JOBLIB_MAX_NBYTES=500M")
    print("JOBLIB_VERBOSE=0")
    print(f"OMP_NUM_THREADS={info.cpu_logical}")
    print(f"MKL_NUM_THREADS={info.cpu_logical}")
    print("-" * 40)

    print("\n" + "=" * 60)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _extract_model_size_b(model_name: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)b", str(model_name or "").lower())
    if not match:
        return -1.0
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return -1.0


def _trim_text(value: Any, max_chars: int = 280) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _extract_json_payload(raw_text: str) -> tuple[Any | None, str]:
    text = str(raw_text or "").strip()
    if not text:
        return None, "empty_response"

    def _attempt_literal_eval(candidate: str, mode: str) -> tuple[Any | None, str]:
        try:
            return ast.literal_eval(candidate), mode
        except (SyntaxError, ValueError):
            return None, mode

    try:
        return json.loads(text), "direct"
    except json.JSONDecodeError:
        pass

    payload, mode = _attempt_literal_eval(text, "python_literal")
    if payload is not None:
        return payload, mode

    fenced_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fenced_match:
        candidate = fenced_match.group(1).strip()
        try:
            return json.loads(candidate), "markdown_fence"
        except json.JSONDecodeError:
            pass
        payload, mode = _attempt_literal_eval(candidate, "markdown_python_literal")
        if payload is not None:
            return payload, mode

    object_match = re.search(r"\{[\s\S]*\}", text)
    if object_match:
        candidate = object_match.group(0).strip()
        try:
            return json.loads(candidate), "object_slice"
        except json.JSONDecodeError:
            pass
        payload, mode = _attempt_literal_eval(candidate, "object_python_literal")
        if payload is not None:
            return payload, mode

    array_match = re.search(r"\[[\s\S]*\]", text)
    if array_match:
        candidate = array_match.group(0).strip()
        try:
            return json.loads(candidate), "array_slice"
        except json.JSONDecodeError:
            pass
        payload, mode = _attempt_literal_eval(candidate, "array_python_literal")
        if payload is not None:
            return payload, mode

    return None, "invalid_json"


def _coerce_token_items(payload: Any) -> list[Any] | None:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return None

    for key in ("tokens", "results", "proposals", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return value

    nested_value = None
    for key in ("response", "content", "output", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested_items = _coerce_token_items(value)
            if nested_items is not None:
                return nested_items
        if isinstance(value, str) and value.strip():
            nested_value = value
            break

    if nested_value:
        nested_payload, _mode = _extract_json_payload(nested_value)
        if nested_payload is not None:
            nested_items = _coerce_token_items(nested_payload)
            if nested_items is not None:
                return nested_items

    if {"token", "used_indicators"}.issubset(payload.keys()):
        return [payload]

    return None


def _messages_to_generate_prompt(system_prompt: str, user_prompt: str, json_mode: bool) -> str:
    lines = []
    if system_prompt.strip():
        lines.append(f"System: {system_prompt.strip()}")
    if user_prompt.strip():
        lines.append(f"User: {user_prompt.strip()}")
    if json_mode:
        lines.append("System: Respond with valid JSON only.")
    lines.append("Assistant:")
    return "\n".join(lines)


def _ollama_generate_request(
    *,
    ollama_host: str,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout_s: float,
    json_mode: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model_name,
        "prompt": _messages_to_generate_prompt(system_prompt, user_prompt, json_mode),
        "stream": False,
        "keep_alive": "0m",
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "top_p": 0.9,
        },
    }
    if json_mode:
        payload["format"] = "json"

    start = time.perf_counter()
    try:
        response = httpx.post(
            f"{ollama_host}/api/generate",
            json=payload,
            timeout=timeout_s,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        body = _trim_text(getattr(response, "text", ""), max_chars=320)
        if response.status_code != 200:
            return {
                "ok": False,
                "transport": "generate",
                "status": "http_error",
                "error_type": "http_error",
                "http_status": response.status_code,
                "error_detail": body,
                "content": "",
                "latency_ms": latency_ms,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

        data = response.json() if response.content else {}
        prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
        completion_tokens = int(data.get("eval_count", 0) or 0)
        return {
            "ok": True,
            "transport": "generate",
            "status": "ok",
            "error_type": "success",
            "http_status": response.status_code,
            "error_detail": "",
            "content": str(data.get("response", "") or ""),
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    except httpx.TimeoutException:
        return {
            "ok": False,
            "transport": "generate",
            "status": "timeout",
            "error_type": "timeout",
            "http_status": None,
            "error_detail": f"timeout after {int(timeout_s)}s",
            "content": "",
            "latency_ms": (time.perf_counter() - start) * 1000,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "transport": "generate",
            "status": "request_error",
            "error_type": "request_error",
            "http_status": None,
            "error_detail": str(exc),
            "content": "",
            "latency_ms": (time.perf_counter() - start) * 1000,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }


def _ollama_chat_request(
    *,
    ollama_host: str,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    timeout_s: float,
    json_mode: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "keep_alive": "0m",
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "top_p": 0.9,
        },
    }
    if json_mode:
        payload["format"] = "json"

    start = time.perf_counter()
    try:
        response = httpx.post(
            f"{ollama_host}/api/chat",
            json=payload,
            timeout=timeout_s,
        )
        if response.status_code == 404:
            return _ollama_generate_request(
                ollama_host=ollama_host,
                model_name=model_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
                json_mode=json_mode,
            )

        latency_ms = (time.perf_counter() - start) * 1000
        body = _trim_text(getattr(response, "text", ""), max_chars=320)
        if response.status_code != 200:
            return {
                "ok": False,
                "transport": "chat",
                "status": "http_error",
                "error_type": "http_error",
                "http_status": response.status_code,
                "error_detail": body,
                "content": "",
                "latency_ms": latency_ms,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

        data = response.json() if response.content else {}
        prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
        completion_tokens = int(data.get("eval_count", 0) or 0)
        return {
            "ok": True,
            "transport": "chat",
            "status": "ok",
            "error_type": "success",
            "http_status": response.status_code,
            "error_detail": "",
            "content": str(data.get("message", {}).get("content", "") or ""),
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    except httpx.TimeoutException:
        return {
            "ok": False,
            "transport": "chat",
            "status": "timeout",
            "error_type": "timeout",
            "http_status": None,
            "error_detail": f"timeout after {int(timeout_s)}s",
            "content": "",
            "latency_ms": (time.perf_counter() - start) * 1000,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "transport": "chat",
            "status": "request_error",
            "error_type": "request_error",
            "http_status": None,
            "error_detail": str(exc),
            "content": "",
            "latency_ms": (time.perf_counter() - start) * 1000,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }


def _build_llm_token_matrix_prompt(
    tokens: list[str],
    timeframe: str,
    allowed_indicators: list[str],
) -> tuple[str, str]:
    tokens_csv = ", ".join(tokens)
    indicators_csv = ", ".join(allowed_indicators)
    system_prompt = (
        "You are an expert quantitative trading strategy designer for a backtest platform. "
        "Return ONLY valid JSON. No markdown, no commentary, no reasoning trace."
    )
    user_prompt = (
        f"Benchmark version: {LLM_BENCHMARK_PROMPT_VERSION}\n"
        "This is a strict contract benchmark.\n"
        f"Timeframe: {timeframe}\n"
        f"Tokens in exact required order: {tokens_csv}\n"
        f"Allowed indicators only: {indicators_csv}\n\n"
        "Return EXACTLY one JSON object with this schema:\n"
        "{\n"
        f'  "benchmark_name": "{LLM_BENCHMARK_PROMPT_VERSION}",\n'
        f'  "timeframe": "{timeframe}",\n'
        '  "tokens": [\n'
        "    {\n"
        '      "token": "BTCUSDC",\n'
        '      "used_indicators": ["ema", "rsi", "atr"],\n'
        '      "setup": "trend continuation after pullback above ema with rsi confirmation",\n'
        '      "risk_management": "1.5 ATR stop, 3 ATR target, no leverage"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        f"- The tokens array must contain exactly {len(tokens)} objects, one per token, preserving the exact order above.\n"
        "- No duplicate tokens, no missing tokens, no extra tokens.\n"
        "- used_indicators must contain 2 or 3 indicators chosen only from the allowed list.\n"
        "- setup and risk_management must both be non-empty plain strings.\n"
        "- Keep setup concise (max 18 words).\n"
        "- Keep risk_management concise (max 14 words).\n"
        "- Do not mention leverage above 1.\n"
        "- If confidence is low for a token, still return a valid compact object with a conservative no-trade style setup.\n"
        "- Output JSON only."
    )
    return system_prompt, user_prompt


def _validate_token_matrix_payload(
    payload: Any,
    expected_tokens: list[str],
    allowed_indicators: list[str],
) -> dict[str, Any]:
    token_items = _coerce_token_items(payload)

    if token_items is None:
        return {
            "status": "missing_tokens_array",
            "error_type": "missing_tokens_array",
            "coverage_ratio": 0.0,
            "matched_expected_count": 0,
            "valid_token_count": 0,
            "invalid_indicator_count": 0,
            "invalid_field_count": 0,
            "missing_tokens": list(expected_tokens),
            "extra_tokens": [],
            "duplicate_tokens": [],
            "issues": ["top_level_tokens_array_missing"],
            "token_records": [],
        }

    expected_set = set(expected_tokens)
    allowed_set = {str(indicator or "").strip().lower() for indicator in allowed_indicators}
    returned_counter: Counter[str] = Counter()
    token_records: list[dict[str, Any]] = []
    invalid_indicator_count = 0
    invalid_field_count = 0

    for index, item in enumerate(token_items):
        if not isinstance(item, dict):
            token_records.append(
                {
                    "index": index,
                    "token": "",
                    "valid": False,
                    "issues": ["item_not_object"],
                    "bad_indicators": [],
                },
            )
            invalid_field_count += 1
            continue

        token = str(item.get("token", "") or "").strip().upper()
        if token:
            returned_counter[token] += 1

        used_indicators_raw = item.get("used_indicators", [])
        if isinstance(used_indicators_raw, list):
            used_indicators = [
                str(value or "").strip().lower() for value in used_indicators_raw if str(value or "").strip()
            ]
        else:
            used_indicators = []

        bad_indicators = [indicator for indicator in used_indicators if indicator not in allowed_set]
        issues: list[str] = []
        if token not in expected_set:
            issues.append("unexpected_token")
        if not token:
            issues.append("missing_token")
        if len(used_indicators) < 2 or len(used_indicators) > 3:
            issues.append("used_indicators_count")
        if bad_indicators:
            issues.append("invalid_indicators")

        for field_name in ("setup", "risk_management"):
            value = str(item.get(field_name, "") or "").strip()
            if not value:
                issues.append(f"missing_{field_name}")

        if bad_indicators:
            invalid_indicator_count += len(bad_indicators)
        invalid_field_count += sum(1 for issue in issues if issue.startswith("missing_"))

        token_records.append(
            {
                "index": index,
                "token": token,
                "valid": not issues,
                "issues": issues,
                "bad_indicators": bad_indicators,
            },
        )

    missing_tokens = [token for token in expected_tokens if returned_counter[token] == 0]
    extra_tokens = sorted(token for token in returned_counter if token not in expected_set)
    duplicate_tokens = sorted(token for token, count in returned_counter.items() if count > 1)
    valid_token_count = sum(1 for record in token_records if record.get("valid"))
    matched_expected_count = len(expected_tokens) - len(missing_tokens)
    coverage_ratio = matched_expected_count / max(len(expected_tokens), 1)

    issues: list[str] = []
    if missing_tokens:
        issues.append("missing_tokens")
    if extra_tokens:
        issues.append("extra_tokens")
    if duplicate_tokens:
        issues.append("duplicate_tokens")
    if invalid_indicator_count > 0:
        issues.append("invalid_indicators")
    if invalid_field_count > 0:
        issues.append("missing_required_fields")
    if any("item_not_object" in record.get("issues", []) for record in token_records):
        issues.append("item_not_object")

    if not issues and valid_token_count == len(expected_tokens):
        status = "success"
        error_type = "success"
    elif missing_tokens or extra_tokens or duplicate_tokens:
        status = "token_set_mismatch"
        error_type = "token_set_mismatch"
    elif invalid_indicator_count > 0:
        status = "invalid_indicators"
        error_type = "invalid_indicators"
    else:
        status = "schema_violation"
        error_type = "schema_violation"

    return {
        "status": status,
        "error_type": error_type,
        "coverage_ratio": coverage_ratio,
        "matched_expected_count": matched_expected_count,
        "valid_token_count": valid_token_count,
        "invalid_indicator_count": invalid_indicator_count,
        "invalid_field_count": invalid_field_count,
        "missing_tokens": missing_tokens,
        "extra_tokens": extra_tokens,
        "duplicate_tokens": duplicate_tokens,
        "issues": issues,
        "token_records": token_records,
    }


def _evaluate_chat_attempt(
    chat_result: dict[str, Any],
    expected_tokens: list[str],
    allowed_indicators: list[str],
) -> dict[str, Any]:
    if not chat_result.get("ok"):
        validation = {
            "status": str(chat_result.get("status") or "request_error"),
            "error_type": str(chat_result.get("error_type") or "request_error"),
            "coverage_ratio": 0.0,
            "matched_expected_count": 0,
            "valid_token_count": 0,
            "invalid_indicator_count": 0,
            "invalid_field_count": 0,
            "missing_tokens": list(expected_tokens),
            "extra_tokens": [],
            "duplicate_tokens": [],
            "issues": [str(chat_result.get("error_detail") or "request_failed")],
            "token_records": [],
        }
        return {
            "chat": chat_result,
            "payload": None,
            "parse_mode": "not_attempted",
            "validation": validation,
            "status": validation["status"],
            "error_type": validation["error_type"],
        }

    payload, parse_mode = _extract_json_payload(str(chat_result.get("content", "") or ""))
    if payload is None:
        validation = {
            "status": "invalid_json",
            "error_type": "invalid_json",
            "coverage_ratio": 0.0,
            "matched_expected_count": 0,
            "valid_token_count": 0,
            "invalid_indicator_count": 0,
            "invalid_field_count": 0,
            "missing_tokens": list(expected_tokens),
            "extra_tokens": [],
            "duplicate_tokens": [],
            "issues": [parse_mode],
            "token_records": [],
        }
    else:
        validation = _validate_token_matrix_payload(payload, expected_tokens, allowed_indicators)

    return {
        "chat": chat_result,
        "payload": payload,
        "parse_mode": parse_mode,
        "validation": validation,
        "status": validation["status"],
        "error_type": validation["error_type"],
    }


def _attempt_score(attempt: dict[str, Any]) -> tuple[int, float, int]:
    validation = attempt.get("validation", {})
    status = str(validation.get("status") or "")
    if status == "success":
        return (
            3,
            float(validation.get("coverage_ratio", 0.0) or 0.0),
            int(validation.get("valid_token_count", 0) or 0),
        )
    if attempt.get("chat", {}).get("ok"):
        return (
            2,
            float(validation.get("coverage_ratio", 0.0) or 0.0),
            int(validation.get("valid_token_count", 0) or 0),
        )
    return (1, 0.0, 0)


def _build_llm_candidate_inventory(model_filter: str = "") -> list[dict[str, Any]]:
    from agents.model_config import list_available_models

    catalog_infos = list_available_models()
    info_by_name: dict[str, Any] = {}
    for info in catalog_infos:
        normalized_name = normalize_model_name(getattr(info, "name", "")) or str(getattr(info, "name", "") or "")
        if normalized_name:
            info_by_name[normalized_name] = info

    pattern = re.compile(model_filter, re.IGNORECASE) if model_filter else None
    candidates: list[dict[str, Any]] = []
    for normalized_name in sorted(info_by_name.keys()):
        info = info_by_name[normalized_name]
        description = str(getattr(info, "description", "") or "")
        if pattern and not pattern.search(" ".join([normalized_name, description])):
            continue
        params_billions = float(getattr(info, "params_billions", 0.0) or 0.0)
        if params_billions <= 0:
            params_billions = _extract_model_size_b(normalized_name)
        category = str(getattr(getattr(info, "category", None), "value", "unknown") or "unknown")
        if category == "unknown":
            if params_billions >= 30:
                category = "heavy"
            elif params_billions >= 10:
                category = "medium"
            elif params_billions > 0:
                category = "light"
        cloud_billed = bool(getattr(info, "cloud_only", False)) or normalized_name.endswith("-cloud")
        requires_manual_approval = bool(getattr(info, "requires_manual_approval", False)) or params_billions > 50.0
        candidates.append(
            {
                "canonical_name": normalized_name,
                "requested_name": normalized_name,
                "runtime_name": "",
                "description": description,
                "category": category,
                "params_billions": params_billions,
                "cloud_billed": cloud_billed,
                "requires_manual_approval": requires_manual_approval,
            },
        )
    return candidates


def _default_llm_benchmark_output_path(explicit_output: str) -> Path:
    if explicit_output.strip():
        return Path(explicit_output.strip())
    analysis_dir = Path("backtest_results") / "_analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return analysis_dir / f"llm_token_matrix_benchmark_{stamp}.json"


def _summarize_llm_benchmark(
    probe_records: list[dict[str, Any]],
    run_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    probe_status_counts = Counter(record.get("probe_status", "unknown") for record in probe_records)
    chat_policy_counts = Counter(record.get("chat_policy", "unknown") for record in probe_records)
    run_status_counts = Counter(row.get("status", "unknown") for row in run_rows)
    error_type_counts = Counter(
        row.get("error_type", "unknown") for row in run_rows if row.get("error_type") not in {None, "success"}
    )
    missing_token_counts: Counter[str] = Counter()
    invalid_indicator_counts: Counter[str] = Counter()
    per_model_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in run_rows:
        model_name = str(row.get("model_name", "") or "")
        if model_name:
            per_model_rows[model_name].append(row)
        missing_token_counts.update(row.get("missing_tokens", []))
        for token_record in row.get("token_records", []):
            for indicator in token_record.get("bad_indicators", []):
                invalid_indicator_counts[str(indicator)] += 1

    model_summaries: list[dict[str, Any]] = []
    for model_name, rows in per_model_rows.items():
        attempts = len(rows)
        success_runs = sum(1 for row in rows if row.get("status") == "success")
        avg_latency_ms = sum(float(row.get("latency_ms", 0.0) or 0.0) for row in rows) / max(attempts, 1)
        avg_coverage_ratio = sum(float(row.get("coverage_ratio", 0.0) or 0.0) for row in rows) / max(attempts, 1)
        avg_valid_tokens = sum(int(row.get("valid_token_count", 0) or 0) for row in rows) / max(attempts, 1)
        fallback_runs = sum(1 for row in rows if bool(row.get("fallback_selected", False)))
        sample = rows[0]
        model_summaries.append(
            {
                "model_name": model_name,
                "canonical_name": sample.get("canonical_name", model_name),
                "category": sample.get("category", "unknown"),
                "params_billions": float(sample.get("params_billions", 0.0) or 0.0),
                "cloud_billed": bool(sample.get("cloud_billed", False)),
                "requires_manual_approval": bool(sample.get("requires_manual_approval", False)),
                "attempts": attempts,
                "success_runs": success_runs,
                "success_rate": success_runs / max(attempts, 1),
                "avg_latency_ms": avg_latency_ms,
                "avg_coverage_ratio": avg_coverage_ratio,
                "avg_valid_tokens": avg_valid_tokens,
                "fallback_runs": fallback_runs,
            },
        )

    model_summaries.sort(
        key=lambda item: (
            -float(item.get("success_rate", 0.0) or 0.0),
            -float(item.get("avg_coverage_ratio", 0.0) or 0.0),
            float(item.get("avg_latency_ms", 0.0) or 0.0),
            str(item.get("model_name", "")),
        ),
    )

    return {
        "probe_models": len(probe_records),
        "probe_status_counts": dict(probe_status_counts),
        "chat_policy_counts": dict(chat_policy_counts),
        "executed_runs": len(run_rows),
        "run_status_counts": dict(run_status_counts),
        "error_type_counts": dict(error_type_counts),
        "successful_models": sum(1 for item in model_summaries if item.get("success_runs", 0) > 0),
        "model_summaries": model_summaries,
        "top_models": model_summaries[:10],
        "missing_token_counts": dict(missing_token_counts.most_common(10)),
        "invalid_indicator_counts": dict(invalid_indicator_counts.most_common(10)),
    }


def _render_llm_benchmark_markdown(payload: dict[str, Any]) -> str:
    summary = dict(payload.get("summary", {}) or {})
    config = dict(payload.get("config", {}) or {})
    probe_records = list(payload.get("probe_records", []) or [])
    token_universe = list(payload.get("token_universe", []) or [])
    lines = [
        "# LLM Token Matrix Benchmark",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Ollama host: {config.get('ollama_host', '')}",
        f"- Timeframe: {config.get('timeframe', '')}",
        f"- Tokens: {len(token_universe)}",
        f"- Runs per model: {config.get('runs_per_model', 0)}",
        f"- Probe models: {summary.get('probe_models', 0)}",
        f"- Executed runs: {summary.get('executed_runs', 0)}",
        "",
        "## Probe Policies",
        "",
    ]
    for key, value in dict(summary.get("chat_policy_counts", {}) or {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Common Errors", ""])
    error_counts = dict(summary.get("error_type_counts", {}) or {})
    if error_counts:
        for key, value in error_counts.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- Aucun échec d'exécution enregistré.")

    lines.extend(["", "## Top Models", ""])
    top_models = list(summary.get("top_models", []) or [])
    if top_models:
        for item in top_models:
            lines.append(
                "- {model} | success={success}/{attempts} | coverage={coverage:.2%} | latency={latency:.0f}ms".format(
                    model=item.get("model_name", "?"),
                    success=int(item.get("success_runs", 0) or 0),
                    attempts=int(item.get("attempts", 0) or 0),
                    coverage=float(item.get("avg_coverage_ratio", 0.0) or 0.0),
                    latency=float(item.get("avg_latency_ms", 0.0) or 0.0),
                ),
            )
    else:
        lines.append("- Aucun modèle n'a été exécuté.")

    probe_only = [record for record in probe_records if record.get("chat_policy") != "full"]
    lines.extend(["", "## Probe Only / Skipped", ""])
    if probe_only:
        for record in probe_only[:20]:
            lines.append(
                "- {model} | policy={policy} | probe={probe} | {message}".format(
                    model=record.get("requested_name", "?"),
                    policy=record.get("chat_policy", "?"),
                    probe=record.get("probe_status", "?"),
                    message=_trim_text(record.get("probe_message", ""), max_chars=160),
                ),
            )
    else:
        lines.append("- Aucun modèle en probe-only.")

    return "\n".join(lines) + "\n"


def _persist_llm_benchmark_payload(output_path: Path, payload: dict[str, Any]) -> None:
    from tools.generate_html_report import generate_llm_benchmark_html_report

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    markdown_path = output_path.with_suffix(".md")
    with open(markdown_path, "w", encoding="utf-8") as handle:
        handle.write(_render_llm_benchmark_markdown(payload))

    html_payload = dict(payload)
    html_payload["__source_path"] = str(output_path)
    generate_llm_benchmark_html_report(html_payload, output_path.with_suffix(".html"))


def run_llm_token_matrix_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    from agents.ollama_manager import (
        cleanup_all_models,
        ensure_ollama_running,
        list_ollama_models,
        probe_model_runtime_acceptance,
        stop_owned_local_ollama_server,
        warmup_model,
    )
    from data.loader import discover_available_data
    from indicators.registry import list_indicators

    ollama_host = str(args.llm_ollama_host or "http://127.0.0.1:11434").strip()
    runs_per_model = max(1, int(args.llm_runs or 1))
    timeout_s = float(max(10, int(args.llm_timeout or 120)))
    max_tokens = max(256, int(args.llm_max_tokens or 2400))
    temperature = float(args.llm_temperature or 0.2)
    keep_alive_minutes = max(1, int(args.llm_keep_alive_minutes or 10))
    output_path = _default_llm_benchmark_output_path(str(args.llm_output or ""))

    available_tokens, available_timeframes = discover_available_data()
    missing_tokens = [token for token in CANONICAL_LLM_BENCHMARK_TOKENS if token not in available_tokens]
    if missing_tokens:
        raise RuntimeError(
            "Tokens benchmark manquants dans les données: " + ", ".join(missing_tokens),
        )
    if args.llm_timeframe not in available_timeframes:
        raise RuntimeError(
            f"Timeframe benchmark indisponible: {args.llm_timeframe}. Disponibles: {available_timeframes}",
        )

    available_indicator_names = set(list_indicators())
    allowed_indicators = [
        indicator for indicator in DEFAULT_LLM_BENCHMARK_ALLOWED_INDICATORS if indicator in available_indicator_names
    ]
    if not allowed_indicators:
        allowed_indicators = list(DEFAULT_LLM_BENCHMARK_ALLOWED_INDICATORS)

    system_prompt, user_prompt = _build_llm_token_matrix_prompt(
        CANONICAL_LLM_BENCHMARK_TOKENS,
        args.llm_timeframe,
        allowed_indicators,
    )

    ok, msg = ensure_ollama_running(ollama_host=ollama_host)
    if not ok:
        raise RuntimeError(msg)

    probe_records: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    payload: dict[str, Any] = {}

    try:
        tags_status_code: int | None = None
        tags_payload: dict[str, Any] | None = None
        try:
            tags_response = httpx.get(f"{ollama_host}/api/tags", timeout=8.0)
            tags_status_code = tags_response.status_code
            if tags_response.status_code == 200:
                tags_payload = tags_response.json() if tags_response.content else {}
        except Exception:
            tags_payload = None

        runtime_models_exact = list_ollama_models(ollama_host=ollama_host)
        runtime_models_by_norm = {normalize_model_name(name) or str(name): str(name) for name in runtime_models_exact}
        candidates = _build_llm_candidate_inventory(model_filter=str(args.llm_model_filter or ""))

        for candidate in candidates:
            canonical_name = str(candidate["canonical_name"])
            runtime_name = runtime_models_by_norm.get(canonical_name, "")
            probe_target = runtime_name or canonical_name
            probe = probe_model_runtime_acceptance(
                probe_target,
                requested_model=canonical_name,
                ollama_host=ollama_host,
                tags_payload=tags_payload,
                tags_status_code=tags_status_code,
            )
            is_expensive = bool(candidate["cloud_billed"] or candidate["requires_manual_approval"])
            chat_policy = "full" if probe.get("accepted") else "probe_only_unaccepted"
            if chat_policy == "full" and is_expensive and not bool(args.llm_include_expensive):
                chat_policy = "probe_only_expensive"

            probe_records.append(
                {
                    **candidate,
                    "runtime_name": runtime_name,
                    "probe_target": probe_target,
                    "probe_status": str(probe.get("status") or "unknown"),
                    "probe_message": str(probe.get("message") or ""),
                    "probe_http_status": probe.get("runtime_status_code"),
                    "probe_present_in_tags": bool(probe.get("present_in_tags", False)),
                    "probe_accepted": bool(probe.get("accepted", False)),
                    "chat_policy": chat_policy,
                },
            )

        full_candidates = [record for record in probe_records if record.get("chat_policy") == "full"]
        full_candidates.sort(
            key=lambda item: (
                {"light": 0, "medium": 1, "heavy": 2, "unknown": 3}.get(str(item.get("category", "unknown")), 3),
                float(item.get("params_billions", 0.0) or 0.0),
                str(item.get("runtime_name") or item.get("canonical_name") or ""),
            ),
        )

        if int(args.llm_max_models or 0) > 0:
            full_candidates = full_candidates[: int(args.llm_max_models)]

        print("\n" + "=" * 60)
        print("🤖 BENCHMARK LLM TOKEN MATRIX")
        print("=" * 60)
        print(f"  Ollama host: {ollama_host}")
        print(f"  Tokens fixes: {len(CANONICAL_LLM_BENCHMARK_TOKENS)}")
        print(f"  Timeframe: {args.llm_timeframe}")
        print(f"  Modèles sondés: {len(probe_records)}")
        print(f"  Modèles exécutés: {len(full_candidates)}")
        print(f"  Runs par modèle: {runs_per_model}")
        print(f"  Timeout par run: {int(timeout_s)}s")
        print("=" * 60)

        for model_index, candidate in enumerate(full_candidates, start=1):
            model_name = str(candidate.get("runtime_name") or candidate.get("canonical_name") or "").strip()
            print(
                f"\n[{model_index}/{len(full_candidates)}] {model_name} ({candidate.get('category', 'unknown')})",
            )

            cleanup_all_models(ollama_host=ollama_host)
            warmup_ok, warmup_detail = warmup_model(
                model_name,
                ollama_host=ollama_host,
                keep_alive_minutes=keep_alive_minutes,
                timeout_s=timeout_s,
            )
            if not warmup_ok:
                run_rows.append(
                    {
                        "model_name": model_name,
                        "canonical_name": candidate.get("canonical_name", model_name),
                        "category": candidate.get("category", "unknown"),
                        "params_billions": float(candidate.get("params_billions", 0.0) or 0.0),
                        "cloud_billed": bool(candidate.get("cloud_billed", False)),
                        "requires_manual_approval": bool(candidate.get("requires_manual_approval", False)),
                        "probe_status": candidate.get("probe_status", "unknown"),
                        "run_index": 1,
                        "status": "warmup_failed",
                        "error_type": "warmup_failed",
                        "latency_ms": 0.0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "coverage_ratio": 0.0,
                        "matched_expected_count": 0,
                        "valid_token_count": 0,
                        "missing_tokens": list(CANONICAL_LLM_BENCHMARK_TOKENS),
                        "extra_tokens": [],
                        "duplicate_tokens": [],
                        "invalid_indicator_count": 0,
                        "invalid_field_count": 0,
                        "token_records": [],
                        "fallback_attempted": False,
                        "fallback_selected": False,
                        "parse_mode": "not_attempted",
                        "transport": "warmup",
                        "http_status": None,
                        "error_detail": warmup_detail,
                        "response_excerpt": "",
                    },
                )
                print(f"  ❌ Warmup échoué: {warmup_detail}")
            else:
                print(f"  ✅ Warmup: {warmup_detail}")
                for run_index in range(1, runs_per_model + 1):
                    cleanup_all_models(ollama_host=ollama_host)
                    primary_attempt = _evaluate_chat_attempt(
                        _ollama_chat_request(
                            ollama_host=ollama_host,
                            model_name=model_name,
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            timeout_s=timeout_s,
                            json_mode=True,
                        ),
                        CANONICAL_LLM_BENCHMARK_TOKENS,
                        allowed_indicators,
                    )
                    fallback_attempted = False
                    fallback_selected = False
                    fallback_attempt: dict[str, Any] | None = None
                    selected_attempt = primary_attempt

                    if primary_attempt["chat"].get("ok") and primary_attempt.get("status") != "success":
                        fallback_attempted = True
                        fallback_attempt = _evaluate_chat_attempt(
                            _ollama_chat_request(
                                ollama_host=ollama_host,
                                model_name=model_name,
                                system_prompt=system_prompt,
                                user_prompt=user_prompt,
                                temperature=temperature,
                                max_tokens=max_tokens,
                                timeout_s=timeout_s,
                                json_mode=False,
                            ),
                            CANONICAL_LLM_BENCHMARK_TOKENS,
                            allowed_indicators,
                        )
                        if _attempt_score(fallback_attempt) > _attempt_score(primary_attempt):
                            selected_attempt = fallback_attempt
                            fallback_selected = True

                    cleanup_all_models(ollama_host=ollama_host)
                    validation = dict(selected_attempt.get("validation", {}) or {})
                    chat = dict(selected_attempt.get("chat", {}) or {})
                    run_rows.append(
                        {
                            "model_name": model_name,
                            "canonical_name": candidate.get("canonical_name", model_name),
                            "category": candidate.get("category", "unknown"),
                            "params_billions": float(candidate.get("params_billions", 0.0) or 0.0),
                            "cloud_billed": bool(candidate.get("cloud_billed", False)),
                            "requires_manual_approval": bool(candidate.get("requires_manual_approval", False)),
                            "probe_status": candidate.get("probe_status", "unknown"),
                            "run_index": run_index,
                            "status": validation.get("status", "unknown"),
                            "error_type": validation.get("error_type", chat.get("error_type", "unknown")),
                            "latency_ms": float(chat.get("latency_ms", 0.0) or 0.0),
                            "prompt_tokens": int(chat.get("prompt_tokens", 0) or 0),
                            "completion_tokens": int(chat.get("completion_tokens", 0) or 0),
                            "total_tokens": int(chat.get("total_tokens", 0) or 0),
                            "coverage_ratio": float(validation.get("coverage_ratio", 0.0) or 0.0),
                            "matched_expected_count": int(validation.get("matched_expected_count", 0) or 0),
                            "valid_token_count": int(validation.get("valid_token_count", 0) or 0),
                            "missing_tokens": list(validation.get("missing_tokens", []) or []),
                            "extra_tokens": list(validation.get("extra_tokens", []) or []),
                            "duplicate_tokens": list(validation.get("duplicate_tokens", []) or []),
                            "invalid_indicator_count": int(validation.get("invalid_indicator_count", 0) or 0),
                            "invalid_field_count": int(validation.get("invalid_field_count", 0) or 0),
                            "token_records": list(validation.get("token_records", []) or []),
                            "fallback_attempted": fallback_attempted,
                            "fallback_selected": fallback_selected,
                            "parse_mode": str(selected_attempt.get("parse_mode", "unknown") or "unknown"),
                            "transport": str(chat.get("transport", "unknown") or "unknown"),
                            "http_status": chat.get("http_status"),
                            "error_detail": str(chat.get("error_detail", "") or ""),
                            "response_excerpt": _trim_text(chat.get("content", ""), max_chars=220),
                            "primary_status": primary_attempt.get("status", "unknown"),
                            "primary_error_type": primary_attempt.get("error_type", "unknown"),
                            "fallback_status": ""
                            if fallback_attempt is None
                            else fallback_attempt.get("status", "unknown"),
                            "fallback_error_type": ""
                            if fallback_attempt is None
                            else fallback_attempt.get("error_type", "unknown"),
                        },
                    )
                    print(
                        "  run {run}: {status} | coverage={coverage:.0%} | latency={latency:.0f}ms{fallback}".format(
                            run=run_index,
                            status=validation.get("status", "unknown"),
                            coverage=float(validation.get("coverage_ratio", 0.0) or 0.0),
                            latency=float(chat.get("latency_ms", 0.0) or 0.0),
                            fallback=" | retry-nojson" if fallback_selected else "",
                        ),
                    )

            payload = {
                "generated_at": _utc_now_iso(),
                "config": {
                    "ollama_host": ollama_host,
                    "timeframe": args.llm_timeframe,
                    "tokens_count": len(CANONICAL_LLM_BENCHMARK_TOKENS),
                    "runs_per_model": runs_per_model,
                    "timeout_s": timeout_s,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "keep_alive_minutes": keep_alive_minutes,
                    "include_expensive": bool(args.llm_include_expensive),
                    "model_filter": str(args.llm_model_filter or ""),
                    "max_models": int(args.llm_max_models or 0),
                    "prompt_version": LLM_BENCHMARK_PROMPT_VERSION,
                },
                "token_universe": list(CANONICAL_LLM_BENCHMARK_TOKENS),
                "allowed_indicators": list(allowed_indicators),
                "runtime_models_exact": list(runtime_models_exact),
                "probe_records": probe_records,
                "run_rows": run_rows,
                "summary": _summarize_llm_benchmark(probe_records, run_rows),
            }
            _persist_llm_benchmark_payload(output_path, payload)

        payload = {
            "generated_at": _utc_now_iso(),
            "config": {
                "ollama_host": ollama_host,
                "timeframe": args.llm_timeframe,
                "tokens_count": len(CANONICAL_LLM_BENCHMARK_TOKENS),
                "runs_per_model": runs_per_model,
                "timeout_s": timeout_s,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "keep_alive_minutes": keep_alive_minutes,
                "include_expensive": bool(args.llm_include_expensive),
                "model_filter": str(args.llm_model_filter or ""),
                "max_models": int(args.llm_max_models or 0),
                "prompt_version": LLM_BENCHMARK_PROMPT_VERSION,
            },
            "token_universe": list(CANONICAL_LLM_BENCHMARK_TOKENS),
            "allowed_indicators": list(allowed_indicators),
            "runtime_models_exact": list(runtime_models_exact),
            "probe_records": probe_records,
            "run_rows": run_rows,
            "summary": _summarize_llm_benchmark(probe_records, run_rows),
        }
        _persist_llm_benchmark_payload(output_path, payload)
        print(f"\n📁 Résultats JSON: {output_path}")
        print(f"📝 Rapport Markdown: {output_path.with_suffix('.md')}")
        print(f"🌐 Rapport HTML triable: {output_path.with_suffix('.html')}")
        return payload
    finally:
        cleanup_all_models(ollama_host=ollama_host)
        stop_owned_local_ollama_server(ollama_host=ollama_host)


def main():
    parser = argparse.ArgumentParser(description="Benchmark système backtest")
    parser.add_argument("--full", action="store_true", help="Benchmark complet")
    parser.add_argument("--parallel-only", action="store_true", help="Benchmark parallèle uniquement")
    parser.add_argument("--numba-only", action="store_true", help="Benchmark Numba uniquement")
    parser.add_argument("--n-bars", type=int, default=10000, help="Nombre de barres de test")
    parser.add_argument("--n-combos", type=int, default=100, help="Nombre de combinaisons sweep")
    parser.add_argument(
        "--llm-proposal-benchmark", action="store_true", help="Benchmark LLM multi-modèles sur 23 tokens fixes",
    )
    parser.add_argument("--llm-runs", type=int, default=1, help="Nombre de runs par modèle pour le benchmark LLM")
    parser.add_argument(
        "--llm-timeframe",
        type=str,
        default=DEFAULT_LLM_BENCHMARK_TIMEFRAME,
        help="Timeframe de référence pour le benchmark LLM",
    )
    parser.add_argument("--llm-timeout", type=int, default=120, help="Timeout en secondes par run LLM")
    parser.add_argument("--llm-max-tokens", type=int, default=2400, help="Tokens maximum de sortie par run LLM")
    parser.add_argument(
        "--llm-temperature", type=float, default=0.2, help="Température de génération pour le benchmark LLM",
    )
    parser.add_argument(
        "--llm-keep-alive-minutes", type=int, default=10, help="Keep-alive minutes pour le warmup des modèles",
    )
    parser.add_argument(
        "--llm-max-models",
        type=int,
        default=0,
        help="Limiter le nombre de modèles réellement exécutés après la phase probe (0=tous)",
    )
    parser.add_argument("--llm-model-filter", type=str, default="", help="Regex de filtrage des modèles benchmarkés")
    parser.add_argument(
        "--llm-include-expensive",
        action="store_true",
        help="Exécuter aussi les modèles cloud ou >50B au lieu de les laisser en probe-only",
    )
    parser.add_argument("--llm-output", type=str, default="", help="Chemin de sortie JSON du benchmark LLM")
    parser.add_argument(
        "--llm-ollama-host",
        type=str,
        default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        help="Host Ollama à utiliser pour le benchmark LLM",
    )
    args = parser.parse_args()

    if args.llm_proposal_benchmark:
        run_llm_token_matrix_benchmark(args)
        print("\n✅ Benchmark LLM terminé!")
        return

    print("\n🚀 BENCHMARK SYSTÈME BACKTEST CORE")
    print("=" * 60)

    # Info système
    info = get_system_info()
    print_system_info(info)

    # Générer données de test
    print(f"\n📊 Génération données de test ({args.n_bars} barres)...")
    df = generate_test_data(args.n_bars)

    all_results = []

    # Benchmarks
    if args.numba_only or args.full or not (args.parallel_only):
        results = benchmark_numba(df)
        all_results.extend(results)

    if args.parallel_only or args.full or not (args.numba_only):
        results = benchmark_parallel_sweep(df, args.n_combos)
        all_results.extend(results)

    if args.full:
        results = benchmark_real_backtest(df)
        all_results.extend(results)

    # Recommandations
    print_recommendations(info, all_results)

    print("\n✅ Benchmark terminé!")


if __name__ == "__main__":
    main()
