"""Database management for fraud detection system"""
import sqlite3
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path='affiliate_data.db'):
        self.db_path = db_path
        self.conn = None
        self.setup_database()

    def setup_database(self):
        """Create tables with proper schema and indexes"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Paid transactions (sales) table
        c.execute('''CREATE TABLE IF NOT EXISTS paid (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            duid TEXT UNIQUE NOT NULL,
            email TEXT,
            trans_datetime TIMESTAMP,
            campaign TEXT,
            ad_id TEXT,
            sale_amount REAL,
            payout_amount REAL,
            first_name TEXT,
            last_name TEXT,
            zip TEXT,
            ip TEXT,
            geo_country TEXT,
            custom_u1 TEXT,
            custom_http_user_agent TEXT,
            proc_name TEXT,
            processor_subscriber_id TEXT,
            credit_count INTEGER,
            credit_amount REAL,
            chargeback_count INTEGER,
            chargeback_amount REAL,
            ref_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            analyzed BOOLEAN DEFAULT 0
        )''')

        # Free signups (leads) table
        c.execute('''CREATE TABLE IF NOT EXISTS free (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            duid TEXT UNIQUE NOT NULL,
            email TEXT,
            username TEXT,
            site_code TEXT,
            tour_code TEXT,
            campaign TEXT,
            ad_id TEXT,
            trans_datetime TIMESTAMP,
            ip TEXT,
            geo_country TEXT,
            user1 TEXT,
            payout_amount REAL,
            custom_http_user_agent TEXT,
            pov_verified BOOLEAN,
            pov_verified_time TIMESTAMP,
            ref_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            analyzed BOOLEAN DEFAULT 0
        )''')

        # Fraud detection results table
        c.execute('''CREATE TABLE IF NOT EXISTS fraud_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            duid TEXT UNIQUE NOT NULL,
            email TEXT,
            risk_score INTEGER,
            flags TEXT,
            details TEXT,
            payout_amount REAL,
            data_type TEXT,
            analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Fetch history table
        c.execute('''CREATE TABLE IF NOT EXISTS fetch_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_type TEXT,
            start_date TEXT,
            end_date TEXT,
            records_fetched INTEGER,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Create indexes for performance
        indexes = [
            'CREATE INDEX IF NOT EXISTS idx_paid_duid ON paid(duid)',
            'CREATE INDEX IF NOT EXISTS idx_paid_email ON paid(email)',
            'CREATE INDEX IF NOT EXISTS idx_paid_ip ON paid(ip)',
            'CREATE INDEX IF NOT EXISTS idx_paid_analyzed ON paid(analyzed)',
            'CREATE INDEX IF NOT EXISTS idx_free_duid ON free(duid)',
            'CREATE INDEX IF NOT EXISTS idx_free_email ON free(email)',
            'CREATE INDEX IF NOT EXISTS idx_free_ip ON free(ip)',
            'CREATE INDEX IF NOT EXISTS idx_free_analyzed ON free(analyzed)',
            'CREATE INDEX IF NOT EXISTS idx_fraud_risk ON fraud_results(risk_score)',
            'CREATE INDEX IF NOT EXISTS idx_fraud_duid ON fraud_results(duid)',
        ]

        for index in indexes:
            c.execute(index)

        conn.commit()
        conn.close()
        logger.info(f"Database setup complete: {self.db_path}")

    def insert_paid_records(self, records):
        """Insert paid transaction records"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        inserted = 0
        duplicates = 0
        errors = 0

        for i, record in enumerate(records):
            try:
                # Validate record is a dict
                if not isinstance(record, dict):
                    logger.error(f"Record {i} is not a dict: {type(record)}")
                    errors += 1
                    continue

                # Debug: log first record structure
                if i == 0:
                    logger.info(f"First record keys: {list(record.keys())}")

                c.execute('''INSERT INTO paid (
                    duid, email, trans_datetime, campaign, ad_id, sale_amount,
                    payout_amount, first_name, last_name, zip, ip, geo_country,
                    custom_u1, custom_http_user_agent, proc_name,
                    processor_subscriber_id, credit_count, credit_amount,
                    chargeback_count, chargeback_amount, ref_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    record.get('DUID'),
                    record.get('Email'),
                    record.get('Transaction Date Time'),
                    record.get('Campaign'),
                    record.get('Ad ID'),
                    float(record.get('Sale Amount', 0) or 0),
                    float(record.get('Payout Amount', 0) or 0),
                    record.get('First Name'),
                    record.get('Last Name'),
                    record.get('Zip'),
                    record.get('IP Address'),
                    record.get('Geo Country'),
                    record.get('User1 (user1)'),
                    record.get('HTTP User Agent'),
                    record.get('Processor Name'),
                    record.get('Processor Subscriber ID'),
                    int(record.get('Credit Count', 0) or 0),
                    float(record.get('Credit Amount', 0) or 0),
                    int(record.get('Chargeback Count', 0) or 0),
                    float(record.get('Chargeback Amount', 0) or 0),
                    record.get('Referer')
                ))
                inserted += 1
            except sqlite3.IntegrityError:
                duplicates += 1
                continue
            except Exception as e:
                logger.error(f"Error inserting record {i}: {e}")
                logger.error(f"Record type: {type(record)}, content: {record}")
                errors += 1
                continue

        conn.commit()
        conn.close()

        logger.info(f"Inserted {inserted} paid records, {duplicates} duplicates skipped, {errors} errors")
        return inserted, duplicates

    def insert_free_records(self, records):
        """Insert free signup (leads) records"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        inserted = 0
        duplicates = 0
        errors = 0

        for i, record in enumerate(records):
            try:
                # Validate record is a dict
                if not isinstance(record, dict):
                    logger.error(f"Record {i} is not a dict: {type(record)}")
                    errors += 1
                    continue

                # Debug: log first record structure
                if i == 0:
                    logger.info(f"First record keys: {list(record.keys())}")

                c.execute('''INSERT INTO free (
                    duid, email, username, site_code, tour_code, campaign, ad_id,
                    trans_datetime, ip, geo_country, user1, payout_amount,
                    custom_http_user_agent, pov_verified, pov_verified_time, ref_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    record.get('DUID'),
                    record.get('Email'),
                    record.get('Username'),
                    record.get('Site Code'),
                    record.get('Tour Code'),
                    record.get('Campaign'),
                    record.get('Ad ID'),
                    record.get('Transaction Date Time'),
                    record.get('IP Address'),
                    record.get('Geo Country'),
                    record.get('User1 (user1)'),
                    float(record.get('Payout Amount', 0) or 0),
                    record.get('HTTP User Agent'),
                    bool(record.get('POV Verified', 0)),
                    record.get('POV Verified Time'),
                    record.get('Referer')
                ))
                inserted += 1
            except sqlite3.IntegrityError:
                duplicates += 1
                continue
            except Exception as e:
                logger.error(f"Error inserting record {i}: {e}")
                logger.error(f"Record type: {type(record)}, content: {record}")
                errors += 1
                continue

        conn.commit()
        conn.close()

        logger.info(f"Inserted {inserted} free records, {duplicates} duplicates skipped, {errors} errors")
        return inserted, duplicates

    def get_last_fetch_date(self, data_type):
        """Get the last fetch date for incremental updates"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        table = 'paid' if data_type == 'paid' else 'free'
        c.execute(f"SELECT MAX(trans_datetime) FROM {table}")
        result = c.fetchone()[0]

        conn.close()
        return result

    def get_unanalyzed_records(self, data_type, limit=None):
        """Get records that haven't been analyzed yet"""
        conn = sqlite3.connect(self.db_path)

        table = 'paid' if data_type == 'paid' else 'free'
        query = f"SELECT * FROM {table} WHERE analyzed = 0"

        if limit:
            query += f" LIMIT {limit}"

        import pandas as pd
        df = pd.read_sql_query(query, conn)
        conn.close()

        return df

    def mark_as_analyzed(self, duids, data_type):
        """Mark records as analyzed"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        table = 'paid' if data_type == 'paid' else 'free'
        placeholders = ','.join('?' * len(duids))
        c.execute(f"UPDATE {table} SET analyzed = 1 WHERE duid IN ({placeholders})", duids)

        conn.commit()
        conn.close()

    def save_fraud_results(self, results):
        """Save fraud detection results"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        for result in results:
            try:
                c.execute('''INSERT OR REPLACE INTO fraud_results (
                    duid, email, risk_score, flags, details, payout_amount, data_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (
                    result['DUID'],
                    result['email'],
                    result['risk_score'],
                    str(result['flags']),
                    str(result['details']),
                    result.get('payout_amount', 0),
                    result.get('data_type', 'unknown')
                ))
            except Exception as e:
                logger.error(f"Error saving fraud result for {result.get('DUID')}: {e}")
                continue

        conn.commit()
        conn.close()

    def get_fraud_statistics(self):
        """Get fraud detection statistics"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        stats = {}

        # Total analyzed
        c.execute("SELECT COUNT(*) FROM fraud_results")
        stats['total_analyzed'] = c.fetchone()[0]

        # High risk count
        c.execute("SELECT COUNT(*) FROM fraud_results WHERE risk_score >= 50")
        stats['high_risk'] = c.fetchone()[0]

        # Medium risk count
        c.execute("SELECT COUNT(*) FROM fraud_results WHERE risk_score >= 25 AND risk_score < 50")
        stats['medium_risk'] = c.fetchone()[0]

        # Revenue at risk
        c.execute("SELECT SUM(payout_amount) FROM fraud_results WHERE risk_score >= 50")
        result = c.fetchone()[0]
        stats['revenue_at_risk'] = result if result else 0

        # Last analysis date
        c.execute("SELECT MAX(analyzed_at) FROM fraud_results")
        stats['last_analysis'] = c.fetchone()[0]

        conn.close()
        return stats

    def record_fetch(self, data_type, start_date, end_date, count):
        """Record a data fetch in history"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute('''INSERT INTO fetch_history (data_type, start_date, end_date, records_fetched)
                     VALUES (?, ?, ?, ?)''',
                  (data_type, start_date, end_date, count))

        conn.commit()
        conn.close()

    def get_fraud_results(self, data_type=None, min_risk=None, limit=None):
        """
        Get fraud results as DataFrame.
        
        Args:
            data_type: Filter by 'free' or 'paid' (None for all)
            min_risk: Minimum risk score (None for all)
            limit: Maximum number of records (None for all)
        
        Returns:
            pandas DataFrame with fraud results
        """
        import pandas as pd
        
        conn = sqlite3.connect(self.db_path)
        
        query = "SELECT * FROM fraud_results WHERE 1=1"
        params = []
        
        if data_type:
            query += " AND data_type = ?"
            params.append(data_type)
        
        if min_risk is not None:
            query += " AND risk_score >= ?"
            params.append(min_risk)
        
        query += " ORDER BY risk_score DESC"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        df = pd.read_sql_query(query, conn, params=params)
        
        # Join with free/paid tables to get additional fields
        if len(df) > 0:
            # Get DUIDs
            duids = df['duid'].tolist()
            placeholders = ','.join(['?'] * len(duids))
            
            # Get free data
            free_query = f"""
                SELECT duid, email, ip, geo_country, pov_verified, pov_verified_time, 
                       trans_datetime, campaign, ad_id
                FROM free 
                WHERE duid IN ({placeholders})
            """
            free_df = pd.read_sql_query(free_query, conn, params=duids)
            
            # Get paid data
            paid_query = f"""
                SELECT duid, email, ip, geo_country, first_name, last_name,
                       trans_datetime, campaign, ad_id
                FROM paid 
                WHERE duid IN ({placeholders})
            """
            paid_df = pd.read_sql_query(paid_query, conn, params=duids)
            
            # Merge free data
            if len(free_df) > 0:
                df = df.merge(free_df, on='duid', how='left', suffixes=('', '_free'))
                # Calculate pov_seconds if available
                if 'pov_verified_time' in df.columns and 'trans_datetime' in df.columns:
                    df['pov_seconds'] = pd.to_datetime(df['pov_verified_time']) - pd.to_datetime(df['trans_datetime'])
                    df['pov_seconds'] = df['pov_seconds'].dt.total_seconds()
            
            # Merge paid data
            if len(paid_df) > 0:
                df = df.merge(paid_df, on='duid', how='left', suffixes=('', '_paid'))
        
        conn.close()
        return df
