"""
Module-ID: catalog.models

Purpose: Modèles de données pour le catalogue de fiches de stratégies.

Key components: Archetype, ParamDef, ParamPack, Variant, GatingConfig, CatalogConfig, CatalogResult
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Archetype:
    """Template de fiche de stratégie avec placeholders paramétrables."""

    archetype_id: str
    version: str = "1.0"
    family: str = ""  # mean_reversion, trend, breakout, momentum, volatility
    side: str = "both"  # long_only, short_only, both
    timeframe: str = "1h"
    indicators: List[str] = field(default_factory=list)
    indicator_params: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    entry_long_logic: str = ""
    entry_short_logic: str = ""
    exit_logic: str = ""
    risk_management: str = ""
    default_params: Dict[str, Any] = field(default_factory=dict)
    parameter_specs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    requirements: Dict[str, Any] = field(default_factory=lambda: {
        "ohlcv_required": True, "dataset_features": []
    })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "archetype_id": self.archetype_id,
            "version": self.version,
            "family": self.family,
            "side": self.side,
            "timeframe": self.timeframe,
            "indicators": self.indicators,
            "indicator_params": self.indicator_params,
            "entry_long_logic": self.entry_long_logic,
            "entry_short_logic": self.entry_short_logic,
            "exit_logic": self.exit_logic,
            "risk_management": self.risk_management,
            "default_params": self.default_params,
            "parameter_specs": self.parameter_specs,
            "requirements": self.requirements,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Archetype:
        return cls(
            archetype_id=data["archetype_id"],
            version=data.get("version", "1.0"),
            family=data.get("family", ""),
            side=data.get("side", "both"),
            timeframe=data.get("timeframe", "1h"),
            indicators=data.get("indicators", []),
            indicator_params=data.get("indicator_params", {}),
            entry_long_logic=data.get("entry_long_logic", ""),
            entry_short_logic=data.get("entry_short_logic", ""),
            exit_logic=data.get("exit_logic", ""),
            risk_management=data.get("risk_management", ""),
            default_params=data.get("default_params", {}),
            parameter_specs=data.get("parameter_specs", {}),
            requirements=data.get("requirements", {
                "ohlcv_required": True, "dataset_features": []
            }),
        )

    @classmethod
    def load(cls, path: Path) -> Archetype:
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def save(self, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


@dataclass
class ParamDef:
    """Définition d'un paramètre dans un param_pack."""

    dist: str = "int_uniform"  # int_uniform, uniform, categorical, log_uniform
    source: Optional[str] = None  # "toml" pour charger depuis indicator_ranges.toml
    indicator: Optional[str] = None  # nom indicateur (si source=toml)
    param: Optional[str] = None  # nom paramètre dans le TOML (si source=toml)
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    options: Optional[List[Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"dist": self.dist}
        if self.source:
            d["source"] = self.source
        if self.indicator:
            d["indicator"] = self.indicator
        if self.param:
            d["param"] = self.param
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.step is not None:
            d["step"] = self.step
        if self.options is not None:
            d["options"] = self.options
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ParamDef:
        return cls(
            dist=data.get("dist", "int_uniform"),
            source=data.get("source"),
            indicator=data.get("indicator"),
            param=data.get("param"),
            min=data.get("min"),
            max=data.get("max"),
            step=data.get("step"),
            options=data.get("options"),
        )


@dataclass
class ParamPack:
    """Définition de distributions et contraintes pour instancier un archetype."""

    param_pack_id: str
    archetype_id: str
    seed: int = 42
    param_defs: Dict[str, ParamDef] = field(default_factory=dict)
    constraints: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "param_pack_id": self.param_pack_id,
            "archetype_id": self.archetype_id,
            "seed": self.seed,
            "param_defs": {k: v.to_dict() for k, v in self.param_defs.items()},
            "constraints": self.constraints,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ParamPack:
        param_defs = {}
        for k, v in data.get("param_defs", {}).items():
            param_defs[k] = ParamDef.from_dict(v)
        return cls(
            param_pack_id=data["param_pack_id"],
            archetype_id=data["archetype_id"],
            seed=data.get("seed", 42),
            param_defs=param_defs,
            constraints=data.get("constraints", []),
        )

    @classmethod
    def load(cls, path: Path) -> ParamPack:
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def save(self, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


@dataclass
class Variant:
    """Fiche de stratégie instanciée (variant concret d'un archetype)."""

    variant_id: str
    archetype_id: str
    param_pack_id: str
    params: Dict[str, Any] = field(default_factory=dict)
    proposal: Dict[str, Any] = field(default_factory=dict)
    builder_text: str = ""
    fingerprint: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)
    gating_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "variant_id": self.variant_id,
            "archetype_id": self.archetype_id,
            "param_pack_id": self.param_pack_id,
            "params": self.params,
            "proposal": self.proposal,
            "builder_text": self.builder_text,
            "fingerprint": self.fingerprint,
            "provenance": self.provenance,
        }
        if self.gating_result is not None:
            d["gating_result"] = self.gating_result
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Variant:
        return cls(
            variant_id=data["variant_id"],
            archetype_id=data["archetype_id"],
            param_pack_id=data["param_pack_id"],
            params=data.get("params", {}),
            proposal=data.get("proposal", {}),
            builder_text=data.get("builder_text", ""),
            fingerprint=data.get("fingerprint", ""),
            provenance=data.get("provenance", {}),
            gating_result=data.get("gating_result"),
        )


