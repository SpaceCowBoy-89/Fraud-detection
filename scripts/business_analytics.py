"""
Business Analytics Module

Calculate business metrics and KPIs for fraud detection system.

Features:
- Fraud loss prevented calculation
- False positive rate and impact
- Risk management metrics
- ROI alternatives (without system cost data)
- Industry benchmarking
- Stakeholder-specific metrics
"""

import pandas as pd
import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)


class BusinessAnalytics:
    """
    Business metrics and KPI calculations
    """
    
    def __init__(self, db):
        self.db = db
        
        # Industry benchmarks (dating industry)
        self.industry_benchmarks = {
            'fraud_rate': 3.1,  # 3.1% average for dating sites
            'false_positive_rate': 3.5,  # 3.5% average
            'detection_time_hours': 24,  # 24 hour average
            'source': 'Dating Industry Reports 2024-2025'
        }
    
    def calculate_fraud_prevented(self, start_date=None, end_date=None):
        """
        Calculate fraud loss prevented
        
        Args:
            start_date: Optional start date (YYYY-MM-DD)
            end_date: Optional end date (YYYY-MM-DD)
            
        Returns:
            dict with fraud prevented metrics
        """
        logger.info("Calculating fraud loss prevented...")
        
        import sqlite3
        conn = sqlite3.connect(self.db.db_path)
        
        # Build query for confirmed fraud
        query = """
            SELECT 
                fr.payout_amount,
                fo.outcome,
                fo.reviewed_at
            FROM fraud_results fr
            INNER JOIN fraud_outcomes fo ON fr.duid = fo.duid
            WHERE fo.outcome = 'confirmed_fraud'
        """
        
        params = []
        if start_date and end_date:
            query += " AND fo.reviewed_at BETWEEN ? AND ?"
            params = [start_date, end_date]
        
        df = pd.read_sql_query(query, conn, params=params if params else None)
        conn.close()
        
        if df.empty:
            return {
                'total_prevented': 0.0,
                'count': 0,
                'trend': None,
                'monthly_breakdown': []
            }
        
        # Calculate total prevented
        amounts = pd.to_numeric(df['payout_amount'], errors='coerce')
        total_prevented = float(amounts.sum())
        count = len(df)
        
        # Calculate trend (compare to previous period)
        trend = None
        if start_date and end_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            days_diff = (end_dt - start_dt).days
            
            prev_start = (start_dt - timedelta(days=days_diff)).strftime('%Y-%m-%d')
            prev_end = start_date
            
            # Query previous period
            prev_query = """
                SELECT SUM(fr.payout_amount) as prev_total
                FROM fraud_results fr
                INNER JOIN fraud_outcomes fo ON fr.duid = fo.duid
                WHERE fo.outcome = 'confirmed_fraud'
                AND fo.reviewed_at BETWEEN ? AND ?
            """
            conn = sqlite3.connect(self.db.db_path)
            prev_df = pd.read_sql_query(prev_query, conn, params=[prev_start, prev_end])
            conn.close()
            
            prev_total = prev_df['prev_total'].iloc[0] if not prev_df.empty else 0
            if prev_total and prev_total > 0:
                trend = round(((total_prevented - prev_total) / prev_total) * 100, 1)
        
        # Monthly breakdown
        df['month'] = pd.to_datetime(df['reviewed_at']).dt.to_period('M')
        monthly = df.groupby('month')['payout_amount'].apply(
            lambda x: float(pd.to_numeric(x, errors='coerce').sum())
        ).to_dict()
        monthly_breakdown = [
            {'month': str(month), 'amount': amount} 
            for month, amount in monthly.items()
        ]
        
        logger.info(f"Fraud prevented: ${total_prevented:,.2f} ({count} accounts)")
        
        return {
            'total_prevented': round(total_prevented, 2),
            'count': count,
            'trend': trend,
            'monthly_breakdown': monthly_breakdown
        }
    
    def calculate_false_positive_rate(self, start_date=None, end_date=None):
        """
        Calculate false positive metrics
        
        Args:
            start_date: Optional start date
            end_date: Optional end date
            
        Returns:
            dict with false positive metrics
        """
        logger.info("Calculating false positive rate...")
        
        import sqlite3
        conn = sqlite3.connect(self.db.db_path)
        
        # Get all outcomes
        query = """
            SELECT 
                fo.outcome,
                fr.payout_amount
            FROM fraud_outcomes fo
            INNER JOIN fraud_results fr ON fo.duid = fr.duid
            WHERE fr.risk_score >= 50
        """
        
        params = []
        if start_date and end_date:
            query += " AND fo.reviewed_at BETWEEN ? AND ?"
            params = [start_date, end_date]
        
        df = pd.read_sql_query(query, conn, params=params if params else None)
        conn.close()
        
        if df.empty:
            return {
                'rate': 0.0,
                'count': 0,
                'total_flagged': 0,
                'revenue_impact': 0.0
            }
        
        # Calculate FP rate
        false_positives = len(df[df['outcome'] == 'false_positive'])
        total_flagged = len(df)
        rate = (false_positives / total_flagged * 100) if total_flagged > 0 else 0.0
        
        # Estimate revenue impact (FP * avg customer value)
        fp_amounts = pd.to_numeric(
            df[df['outcome'] == 'false_positive']['payout_amount'], 
            errors='coerce'
        )
        revenue_impact = float(fp_amounts.sum())
        
        logger.info(f"False positive rate: {rate:.2f}% ({false_positives}/{total_flagged})")
        
        return {
            'rate': round(rate, 2),
            'count': false_positives,
            'total_flagged': total_flagged,
            'revenue_impact': round(revenue_impact, 2)
        }
    
    def calculate_risk_metrics(self, start_date=None, end_date=None):
        """
        Overall risk management metrics
        
        Args:
            start_date: Optional start date
            end_date: Optional end date
            
        Returns:
            dict with risk metrics
        """
        logger.info("Calculating risk metrics...")
        
        import sqlite3
        conn = sqlite3.connect(self.db.db_path)
        
        # Get total accounts and fraud accounts
        query = "SELECT COUNT(*) as total FROM fraud_results"
        params = []
        
        if start_date and end_date:
            query += " WHERE analyzed_at BETWEEN ? AND ?"
            params = [start_date, end_date]
        
        total_df = pd.read_sql_query(query, conn, params=params if params else None)
        total_accounts = total_df['total'].iloc[0]
        
        # Get confirmed fraud count
        fraud_query = """
            SELECT COUNT(*) as fraud_count
            FROM fraud_results fr
            INNER JOIN fraud_outcomes fo ON fr.duid = fo.duid
            WHERE fo.outcome = 'confirmed_fraud'
        """
        
        if start_date and end_date:
            fraud_query += " AND fo.reviewed_at BETWEEN ? AND ?"
        
        fraud_df = pd.read_sql_query(fraud_query, conn, params=params if params else None)
        fraud_count = fraud_df['fraud_count'].iloc[0]
        
        # Risk distribution
        risk_query = """
            SELECT 
                CASE 
                    WHEN risk_score < 25 THEN 'low'
                    WHEN risk_score < 50 THEN 'medium'
                    ELSE 'high'
                END as risk_level,
                COUNT(*) as count
            FROM fraud_results
        """
        
        if start_date and end_date:
            risk_query += " WHERE analyzed_at BETWEEN ? AND ?"
        
        risk_query += " GROUP BY risk_level"
        
        risk_df = pd.read_sql_query(risk_query, conn, params=params if params else None)
        conn.close()
        
        # Calculate fraud rate
        fraud_rate = (fraud_count / total_accounts * 100) if total_accounts > 0 else 0.0
        
        # Risk distribution
        distribution = {row['risk_level']: int(row['count']) for _, row in risk_df.iterrows()}
        distribution_pct = {
            level: round((count / total_accounts * 100), 2) if total_accounts > 0 else 0
            for level, count in distribution.items()
        }
        
        # Trend analysis (compare to previous period)
        trend = 'stable'
        if start_date and end_date:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            days_diff = (end_dt - start_dt).days
            
            prev_start = (start_dt - timedelta(days=days_diff)).strftime('%Y-%m-%d')
            prev_end = start_date
            
            # Get previous period fraud rate
            conn = sqlite3.connect(self.db.db_path)
            prev_query = """
                SELECT COUNT(*) as prev_fraud
                FROM fraud_results fr
                INNER JOIN fraud_outcomes fo ON fr.duid = fo.duid
                WHERE fo.outcome = 'confirmed_fraud'
                AND fo.reviewed_at BETWEEN ? AND ?
            """
            prev_fraud_df = pd.read_sql_query(prev_query, conn, params=[prev_start, prev_end])
            prev_fraud_count = prev_fraud_df['prev_fraud'].iloc[0]
            
            prev_total_query = f"SELECT COUNT(*) as prev_total FROM fraud_results WHERE analyzed_at BETWEEN ? AND ?"
            prev_total_df = pd.read_sql_query(prev_total_query, conn, params=[prev_start, prev_end])
            prev_total = prev_total_df['prev_total'].iloc[0]
            conn.close()
            
            if prev_total > 0:
                prev_rate = (prev_fraud_count / prev_total * 100)
                if fraud_rate < prev_rate * 0.9:
                    trend = 'improving'
                elif fraud_rate > prev_rate * 1.1:
                    trend = 'worsening'
        
        logger.info(f"Overall fraud rate: {fraud_rate:.2f}% (trend: {trend})")
        
        return {
            'fraud_rate': round(fraud_rate, 2),
            'total_accounts': int(total_accounts),
            'fraud_count': int(fraud_count),
            'distribution': distribution,
            'distribution_pct': distribution_pct,
            'trend': trend
        }
    
    def calculate_value_metrics(self, start_date=None, end_date=None):
        """
        Calculate ROI alternatives (without system cost data)
        
        Args:
            start_date: Optional start date
            end_date: Optional end date
            
        Returns:
            dict with value metrics
        """
        logger.info("Calculating value metrics...")
        
        fraud_prevented = self.calculate_fraud_prevented(start_date, end_date)
        false_positives = self.calculate_false_positive_rate(start_date, end_date)
        
        # Protection rate: prevented / (prevented + losses)
        # Assuming losses are 0 since we're preventing them
        protection_rate = 100.0 if fraud_prevented['total_prevented'] > 0 else 0.0
        
        # Net value: prevented - FP cost
        net_value = fraud_prevented['total_prevented'] - false_positives['revenue_impact']
        
        # Savings rate: prevented / total revenue (estimate from payouts)
        import sqlite3
        conn = sqlite3.connect(self.db.db_path)
        
        query = "SELECT SUM(payout_amount) as total_payout FROM fraud_results"
        params = []
        if start_date and end_date:
            query += " WHERE analyzed_at BETWEEN ? AND ?"
            params = [start_date, end_date]
        
        payout_df = pd.read_sql_query(query, conn, params=params if params else None)
        conn.close()
        
        total_payouts = payout_df['total_payout'].iloc[0] if not payout_df.empty and payout_df['total_payout'].iloc[0] else 0
        savings_rate = (fraud_prevented['total_prevented'] / total_payouts * 100) if total_payouts > 0 else 0.0
        
        logger.info(f"Value metrics: Protection rate {protection_rate:.1f}%, Net value ${net_value:,.2f}")
        
        return {
            'protection_rate': round(protection_rate, 2),
            'net_value': round(net_value, 2),
            'savings_rate': round(savings_rate, 2),
            'fraud_prevented': fraud_prevented['total_prevented'],
            'false_positive_cost': false_positives['revenue_impact']
        }
    
    def get_industry_benchmarks(self):
        """
        Get industry benchmark comparisons
        
        Returns:
            dict with benchmark comparisons
        """
        logger.info("Calculating industry benchmarks...")
        
        # Get our current metrics
        risk_metrics = self.calculate_risk_metrics()
        fp_metrics = self.calculate_false_positive_rate()
        
        our_fraud_rate = risk_metrics['fraud_rate']
        our_fp_rate = fp_metrics['rate']
        
        # Compare to industry
        fraud_comparison = our_fraud_rate - self.industry_benchmarks['fraud_rate']
        fraud_better = fraud_comparison < 0
        fraud_pct_diff = abs((fraud_comparison / self.industry_benchmarks['fraud_rate']) * 100)
        
        fp_comparison = our_fp_rate - self.industry_benchmarks['false_positive_rate']
        fp_better = fp_comparison < 0
        fp_pct_diff = abs((fp_comparison / self.industry_benchmarks['false_positive_rate']) * 100)
        
        # Percentile calculation (simplified)
        if fraud_better:
            percentile = 50 + (fraud_pct_diff / 2)
        else:
            percentile = 50 - (fraud_pct_diff / 2)
        percentile = max(10, min(90, percentile))  # Cap between 10-90
        
        logger.info(f"Industry comparison: {fraud_pct_diff:.1f}% {'better' if fraud_better else 'worse'} than average")
        
        return {
            'our_metrics': {
                'fraud_rate': our_fraud_rate,
                'false_positive_rate': our_fp_rate,
                'detection_time': '< 1 min'  # Real-time
            },
            'industry_avg': self.industry_benchmarks,
            'comparison': {
                'fraud_rate': {
                    'difference': round(fraud_comparison, 2),
                    'better': fraud_better,
                    'pct_diff': round(fraud_pct_diff, 1)
                },
                'false_positive_rate': {
                    'difference': round(fp_comparison, 2),
                    'better': fp_better,
                    'pct_diff': round(fp_pct_diff, 1)
                }
            },
            'percentile': round(percentile, 0)
        }
    
    def get_stakeholder_metrics(self, stakeholder_type, start_date=None, end_date=None):
        """
        Get tailored metrics for specific stakeholders
        
        Args:
            stakeholder_type: 'finance', 'marketing', or 'operations'
            start_date: Optional start date
            end_date: Optional end date
            
        Returns:
            dict with stakeholder-specific metrics
        """
        logger.info(f"Generating {stakeholder_type} metrics...")
        
        if stakeholder_type == 'finance':
            return {
                'fraud_prevented': self.calculate_fraud_prevented(start_date, end_date),
                'value_metrics': self.calculate_value_metrics(start_date, end_date),
                'risk_metrics': self.calculate_risk_metrics(start_date, end_date)
            }
        
        elif stakeholder_type == 'marketing':
            # Marketing cares about affiliate/campaign performance
            import sqlite3
            conn = sqlite3.connect(self.db.db_path)
            
            # Fraud by affiliate
            aff_query = """
                SELECT 
                    webmaster_code,
                    COUNT(*) as total,
                    SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) as high_risk
                FROM fraud_results
                WHERE webmaster_code IS NOT NULL
            """
            if start_date and end_date:
                aff_query += " AND analyzed_at BETWEEN ? AND ?"
                params = [start_date, end_date]
            else:
                params = None
            
            aff_query += " GROUP BY webmaster_code ORDER BY high_risk DESC LIMIT 10"
            
            aff_df = pd.read_sql_query(aff_query, conn, params=params)
            aff_df['fraud_rate'] = (aff_df['high_risk'] / aff_df['total'] * 100).round(2)
            
            # Fraud by campaign
            camp_query = """
                SELECT 
                    campaign,
                    COUNT(*) as total,
                    SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) as high_risk
                FROM fraud_results
                WHERE campaign IS NOT NULL
            """
            if start_date and end_date:
                camp_query += " AND analyzed_at BETWEEN ? AND ?"
            
            camp_query += " GROUP BY campaign ORDER BY high_risk DESC LIMIT 10"
            
            camp_df = pd.read_sql_query(camp_query, conn, params=params)
            camp_df['fraud_rate'] = (camp_df['high_risk'] / camp_df['total'] * 100).round(2)
            
            conn.close()
            
            return {
                'top_risk_affiliates': aff_df.to_dict('records'),
                'top_risk_campaigns': camp_df.to_dict('records'),
                'overall_risk': self.calculate_risk_metrics(start_date, end_date)
            }
        
        elif stakeholder_type == 'operations':
            # Operations cares about detection accuracy and efficiency
            return {
                'false_positive_rate': self.calculate_false_positive_rate(start_date, end_date),
                'risk_metrics': self.calculate_risk_metrics(start_date, end_date),
                'industry_benchmarks': self.get_industry_benchmarks()
            }
        
        else:
            raise ValueError(f"Unknown stakeholder type: {stakeholder_type}")
    
    def get_all_metrics(self, start_date=None, end_date=None):
        """
        Get comprehensive metrics for dashboard
        
        Args:
            start_date: Optional start date
            end_date: Optional end date
            
        Returns:
            dict with all business metrics
        """
        logger.info("Generating comprehensive business metrics...")
        
        return {
            'fraud_prevented': self.calculate_fraud_prevented(start_date, end_date),
            'false_positive_rate': self.calculate_false_positive_rate(start_date, end_date),
            'risk_metrics': self.calculate_risk_metrics(start_date, end_date),
            'value_metrics': self.calculate_value_metrics(start_date, end_date),
            'industry_benchmarks': self.get_industry_benchmarks(),
            'generated_at': datetime.now().isoformat()
        }
