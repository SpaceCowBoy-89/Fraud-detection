"""Tests for exportable fraud flag reference catalog."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fraud_flags_reference import (
    catalog_path,
    enrich_catalog,
    export_csv,
    export_json,
    export_markdown,
    load_catalog,
)


def test_catalog_file_exists_and_valid():
    path = catalog_path()
    assert path.is_file()
    data = load_catalog(path)
    assert data.get("version") >= 1
    assert len(data.get("flags", [])) >= 20


def test_enrich_adds_resolved_points_and_explanation():
    cat = load_catalog()
    enriched = enrich_catalog(cat, {"excessive_dots": 99})
    row = next(f for f in enriched["flags"] if f["catalog_key"] == "EXCESSIVE_DOTS")
    assert "99 pts" in row["resolved_points"]
    assert row.get("explanation")
    assert row.get("score_tiers_resolved")


def test_export_csv_has_header_and_bom():
    cat = enrich_catalog(load_catalog(), {})
    raw = export_csv(cat).decode("utf-8-sig")
    lines = raw.strip().splitlines()
    assert "catalog_key" in lines[0]
    assert "AFFILIATE_DOMAIN_CONCENTRATION" in raw


def test_export_json_roundtrip():
    cat = enrich_catalog(load_catalog(), {})
    payload = json.loads(export_json(cat).decode("utf-8"))
    assert payload["flags"][0]["resolved_points"] is not None


def test_export_markdown_contains_sections():
    cat = enrich_catalog(load_catalog(), {})
    md = export_markdown(cat).decode("utf-8")
    assert "# Fraud detection flags" in md
    assert "AFFILIATE_DOMAIN_CONCENTRATION" in md
    assert "Why it matters" in md
    assert "How scoring works" in md


def test_main_cli_writes_csv(tmp_path):
    from fraud_flags_reference import main

    out = tmp_path / "out.csv"
    assert main(["-f", "csv", "-o", str(out)]) == 0
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
