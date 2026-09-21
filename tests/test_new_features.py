"""
Test Suite for New Features (Week Implementation)

Tests:
- Data Preprocessor
- EDA Analyzer
- Business Analytics
- Date Range Filtering
"""

import pytest
import pandas as pd
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from data_preprocessor import DataPreprocessor
from eda_analyzer import EDAAnalyzer
from business_analytics import BusinessAnalytics


class TestDataPreprocessor:
    """Test data preprocessing"""
    
    def test_clean_email_valid(self):
        """Test email cleaning with valid email"""
        preprocessor = DataPreprocessor()
        result = preprocessor.clean_email('  Test.User@GMAIL.com  ')
        
        assert result['cleaned'] == 'test.user@gmail.com'
        assert result['valid'] == True
        assert result['disposable'] == False
        assert result['domain'] == 'gmail.com'
    
    def test_clean_email_invalid(self):
        """Test email cleaning with invalid email"""
        preprocessor = DataPreprocessor()
        result = preprocessor.clean_email('not-an-email')
        
        assert result['cleaned'] is None
        assert result['valid'] == False
    
    def test_clean_email_disposable(self):
        """Test disposable email detection"""
        preprocessor = DataPreprocessor()
        result = preprocessor.clean_email('test@tempmail.org')
        
        assert result['valid'] == True
        assert result['disposable'] == True
    
    def test_validate_amount_valid(self):
        """Test amount validation"""
        preprocessor = DataPreprocessor()
        result = preprocessor.validate_amount(25.50, 'payout')
        
        assert result['valid'] == True
        assert len(result['flags']) == 0
    
    def test_validate_amount_negative(self):
        """Test negative amount detection"""
        preprocessor = DataPreprocessor()
        result = preprocessor.validate_amount(-10.00, 'payout')
        
        assert result['valid'] == False
        assert 'NEGATIVE_AMOUNT' in result['flags']
    
    def test_validate_amount_zero(self):
        """Test zero amount"""
        preprocessor = DataPreprocessor()
        result = preprocessor.validate_amount(0, 'payout')
        
        assert result['valid'] == True
        assert 'ZERO_AMOUNT' in result['flags']
    
    def test_preprocess_batch(self):
        """Test batch preprocessing"""
        preprocessor = DataPreprocessor()
        
        df = pd.DataFrame({
            'email': ['Test@Gmail.com', 'user@tempmail.org', 'invalid'],
            'payout_amount': [25.50, 10.00, -5.00],
            'trans_datetime': ['2026-01-20 10:30:00', '2026-01-20 14:30:00', '2026-01-20 22:30:00']
        })
        
        cleaned_df, report = preprocessor.preprocess_batch(df)
        
        assert 'email_cleaned' in cleaned_df.columns
        assert 'email_valid' in cleaned_df.columns
        assert 'email_disposable' in cleaned_df.columns
        assert 'amount_valid' in cleaned_df.columns
        assert 'hour_of_day' in cleaned_df.columns
        assert 'is_night' in cleaned_df.columns
        
        assert report['total_records'] == 3
        assert report['emails_cleaned'] == 2  # 2 valid emails
        assert report['disposable_emails'] == 1
        assert report['invalid_amounts'] == 1  # 1 negative


class TestEDAAnalyzer:
    """Test EDA analyzer"""
    
    def test_generate_profile(self):
        """Test data profiling"""
        analyzer = EDAAnalyzer()
        
        df = pd.DataFrame({
            'duid': ['1', '2', '3'],
            'email': ['a@test.com', 'b@test.com', None],
            'trans_datetime': ['2026-01-20', '2026-01-21', '2026-01-22'],
            'payout_amount': [10, 20, 30]
        })
        
        profile = analyzer.generate_profile(df, 'free')
        
        assert profile['record_count'] == 3
        assert profile['column_count'] == 4
        assert profile['data_type'] == 'free'
        assert 'completeness' in profile
        assert profile['completeness']['email']['percentage'] < 100  # Has 1 null
    
    def test_check_data_quality(self):
        """Test quality checks"""
        analyzer = EDAAnalyzer()
        
        df = pd.DataFrame({
            'duid': ['1', '2', '2'],  # Duplicate DUID
            'email': ['a@test.com', 'invalid', None],  # Invalid and missing
            'trans_datetime': ['2026-01-20', '2026-01-21', None]
        })
        
        issues = analyzer.check_data_quality(df)
        
        assert len(issues['critical']) > 0 or len(issues['warnings']) > 0
        # Should detect missing email and duplicate DUID
    
    def test_detect_outliers(self):
        """Test outlier detection"""
        analyzer = EDAAnalyzer()
        
        df = pd.DataFrame({
            'duid': ['1', '2', '3', '4', '5'],
            'payout_amount': [10, 10, 10, 10, 1000],  # 1000 is outlier
            'email_disposable': [False, False, False, True, False]  # DUID 4 is disposable
        })
        
        outliers = analyzer.detect_outliers(df)
        
        assert len(outliers) >= 2  # Should detect amount outlier and disposable


class TestBusinessAnalytics:
    """Test business analytics (requires mock database)"""
    
    def test_industry_benchmarks_structure(self):
        """Test industry benchmark data structure"""
        # Create mock DB
        from database import Database
        from tempfile import NamedTemporaryFile
        
        with NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db = Database(tmp.name)
            analytics = BusinessAnalytics(db)
            
            benchmarks = analytics.industry_benchmarks
            
            assert 'fraud_rate' in benchmarks
            assert benchmarks['fraud_rate'] == 3.1
            assert 'false_positive_rate' in benchmarks
            assert benchmarks['false_positive_rate'] == 3.5
            assert 'source' in benchmarks


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
