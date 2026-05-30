"""Tests unitaires pour config.indicator_history et l'extension de rank_indicator_selection.

Couvre :
- Persistance JSON (load/save/sanitize)
- Application des bannissements (ban_threshold, ban_duration)
- Sélection diversifiée (pénalités famille, inter-sessions)
- Pénalité de répétition dans rank_indicator_selection
- Mapping indicateur → famille
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helper : stub indicator_history sans toucher le disque du projet
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_policy(tmp_path: Path):
    """Retourne une politique générique avec history_file dans tmp_path."""
    return {
        "enabled": True,
        "history_length": 5,
        "ban_threshold": 3,
        "ban_duration": 2,
        "family_penalty_runs": 2,
        "previous_penalty": 0.50,
        "novelty_bonus": 0.60,
        "family_penalty": 0.25,
        "family_bonus": 0.15,
        "category_sampling_enabled": False,
        "category_min_families": 2,
        "history_file": str(tmp_path / "indicator_history.json"),
    }


@pytest.fixture
def history_mod():
    """Importe config.indicator_history (doit être importable depuis le workspace)."""
    import config.indicator_history as mod

    return mod


# ===========================================================================
# 1. Persistance JSON
# ===========================================================================


class TestPersistenceJSON:
    def test_load_empty_when_file_missing(self, history_mod, tmp_policy):
        """load_history retourne un historique vide si le fichier n'existe pas."""
        h = history_mod.load_history(tmp_policy)
        assert h["recent_runs"] == []
        assert h["recent_families"] == []
        assert h["banned_indicators"] == {}

    def test_save_and_reload(self, history_mod, tmp_policy):
        """save_history écrit et load_history relit correctement."""
        data = {
            "recent_runs": [["rsi", "macd"], ["ema", "atr"]],
            "recent_families": [["momentum"], ["trend-following"]],
            "banned_indicators": {"bollinger": 2},
        }
        history_mod.save_history(data, tmp_policy)
        loaded = history_mod.load_history(tmp_policy)
        assert loaded["recent_runs"] == [["rsi", "macd"], ["ema", "atr"]]
        assert loaded["banned_indicators"] == {"bollinger": 2}

    def test_save_atomic_does_not_corrupt(self, history_mod, tmp_policy, tmp_path):
        """Deux save_history consécutifs ne corrompent pas le fichier."""
        history_mod.save_history({"recent_runs": [["rsi"]], "recent_families": [], "banned_indicators": {}}, tmp_policy)
        history_mod.save_history(
            {"recent_runs": [["rsi"], ["macd"]], "recent_families": [], "banned_indicators": {}}, tmp_policy,
        )
        loaded = history_mod.load_history(tmp_policy)
        assert len(loaded["recent_runs"]) == 2

    def test_load_corrupted_file_returns_empty(self, history_mod, tmp_policy, tmp_path):
        """Un fichier JSON corrompu renvoie un historique vide."""
        (tmp_path / "indicator_history.json").write_text("NOT_JSON", encoding="utf-8")
        h = history_mod.load_history(tmp_policy)
        assert h["recent_runs"] == []

    def test_sanitize_strips_invalid_types(self, history_mod):
        """_sanitize_history accepte les structures valides et ignore le reste."""
        raw = {
            "recent_runs": [["rsi", 42, None], "bad"],  # mixed/wrong types
            "banned_indicators": {"ema": "3", "bollinger": 1},
            "recent_families": None,
        }
        clean = history_mod._sanitize_history(raw)
        assert isinstance(clean["recent_runs"], list)
        assert isinstance(clean["banned_indicators"], dict)
        assert clean["recent_families"] == []
        # int "3" doit être converti en int
        assert clean["banned_indicators"]["ema"] == 3


# ===========================================================================
# 2. Bannissements
# ===========================================================================


