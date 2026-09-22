"""Cache-only IP geo lookups during batch scoring."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

from email_fraud_detector import EmailFraudDetector


def test_get_ip_geolocation_skips_network_by_default():
    d = EmailFraudDetector()
    assert d.ip_geolocation_live_lookups is False
    t0 = time.time()
    assert d.get_ip_geolocation('8.8.8.8') is None
    assert time.time() - t0 < 0.25


def test_get_ip_geolocation_returns_cache():
    d = EmailFraudDetector()
    d.ip_geolocation_cache['8.8.8.8'] = {
        'country_code': 'US',
        'region': 'CA',
        'city': 'Mountain View',
    }
    geo = d.get_ip_geolocation('8.8.8.8')
    assert geo['country_code'] == 'US'
