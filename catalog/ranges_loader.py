"""
Module-ID: catalog.ranges_loader

Purpose: Bridge entre indicator_ranges.toml et ParameterSpec pour les param_packs.
"""

from __future__ import annotations

from typing import Any, Dict

from utils.indicator_ranges import load_indicator_ranges
from utils.parameters import ParameterSpec

from catalog.models import ParamDef, ParamPack


def _param_type_from_def(pdef: ParamDef, toml_spec: Dict[str, Any] | None = None) -> str:
    """Infère le type du paramètre depuis la définition ou le TOML."""
    if pdef.dist in ("int_uniform",):
        return "int"
    if pdef.options is not None:
        return "categorical"
    if toml_spec and "options" in toml_spec:
        return "categorical"
    if toml_spec and toml_spec.get("type") == "string":
        return "categorical"
    # Vérifier si min/max/step sont entiers
    if pdef.min is not None and pdef.max is not None:
        if isinstance(pdef.min, int) and isinstance(pdef.max, int):
            if pdef.step is None or isinstance(pdef.step, int):
                return "int"
    return "float"


def resolve_param_def(name: str, pdef: ParamDef) -> ParameterSpec:
    """
    Résout un ParamDef en ParameterSpec concret.

    Si source="toml", charge les bornes depuis indicator_ranges.toml.
    Sinon, utilise les valeurs min/max/step directes.
    """
    if pdef.source == "toml" and pdef.indicator and pdef.param:
        ranges = load_indicator_ranges()
        indicator_ranges = ranges.get(pdef.indicator, {})
        toml_spec = indicator_ranges.get(pdef.param, {})

        if not toml_spec:
            raise ValueError(
                f"Paramètre TOML introuvable : {pdef.indicator}.{pdef.param}"
            )

        min_val = float(toml_spec.get("min", 0))
        max_val = float(toml_spec.get("max", 100))
        step = toml_spec.get("step")
        default = toml_spec.get("default", min_val)
        ptype = _param_type_from_def(pdef, toml_spec)

        return ParameterSpec(
            name=name,
            min_val=min_val,
            max_val=max_val,
            default=float(default) if default is not None else min_val,
            step=float(step) if step is not None else None,
            param_type=ptype,
        )

    # Source directe (min/max/step explicites)
    if pdef.min is None or pdef.max is None:
        raise ValueError(
            f"ParamDef '{name}' sans source TOML doit avoir min et max."
        )

    ptype = _param_type_from_def(pdef)
    return ParameterSpec(
        name=name,
        min_val=float(pdef.min),
        max_val=float(pdef.max),
        default=float((pdef.min + pdef.max) / 2),
        step=float(pdef.step) if pdef.step is not None else None,
        param_type=ptype,
    )


def resolve_param_defs(param_pack: ParamPack) -> Dict[str, ParameterSpec]:
    """Résout tous les ParamDef d'un ParamPack en ParameterSpec."""
    specs: Dict[str, ParameterSpec] = {}
    for name, pdef in param_pack.param_defs.items():
        specs[name] = resolve_param_def(name, pdef)
    return specs
