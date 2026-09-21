"""Tests for Apple private relay exemptions and affiliate domain concentration."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from email_fraud_detector import EmailFraudDetector


SCRAMBLED_GMAIL = 'xkjhgfdsqwrt@gmail.com'
SCRAMBLED_YAHOO = 'bcdfghjklmnp@yahoo.com'
APPLE_RELAY = '7t7ck2nn7b@privaterelay.appleid.com'
PHONE_REG = 'pending-abc123@phone-registration.invalid'
PHONE_REG_SCRAMBLED = 'pending-xkjhgfdsqwrt@phone-registration.invalid'


@pytest.fixture
def detector():
    return EmailFraudDetector()


class TestApplePrivateRelay:
    def test_apple_relay_not_scrambled(self, detector):
        result = detector.analyze_email(APPLE_RELAY)
        assert 'SCRAMBLED_PATTERN' not in result['flags']
        assert result['details'].get('is_privacy_relay') is True

    def test_scrambled_gmail_still_flagged(self, detector):
        result = detector.analyze_email(SCRAMBLED_GMAIL)
        assert 'SCRAMBLED_PATTERN' in result['flags']
        assert result['details'].get('is_privacy_relay') is not True

    def test_scrambled_yahoo_still_flagged(self, detector):
        result = detector.analyze_email(SCRAMBLED_YAHOO)
        assert 'SCRAMBLED_PATTERN' in result['flags']

    def test_apple_relay_skips_local_part_rules(self, detector):
        """Provider-generated relay addresses should not hit username heuristics."""
        result = detector.analyze_email('fatima12345@privaterelay.appleid.com')
        local_part_flags = {
            'SCRAMBLED_PATTERN', 'DIGIT_SUFFIX', 'SUSPICIOUS_NAME',
            'NAME_NUMBER_PATTERN', 'EXCESSIVE_DOTS', 'WRITTEN_NUMBER_PATTERN',
        }
        assert local_part_flags.isdisjoint(set(result['flags']))


class TestPhoneRegistrationPlaceholder:
    def test_phone_registration_not_scrambled(self, detector):
        result = detector.analyze_email(PHONE_REG_SCRAMBLED)
        assert 'SCRAMBLED_PATTERN' not in result['flags']
        assert result['details'].get('is_privacy_relay') is True

    def test_phone_registration_skips_local_part_rules(self, detector):
        """System-generated pending-* addresses should not hit username heuristics."""
        samples = [
            'pending-xkjhgfdsqwrt@phone-registration.invalid',
            'pending-fatima123@phone-registration.invalid',
            'pending-john43murphy5398@phone-registration.invalid',
            'pending-emillythree@phone-registration.invalid',
        ]
        local_part_flags = {
            'SCRAMBLED_PATTERN', 'DIGIT_SUFFIX', 'SUSPICIOUS_NAME',
            'NAME_NUMBER_PATTERN', 'EXCESSIVE_DOTS', 'WRITTEN_NUMBER_PATTERN',
        }
        for email in samples:
            result = detector.analyze_email(email)
            assert local_part_flags.isdisjoint(set(result['flags'])), email

    def test_phone_registration_excluded_from_domain_concentration(self):
        detector = EmailFraudDetector()
        rows = [
            {
                'email': f'pending-code{i}@phone-registration.invalid',
                'webmaster_code': 'aff1',
                'duid': str(i),
                'custom_u1': 'MAN',
            }
            for i in range(25)
        ]
        df = pd.DataFrame(rows)
        detector.normalize_column_names(df)
        detector.build_affiliate_domain_concentration_map(df)
        assert not detector.affiliate_domain_concentration_flags

        results = [
            detector.analyze_email(r['email']) | {
                'webmaster_code': r['webmaster_code'],
                'email': r['email'],
            }
            for r in rows
        ]
        detector.apply_affiliate_domain_concentration_to_results(results)
        assert all('AFFILIATE_DOMAIN_CONCENTRATION' not in r['flags'] for r in results)


def _make_domain_concentration_df():
    """Affiliate aff1: 20 gmail + 2 nerd.com (9.09% nerd.com, triggers at 5%)."""
    rows = []
    for i in range(20):
        rows.append({
            'email': f'user{i}@gmail.com',
            'webmaster_code': 'aff1',
            'duid': f'g{i}',
            'custom_u1': 'MAN',
        })
    for i in range(2):
        rows.append({
            'email': f'user{i}@nerd.com',
            'webmaster_code': 'aff1',
            'duid': f'p{i}',
            'custom_u1': 'MAN',
        })
    return pd.DataFrame(rows)


class TestAffiliateDomainConcentration:
    def test_build_map_flags_non_gmail_above_threshold(self):
        detector = EmailFraudDetector()
        df = _make_domain_concentration_df()
        detector.normalize_column_names(df)
        detector.build_affiliate_domain_concentration_map(df)

        assert ('aff1', 'nerd.com') in detector.affiliate_domain_concentration_flags
        assert ('aff1', 'gmail.com') not in detector.affiliate_domain_concentration_flags
        info = detector.affiliate_domain_concentration_flags[('aff1', 'nerd.com')]
        assert info['pct'] >= 5.0
        assert info['count'] == 2
        assert info['total'] == 22

    def test_apply_flags_only_concentrated_domain_rows(self):
        detector = EmailFraudDetector()
        df = _make_domain_concentration_df()
        detector.normalize_column_names(df)
        detector.build_affiliate_domain_concentration_map(df)

        results = []
        for _, row in df.iterrows():
            analysis = detector.analyze_email(row['email'])
            analysis['webmaster_code'] = row['webmaster_code']
            analysis['DUID'] = row['duid']
            results.append(analysis)

        detector.apply_affiliate_domain_concentration_to_results(results)

        concentrated = [r for r in results if r['email'].endswith('@nerd.com')]
        gmail = [r for r in results if r['email'].endswith('@gmail.com')]

        assert all('AFFILIATE_DOMAIN_CONCENTRATION' in r['flags'] for r in concentrated)
        assert all('AFFILIATE_DOMAIN_CONCENTRATION' not in r['flags'] for r in gmail)

    def test_gmail_excluded_from_concentration(self):
        """gmail.com is excluded from concentration monitoring even at 100%."""
        detector = EmailFraudDetector()
        df = pd.DataFrame([
            {'email': f'u{i}@gmail.com', 'webmaster_code': 'aff2', 'duid': str(i)}
            for i in range(25)
        ])
        detector.normalize_column_names(df)
        detector.build_affiliate_domain_concentration_map(df)
        assert not any(domain == 'gmail.com' for (_aff, domain) in detector.affiliate_domain_concentration_flags)

    def test_major_provider_can_be_flagged(self):
        """Protonmail is not excluded — 20% share triggers at 5% threshold."""
        detector = EmailFraudDetector()
        rows = []
        for i in range(20):
            rows.append({'email': f'u{i}@gmail.com', 'webmaster_code': 'aff4', 'duid': str(i)})
        for i in range(5):
            rows.append({'email': f'p{i}@protonmail.com', 'webmaster_code': 'aff4', 'duid': f'p{i}'})
        df = pd.DataFrame(rows)
        detector.normalize_column_names(df)
        detector.build_affiliate_domain_concentration_map(df)
        assert ('aff4', 'protonmail.com') in detector.affiliate_domain_concentration_flags

    def test_below_threshold_not_flagged(self):
        """1 nerd.com out of 25 (4%) should not trigger at 5% threshold."""
        detector = EmailFraudDetector()
        rows = [
            {'email': f'u{i}@gmail.com', 'webmaster_code': 'aff3', 'duid': str(i)}
            for i in range(24)
        ]
        rows.append({'email': 'solo@nerd.com', 'webmaster_code': 'aff3', 'duid': 'solo'})
        df = pd.DataFrame(rows)
        detector.normalize_column_names(df)
        detector.build_affiliate_domain_concentration_map(df)
        assert ('aff3', 'nerd.com') not in detector.affiliate_domain_concentration_flags
