"""Tests pour config.token_taxonomy.

Couvre :
- Chargement résilient au changement de cwd (régression du bug
  `Path("config/...")` qui produit OSError Errno 22 quand Streamlit
  change le cwd).
- Cohérence get_natural_universe_id (universe:bucket).
- Exclusion source dans get_tokens_in_universe.
- get_adjacent_bucket_tokens couvre L_n±1.
- get_cross_universe_diagnostic_tokens n'inclut pas l'univers source.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from config import token_taxonomy as tx


@pytest.fixture(autouse=True)
def _reset_taxonomy_cache():
    tx.reset_cache()
    yield
    tx.reset_cache()


def test_load_taxonomy_returns_dict_with_expected_keys():
    payload = tx.load_token_taxonomy()
    assert isinstance(payload, dict)
    assert "primary_universes" in payload
    assert "liquidity_buckets" in payload
    assert "bucket_order" in payload
    assert "tokens" in payload
    assert isinstance(payload["tokens"], dict)
    assert len(payload["tokens"]) >= 100  # 232 tokens dans l'étude


def test_load_taxonomy_is_resilient_to_cwd_change():
    """Régression bug paths relatifs Windows + Streamlit (cwd change).

    Le module utilise Path(__file__).resolve().parent : le chdir vers
    n'importe quel répertoire ne doit pas casser le chargement.
    """
    import tempfile

    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            os.chdir(tmp_dir)
            payload = tx.load_token_taxonomy(force_reload=True)
            assert "tokens" in payload
        finally:
            os.chdir(original_cwd)


def test_normalization_is_case_insensitive():
    assert tx.get_token_universe("btcusdc") == tx.get_token_universe("BTCUSDC")
    assert tx.get_token_bucket("btcusdc") == "L0_mega"


def test_unknown_token_returns_none():
    assert tx.get_token_universe("UNKNOWN_FOO_BAR_USDC") is None
    assert tx.get_token_bucket("UNKNOWN_FOO_BAR_USDC") is None
    assert tx.get_natural_universe_id("UNKNOWN_FOO_BAR_USDC") is None


def test_btc_eth_are_majors_l0_mega():
    assert tx.get_token_universe("BTCUSDC") == "MAJORS_RESERVE_BETA"
    assert tx.get_token_bucket("BTCUSDC") == "L0_mega"
    assert tx.get_natural_universe_id("BTCUSDC") == "MAJORS_RESERVE_BETA:L0_mega"

    assert tx.get_token_universe("ETHUSDC") == "MAJORS_RESERVE_BETA"
    assert tx.get_token_bucket("ETHUSDC") == "L0_mega"


def test_aave_is_defi_l2_mid_per_study():
    """Cas explicite de l'étude utilisateur : AAVE → DEFI_DEX_LENDING_PERPS_YIELD:L2_mid."""
    assert tx.get_natural_universe_id("AAVEUSDC") == "DEFI_DEX_LENDING_PERPS_YIELD:L2_mid"


def test_uni_crv_are_defi_l3_low_per_study():
    """Cas explicite de l'étude utilisateur : UNI → L3_low, CRV → L3_low."""
    assert tx.get_token_bucket("UNIUSDC") == "L3_low"
    assert tx.get_token_universe("UNIUSDC") == "DEFI_DEX_LENDING_PERPS_YIELD"
    assert tx.get_token_bucket("CRVUSDC") == "L3_low"
    assert tx.get_token_universe("CRVUSDC") == "DEFI_DEX_LENDING_PERPS_YIELD"


def test_memecoins_are_in_meme_universe():
    for symbol in ("DOGEUSDC", "SHIBUSDC", "PEPEUSDC"):
        assert tx.get_token_universe(symbol) == "MEME_SOCIAL_POLITICAL", symbol


def test_get_tokens_in_universe_filters_by_universe():
    tokens = tx.get_tokens_in_universe("MAJORS_RESERVE_BETA")
    assert "BTCUSDC" in tokens
    assert "ETHUSDC" in tokens
    # Pas de DeFi
    assert "AAVEUSDC" not in tokens
    assert "UNIUSDC" not in tokens


def test_get_tokens_in_universe_filters_by_bucket():
    tokens = tx.get_tokens_in_universe("MAJORS_RESERVE_BETA", bucket="L0_mega")
    assert tokens == ["BTCUSDC", "ETHUSDC"]


def test_get_tokens_in_universe_excludes_source():
    tokens = tx.get_tokens_in_universe(
        "DEFI_DEX_LENDING_PERPS_YIELD",
        bucket="L3_low",
        exclude=["CRVUSDC"],
    )
    assert "CRVUSDC" not in tokens
    assert "UNIUSDC" in tokens  # autre L3_low du même univers


