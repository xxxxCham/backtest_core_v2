from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agents.llm_client import LLMConfig, LLMProvider
from agents.llm_router import build_phase1_topology
from core.llm_multi.download_manager import plan_missing_downloads
from core.llm_multi.model_discovery import (
    DiscoveredModel,
    ModelInventory,
    discover_local_models,
)
from core.llm_multi.registry import resolve_profile_assignments
from core.llm_multi.session_manager import MultiLLMSessionManager
import core.llm_multi.model_discovery as model_discovery_module
import core.llm_multi.download_manager as download_manager_module
import core.llm_multi.session_manager as session_manager_module
import utils.model_loader as model_loader_module


def _inventory(
    models: list[tuple[str, str] | tuple[str, str, bool]],
    *,
    live_ollama_reachable: bool = False,
) -> ModelInventory:
    discovered = []
    for raw in models:
        if len(raw) == 2:
            name, backend = raw
            live = False
        else:
            name, backend, live = raw
        discovered.append(
            DiscoveredModel(
                name=name,
                backend=backend,
                source="test",
                verified_available=True,
                path=f"/fake/{name}",
                exists_on_disk=True,
                aliases=[name],
                live=live,
            )
        )
    return ModelInventory(
        discovered_models=discovered,
        scanned_roots=[],
        missing_roots=[],
        live_ollama_reachable=live_ollama_reachable,
        live_ollama_host="http://127.0.0.1:11434",
    )


def test_discover_local_models_detects_verified_manifest_and_hf_dirs(
    tmp_path: Path,
    monkeypatch,
):
    ollama_root = tmp_path / "ollama"
    manifest_path = (
        ollama_root
        / "manifests"
        / "registry.ollama.ai"
        / "library"
        / "qwen3-coder"
        / "30b"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("{}", encoding="utf-8")

    hf_root = tmp_path / "huggingface"
    hf_model_dir = hf_root / "fin-llama-33b"
    hf_model_dir.mkdir(parents=True, exist_ok=True)
    (hf_model_dir / "config.json").write_text("{}", encoding="utf-8")

    fake_models_json = tmp_path / "models.json"
    fake_models_json.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        model_discovery_module,
        "DEFAULT_MODEL_SEARCH_ROOTS",
        (ollama_root, hf_root),
    )
    monkeypatch.setattr(
        model_discovery_module,
        "get_models_json_path",
        lambda: fake_models_json,
    )
    monkeypatch.setattr(
        model_discovery_module,
        "load_models_json",
        lambda force_reload=True: {"ollama_models": [], "huggingface_models": []},
    )

    inventory = discover_local_models(include_live_ollama=False)

    assert inventory.find("qwen3-coder:30b") is not None
    assert inventory.find("qwen3-coder:30b").verified_available is True
    assert inventory.find("fin-llama-33b") is not None
    assert inventory.find("fin-llama-33b").verified_available is True


def test_resolve_profile_assignments_prefers_verified_local_models():
    inventory = _inventory(
        [
            ("gemma3:12b", "ollama"),
            ("qwen3-coder:30b", "ollama"),
            ("deepseek-r1-distill:14b", "ollama"),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama"),
            ("nemotron-orchestrator-8b:latest", "ollama"),
        ]
    )

    resolved = resolve_profile_assignments("24GB_balanced", inventory)
    assignments = {assignment.role: assignment for assignment in resolved["assignments"]}

    assert resolved["missing_roles"] == []
    assert assignments["builder_llm"].resolved_model == "qwen3-coder:30b"
    assert assignments["critic_llm"].resolved_model == "deepseek-r1-distill:14b"


def test_resolve_profile_assignments_light_profile_prefers_small_models():
    inventory = _inventory(
        [
            ("mistral:7b-instruct", "ollama", True),
            ("gemma3:12b", "ollama", True),
            ("deepseek-r1:8b", "ollama", True),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama", True),
            ("nemotron-orchestrator-8b:latest", "ollama", True),
            ("qwen3-30b-a3b:q4_k_m", "ollama", True),
        ],
        live_ollama_reachable=True,
    )

    resolved = resolve_profile_assignments(
        "24GB_light_test",
        inventory,
        require_live_ollama=True,
    )
    assignments = {assignment.role: assignment for assignment in resolved["assignments"]}

    assert resolved["missing_roles"] == []
    assert assignments["idea_llm"].resolved_model == "mistral:7b-instruct"
    assert assignments["builder_llm"].resolved_model == "gemma3:12b"
    assert assignments["critic_llm"].resolved_model == "deepseek-r1:8b"
    assert assignments["risk_llm"].resolved_model == "martain7r/finance-llama-8b:q4_k_m"


