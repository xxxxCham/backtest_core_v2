from __future__ import annotations

import argparse
import copy
import json
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

HF_ARCHIVE_SPECS: list[dict[str, Any]] = [
    {
        "id": "llama2-13b-fp16-hf",
        "name": "Llama 2 13B FP16 (HuggingFace)",
        "relative_archive": Path(r"llama2-13b-fp16"),
        "format": "safetensors",
        "use_case": "general_transformers",
        "parameters": "13B",
        "quantization": "fp16",
        "context_length": 4096,
        "description": "Meta Llama 2 13B au format HuggingFace.",
    },
    {
        "id": "llama-3.1-8b-instruct-hf",
        "name": "Llama 3.1 8B Instruct (HuggingFace)",
        "relative_archive": Path(r"llama-3.1-8b-instruct"),
        "format": "safetensors",
        "use_case": "instruction_transformers",
        "parameters": "8B",
        "quantization": "fp16",
        "context_length": 128000,
        "description": "Meta Llama 3.1 8B Instruct au format HuggingFace.",
    },
    {
        "id": "fin-llama-33b-hf",
        "name": "Fin Llama 33B (HuggingFace)",
        "relative_archive": Path(r"fin-llama-33b"),
        "format": "safetensors",
        "use_case": "reasoning_finance",
        "parameters": "33B",
        "quantization": "fp16",
        "context_length": 128000,
        "description": "Fin Llama 33B source HuggingFace pour usage finance.",
    },
    {
        "id": "nemotron-3-nano-30b-hf",
        "name": "Nemotron 3 Nano 30B (HuggingFace)",
        "relative_archive": Path(r"nemotron-3-nano-30b"),
        "format": "safetensors",
        "use_case": "reasoning_transformers",
        "parameters": "30B",
        "quantization": "fp16",
        "context_length": 32768,
        "description": "Nemotron 3 Nano 30B source HuggingFace.",
    },
]

CANONICAL_OLLAMA_NAMES = {
    "devstral-small-2": "devstral-small-2:24b",
    "deepseek-r1-14b-local:latest": "deepseek-r1-distill:14b",
    "deepseek-r1-14b-local": "deepseek-r1-distill:14b",
    "lfm2": "lfm2:24b",
    "nemotron-cascade-14b-thinking-claude-4.5-opus-distill.q8_0:latest": "nemotron-cascade-14b-local:latest",
    "nemotron-cascade-14b-thinking-claude-4.5-opus-distill.q8_0": "nemotron-cascade-14b-local:latest",
    "qwen3.5": "qwen3.5:35b",
    "qwen3-coder-next": "qwen3-coder:30b",
    "qwen3-coder-next:q4_k_m": "qwen3-coder:30b",
    "qwen3-vl": "qwen3-vl:32b",
    "qwen3-vl:30b": "qwen3-vl:32b",
}

DISCOVERED_OLLAMA_METADATA_OVERRIDES: dict[str, dict[str, Any]] = {
    "devstral-small-2:24b": {
        "id": "devstral-small-2-24b",
        "name": "Devstral Small 2 24B",
        "use_case": "coding",
        "parameters": "24.0B",
        "quantization": "Q4_K_M",
        "context_length": 393216,
        "description": "Devstral Small 2 24B - agent de code local pour exploration et edition multi-fichiers.",
    },
    "lfm2:24b": {
        "id": "lfm2-24b",
        "name": "LFM2 24B",
        "use_case": "general",
        "parameters": "23.8B",
        "quantization": "Q4_K_M",
        "context_length": 32768,
        "description": "LFM2 24B - modele generaliste efficace pour une machine locale 24GB-class.",
    },
    "qwen3-30b-a3b:q4_k_m": {
        "id": "qwen3-30b-a3b-q4_k_m",
        "name": "Qwen3 30B A3B Q4_K_M",
        "use_case": "coding_reasoning",
        "parameters": "30.5B",
        "quantization": "Q4_K_M",
        "context_length": 40960,
        "description": "Qwen3 30B A3B Q4_K_M importe depuis la bibliotheque GGUF canonique.",
    },
    "qwen3-vl:32b": {
        "id": "qwen3-vl-32b",
        "name": "Qwen3 VL 32B",
        "use_case": "multimodal",
        "parameters": "33.4B",
        "quantization": "Q4_K_M",
        "context_length": 262144,
        "description": "Qwen3 Vision-Language 32B - vision, outils et raisonnement sur endpoint Ollama local.",
    },
    "qwen3.5:35b": {
        "id": "qwen3.5-35b",
        "name": "Qwen 3.5 35B",
        "use_case": "multimodal",
        "parameters": "36.0B",
        "quantization": "Q4_K_M",
        "context_length": 262144,
        "description": "Qwen 3.5 35B - modele multimodal generaliste recent, haut de gamme local.",
    },
}


