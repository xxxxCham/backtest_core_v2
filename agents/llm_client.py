"""Module-ID: agents.llm_client

Purpose: Client LLM unifié supportant Ollama (local) et OpenAI (cloud) avec abstraction commune.

Role in pipeline: orchestration

Key components: LLMClient (abstract), OllamaClient, OpenAIClient, LLMConfig, LLMMessage, LLMResponse

Inputs: LLMConfig (provider, model, params), messages, système prompt

Outputs: LLMResponse (texte/JSON, usage tokens, timing)

Dependencies: httpx, pydantic, utils.log

Conventions: json_mode force JSON strict; parse_json gère blocs ```json ``` et inline; timeout adaptatif pour reasoning models (deepseek-r1, o1); fallback parsing si JSON mode échoue.

Read-if: Ajout providers, modification parsing, ou gestion erreurs LLM.

Skip-if: Vous appelez juste le client via create_llm_client().
"""

from __future__ import annotations

# pylint: disable=broad-except
import json
import os
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

import agents.ollama_manager as ollama_manager_module
from agents.ollama_runtime import (
    get_ollama_cloud_runtime_model_candidates,
    is_ollama_model_not_found_response,
    resolve_ollama_request_context,
)
from backtest.errors import LLMUnavailableError
from utils.observability import get_obs_logger

logger = get_obs_logger(__name__)


class StreamAbortRequest(Exception):
    """Levée par on_chunk pour demander un arrêt gracieux du stream (ex: boucle de répétition)."""


class LLMProvider(Enum):
    """Fournisseurs LLM supportés."""

    OLLAMA = "ollama"
    OPENAI = "openai"


@dataclass
class LLMConfig:
    """Configuration du client LLM."""

    provider: LLMProvider = LLMProvider.OLLAMA
    model: str = "llama3.2"

    # Ollama
    ollama_host: str = "http://127.0.0.1:11434"

    # OpenAI
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    # Paramètres de génération
    temperature: float = 0.7
    max_tokens: int = 2000
    num_ctx: int | None = None
    top_p: float = 0.9

    # Ollama keep_alive (ex: "20m", "0m" pour décharger immédiatement)
    keep_alive: str | None = None

    # Désactiver le mode "thinking" des modèles (gemma4, qwen3, etc.)
    # False = pas de <think> tags, None = laisser le modèle décider
    think: bool | None = False

    # Retry/timeout
    # Note: 600s (10min) par défaut pour supporter les modèles de raisonnement
    # (deepseek-r1, qwq, etc.) qui peuvent prendre 5-10 minutes
    timeout_seconds: int = 600
    max_retries: int = 3
    retry_delay_seconds: float = 1.0

    @classmethod
    def from_env(cls) -> LLMConfig:
        """Crée une configuration depuis les variables d'environnement."""
        provider_str = os.environ.get("BACKTEST_LLM_PROVIDER", "ollama").lower()
        provider = LLMProvider.OPENAI if provider_str == "openai" else LLMProvider.OLLAMA

        return cls(
            provider=provider,
            model=os.environ.get("BACKTEST_LLM_MODEL", "llama3.2"),
            ollama_host=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
            openai_api_key=os.environ.get("OPENAI_API_KEY"),
            openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            temperature=float(os.environ.get("BACKTEST_LLM_TEMPERATURE", "0.7")),
            max_tokens=int(os.environ.get("BACKTEST_LLM_MAX_TOKENS", "2000")),
            num_ctx=(int(os.environ["BACKTEST_LLM_NUM_CTX"]) if os.environ.get("BACKTEST_LLM_NUM_CTX") else None),
        )


