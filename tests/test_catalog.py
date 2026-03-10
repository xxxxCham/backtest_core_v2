"""
Tests pour le module catalog — générateur paramétrique de fiches de stratégies.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths helpers
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
ARCHETYPES_DIR = ROOT / "catalog" / "archetypes"
PARAM_PACKS_DIR = ROOT / "catalog" / "param_packs"
EXAMPLE_CONFIG = ROOT / "catalog" / "example_config.json"


# ===========================================================================
# 1. Fingerprint
# ===========================================================================

class TestFingerprint:
    def test_fingerprint_deterministic(self):
        """Même objet → même hash, stable entre appels."""
        from catalog.fingerprint import fingerprint_sha256

        obj = {"a": 1, "b": [2, 3], "c": {"d": 4.0}}
        h1 = fingerprint_sha256(obj)
        h2 = fingerprint_sha256(obj)
        assert h1 == h2
        assert len(h1) == 64  # SHA256 hex

    def test_canonical_json_sort_keys(self):
        """Clés triées, séparateurs compacts."""
        from catalog.fingerprint import canonical_json

        result = canonical_json({"z": 1, "a": 2, "m": 3})
        assert result == '{"a":2,"m":3,"z":1}'

    def test_canonical_json_float_normalization(self):
        """Flottants entiers convertis en int."""
        from catalog.fingerprint import canonical_json

        result = canonical_json({"val": 5.0})
        assert '"val":5' in result

    def test_different_objects_different_fingerprints(self):
        """Deux objets différents → fingerprints différents."""
        from catalog.fingerprint import fingerprint_sha256

        h1 = fingerprint_sha256({"a": 1})
        h2 = fingerprint_sha256({"a": 2})
        assert h1 != h2


# ===========================================================================
# 2. Archetype loading
# ===========================================================================

class TestArchetypeLoad:
    @pytest.fixture
    def archetype_files(self):
        return sorted(ARCHETYPES_DIR.glob("*.json"))

    def test_five_archetypes_exist(self, archetype_files):
        """5 fichiers archetypes existent."""
        assert len(archetype_files) == 5

    def test_archetype_load_all(self, archetype_files):
        """Tous les archetypes se chargent sans erreur."""
        from catalog.models import Archetype

        for path in archetype_files:
            arch = Archetype.load(path)
            assert arch.archetype_id
            assert arch.family
            assert len(arch.indicators) > 0
            assert arch.entry_long_logic
            assert arch.exit_logic
            assert arch.risk_management
            assert arch.default_params
            assert arch.parameter_specs

    def test_archetype_required_fields(self):
        """L'archetype mean_reversion a les bons champs."""
        from catalog.models import Archetype

        path = ARCHETYPES_DIR / "mean_reversion_bollinger_rsi.json"
        arch = Archetype.load(path)
        assert arch.archetype_id == "mean_reversion_bollinger_rsi"
        assert arch.family == "mean_reversion"
        assert "bollinger" in arch.indicators
        assert "rsi" in arch.indicators
        assert "atr" in arch.indicators
        assert "rsi_oversold" in arch.entry_long_logic or "${rsi_oversold}" in arch.entry_long_logic


# ===========================================================================
# 3. ParamPack loading
# ===========================================================================

class TestParamPackLoad:
    @pytest.fixture
    def pack_files(self):
        return sorted(PARAM_PACKS_DIR.glob("*.json"))

    def test_five_param_packs_exist(self, pack_files):
        """5 fichiers param_packs existent."""
        assert len(pack_files) == 5

    def test_param_pack_load_all(self, pack_files):
        """Tous les param_packs se chargent et sont liés à un archetype."""
        from catalog.models import ParamPack

        for path in pack_files:
            pack = ParamPack.load(path)
            assert pack.param_pack_id
            assert pack.archetype_id
            assert len(pack.param_defs) > 0

    def test_param_pack_archetype_link(self, pack_files):
        """Chaque param_pack référence un archetype existant."""
        from catalog.models import Archetype, ParamPack

        archetype_ids = {
            Archetype.load(p).archetype_id
            for p in ARCHETYPES_DIR.glob("*.json")
        }
        for path in pack_files:
            pack = ParamPack.load(path)
            assert pack.archetype_id in archetype_ids, (
                f"{pack.param_pack_id} référence un archetype inconnu: {pack.archetype_id}"
            )


