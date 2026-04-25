from __future__ import annotations

import importlib
import json
import logging
import re
import sys

import numpy as np
import pandas as pd


def test_obv_handles_empty_and_mismatched_inputs() -> None:
    from indicators.obv import obv

    assert obv(np.array([], dtype=float), np.array([], dtype=float)).size == 0

    try:
        obv(np.array([1.0, 2.0]), np.array([10.0]))
    except ValueError as exc:
        assert "same length" in str(exc)
    else:
        raise AssertionError("obv should reject mismatched close/volume lengths")


def test_token_classification_is_case_insensitive_and_deterministic(monkeypatch) -> None:
    from data import token_classification as mod

    monkeypatch.setattr(
        mod,
        "load_token_profiles",
        lambda: {
            "profiles": {
                "high_volatility": {"tokens": ["BTCUSDC", "ethusdc"]},
                "medium_volatility": {"tokens": ["ADAUSDC"]},
            },
            "archetype_recommendations": {
                "scalping": {
                    "timeframes": ["3m", "5m"],
                    "preferred_tf": "3m",
                    "token_profile": "high_volatility",
                },
            },
        },
    )

    assert mod.classify_token("btcusdc") == "high_volatility"
    assert mod.get_tokens_by_profile("any") == ["ADAUSDC", "BTCUSDC", "ETHUSDC"]
    assert mod.get_preferred_timeframe("  SCALPING ") == "3m"


def test_bollinger_atr_v3_skips_flat_bands() -> None:
    from strategies.bollinger_atr_v3 import BollingerATRStrategyV3

    strategy = BollingerATRStrategyV3()
    df = pd.DataFrame(
        {
            "close": [100.0, 100.0, 100.0],
        },
        index=pd.date_range("2026-01-01", periods=3, freq="h"),
    )
    flat_band = pd.Series([100.0, 100.0, 100.0], index=df.index)
    atr = pd.Series([1.0, 1.0, 1.0], index=df.index)

    signals = strategy.generate_signals(
        df,
        indicators={"bollinger": {"upper": flat_band, "middle": flat_band, "lower": flat_band}, "atr": atr},
        params={},
    )

    assert signals.eq(0.0).all()


def test_health_monitor_stop_interrupts_sleep() -> None:
    from utils.health import HealthMonitor

    monitor = HealthMonitor()
    monitor.start_monitoring(interval=60.0)
    monitor.stop_monitoring()

    assert monitor._monitor_thread is None
    assert monitor._stop_event.is_set()


def test_bench_sweep_fast_import_has_no_stdout(capsys) -> None:
    sys.modules.pop("tools.bench_sweep_fast", None)
    importlib.import_module("tools.bench_sweep_fast")
    captured = capsys.readouterr()
    assert captured.out == ""


def test_test_worker_fast_import_has_no_stdout(capsys) -> None:
    sys.modules.pop("tools.test_worker_fast", None)
    importlib.import_module("tools.test_worker_fast")
    captured = capsys.readouterr()
    assert captured.out == ""


def test_atr_handles_empty_and_mismatched_inputs() -> None:
    from indicators.atr import atr, true_range

    assert true_range(np.array([], dtype=float), np.array([], dtype=float), np.array([], dtype=float)).size == 0
    assert atr(np.array([], dtype=float), np.array([], dtype=float), np.array([], dtype=float)).size == 0

    try:
        true_range(np.array([1.0]), np.array([0.5, 0.4]), np.array([0.8]))
    except ValueError as exc:
        assert "same length" in str(exc)
    else:
        raise AssertionError("true_range should reject mismatched array lengths")


def test_kvo_starts_neutral_and_handles_empty_inputs() -> None:
    from indicators.kvo import kvo

    empty = kvo(np.array([], dtype=float), np.array([], dtype=float), np.array([], dtype=float), np.array([], dtype=float))
    assert empty["kvo"].size == 0
    assert empty["signal"].size == 0

    values = kvo(
        np.array([10.0, 11.0, 12.0]),
        np.array([9.0, 10.0, 11.0]),
        np.array([9.5, 10.5, 11.5]),
        np.array([100.0, 120.0, 140.0]),
    )
    assert values["kvo"][0] == 0.0


def test_extract_dataframe_timestamps_uses_min_max_and_rejects_empty() -> None:
    from agents.integration import extract_dataframe_timestamps

    df = pd.DataFrame(
        {"timestamp": [1714608000000, 1714435200000, 1714521600000]},
    )
    start, end = extract_dataframe_timestamps(df)
    assert start < end
    assert start == pd.Timestamp("2024-04-30 00:00:00")
    assert end == pd.Timestamp("2024-05-02 00:00:00")

    try:
        extract_dataframe_timestamps(pd.DataFrame())
    except ValueError as exc:
        assert "must not be empty" in str(exc)
    else:
        raise AssertionError("extract_dataframe_timestamps should reject empty dataframes")


