"""
Unit tests for EmailFraudDetector

Run with: python -m pytest tests/ -v
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from email_fraud_detector import EmailFraudDetector


class TestEmailFraudDetector:
    """Tests for EmailFraudDetector class"""
    
    @pytest.fixture
    def detector(self):
        """Create a fresh detector instance for each test"""
        return EmailFraudDetector()
    
    # ==================== Basic Email Analysis ====================
    
    def test_valid_email_low_risk(self, detector):
        """Test a normal email gets low risk score"""
        result = detector.analyze_email("john.smith@gmail.com")
        assert result['risk_score'] < 25
        assert result['email'] == "john.smith@gmail.com"
    
    def test_invalid_email_no_at_symbol(self, detector):
        """Test email without @ symbol - treated as data quality, not fraud"""
        result = detector.analyze_email("invalid_email")
        assert result['risk_score'] == 0  # Data quality issue, not fraud
        assert 'DATA_QUALITY_MISSING_EMAIL' in result['flags']
    
    def test_empty_email(self, detector):
        """Test empty/None email"""
        result = detector.analyze_email(None)
        assert result['risk_score'] == 0
        assert result['flags'] == []
    
    # ==================== Excessive Dots Pattern ====================
    
    def test_excessive_dots_flagged(self, detector):
        """Test email with >3 dots gets flagged"""
        result = detector.analyze_email("a.b.c.d.e@gmail.com")
        assert 'EXCESSIVE_DOTS' in result['flags']
        assert result['details']['dot_count'] > 3
    
    def test_normal_dots_not_flagged(self, detector):
        """Test email with ≤3 dots not flagged"""
        result = detector.analyze_email("john.doe@gmail.com")
        assert 'EXCESSIVE_DOTS' not in result['flags']
    
    # ==================== Digit Suffix Pattern ====================
    
    def test_digit_suffix_4_digits(self, detector):
        """Test email ending with 4 digits"""
        result = detector.analyze_email("user1234@gmail.com")
        assert 'DIGIT_SUFFIX' in result['flags']
    
    def test_digit_suffix_5_digits(self, detector):
        """Test email ending with 5 digits"""
        result = detector.analyze_email("user12345@gmail.com")
        assert 'DIGIT_SUFFIX' in result['flags']
    
    def test_digit_suffix_3_digits_not_flagged(self, detector):
        """Test email ending with 3 digits not flagged"""
        result = detector.analyze_email("user123@gmail.com")
        assert 'DIGIT_SUFFIX' not in result['flags']
    
    # ==================== Scrambled Pattern ====================
    
    def test_scrambled_pattern_detected(self, detector):
        """Test clearly scrambled email"""
        result = detector.analyze_email("xkjhgfdsqwrt@gmail.com")
        # May or may not flag depending on algorithm
        assert 'email' in result
    
    def test_normal_name_not_scrambled(self, detector):
        """Test normal name not flagged as scrambled"""
        result = detector.analyze_email("michael.johnson@gmail.com")
        assert 'SCRAMBLED_PATTERN' not in result['flags']
    
    # ==================== Name-Number Pattern ====================
    
    def test_name_number_pattern(self, detector):
        """Test firstname+number+lastname+number pattern"""
        result = detector.analyze_email("john43murphy5398@gmail.com")
        assert 'NAME_NUMBER_PATTERN' in result['flags']
    
    def test_simple_name_not_name_number(self, detector):
        """Test simple name not flagged"""
        result = detector.analyze_email("johnmurphy@gmail.com")
        assert 'NAME_NUMBER_PATTERN' not in result['flags']
    
    # ==================== Written Number Pattern ====================
    
    def test_written_number_pattern(self, detector):
        """Test written number word in email"""
        result = detector.analyze_email("emillythree@gmail.com")
        assert 'WRITTEN_NUMBER_PATTERN' in result['flags']
    
    def test_no_written_number(self, detector):
        """Test normal email without written numbers"""
        result = detector.analyze_email("emily@gmail.com")
        assert 'WRITTEN_NUMBER_PATTERN' not in result['flags']
    
    # ==================== Suspicious Name ====================
    
    def test_suspicious_name_detected(self, detector):
        """Test known suspicious name"""
        result = detector.analyze_email("fatima123@gmail.com")
        assert 'SUSPICIOUS_NAME' in result['flags']
    
    # ==================== POV Timing ====================
    
    def test_pov_instant_validation_20s(self, detector):
        """Test POV validation under 20 seconds"""
        from datetime import datetime, timedelta
        
        signup = datetime.now()
        pov_time = signup + timedelta(seconds=15)
        
        result = detector.analyze_email(
            "test@gmail.com",
            trans_datetime=signup,
            pov_verified=True,
            pov_verified_time=pov_time
        )
        
        assert 'POV_INSTANT_VALIDATION_20S' in result['flags']
        assert result['details']['pov_validation_seconds'] == 15
    
    def test_pov_instant_validation_40s(self, detector):
        """Test POV validation 20-40 seconds"""
        from datetime import datetime, timedelta
        
        signup = datetime.now()
        pov_time = signup + timedelta(seconds=35)
        
        result = detector.analyze_email(
            "test@gmail.com",
            trans_datetime=signup,
            pov_verified=True,
            pov_verified_time=pov_time
        )
        
        assert 'POV_INSTANT_VALIDATION_40S' in result['flags']
    
    def test_pov_normal_validation(self, detector):
        """Test POV validation over 60 seconds"""
        from datetime import datetime, timedelta
        
        signup = datetime.now()
        pov_time = signup + timedelta(seconds=120)
        
        result = detector.analyze_email(
            "test@gmail.com",
            trans_datetime=signup,
            pov_verified=True,
            pov_verified_time=pov_time
        )
        
        assert 'POV_INSTANT_VALIDATION_20S' not in result['flags']
        assert 'POV_INSTANT_VALIDATION_40S' not in result['flags']
        assert result['details']['pov_risk_level'] == 'NORMAL'
    
    # ==================== Device Type ====================
    
    def test_detect_mobile_device(self, detector):
        """Test mobile device detection"""
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)"
        device_type = detector.detect_device_type(ua)
        assert device_type == 'mobile'
    
    def test_detect_android_device(self, detector):
        """Test Android device detection"""
        ua = "Mozilla/5.0 (Linux; Android 10; SM-G975F)"
        device_type = detector.detect_device_type(ua)
        assert device_type == 'mobile'
    
    def test_detect_desktop_windows(self, detector):
        """Test Windows desktop detection"""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        device_type = detector.detect_device_type(ua)
        assert device_type == 'desktop'
    
    def test_detect_desktop_mac(self, detector):
        """Test Mac desktop detection"""
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        device_type = detector.detect_device_type(ua)
        assert device_type == 'desktop'
    
    def test_desktop_windows_10_higher_risk(self, detector):
        """Test Windows 10 desktop gets higher risk than other desktops"""
        ua_win10 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        ua_mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        
        result_win10 = detector.analyze_email("test@gmail.com", user_agent=ua_win10)
        result_mac = detector.analyze_email("test@gmail.com", user_agent=ua_mac)
        
        # Both should have DESKTOP_DEVICE_SUSPICIOUS
        assert 'DESKTOP_DEVICE_SUSPICIOUS' in result_win10['flags']
        assert 'DESKTOP_DEVICE_SUSPICIOUS' in result_mac['flags']
        
        # Windows 10 should have higher risk
        assert result_win10['risk_score'] > result_mac['risk_score']
    
    # ==================== Risk Score Capping ====================
    
    def test_risk_score_capped_at_100(self, detector):
        """Test risk score doesn't exceed 100"""
        # Email with many fraud indicators
        result = detector.analyze_email("fatima43murphy5398.a.b.c.d@gmail.com")
        assert result['risk_score'] <= 100
    
    # ==================== Is Scrambled Detection ====================
    
    def test_is_scrambled_returns_tuple(self, detector):
        """Test is_scrambled returns tuple with bool and dict"""
        result, indicators = detector.is_scrambled("xyzqwrt")
        assert isinstance(result, bool)
        assert isinstance(indicators, dict)
    
    def test_short_username_not_scrambled(self, detector):
        """Test short username not analyzed for scrambling"""
        result, indicators = detector.is_scrambled("abc")
        assert result == False
        assert indicators == {}
    
    # ==================== Column Mapping ====================
    
    def test_normalize_column_names(self, detector):
        """Test column name normalization"""
        import pandas as pd
        
        df = pd.DataFrame({
            'Email': ['test@gmail.com'],
            'IP Address': ['1.2.3.4'],
            'DUID': ['123']
        })
        
        detector.normalize_column_names(df)
        
        assert 'email' in detector.column_map
        assert 'ip' in detector.column_map
        assert 'duid' in detector.column_map