def test_plan_missing_downloads_lists_unresolved_roles():
    inventory = _inventory(
        [
            ("qwen3-coder:30b", "ollama"),
            ("deepseek-r1-distill:14b", "ollama"),
        ]
    )

    requests = plan_missing_downloads("24GB_balanced", inventory)
    missing_roles = {request.role for request in requests}

    assert "idea_llm" in missing_roles
    assert "execution_router_llm" not in missing_roles


def test_resolve_profile_assignments_prefers_live_ollama_match_when_required():
    inventory = _inventory(
        [
            ("qwen2.5:32b", "ollama", False),
            ("gemma3:12b", "ollama", True),
            ("qwen3-coder:30b", "ollama", True),
            ("deepseek-r1-distill:14b", "ollama", True),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama", True),
            ("nemotron-orchestrator-8b:latest", "ollama", True),
        ],
        live_ollama_reachable=True,
    )

    resolved = resolve_profile_assignments(
        "24GB_balanced",
        inventory,
        require_live_ollama=True,
    )
    assignments = {assignment.role: assignment for assignment in resolved["assignments"]}

    assert assignments["idea_llm"].resolved_model == "gemma3:12b"
    assert assignments["idea_llm"].live is True
    assert assignments["idea_llm"].available is True


def test_resolve_profile_assignments_applies_role_override():
    inventory = _inventory(
        [
            ("qwen2.5:32b", "ollama", True),
            ("qwen3-coder:30b", "ollama", True),
            ("deepseek-r1-distill:14b", "ollama", True),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama", True),
            ("nemotron-orchestrator-8b:latest", "ollama", True),
            ("mistral:7b-instruct", "ollama", True),
        ],
        live_ollama_reachable=True,
    )

    resolved = resolve_profile_assignments(
        "24GB_balanced",
        inventory,
        role_overrides={"risk_llm": "mistral:7b-instruct"},
        require_live_ollama=True,
    )
    assignments = {assignment.role: assignment for assignment in resolved["assignments"]}

    assert assignments["risk_llm"].requested_model == "mistral:7b-instruct"
    assert assignments["risk_llm"].resolved_model == "mistral:7b-instruct"
    assert assignments["risk_llm"].available is True


def test_resolve_profile_assignments_accepts_role_override_candidate_pool():
    inventory = _inventory(
        [
            ("qwen2.5:32b", "ollama", True),
            ("qwen3-coder:30b", "ollama", True),
            ("deepseek-r1-distill:14b", "ollama", True),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama", True),
            ("nemotron-orchestrator-8b:latest", "ollama", True),
            ("mistral:7b-instruct", "ollama", True),
        ],
        live_ollama_reachable=True,
    )

    resolved = resolve_profile_assignments(
        "24GB_balanced",
        inventory,
        role_overrides={
            "risk_llm": ["mistral:7b-instruct", "martain7r/finance-llama-8b:q4_k_m"]
        },
        require_live_ollama=True,
    )
    assignments = {assignment.role: assignment for assignment in resolved["assignments"]}

    assert assignments["risk_llm"].requested_model == "mistral:7b-instruct"
    assert assignments["risk_llm"].resolved_model == "mistral:7b-instruct"
    assert assignments["risk_llm"].alternatives[0] == "martain7r/finance-llama-8b:q4_k_m"


def test_resolve_profile_assignments_marks_router_optional():
    inventory = _inventory(
        [
            ("qwen2.5:32b", "ollama", True),
            ("qwen3-coder:30b", "ollama", True),
            ("deepseek-r1-distill:14b", "ollama", True),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama", True),
        ],
        live_ollama_reachable=True,
    )

    resolved = resolve_profile_assignments(
        "24GB_balanced",
        inventory,
        require_live_ollama=True,
    )
    assignments = {assignment.role: assignment for assignment in resolved["assignments"]}

    assert resolved["missing_roles"] == []
    assert assignments["execution_router_llm"].required is False
    assert assignments["execution_router_llm"].available is False


def test_plan_missing_downloads_skips_models_not_exposed_by_live_host():
    inventory = _inventory(
        [
            ("qwen2.5:32b", "ollama", False),
            ("qwen3-coder:30b", "ollama", True),
            ("deepseek-r1-distill:14b", "ollama", True),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama", True),
            ("nemotron-orchestrator-8b:latest", "ollama", True),
        ],
        live_ollama_reachable=True,
    )

    requests = plan_missing_downloads(
        "24GB_balanced",
        inventory,
        require_live_ollama=True,
    )

    missing_roles = {request.role for request in requests}
    assert "idea_llm" not in missing_roles


