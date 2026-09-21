"""Content review flag helpers and admin enricher integration."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
for p in (ROOT, SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from config import Config  # noqa: E402
from flag_utils import (  # noqa: E402
    content_review_flag_label,
    has_content_review_flag,
    needs_content_review,
)
from scripts.admin_enricher import AdminEnricher  # noqa: E402


def test_needs_content_review_fast_upload():
    assert needs_content_review(True, 60, '[]', fast_seconds=180) is True
    assert needs_content_review(True, 179, '[]', fast_seconds=180) is True
    assert needs_content_review(True, 180, '[]', fast_seconds=180) is False
    assert needs_content_review(True, 500, '[]', fast_seconds=180) is False


def test_needs_content_review_no_pic():
    assert needs_content_review(False, 10, '["NAME_NUMBER_PATTERN"]', fast_seconds=180) is False
    assert needs_content_review(None, None, '["NAME_NUMBER_PATTERN"]', fast_seconds=180) is False
    # fillna('') from pandas leaves empty strings — must not raise int('')
    assert needs_content_review('', '', '["NAME_NUMBER_PATTERN"]', fast_seconds=180) is False
    assert needs_content_review('', 60, '[]', fast_seconds=180) is False


def test_needs_content_review_empty_upload_seconds_with_pic():
    """Uploaded pic but missing seconds (common before enrichment) should not crash."""
    assert needs_content_review(1, '', '[]', fast_seconds=180) is False
    assert needs_content_review(True, '', '["NAME_NUMBER_PATTERN"]', fast_seconds=180) is True


def test_needs_content_review_suspicious_email_flag():
    flags = json.dumps(['NAME_NUMBER_PATTERN', 'EXCESSIVE_DOTS'])
    assert needs_content_review(True, 500, flags, fast_seconds=180) is True
    assert needs_content_review(True, 500, '[]', fast_seconds=180) is False


def test_has_content_review_flag():
    assert has_content_review_flag('["CONTENT_REVIEW"]') is True
    assert has_content_review_flag('["CONTENT_REVIEW(+5)"]') is True
    assert has_content_review_flag('["NAME_NUMBER_PATTERN"]') is False


def test_content_review_flag_label():
    assert content_review_flag_label(0) == 'CONTENT_REVIEW'
    assert content_review_flag_label(5) == 'CONTENT_REVIEW(+5)'


def test_admin_enricher_score_adds_content_review():
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.json"
        cfg_path.write_text(json.dumps({
            "risk_scores": {"content_review": 0},
            "profile_image_fast_seconds": 180,
        }))
        enricher = AdminEnricher(config=Config(str(cfg_path)), client=object())

        data = {
            'user': {
                'registration_timestamp': '2025-01-01 12:00:00',
                'registration_ip': '1.2.3.4',
            },
            'profile_image_upload': {
                'uploaded': True,
                'uploaded_at': '2025-01-01 12:01:00',
            },
            'shared_payment_methods': [],
        }
        out = enricher._score('123', data, existing_flags=['SCRAMBLED_PATTERN'])
        assert 'CONTENT_REVIEW' in out['flags']
        assert out['profile_image_uploaded'] is True
        assert out['profile_image_upload_seconds'] == 60
