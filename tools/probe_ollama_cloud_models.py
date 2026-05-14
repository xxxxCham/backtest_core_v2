"""Probe runtime des modèles Ollama Cloud pour distinguer Free / Paid / Indisponible.

Usage : python tools/probe_ollama_cloud_models.py [--out report.json]

Pré-requis : OLLAMA_API_KEY défini dans l'env (clé Ollama Cloud).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.model_config import KNOWN_MODELS  # noqa: E402
from agents.ollama_runtime import (  # noqa: E402
    get_ollama_cloud_runtime_model_candidates,
)

OLLAMA_DIRECT_HOST = "https://ollama.com"

# Modèles supplémentaires vus sur https://ollama.com/search?c=cloud
# (la page ne montre pas de badge subscription, on probe pour confirmer)
EXTRA_CANDIDATES_FROM_SEARCH = [
    "gemini-3-flash-preview",
    "ministral-3:14b",
    "ministral-3:8b",
    "ministral-3:3b",
    "devstral-small-2:24b",
    "rnj-1:8b",
    "nemotron-3-nano:30b",
    "nemotron-3-nano:4b",
    "gemma4:31b",
    "gemma4:26b",
    "qwen3.5:35b",
    "qwen3.5:27b",
    "qwen3.5:9b",
    "qwen3.5:4b",
    "qwen3.5:2b",
    "qwen3.5:0.8b",
    "qwen3-coder-next",
    "minimax-m2.1",
    "gpt-oss:20b",
]


def _build_probe_targets() -> list[tuple[str, str]]:
    """Renvoie [(canonical_name, request_model)] pour le probe.

    request_model = nom à envoyer dans le payload (avec suffixe -cloud / :cloud)
    """
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()

    cloud_only_canonical = sorted(
        {info.name for info in KNOWN_MODELS.values() if info.cloud_only}
    )
    for name in cloud_only_canonical + EXTRA_CANDIDATES_FROM_SEARCH:
        if name in seen:
            continue
        seen.add(name)
        candidates = get_ollama_cloud_runtime_model_candidates(name, direct_cloud=True)
        if not candidates:
            # fallback minimal: ":cloud" suffix
            request_model = f"{name}:cloud" if ":" not in name else f"{name}-cloud"
        else:
            request_model = candidates[0]
        targets.append((name, request_model))
    return targets


def _classify(status_code: int, body_text: str) -> str:
    body_lower = body_text.lower()
    if status_code == 200:
        return "free"
    if status_code in (401, 403):
        if "subscription" in body_lower or "upgrade" in body_lower:
            return "paid"
        return "auth"
    if status_code == 404:
        return "missing"
    if status_code == 429:
        return "rate_limited"
    return f"http_{status_code}"


def probe_one(client: httpx.Client, request_model: str, api_key: str) -> dict[str, str | int]:
    payload = {
        "model": request_model,
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        "options": {"num_predict": 1},
    }
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        resp = client.post(
            f"{OLLAMA_DIRECT_HOST}/api/chat",
            json=payload,
            headers=headers,
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        return {"status": -1, "verdict": "transport_error", "body": str(exc)[:200]}
    body = resp.text or ""
    return {
        "status": resp.status_code,
        "verdict": _classify(resp.status_code, body),
        "body": body[:200],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "tools" / "probe_ollama_cloud_models_report.json")
    args = parser.parse_args()

    api_key = os.environ.get("OLLAMA_API_KEY", "").strip()
    if not api_key:
        print("[ERR] OLLAMA_API_KEY non défini dans l'environnement.", file=sys.stderr)
        return 2

    targets = _build_probe_targets()
    print(f"[INFO] {len(targets)} modèles cloud à probe")

    results: list[dict[str, object]] = []
    with httpx.Client() as client:
        for canonical, request_model in targets:
            print(f"  -> {canonical:35s} (sent as {request_model})", end=" ", flush=True)
            outcome = probe_one(client, request_model, api_key)
            print(f"{outcome['status']} -> {outcome['verdict']}")
            results.append({"canonical": canonical, "request_model": request_model, **outcome})

    summary: dict[str, list[str]] = {}
    for entry in results:
        verdict = str(entry["verdict"])
        summary.setdefault(verdict, []).append(str(entry["canonical"]))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        json.dump(
            {
                "summary": {k: sorted(v) for k, v in summary.items()},
                "results": results,
            },
            fh,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\n[OK] rapport écrit dans {args.out}")
    print("\n=== RÉCAP ===")
    for verdict, names in sorted(summary.items()):
        print(f"{verdict:18s} ({len(names):2d}): {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
