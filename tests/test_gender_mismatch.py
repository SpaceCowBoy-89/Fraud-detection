"""Tests for billing gender mismatch detection"""
import pytest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.email_fraud_detector import (
    EmailFraudDetector,
    GENDER_DETECTOR_AVAILABLE,
    parse_fraud_results_flags,
    parse_fraud_results_details,
    rescore_woman_concentration_from_fraud_results_table,
)


@pytest.mark.skipif(not GENDER_DETECTOR_AVAILABLE, reason="gender-guesser not installed")
def test_email_name_extraction():
    """Extract plausible first names from email local-parts."""
    detector = EmailFraudDetector()

    assert 'Pamela' in detector.extract_name_candidates_from_username('pamelabrown22')
    assert detector.extract_name_candidates_from_username('john.smith123')[0] == 'John'
    assert detector.extract_name_candidates_from_username('mary_johnson')[0] == 'Mary'
    assert detector.extract_name_candidates_from_username('123xyz') == []


@pytest.mark.skipif(not GENDER_DETECTOR_AVAILABLE, reason="gender-guesser not installed")
def test_email_gender_mismatch_detection():
    """Email username female name + declared man should mismatch."""
    detector = EmailFraudDetector()

    result = detector.check_email_gender_mismatch('pamelabrown22@gmail.com', 'man')
    assert result['mismatch'] is True
    assert result['predicted_gender'] == 'female'
    assert result['declared_gender'] == 'male'
    assert result.get('extracted_name')

    result = detector.check_email_gender_mismatch('johndoe@example.com', 'woman')
    assert result['mismatch'] is True
    assert result['predicted_gender'] == 'male'

    result = detector.check_email_gender_mismatch('sarahsmith@example.com', 'woman')
    assert result['mismatch'] is False


@pytest.mark.skipif(not GENDER_DETECTOR_AVAILABLE, reason="gender-guesser not installed")
def test_email_gender_mismatch_in_fraud_analysis():
    """GENDER_NAME_MISMATCH flag on free-style signups without billing name."""
    detector = EmailFraudDetector()

    result = detector.analyze_email(
        email='pamelabrown22@gmail.com',
        user1='man',
    )
    assert 'GENDER_NAME_MISMATCH' in result['flags']
    assert 'BILLING_GENDER_MISMATCH' not in result['flags']
    assert result['risk_score'] >= 35
    assert 'email_gender_mismatch' in result['details']
    assert result['details']['email_gender_mismatch']['predicted_gender'] == 'female'

    result_ok = detector.analyze_email(
        email='michaelbrown@example.com',
        user1='man',
    )
    assert 'GENDER_NAME_MISMATCH' not in result_ok['flags']


@pytest.mark.skipif(not GENDER_DETECTOR_AVAILABLE, reason="gender-guesser not installed")
def test_email_gender_skipped_when_billing_mismatch_present():
    """Avoid double-scoring when billing name already mismatches."""
    detector = EmailFraudDetector()

    result = detector.analyze_email(
        email='pamelabrown22@gmail.com',
        first_name='Patricia',
        user1='man',
    )
    assert 'BILLING_GENDER_MISMATCH' in result['flags']
    assert 'GENDER_NAME_MISMATCH' not in result['flags']


@pytest.mark.skipif(not GENDER_DETECTOR_AVAILABLE, reason="gender-guesser not installed")
def test_gender_mismatch_detection():
    """Test that gender mismatches are correctly detected"""
    detector = EmailFraudDetector()
    
    # Test case 1: Clear mismatch - Female name, male declared
    result = detector.check_gender_mismatch('Patricia', 'man')
    assert result['mismatch'] == True
    assert result['predicted_gender'] == 'female'
    assert result['declared_gender'] == 'male'
    
    # Test case 2: Clear mismatch - Male name, female declared
    result = detector.check_gender_mismatch('John', 'woman')
    assert result['mismatch'] == True
    assert result['predicted_gender'] == 'male'
    assert result['declared_gender'] == 'female'
    
    # Test case 3: Match - Female name, female declared
    result = detector.check_gender_mismatch('Sarah', 'woman')
    assert result['mismatch'] == False
    assert result['predicted_gender'] == 'female'
    assert result['declared_gender'] == 'female'
    
    # Test case 4: Match - Male name, male declared
    result = detector.check_gender_mismatch('Michael', 'man')
    assert result['mismatch'] == False
    assert result['predicted_gender'] == 'male'
    assert result['declared_gender'] == 'male'


@pytest.mark.skipif(not GENDER_DETECTOR_AVAILABLE, reason="gender-guesser not installed")
def test_gender_mismatch_edge_cases():
    """Test edge cases in gender detection"""
    detector = EmailFraudDetector()
    
    # No first name
    result = detector.check_gender_mismatch(None, 'man')
    assert result['mismatch'] == False
    assert result.get('reason') == 'no_data'
    
    # No declared gender
    result = detector.check_gender_mismatch('John', None)
    assert result['mismatch'] == False
    assert result.get('reason') == 'no_declared_gender'
    
    # Androgynous name (or library classifies as matching declared gender)
    result = detector.check_gender_mismatch('Alex', 'man')
    assert result['mismatch'] == False
    assert result.get('reason') in ('androgynous_name', None)
    
    # Unknown name
    result = detector.check_gender_mismatch('Xyz', 'man')
    assert result['mismatch'] == False
    assert result.get('reason') in ['unknown_name', 'androgynous_name']