def test_multi_llm_session_manager_falls_back_when_idea_role_missing():
    inventory = _inventory(
        [
            ("qwen3-coder:30b", "ollama"),
            ("deepseek-r1-distill:14b", "ollama"),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama"),
            ("nemotron-orchestrator-8b:latest", "ollama"),
        ]
    )
    manager = MultiLLMSessionManager(
        profile_name="fast_local",
        base_llm_config=LLMConfig(model="qwen3-coder:30b"),
        inventory=inventory,
        client_factory=lambda config: None,
    )

    bundle = manager.generate_objective(
        symbols=["BTCUSDT"],
        timeframes=["1h"],
        available_indicators=["rsi", "atr"],
        history_tail=[],
        fallback_objective="Fallback objective",
    )

    assert bundle["objective"] == "Fallback objective"
    assert bundle["used_fallback"] is True


def test_multi_llm_session_manager_runs_minimal_cycle():
    inventory = _inventory(
        [
            ("deepseek-moe-16b-local:latest", "ollama"),
            ("qwen3-coder:30b", "ollama"),
            ("deepseek-r1-distill:14b", "ollama"),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama"),
            ("nemotron-orchestrator-8b:latest", "ollama"),
        ]
    )

    called_models: list[str] = []

    class _FakeClient:
        def __init__(self, config: LLMConfig):
            self.config = config

        def chat(self, messages):
            model_name = self.config.model
            called_models.append(model_name)
            if "deepseek-moe-16b-local" in model_name:
                content = "Momentum breakout on BTCUSDT 1h with EMA + ATR + RSI filter."
            elif "finance-llama" in model_name:
                content = '{"risk_level":"medium","key_risks":["drawdown"],"mitigations":["reduce leverage"]}'
            else:
                content = '{"verdict":"promising","critique":"solid baseline","next_focus":["increase trade count"]}'
            return SimpleNamespace(
                content=content,
                provider=LLMProvider.OLLAMA,
                latency_ms=10.0,
                prompt_tokens=12,
                completion_tokens=18,
            )

    captured: dict[str, str] = {}

    def _builder_runner(run_objective: str, run_model: str):
        captured["objective"] = run_objective
        captured["model"] = run_model
        return SimpleNamespace(
            session_id="sess-1",
            status="success",
            best_sharpe=1.23,
            best_score=1.55,
            iterations=[1, 2],
            best_iteration=SimpleNamespace(
                backtest_result=SimpleNamespace(
                    metrics={
                        "sharpe_ratio": 1.23,
                        "total_return_pct": 12.4,
                        "max_drawdown_pct": -8.2,
                        "profit_factor": 1.4,
                        "total_trades": 24,
                    }
                )
            ),
        )

    manager = MultiLLMSessionManager(
        profile_name="fast_local",
        base_llm_config=LLMConfig(model="qwen3-coder:30b"),
        inventory=inventory,
        client_factory=_FakeClient,
    )
    result = manager.run_cycle(
        symbols=["BTCUSDT"],
        timeframes=["1h"],
        available_indicators=["ema", "atr", "rsi"],
        history_tail=[],
        target_sharpe=1.0,
        builder_runner=_builder_runner,
        fallback_objective="Fallback objective",
    )

    assert captured["model"] == "qwen3-coder:30b"
    assert "BTCUSDT" in captured["objective"]
    assert result.router_decision["action"] == "accept"
    assert result.role_outputs["execution_router_llm"].model == "deterministic_router"
    assert result.shared_memory["objective_context"]["objective"]
    assert result.shared_memory["latest_session"]["metrics"]["total_trades"] == 24
    assert result.shared_memory["risk_context"]["risk_level"] == "medium"
    assert all("orchestrator" not in model for model in called_models)
    assert result.session_summary["metrics"]["total_trades"] == 24
    assert manager.shared_memory_snapshot()["objective_context"]["objective"] == ""