@dataclass
class LLMMessage:
    """Message pour la conversation LLM."""

    role: str  # "system", "user", "assistant"
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    """Réponse du LLM."""

    content: str
    model: str
    provider: LLMProvider

    # Métriques
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0

    # Parsing
    raw_response: dict[str, Any] = field(default_factory=dict)
    parsed_json: dict[str, Any] | None = None
    parse_error: str | None = None

    # Streaming abort (répétition détectée en cours de génération)
    aborted: bool = False

    @property
    def is_valid(self) -> bool:
        """Vérifie si la réponse est valide."""
        return bool(self.content) and self.parse_error is None

    def parse_json(self) -> dict[str, Any] | None:
        """Tente de parser le contenu comme JSON.

        Gère les cas où le JSON est dans un bloc markdown ```json ... ```
        """
        if self.parsed_json is not None:
            return self.parsed_json

        content = self.content.strip()

        # Essayer de parser directement
        try:
            self.parsed_json = json.loads(content)
            return self.parsed_json
        except json.JSONDecodeError:
            pass

        # Chercher un bloc JSON dans markdown
        import re

        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        if json_match:
            try:
                self.parsed_json = json.loads(json_match.group(1))
                return self.parsed_json
            except json.JSONDecodeError as e:
                self.parse_error = f"JSON invalide dans bloc markdown: {e}"

        # Chercher un objet JSON dans le texte
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            try:
                self.parsed_json = json.loads(json_match.group())
                return self.parsed_json
            except json.JSONDecodeError as e:
                self.parse_error = f"JSON invalide: {e}"

        self.parse_error = "Aucun JSON trouvé dans la réponse"
        return None


