from __future__ import annotations

from types import SimpleNamespace

from agents import ollama_manager as ollama_manager_module
from agents.llm_client import LLMConfig, LLMMessage, LLMProvider, LLMResponse, OllamaClient


def test_unload_model_defers_while_ollama_request_active(monkeypatch):
    host = "http://127.0.0.1:11434"
    post_calls: list[str] = []

    def _fake_post(*args, **kwargs):
        del args, kwargs
        post_calls.append("called")
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(ollama_manager_module.httpx, "post", _fake_post)

    token = ollama_manager_module.begin_ollama_request(host, "qwen3.6:35b")
    try:
        assert ollama_manager_module.unload_model("qwen3.6:35b", ollama_host=host) is False
    finally:
        ollama_manager_module.end_ollama_request(token)

    assert post_calls == []


def test_cleanup_all_models_defers_while_ollama_request_active(monkeypatch):
    host = "http://127.0.0.1:11434"
    get_calls: list[str] = []

    def _fake_get(*args, **kwargs):
        del args, kwargs
        get_calls.append("called")
        return SimpleNamespace(status_code=200, json=lambda: {"models": [{"name": "qwen3.6:35b"}]})

    monkeypatch.setattr(ollama_manager_module.httpx, "get", _fake_get)

    token = ollama_manager_module.begin_ollama_request(host, "qwen3.6:35b")
    try:
        assert ollama_manager_module.cleanup_all_models(host) == 0
    finally:
        ollama_manager_module.end_ollama_request(token)

    assert get_calls == []


def test_stop_owned_ollama_defers_while_request_active():
    host = "http://127.0.0.1:11434"
    terminated = {"called": False}

    class _FakeProcess:
        def poll(self):
            return None

        def terminate(self):
            terminated["called"] = True

    record = ollama_manager_module._OwnedOllamaProcess(host=host, process=_FakeProcess())
    with ollama_manager_module._OWNED_OLLAMA_LOCK:
        ollama_manager_module._OWNED_OLLAMA_PROCESSES[host] = record

    token = ollama_manager_module.begin_ollama_request(host, "qwen3.6:35b")
    try:
        assert ollama_manager_module.stop_owned_local_ollama_server(host) == 0
        with ollama_manager_module._OWNED_OLLAMA_LOCK:
            assert ollama_manager_module._OWNED_OLLAMA_PROCESSES.get(host) is record
    finally:
        ollama_manager_module.end_ollama_request(token)
        with ollama_manager_module._OWNED_OLLAMA_LOCK:
            ollama_manager_module._OWNED_OLLAMA_PROCESSES.pop(host, None)

    assert terminated["called"] is False


def test_ollama_client_registers_active_request_during_chat(monkeypatch):
    host = "http://127.0.0.1:11434"
    client = OllamaClient(
        LLMConfig(
            provider=LLMProvider.OLLAMA,
            model="qwen3.6:35b",
            ollama_host=host,
        ),
    )

    def _fake_chat_untracked(self, messages, temperature=None, max_tokens=None, json_mode=False):
        del self, messages, temperature, max_tokens, json_mode
        assert ollama_manager_module.get_active_ollama_request_count(host) == 1
        return LLMResponse(content="ok", model="qwen3.6:35b", provider=LLMProvider.OLLAMA)

    monkeypatch.setattr(OllamaClient, "_chat_untracked", _fake_chat_untracked)

    try:
        response = client.chat([LLMMessage(role="user", content="ping")])
    finally:
        client.close()

    assert response.content == "ok"
    assert ollama_manager_module.get_active_ollama_request_count(host) == 0


def test_warmup_model_unloads_competing_model_before_preload(monkeypatch):
    host = "http://127.0.0.1:11434"
    post_payloads: list[dict] = []

    def _fake_get(url, **kwargs):
        del url, kwargs
        return SimpleNamespace(
            status_code=200,
            content=b"{}",
            json=lambda: {"models": [{"name": "qwen3.6:35b"}]},
        )

    def _fake_post(url, json=None, **kwargs):
        del url, kwargs
        post_payloads.append(dict(json or {}))
        return SimpleNamespace(status_code=200, content=b"{}", json=lambda: {})

    monkeypatch.setattr(ollama_manager_module.httpx, "get", _fake_get)
    monkeypatch.setattr(ollama_manager_module.httpx, "post", _fake_post)
    monkeypatch.setattr(ollama_manager_module.time, "sleep", lambda *_args, **_kwargs: None)

    ok, detail = ollama_manager_module.warmup_model(
        "gemma4:26b",
        ollama_host=host,
        timeout_s=300.0,
    )

    assert ok is True
    assert "concurrents déchargés" in detail
    assert post_payloads[0]["model"] == "qwen3.6:35b"
    assert post_payloads[0]["keep_alive"] == 0
    assert post_payloads[1]["model"] == "gemma4:26b"
    assert post_payloads[1]["keep_alive"] == "10m"


def test_warmup_model_defers_competing_unload_when_request_active(monkeypatch):
    host = "http://127.0.0.1:11434"
    post_calls: list[str] = []

    def _fake_get(url, **kwargs):
        del url, kwargs
        return SimpleNamespace(
            status_code=200,
            content=b"{}",
            json=lambda: {"models": [{"name": "qwen3.6:35b"}]},
        )

    def _fake_post(*args, **kwargs):
        del args, kwargs
        post_calls.append("called")
        return SimpleNamespace(status_code=200, content=b"{}", json=lambda: {})

    monkeypatch.setattr(ollama_manager_module.httpx, "get", _fake_get)
    monkeypatch.setattr(ollama_manager_module.httpx, "post", _fake_post)

    token = ollama_manager_module.begin_ollama_request(host, "qwen3.6:35b")
    try:
        ok, detail = ollama_manager_module.warmup_model(
            "gemma4:26b",
            ollama_host=host,
            timeout_s=300.0,
        )
    finally:
        ollama_manager_module.end_ollama_request(token)

    assert ok is False
    assert "warmup différé" in detail
    assert post_calls == []