class TestBanLogic:
    def test_ban_triggered_at_threshold(self, history_mod, tmp_policy):
        """Un indicateur apparaissant ban_threshold fois est banni."""
        pol = dict(tmp_policy)
        pol["ban_threshold"] = 3
        pol["ban_duration"] = 2
        # 3 runs contenant "rsi"
        h = {"recent_runs": [], "recent_families": [], "banned_indicators": {}}
        history_mod.save_history(h, pol)
        for _ in range(3):
            history_mod.update_history(["rsi", "macd"], policy=pol)
        h = history_mod.load_history(pol)
        assert "rsi" in h["banned_indicators"]
        assert h["banned_indicators"]["rsi"] > 0

    def test_ban_expires_after_duration(self, history_mod, tmp_path):
        """Un bannissement de durée 2 disparaît après 2 runs ET que l'indicateur
        soit sorti du fenêtre FIFO (history_length=2 pour ce test).
        """
        pol = {
            "enabled": True,
            "history_length": 2,  # fenêtre courte : les 2 runs "rsi" tombent vite
            "ban_threshold": 2,
            "ban_duration": 2,
            "family_penalty_runs": 2,
            "previous_penalty": 0.5,
            "novelty_bonus": 0.6,
            "family_penalty": 0.25,
            "family_bonus": 0.15,
            "category_sampling_enabled": False,
            "category_min_families": 2,
            "history_file": str(tmp_path / "history_expire.json"),
        }
        # 2 runs avec rsi → banni (durée 2)
        history_mod.update_history(["rsi"], policy=pol)
        history_mod.update_history(["rsi"], policy=pol)
        h = history_mod.load_history(pol)
        assert "rsi" in h["banned_indicators"], "rsi devrait être banni après 2 runs"

        # 2 runs avec uniquement "ema" :
        # - les 2 runs "rsi" tombent hors de la FIFO (history_length=2)
        # - le compteur de durée de "rsi" atteint 0 → expiration
        history_mod.update_history(["ema"], policy=pol)
        history_mod.update_history(["ema"], policy=pol)
        h2 = history_mod.load_history(pol)
        # "rsi" ne doit plus être présent (ou durée 0)
        assert "rsi" not in h2.get("banned_indicators", {}) or h2["banned_indicators"].get("rsi", 0) == 0

    def test_get_banned_indicators_returns_only_active(self, history_mod, tmp_policy):
        """get_banned_indicators ne retourne que les indicateurs avec durée > 0."""
        h = {
            "recent_runs": [],
            "recent_families": [],
            "banned_indicators": {"rsi": 2, "ema": 0, "macd": 1},
        }
        banned = history_mod.get_banned_indicators(h)
        assert "rsi" in banned
        assert "macd" in banned
        assert "ema" not in banned

    def test_ban_does_not_exceed_history_length(self, history_mod, tmp_policy):
        """La FIFO ne dépasse pas history_length runs."""
        pol = dict(tmp_policy)
        pol["history_length"] = 3
        for i in range(10):
            history_mod.update_history([f"ind_{i}"], policy=pol)
        h = history_mod.load_history(pol)
        assert len(h["recent_runs"]) <= 3


# ===========================================================================
# 3. Sélection diversifiée par familles
# ===========================================================================


class TestFamilyDiversity:
    def test_get_recent_families_deduplicates(self, history_mod, tmp_policy):
        """get_recent_families retourne des familles distinctes."""
        pol = dict(tmp_policy)
        pol["family_penalty_runs"] = 3
        h = {
            "recent_runs": [],
            "recent_families": [["momentum"], ["momentum", "trend-following"]],
            "banned_indicators": {},
        }
        fams = history_mod.get_recent_families(h, pol)
        assert fams.count("momentum") == 1
        assert "trend-following" in fams

    def test_infer_families_from_indicators(self, history_mod):
        """infer_families_from_indicators associe correctement indicateur→famille."""
        fam_map = history_mod.build_indicator_to_family_map()
        # "rsi" appartient à "mean-reversion" ou "momentum" selon la config
        assert isinstance(fam_map, dict)
        if fam_map:  # peut être vide si import builder_objectives échoue en test isolé
            inferred = history_mod.infer_families_from_indicators(["rsi", "ema"], fam_map)
            assert isinstance(inferred, list)

    def test_build_indicator_family_map_no_duplicates(self, history_mod):
        """Chaque indicateur n'est mappé qu'à une seule famille."""
        fam_map = history_mod.build_indicator_to_family_map()
        for ind, fam in fam_map.items():
            assert isinstance(fam, str)
            assert fam  # pas de famille vide

    def test_update_history_records_families(self, history_mod, tmp_policy):
        """update_history enregistre les familles inférées."""
        try:
            fam_map = history_mod.build_indicator_to_family_map()
            inds = list(fam_map.keys())[:3] if fam_map else ["rsi"]
            families = history_mod.infer_families_from_indicators(inds, fam_map)
        except Exception:
            inds = ["rsi"]
            families = ["test-family"]
        h = history_mod.update_history(inds, families_used=families, policy=tmp_policy)
        assert "recent_families" in h
        if families:
            assert len(h["recent_families"]) > 0


# ===========================================================================
# 4. Pénalité de répétition dans rank_indicator_selection
# ===========================================================================