def test_openai_client_preserves_zero_temperature_and_max_tokens(monkeypatch) -> None:
    from agents import llm_client as mod

    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            captured["init_kwargs"] = kwargs

        def post(self, url, json=None):  # noqa: ANN001
            captured["url"] = url
            captured["payload"] = json
            return FakeResponse()

        def close(self) -> None:
            return None

    monkeypatch.setattr(mod.httpx, "Client", FakeClient)
    client = mod.OpenAIClient(
        mod.LLMConfig(
            provider=mod.LLMProvider.OPENAI,
            model="gpt-test",
            openai_api_key="test-key",
            temperature=0.7,
            max_tokens=128,
        ),
    )

    response = client.chat([mod.LLMMessage(role="user", content="hello")], temperature=0.0, max_tokens=0)

    assert response.content == "ok"
    assert captured["payload"]["temperature"] == 0.0
    assert captured["payload"]["max_tokens"] == 0


def test_format_table_handles_ragged_rows() -> None:
    from cli.formatters import format_table

    table = format_table(["A", "B"], [["1", "2", "3"], ["x"]])

    assert "3" in table
    assert "x" in table


def test_colored_formatter_restores_original_levelname() -> None:
    from utils.log import ColoredFormatter

    formatter = ColoredFormatter("%(levelname)s:%(message)s")
    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )

    first = formatter.format(record)
    second = formatter.format(record)

    plain_first = re.sub(r"\x1b\[[0-9;]*m", "", first)
    plain_second = re.sub(r"\x1b\[[0-9;]*m", "", second)
    assert plain_first == "WARNING:hello"
    assert plain_second == plain_first
    assert record.levelname == "WARNING"


def test_benchmark_ablation_json_mode_stays_machine_readable(monkeypatch, capsys) -> None:
    import tools.benchmark_ablation as mod

    def fake_run(n: int, *, verbose: bool = True):  # noqa: ANN001
        assert n == 7
        assert verbose is False
        return ({"code_repair": "1.23 ± 0.01 ms"}, {"code_repair": 1.23})

    monkeypatch.setattr(mod, "_run_benchmarks", fake_run)
    monkeypatch.setattr(sys, "argv", ["benchmark_ablation.py", "--json", "--n-runs", "7"])

    mod.main()
    output = capsys.readouterr().out.strip()
    assert json.loads(output) == {"n_runs": 7, "median_ms": {"code_repair": 1.23}}


def test_profile_sweep_requires_available_data(monkeypatch) -> None:
    import tools.profile_sweep as mod

    monkeypatch.setattr(mod, "load_ohlcv", lambda symbol, timeframe: None)

    try:
        mod.profile_sweep()
    except RuntimeError as exc:
        assert "aucune donnée" in str(exc)
    else:
        raise AssertionError("profile_sweep should fail fast when no data is available")


def test_cci_handles_empty_and_mismatched_inputs() -> None:
    from indicators.cci import cci

    assert cci(np.array([], dtype=float), np.array([], dtype=float), np.array([], dtype=float)).size == 0

    try:
        cci(np.array([1.0]), np.array([1.0, 2.0]), np.array([1.0]))
    except ValueError as exc:
        assert "same length" in str(exc)
    else:
        raise AssertionError("cci should reject mismatched high/low/close lengths")


def test_stoch_rsi_divergence_skips_nan_price_windows() -> None:
    from indicators.stoch_rsi import stoch_rsi_divergence

    result = stoch_rsi_divergence(
        pd.Series([np.nan, np.nan, np.nan, 10.0]),
        np.array([10.0, 20.0, 30.0, 40.0]),
        lookback=2,
    )

    assert result.shape == (4,)
    assert result[2] == 0.0


def test_repair_autonomous_supervisor_history_skips_missing_backup(monkeypatch, capsys, tmp_path) -> None:
    import tools.repair_autonomous_supervisor_history as mod

    saved: dict[str, object] = {}
    monkeypatch.setattr(
        mod,
        "_load_autonomous_supervisor_state",
        lambda: {"history": [{"session_id": ""}], "supervisor": {"active": True}},
    )
    monkeypatch.setattr(mod, "_load_autonomous_runtime_state", lambda: {"status": "idle"})
    monkeypatch.setattr(
        mod,
        "_recover_autonomous_history_from_disk",
        lambda history, runtime_state: ([{"session_id": "session-1"}], True),
    )
    monkeypatch.setattr(
        mod,
        "_save_autonomous_supervisor_state",
        lambda history, supervisor: saved.update({"history": history, "supervisor": supervisor}),
    )
    monkeypatch.setattr(
        mod.shutil,
        "copy2",
        lambda src, dst: (_ for _ in ()).throw(AssertionError("copy2 should not be called")),
    )
    monkeypatch.setattr(mod, "_AUTONOMOUS_SUPERVISOR_STATE_FILE", str(tmp_path / "missing.json"))

    assert mod.main() == 0

    output = json.loads(capsys.readouterr().out)
    assert output["backup_file"] is None
    assert saved["history"] == [{"session_id": "session-1"}]