# ===========================================================================
# 4. Ranges loader (TOML resolution)
# ===========================================================================

class TestRangesLoader:
    def test_resolve_param_defs_from_toml(self):
        """Résolution source 'toml' → bornes concrètes non nulles."""
        from catalog.models import ParamPack
        from catalog.ranges_loader import resolve_param_defs

        pack = ParamPack.load(PARAM_PACKS_DIR / "mr_boll_rsi__v1.json")
        specs = resolve_param_defs(pack)

        # bb_period source=toml → doit avoir min/max > 0
        assert "bb_period" in specs
        assert specs["bb_period"].min_val > 0
        assert specs["bb_period"].max_val > specs["bb_period"].min_val

    def test_resolve_direct_param_defs(self):
        """Résolution source directe (min/max/step)."""
        from catalog.models import ParamPack
        from catalog.ranges_loader import resolve_param_defs

        pack = ParamPack.load(PARAM_PACKS_DIR / "mr_boll_rsi__v1.json")
        specs = resolve_param_defs(pack)

        # rsi_oversold source directe → min=20, max=40
        assert "rsi_oversold" in specs
        assert specs["rsi_oversold"].min_val == 20.0
        assert specs["rsi_oversold"].max_val == 40.0


# ===========================================================================
# 5. Sanity validation
# ===========================================================================

class TestSanity:
    def _make_valid_variant(self):
        """Crée un variant minimal valide."""
        from catalog.models import Variant

        return Variant(
            variant_id="test_v0001",
            archetype_id="test_arch",
            param_pack_id="test_pack",
            params={"rsi_period": 14},
            proposal={
                "strategy_name": "test_strategy",
                "used_indicators": ["bollinger", "rsi", "atr"],
                "entry_long_logic": "close < bollinger.lower and rsi < 30",
                "entry_short_logic": "close > bollinger.upper and rsi > 70",
                "exit_logic": "cross_any(close, bollinger.middle)",
                "risk_management": "ATR stop-loss (1.5x)",
                "default_params": {
                    "bb_period": 20, "rsi_period": 14,
                    "stop_atr_mult": 1.5, "warmup": 50, "leverage": 1,
                },
                "parameter_specs": {},
            },
        )

    def test_valid_variant_passes(self):
        """Un variant bien formé passe la validation."""
        from catalog.sanity import validate_variant

        variant = self._make_valid_variant()
        is_valid, reasons = validate_variant(variant)
        assert is_valid, f"Should be valid but got: {reasons}"

    def test_registry_only_valid(self):
        """Rejet d'un indicateur inventé."""
        from catalog.sanity import validate_variant

        variant = self._make_valid_variant()
        variant.proposal["used_indicators"] = ["magic_indicator"]
        is_valid, reasons = validate_variant(variant)
        assert not is_valid
        assert any("magic_indicator" in r for r in reasons)

    def test_stop_loss_mandatory(self):
        """Rejet si aucun stop-loss déclaré."""
        from catalog.sanity import validate_variant

        variant = self._make_valid_variant()
        variant.proposal["default_params"] = {"warmup": 50, "leverage": 1}
        variant.proposal["risk_management"] = "No risk management"
        is_valid, reasons = validate_variant(variant)
        assert not is_valid
        assert any("stop" in r.lower() for r in reasons)

    def test_anti_lookahead_dsl(self):
        """Rejet d'expressions look-ahead."""
        from catalog.sanity import validate_variant

        variant = self._make_valid_variant()

        # Test [t+1]
        variant.proposal["entry_long_logic"] = "close[t+1] > open"
        is_valid, reasons = validate_variant(variant)
        assert not is_valid
        assert any("look-ahead" in r.lower() or "lookahead" in r.lower() for r in reasons)

    def test_anti_lookahead_shift(self):
        """Rejet de shift(-1)."""
        from catalog.sanity import validate_variant

        variant = self._make_valid_variant()
        variant.proposal["exit_logic"] = "rsi.shift(-1) > 70"
        is_valid, reasons = validate_variant(variant)
        assert not is_valid

    def test_placeholder_rejected(self):
        """Rejet d'un entry_long_logic placeholder."""
        from catalog.sanity import validate_variant

        variant = self._make_valid_variant()
        variant.proposal["entry_long_logic"] = ""
        is_valid, reasons = validate_variant(variant)
        assert not is_valid

    def test_crosses_token_rejected(self):
        """Rejet explicite des tokens DSL ambigus 'crosses'."""
        from catalog.sanity import validate_variant

        variant = self._make_valid_variant()
        variant.proposal["exit_logic"] = "close crosses bollinger.middle"
        is_valid, reasons = validate_variant(variant)
        assert not is_valid
        assert any("crosses" in r.lower() for r in reasons)

    def test_forbidden_df_token_rejected(self):
        """Rejet des expressions DSL non compatibles contrat codegen."""
        from catalog.sanity import validate_variant

        variant = self._make_valid_variant()
        variant.proposal["entry_long_logic"] = "df['close'] > bollinger.lower"
        is_valid, reasons = validate_variant(variant)
        assert not is_valid
        assert any("df[" in r.lower() for r in reasons)

    def test_exogene_indicator_rejected(self):
        """Rejet d'indicateurs exogènes en profil ohlcv_only."""
        from catalog.sanity import validate_variant

        variant = self._make_valid_variant()
        variant.proposal["used_indicators"] = ["fear_greed", "rsi"]
        is_valid, reasons = validate_variant(variant, profile="ohlcv_only")
        assert not is_valid
        assert any("fear_greed" in r for r in reasons)