def _folder_stats(path: Path) -> tuple[int, int]:
    if not path.exists():
        raise FileNotFoundError(f"Missing required path: {path}")
    files = [candidate for candidate in path.rglob("*") if candidate.is_file()]
    size_bytes = sum(candidate.stat().st_size for candidate in files)
    return size_bytes, len(files)


def _registry_path_to_runtime_name(path_str: str) -> str:
    normalized = path_str.replace("\\", "/").strip("/")
    parts = [chunk for chunk in normalized.split("/") if chunk]
    if len(parts) < 4 or parts[0].lower() != "registry.ollama.ai":
        return path_str.replace("\\", "/")

    namespace = parts[1]
    if namespace.lower() == "library":
        model = parts[2]
        tag = "/".join(parts[3:])
        return f"{model}:{tag}" if tag else model

    model = f"{namespace}/{parts[2]}"
    tag = "/".join(parts[3:])
    return f"{model}:{tag}" if tag else model


def _runtime_name_variants(name: str) -> set[str]:
    raw = str(name or "").strip()
    if not raw:
        return set()
    normalized = _registry_path_to_runtime_name(raw) if raw.lower().startswith("registry.ollama.ai/") else raw
    lowered = normalized.lower()
    variants = {lowered}
    if lowered.endswith(":latest"):
        variants.add(lowered[:-7])
    return variants


def _canonical_runtime_name(name: str) -> str:
    normalized = _registry_path_to_runtime_name(str(name or "").strip())
    if not normalized:
        return ""
    return CANONICAL_OLLAMA_NAMES.get(normalized.lower(), normalized)


def _legacy_entry_identifiers(entry: dict[str, Any]) -> set[str]:
    identifiers: set[str] = set()

    def add(value: object) -> None:
        if not isinstance(value, str):
            return
        raw = value.strip()
        if not raw:
            return
        identifiers.update(_runtime_name_variants(raw))

    add(entry.get("id"))
    add(entry.get("ollama_name"))
    add(entry.get("model_name"))

    model_name = str(entry.get("model_name") or "").strip()
    tag = str(entry.get("tag") or "").strip()
    if model_name and tag:
        add(f"{model_name}:{tag}")

    for alias in entry.get("aliases", []) or []:
        add(alias)

    return identifiers


def _legacy_alias_payload(entry: dict[str, Any]) -> list[str]:
    aliases: list[str] = []

    def add(value: object) -> None:
        if not isinstance(value, str):
            return
        raw = value.strip()
        if raw and raw not in aliases:
            aliases.append(raw)

    add(entry.get("id"))
    add(entry.get("ollama_name"))
    add(entry.get("model_name"))
    model_name = str(entry.get("model_name") or "").strip()
    tag = str(entry.get("tag") or "").strip()
    if model_name and tag:
        add(f"{model_name}:{tag}")
    for alias in entry.get("aliases", []) or []:
        add(alias)
    return aliases


