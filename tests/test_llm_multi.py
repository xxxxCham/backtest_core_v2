from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agents.llm_client import LLMConfig, LLMProvider
from core.llm_multi.download_manager import plan_missing_downloads
from core.llm_multi.model_discovery import (
    DiscoveredModel,
    ModelInventory,
    discover_local_models,
)
from core.llm_multi.registry import resolve_profile_assignments
from core.llm_multi.session_manager import MultiLLMSessionManager
import core.llm_multi.model_discovery as model_discovery_module


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
    assert "execution_router_llm" in missing_roles


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

    class _FakeClient:
        def __init__(self, config: LLMConfig):
            self.config = config

        def chat(self, messages):
            model_name = self.config.model
            if "deepseek-moe-16b-local" in model_name:
                content = "Momentum breakout on BTCUSDT 1h with EMA + ATR + RSI filter."
            elif "finance-llama" in model_name:
                content = '{"risk_level":"medium","key_risks":["drawdown"],"mitigations":["reduce leverage"]}'
            elif "orchestrator" in model_name:
                content = '{"action":"iterate","confidence":0.82,"reason":"needs more trades"}'
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
        fallback_builder_model="deepseek-coder-33b-local:latest",
        builder_runner=_builder_runner,
        fallback_objective="Fallback objective",
    )

    assert captured["model"] == "qwen3-coder:30b"
    assert "BTCUSDT" in captured["objective"]
    assert result.router_decision["action"] == "iterate"
    assert result.session_summary["metrics"]["total_trades"] == 24


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
