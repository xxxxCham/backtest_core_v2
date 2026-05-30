"""Tests pour tools/audit_taxonomy_coverage.py.

Couvre :
- compute_taxonomy_coverage retourne le bon split (covered/missing/orphan).
- build_unclassified_stub produit un JSON template valide.
- render_text_report ne crash pas et inclut les compteurs.
- CLI main() : exit 0 si tout est couvert, exit 2 avec --exit-on-missing si manquants.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import audit_taxonomy_coverage as audit


def _fake_inventory(symbols: list[str]) -> dict[str, dict[str, dict[str, object]]]:
    return {
        symbol: {"1h": {"path": f"/fake/{symbol}_1h.parquet", "n_bars": 1000}}
        for symbol in symbols
    }


def _fake_taxonomy(symbols: list[str]) -> dict[str, object]:
    return {
        "version": "test",
        "tokens": {
            symbol: {
                "primary_universe": "MAJORS_RESERVE_BETA",
                "secondary_tags": [],
                "liquidity_bucket": "L0_mega",
            }
            for symbol in symbols
        },
    }


def test_compute_coverage_all_match():
    inventory = _fake_inventory(["BTCUSDC", "ETHUSDC"])
    taxonomy = _fake_taxonomy(["BTCUSDC", "ETHUSDC"])
    report = audit.compute_taxonomy_coverage(inventory=inventory, taxonomy=taxonomy)
    assert report["ohlcv_symbol_count"] == 2
    assert report["taxonomy_symbol_count"] == 2
    assert report["covered_symbols"] == ["BTCUSDC", "ETHUSDC"]
    assert report["missing_in_taxonomy"] == []
    assert report["orphan_in_taxonomy"] == []
    assert report["coverage_pct"] == 100.0


def test_compute_coverage_missing_in_taxonomy_listed():
    inventory = _fake_inventory(["BTCUSDC", "NEWTOKENUSDC", "OTHERUSDC"])
    taxonomy = _fake_taxonomy(["BTCUSDC"])
    report = audit.compute_taxonomy_coverage(inventory=inventory, taxonomy=taxonomy)
    assert report["missing_in_taxonomy"] == ["NEWTOKENUSDC", "OTHERUSDC"]
    assert report["orphan_in_taxonomy"] == []
    assert report["coverage_pct"] == round(1 / 3 * 100.0, 1)


def test_compute_coverage_orphan_in_taxonomy_listed():
    inventory = _fake_inventory(["BTCUSDC"])
    taxonomy = _fake_taxonomy(["BTCUSDC", "DELISTEDUSDC"])
    report = audit.compute_taxonomy_coverage(inventory=inventory, taxonomy=taxonomy)
    assert report["missing_in_taxonomy"] == []
    assert report["orphan_in_taxonomy"] == ["DELISTEDUSDC"]
    assert report["coverage_pct"] == 100.0


def test_compute_coverage_empty_inventory():
    report = audit.compute_taxonomy_coverage(inventory={}, taxonomy=_fake_taxonomy(["BTCUSDC"]))
    assert report["ohlcv_symbol_count"] == 0
    assert report["coverage_pct"] == 0.0
    assert report["orphan_in_taxonomy"] == ["BTCUSDC"]


def test_compute_coverage_case_insensitive():
    inventory = _fake_inventory(["btcusdc"])
    taxonomy = _fake_taxonomy(["BTCUSDC"])
    report = audit.compute_taxonomy_coverage(inventory=inventory, taxonomy=taxonomy)
    assert report["covered_symbols"] == ["BTCUSDC"]


def test_build_unclassified_stub_format():
    stub = audit.build_unclassified_stub(["FOOUSDC", "BARUSDC"])
    assert stub["version"] == "stub"
    assert "tokens" in stub
    assert set(stub["tokens"].keys()) == {"FOOUSDC", "BARUSDC"}
    for token_entry in stub["tokens"].values():
        assert token_entry["primary_universe"] == "NEW_LISTING_MISC_HIGH_BETA"
        assert token_entry["liquidity_bucket"] is None
        assert "unclassified" in token_entry["secondary_tags"]


def test_render_text_report_contains_counts():
    report = audit.compute_taxonomy_coverage(
        inventory=_fake_inventory(["BTCUSDC", "NEWUSDC"]),
        taxonomy=_fake_taxonomy(["BTCUSDC", "DELISTEDUSDC"]),
    )
    text = audit.render_text_report(report)
    assert "OHLCV disponibles" in text
    assert "NEWUSDC" in text  # listé en missing
    assert "DELISTEDUSDC" in text  # listé en orphan


def test_main_exit_zero_when_no_missing(monkeypatch, capsys):
    monkeypatch.setattr(
        audit,
        "compute_taxonomy_coverage",
        lambda **kwargs: {
            "ohlcv_symbol_count": 1,
            "taxonomy_symbol_count": 1,
            "covered_symbols": ["BTCUSDC"],
            "missing_in_taxonomy": [],
            "orphan_in_taxonomy": [],
            "coverage_pct": 100.0,
        },
    )
    exit_code = audit.main([])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Audit taxonomie" in captured.out


def test_main_exit_2_when_missing_and_flag(monkeypatch, capsys):
    monkeypatch.setattr(
        audit,
        "compute_taxonomy_coverage",
        lambda **kwargs: {
            "ohlcv_symbol_count": 2,
            "taxonomy_symbol_count": 1,
            "covered_symbols": ["BTCUSDC"],
            "missing_in_taxonomy": ["NEWUSDC"],
            "orphan_in_taxonomy": [],
            "coverage_pct": 50.0,
        },
    )
    exit_code = audit.main(["--exit-on-missing"])
    assert exit_code == 2


def test_main_json_output(monkeypatch, capsys):
    monkeypatch.setattr(
        audit,
        "compute_taxonomy_coverage",
        lambda **kwargs: {
            "ohlcv_symbol_count": 1,
            "taxonomy_symbol_count": 1,
            "covered_symbols": ["BTCUSDC"],
            "missing_in_taxonomy": [],
            "orphan_in_taxonomy": [],
            "coverage_pct": 100.0,
        },
    )
    audit.main(["--json"])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["coverage_pct"] == 100.0


def test_main_emits_stub_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        audit,
        "compute_taxonomy_coverage",
        lambda **kwargs: {
            "ohlcv_symbol_count": 2,
            "taxonomy_symbol_count": 1,
            "covered_symbols": ["BTCUSDC"],
            "missing_in_taxonomy": ["NEWUSDC"],
            "orphan_in_taxonomy": [],
            "coverage_pct": 50.0,
        },
    )
    stub_path = tmp_path / "stub.json"
    exit_code = audit.main(["--emit-stub", "--stub-path", str(stub_path)])
    assert exit_code == 0
    assert stub_path.exists()
    payload = json.loads(stub_path.read_text(encoding="utf-8"))
    assert "NEWUSDC" in payload["tokens"]


def test_main_no_stub_when_no_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        audit,
        "compute_taxonomy_coverage",
        lambda **kwargs: {
            "ohlcv_symbol_count": 1,
            "taxonomy_symbol_count": 1,
            "covered_symbols": ["BTCUSDC"],
            "missing_in_taxonomy": [],
            "orphan_in_taxonomy": [],
            "coverage_pct": 100.0,
        },
    )
    stub_path = tmp_path / "stub.json"
    exit_code = audit.main(["--emit-stub", "--stub-path", str(stub_path)])
    assert exit_code == 0
    # Pas de missing → pas de stub écrit
    assert not stub_path.exists()