def _build_entry_index(entries: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        for key in _legacy_entry_identifiers(entry):
            index.setdefault(key, []).append(entry)
    return index


def _pick_index_entry(index: dict[str, list[dict[str, Any]]], *candidates: str) -> dict[str, Any] | None:
    for candidate in candidates:
        for key in _runtime_name_variants(candidate):
            matches = index.get(key, [])
            if matches:
                return matches[0]
    return None


def _rebase_path(raw_path: str, gguf_root: Path, hf_root: Path) -> str:
    normalized = raw_path.replace("/", "\\")
    lowered = normalized.lower()
    if lowered.startswith(r"k:\models"):
        suffix = normalized[len(r"K:\models") :].lstrip("\\")
        return str(gguf_root / Path(suffix))
    if lowered.startswith(r"l:\models"):
        suffix = normalized[len(r"L:\models") :].lstrip("\\")
        return str(hf_root / Path(suffix))
    return raw_path


def _rebase_entry_paths(entry: dict[str, Any], gguf_root: Path, hf_root: Path) -> dict[str, Any]:
    updated = copy.deepcopy(entry)
    for field in ("path", "backup_path"):
        raw_path = str(updated.get(field) or "").strip()
        if raw_path:
            updated[field] = _rebase_path(raw_path, gguf_root=gguf_root, hf_root=hf_root)
    return updated


def _discover_runtime_manifests(ollama_root: Path) -> dict[str, dict[str, Any]]:
    manifests_root = ollama_root / "manifests"
    if not manifests_root.exists():
        raise FileNotFoundError(f"Missing Ollama manifests root: {manifests_root}")

    discovered: dict[str, dict[str, Any]] = {}
    for manifest_path in sorted(candidate for candidate in manifests_root.rglob("*") if candidate.is_file()):
        rel_path = manifest_path.relative_to(manifests_root)
        runtime_name = _registry_path_to_runtime_name(rel_path.as_posix())
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        model_layer = next(
            (
                layer
                for layer in payload.get("layers", []) or []
                if layer.get("mediaType") == "application/vnd.ollama.image.model"
            ),
            {},
        )
        discovered[runtime_name.lower()] = {
            "runtime_name": runtime_name,
            "manifest_path": str(manifest_path),
            "manifest_relative": rel_path.as_posix(),
            "model_digest": str(model_layer.get("digest") or ""),
            "size_gb": round((int(model_layer.get("size") or 0)) / (1024**3), 2),
        }
    return discovered


def _merge_aliases(entry: dict[str, Any], aliases: Iterable[str]) -> None:
    current = [str(value).strip() for value in entry.get("aliases", []) or [] if str(value).strip()]
    seen = {value.lower() for value in current}
    protected = {
        str(entry.get("id") or "").strip().lower(),
        str(entry.get("ollama_name") or "").strip().lower(),
    }
    for alias in aliases:
        raw = str(alias or "").strip()
        lowered = raw.lower()
        if not raw or lowered in seen or lowered in protected:
            continue
        current.append(raw)
        seen.add(lowered)
    if current:
        entry["aliases"] = current
    elif "aliases" in entry:
        entry.pop("aliases", None)


def _default_catalog_entry(runtime_name: str, manifest: dict[str, Any]) -> dict[str, Any]:
    override = copy.deepcopy(DISCOVERED_OLLAMA_METADATA_OVERRIDES.get(runtime_name.lower(), {}))
    slug = runtime_name.replace("/", "-").replace(":", "-").replace(".", "-")
    entry = {
        "id": slug,
        "name": runtime_name,
        "use_case": "general",
        "format": "ollama_registry",
        "size_gb": manifest.get("size_gb", 0.0),
        "parameters": "?",
        "quantization": "?",
        "ollama_name": runtime_name,
        "description": f"Modele Ollama decouvert automatiquement: {runtime_name}",
        "context_length": 0,
    }
    entry.update(override)
    entry["ollama_name"] = str(entry.get("ollama_name") or runtime_name)
    return entry


def _build_hf_entries(hf_root: Path) -> tuple[list[OrderedDict[str, Any]], list[str], float]:
    entries: list[OrderedDict[str, Any]] = []
    missing: list[str] = []
    total_hf_bytes = 0

    for spec in HF_ARCHIVE_SPECS:
        target = hf_root / spec["relative_archive"]
        if not target.exists():
            missing.append(str(target))
            continue

        size_bytes, num_files = _folder_stats(target)
        total_hf_bytes += size_bytes
        entry = OrderedDict()
        entry["id"] = spec["id"]
        entry["name"] = spec["name"]
        entry["path"] = str(target)
        entry["format"] = spec["format"]
        entry["size_gb"] = round(size_bytes / (1024**3), 2)
        entry["use_case"] = spec["use_case"]
        entry["parameters"] = spec["parameters"]
        entry["quantization"] = spec["quantization"]
        entry["num_files"] = num_files
        entry["context_length"] = spec["context_length"]
        entry["description"] = spec["description"]
        entries.append(entry)

    return entries, missing, round(total_hf_bytes / (1024**3), 2)


def _canonicalize_model_categories(
    categories: dict[str, list[str]],
    id_alias_map: dict[str, str],
) -> dict[str, list[str]]:
    updated: dict[str, list[str]] = OrderedDict()
    for category, model_ids in categories.items():
        seen: set[str] = set()
        rewritten: list[str] = []
        for model_id in model_ids or []:
            raw = str(model_id or "").strip()
            if not raw:
                continue
            canonical = id_alias_map.get(raw, raw)
            if canonical not in seen:
                rewritten.append(canonical)
                seen.add(canonical)
        updated[category] = rewritten
    return updated


def build_catalog(
    legacy_json: Path,
    output_json: Path,
    catalog_root: Path,
    ollama_root: Path,
    gguf_root: Path,
    hf_root: Path,
) -> dict[str, Any]:
    payload = json.loads(legacy_json.read_text(encoding="utf-8-sig"))

    legacy_ollama_models = list(payload.get("ollama_models", []))
    legacy_cloud_models = list(payload.get("cloud_models", []))
    legacy_ollama_index = _build_entry_index(legacy_ollama_models)
    legacy_cloud_index = _build_entry_index(legacy_cloud_models)
    runtime_manifests = _discover_runtime_manifests(ollama_root)

    canonical_groups: dict[str, dict[str, Any]] = OrderedDict()
    for manifest in runtime_manifests.values():
        runtime_name = manifest["runtime_name"]
        canonical_name = _canonical_runtime_name(runtime_name)
        group_key = canonical_name.lower()
        group = canonical_groups.setdefault(
            group_key,
            {
                "canonical_name": canonical_name,
                "manifests": [],
                "runtime_names": set(),
                "alias_entries": {},
            },
        )
        group["manifests"].append(manifest)
        group["runtime_names"].add(runtime_name)

        alias_entry = _pick_index_entry(legacy_ollama_index, runtime_name)
        if alias_entry is not None:
            group["alias_entries"][str(alias_entry.get("id") or runtime_name)] = alias_entry

    canonical_name_map: dict[str, str] = {}
    id_alias_map: dict[str, str] = {}
    alias_report: dict[str, list[str]] = OrderedDict()
    ollama_entries: list[dict[str, Any]] = []
    cloud_entries: list[dict[str, Any]] = []

    def legacy_order(group: dict[str, Any]) -> int:
        candidates = [
            _pick_index_entry(legacy_ollama_index, group["canonical_name"]),
            *_pick_index_candidates(group["alias_entries"].values()),
        ]
        positions = []
        for entry in candidates:
            try:
                positions.append(legacy_ollama_models.index(entry))
            except ValueError:
                continue
        if positions:
            return min(positions)
        cloud_candidate = _pick_index_entry(legacy_cloud_index, group["canonical_name"])
        if cloud_candidate is not None:
            try:
                return len(legacy_ollama_models) + legacy_cloud_models.index(cloud_candidate)
            except ValueError:
                return len(legacy_ollama_models) + len(legacy_cloud_models)
        return len(legacy_ollama_models) + len(legacy_cloud_models) + 1000

    sorted_groups = sorted(canonical_groups.values(), key=legacy_order)
    for group in sorted_groups:
        canonical_name = group["canonical_name"]
        alias_entries = list(group["alias_entries"].values())
        is_cloud = canonical_name.lower().endswith("-cloud")

        if is_cloud:
            cloud_entry = _pick_index_entry(legacy_cloud_index, canonical_name)
            if cloud_entry is None:
                cloud_entry = {
                    "id": canonical_name.replace("/", "-").replace(":", "-"),
                    "name": canonical_name,
                    "ollama_name": canonical_name,
                    "type": "cloud_api",
                    "parameters": "?",
                    "description": f"Modele cloud detecte via manifest: {canonical_name}",
                }
            exact_name = str(cloud_entry.get("ollama_name") or canonical_name)
            canonical_name_map[canonical_name.lower()] = exact_name
            cloud_entries.append(cloud_entry)
            continue

        legacy_entry = _pick_index_entry(legacy_ollama_index, canonical_name)
        if legacy_entry is None and alias_entries:
            legacy_entry = alias_entries[0]

        manifest_sizes = [float(item.get("size_gb") or 0.0) for item in group["manifests"]]
        manifest_paths = [str(item.get("manifest_path") or "") for item in group["manifests"] if item.get("manifest_path")]
        entry = _rebase_entry_paths(legacy_entry, gguf_root=gguf_root, hf_root=hf_root) if legacy_entry else _default_catalog_entry(canonical_name, group["manifests"][0])

        exact_ollama_name = str(entry.get("ollama_name") or canonical_name)
        canonical_name_map[canonical_name.lower()] = exact_ollama_name
        entry["ollama_name"] = exact_ollama_name
        if manifest_sizes:
            entry["size_gb"] = round(max(manifest_sizes), 2)
        if manifest_paths:
            entry["manifest_path"] = manifest_paths[0]

        merged_aliases: list[str] = []
        for runtime_name in sorted(group["runtime_names"]):
            if runtime_name.lower() != exact_ollama_name.lower():
                merged_aliases.append(runtime_name)
        for alias_entry in alias_entries:
            merged_aliases.extend(_legacy_alias_payload(alias_entry))
            alias_id = str(alias_entry.get("id") or "").strip()
            canonical_id = str(entry.get("id") or "").strip()
            if alias_id and canonical_id and alias_id != canonical_id:
                id_alias_map[alias_id] = canonical_id

        _merge_aliases(entry, merged_aliases)
        alias_report[exact_ollama_name] = [alias for alias in entry.get("aliases", []) or [] if alias]
        ollama_entries.append(entry)

    for alias_id, canonical_id in list(id_alias_map.items()):
        if alias_id == canonical_id:
            id_alias_map.pop(alias_id, None)

    hf_entries, missing_hf_targets, total_hf_gb = _build_hf_entries(hf_root)
    if missing_hf_targets:
        missing_text = "\n".join(f"- {path}" for path in missing_hf_targets)
        raise FileNotFoundError(
            "Missing required HuggingFace archives on destination root:\n" + missing_text
        )

    payload["version"] = str(payload.get("version") or "3.0")
    payload["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    payload["generation_method"] = "c_runtime_kl_topology_v2"
    payload["models_directory"] = str(catalog_root)
    payload["catalog_notes"] = {
        "runtime_ollama_root": str(ollama_root),
        "gguf_library_root": str(gguf_root),
        "hf_archive_root": str(hf_root),
        "legacy_d_models": str(legacy_json),
        "ollama_manifest_count": len(runtime_manifests),
        "ollama_alias_collapse": alias_report,
    }
    payload["ollama_models"] = ollama_entries
    payload["cloud_models"] = cloud_entries
    payload["huggingface_models"] = hf_entries
    payload["model_categories"] = _canonicalize_model_categories(
        payload.get("model_categories", {}),
        id_alias_map=id_alias_map,
    )

    updated_recommendations: dict[str, Any] = OrderedDict()
    for task, value in (payload.get("recommended_by_task", {}) or {}).items():
        if isinstance(value, str):
            canonical_name = _canonical_runtime_name(value)
            updated_recommendations[task] = canonical_name_map.get(canonical_name.lower(), canonical_name)
        else:
            updated_recommendations[task] = value
    payload["recommended_by_task"] = updated_recommendations

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "output_json": str(output_json),
        "catalog_root": str(catalog_root),
        "ollama_root": str(ollama_root),
        "gguf_root": str(gguf_root),
        "hf_root": str(hf_root),
        "ollama_models": len(ollama_entries),
        "cloud_models": len(cloud_entries),
        "huggingface_models": len(hf_entries),
        "huggingface_total_gb": total_hf_gb,
        "alias_collapse_count": sum(1 for aliases in alias_report.values() if aliases),
    }


def _pick_index_candidates(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry is not None]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the centralized C:\\AI catalog for the C/K/L model topology.")
    parser.add_argument("--legacy-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--catalog-root", required=True)
    parser.add_argument("--ollama-root", required=True)
    parser.add_argument("--gguf-root", default=r"K:\models")
    parser.add_argument("--hf-root", default=r"L:\models")
    args = parser.parse_args()

    report = build_catalog(
        legacy_json=Path(args.legacy_json),
        output_json=Path(args.output_json),
        catalog_root=Path(args.catalog_root),
        ollama_root=Path(args.ollama_root),
        gguf_root=Path(args.gguf_root),
        hf_root=Path(args.hf_root),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