# ===========================================================================
# 6. Chainer (generation)
# ===========================================================================

class TestChainer:
    def test_generate_variants_count(self):
        """Génère des variants et vérifie le count."""
        from catalog.chainer import generate_catalog
        from catalog.models import CatalogConfig

        config = CatalogConfig(
            seed=42,
            n_variants_target=20,
            batch_size=10,
            archetypes_dir=str(ARCHETYPES_DIR),
            param_packs_dir=str(PARAM_PACKS_DIR),
        )
        result = generate_catalog(config)
        assert result.total_generated > 0
        assert result.total_after_sanity > 0
        assert len(result.variants) > 0

    def test_dedup_fingerprints(self):
        """Deux runs identiques → mêmes fingerprints, pas de doublons."""
        from catalog.chainer import generate_catalog
        from catalog.models import CatalogConfig

        config = CatalogConfig(
            seed=42,
            n_variants_target=10,
            batch_size=10,
            archetypes_dir=str(ARCHETYPES_DIR),
            param_packs_dir=str(PARAM_PACKS_DIR),
        )

        result = generate_catalog(config)
        fps = [v.fingerprint for v in result.variants]
        assert len(fps) == len(set(fps)), "Fingerprints should be unique"

    def test_deterministic_seeding(self):
        """Même seed → mêmes variants."""
        from catalog.chainer import generate_catalog
        from catalog.models import CatalogConfig

        config = CatalogConfig(
            seed=123,
            n_variants_target=5,
            batch_size=10,
            archetypes_dir=str(ARCHETYPES_DIR),
            param_packs_dir=str(PARAM_PACKS_DIR),
        )

        r1 = generate_catalog(config)
        r2 = generate_catalog(config)

        fps1 = [v.fingerprint for v in r1.variants]
        fps2 = [v.fingerprint for v in r2.variants]
        assert fps1 == fps2


# ===========================================================================
# 7. Builder export
# ===========================================================================

class TestBuilderExport:
    def _make_proposal(self):
        return {
            "strategy_name": "test_mr_bollinger",
            "hypothesis": "Test hypothesis",
            "change_type": "logic",
            "used_indicators": ["bollinger", "rsi", "atr"],
            "indicator_params": {
                "bollinger": {"period": 20, "std_dev": 2.0},
                "rsi": {"period": 14},
            },
            "entry_long_logic": "close < bollinger.lower and rsi < 30",
            "entry_short_logic": "close > bollinger.upper and rsi > 70",
            "exit_logic": "cross_any(close, bollinger.middle)",
            "risk_management": "ATR stop-loss (1.5x)",
            "default_params": {
                "bb_period": 20, "stop_atr_mult": 1.5,
                "tp_atr_mult": 3.0, "warmup": 50, "leverage": 1,
            },
            "parameter_specs": {},
        }

    def test_export_text_v1_format(self):
        """Format texte contient 'FICHE_STRATEGIE v1' et indicateurs."""
        from catalog.builder_export import to_text_v1

        proposal = self._make_proposal()
        text = to_text_v1(proposal)
        assert "FICHE_STRATEGIE v1" in text
        assert "bollinger" in text
        assert "rsi" in text
        assert "stop_atr_mult" in text

    def test_export_json_proposal_keys(self):
        """JSON proposal contient toutes les clés requises du Builder."""
        from catalog.builder_export import to_json_proposal

        proposal = self._make_proposal()
        result = to_json_proposal(proposal)

        required_keys = {
            "strategy_name", "used_indicators", "entry_long_logic",
            "exit_logic", "risk_management", "default_params", "parameter_specs",
        }
        assert required_keys.issubset(result.keys())

    def test_export_json_forces_leverage_and_warmup(self):
        """JSON proposal force leverage=1 et warmup=50 par défaut."""
        from catalog.builder_export import to_json_proposal

        minimal = {
            "strategy_name": "test",
            "default_params": {},
        }
        result = to_json_proposal(minimal)
        assert result["default_params"]["leverage"] == 1
        assert result["default_params"]["warmup"] == 50