def test_multi_llm_session_manager_unloads_role_models_and_exposes_prompt_inputs(
    monkeypatch,
):
    inventory = _inventory(
        [
            ("deepseek-moe-16b-local:latest", "ollama"),
            ("qwen3-coder:30b", "ollama"),
            ("deepseek-r1-distill:14b", "ollama"),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama"),
        ]
    )

    unloaded_models: list[str] = []

    monkeypatch.setattr(
        "core.llm_multi.session_manager.unload_model",
        lambda model_name, ollama_host=None: unloaded_models.append(model_name) or True,
    )

    class _FakeClient:
        def __init__(self, config: LLMConfig):
            self.config = config

        def chat(self, messages):
            if "deepseek-moe-16b-local" in self.config.model:
                content = (
                    '{"objective":"Test breakout on BTCUSDT 1h.",'
                    '"rationale":"Momentum after compression.",'
                    '"constraints":["Need at least 20 trades"],'
                    '"strategy_family":"breakout"}'
                )
            elif "finance-llama" in self.config.model:
                content = '{"risk_level":"medium","key_risks":["drawdown"],"mitigations":["reduce leverage"]}'
            else:
                content = '{"verdict":"promising","critique":"solid baseline","next_focus":["improve exits"]}'
            return SimpleNamespace(
                content=content,
                provider=LLMProvider.OLLAMA,
                latency_ms=10.0,
                prompt_tokens=12,
                completion_tokens=18,
            )

    manager = MultiLLMSessionManager(
        profile_name="fast_local",
        base_llm_config=LLMConfig(model="qwen3-coder:30b"),
        inventory=inventory,
        client_factory=_FakeClient,
    )
    objective_bundle = manager.generate_objective(
        symbols=["BTCUSDT"],
        timeframes=["1h"],
        available_indicators=["ema", "atr", "rsi"],
        history_tail=[{"symbol": "ETHUSDT", "timeframe": "4h"}],
        fallback_objective="Fallback objective",
    )
    review_bundle = manager.review_builder_session(
        objective=objective_bundle["objective"],
        builder_session=SimpleNamespace(
            session_id="sess-3",
            status="success",
            best_sharpe=1.05,
            best_score=1.15,
            iterations=[1],
            best_iteration=SimpleNamespace(
                backtest_result=SimpleNamespace(
                    metrics={
                        "sharpe_ratio": 1.05,
                        "total_return_pct": 8.1,
                        "max_drawdown_pct": -6.5,
                        "profit_factor": 1.2,
                        "total_trades": 22,
                    }
                )
            ),
        ),
        target_sharpe=1.0,
    )

    assert unloaded_models == [
        "deepseek-moe-16b-local:latest",
        "deepseek-r1-distill:14b",
        "martain7r/finance-llama-8b:q4_k_m",
    ]
    assert objective_bundle["role_output"].metadata["prompt_inputs"] == {
        "symbols": ["BTCUSDT"],
        "timeframes": ["1h"],
        "available_indicators": ["ema", "atr", "rsi"],
        "history_tail_size": 1,
    }
    assert objective_bundle["role_output"].metadata["model_lifecycle"][
        "unloaded_after_call"
    ] is True
    assert review_bundle["role_outputs"]["critic_llm"].metadata[
        "session_summary_in_prompt"
    ]["metrics"]["total_trades"] == 22
    assert review_bundle["role_outputs"]["risk_llm"].metadata[
        "session_summary_in_prompt"
    ]["metrics"]["sharpe_ratio"] == 1.05


def test_multi_llm_session_manager_routes_roles_to_distinct_hosts(monkeypatch):
    inventory = _inventory(
        [
            ("deepseek-moe-16b-local:latest", "ollama", True),
            ("qwen3-coder:30b", "ollama", True),
            ("deepseek-r1-distill:14b", "ollama", True),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama", True),
        ],
        live_ollama_reachable=True,
    )
    seen_calls: list[tuple[str, str]] = []
    unloaded: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "core.llm_multi.session_manager.unload_model",
        lambda model_name, ollama_host=None: unloaded.append(
            (model_name, str(ollama_host or ""))
        )
        or True,
    )

    class _FakeClient:
        def __init__(self, config: LLMConfig):
            self.config = config

        def chat(self, messages):
            seen_calls.append((self.config.model, self.config.ollama_host))
            if "deepseek-moe-16b-local" in self.config.model:
                content = (
                    '{"objective":"Test a breakout on BTCUSDT 1h.",'
                    '"rationale":"Momentum after compression.",'
                    '"constraints":["Need enough trades"],'
                    '"strategy_family":"breakout"}'
                )
            elif "finance-llama" in self.config.model:
                content = '{"risk_level":"medium","key_risks":["drawdown"],"mitigations":["reduce leverage"]}'
            else:
                content = '{"verdict":"promising","critique":"solid baseline","next_focus":["improve exits"]}'
            return SimpleNamespace(
                content=content,
                provider=LLMProvider.OLLAMA,
                latency_ms=10.0,
                prompt_tokens=12,
                completion_tokens=18,
            )

    manager = MultiLLMSessionManager(
        profile_name="fast_local",
        base_llm_config=LLMConfig(model="qwen3-coder:30b", ollama_host="http://127.0.0.1:11434"),
        inventory=inventory,
        llm_topology_config=build_phase1_topology(
            primary_host="http://127.0.0.1:11434",
            control_host="http://127.0.0.1:22434",
        ),
        client_factory=_FakeClient,
    )
    objective_bundle = manager.generate_objective(
        symbols=["BTCUSDT"],
        timeframes=["1h"],
        available_indicators=["ema", "atr", "rsi"],
        history_tail=[],
        fallback_objective="Fallback objective",
    )
    review_bundle = manager.review_builder_session(
        objective=objective_bundle["objective"],
        builder_session=SimpleNamespace(
            session_id="sess-route",
            status="success",
            best_sharpe=1.11,
            best_score=1.25,
            iterations=[1],
            best_iteration=SimpleNamespace(
                backtest_result=SimpleNamespace(
                    metrics={
                        "sharpe_ratio": 1.11,
                        "total_return_pct": 9.3,
                        "max_drawdown_pct": -6.2,
                        "profit_factor": 1.25,
                        "total_trades": 23,
                    }
                )
            ),
        ),
        target_sharpe=1.0,
    )

    assert seen_calls[0] == ("deepseek-moe-16b-local:latest", "http://127.0.0.1:11434")
    assert ("deepseek-r1-distill:14b", "http://127.0.0.1:22434") in seen_calls
    assert ("martain7r/finance-llama-8b:q4_k_m", "http://127.0.0.1:22434") in seen_calls
    assert ("deepseek-r1-distill:14b", "http://127.0.0.1:22434") in unloaded
    assert ("martain7r/finance-llama-8b:q4_k_m", "http://127.0.0.1:22434") in unloaded
    assert review_bundle["role_outputs"]["critic_llm"].metadata["route"]["ollama_host"] == "http://127.0.0.1:22434"
    assert review_bundle["role_outputs"]["risk_llm"].metadata["route"]["ollama_host"] == "http://127.0.0.1:22434"


