"""
Unit tests for Database module

Run with: python -m pytest tests/test_database.py -v
"""

import pytest
import sys
import os
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import Database


class TestDatabase:
    """Tests for Database class"""
    
    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing"""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        db = Database(path)
        yield db
        # Cleanup
        os.unlink(path)
    
    # ==================== Database Setup ====================
    
    def test_database_creates_tables(self, temp_db):
        """Test that all required tables are created"""
        import sqlite3
        
        conn = sqlite3.connect(temp_db.db_path)
        cursor = conn.cursor()
        
        # Get list of tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        
        required_tables = ['free', 'paid', 'fraud_results', 'fetch_history', 
                          'fraud_outcomes', 'affiliate_actions', 'detection_metrics', 'low_risk_samples']
        
        for table in required_tables:
            assert table in tables, f"Table {table} not found"
    
    def test_context_manager_commits(self, temp_db):
        """Test that context manager commits changes"""
        with temp_db.get_connection() as conn:
            conn.execute("INSERT INTO fetch_history (data_type, start_date, end_date, records_fetched) VALUES ('test', '2024-01-01', '2024-01-02', 10)")
        
        # Verify data was committed
        with temp_db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM fetch_history")
            count = cursor.fetchone()[0]
        
        assert count == 1
    
    # ==================== Table Name Validation ====================
    
    def test_valid_table_name(self, temp_db):
        """Test valid table name passes validation"""
        # Should not raise
        temp_db._validate_table_name('free')
        temp_db._validate_table_name('paid')
        temp_db._validate_table_name('fraud_results')
    
    def test_invalid_table_name_raises(self, temp_db):
        """Test invalid table name raises ValueError"""
        with pytest.raises(ValueError):
            temp_db._validate_table_name('invalid_table')
    
    # ==================== Fraud Results ====================
    
    def test_save_and_get_fraud_results(self, temp_db):
        """Test saving and retrieving fraud results"""
        results = [
            {
                'DUID': 'test123',
                'email': 'test@example.com',
                'risk_score': 75,
                'flags': ['HIGH_RISK'],
                'details': {'test': True},
                'payout_amount': 100.50,
                'data_type': 'free'
            }
        ]
        
        temp_db.save_fraud_results(results)
        
        df = temp_db.get_fraud_results()
        
        assert len(df) == 1
        assert df.iloc[0]['duid'] == 'test123'
        assert df.iloc[0]['risk_score'] == 75
    
    def test_get_fraud_results_with_filter(self, temp_db):
        """Test filtering fraud results by risk score"""
        results = [
            {'DUID': 'low1', 'email': 'low@test.com', 'risk_score': 10, 'flags': [], 'details': {}, 'payout_amount': 10, 'data_type': 'free'},
            {'DUID': 'med1', 'email': 'med@test.com', 'risk_score': 30, 'flags': [], 'details': {}, 'payout_amount': 20, 'data_type': 'free'},
            {'DUID': 'high1', 'email': 'high@test.com', 'risk_score': 60, 'flags': [], 'details': {}, 'payout_amount': 30, 'data_type': 'free'},
        ]
        
        temp_db.save_fraud_results(results)
        
        # Get only high risk
        high_risk_df = temp_db.get_fraud_results(min_risk=50)
        assert len(high_risk_df) == 1
        assert high_risk_df.iloc[0]['duid'] == 'high1'
        
        # Get medium and above
        med_plus_df = temp_db.get_fraud_results(min_risk=25)
        assert len(med_plus_df) == 2

    def test_get_fraud_results_no_duplicate_rows_when_duid_in_free_and_paid(self, temp_db):
        """Same duid in free + paid must not Cartesian-merge into multiple rows."""
        with temp_db.get_connection() as conn:
            conn.execute(
                """INSERT INTO fraud_results (duid, email, risk_score, flags, details, payout_amount, data_type)
                   VALUES ('dupuid', 'user@example.com', 80, '[]', '{}', 25, 'paid')"""
            )
            conn.execute(
                """INSERT INTO free (duid, email, trans_datetime, webmaster_code)
                   VALUES ('dupuid', 'user@example.com', '2024-01-01 10:00:00', 'aff_free')"""
            )
            conn.execute(
                """INSERT INTO paid (duid, email, trans_datetime, webmaster_code, payout_amount)
                   VALUES ('dupuid', 'user@example.com', '2024-01-02 11:00:00', 'aff_paid', 25)"""
            )
        df = temp_db.get_fraud_results(min_risk=50)
        assert len(df) == 1
        assert df.iloc[0]['duid'] == 'dupuid'
    
    # ==================== Fraud Statistics ====================
    
    def test_get_fraud_statistics(self, temp_db):
        """Test fraud statistics calculation"""
        results = [
            {'DUID': 'low1', 'email': 'low@test.com', 'risk_score': 10, 'flags': [], 'details': {}, 'payout_amount': 10, 'data_type': 'free'},
            {'DUID': 'med1', 'email': 'med@test.com', 'risk_score': 30, 'flags': [], 'details': {}, 'payout_amount': 20, 'data_type': 'free'},
            {'DUID': 'high1', 'email': 'high@test.com', 'risk_score': 60, 'flags': [], 'details': {}, 'payout_amount': 100, 'data_type': 'free'},
            {'DUID': 'high2', 'email': 'high2@test.com', 'risk_score': 75, 'flags': [], 'details': {}, 'payout_amount': 200, 'data_type': 'free'},
        ]
        
        temp_db.save_fraud_results(results)
        
        stats = temp_db.get_fraud_statistics()
        
        assert stats['total_analyzed'] == 4
        assert stats['high_risk'] == 2
        assert stats['medium_risk'] == 1
        assert stats['revenue_at_risk'] == 300  # 100 + 200
    
    # ==================== Outcome Tracking ====================
    
    def test_record_fraud_outcome(self, temp_db):
        """Test recording fraud outcome"""
        # First save a fraud result
        results = [
            {'DUID': 'test123', 'email': 'test@example.com', 'risk_score': 75, 
             'flags': ['HIGH_RISK'], 'details': {}, 'payout_amount': 100, 'data_type': 'free'}
        ]
        temp_db.save_fraud_results(results)
        
        # Record outcome
        success = temp_db.record_fraud_outcome(
            duid='test123',
            outcome='confirmed_fraud',
            notes='Test note'
        )
        
        assert success == True
        
        # Verify outcome was recorded
        df = temp_db.get_reviewed_outcomes(days=1)
        assert len(df) == 1
        assert df.iloc[0]['outcome'] == 'confirmed_fraud'
    
    def test_record_outcome_invalid_outcome(self, temp_db):
        """Test recording invalid outcome fails"""
        success = temp_db.record_fraud_outcome(
            duid='test123',
            outcome='invalid_outcome'
        )
        
        assert success == False
    
    def test_record_outcome_missing_duid(self, temp_db):
        """Test recording outcome for non-existent DUID fails"""
        success = temp_db.record_fraud_outcome(
            duid='nonexistent',
            outcome='confirmed_fraud'
        )
        
        assert success == False
    
    # ==================== Pending Reviews ====================
    
    def test_get_pending_reviews(self, temp_db):
        """Test getting pending reviews"""
        results = [
            {'DUID': 'reviewed1', 'email': 'reviewed@test.com', 'risk_score': 60, 
             'flags': [], 'details': {}, 'payout_amount': 100, 'data_type': 'free'},
            {'DUID': 'pending1', 'email': 'pending@test.com', 'risk_score': 70, 
             'flags': [], 'details': {}, 'payout_amount': 200, 'data_type': 'free'},
        ]
        temp_db.save_fraud_results(results)
        
        # Record outcome for one
        temp_db.record_fraud_outcome('reviewed1', 'confirmed_fraud')
        
        # Get pending - should only return the one without outcome
        pending = temp_db.get_pending_reviews(min_risk=50)
        
        assert len(pending) == 1
        assert pending.iloc[0]['duid'] == 'pending1'
    
    # ==================== Effectiveness Metrics ====================
    
    def test_get_effectiveness_metrics(self, temp_db):
        """Test effectiveness metrics calculation"""
        results = [
            {'DUID': 'high1', 'email': 'high1@test.com', 'risk_score': 60, 
             'flags': [], 'details': {}, 'payout_amount': 100, 'data_type': 'free'},
            {'DUID': 'high2', 'email': 'high2@test.com', 'risk_score': 70, 
             'flags': [], 'details': {}, 'payout_amount': 200, 'data_type': 'free'},
        ]
        temp_db.save_fraud_results(results)
        
        # Record outcomes
        temp_db.record_fraud_outcome('high1', 'confirmed_fraud')
        temp_db.record_fraud_outcome('high2', 'false_positive')
        
        metrics = temp_db.get_effectiveness_metrics()
        
        assert metrics['total_flagged_high'] == 2
        assert metrics['reviewed_high'] == 2
        assert metrics['confirmed_fraud_high'] == 1
        assert metrics['false_positives_high'] == 1
        assert metrics['precision_high'] == 0.5
    
    # ==================== Low Risk Sampling ====================
    
    def test_sample_low_risk_accounts(self, temp_db):
        """Test sampling low risk accounts"""
        results = [
            {'DUID': 'low1', 'email': 'low1@test.com', 'risk_score': 5, 
             'flags': [], 'details': {}, 'payout_amount': 10, 'data_type': 'free'},
            {'DUID': 'low2', 'email': 'low2@test.com', 'risk_score': 15, 
             'flags': [], 'details': {}, 'payout_amount': 20, 'data_type': 'free'},
            {'DUID': 'high1', 'email': 'high@test.com', 'risk_score': 60, 
             'flags': [], 'details': {}, 'payout_amount': 100, 'data_type': 'free'},
        ]
        temp_db.save_fraud_results(results)
        
        # Sample should only return low risk
        sample = temp_db.sample_low_risk_accounts(count=10, max_risk=24)
        
        assert len(sample) == 2
        assert all(sample['risk_score'] <= 24)
    
    def test_record_low_risk_review(self, temp_db):
        """Test recording low risk review"""
        results = [
            {'DUID': 'low1', 'email': 'low1@test.com', 'risk_score': 5, 
             'flags': [], 'details': {}, 'payout_amount': 10, 'data_type': 'free'},
        ]
        temp_db.save_fraud_results(results)
        
        # Sample first
        temp_db.sample_low_risk_accounts(count=1, max_risk=24)
        
        # Record review
        success = temp_db.record_low_risk_review('low1', 'missed_fraud', 'Test notes')
        
        assert success == True
        
        # Verify
        samples = temp_db.get_low_risk_samples(status='missed_fraud')
        assert len(samples) == 1

    def test_affiliate_actions_crud(self, temp_db):
        assert temp_db.get_affiliate_action('AFFX') is None
        assert temp_db.upsert_affiliate_action(
            'AFFX',
            'actioned',
            action_type='traffic_closed',
            trigger_reason='high_fraud_rate',
            notes='Closed per tool',
            updated_by='pytest',
        ) is True
        row = temp_db.get_affiliate_action('AFFX')
        assert row['webmaster_code'] == 'AFFX'
        assert row['action_status'] == 'actioned'
        assert row['action_type'] == 'traffic_closed'
        assert len(temp_db.list_affiliate_actions()) == 1
        assert temp_db.delete_affiliate_action('AFFX') == 1
        assert temp_db.get_affiliate_action('AFFX') is None


class TestBillingCorrelations:
    """Tests for billing correlation features"""
    
    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing"""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        db = Database(path)
        yield db
        os.unlink(path)
    
    def test_get_billing_correlations_empty(self, temp_db):
        """Test billing correlations with no data"""
        df = temp_db.get_billing_correlations()
        assert len(df) == 0
    
    def test_high_risk_billing_summary_empty(self, temp_db):
        """Test billing summary with no data"""
        summary = temp_db.get_high_risk_billing_summary()
        
        assert summary['shared_billing_clusters'] == 0
        assert summary['accounts_in_clusters'] == 0
        assert summary['total_payout_at_risk'] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
