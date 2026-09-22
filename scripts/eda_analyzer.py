"""
Exploratory Data Analysis (EDA) Module

Comprehensive data exploration and quality analysis for fraud detection.

Features:
- Data profiling and statistics
- Distribution analysis
- Correlation with fraud
- Data quality checks
- Outlier detection
- HTML report generation
- PDF export capability
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime
from collections import Counter
import json

logger = logging.getLogger(__name__)


class EDAAnalyzer:
    """
    Comprehensive exploratory data analysis
    """
    
    def __init__(self, db=None):
        self.db = db
        self.analysis_results = {}
        
    def generate_profile(self, df, data_type='unknown'):
        """
        Generate comprehensive data profile
        
        Args:
            df: pandas DataFrame
            data_type: 'free', 'paid', or 'fraud'
            
        Returns:
            dict with profiling results
        """
        logger.info(f"Generating profile for {len(df)} {data_type} records...")
        
        profile = {
            'data_type': data_type,
            'record_count': len(df),
            'column_count': len(df.columns),
            'memory_usage': df.memory_usage(deep=True).sum() / (1024**2),  # MB
        }
        
        # Date range
        if 'trans_datetime' in df.columns:
            dates = pd.to_datetime(df['trans_datetime'], errors='coerce')
            profile['date_range'] = {
                'start': dates.min().isoformat() if not pd.isna(dates.min()) else None,
                'end': dates.max().isoformat() if not pd.isna(dates.max()) else None,
                'span_days': (dates.max() - dates.min()).days if not pd.isna(dates.min()) else 0
            }
        
        # Field completeness
        completeness = {}
        for col in df.columns:
            non_null = df[col].notna().sum()
            completeness[col] = {
                'count': int(non_null),
                'percentage': round((non_null / len(df)) * 100, 2)
            }
        profile['completeness'] = completeness
        
        # Missing values
        missing = df.isnull().sum()
        profile['missing_values'] = {
            col: int(count) for col, count in missing.items() if count > 0
        }
        
        # Duplicate records (by DUID if available)
        if 'duid' in df.columns:
            duplicates = df['duid'].duplicated().sum()
            profile['duplicates'] = int(duplicates)
        
        # Unique counts for key fields
        unique_counts = {}
        for col in ['email', 'webmaster_code', 'campaign', 'ip', 'email_domain']:
            if col in df.columns:
                unique_counts[col] = int(df[col].nunique())
        profile['unique_counts'] = unique_counts
        
        logger.info(f"Profile complete: {profile['record_count']} records, "
                   f"{profile['column_count']} columns, "
                   f"{len(profile['missing_values'])} fields with missing data")
        
        return profile
    
    def analyze_distributions(self, df):
        """
        Analyze field distributions
        
        Args:
            df: pandas DataFrame
            
        Returns:
            dict with distribution data
        """
        logger.info("Analyzing distributions...")
        
        distributions = {}
        
        # Email domains (top 20)
        if 'email' in df.columns or 'email_domain' in df.columns:
            domain_col = 'email_domain' if 'email_domain' in df.columns else 'email'
            if domain_col == 'email':
                domains = df[domain_col].str.split('@').str[1]
            else:
                domains = df[domain_col]
            
            domain_counts = domains.value_counts().head(20)
            distributions['email_domains'] = {
                'labels': domain_counts.index.tolist(),
                'values': domain_counts.values.tolist()
            }
        
        # Payout amounts
        if 'payout_amount' in df.columns:
            amounts = pd.to_numeric(df['payout_amount'], errors='coerce')
            amounts = amounts[amounts > 0]
            
            if len(amounts) > 0:
                distributions['payout_amounts'] = {
                    'mean': float(amounts.mean()),
                    'median': float(amounts.median()),
                    'std': float(amounts.std()),
                    'min': float(amounts.min()),
                    'max': float(amounts.max()),
                    'q1': float(amounts.quantile(0.25)),
                    'q3': float(amounts.quantile(0.75)),
                    'histogram': {
                        'bins': np.histogram(amounts, bins=20)[1].tolist(),
                        'counts': np.histogram(amounts, bins=20)[0].tolist()
                    }
                }
        
        # Geographic distribution (top 10 countries)
        if 'geo_country' in df.columns:
            country_counts = df['geo_country'].value_counts().head(10)
            distributions['geographic'] = {
                'labels': country_counts.index.tolist(),
                'values': country_counts.values.tolist()
            }
        
        # Time patterns
        if 'trans_datetime' in df.columns:
            dates = pd.to_datetime(df['trans_datetime'], errors='coerce')
            
            # Hourly pattern
            hours = dates.dt.hour.value_counts().sort_index()
            distributions['hourly_pattern'] = {
                'hours': hours.index.tolist(),
                'counts': hours.values.tolist()
            }
            
            # Daily pattern (day of week)
            days = dates.dt.dayofweek.value_counts().sort_index()
            day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
            distributions['daily_pattern'] = {
                'days': [day_names[i] for i in days.index],
                'counts': days.values.tolist()
            }
        
        # Campaign distribution (top 15)
        if 'campaign' in df.columns:
            campaign_counts = df['campaign'].value_counts().head(15)
            distributions['campaigns'] = {
                'labels': campaign_counts.index.tolist(),
                'values': campaign_counts.values.tolist()
            }
        
        # Affiliate distribution (top 15)
        if 'webmaster_code' in df.columns:
            affiliate_counts = df['webmaster_code'].value_counts().head(15)
            distributions['affiliates'] = {
                'labels': affiliate_counts.index.tolist(),
                'values': affiliate_counts.values.tolist()
            }
        
        logger.info(f"Distribution analysis complete: {len(distributions)} distributions generated")
        
        return distributions
    
    def analyze_correlations(self, df, fraud_df=None):
        """
        Analyze correlations with fraud
        
        Args:
            df: Source data DataFrame
            fraud_df: Fraud results DataFrame (optional)
            
        Returns:
            dict with correlation data
        """
        logger.info("Analyzing fraud correlations...")
        
        correlations = {}
        
        if fraud_df is None or fraud_df.empty:
            logger.warning("No fraud data available for correlation analysis")
            return correlations
        
        # Merge with fraud data
        if 'duid' in df.columns and 'duid' in fraud_df.columns:
            merged = df.merge(fraud_df[['duid', 'risk_score', 'flags']], on='duid', how='left')
            merged['is_high_risk'] = merged['risk_score'] >= 50
        else:
            logger.warning("Cannot merge - DUID column missing")
            return correlations
        
        # Fraud rate by email domain
        if 'email' in merged.columns or 'email_domain' in merged.columns:
            domain_col = 'email_domain' if 'email_domain' in merged.columns else 'email'
            if domain_col == 'email':
                merged['domain'] = merged[domain_col].str.split('@').str[1]
            else:
                merged['domain'] = merged[domain_col]
            
            domain_fraud = merged.groupby('domain').agg({
                'is_high_risk': ['sum', 'count']
            }).reset_index()
            domain_fraud.columns = ['domain', 'high_risk_count', 'total_count']
            domain_fraud['fraud_rate'] = (domain_fraud['high_risk_count'] / domain_fraud['total_count'] * 100).round(2)
            domain_fraud = domain_fraud[domain_fraud['total_count'] >= 5].sort_values('fraud_rate', ascending=False).head(20)
            
            correlations['fraud_by_domain'] = domain_fraud.to_dict('records')
        
        # Fraud rate by payout amount range
        if 'payout_amount' in merged.columns:
            amounts = pd.to_numeric(merged['payout_amount'], errors='coerce')
            merged['amount_range'] = pd.cut(amounts, bins=[0, 1, 5, 10, 50, 100, float('inf')],
                                           labels=['$0-1', '$1-5', '$5-10', '$10-50', '$50-100', '$100+'])
            
            amount_fraud = merged.groupby('amount_range', observed=True).agg({
                'is_high_risk': ['sum', 'count']
            }).reset_index()
            amount_fraud.columns = ['amount_range', 'high_risk_count', 'total_count']
            amount_fraud['fraud_rate'] = (amount_fraud['high_risk_count'] / amount_fraud['total_count'] * 100).round(2)
            
            correlations['fraud_by_amount'] = amount_fraud.to_dict('records')
        
        # Fraud rate by country
        if 'geo_country' in merged.columns:
            country_fraud = merged.groupby('geo_country').agg({
                'is_high_risk': ['sum', 'count']
            }).reset_index()
            country_fraud.columns = ['country', 'high_risk_count', 'total_count']
            country_fraud['fraud_rate'] = (country_fraud['high_risk_count'] / country_fraud['total_count'] * 100).round(2)
            country_fraud = country_fraud[country_fraud['total_count'] >= 10].sort_values('fraud_rate', ascending=False).head(15)
            
            correlations['fraud_by_country'] = country_fraud.to_dict('records')
        
        # Fraud rate by campaign
        if 'campaign' in merged.columns:
            campaign_fraud = merged.groupby('campaign').agg({
                'is_high_risk': ['sum', 'count']
            }).reset_index()
            campaign_fraud.columns = ['campaign', 'high_risk_count', 'total_count']
            campaign_fraud['fraud_rate'] = (campaign_fraud['high_risk_count'] / campaign_fraud['total_count'] * 100).round(2)
            campaign_fraud = campaign_fraud[campaign_fraud['total_count'] >= 10].sort_values('fraud_rate', ascending=False).head(15)
            
            correlations['fraud_by_campaign'] = campaign_fraud.to_dict('records')
        
        # Fraud rate by time of day
        if 'trans_datetime' in merged.columns:
            dates = pd.to_datetime(merged['trans_datetime'], errors='coerce')
            merged['hour'] = dates.dt.hour
            
            time_fraud = merged.groupby('hour').agg({
                'is_high_risk': ['sum', 'count']
            }).reset_index()
            time_fraud.columns = ['hour', 'high_risk_count', 'total_count']
            time_fraud['fraud_rate'] = (time_fraud['high_risk_count'] / time_fraud['total_count'] * 100).round(2)
            
            correlations['fraud_by_hour'] = time_fraud.to_dict('records')
        
        logger.info(f"Correlation analysis complete: {len(correlations)} correlation types analyzed")
        
        return correlations
    
    def check_data_quality(self, df):
        """
        Identify data quality issues
        
        Args:
            df: pandas DataFrame
            
        Returns:
            dict with quality issues
        """
        logger.info("Checking data quality...")
        
        issues = {
            'critical': [],
            'warnings': [],
            'info': []
        }
        
        # Missing critical fields
        critical_fields = ['duid', 'email', 'trans_datetime']
        for field in critical_fields:
            if field in df.columns:
                missing_count = df[field].isnull().sum()
                if missing_count > 0:
                    issues['critical'].append({
                        'type': 'missing_critical_field',
                        'field': field,
                        'count': int(missing_count),
                        'percentage': round((missing_count / len(df)) * 100, 2)
                    })
        
        # Duplicate records
        if 'duid' in df.columns:
            duplicates = df['duid'].duplicated().sum()
            if duplicates > 0:
                issues['warnings'].append({
                    'type': 'duplicate_records',
                    'count': int(duplicates),
                    'percentage': round((duplicates / len(df)) * 100, 2)
                })
        
        # Invalid emails
        if 'email' in df.columns:
            invalid_emails = df[~df['email'].str.contains('@', na=False)].shape[0]
            if invalid_emails > 0:
                issues['warnings'].append({
                    'type': 'invalid_emails',
                    'count': int(invalid_emails),
                    'percentage': round((invalid_emails / len(df)) * 100, 2)
                })
        
        # Suspicious IP patterns (many records from same IP)
        if 'ip' in df.columns:
            ip_counts = df['ip'].value_counts()
            suspicious_ips = ip_counts[ip_counts > 100]
            if len(suspicious_ips) > 0:
                issues['warnings'].append({
                    'type': 'ip_concentration',
                    'count': len(suspicious_ips),
                    'max_records_per_ip': int(suspicious_ips.max())
                })
        
        # Future dates
        if 'trans_datetime' in df.columns:
            dates = pd.to_datetime(df['trans_datetime'], errors='coerce')
            future_dates = dates[dates > pd.Timestamp.now()].count()
            if future_dates > 0:
                issues['critical'].append({
                    'type': 'future_dates',
                    'count': int(future_dates)
                })
        
        # Negative amounts
        if 'payout_amount' in df.columns:
            amounts = pd.to_numeric(df['payout_amount'], errors='coerce')
            negative = (amounts < 0).sum()
            if negative > 0:
                issues['warnings'].append({
                    'type': 'negative_amounts',
                    'count': int(negative)
                })
        
        # Data freshness
        if 'trans_datetime' in df.columns:
            dates = pd.to_datetime(df['trans_datetime'], errors='coerce')
            latest_date = dates.max()
            days_old = (pd.Timestamp.now() - latest_date).days
            if days_old > 30:
                issues['info'].append({
                    'type': 'stale_data',
                    'days_since_latest': int(days_old),
                    'latest_record': latest_date.isoformat()
                })
        
        logger.info(f"Quality check complete: {len(issues['critical'])} critical, "
                   f"{len(issues['warnings'])} warnings, {len(issues['info'])} info")
        
        return issues
    
    def detect_outliers(self, df):
        """
        Statistical outlier detection
        
        Args:
            df: pandas DataFrame
            
        Returns:
            list of DUIDs flagged as outliers
        """
        logger.info("Detecting statistical outliers...")
        
        outlier_duids = []
        
        if 'duid' not in df.columns:
            logger.warning("No DUID column for outlier tracking")
            return outlier_duids
        
        # Amount outliers (Z-score > 3). Need enough spread that a lone spike registers.
        if 'payout_amount' in df.columns:
            amounts = pd.to_numeric(df['payout_amount'], errors='coerce')
            amounts_clean = amounts[amounts > 0]
            
            if len(amounts_clean) > 0:
                mean = amounts_clean.mean()
                std = amounts_clean.std()
                
                if std > 0:
                    z_scores = np.abs((amounts - mean) / std)
                    amount_outliers = df[z_scores > 3]['duid'].tolist()
                    outlier_duids.extend(amount_outliers)

                # Small / flat samples: Z-score often misses a single spike. Also flag
                # payouts far above the median (10x) when median is positive.
                median = float(amounts_clean.median())
                if median > 0:
                    spike = df[amounts >= (median * 10)]['duid'].tolist()
                    outlier_duids.extend(spike)
        
        # Disposable email domains
        if 'email_disposable' in df.columns:
            disposable_outliers = df[df['email_disposable'] == True]['duid'].tolist()
            outlier_duids.extend(disposable_outliers)
        
        # High IP concentration (same IP for many accounts)
        if 'ip' in df.columns:
            ip_counts = df['ip'].value_counts()
            high_concentration_ips = ip_counts[ip_counts > 50].index
            ip_outliers = df[df['ip'].isin(high_concentration_ips)]['duid'].tolist()
            outlier_duids.extend(ip_outliers)
        
        # Remove duplicates
        outlier_duids = list(set(outlier_duids))
        
        logger.info(f"Outlier detection complete: {len(outlier_duids)} outliers found")
        
        return outlier_duids
    
    def run_full_analysis(self, data_type='free', start_date=None, end_date=None, affiliate=None):
        """
        Run complete EDA analysis

        Args:
            data_type: 'free' or 'paid'
            start_date: Optional start date filter
            end_date: Optional end date filter
            affiliate: Optional webmaster_code to restrict analysis to one affiliate

        Returns:
            dict with all analysis results
        """
        if not self.db:
            raise ValueError("Database connection required for full analysis")

        logger.info(f"Starting full EDA analysis for {data_type} data"
                    + (f" [affiliate={affiliate}]" if affiliate else "") + "...")

        import sqlite3
        conn = sqlite3.connect(self.db.db_path)

        # Build parameterised query — affiliate filter is optional
        where_clauses = []
        params = []

        if start_date and end_date:
            from database import Database
            where_clauses.append(Database.SQL_TRANS_DATE_BETWEEN)
            params.extend([start_date, end_date])

        if affiliate:
            where_clauses.append("webmaster_code = ?")
            params.append(affiliate)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        query = f"SELECT * FROM {data_type} {where_sql}"
        df = pd.read_sql_query(query, conn, params=params if params else None)

        # Load fraud results — restrict to same affiliate so correlations are scoped correctly
        if affiliate:
            fraud_df = pd.read_sql_query(
                "SELECT * FROM fraud_results WHERE webmaster_code = ?", conn, params=[affiliate]
            )
        else:
            fraud_df = pd.read_sql_query("SELECT * FROM fraud_results", conn)
        conn.close()
        
        if df.empty:
            logger.warning(f"No {data_type} data found")
            return {'error': 'No data available'}
        
        # Run all analyses
        results = {
            'generated_at': datetime.now().isoformat(),
            'data_type': data_type,
            'affiliate_filter': affiliate or None,
            'date_filter': {
                'start': start_date,
                'end': end_date
            } if start_date and end_date else None,
            'profile': self.generate_profile(df, data_type),
            'distributions': self.analyze_distributions(df),
            'correlations': self.analyze_correlations(df, fraud_df),
            'quality_issues': self.check_data_quality(df),
            'outliers': self.detect_outliers(df)
        }
        
        self.analysis_results = results
        logger.info("Full EDA analysis complete")
        
        return results
    
    def export_to_json(self, filepath):
        """Export analysis results to JSON"""
        with open(filepath, 'w') as f:
            json.dump(self.analysis_results, f, indent=2, default=str)
        logger.info(f"Analysis exported to {filepath}")