def test_multi_llm_phase_clients_switch_same_host_models_and_cleanup(monkeypatch):
    inventory = _inventory(
        [
            ("deepseek-moe-16b-local:latest", "ollama", True),
            ("qwen3-coder:30b", "ollama", True),
            ("deepseek-r1-distill:14b", "ollama", True),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama", True),
        ],
        live_ollama_reachable=True,
    )
    unload_events: list[tuple[str, str]] = []
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        session_manager_module,
        "unload_model",
        lambda model_name, ollama_host=None: unload_events.append(
            (model_name, str(ollama_host or ""))
        )
        or True,
    )

    class _FakeClient:
        def __init__(self, config: LLMConfig):
            self.config = config

        def chat(
            self,
            messages,
            json_mode=False,
            temperature=None,
            max_tokens=None,
        ):
            calls.append((self.config.model, self.config.ollama_host))
            return SimpleNamespace(
                content='{"ok": true}',
                provider=LLMProvider.OLLAMA,
                latency_ms=5.0,
                prompt_tokens=8,
                completion_tokens=10,
            )

    manager = MultiLLMSessionManager(
        profile_name="fast_local",
        base_llm_config=LLMConfig(
            model="qwen3-coder:30b",
            ollama_host="http://127.0.0.1:11434",
        ),
        inventory=inventory,
        llm_topology_config=build_phase1_topology(
            primary_host="http://127.0.0.1:11434",
            control_host="http://127.0.0.1:11434",
        ),
        client_factory=_FakeClient,
    )

    phase_clients = manager.build_builder_phase_clients()
    phase_clients["code"].chat([SimpleNamespace(role="user", content="code")])
    phase_clients["analysis"].chat([SimpleNamespace(role="user", content="analysis")])
    phase_clients["pre_reflection"].chat(
        [SimpleNamespace(role="user", content="risk")]
    )
    releases = manager.release_runtime_models()
    snapshot = manager.runtime_flow_snapshot()

    assert calls == [
        ("qwen3-coder:30b", "http://127.0.0.1:11434"),
        ("deepseek-r1-distill:14b", "http://127.0.0.1:11434"),
        ("martain7r/finance-llama-8b:q4_k_m", "http://127.0.0.1:11434"),
    ]
    assert unload_events[:2] == [
        ("qwen3-coder:30b", "http://127.0.0.1:11434"),
        ("deepseek-r1-distill:14b", "http://127.0.0.1:11434"),
    ]
    assert releases == [
        {
            "host": "http://127.0.0.1:11434",
            "model": "martain7r/finance-llama-8b:q4_k_m",
            "released": True,
        }
    ]
    assert snapshot["active_models_by_host"] == {}
    assert any(
        event["event"] == "runtime_switch"
        and event["role"] == "critic_llm"
        and event["previous_model"] == "qwen3-coder:30b"
        for event in snapshot["recent_events"]
    )
    assert any(
        event["event"] == "runtime_release"
        and event["model"] == "martain7r/finance-llama-8b:q4_k_m"
        for event in snapshot["recent_events"]
    )


