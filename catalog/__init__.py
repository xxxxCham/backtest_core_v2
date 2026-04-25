"""Module-ID: catalog

Purpose: Générateur paramétrique de catalogue de fiches de stratégies.

Role in pipeline: generation / orchestration

Key components: models, fingerprint, chainer, sanity, gating, builder_export, runner

Inputs: CatalogConfig JSON, archetypes JSON, param_packs JSON

Outputs: Variants filtrés (JSON + texte Builder), index, run_meta

Dependencies: utils.parameters, utils.indicator_ranges, indicators.registry, backtest.engine

Conventions: Archetypes + param_packs → variants → sanity → gating → export.
"""

from catalog.fingerprint import canonical_json, fingerprint_sha256
from catalog.models import (
    Archetype,
    CatalogConfig,
    CatalogResult,
    GatingConfig,
    ParamDef,
    ParamPack,
    Variant,
)
from catalog.runner import run_catalog
from catalog.strategy_catalog import (
    BUILDER_STATES,
    CATALOG_SCHEMA_VERSION,
    CATEGORY_ORDER,
    DEFAULT_CATALOG_PATH,
    STATUS_VALUES,
    archive_entries,
    build_entry_from_saved_run,
    build_entry_id,
    compute_params_hash,
    get_entry,
    list_entries,
    move_entries,
    note_entry,
    read_catalog,
    tag_entries,
    upsert_entry,
    upsert_from_builder_session,
    upsert_from_saved_run,
    write_catalog,
)

__all__ = [
    "BUILDER_STATES",
    "CATALOG_SCHEMA_VERSION",
    "CATEGORY_ORDER",
    "DEFAULT_CATALOG_PATH",
    "STATUS_VALUES",
    "Archetype",
    "CatalogConfig",
    "CatalogResult",
    "GatingConfig",
    "ParamDef",
    "ParamPack",
    "Variant",
    "archive_entries",
    "build_entry_from_saved_run",
    "build_entry_id",
    "canonical_json",
    "compute_params_hash",
    "fingerprint_sha256",
    "get_entry",
    "list_entries",
    "move_entries",
    "note_entry",
    "read_catalog",
    "run_catalog",
    "tag_entries",
    "upsert_entry",
    "upsert_from_builder_session",
    "upsert_from_saved_run",
    "write_catalog",
]