# ===========================================================================
# 8. Models serialization
# ===========================================================================

class TestModels:
    def test_archetype_roundtrip(self, tmp_path):
        """Archetype to_dict/from_dict roundtrip."""
        from catalog.models import Archetype

        arch = Archetype(
            archetype_id="test_arch",
            family="test",
            indicators=["rsi"],
            entry_long_logic="rsi < 30",
            exit_logic="rsi > 70",
        )
        arch.save(tmp_path / "test.json")
        loaded = Archetype.load(tmp_path / "test.json")
        assert loaded.archetype_id == "test_arch"
        assert loaded.indicators == ["rsi"]

    def test_param_pack_roundtrip(self, tmp_path):
        """ParamPack to_dict/from_dict roundtrip."""
        from catalog.models import ParamDef, ParamPack

        pack = ParamPack(
            param_pack_id="test_pack",
            archetype_id="test_arch",
            seed=42,
            param_defs={"rsi_period": ParamDef(dist="int_uniform", min=7, max=21)},
            constraints=[{"type": "less_than", "a": "a", "b": "b"}],
        )
        pack.save(tmp_path / "test_pack.json")
        loaded = ParamPack.load(tmp_path / "test_pack.json")
        assert loaded.param_pack_id == "test_pack"
        assert "rsi_period" in loaded.param_defs

    def test_catalog_config_load(self):
        """CatalogConfig se charge depuis example_config.json."""
        from catalog.models import CatalogConfig

        config = CatalogConfig.load(EXAMPLE_CONFIG)
        assert config.seed == 42
        assert config.n_variants_target == 200
        assert config.batch_size == 50

    def test_variant_to_dict(self):
        """Variant.to_dict contient tous les champs."""
        from catalog.models import Variant

        v = Variant(
            variant_id="v1",
            archetype_id="a1",
            param_pack_id="p1",
            params={"x": 1},
            proposal={"strategy_name": "test"},
            fingerprint="abc123",
        )
        d = v.to_dict()
        assert d["variant_id"] == "v1"
        assert d["fingerprint"] == "abc123"
        assert "gating_result" not in d  # None → omis


# ===========================================================================
# 9. Gating (compile check only — no actual backtest)
# ===========================================================================

class TestGatingCompile:
    def test_gating_proposal_compiles(self):
        """compile_proposal_to_code produit du code Python non vide."""
        from agents.strategy_builder import compile_proposal_to_code

        proposal = {
            "strategy_name": "test_compile",
            "used_indicators": ["bollinger", "rsi", "atr"],
            "indicator_params": {
                "bollinger": {"period": 20, "std_dev": 2.0},
                "rsi": {"period": 14},
                "atr": {"period": 14},
            },
            "entry_long_logic": "close < bollinger.lower and rsi < 30",
            "entry_short_logic": "close > bollinger.upper and rsi > 70",
            "exit_logic": "cross_any(close, bollinger.middle)",
            "risk_management": "ATR stop-loss (1.5x)",
            "default_params": {
                "bb_period": 20, "rsi_period": 14, "atr_period": 14,
                "stop_atr_mult": 1.5, "tp_atr_mult": 3.0,
                "warmup": 50, "leverage": 1,
            },
            "parameter_specs": {},
        }
        code = compile_proposal_to_code(proposal, variant=0)
        assert code
        assert "class" in code
        assert "generate_signals" in code