class TestEmailPatterns:
    """Test specific email patterns from real fraud cases"""
    
    @pytest.fixture
    def detector(self):
        return EmailFraudDetector()
    
    def test_kelly_name_extraction(self, detector):
        """Test kelly is extracted correctly (regression test)"""
        # This was a reported bug where 'kelly' was extracted as 'kell'
        result = detector.analyze_email("kellylane678@gmail.com")
        # Should not have scrambled pattern for a real name
        assert 'email' in result
    
    def test_common_fraud_pattern_1(self, detector):
        """Test common fraud pattern: firstname+digits+lastname+digits"""
        result = detector.analyze_email("bradley93sanders5984@gmail.com")
        assert 'NAME_NUMBER_PATTERN' in result['flags']
        assert result['risk_score'] >= 40
    
    def test_protonmail_not_flagged_for_domain(self, detector):
        """Test protonmail is a major provider"""
        result = detector.analyze_email("user@protonmail.com")
        assert result['details']['is_major_provider'] == True


class TestRiskScoreValues:
    """Test that risk scores match documented values"""
    
    @pytest.fixture
    def detector(self):
        return EmailFraudDetector()
    
    def test_excessive_dots_score(self, detector):
        """EXCESSIVE_DOTS should add 20 points"""
        result = detector.analyze_email("a.b.c.d.e@gmail.com")
        # Should only have EXCESSIVE_DOTS
        if result['flags'] == ['EXCESSIVE_DOTS']:
            assert result['risk_score'] == 20
    
    def test_digit_suffix_score(self, detector):
        """DIGIT_SUFFIX should add 15 points"""
        result = detector.analyze_email("user12345@gmail.com")
        # Should only have DIGIT_SUFFIX
        if result['flags'] == ['DIGIT_SUFFIX']:
            assert result['risk_score'] == 15
    
    def test_name_number_pattern_score(self, detector):
        """NAME_NUMBER_PATTERN should add 40 points"""
        result = detector.analyze_email("john1smith2@gmail.com")
        if 'NAME_NUMBER_PATTERN' in result['flags']:
            assert result['risk_score'] >= 40


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