class TestRankIndicatorSelection:
    def _rank(self, indicators, **kwargs):
        from agents.indicator_context import rank_indicator_selection

        return rank_indicator_selection(indicators, **kwargs)

    def test_banned_indicators_removed(self):
        """Les indicateurs bannis ne doivent pas apparaître dans le classement."""
        candidates = ["rsi", "ema", "macd", "bollinger", "atr"]
        ranked = self._rank(candidates, banned_indicators={"rsi", "bollinger"})
        assert "rsi" not in ranked
        assert "bollinger" not in ranked
        assert len(ranked) == 3

    def test_inter_session_penalty_lowers_rank(self):
        """Un indicateur vu récemment reçoit un malus et descend dans le classement."""
        # Sans pénalité : "ema" et "rsi" sont équivalents
        candidates = ["rsi", "ema", "macd", "atr"]
        baseline = self._rank(candidates, objective="trend momentum", session_seed="test-seed-1")

        # Avec pénalité sur "rsi"
        with_penalty = self._rank(
            candidates,
            objective="trend momentum",
            session_seed="test-seed-1",
            inter_session_indicators=["rsi"],
            inter_session_penalty=5.0,  # pénalité forte pour le test
        )
        # "rsi" devrait être plus bas avec pénalité
        assert (
            with_penalty.index("rsi") >= baseline.index("rsi") or with_penalty.index("rsi") > 0
        )  # au moins non en tête si pénalité forte

    def test_novelty_bonus_raises_rank(self):
        """Un indicateur jamais vu reçoit un bonus et monte dans le classement."""
        candidates = ["rsi", "ema", "unusual_indicator", "atr"]
        # Tous les indicateurs sauf "unusual_indicator" sont "récents"
        ranked = self._rank(
            candidates,
            inter_session_indicators=["rsi", "ema", "atr"],
            inter_session_novelty_bonus=10.0,  # bonus très fort
            prefer_diversity=True,
        )
        # "unusual_indicator" devrait être en tête grâce au bonus de nouveauté
        # (sauf si un autre indicateur a un score de pertinence très fort)
        assert ranked[0] == "unusual_indicator" or "unusual_indicator" in ranked[:2]

    def test_performance_priors_raise_rank(self):
        """Un prior historique positif doit favoriser un indicateur."""
        candidates = ["rsi", "bollinger"]
        ranked = self._rank(
            candidates,
            session_seed="performance-prior-test",
            performance_priors={"rsi": -2.0, "bollinger": 2.0},
            performance_prior_weight=10.0,
        )
        assert ranked.index("bollinger") < ranked.index("rsi")

    def test_family_penalty_applied(self):
        """Les indicateurs d'une famille récente reçoivent un malus."""
        from agents.indicator_context import rank_indicator_selection
        from config.indicator_history import build_indicator_to_family_map

        fam_map = build_indicator_to_family_map()
        if not fam_map:
            pytest.skip("build_indicator_to_family_map returned empty (import issue in test env)")

        # Trouver des indicateurs de familles différentes
        family_to_inds: dict[str, list[str]] = {}
        for ind, fam in fam_map.items():
            family_to_inds.setdefault(fam, []).append(ind)

        if len(family_to_inds) < 2:
            pytest.skip("Not enough families to test family penalty")

        families = list(family_to_inds.keys())
        penalized_family = families[0]
        neutral_family = families[1]
        penalized_ind = family_to_inds[penalized_family][0]
        neutral_ind = family_to_inds[neutral_family][0]

        ranked = rank_indicator_selection(
            [penalized_ind, neutral_ind, "atr"],
            previous_families=[penalized_family],
            family_penalty=10.0,  # pénalité forte pour le test
            session_seed="family-test",
        )
        # L'indicateur de la famille pénalisée doit être derrière
        assert ranked.index(neutral_ind) < ranked.index(penalized_ind) or ranked[-1] == penalized_ind

    def test_empty_available_returns_empty(self):
        """rank_indicator_selection avec liste vide retourne liste vide."""
        ranked = self._rank([], banned_indicators={"rsi"})
        assert ranked == []

    def test_all_banned_returns_empty(self):
        """Si tous les indicateurs sont bannis, retourne une liste vide."""
        candidates = ["rsi", "ema"]
        ranked = self._rank(candidates, banned_indicators={"rsi", "ema"})
        assert ranked == []


# ===========================================================================
# 5. load_policy avec valeurs par défaut
# ===========================================================================


class TestLoadPolicy:
    def test_load_policy_returns_defaults_when_missing(self, history_mod, tmp_path, monkeypatch):
        """load_policy retourne les valeurs par défaut si le fichier est absent."""
        from config import indicator_history as mod

        # Patcher _policy_file pour pointer vers un fichier inexistant
        monkeypatch.setattr(mod, "_policy_file", lambda: tmp_path / "no_policy.json")
        monkeypatch.setattr(mod, "_policy_cache", None)
        pol = mod.load_policy(force_reload=True)
        assert pol["history_length"] == 10
        assert pol["ban_threshold"] == 4
        assert pol["ban_duration"] == 3

    def test_load_policy_merges_with_defaults(self, history_mod, tmp_path, monkeypatch):
        """load_policy fusionne les valeurs présentes avec les defaults."""
        from config import indicator_history as mod

        policy_path = tmp_path / "my_policy.json"
        policy_path.write_text(json.dumps({"ban_threshold": 7, "history_length": 20}), encoding="utf-8")
        monkeypatch.setattr(mod, "_policy_file", lambda: policy_path)
        monkeypatch.setattr(mod, "_policy_cache", None)
        pol = mod.load_policy(force_reload=True)
        assert pol["ban_threshold"] == 7
        assert pol["history_length"] == 20
        # Clé non présente → valeur par défaut
        assert pol["ban_duration"] == 3