def test_multi_llm_session_manager_uses_builder_override():
    inventory = _inventory(
        [
            ("qwen2.5:32b", "ollama"),
            ("qwen3-coder:30b", "ollama"),
            ("deepseek-r1-distill:14b", "ollama"),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama"),
            ("nemotron-orchestrator-8b:latest", "ollama"),
            ("deepseek-coder-33b-local:latest", "ollama"),
        ]
    )

    manager = MultiLLMSessionManager(
        profile_name="24GB_balanced",
        base_llm_config=LLMConfig(model="qwen3-coder:30b"),
        inventory=inventory,
        role_overrides={"builder_llm": "deepseek-coder-33b-local:latest"},
        client_factory=lambda config: None,
    )

    assert manager.resolve_builder_model() == "deepseek-coder-33b-local:latest"


def test_multi_llm_role_client_emits_signals_and_recovers_once(monkeypatch):
    inventory = _inventory(
        [
            ("qwen3-coder:30b", "ollama", True),
            ("deepseek-r1-distill:14b", "ollama", True),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama", True),
            ("deepseek-moe-16b-local:latest", "ollama", True),
        ],
        live_ollama_reachable=True,
    )
    ensure_calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        session_manager_module,
        "ensure_ollama_running",
        lambda ollama_host=None, gpu_target=None: ensure_calls.append(
            (str(ollama_host or ""), gpu_target)
        )
        or (True, "restarted"),
    )

    class _RecoveringClient:
        def __init__(self, config: LLMConfig):
            self.config = config
            self.calls = 0

        def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("connection dropped")
            return SimpleNamespace(
                content='{"ok": true}',
                provider=LLMProvider.OLLAMA,
                latency_ms=5.0,
                prompt_tokens=8,
                completion_tokens=10,
            )

    manager = MultiLLMSessionManager(
        profile_name="fast_local",
        base_llm_config=LLMConfig(
            model="qwen3-coder:30b",
            ollama_host="http://127.0.0.1:11434",
        ),
        inventory=inventory,
        llm_topology_config=build_phase1_topology(
            primary_host="http://127.0.0.1:11434",
            control_host="http://127.0.0.1:22434",
        ),
        client_factory=_RecoveringClient,
    )

    critic_client = manager.build_role_client("critic_llm")
    response = critic_client.chat([SimpleNamespace(role="user", content="critique")])
    snapshot = manager.runtime_flow_snapshot()

    assert response.content == '{"ok": true}'
    assert ensure_calls == [("http://127.0.0.1:22434", "GPU-1")]
    assert any(
        event["event"] == "role_mission_failed"
        and event["role"] == "critic_llm"
        for event in snapshot["recent_events"]
    )
    assert any(
        event["event"] == "role_recovered"
        and event["role"] == "critic_llm"
        for event in snapshot["recent_events"]
    )
    critic_row = next(row for row in snapshot["role_rows"] if row["role"] == "critic_llm")
    assert critic_row["signal"] == "mission_done"


def test_multi_llm_session_manager_builder_role_no_longer_falls_back():
    inventory = _inventory(
        [
            ("deepseek-moe-16b-local:latest", "ollama"),
            ("deepseek-r1-distill:14b", "ollama"),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama"),
        ]
    )

    manager = MultiLLMSessionManager(
        profile_name="fast_local",
        base_llm_config=LLMConfig(model="qwen3-coder:30b"),
        inventory=inventory,
        client_factory=lambda config: None,
    )

    try:
        manager.resolve_builder_model()
    except RuntimeError as exc:
        assert "mono-model fallback disabled" in str(exc)
    else:
        raise AssertionError("builder_llm fallback should be disabled in multi-role mode")


