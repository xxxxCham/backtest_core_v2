"""CLI minimaliste pour lancer agents.simple_builder hors Streamlit.

Aucun fork de processus. Aucune relance externe. Aucun watchdog.

Usage:
    python tools\\run_simple_builder.py --objective "RSI mean reversion" \\
        --symbol BTCUSDT --timeframe 1h --bars 800 --iterations 3

Avec donnees synthetiques (defaut) si --data n'est pas fourni :
    python tools\\run_simple_builder.py --objective "test"

Avec donnees reelles parquet :
    python tools\\run_simple_builder.py \\
        --data D:\\path\\to\\BTCUSDT_1h.parquet \\
        --objective "RSI mean reversion canonique" --iterations 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Bootstrap chemin si lance hors PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Side-effect: enregistre les indicateurs
import indicators.registry  # noqa: F401, E402

from agents.llm_client import LLMConfig  # noqa: E402
from agents.simple_builder import SimpleBuilder  # noqa: E402


def _build_synthetic(*, n_bars: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    drift = rng.normal(loc=0.0005, scale=0.012, size=n_bars)
    close = 100.0 * np.exp(np.cumsum(drift))
    high = close * (1 + np.abs(rng.normal(0, 0.004, n_bars)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n_bars)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.uniform(1000, 5000, size=n_bars)
    idx = pd.date_range("2024-01-01", periods=n_bars, freq="h", tz="UTC")
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    }, index=idx)


def _load_data(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        raise SystemExit(f"format non supporte: {path.suffix}")
    if "datetime" in df.columns:
        df = df.set_index(pd.to_datetime(df["datetime"], utc=True)).drop(
            columns=["datetime"],
        )
    elif "date" in df.columns:
        df = df.set_index(pd.to_datetime(df["date"], utc=True)).drop(columns=["date"])
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    needed = {"open", "high", "low", "close"}
    missing = needed - set(df.columns)
    if missing:
        raise SystemExit(f"colonnes OHLCV manquantes: {sorted(missing)}")
    return df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke runner du SimpleBuilder")
    parser.add_argument("--objective", required=True, help="Objectif strategie en langage naturel")
    parser.add_argument("--symbol", default="SYNTH")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--data", type=Path, default=None,
                        help="Parquet/CSV OHLCV. Si absent: donnees synthetiques.")
    parser.add_argument("--bars", type=int, default=800,
                        help="Nombre de barres synthetiques si --data absent.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--retry-on-invalid-json", type=int, default=1)
    parser.add_argument("--initial-capital", type=float, default=10000.0)
    parser.add_argument("--ollama-host", default=None,
                        help="Surcharge OLLAMA_HOST (sinon env, sinon http://127.0.0.1:11434)")
    parser.add_argument("--model", default=None,
                        help="Surcharge BACKTEST_LLM_MODEL")
    parser.add_argument("--sessions-dir", type=Path, default=None,
                        help="Dossier de sortie NDJSON. Defaut: BACKTEST_RESULTS_DIR/_builder_sessions/_simple_builder")
    args = parser.parse_args(argv)

    if args.data is not None:
        if not args.data.exists():
            raise SystemExit(f"data introuvable: {args.data}")
        data = _load_data(args.data)
        print(f"[data] {args.data} bars={len(data)} from={data.index[0]} to={data.index[-1]}")
    else:
        data = _build_synthetic(n_bars=int(args.bars), seed=int(args.seed))
        print(f"[data] synthetiques bars={len(data)} seed={args.seed}")

    cfg = LLMConfig.from_env()
    if args.ollama_host:
        cfg.ollama_host = args.ollama_host
    if args.model:
        cfg.model = args.model
    print(f"[llm] provider={cfg.provider.value} model={cfg.model} host={cfg.ollama_host}")

    builder = SimpleBuilder(
        llm_config=cfg,
        max_iterations=int(args.iterations),
        retry_on_invalid_json=int(args.retry_on_invalid_json),
        initial_capital=float(args.initial_capital),
        sessions_dir=args.sessions_dir,
    )
    session = builder.build(
        objective=args.objective, data=data,
        symbol=args.symbol, timeframe=args.timeframe,
    )

    summary = {
        "session_id": session.session_id,
        "final_status": session.final_status,
        "accepted_iteration": session.accepted_iteration,
        "n_iterations": len(session.iterations),
        "best_metrics": session.best_metrics(),
        "iterations": [
            {
                "i": it.iteration, "status": it.status, "phase_reached": it.phase_reached,
                "reason": it.reason, "error_code": it.error_code,
                "llm_latency_s": round(it.llm_latency_s, 2),
                "backtest_latency_s": round(it.backtest_latency_s, 3),
                "n_trades": it.metrics.get("n_trades", 0),
            }
            for it in session.iterations
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if session.final_status == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
