"""Local model discovery for the parallel multi-LLM builder."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import httpx

from utils.model_loader import get_models_json_path, load_models_json

DEFAULT_MODEL_SEARCH_ROOTS = (
    Path(r"D:\models\huggingface"),
    Path(r"D:\models\ollama"),
    Path(r"C:\LLM-Local"),
    Path(r"C:\Users\o3-Pro\Llama_ccp_win"),
)

_MODEL_FILE_SUFFIXES = {".gguf", ".safetensors", ".bin"}


def canonical_model_name(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        return ""
    if value.endswith(":latest"):
        value = value[:-7]
    return value.lower()


def _alias_variants(name: str) -> set[str]:
    raw = str(name or "").strip()
    if not raw:
        return set()
    aliases = {raw, raw.lower()}
    canonical = canonical_model_name(raw)
    if canonical:
        aliases.add(canonical)
    if ":" in raw:
        base = raw.split(":", 1)[0]
        aliases.add(base)
        aliases.add(base.lower())
    else:
        aliases.add(f"{raw}:latest")
        aliases.add(f"{raw.lower()}:latest")
    return {alias for alias in aliases if alias}


def _role_hints_for_name(name: str) -> List[str]:
    lowered = canonical_model_name(name)
    hints: set[str] = set()
    if any(token in lowered for token in ("qwen", "gemma", "mistral", "deepseek", "llama", "alia")):
        hints.add("idea_llm")
    if any(token in lowered for token in ("coder", "code", "qwen3-coder", "gpt-oss")):
        hints.add("builder_llm")
    if any(token in lowered for token in ("r1", "qwq", "critic", "think")):
        hints.add("critic_llm")
    if any(token in lowered for token in ("finance", "risk", "fin-llama", "dragon")):
        hints.add("risk_llm")
    if any(token in lowered for token in ("micro", "nano", "flash", "7b", "8b", "router", "orchestrator")):
        hints.add("execution_router_llm")
    return sorted(hints)


@dataclass
class DiscoveredModel:
    """Single discovered model entry."""

    name: str
    backend: str
    source: str
    verified_available: bool
    path: str = ""
    exists_on_disk: bool = False
    live: bool = False
    aliases: List[str] = field(default_factory=list)
    role_hints: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def matches(self, requested_name: str) -> bool:
        target = canonical_model_name(requested_name)
        return target in {canonical_model_name(alias) for alias in self.aliases}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "backend": self.backend,
            "source": self.source,
            "verified_available": self.verified_available,
            "path": self.path,
            "exists_on_disk": self.exists_on_disk,
            "live": self.live,
            "aliases": list(self.aliases),
            "role_hints": list(self.role_hints),
            "metadata": dict(self.metadata),
        }


@dataclass
class ModelInventory:
    """Structured inventory of all discovered local models."""

    discovered_models: List[DiscoveredModel]
    scanned_roots: List[str]
    missing_roots: List[str]
    warnings: List[str] = field(default_factory=list)
    live_ollama_host: str = ""
    live_ollama_reachable: bool = False

    def find(self, requested_name: str) -> Optional[DiscoveredModel]:
        target = canonical_model_name(requested_name)
        if not target:
            return None
        exact_matches = [
            model
            for model in self.discovered_models
            if target in {canonical_model_name(alias) for alias in model.aliases}
        ]
        if not exact_matches:
            return None
        exact_matches.sort(
            key=lambda model: (
                0 if model.verified_available else 1,
                0 if model.live else 1,
                model.name.lower(),
            )
        )
        return exact_matches[0]

    def summary(self) -> Dict[str, Any]:
        verified = [model for model in self.discovered_models if model.verified_available]
        by_backend: Dict[str, int] = {}
        for model in verified:
            by_backend[model.backend] = by_backend.get(model.backend, 0) + 1
        return {
            "total_models": len(self.discovered_models),
            "verified_models": len(verified),
            "catalog_only_models": len(self.discovered_models) - len(verified),
            "by_backend": by_backend,
            "live_ollama_reachable": self.live_ollama_reachable,
            "live_ollama_host": self.live_ollama_host,
            "scanned_roots": list(self.scanned_roots),
            "missing_roots": list(self.missing_roots),
            "warnings": list(self.warnings),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary(),
            "models": [model.to_dict() for model in self.discovered_models],
        }


def _preferred_search_roots(extra_roots: Optional[Iterable[str | Path]] = None) -> List[Path]:
    roots: List[Path] = list(DEFAULT_MODEL_SEARCH_ROOTS)
    env_ollama_models = os.environ.get("OLLAMA_MODELS")
    if env_ollama_models:
        roots.append(Path(env_ollama_models))
    models_json_path = get_models_json_path()
    roots.append(models_json_path.parent)
    if extra_roots:
        roots.extend(Path(root) for root in extra_roots)

    ordered: List[Path] = []
    seen: set[str] = set()
    for root in roots:
        normalized = str(root).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(Path(normalized))
    return ordered


def _merge_model_candidate(
    registry: Dict[str, DiscoveredModel],
    model: DiscoveredModel,
) -> None:
    key = canonical_model_name(model.name)
    if not key:
        return
    existing = registry.get(key)
    if existing is None:
        registry[key] = model
        return

    existing.aliases = sorted(set(existing.aliases) | set(model.aliases))
    existing.role_hints = sorted(set(existing.role_hints) | set(model.role_hints))
    existing.metadata.update({k: v for k, v in model.metadata.items() if v not in (None, "")})
    existing.verified_available = existing.verified_available or model.verified_available
    existing.exists_on_disk = existing.exists_on_disk or model.exists_on_disk
    existing.live = existing.live or model.live
    if model.path and (not existing.path or model.verified_available):
        existing.path = model.path
    if model.verified_available and not existing.verified_available:
        existing.source = model.source
        existing.backend = model.backend


def _register_model(
    registry: Dict[str, DiscoveredModel],
    *,
    name: str,
    backend: str,
    source: str,
    verified_available: bool,
    path: str = "",
    exists_on_disk: bool = False,
    live: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    aliases = sorted(_alias_variants(name))
    if metadata:
        for alias_key in ("ollama_name", "id", "model_name", "name"):
            alias_value = metadata.get(alias_key)
            aliases.extend(sorted(_alias_variants(alias_value)))
    model = DiscoveredModel(
        name=str(name).strip(),
        backend=backend,
        source=source,
        verified_available=verified_available,
        path=path,
        exists_on_disk=exists_on_disk,
        live=live,
        aliases=sorted(set(aliases)),
        role_hints=_role_hints_for_name(name),
        metadata=dict(metadata or {}),
    )
    _merge_model_candidate(registry, model)


def _discover_from_models_json(registry: Dict[str, DiscoveredModel]) -> None:
    payload = load_models_json(force_reload=True)
    for entry in payload.get("ollama_models", []):
        name = (
            entry.get("ollama_name")
            or entry.get("model_name")
            or entry.get("id")
            or entry.get("name")
        )
        if not name:
            continue
        candidate_path = str(entry.get("path") or entry.get("backup_path") or "").strip()
        exists_on_disk = bool(candidate_path) and Path(candidate_path).exists()
        _register_model(
            registry,
            name=name,
            backend="ollama",
            source="models_json",
            verified_available=exists_on_disk,
            path=candidate_path,
            exists_on_disk=exists_on_disk,
            metadata=entry,
        )

    for entry in payload.get("huggingface_models", []):
        name = entry.get("name") or entry.get("id")
        if not name:
            continue
        candidate_path = str(entry.get("path") or "").strip()
        exists_on_disk = bool(candidate_path) and Path(candidate_path).exists()
        _register_model(
            registry,
            name=name,
            backend="huggingface",
            source="models_json",
            verified_available=exists_on_disk,
            path=candidate_path,
            exists_on_disk=exists_on_disk,
            metadata=entry,
        )


def _discover_from_ollama_manifests(registry: Dict[str, DiscoveredModel], root: Path) -> None:
    manifest_root = root / "manifests"
    if not manifest_root.exists():
        return
    for manifest in manifest_root.rglob("*"):
        if not manifest.is_file():
            continue
        try:
            relative_parts = manifest.relative_to(manifest_root).parts
        except ValueError:
            continue
        if len(relative_parts) < 4:
            continue
        _, namespace, model_name, tag = relative_parts[:4]
        if namespace == "library":
            resolved_name = f"{model_name}:{tag}"
        else:
            resolved_name = f"{namespace}/{model_name}:{tag}"
        _register_model(
            registry,
            name=resolved_name,
            backend="ollama",
            source="ollama_manifest",
            verified_available=True,
            path=str(manifest),
            exists_on_disk=True,
            metadata={"manifest_path": str(manifest)},
        )


def _discover_from_huggingface_root(registry: Dict[str, DiscoveredModel], root: Path) -> None:
    if not root.exists():
        return
    for candidate in root.iterdir():
        if not candidate.is_dir():
            continue
        has_marker = any(
            (candidate / marker).exists()
            for marker in ("config.json", "model.safetensors.index.json", "tokenizer_config.json")
        )
        if not has_marker:
            continue
        _register_model(
            registry,
            name=candidate.name,
            backend="huggingface",
            source="filesystem",
            verified_available=True,
            path=str(candidate),
            exists_on_disk=True,
            metadata={"directory": str(candidate)},
        )


def _iter_generic_model_files(root: Path, max_depth: int = 2) -> Iterable[Path]:
    results: List[Path] = []
    if not root.exists():
        return results
    for base, dirs, files in os.walk(root):
        current = Path(base)
        try:
            depth = len(current.relative_to(root).parts)
        except ValueError:
            depth = 0
        if depth > max_depth:
            dirs[:] = []
            continue
        for filename in files:
            path = current / filename
            if path.suffix.lower() in _MODEL_FILE_SUFFIXES or filename == "config.json":
                results.append(path)
    return results


def _discover_from_generic_roots(registry: Dict[str, DiscoveredModel], roots: Iterable[Path]) -> None:
    for root in roots:
        if not root.exists():
            continue
        for marker in _iter_generic_model_files(root):
            marker_str = str(marker).lower().replace("/", "\\")
            if "\\models\\huggingface\\" in marker_str or "\\models\\ollama\\" in marker_str:
                continue
            name = marker.parent.name if marker.name == "config.json" else marker.stem
            backend = (
                "huggingface"
                if marker.suffix.lower() == ".safetensors" or marker.name == "config.json"
                else "gguf"
            )
            _register_model(
                registry,
                name=name,
                backend=backend,
                source="filesystem",
                verified_available=True,
                path=str(marker.parent if marker.name == "config.json" else marker),
                exists_on_disk=True,
                metadata={"marker": str(marker)},
            )


def _discover_from_live_ollama(
    registry: Dict[str, DiscoveredModel],
    *,
    ollama_host: str,
    warnings: List[str],
) -> bool:
    host = str(ollama_host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
    try:
        response = httpx.get(f"{host}/api/tags", timeout=3.0)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"ollama_api_unreachable: {exc}")
        return False

    for entry in payload.get("models", []):
        name = entry.get("name")
        if not name:
            continue
        _register_model(
            registry,
            name=name,
            backend="ollama",
            source="ollama_api",
            verified_available=True,
            exists_on_disk=True,
            live=True,
            metadata=entry,
        )
    return True


def discover_local_models(
    *,
    extra_roots: Optional[Iterable[str | Path]] = None,
    ollama_host: Optional[str] = None,
    include_live_ollama: bool = True,
) -> ModelInventory:
    """Build an inventory of local models across known roots and catalogs."""

    roots = _preferred_search_roots(extra_roots)
    scanned_roots = [str(root) for root in roots]
    missing_roots = [str(root) for root in roots if not root.exists()]
    warnings: List[str] = []
    registry: Dict[str, DiscoveredModel] = {}

    _discover_from_models_json(registry)

    for root in roots:
        root_str = str(root).lower().replace("/", "\\")
        if "models\\ollama" in root_str:
            _discover_from_ollama_manifests(registry, root)
        elif "models\\huggingface" in root_str:
            _discover_from_huggingface_root(registry, root)

    generic_roots = [
        root
        for root in roots
        if root.exists()
        and "models\\ollama" not in str(root).lower().replace("/", "\\")
        and "models\\huggingface" not in str(root).lower().replace("/", "\\")
    ]
    _discover_from_generic_roots(registry, generic_roots)

    host = str(ollama_host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
    live_ollama_reachable = False
    if include_live_ollama:
        live_ollama_reachable = _discover_from_live_ollama(
            registry,
            ollama_host=host,
            warnings=warnings,
        )

    models = sorted(
        registry.values(),
        key=lambda model: (
            0 if model.verified_available else 1,
            model.backend,
            canonical_model_name(model.name),
        ),
    )
    return ModelInventory(
        discovered_models=models,
        scanned_roots=scanned_roots,
        missing_roots=missing_roots,
        warnings=warnings,
        live_ollama_host=host,
        live_ollama_reachable=live_ollama_reachable,
    )