def test_multi_llm_session_manager_consume_shared_memory_tracks_market_and_resets():
    inventory = _inventory(
        [
            ("deepseek-moe-16b-local:latest", "ollama"),
            ("qwen3-coder:30b", "ollama"),
            ("deepseek-r1-distill:14b", "ollama"),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama"),
        ]
    )

    class _FakeClient:
        def __init__(self, config: LLMConfig):
            self.config = config

        def chat(self, messages):
            if "deepseek-moe-16b-local" in self.config.model:
                content = (
                    '{"objective":"Test a breakout on ETHUSDT 4h.",'
                    '"rationale":"Trend continuation after compression.",'
                    '"constraints":["Need enough trades"],'
                    '"strategy_family":"breakout"}'
                )
            elif "finance-llama" in self.config.model:
                content = '{"risk_level":"low","key_risks":["spread"],"mitigations":["use liquid pairs"]}'
            else:
                content = '{"verdict":"promising","critique":"good baseline","next_focus":["tighten exits"]}'
            return SimpleNamespace(
                content=content,
                provider=LLMProvider.OLLAMA,
                latency_ms=5.0,
                prompt_tokens=8,
                completion_tokens=10,
            )

    manager = MultiLLMSessionManager(
        profile_name="fast_local",
        base_llm_config=LLMConfig(model="qwen3-coder:30b"),
        inventory=inventory,
        client_factory=_FakeClient,
    )
    objective_bundle = manager.generate_objective(
        symbols=["ETHUSDT"],
        timeframes=["4h"],
        available_indicators=["ema", "atr", "rsi"],
        history_tail=[],
        fallback_objective="Fallback objective",
    )
    manager.set_selected_market(symbol="ETHUSDT", timeframe="4h")
    review_bundle = manager.review_builder_session(
        objective=objective_bundle["objective"],
        builder_session=SimpleNamespace(
            session_id="sess-2",
            status="success",
            best_sharpe=1.1,
            best_score=1.2,
            iterations=[1],
            best_iteration=SimpleNamespace(
                backtest_result=SimpleNamespace(
                    metrics={
                        "sharpe_ratio": 1.1,
                        "total_return_pct": 9.5,
                        "max_drawdown_pct": -7.5,
                        "profit_factor": 1.3,
                        "total_trades": 21,
                    }
                )
            ),
        ),
        target_sharpe=1.0,
    )
    snapshot = manager.consume_shared_memory()

    assert review_bundle["router_decision"]["action"] == "accept"
    assert snapshot["market_context"] == {"symbol": "ETHUSDT", "timeframe": "4h"}
    assert snapshot["critic_context"]["next_focus"] == ["tighten exits"]
    assert snapshot["risk_context"]["risk_level"] == "low"
    assert manager.shared_memory_snapshot()["market_context"] == {
        "symbol": "",
        "timeframe": "",
    }


def test_multi_llm_session_manager_extracts_objective_field_from_json():
    inventory = _inventory(
        [
            ("deepseek-moe-16b-local:latest", "ollama"),
            ("qwen3-coder:30b", "ollama"),
            ("deepseek-r1-distill:14b", "ollama"),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama"),
            ("nemotron-orchestrator-8b:latest", "ollama"),
        ]
    )

    class _IdeaJsonClient:
        def __init__(self, config: LLMConfig):
            self.config = config

        def chat(self, messages):
            if "deepseek-moe-16b-local" in self.config.model:
                content = (
                    '{"objective":"Build a breakout strategy on ALGOUSDC 1h using RSI, '
                    'Bollinger and ATR."}'
                )
            else:
                content = '{"action":"iterate","confidence":0.5,"reason":"ok"}'
            return SimpleNamespace(
                content=content,
                provider=LLMProvider.OLLAMA,
                latency_ms=5.0,
                prompt_tokens=8,
                completion_tokens=10,
            )

    manager = MultiLLMSessionManager(
        profile_name="fast_local",
        base_llm_config=LLMConfig(model="qwen3-coder:30b"),
        inventory=inventory,
        client_factory=_IdeaJsonClient,
    )
    bundle = manager.generate_objective(
        symbols=["ALGOUSDC"],
        timeframes=["1h"],
        available_indicators=["rsi", "bollinger", "atr"],
        history_tail=[],
        fallback_objective="Fallback objective",
    )

    assert bundle["objective"] == (
        "Build a breakout strategy on ALGOUSDC 1h using RSI, Bollinger and ATR."
    )


def test_multi_llm_session_manager_extracts_objective_from_prefixed_json():
    inventory = _inventory(
        [
            ("deepseek-moe-16b-local:latest", "ollama"),
            ("qwen3-coder:30b", "ollama"),
            ("deepseek-r1-distill:14b", "ollama"),
            ("martain7r/finance-llama-8b:q4_k_m", "ollama"),
        ]
    )

    class _IdeaWrappedJsonClient:
        def __init__(self, config: LLMConfig):
            self.config = config

        def chat(self, messages):
            if "deepseek-moe-16b-local" in self.config.model:
                content = (
                    "json\n"
                    '{"objective":"Build a mean-reversion strategy on BTCUSDC 1h using RSI and EMA.",'
                    '"rationale":"Oversold bounce with trend confirmation.",'
                    '"constraints":["At least 20 trades"],'
                    '"strategy_family":"mean_reversion"}'
                )
            else:
                content = '{"verdict":"promising","critique":"ok","next_focus":["improve exits"]}'
            return SimpleNamespace(
                content=content,
                provider=LLMProvider.OLLAMA,
                latency_ms=5.0,
                prompt_tokens=8,
                completion_tokens=10,
            )

    manager = MultiLLMSessionManager(
        profile_name="fast_local",
        base_llm_config=LLMConfig(model="qwen3-coder:30b"),
        inventory=inventory,
        client_factory=_IdeaWrappedJsonClient,
    )
    bundle = manager.generate_objective(
        symbols=["BTCUSDC"],
        timeframes=["1h"],
        available_indicators=["rsi", "ema", "atr"],
        history_tail=[],
        fallback_objective="Fallback objective",
    )

    assert bundle["objective"].startswith(
        "Build a mean-reversion strategy on BTCUSDC 1h using RSI and EMA."
    )