@dataclass
class GatingConfig:
    """Configuration du mini-backtest gating."""

    enabled: bool = False
    max_seconds: float = 2.0
    thresholds: Dict[str, float] = field(default_factory=lambda: {
        "min_trades": 20,
        "max_drawdown_pct": 40.0,
        "min_profit_factor": 1.05,
    })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_seconds": self.max_seconds,
            "thresholds": self.thresholds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GatingConfig:
        return cls(
            enabled=data.get("enabled", False),
            max_seconds=data.get("max_seconds", 2.0),
            thresholds=data.get("thresholds", {
                "min_trades": 20,
                "max_drawdown_pct": 40.0,
                "min_profit_factor": 1.05,
            }),
        )


@dataclass
class CatalogConfig:
    """Configuration complète d'un run de génération de catalogue."""

    catalog_version: str = "1.0"
    run_id: str = ""
    seed: int = 42
    batch_size: int = 50
    n_variants_target: int = 200
    archetypes_dir: str = "catalog/archetypes"
    param_packs_dir: str = "catalog/param_packs"
    output_dir: str = "catalog/generated"
    profiles: Dict[str, Any] = field(default_factory=lambda: {
        "dataset": "ohlcv_only",
        "risk_stoploss_mandatory": True,
    })
    gating: GatingConfig = field(default_factory=GatingConfig)
    builder_integration: Dict[str, Any] = field(default_factory=lambda: {
        "enabled": True,
        "input_format": "json_proposal",
    })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "catalog_version": self.catalog_version,
            "run_id": self.run_id,
            "seed": self.seed,
            "batch_size": self.batch_size,
            "n_variants_target": self.n_variants_target,
            "archetypes_dir": self.archetypes_dir,
            "param_packs_dir": self.param_packs_dir,
            "output_dir": self.output_dir,
            "profiles": self.profiles,
            "gating": self.gating.to_dict(),
            "builder_integration": self.builder_integration,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CatalogConfig:
        gating_data = data.get("gating", {})
        gating = GatingConfig.from_dict(gating_data) if gating_data else GatingConfig()
        return cls(
            catalog_version=data.get("catalog_version", "1.0"),
            run_id=data.get("run_id", ""),
            seed=data.get("seed", 42),
            batch_size=data.get("batch_size", 50),
            n_variants_target=data.get("n_variants_target", 200),
            archetypes_dir=data.get("archetypes_dir", "catalog/archetypes"),
            param_packs_dir=data.get("param_packs_dir", "catalog/param_packs"),
            output_dir=data.get("output_dir", "catalog/generated"),
            profiles=data.get("profiles", {
                "dataset": "ohlcv_only",
                "risk_stoploss_mandatory": True,
            }),
            gating=gating,
            builder_integration=data.get("builder_integration", {
                "enabled": True,
                "input_format": "json_proposal",
            }),
        )

    @classmethod
    def load(cls, path: Path) -> CatalogConfig:
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


@dataclass
class CatalogResult:
    """Résultat d'une exécution de génération de catalogue."""

    run_id: str = ""
    total_generated: int = 0
    total_after_sanity: int = 0
    total_after_gating: int = 0
    n_batches: int = 0
    variants: List[Variant] = field(default_factory=list)
    rejections: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_generated": self.total_generated,
            "total_after_sanity": self.total_after_sanity,
            "total_after_gating": self.total_after_gating,
            "n_batches": self.n_batches,
            "variants": [v.to_dict() for v in self.variants],
            "rejections": self.rejections,
        }