class LLMClient(ABC):
    """Interface abstraite pour les clients LLM."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self._total_tokens = 0
        self._total_requests = 0

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Envoie une conversation au LLM.

        Args:
            messages: Liste de messages
            temperature: Override température
            max_tokens: Override max tokens
            json_mode: Forcer réponse JSON (si supporté)

        Returns:
            Réponse du LLM

        """

    @abstractmethod
    def is_available(self) -> bool:
        """Vérifie si le LLM est disponible."""

    def simple_chat(
        self,
        user_message: str,
        system_prompt: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Chat simplifié avec un seul message.

        Args:
            user_message: Message utilisateur
            system_prompt: Prompt système optionnel
            **kwargs: Arguments passés à chat()

        Returns:
            Réponse du LLM

        """
        messages = []
        if system_prompt:
            messages.append(LLMMessage(role="system", content=system_prompt))
        messages.append(LLMMessage(role="user", content=user_message))

        return self.chat(messages, **kwargs)

    @property
    def stats(self) -> dict[str, Any]:
        """Statistiques d'utilisation."""
        return {
            "total_tokens": self._total_tokens,
            "total_requests": self._total_requests,
            "provider": self.config.provider.value,
            "model": self.config.model,
        }

    def abort_current_stream(self) -> bool:
        """Demande l'arrêt du stream actif quand le provider le supporte."""
        return False


def _is_reasoning_model(model_name: str) -> bool:
    """Détecte si un modèle est un modèle de raisonnement qui peut prendre plus de temps.

    Les modèles de raisonnement comme deepseek-r1, qwq, o1, etc. peuvent prendre
    5-15 minutes pour raisonner sur des tâches complexes.
    """
    reasoning_patterns = [
        "deepseek-r1",
        "qwq",
        "o1",
        "o3",
        "r1",
        "reasoning",
    ]
    model_lower = model_name.lower()
    return any(pattern in model_lower for pattern in reasoning_patterns)


def _get_adaptive_timeout(config: LLMConfig) -> float:
    """Retourne un timeout adapté au type de modèle.

    - Modèles de raisonnement: 15 minutes (900s)
    - Modèles standards: timeout configuré
    """
    if _is_reasoning_model(config.model):
        logger.info(f"🧠 Modèle de raisonnement détecté ({config.model}): timeout étendu à 15 min")
        return 900.0  # 15 minutes pour les modèles de raisonnement
    return float(config.timeout_seconds)


class OllamaClient(LLMClient):
    """Client pour Ollama (LLM local)."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        # Timeout adaptatif selon le type de modèle
        adaptive_timeout = _get_adaptive_timeout(config)
        self._request_ctx = resolve_ollama_request_context(
            config.ollama_host,
            model_name=config.model,
        )
        self._request_ollama_host = str(
            self._request_ctx["effective_host"] or config.ollama_host,
        ).rstrip("/")
        self._request_model = str(
            self._request_ctx["request_model"] or config.model,
        ).strip() or config.model
        self._request_model_candidates = [
            candidate
            for candidate in get_ollama_cloud_runtime_model_candidates(
                config.model,
                direct_cloud=bool(self._request_ctx.get("direct_cloud")),
            )
            if str(candidate or "").strip()
        ]
        if self._request_model not in self._request_model_candidates:
            self._request_model_candidates.insert(0, self._request_model)
        client_kwargs: dict[str, Any] = {"timeout": adaptive_timeout}
        headers = dict(self._request_ctx.get("headers", {}) or {})
        if headers:
            client_kwargs["headers"] = headers
        self._http_client = httpx.Client(**client_kwargs)
        self._adaptive_timeout = adaptive_timeout
        self._stream_lock = threading.Lock()
        self._active_stream_response: httpx.Response | None = None
        self._stream_abort_requested = False

    def _register_active_stream_response(self, response: httpx.Response) -> None:
        with self._stream_lock:
            self._active_stream_response = response
            self._stream_abort_requested = False

    def _clear_active_stream_response(self) -> None:
        with self._stream_lock:
            self._active_stream_response = None

    def _consume_stream_abort_requested(self) -> bool:
        with self._stream_lock:
            requested = bool(self._stream_abort_requested)
            self._stream_abort_requested = False
            return requested

    def _is_stream_abort_requested(self) -> bool:
        with self._stream_lock:
            return bool(self._stream_abort_requested)

    def abort_current_stream(self) -> bool:
        with self._stream_lock:
            response = self._active_stream_response
            if response is None:
                return False
            self._stream_abort_requested = True
            self._active_stream_response = None
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass
        return True

    def _messages_to_prompt(self, messages: list[LLMMessage], json_mode: bool) -> str:
        """Convertit une conversation en prompt simple pour /api/generate."""
        lines: list[str] = []
        for msg in messages:
            role = (msg.role or "user").strip().lower()
            if role == "system":
                label = "System"
            elif role == "assistant":
                label = "Assistant"
            else:
                label = "User"
            content = msg.content.strip()
            if content:
                lines.append(f"{label}: {content}")
        if json_mode:
            lines.append("System: Respond with valid JSON only.")
        lines.append("Assistant:")
        return "\n".join(lines).strip()

    def _request_model_sequence(self) -> list[str]:
        sequence = [self._request_model]
        sequence.extend(
            candidate for candidate in self._request_model_candidates if candidate != self._request_model
        )
        return sequence

    def _promote_request_model(self, model_name: str) -> None:
        candidate = str(model_name or "").strip()
        if not candidate:
            return
        self._request_model = candidate
        self._request_model_candidates = [candidate] + [
            item for item in self._request_model_candidates if item != candidate
        ]

    def _chat_via_generate(
        self,
        messages: list[LLMMessage],
        temperature: float | None,
        max_tokens: int | None,
        json_mode: bool,
    ) -> LLMResponse:
        """Fallback Ollama via /api/generate quand /api/chat est indisponible."""
        url = f"{self._request_ollama_host}/api/generate"
        prompt = self._messages_to_prompt(messages, json_mode)

        payload = {
            "model": self._request_model,
            "prompt": prompt,
            "stream": False,
            "options": self._build_ollama_options(
                temperature=temperature,
                max_tokens=max_tokens,
            ),
        }

        self._inject_keep_alive(payload)
        if self.config.think is not None:
            payload["think"] = self.config.think
        if json_mode:
            payload["format"] = "json"

        start_time = time.time()
        try:
            response = None
            for candidate_model in self._request_model_sequence():
                payload["model"] = candidate_model
                response = self._http_client.post(
                    url,
                    json=payload,
                    timeout=self._adaptive_timeout,
                )
                body = str(getattr(response, "text", "") or "")
                if is_ollama_model_not_found_response(response.status_code, body):
                    continue
                response.raise_for_status()
                self._promote_request_model(candidate_model)
                break
            if response is None:
                raise RuntimeError("generate fallback failed: no request candidate available")
            if is_ollama_model_not_found_response(response.status_code, getattr(response, "text", "")):
                raise RuntimeError(
                    f"generate fallback failed: modèle introuvable pour {self.config.model}",
                )
        except Exception as exc:
            logger.warning("Ollama /api/generate échoué: %s", exc)
            return LLMResponse(
                content="",
                model=self.config.model,
                provider=LLMProvider.OLLAMA,
                parse_error=f"generate fallback failed: {exc}",
            )

        data = response.json()
        latency = (time.time() - start_time) * 1000

        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        total_tokens = prompt_tokens + completion_tokens

        self._total_tokens += total_tokens
        self._total_requests += 1

        llm_response = LLMResponse(
            content=data.get("response", ""),
            model=self.config.model,
            provider=LLMProvider.OLLAMA,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency,
            raw_response=data,
        )

        if json_mode:
            llm_response.parse_json()

        return llm_response

    def close(self) -> None:
        """Ferme le client HTTP sous-jacent."""
        try:
            self.abort_current_stream()
            self._http_client.close()
        except Exception:  # noqa: BLE001
            pass

    def _inject_keep_alive(self, payload: dict) -> None:
        """Injecte keep_alive dans le payload si configuré."""
        if self.config.keep_alive is not None:
            payload["keep_alive"] = self.config.keep_alive

    def is_available(self) -> bool:
        """Vérifie si Ollama est disponible."""
        return ollama_manager_module.is_ollama_available(self._request_ollama_host)

    def list_models(self) -> list[str]:
        """Liste les modèles disponibles dans Ollama."""
        return ollama_manager_module.list_ollama_models(self._request_ollama_host)

    def _build_ollama_options(
        self,
        *,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": self.config.temperature if temperature is None else temperature,
            "num_predict": self.config.max_tokens if max_tokens is None else max_tokens,
            "top_p": self.config.top_p,
        }
        if self.config.num_ctx is not None:
            options["num_ctx"] = self.config.num_ctx
        return options

    def chat(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Envoie une conversation à Ollama."""
        url = f"{self._request_ollama_host}/api/chat"
        use_generate_fallback = False

        payload = {
            "model": self._request_model,
            "messages": [m.to_dict() for m in messages],
            "stream": False,
            "options": self._build_ollama_options(
                temperature=temperature,
                max_tokens=max_tokens,
            ),
        }

        self._inject_keep_alive(payload)
        if self.config.think is not None:
            payload["think"] = self.config.think
        if json_mode:
            payload["format"] = "json"

        start_time = time.time()

        for attempt in range(self.config.max_retries):
            try:
                # Log avec timeout adaptatif pour information
                if attempt == 0:
                    logger.info(
                        f"🤖 Interrogation {self.config.model} (timeout: {self._adaptive_timeout:.0f}s)...",
                    )

                if use_generate_fallback:
                    return self._chat_via_generate(messages, temperature, max_tokens, json_mode)

                response = None
                for candidate_model in self._request_model_sequence():
                    payload["model"] = candidate_model
                    response = self._http_client.post(
                        url,
                        json=payload,
                        timeout=self._adaptive_timeout,
                    )
                    body = str(getattr(response, "text", "") or "")
                    if is_ollama_model_not_found_response(response.status_code, body):
                        continue
                    if response.status_code == 404:
                        logger.warning(
                            "Ollama /api/chat introuvable (404). Fallback vers /api/generate.",
                        )
                        use_generate_fallback = True
                        return self._chat_via_generate(messages, temperature, max_tokens, json_mode)
                    response.raise_for_status()
                    self._promote_request_model(candidate_model)
                    break
                if response is None:
                    raise RuntimeError("no Ollama request candidate available")
                if is_ollama_model_not_found_response(response.status_code, getattr(response, "text", "")):
                    raise RuntimeError(f"model request failed for {self.config.model}: no alias accepted")

                data = response.json()
                latency = (time.time() - start_time) * 1000

                # Extraire les tokens si disponibles
                prompt_tokens = data.get("prompt_eval_count", 0)
                completion_tokens = data.get("eval_count", 0)
                total_tokens = prompt_tokens + completion_tokens

                self._total_tokens += total_tokens
                self._total_requests += 1

                llm_response = LLMResponse(
                    content=data.get("message", {}).get("content", ""),
                    model=self.config.model,
                    provider=LLMProvider.OLLAMA,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency,
                    raw_response=data,
                )

                if json_mode:
                    llm_response.parse_json()

                return llm_response

            except httpx.TimeoutException:
                elapsed = time.time() - start_time
                logger.warning(
                    f"⏱️ Timeout Ollama après {elapsed:.1f}s (tentative {attempt + 1}/{self.config.max_retries})",
                )
                logger.info(
                    f"💡 Le modèle {self.config.model} peut prendre du temps pour raisonner. Patience...",
                )
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay_seconds * (attempt + 1))
            except Exception as e:
                logger.error(f"Erreur Ollama: {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay_seconds)

        # Échec après tous les retries
        return LLMResponse(
            content="",
            model=self.config.model,
            provider=LLMProvider.OLLAMA,
            parse_error="Échec après plusieurs tentatives",
        )

    def chat_stream(
        self,
        messages: list[LLMMessage],
        *,
        on_chunk: Callable[[str], None] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Chat avec streaming token par token via l'API Ollama native.

        Appelle ``on_chunk(text)`` pour chaque fragment de texte généré,
        puis retourne la réponse complète comme ``chat()``.

        Si ``on_chunk`` est None, délègue à ``chat()`` classique.
        """
        if on_chunk is None:
            return self.chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
            )

        url = f"{self._request_ollama_host}/api/chat"
        payload = {
            "model": self._request_model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
            "options": self._build_ollama_options(
                temperature=temperature,
                max_tokens=max_tokens,
            ),
        }
        self._inject_keep_alive(payload)
        if self.config.think is not None:
            payload["think"] = self.config.think
        if json_mode:
            payload["format"] = "json"

        start_time = time.time()
        full_content: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0
        _stream_aborted = False

        logger.info(
            "🤖 Interrogation streaming %s (timeout: %.0fs)...",
            self.config.model,
            self._adaptive_timeout,
        )

        try:
            accepted_stream = False
            for candidate_model in self._request_model_sequence():
                payload["model"] = candidate_model
                with self._http_client.stream(
                    "POST",
                    url,
                    json=payload,
                    timeout=self._adaptive_timeout,
                ) as response:
                    self._register_active_stream_response(response)
                    try:
                        if response.status_code >= 400:
                            body = response.read().decode("utf-8", errors="ignore")
                            if is_ollama_model_not_found_response(response.status_code, body):
                                continue
                            if response.status_code == 404:
                                logger.warning(
                                    "Ollama /api/chat introuvable (404). Fallback vers /api/generate.",
                                )
                                return self.chat(
                                    messages,
                                    temperature=temperature,
                                    max_tokens=max_tokens,
                                    json_mode=json_mode,
                                )
                            response.raise_for_status()
                        self._promote_request_model(candidate_model)
                        accepted_stream = True
                        for line in response.iter_lines():
                            if self._is_stream_abort_requested():
                                _stream_aborted = True
                                break
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            chunk = data.get("message", {}).get("content", "")
                            if chunk:
                                full_content.append(chunk)
                                try:
                                    on_chunk(chunk)
                                except StreamAbortRequest:
                                    logger.warning(
                                        "stream_repetition_abort model=%s chars_received=%d",
                                        self.config.model,
                                        sum(len(c) for c in full_content),
                                    )
                                    _stream_aborted = True
                                    break
                                except Exception:  # noqa: BLE001
                                    pass
                            if data.get("done", False):
                                prompt_tokens = data.get("prompt_eval_count", 0)
                                completion_tokens = data.get("eval_count", 0)
                                break
                        break
                    finally:
                        self._clear_active_stream_response()
            if not accepted_stream:
                raise RuntimeError(f"stream request failed for {self.config.model}: no alias accepted")
        except Exception as exc:
            if self._consume_stream_abort_requested():
                logger.info(
                    "Streaming Ollama interrompu explicitement model=%s",
                    self.config.model,
                )
                _stream_aborted = True
            else:
                logger.warning("Streaming Ollama échoué (%s) — fallback non-stream", exc)
                return self.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )

        latency = (time.time() - start_time) * 1000
        total_tokens = prompt_tokens + completion_tokens
        self._total_tokens += total_tokens
        self._total_requests += 1

        content = "".join(full_content)
        llm_response = LLMResponse(
            content=content,
            model=self.config.model,
            provider=LLMProvider.OLLAMA,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency,
            raw_response={},
            aborted=_stream_aborted,
        )
        if json_mode:
            llm_response.parse_json()

        return llm_response


class OpenAIClient(LLMClient):
    """Client pour OpenAI API (et compatibles)."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)

        if not config.openai_api_key:
            raise LLMUnavailableError(
                "OpenAI API key requise (OPENAI_API_KEY)",
                provider="openai",
                reason="missing_api_key",
            )

        # Timeout adaptatif selon le type de modèle
        adaptive_timeout = _get_adaptive_timeout(config)
        self._adaptive_timeout = adaptive_timeout

        self._http_client = httpx.Client(
            timeout=adaptive_timeout,
            headers={
                "Authorization": f"Bearer {config.openai_api_key}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        """Ferme le client HTTP sous-jacent."""
        try:
            self._http_client.close()
        except Exception:  # noqa: BLE001
            pass

    def is_available(self) -> bool:
        """Vérifie si l'API OpenAI est disponible."""
        try:
            response = self._http_client.get(
                f"{self.config.openai_base_url}/models",
                timeout=5.0,
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"OpenAI non disponible: {e}")
            return False

    def chat(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Envoie une conversation à OpenAI."""
        url = f"{self.config.openai_base_url}/chat/completions"

        payload = {
            "model": self.config.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
            "top_p": self.config.top_p,
        }

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        start_time = time.time()

        for attempt in range(self.config.max_retries):
            try:
                response = self._http_client.post(url, json=payload)
                response.raise_for_status()

                data = response.json()
                latency = (time.time() - start_time) * 1000

                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)

                self._total_tokens += total_tokens
                self._total_requests += 1

                content = ""
                if data.get("choices"):
                    content = data["choices"][0].get("message", {}).get("content", "")

                llm_response = LLMResponse(
                    content=content,
                    model=self.config.model,
                    provider=LLMProvider.OPENAI,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    latency_ms=latency,
                    raw_response=data,
                )

                if json_mode:
                    llm_response.parse_json()

                return llm_response

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Rate limit
                    wait_time = self.config.retry_delay_seconds * (2**attempt)
                    logger.warning(f"Rate limit OpenAI, attente {wait_time}s")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Erreur OpenAI HTTP: {e}")
                    break
            except Exception as e:
                logger.error(f"Erreur OpenAI: {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay_seconds)

        return LLMResponse(
            content="",
            model=self.config.model,
            provider=LLMProvider.OPENAI,
            parse_error="Échec après plusieurs tentatives",
        )


def create_llm_client(config: LLMConfig | None = None) -> LLMClient:
    """Factory pour créer le bon client LLM.

    Args:
        config: Configuration (ou depuis env si None)

    Returns:
        Client LLM approprié

    """
    if config is None:
        config = LLMConfig.from_env()

    if config.provider == LLMProvider.OPENAI:
        return OpenAIClient(config)
    return OllamaClient(config)
