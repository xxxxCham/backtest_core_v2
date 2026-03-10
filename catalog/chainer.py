"""
Module-ID: catalog.chainer

Purpose: Moteur de génération de variants (grid/sampling, seeding, batching, dédup).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from utils.parameters import (
    ConstraintValidator,
    ParameterConstraint,
    ParameterSpec,
    compute_search_space_stats,
    generate_param_grid,
)

from catalog.builder_export import to_json_proposal, to_text_v1
from catalog.fingerprint import fingerprint_sha256
from catalog.models import (
    Archetype,
    CatalogConfig,
    CatalogResult,
    ParamPack,
    Variant,
)
from catalog.ranges_loader import resolve_param_defs
from catalog.sanity import validate_variant


def _seed_for_archetype(root_seed: int, archetype_id: str) -> int:
    """Calcule un seed déterministe par archetype."""
    raw = f"{root_seed}:{archetype_id}".encode("utf-8")
    return int(hashlib.md5(raw).hexdigest()[:8], 16)


def _build_constraints(param_pack: ParamPack) -> ConstraintValidator:
    """Convertit les contraintes JSON d'un ParamPack en ConstraintValidator."""
    validator = ConstraintValidator()
    for c in param_pack.constraints:
        ctype = c.get("type", "")
        a = c.get("a", "")
        b = c.get("b")
        value = c.get("value")
        ratio = c.get("ratio")
        validator.add_constraint(ParameterConstraint(
            param_a=a,
            constraint_type=ctype,
            param_b=b,
            value=value,
            ratio=ratio,
        ))
    return validator


def normalize_dsl(text: str) -> str:
    """Normalise les tokens DSL ambigus pour compatibilité codegen.

    Transformations:
    - ``X crosses_above Y``  → ``cross_up(X, Y)``
    - ``X crosses_below Y``  → ``cross_down(X, Y)``
    - ``X crosses Y``        → ``cross_any(X, Y)``
    - ``X changes sign``     → ``sign_change(X)``
    - ``X changes``          → ``direction_change(X)``

    Les helpers cross_up/cross_down doivent être implémentés vectoriellement:
    ``prev = np.roll(x,1); prev[0]=np.nan; cross_up = (x>y) & (prev<=prev_y)``
    """
    # Legacy aliases -> contrat unique
    text = re.sub(r"\bcross_above\s*\(", "cross_up(", text)
    text = re.sub(r"\bcross_below\s*\(", "cross_down(", text)

    # crosses_above / crosses_below en premier (plus spécifique)
    text = re.sub(
        r"(\S+)\s+crosses_above\s+(\S+)",
        r"cross_up(\1, \2)",
        text,
    )
    text = re.sub(
        r"(\S+)\s+crosses_below\s+(\S+)",
        r"cross_down(\1, \2)",
        text,
    )
    # "X crosses Y" → bidirectionnel
    text = re.sub(
        r"(\S+)\s+crosses\s+(\S+)",
        r"cross_any(\1, \2)",
        text,
    )
    # "X changes sign"
    text = re.sub(
        r"(\S+)\s+changes\s+sign\b",
        r"sign_change(\1)",
        text,
    )
    # "X changes" (generic)
    text = re.sub(
        r"(\S+)\s+changes\b",
        r"direction_change(\1)",
        text,
    )
    return text


def _instantiate_dsl(template: str, params: Dict[str, Any]) -> str:
    """Remplace les placeholders ${...} puis normalise les tokens DSL."""
    def _replacer(match: re.Match) -> str:
        key = match.group(1)
        if key in params:
            return str(params[key])
        return match.group(0)

    result = re.sub(r"\$\{(\w+)\}", _replacer, template)
    return normalize_dsl(result)


