"""Page Streamlit dediee au Simple Builder mono-LLM canonique.

Cette page est volontairement isolee de `ui/builder_view.py`. Elle invoque `agents.simple_builder.SimpleBuilder`
directement, sans aucune relance externe ni watchdog.

Lancement standalone (recommande pour tests) :
    streamlit run ui/pages/simple_builder_page.py

Aucun lancement automatique : c'est l'utilisateur qui clique "Lancer".
"""

from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap PYTHONPATH si standalone
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.observability import init_logging  # noqa: E402

init_logging()

import json  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

# Side-effect : enregistre les indicateurs dans le registry
import indicators.registry  # noqa: F401, E402
from agents.llm_client import LLMConfig, LLMProvider  # noqa: E402
from agents.simple_builder import (  # noqa: E402
    DEFAULT_ACCEPT_CRITERIA,
    SimpleBuilder,
)
from indicators.registry import list_indicators  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_synthetic(*, n_bars: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    drift = rng.normal(loc=0.0005, scale=0.012, size=n_bars)
    close = 100.0 * np.exp(np.cumsum(drift))
    high = close * (1 + np.abs(rng.normal(0, 0.004, n_bars)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n_bars)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.uniform(1000, 5000, size=n_bars)
    idx = pd.date_range("2024-01-01", periods=n_bars, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )


def _load_parquet_or_csv(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        raise ValueError(f"format non supporte: {path.suffix}")
    if "datetime" in df.columns:
        df = df.set_index(pd.to_datetime(df["datetime"], utc=True)).drop(
            columns=["datetime"],
        )
    elif "date" in df.columns:
        df = df.set_index(pd.to_datetime(df["date"], utc=True)).drop(columns=["date"])
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    return df


def _format_metric(name: str, value: float, ok: bool) -> str:
    cls = "bc-success" if ok else "bc-error"
    icon = "OK" if ok else "FAIL"
    return (
        f"<div class='bc-card' style='display:inline-block;margin:2px;padding:4px 8px'>"
        f"<b class='{cls}'>{icon}</b> "
        f"<span class='bc-caption'>{name}</span> = "
        f"<code>{value:.3f}</code></div>"
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def render_page() -> None:
    from ui.theme import apply_theme

    st.set_page_config(page_title="Simple Builder", layout="wide")
    apply_theme(force=True)
    st.title("Simple Builder — mono-LLM canonique")
    st.caption(
        "Pipeline 9 etapes explicites. Aucune relance automatique. "
        "JSON DSL strict, interpreteur deterministe.",
    )

    with st.sidebar:
        st.header("Configuration")
        st.subheader("LLM")
        provider = st.selectbox(
            "Provider",
            options=("ollama", "openai"),
            index=0,
        )
        model = st.text_input(
            "Modele",
            value="qwen2.5:7b",
            help="Nom du modele Ollama (ou OpenAI). Privilegier un modele leger pour la stabilite.",
        )
        host = st.text_input("Ollama host", value="http://127.0.0.1:11434")

        st.subheader("Iterations")
        max_iter = st.number_input("Max iterations", min_value=1, max_value=10, value=3)
        retry = st.number_input(
            "Retry sur JSON invalide (par iter)",
            min_value=0, max_value=2, value=1,
        )

        st.subheader("Capital")
        initial_capital = st.number_input(
            "Capital initial",
            min_value=100.0, value=10000.0, step=500.0,
        )

        st.subheader("Seuils d'acceptation")
        c_min_trades = st.number_input(
            "min_trades",
            min_value=1.0, value=float(DEFAULT_ACCEPT_CRITERIA["min_trades"]),
        )
        c_min_ret = st.number_input(
            "min_total_return_pct",
            value=float(DEFAULT_ACCEPT_CRITERIA["min_total_return_pct"]),
        )
        c_min_sharpe = st.number_input(
            "min_sharpe",
            value=float(DEFAULT_ACCEPT_CRITERIA["min_sharpe"]),
        )
        c_max_dd = st.number_input(
            "max_drawdown_pct",
            min_value=1.0, value=float(DEFAULT_ACCEPT_CRITERIA["max_drawdown_pct"]),
        )
        c_min_pf = st.number_input(
            "min_profit_factor",
            value=float(DEFAULT_ACCEPT_CRITERIA["min_profit_factor"]),
        )

    # ---- Donnees ----------------------------------------------------------
    st.subheader("1. Donnees OHLCV")
    src = st.radio(
        "Source",
        options=("synthetique", "parquet/csv"),
        horizontal=True,
    )
    if src == "synthetique":
        n_bars = st.slider("Nombre de barres", 300, 5000, 800, 100)
        seed = st.number_input("Seed", min_value=0, value=42)
        if st.button("Generer donnees synthetiques", type="secondary"):
            st.session_state["_simple_data"] = _build_synthetic(
                n_bars=int(n_bars), seed=int(seed),
            )
            st.success(f"OK : {n_bars} barres synthetiques generees")
    else:
        path_str = st.text_input(
            "Chemin parquet/csv",
            value="",
            placeholder=r"D:\path\to\BTCUSDT_1h.parquet",
        )
        if st.button("Charger fichier", type="secondary"):
            try:
                df = _load_parquet_or_csv(Path(path_str))
                st.session_state["_simple_data"] = df
                st.success(f"OK : {len(df)} barres chargees ({df.index[0]} -> {df.index[-1]})")
            except (ValueError, FileNotFoundError, OSError) as exc:
                st.error(f"Echec chargement : {exc}")

    data: pd.DataFrame | None = st.session_state.get("_simple_data")
    if data is not None:
        st.caption(f"Donnees chargees : {len(data)} barres")

    # ---- Objectif --------------------------------------------------------
    st.subheader("2. Objectif")
    objective = st.text_area(
        "Objectif strategie",
        value="Mean reversion sur RSI 14 avec confirmation EMA 50",
        height=80,
    )
    symbol = st.text_input("Symbole (logging)", value="SYNTH")
    timeframe = st.text_input("Timeframe (logging)", value="1h")

    with st.expander("Indicateurs disponibles dans le registry"):
        indicators_list = sorted(list_indicators())
        st.write(f"{len(indicators_list)} indicateurs : {', '.join(indicators_list)}")

    # ---- Lancement ------------------------------------------------------
    st.subheader("3. Lancement")
    can_run = data is not None and bool(objective.strip())
    if st.button("Lancer le Simple Builder", type="primary", disabled=not can_run):
        cfg = LLMConfig(
            provider=LLMProvider.OPENAI if provider == "openai" else LLMProvider.OLLAMA,
            model=model,
            ollama_host=host,
        )
        builder = SimpleBuilder(
            llm_config=cfg,
            max_iterations=int(max_iter),
            retry_on_invalid_json=int(retry),
            accept_criteria={
                "min_trades": float(c_min_trades),
                "min_total_return_pct": float(c_min_ret),
                "min_sharpe": float(c_min_sharpe),
                "max_drawdown_pct": float(c_max_dd),
                "min_profit_factor": float(c_min_pf),
            },
            initial_capital=float(initial_capital),
        )
        with st.spinner("Pipeline en cours (LLM -> validate -> backtest -> diagnose)..."):
            try:
                session = builder.build(
                    objective=objective.strip(),
                    data=data,
                    symbol=symbol.strip() or "SYMBOL",
                    timeframe=timeframe.strip() or "1h",
                )
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(f"Echec session : {type(exc).__name__}: {exc}")
                return
        st.session_state["_simple_session"] = session

    # ---- Affichage resultat ---------------------------------------------
    session = st.session_state.get("_simple_session")
    if session is None:
        st.info("Aucune session executee. Configurez les donnees et l'objectif puis cliquez 'Lancer'.")
        return

    st.subheader("4. Resultat de session")
    cols = st.columns(4)
    cols[0].metric("Status", session.final_status)
    cols[1].metric("Iterations", len(session.iterations))
    cols[2].metric(
        "Iter acceptee",
        session.accepted_iteration or "—",
    )
    best = session.best_metrics()
    cols[3].metric(
        "Best return %",
        f"{best.get('total_return_pct', 0.0):.2f}",
    )

    st.markdown("**Iterations**")
    rows = []
    for it in session.iterations:
        rows.append(
            {
                "iter": it.iteration,
                "status": it.status,
                "phase": it.phase_reached,
                "error_code": it.error_code or "",
                "n_trades": it.metrics.get("n_trades", 0),
                "return_pct": float(it.metrics.get("total_return_pct", 0.0) or 0.0),
                "sharpe": float(it.metrics.get("sharpe_ratio", 0.0) or 0.0),
                "max_dd_pct": float(it.metrics.get("max_drawdown_pct", 0.0) or 0.0),
                "pf": float(it.metrics.get("profit_factor", 0.0) or 0.0),
                "llm_s": round(it.llm_latency_s, 2),
                "bt_s": round(it.backtest_latency_s, 2),
                "reason": it.reason,
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

    # Detail par iteration
    for it in session.iterations:
        with st.expander(
            f"Iteration #{it.iteration} — {it.status}"
            + (f" — {it.error_code}" if it.error_code else ""),
        ):
            st.code(json.dumps(it.proposal or {}, ensure_ascii=False, indent=2), language="json")
            if it.diagnosis:
                st.markdown("**Diagnostic**")
                values = it.diagnosis.get("values", {})
                criteria = {
                    "min_trades": float(c_min_trades),
                    "min_total_return_pct": float(c_min_ret),
                    "min_sharpe": float(c_min_sharpe),
                    "max_drawdown_pct": float(c_max_dd),
                    "min_profit_factor": float(c_min_pf),
                }
                failed = set(it.diagnosis.get("failed_checks") or [])
                cells = []
                for key, val in values.items():
                    crit_key = (
                        f"max_drawdown_pct" if key == "max_drawdown_pct"
                        else f"min_{key}" if key not in criteria else key
                    )
                    crit_key = key if key in criteria else crit_key
                    ok = crit_key not in failed
                    cells.append(_format_metric(key, float(val), ok))
                st.markdown("".join(cells), unsafe_allow_html=True)
            if it.reason:
                st.caption(f"Raison : {it.reason}")


if __name__ == "__main__":
    render_page()
