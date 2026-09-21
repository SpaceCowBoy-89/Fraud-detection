"""
Data Preprocessing Module

Automatic data cleaning and enrichment for fraud detection.
Runs before fraud analysis to improve data quality.

Features:
- Email normalization and validation
- Amount validation and outlier detection
- Data enrichment (time-based features, risk scores)
- Quality reporting
"""

import re
import logging
from datetime import datetime
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class DataPreprocessor:
    """
    Automatic data preprocessing for fraud detection
    """
    
    def __init__(self):
        # Known disposable email domains
        self.disposable_domains = {
            'tempmail.org', 'temp-mail.org', 'guerrillamail.com',
            'mailinator.com', '10minutemail.com', 'throwaway.email',
            'getnada.com', 'maildrop.cc', 'trashmail.com'
        }
        
        # Statistics for outlier detection
        self.amount_stats = None
        
    def clean_email(self, email):
        """
        Normalize and validate email addresses
        
        Args:
            email: Raw email string
            
        Returns:
            dict with cleaned email and flags
        """
        if not email or not isinstance(email, str):
            return {
                'cleaned': None,
                'valid': False,
                'disposable': False,
                'domain': None
            }
        
        # Normalize
        cleaned = email.strip().lower()
        
        # Validate format
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        valid = bool(re.match(email_pattern, cleaned))
        
        # Extract domain
        domain = None
        disposable = False
        if valid and '@' in cleaned:
            domain = cleaned.split('@')[1]
            disposable = domain in self.disposable_domains
        
        return {
            'cleaned': cleaned if valid else None,
            'valid': valid,
            'disposable': disposable,
            'domain': domain
        }
    
    def validate_amount(self, amount, amount_type='payout'):
        """
        Validate and detect outliers in monetary amounts
        
        Args:
            amount: Numeric amount
            amount_type: 'payout' or 'sale'
            
        Returns:
            dict with validation results and flags
        """
        result = {
            'valid': False,
            'outlier': False,
            'z_score': None,
            'flags': []
        }
        
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            result['flags'].append('INVALID_AMOUNT')
            return result
        
        # Basic validation
        if amount < 0:
            result['flags'].append('NEGATIVE_AMOUNT')
            return result
        
        if amount == 0:
            result['flags'].append('ZERO_AMOUNT')
        
        result['valid'] = True
        
        # Outlier detection (if we have stats)
        if self.amount_stats and amount_type in self.amount_stats:
            stats = self.amount_stats[amount_type]
            mean = stats['mean']
            std = stats['std']
            
            if std > 0:
                z_score = abs((amount - mean) / std)
                result['z_score'] = z_score
                
                if z_score > 3:
                    result['outlier'] = True
                    result['flags'].append('OUTLIER_AMOUNT')
        
        # Decimal point error detection (e.g., 10000 instead of 100.00)
        if amount > 1000 and amount_type == 'payout':
            result['flags'].append('POSSIBLE_DECIMAL_ERROR')
        
        return result
    
    def calculate_amount_statistics(self, df, amount_col='payout_amount'):
        """
        Calculate statistics for amount validation
        
        Args:
            df: DataFrame with amount data
            amount_col: Column name for amounts
        """
        if amount_col not in df.columns:
            return
        
        amounts = pd.to_numeric(df[amount_col], errors='coerce')
        amounts = amounts[amounts > 0]  # Exclude zero/negative
        
        if len(amounts) > 0:
            self.amount_stats = {
                'payout': {
                    'mean': amounts.mean(),
                    'std': amounts.std(),
                    'median': amounts.median(),
                    'q1': amounts.quantile(0.25),
                    'q3': amounts.quantile(0.75)
                }
            }
    
    def enrich_record(self, record):
        """
        Add derived fields to a record
        
        Args:
            record: Dictionary or Series with record data
            
        Returns:
            dict with enriched fields
        """
        enriched = {}
        
        # Extract time-based features
        if 'trans_datetime' in record and record['trans_datetime']:
            try:
                dt = pd.to_datetime(record['trans_datetime'])
                enriched['hour_of_day'] = dt.hour
                enriched['day_of_week'] = dt.dayofweek  # 0=Monday, 6=Sunday
                enriched['is_weekend'] = dt.dayofweek >= 5
                enriched['is_night'] = dt.hour < 6 or dt.hour >= 22
            except:
                pass
        
        # Domain risk score (simple heuristic)
        if 'email' in record:
            email_info = self.clean_email(record['email'])
            if email_info['disposable']:
                enriched['domain_risk'] = 'high'
            elif email_info['domain'] in ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com']:
                enriched['domain_risk'] = 'low'
            else:
                enriched['domain_risk'] = 'medium'
        
        return enriched
    
    def preprocess_batch(self, df, report=True):
        """
        Preprocess entire DataFrame
        
        Args:
            df: pandas DataFrame
            report: Generate quality report
            
        Returns:
            tuple: (cleaned_df, quality_report)
        """
        logger.info(f"Preprocessing {len(df)} records...")
        
        quality_report = {
            'total_records': len(df),
            'emails_cleaned': 0,
            'invalid_emails': 0,
            'disposable_emails': 0,
            'amount_outliers': 0,
            'invalid_amounts': 0,
            'enriched_fields': []
        }
        
        # Calculate amount statistics first
        if 'payout_amount' in df.columns:
            self.calculate_amount_statistics(df, 'payout_amount')
        
        # Clean emails
        if 'email' in df.columns:
            email_results = df['email'].apply(self.clean_email)
            df['email_cleaned'] = email_results.apply(lambda x: x['cleaned'])
            df['email_valid'] = email_results.apply(lambda x: x['valid'])
            df['email_disposable'] = email_results.apply(lambda x: x['disposable'])
            df['email_domain'] = email_results.apply(lambda x: x['domain'])
            
            quality_report['emails_cleaned'] = email_results.apply(lambda x: x['valid']).sum()
            quality_report['invalid_emails'] = len(df) - quality_report['emails_cleaned']
            quality_report['disposable_emails'] = email_results.apply(lambda x: x['disposable']).sum()
            quality_report['enriched_fields'].extend(['email_cleaned', 'email_valid', 'email_disposable', 'email_domain'])
        
        # Validate amounts
        if 'payout_amount' in df.columns:
            amount_results = df['payout_amount'].apply(lambda x: self.validate_amount(x, 'payout'))
            df['amount_valid'] = amount_results.apply(lambda x: x['valid'])
            df['amount_outlier'] = amount_results.apply(lambda x: x['outlier'])
            df['amount_z_score'] = amount_results.apply(lambda x: x['z_score'])
            
            quality_report['invalid_amounts'] = len(df) - amount_results.apply(lambda x: x['valid']).sum()
            quality_report['amount_outliers'] = amount_results.apply(lambda x: x['outlier']).sum()
            quality_report['enriched_fields'].extend(['amount_valid', 'amount_outlier', 'amount_z_score'])
        
        # Enrich records with derived fields
        enriched_fields = df.apply(self.enrich_record, axis=1)
        for col in ['hour_of_day', 'day_of_week', 'is_weekend', 'is_night', 'domain_risk']:
            if col in enriched_fields.iloc[0] if len(enriched_fields) > 0 else {}:
                df[col] = enriched_fields.apply(lambda x: x.get(col))
                quality_report['enriched_fields'].append(col)
        
        logger.info(f"Preprocessing complete: {quality_report['emails_cleaned']} valid emails, "
                   f"{quality_report['disposable_emails']} disposable, "
                   f"{quality_report['amount_outliers']} amount outliers")
        
        return df, quality_report if report else df
    
    def get_outlier_duids(self, df):
        """
        Get list of DUIDs flagged as outliers
        
        Args:
            df: Preprocessed DataFrame
            
        Returns:
            list of DUIDs with outlier flags
        """
        outliers = []
        
        if 'duid' in df.columns:
            # Amount outliers
            if 'amount_outlier' in df.columns:
                amount_outliers = df[df['amount_outlier'] == True]['duid'].tolist()
                outliers.extend(amount_outliers)
            
            # Disposable email
            if 'email_disposable' in df.columns:
                disposable_outliers = df[df['email_disposable'] == True]['duid'].tolist()
                outliers.extend(disposable_outliers)
        
        return list(set(outliers))  # Remove duplicates


# Convenience function for quick preprocessing
def preprocess(df, report=True):
    """
    Quick preprocessing function
    
    Args:
        df: pandas DataFrame
        report: Generate quality report
        
    Returns:
        tuple: (cleaned_df, quality_report) or just cleaned_df
    """
    preprocessor = DataPreprocessor()
    return preprocessor.preprocess_batch(df, report=report)