def _build_proposal(
    archetype: Archetype,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Construit un proposal JSON au format Builder depuis un archetype + params concrets."""
    # Fusionner les default_params de l'archetype avec les params générés
    merged_params = dict(archetype.default_params)
    merged_params.update(params)
    # Forcer leverage=1 et warmup
    merged_params.setdefault("leverage", 1)
    merged_params.setdefault("warmup", 50)

    # Instancier les expressions DSL
    entry_long = _instantiate_dsl(archetype.entry_long_logic, merged_params)
    entry_short = _instantiate_dsl(archetype.entry_short_logic, merged_params)
    exit_logic = _instantiate_dsl(archetype.exit_logic, merged_params)
    risk_mgmt = _instantiate_dsl(archetype.risk_management, merged_params)

    # Construire indicator_params avec valeurs concrètes
    indicator_params: Dict[str, Dict[str, Any]] = {}
    for ind_name, ind_template in archetype.indicator_params.items():
        resolved: Dict[str, Any] = {}
        for k, v in ind_template.items():
            if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                key = v[2:-1]
                resolved[k] = merged_params.get(key, v)
            else:
                resolved[k] = v
        indicator_params[ind_name] = resolved

    # Construire parameter_specs (garder ceux de l'archetype)
    param_specs = dict(archetype.parameter_specs)

    # Nom de stratégie basé sur l'archetype
    strategy_name = archetype.archetype_id.replace("-", "_")

    return {
        "strategy_name": strategy_name,
        "hypothesis": f"Parametric variant of {archetype.family} archetype {archetype.archetype_id}",
        "change_type": "logic",
        "used_indicators": list(archetype.indicators),
        "indicator_params": indicator_params,
        "entry_long_logic": entry_long,
        "entry_short_logic": entry_short,
        "exit_logic": exit_logic,
        "risk_management": risk_mgmt,
        "default_params": merged_params,
        "parameter_specs": param_specs,
    }


def _sample_random(
    specs: Dict[str, ParameterSpec],
    n: int,
    rng: np.random.Generator,
    constraints: ConstraintValidator,
    max_retries: int = 1000,
) -> List[Dict[str, Any]]:
    """Sampling aléatoire avec contraintes."""
    results: List[Dict[str, Any]] = []
    attempts = 0

    while len(results) < n and attempts < n * max_retries:
        attempts += 1
        sample: Dict[str, Any] = {}

        for name, spec in specs.items():
            if spec.param_type == "int":
                val = rng.integers(int(spec.min_val), int(spec.max_val) + 1)
                if spec.step and spec.step > 1:
                    # Arrondir au step
                    val = int(spec.min_val + round((val - spec.min_val) / spec.step) * spec.step)
                    val = max(int(spec.min_val), min(int(spec.max_val), val))
                sample[name] = int(val)
            else:
                val = rng.uniform(spec.min_val, spec.max_val)
                if spec.step and spec.step > 0:
                    val = spec.min_val + round((val - spec.min_val) / spec.step) * spec.step
                    val = max(spec.min_val, min(spec.max_val, val))
                    val = round(val, 10)
                sample[name] = float(val)

        if constraints.validate(sample):
            results.append(sample)

    return results


def _load_archetypes(archetypes_dir: Path) -> List[Archetype]:
    """Charge tous les archetypes depuis un répertoire."""
    archetypes = []
    if not archetypes_dir.exists():
        return archetypes
    for path in sorted(archetypes_dir.glob("*.json")):
        archetypes.append(Archetype.load(path))
    return archetypes


def _load_param_packs(
    param_packs_dir: Path,
    archetype_id: Optional[str] = None,
) -> List[ParamPack]:
    """Charge les param_packs, filtré optionnellement par archetype_id."""
    packs = []
    if not param_packs_dir.exists():
        return packs
    for path in sorted(param_packs_dir.glob("*.json")):
        pack = ParamPack.load(path)
        if archetype_id is None or pack.archetype_id == archetype_id:
            packs.append(pack)
    return packs


def generate_catalog(config: CatalogConfig) -> CatalogResult:
    """
    Génère le catalogue complet de variants.

    Pipeline : load archetypes → load param_packs → generate → sanity → dedup → batch.
    """
    result = CatalogResult(run_id=config.run_id)
    seen_fingerprints: set = set()
    all_variants: List[Variant] = []

    archetypes_dir = Path(config.archetypes_dir)
    param_packs_dir = Path(config.param_packs_dir)

    archetypes = _load_archetypes(archetypes_dir)
    if not archetypes:
        return result

    # Budget par archetype (réparti également)
    budget_per_archetype = max(1, config.n_variants_target // len(archetypes))

    for archetype in archetypes:
        arch_seed = _seed_for_archetype(config.seed, archetype.archetype_id)
        packs = _load_param_packs(param_packs_dir, archetype.archetype_id)

        if not packs:
            continue

        budget_per_pack = max(1, budget_per_archetype // len(packs))

        for pack in packs:
            pack_seed = _seed_for_archetype(arch_seed, pack.param_pack_id)
            specs = resolve_param_defs(pack)
            constraints = _build_constraints(pack)

            # Estimer l'espace de recherche
            stats = compute_search_space_stats(specs)

            if not stats.is_continuous and 0 < stats.total_combinations <= budget_per_pack:
                # Grid complet
                grid = generate_param_grid(
                    specs,
                    granularity=0.0,
                    max_values_per_param=50,
                    max_total_combinations=budget_per_pack * 10,
                )
                param_combos = constraints.filter_grid(grid)
            else:
                # Sampling aléatoire
                rng = np.random.default_rng(pack_seed)
                param_combos = _sample_random(
                    specs, budget_per_pack, rng, constraints
                )

            # Limiter au budget
            param_combos = param_combos[:budget_per_pack]

            for idx, params in enumerate(param_combos):
                proposal = _build_proposal(archetype, params)
                fp = fingerprint_sha256(proposal)

                if fp in seen_fingerprints:
                    continue
                seen_fingerprints.add(fp)

                variant_id = f"{archetype.archetype_id}__{pack.param_pack_id}__v{idx:04d}"

                variant = Variant(
                    variant_id=variant_id,
                    archetype_id=archetype.archetype_id,
                    param_pack_id=pack.param_pack_id,
                    params=params,
                    proposal=proposal,
                    builder_text=to_text_v1(proposal, archetype),
                    fingerprint=fp,
                    provenance={
                        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                        "seed": pack_seed,
                        "batch_id": idx // config.batch_size,
                    },
                )

                result.total_generated += 1

                # Sanity check
                is_valid, reasons = validate_variant(
                    variant,
                    profile=config.profiles.get("dataset", "ohlcv_only"),
                )
                if not is_valid:
                    result.rejections.append({
                        "variant_id": variant_id,
                        "reasons": reasons,
                        "stage": "sanity",
                    })
                    continue

                result.total_after_sanity += 1
                all_variants.append(variant)

    result.variants = all_variants
    result.total_after_gating = len(all_variants)  # Updated by gating if enabled
    result.n_batches = (len(all_variants) + config.batch_size - 1) // config.batch_size

    return result