def test_model_loader_falls_back_when_target_c_catalog_is_missing(tmp_path: Path, monkeypatch):
    fallback_models_json = tmp_path / "models.json"
    fallback_models_json.write_text("{}", encoding="utf-8")
    missing_current_catalog = tmp_path / "missing" / "catalog" / "models.json"

    monkeypatch.setenv("MODELS_JSON_PATH", str(missing_current_catalog))
    monkeypatch.setattr(model_loader_module, "CURRENT_MODELS_JSON_PATH", missing_current_catalog)
    monkeypatch.setattr(
        model_loader_module,
        "DEFAULT_MODELS_JSON_CANDIDATES",
        (fallback_models_json,),
    )

    assert model_loader_module.get_models_json_path() == fallback_models_json


def test_model_loader_prefers_c_catalog_over_legacy_d_env_when_present(tmp_path: Path, monkeypatch):
    current_models_json = tmp_path / "c_ai" / "catalog" / "models.json"
    legacy_models_json = tmp_path / "d_models" / "models.json"
    current_models_json.parent.mkdir(parents=True, exist_ok=True)
    legacy_models_json.parent.mkdir(parents=True, exist_ok=True)
    current_models_json.write_text("{}", encoding="utf-8")
    legacy_models_json.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("MODELS_JSON_PATH", str(legacy_models_json))
    monkeypatch.setattr(model_loader_module, "CURRENT_MODELS_JSON_PATH", current_models_json)
    monkeypatch.setattr(model_loader_module, "DEFAULT_MODELS_JSON_CANDIDATES", (current_models_json,))
    monkeypatch.setattr(model_loader_module, "LEGACY_MODELS_JSON_CANDIDATES", (legacy_models_json,))

    assert model_loader_module.get_models_json_path() == current_models_json


def test_model_loader_prefers_c_runtime_root_over_legacy_d_env_when_present(tmp_path: Path, monkeypatch):
    current_ollama_root = tmp_path / "c_ai" / "ollama" / "models"
    legacy_ollama_root = tmp_path / "d_models" / "ollama"
    current_ollama_root.mkdir(parents=True, exist_ok=True)
    legacy_ollama_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("OLLAMA_MODELS", str(legacy_ollama_root))
    monkeypatch.setattr(model_loader_module, "CURRENT_OLLAMA_MODELS_ROOT", current_ollama_root)
    monkeypatch.setattr(model_loader_module, "DEFAULT_OLLAMA_MODELS_CANDIDATES", (current_ollama_root,))
    monkeypatch.setattr(model_loader_module, "LEGACY_OLLAMA_MODELS_CANDIDATES", (legacy_ollama_root,))

    assert model_loader_module.get_ollama_models_root() == current_ollama_root


def test_model_loader_resolves_historical_aliases(monkeypatch):
    payload = {
        "ollama_models": [
            {
                "id": "qwen3-coder-30b",
                "name": "Qwen3 Coder 30B",
                "ollama_name": "qwen3-coder:30b",
                "backup_path": r"K:\models\qwen\qwen3-coder-next-40b-Q3_K_XL\model.gguf",
                "size_gb": 18.0,
            }
        ],
        "huggingface_models": [],
        "diffusion_models": [],
    }
    monkeypatch.setattr(model_loader_module, "load_models_json", lambda force_reload=False: payload)

    resolved = model_loader_module.get_model_by_id("qwen3-coder-40b-local")

    assert resolved is not None
    assert resolved["ollama_name"] == "qwen3-coder:30b"
    assert model_loader_module.get_ollama_model_names() == ["qwen3-coder:30b"]


def test_plan_missing_downloads_uses_current_runtime_roots(monkeypatch, tmp_path: Path):
    inventory = _inventory([("deepseek-r1-distill:14b", "ollama")])
    ollama_root = tmp_path / "c_runtime" / "ollama" / "models"
    monkeypatch.setattr(download_manager_module, "get_ollama_models_root", lambda: ollama_root)

    requests = plan_missing_downloads("24GB_balanced", inventory)

    assert requests
    assert all(request.destination_root == str(ollama_root) for request in requests if request.backend == "ollama")