def test_get_tokens_in_universe_unknown_returns_empty():
    assert tx.get_tokens_in_universe("UNKNOWN_UNIVERSE") == []
    assert tx.get_tokens_in_universe("") == []


def test_get_adjacent_bucket_tokens_l2_mid_finds_l1_high_and_l3_low():
    """AAVE est en L2_mid : voisins = L1_high et L3_low du même univers."""
    neighbors = tx.get_adjacent_bucket_tokens(
        "DEFI_DEX_LENDING_PERPS_YIELD",
        "L2_mid",
        exclude=["AAVEUSDC"],
    )
    # Pas de membre L2_mid (la fonction ne retourne QUE les voisins)
    assert "AAVEUSDC" not in neighbors
    assert "MORPHOUSDC" not in neighbors  # MORPHO est aussi L2_mid
    # Mais des L3_low (UNI, CRV, etc.)
    assert "UNIUSDC" in neighbors or "CRVUSDC" in neighbors


def test_get_adjacent_bucket_tokens_l0_mega_only_finds_l1_high_downstream():
    """L0_mega est en haut de l'échelle → un seul voisin (L1_high)."""
    neighbors = tx.get_adjacent_bucket_tokens("MAJORS_RESERVE_BETA", "L0_mega")
    # SOLUSDC est en L1_high MAJORS_RESERVE_BETA → doit apparaître
    assert "SOLUSDC" in neighbors


def test_get_adjacent_bucket_tokens_l4_micro_only_finds_l3_low_upstream():
    """L4_micro est en bas → un seul voisin (L3_low)."""
    neighbors = tx.get_adjacent_bucket_tokens("MEME_SOCIAL_POLITICAL", "L4_micro")
    # Tous les neighbors doivent être L3_low (bucket immédiatement supérieur)
    for symbol in neighbors:
        assert tx.get_token_bucket(symbol) == "L3_low", symbol


def test_get_adjacent_bucket_tokens_unknown_bucket_returns_empty():
    assert tx.get_adjacent_bucket_tokens("MAJORS_RESERVE_BETA", "BOGUS_BUCKET") == []


def test_cross_universe_diagnostic_excludes_source_universe():
    diagnostic = tx.get_cross_universe_diagnostic_tokens(
        "MEME_SOCIAL_POLITICAL",
        n_per_universe=2,
    )
    for symbol in diagnostic:
        universe = tx.get_token_universe(symbol)
        assert universe != "MEME_SOCIAL_POLITICAL", f"{symbol} should not be in source universe"


def test_cross_universe_diagnostic_covers_multiple_universes():
    diagnostic = tx.get_cross_universe_diagnostic_tokens(
        "MEME_SOCIAL_POLITICAL",
        n_per_universe=2,
    )
    universes = {tx.get_token_universe(symbol) for symbol in diagnostic}
    # Devrait couvrir plusieurs univers étrangers (au moins 5 sur 13)
    assert len(universes) >= 5


def test_cross_universe_diagnostic_respects_n_per_universe():
    diagnostic = tx.get_cross_universe_diagnostic_tokens(
        "MAJORS_RESERVE_BETA",
        n_per_universe=1,
    )
    from collections import Counter
    by_universe = Counter(tx.get_token_universe(symbol) for symbol in diagnostic)
    for count in by_universe.values():
        assert count <= 1


def test_cross_universe_diagnostic_zero_returns_empty():
    assert tx.get_cross_universe_diagnostic_tokens("MAJORS_RESERVE_BETA", n_per_universe=0) == []


def test_get_token_tags_returns_list():
    tags = tx.get_token_tags("BTCUSDC")
    assert isinstance(tags, list)
    assert "majors" in tags


def test_list_primary_universes_returns_14_universes():
    universes = tx.list_primary_universes()
    expected = {
        "MAJORS_RESERVE_BETA",
        "L1_ALT_SMART_CONTRACT",
        "L2_ROLLUP_MODULAR_INTEROP",
        "DEFI_DEX_LENDING_PERPS_YIELD",
        "STABLE_FIAT_GOLD_RWA_COLLATERAL",
        "MEME_SOCIAL_POLITICAL",
        "AI_DEPIN_COMPUTE",
        "ORACLE_DATA_INDEXING",
        "BTC_FORK_LEGACY_POW_PRIVACY",
        "GAMING_NFT_METAVERSE_CREATOR",
        "STORAGE_CONTENT_MEDIA_DEPIN",
        "IDENTITY_SOCIAL_PRIVACY_APP",
        "PAYMENT_EXCHANGE_WALLET",
        "NEW_LISTING_MISC_HIGH_BETA",
    }
    assert set(universes) == expected