@pytest.mark.skipif(not GENDER_DETECTOR_AVAILABLE, reason="gender-guesser not installed")
def test_gender_mismatch_in_fraud_analysis():
    """Test that gender mismatch adds risk score in full analysis"""
    detector = EmailFraudDetector()
    
    # Analyze with gender mismatch
    result = detector.analyze_email(
        email='test@example.com',
        first_name='Patricia',
        user1='man'
    )
    
    assert 'BILLING_GENDER_MISMATCH' in result['flags']
    assert result['risk_score'] >= 35  # Should have at least the mismatch score
    assert 'gender_mismatch' in result['details']
    assert result['details']['gender_mismatch']['predicted_gender'] == 'female'
    assert result['details']['gender_mismatch']['declared_gender'] == 'male'
    
    # Analyze without mismatch
    result_no_mismatch = detector.analyze_email(
        email='test@example.com',
        first_name='Patricia',
        user1='woman'
    )
    
    assert 'BILLING_GENDER_MISMATCH' not in result_no_mismatch['flags']


@pytest.mark.skipif(not GENDER_DETECTOR_AVAILABLE, reason="gender-guesser not installed")
def test_gender_normalization():
    """Test that various gender inputs are normalized correctly"""
    detector = EmailFraudDetector()
    
    # Test male variations
    for male_variant in ['man', 'male', 'm', 'Man', 'MALE']:
        result = detector.check_gender_mismatch('Patricia', male_variant)
        assert result['mismatch'] == True
        assert result['declared_gender'] == 'male'
    
    # Test female variations
    for female_variant in ['woman', 'female', 'f', 'Woman', 'FEMALE']:
        result = detector.check_gender_mismatch('John', female_variant)
        assert result['mismatch'] == True
        assert result['declared_gender'] == 'female'


def test_woman_concentration_applied_to_results():
    """Concentrated-affiliate WOMAN rows get WOMAN_CONCENTRATION before DB save (CLI/dashboard path)."""
    detector = EmailFraudDetector()
    detector.gender_concentration_flags = {
        'badaff': {'woman_pct': 50.0, 'women': 10, 'total': 20},
    }
    results = [
        {
            'email': 'a@test.com',
            'webmaster_code': 'badaff',
            'custom_u1': 'WOMAN',
            'risk_score': 10,
            'flags': [],
            'details': {},
        },
        {
            'email': 'b@test.com',
            'webmaster_code': 'badaff',
            'custom_u1': 'MAN',
            'risk_score': 10,
            'flags': [],
            'details': {},
        },
        {
            'email': 'c@test.com',
            'webmaster_code': 'good',
            'custom_u1': 'WOMAN',
            'risk_score': 10,
            'flags': [],
            'details': {},
        },
    ]
    detector.apply_gender_concentration_to_results(results)
    assert 'WOMAN_CONCENTRATION' in results[0]['flags']
    assert results[0]['details'].get('woman_concentration', {}).get('affiliate') == 'badaff'
    assert 'WOMAN_CONCENTRATION' not in results[1]['flags']
    assert 'WOMAN_CONCENTRATION' not in results[2]['flags']


def test_woman_concentration_apply_is_idempotent():
    detector = EmailFraudDetector()
    detector.gender_concentration_flags = {
        'badaff': {'woman_pct': 50.0, 'women': 10, 'total': 20},
    }
    results = [
        {
            'email': 'a@test.com',
            'webmaster_code': 'badaff',
            'custom_u1': 'WOMAN',
            'risk_score': 10,
            'flags': [],
            'details': {},
        }
    ]
    detector.apply_gender_concentration_to_results(results)
    rs_after_first = results[0]['risk_score']
    detector.apply_gender_concentration_to_results(results)
    assert results[0]['risk_score'] == rs_after_first
    assert results[0]['flags'].count('WOMAN_CONCENTRATION') == 1


def test_parse_fraud_results_flags_and_details():
    assert parse_fraud_results_flags("['A', 'B']") == ['A', 'B']
    assert parse_fraud_results_flags('[]') == []
    assert parse_fraud_results_details("{'a': 1}") == {'a': 1}
    assert parse_fraud_results_details('{}') == {}


def test_rescore_woman_concentration_integration(tmp_path):
    import sqlite3
    from database import Database

    dbp = str(tmp_path / 'rw.db')
    db = Database(dbp)
    with sqlite3.connect(dbp) as conn:
        for i in range(25):
            conn.execute(
                """INSERT INTO fraud_results (
                       duid, email, risk_score, flags, details, data_type,
                       webmaster_code, custom_u1
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(100000 + i),
                    f'u{i}@x.com',
                    5,
                    '[]',
                    '{}',
                    'free',
                    'concaff',
                    'WOMAN',
                ),
            )
        conn.commit()

    out1 = rescore_woman_concentration_from_fraud_results_table(db)
    assert out1['updated'] == 25
    assert 'concaff' in (out1.get('affiliates') or [])

    out2 = rescore_woman_concentration_from_fraud_results_table(db)
    assert out2['updated'] == 0


def test_gender_detector_available():
    """Test that we know whether gender detector is available"""
    # This test always runs
    assert isinstance(GENDER_DETECTOR_AVAILABLE, bool)
    
    if GENDER_DETECTOR_AVAILABLE:
        detector = EmailFraudDetector()
        assert detector.gender_detector is not None
    else:
        print("Note: gender-guesser not installed, BILLING_GENDER_MISMATCH detection disabled")
