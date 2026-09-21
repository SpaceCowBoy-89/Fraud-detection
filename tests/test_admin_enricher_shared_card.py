"""Shared-card whitelist behavior in admin enrichment."""

import json
import tempfile
from pathlib import Path

import pytest

from config import Config
from scripts.admin_enricher import AdminEnricher


@pytest.fixture
def enricher_with_whitelist():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "whitelisted_card_fingerprints": ["test_card_fp_abc"],
                    "whitelisted_duids": ["999001"],
                    "risk_scores": {},
                }
            )
        )
        config = Config(str(cfg_path))
        e = AdminEnricher(config=config, client=object())
        yield e


def test_whitelisted_fingerprint_excluded_from_shared_card_count(enricher_with_whitelist):
    data = {
        "user": {},
        "shared_payment_methods": [
            {
                "card_fingerprint": "test_card_fp_abc",
                "other_duids": ["111", "222", "333"],
            },
            {
                "card_fingerprint": "real_card_fp",
                "other_duids": ["444"],
            },
        ],
    }
    out = enricher_with_whitelist._score("100", data)
    assert out["shared_card_count"] == 1
    assert "shared_card_" not in " ".join(out["flags"])


def test_whitelisted_duid_not_counted_as_linked(enricher_with_whitelist):
    data = {
        "user": {},
        "shared_payment_methods": [
            {
                "card_fingerprint": "real_card_fp",
                "other_duids": ["999001", "555"],
            },
        ],
    }
    out = enricher_with_whitelist._score("100", data)
    assert out["shared_card_count"] == 1
