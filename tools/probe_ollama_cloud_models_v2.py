"""Re-probe des modèles 404 avec différentes variantes de suffixes.

Vérifie que les modèles 'missing' du premier probe ne répondent pas non plus
avec un suffixe -cloud / :cloud / :latest / explicit size tag.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

OLLAMA_DIRECT_HOST = "https://ollama.com"

MISSING_TO_RETRY = [
    "deepseek-v3.1",
    "kimi-k2",
    "mistral-large-3",
    "nemotron-3-super:120b",
    "qwen3.5:122b",
    "nemotron-3-nano:4b",
    "gemma4:26b",
    "qwen3.5:35b",
    "qwen3.5:27b",
    "qwen3.5:9b",
    "qwen3.5:4b",
    "qwen3.5:2b",
    "qwen3.5:0.8b",
]


def _build_variants(name: str) -> list[str]:
    variants = [name]
    if ":" in name:
        variants.append(f"{name}-cloud")
    else:
        variants.append(f"{name}:cloud")
        variants.append(f"{name}:latest")
    # Aliases connus
    if name == "kimi-k2":
        variants.extend(["kimi-k2:1t", "kimi-k2:1t-cloud"])
    if name == "deepseek-v3.1":
        variants.extend(["deepseek-v3.1:671b", "deepseek-v3.1:671b-cloud"])
    if name == "mistral-large-3":
        variants.extend(["mistral-large-3:675b", "mistral-large-3:675b-cloud"])
    if name == "qwen3.5:122b":
        variants.extend(["qwen3.5:122b-cloud"])
    return variants


def probe(client: httpx.Client, model: str, api_key: str) -> tuple[int, str]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        "options": {"num_predict": 1},
    }
    try:
        resp = client.post(
            f"{OLLAMA_DIRECT_HOST}/api/chat",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        return resp.status_code, (resp.text or "")[:120]
    except httpx.HTTPError as exc:
        return -1, str(exc)[:120]


def main() -> int:
    api_key = os.environ.get("OLLAMA_API_KEY", "").strip()
    if not api_key:
        print("[ERR] OLLAMA_API_KEY non défini", file=sys.stderr)
        return 2

    results: dict[str, dict[str, object]] = {}
    with httpx.Client() as client:
        for canonical in MISSING_TO_RETRY:
            print(f"\n=== {canonical} ===")
            results[canonical] = {}
            for variant in _build_variants(canonical):
                status, body = probe(client, variant, api_key)
                verdict = (
                    "free" if status == 200
                    else "paid" if status == 403 and "subscription" in body.lower()
                    else "missing" if status == 404
                    else f"http_{status}"
                )
                print(f"  [{status}] {variant:40s} -> {verdict}  | {body[:80]}")
                results[canonical][variant] = {"status": status, "verdict": verdict, "body": body[:120]}

    out = REPO_ROOT / "tools" / "probe_ollama_cloud_models_v2_report.json"
    with out.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print(f"\n[OK] rapport écrit dans {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
