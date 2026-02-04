"""Database management for fraud detection system"""
import sqlite3
from datetime import datetime
from pathlib import Path
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class Database:
    # Valid table names (whitelist for SQL safety)
    VALID_TABLES = {'free', 'paid', 'fraud_results', 'fetch_history', 'session_results', 
                    'fraud_outcomes', 'detection_metrics', 'low_risk_samples'}
    
    def __init__(self, db_path='affiliate_data.db'):
        self.db_path = db_path
        self.conn = None
        self.setup_database()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections with WAL mode and timeout"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        # Enable WAL mode for better concurrency
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')  # 30 second timeout
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _validate_table_name(self, table_name):
        """Validate table name to prevent SQL injection"""
        if table_name not in self.VALID_TABLES:
            raise ValueError(f"Invalid table name: {table_name}. Must be one of: {self.VALID_TABLES}")

    def setup_database(self):
        """Create tables with proper schema and indexes"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        # Enable WAL mode for better concurrency
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
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

        # Fraud outcomes table - tracks confirmed fraud vs false positives
        c.execute('''CREATE TABLE IF NOT EXISTS fraud_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            duid TEXT UNIQUE NOT NULL,
            email TEXT,
            risk_score INTEGER,
            flags TEXT,
            payout_amount REAL,
            outcome TEXT NOT NULL,  -- 'confirmed_fraud', 'false_positive', 'under_review', 'legitimate'
            outcome_notes TEXT,
            reviewed_by TEXT,
            reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            detection_date TIMESTAMP,  -- when fraud detection flagged this
            resolution_date TIMESTAMP,  -- when outcome was determined
            actual_loss REAL DEFAULT 0,  -- actual financial loss if fraud confirmed
            recovery_amount REAL DEFAULT 0  -- amount recovered
        )''')

        # Detection metrics table - tracks precision/recall over time
        c.execute('''CREATE TABLE IF NOT EXISTS detection_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric_date DATE NOT NULL,
            risk_tier TEXT NOT NULL,  -- 'high', 'medium', 'low'
            total_flagged INTEGER DEFAULT 0,
            confirmed_fraud INTEGER DEFAULT 0,
            false_positives INTEGER DEFAULT 0,
            under_review INTEGER DEFAULT 0,
            precision_rate REAL,  -- confirmed / (confirmed + false_positive)
            total_payout_flagged REAL DEFAULT 0,
            actual_fraud_amount REAL DEFAULT 0,
            recovered_amount REAL DEFAULT 0,
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(metric_date, risk_tier)
        )''')

        # Low risk samples table - for false negative detection
        c.execute('''CREATE TABLE IF NOT EXISTS low_risk_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            duid TEXT NOT NULL,
            email TEXT,
            risk_score INTEGER,
            payout_amount REAL,
            sampled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            review_status TEXT DEFAULT 'pending',  -- 'pending', 'reviewed', 'missed_fraud', 'legitimate'
            review_notes TEXT,
            reviewed_at TIMESTAMP
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

    def _get_field(self, record, *field_names, default=None):
        """
        Get field value trying multiple possible field names.
        Handles API responses with different naming conventions.
        """
        for name in field_names:
            if name in record and record[name] is not None:
                return record[name]
        return default
    
    def _get_float(self, record, *field_names, default=0):
        """Get field as float, trying multiple names"""
        value = self._get_field(record, *field_names, default=default)
        try:
            return float(value) if value else default
        except (ValueError, TypeError):
            return default
    
    def _get_int(self, record, *field_names, default=0):
        """Get field as int, trying multiple names"""
        value = self._get_field(record, *field_names, default=default)
        try:
            return int(value) if value else default
        except (ValueError, TypeError):
            return default

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

                # Get DUID - try multiple field names
                duid = self._get_field(record, 'duid', 'DUID', 'Duid')
                if not duid:
                    logger.warning(f"Record {i} has no DUID, skipping")
                    errors += 1
                    continue

                c.execute('''INSERT INTO paid (
                    duid, email, trans_datetime, campaign, ad_id, sale_amount,
                    payout_amount, first_name, last_name, zip, ip, geo_country,
                    custom_u1, custom_http_user_agent, proc_name,
                    processor_subscriber_id, credit_count, credit_amount,
                    chargeback_count, chargeback_amount, ref_url,
                    webmaster_code, webmaster_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    duid,
                    self._get_field(record, 'email', 'Email'),
                    self._get_field(record, 'trans_datetime', 'Transaction Date Time', 'trans_date'),
                    self._get_field(record, 'campaign', 'Campaign'),
                    self._get_field(record, 'ad', 'ad_id', 'Ad ID'),
                    self._get_float(record, 'sale_amt', 'Sale Amount'),
                    self._get_float(record, 'payout', 'payout_amount', 'Payout Amount'),
                    self._get_field(record, 'first_name', 'First Name'),
                    self._get_field(record, 'last_name', 'Last Name'),
                    self._get_field(record, 'zip', 'Zip'),
                    self._get_field(record, 'ip', 'IP Address'),
                    self._get_field(record, 'geo_country_code', 'Geo Country'),
                    self._get_field(record, 'user1', 'User1 (user1)', 'custom_u1'),
                    self._get_field(record, 'CUSTOM_http_user_agent', 'HTTP User Agent'),
                    self._get_field(record, 'proc_name', 'Processor Name'),
                    self._get_field(record, 'proc_subscriber_id', 'Processor Subscriber ID'),
                    self._get_int(record, 'credit_count', 'Credit Count'),
                    self._get_float(record, 'credit_amount', 'Credit Amount'),
                    self._get_int(record, 'chargeback_count', 'Chargeback Count'),
                    self._get_float(record, 'chargeback_amount', 'Chargeback Amount'),
                    self._get_field(record, 'ref_url', 'Referer'),
                    self._get_field(record, 'webmaster_code', 'Webmaster Code'),
                    self._get_field(record, 'webmaster_id', 'Webmaster ID')
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

                # Get DUID - try multiple field names
                duid = self._get_field(record, 'duid', 'DUID', 'Duid')
                if not duid:
                    logger.warning(f"Record {i} has no DUID, skipping")
                    errors += 1
                    continue

                # Handle POV verified - can be various formats
                pov_verified = self._get_field(record, 'pov_verified', 'POV Verified', default=0)
                if isinstance(pov_verified, str):
                    pov_verified = pov_verified.lower() in ('1', 'true', 'yes')
                else:
                    pov_verified = bool(pov_verified)

                c.execute('''INSERT INTO free (
                    duid, email, username, site_code, tour_code, campaign, ad_id,
                    trans_datetime, ip, geo_country, user1, payout_amount,
                    custom_http_user_agent, pov_verified, pov_verified_time, ref_url,
                    webmaster_code, webmaster_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    duid,
                    self._get_field(record, 'email', 'Email'),
                    self._get_field(record, 'username', 'Username'),
                    self._get_field(record, 'site_code', 'Site Code'),
                    self._get_field(record, 'tour_code', 'Tour Code'),
                    self._get_field(record, 'campaign', 'Campaign'),
                    self._get_field(record, 'ad', 'ad_id', 'Ad ID'),
                    self._get_field(record, 'trans_datetime', 'Transaction Date Time', 'trans_date'),
                    self._get_field(record, 'ip', 'IP Address'),
                    self._get_field(record, 'geo_country_code', 'Geo Country'),
                    self._get_field(record, 'user1', 'User1 (user1)', 'custom_u1'),
                    self._get_float(record, 'payout', 'payout_amount', 'Payout Amount'),
                    self._get_field(record, 'CUSTOM_http_user_agent', 'HTTP User Agent'),
                    pov_verified,
                    self._get_field(record, 'pov_verified_time', 'POV Verified Time'),
                    self._get_field(record, 'ref_url', 'Referer'),
                    self._get_field(record, 'webmaster_code', 'Webmaster Code'),
                    self._get_field(record, 'webmaster_id', 'Webmaster ID')
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
        table = 'paid' if data_type == 'paid' else 'free'
        self._validate_table_name(table)
        
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute(f"SELECT MAX(trans_datetime) FROM {table}")
            result = c.fetchone()[0]
        
        return result

    def get_unanalyzed_records(self, data_type, limit=None):
        """Get records that haven't been analyzed yet"""
        table = 'paid' if data_type == 'paid' else 'free'
        self._validate_table_name(table)
        
        query = f"SELECT * FROM {table} WHERE analyzed = 0"
        if limit:
            query += f" LIMIT {int(limit)}"  # Ensure limit is an integer

        import pandas as pd
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn)

        return df

    def mark_as_analyzed(self, duids, data_type):
        """Mark records as analyzed"""
        table = 'paid' if data_type == 'paid' else 'free'
        self._validate_table_name(table)
        
        placeholders = ','.join('?' * len(duids))
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute(f"UPDATE {table} SET analyzed = 1 WHERE duid IN ({placeholders})", duids)

    def save_fraud_results(self, results):
        """Save fraud detection results"""
        with self.get_connection() as conn:
            c = conn.cursor()

            for result in results:
                try:
                    c.execute('''INSERT OR REPLACE INTO fraud_results (
                        duid, email, risk_score, flags, details, payout_amount, data_type,
                        webmaster_code, campaign
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        result['DUID'],
                        result['email'],
                        result['risk_score'],
                        str(result['flags']),
                        str(result['details']),
                        result.get('payout_amount', 0),
                        result.get('data_type', 'unknown'),
                        result.get('webmaster_code'),
                        result.get('campaign')
                    ))
                except Exception as e:
                    logger.error(f"Error saving fraud result for {result.get('DUID')}: {e}")
                    continue

    def get_fraud_statistics(self):
        """Get fraud detection statistics"""
        stats = {}
        
        with self.get_connection() as conn:
            c = conn.cursor()

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

        return stats

    def get_affiliate_fraud_stats(self, min_risk=25):
        """
        Get fraud statistics grouped by affiliate (webmaster_code).
        
        Args:
            min_risk: Minimum risk score to consider (default 25 for medium+)
        
        Returns:
            pandas DataFrame with affiliate fraud stats
        """
        import pandas as pd
        
        query = """
        SELECT 
            webmaster_code,
            COUNT(*) as total_accounts,
            SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) as high_risk_count,
            SUM(CASE WHEN risk_score >= 25 AND risk_score < 50 THEN 1 ELSE 0 END) as medium_risk_count,
            SUM(CASE WHEN risk_score < 25 THEN 1 ELSE 0 END) as low_risk_count,
            ROUND(AVG(risk_score), 1) as avg_risk_score,
            SUM(payout_amount) as total_payout,
            SUM(CASE WHEN risk_score >= 50 THEN payout_amount ELSE 0 END) as high_risk_payout,
            ROUND(SUM(CASE WHEN risk_score >= 50 THEN 1.0 ELSE 0 END) * 100.0 / COUNT(*), 1) as high_risk_pct
        FROM fraud_results
        WHERE webmaster_code IS NOT NULL AND webmaster_code != ''
        GROUP BY webmaster_code
        ORDER BY high_risk_count DESC, total_payout DESC
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn)
        
        return df

    def get_affiliate_comparison(self, webmaster_codes=None):
        """
        Compare fraud patterns across affiliates.
        
        Args:
            webmaster_codes: List of specific affiliates to compare (None for all)
        
        Returns:
            dict with comparison data
        """
        with self.get_connection() as conn:
            c = conn.cursor()
            
            # Overall stats for comparison
            c.execute("""
                SELECT 
                    COUNT(*) as total,
                    AVG(risk_score) as avg_risk,
                    SUM(CASE WHEN risk_score >= 50 THEN 1.0 ELSE 0 END) / COUNT(*) as high_risk_rate
                FROM fraud_results
            """)
            row = c.fetchone()
            overall = {
                'total': row[0],
                'avg_risk': row[1],
                'high_risk_rate': row[2]
            }
            
            return {'overall': overall}

    def get_fraud_by_affiliate(self, webmaster_code, min_risk=None, limit=100):
        """
        Get fraud results for a specific affiliate.
        
        Args:
            webmaster_code: The affiliate's webmaster code
            min_risk: Minimum risk score filter
            limit: Max records to return
        
        Returns:
            pandas DataFrame with fraud results for this affiliate
        """
        import pandas as pd
        
        query = "SELECT * FROM fraud_results WHERE webmaster_code = ?"
        params = [webmaster_code]
        
        if min_risk:
            query += " AND risk_score >= ?"
            params.append(min_risk)
        
        query += " ORDER BY risk_score DESC"
        
        if limit:
            query += f" LIMIT {limit}"
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        
        return df

    def get_cross_affiliate_patterns(self):
        """
        Find patterns that appear across multiple affiliates (potential platform-wide fraud).
        
        Returns:
            dict with cross-affiliate pattern analysis
        """
        patterns = {}
        
        with self.get_connection() as conn:
            c = conn.cursor()
            
            # Find email domains appearing with multiple affiliates
            c.execute("""
                SELECT 
                    SUBSTR(email, INSTR(email, '@') + 1) as domain,
                    COUNT(DISTINCT webmaster_code) as affiliate_count,
                    COUNT(*) as total_accounts,
                    AVG(risk_score) as avg_risk
                FROM fraud_results
                WHERE webmaster_code IS NOT NULL AND email LIKE '%@%'
                GROUP BY domain
                HAVING affiliate_count > 1 AND avg_risk >= 25
                ORDER BY affiliate_count DESC, avg_risk DESC
                LIMIT 20
            """)
            
            patterns['cross_affiliate_domains'] = [
                {'domain': row[0], 'affiliates': row[1], 'accounts': row[2], 'avg_risk': row[3]}
                for row in c.fetchall()
            ]
            
            # Find IPs appearing with multiple affiliates (from source tables)
            c.execute("""
                SELECT 
                    p.ip,
                    COUNT(DISTINCT p.webmaster_code) as affiliate_count,
                    COUNT(*) as total_accounts
                FROM paid p
                WHERE p.webmaster_code IS NOT NULL AND p.ip IS NOT NULL
                GROUP BY p.ip
                HAVING affiliate_count > 1 AND total_accounts > 2
                ORDER BY affiliate_count DESC
                LIMIT 20
            """)
            
            patterns['cross_affiliate_ips'] = [
                {'ip': row[0], 'affiliates': row[1], 'accounts': row[2]}
                for row in c.fetchall()
            ]
        
        return patterns

    def record_fetch(self, data_type, start_date, end_date, count):
        """Record a data fetch in history"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''INSERT INTO fetch_history (data_type, start_date, end_date, records_fetched)
                         VALUES (?, ?, ?, ?)''',
                      (data_type, start_date, end_date, count))

    def backfill_affiliates(self):
        """
        Backfill missing webmaster_code values in fraud_results from source tables.
        Looks up the DUID in free/paid tables and copies webmaster_code.
        
        Returns:
            dict with counts of updated records
        """
        with self.get_connection() as conn:
            c = conn.cursor()
            
            # Count records needing backfill
            c.execute("""
                SELECT COUNT(*) FROM fraud_results 
                WHERE webmaster_code IS NULL OR webmaster_code = ''
            """)
            needs_backfill = c.fetchone()[0]
            
            if needs_backfill == 0:
                return {'needs_backfill': 0, 'updated_from_free': 0, 'updated_from_paid': 0}
            
            # Update from free table
            c.execute("""
                UPDATE fraud_results
                SET webmaster_code = (
                    SELECT f.webmaster_code FROM free f 
                    WHERE f.duid = fraud_results.duid 
                    AND f.webmaster_code IS NOT NULL AND f.webmaster_code != ''
                    LIMIT 1
                )
                WHERE (webmaster_code IS NULL OR webmaster_code = '')
                AND EXISTS (
                    SELECT 1 FROM free f 
                    WHERE f.duid = fraud_results.duid 
                    AND f.webmaster_code IS NOT NULL AND f.webmaster_code != ''
                )
            """)
            updated_from_free = c.rowcount
            
            # Update from paid table
            c.execute("""
                UPDATE fraud_results
                SET webmaster_code = (
                    SELECT p.webmaster_code FROM paid p 
                    WHERE p.duid = fraud_results.duid 
                    AND p.webmaster_code IS NOT NULL AND p.webmaster_code != ''
                    LIMIT 1
                )
                WHERE (webmaster_code IS NULL OR webmaster_code = '')
                AND EXISTS (
                    SELECT 1 FROM paid p 
                    WHERE p.duid = fraud_results.duid 
                    AND p.webmaster_code IS NOT NULL AND p.webmaster_code != ''
                )
            """)
            updated_from_paid = c.rowcount
            
            logger.info(f"Backfilled affiliates: {updated_from_free} from free, {updated_from_paid} from paid")
            
            return {
                'needs_backfill': needs_backfill,
                'updated_from_free': updated_from_free,
                'updated_from_paid': updated_from_paid,
                'total_updated': updated_from_free + updated_from_paid
            }

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
            params.append(int(limit))
        
        with self.get_connection() as conn:
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
        
        return df

    # ==================== OUTCOME TRACKING METHODS ====================

    def record_fraud_outcome(self, duid, outcome, notes=None, reviewed_by=None, 
                             actual_loss=0, recovery_amount=0):
        """
        Record the outcome of a flagged account.
        
        Args:
            duid: Account DUID
            outcome: 'confirmed_fraud', 'false_positive', 'under_review', 'legitimate'
            notes: Optional notes about the review
            reviewed_by: Name/ID of reviewer
            actual_loss: Actual financial loss (for confirmed fraud)
            recovery_amount: Amount recovered
        
        Returns:
            True if successful, False otherwise
        """
        valid_outcomes = {'confirmed_fraud', 'false_positive', 'under_review', 'legitimate'}
        if outcome not in valid_outcomes:
            logger.error(f"Invalid outcome: {outcome}. Must be one of {valid_outcomes}")
            return False
        
        with self.get_connection() as conn:
            c = conn.cursor()
            
            # Get fraud result data for this DUID
            c.execute("""
                SELECT email, risk_score, flags, payout_amount, analyzed_at 
                FROM fraud_results WHERE duid = ?
            """, (duid,))
            result = c.fetchone()
            
            if not result:
                logger.warning(f"No fraud result found for DUID: {duid}")
                return False
            
            email, risk_score, flags, payout_amount, detection_date = result
            
            # Insert or update outcome
            c.execute("""
                INSERT INTO fraud_outcomes (
                    duid, email, risk_score, flags, payout_amount, outcome, 
                    outcome_notes, reviewed_by, detection_date, resolution_date,
                    actual_loss, recovery_amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(duid) DO UPDATE SET
                    outcome = excluded.outcome,
                    outcome_notes = excluded.outcome_notes,
                    reviewed_by = excluded.reviewed_by,
                    resolution_date = excluded.resolution_date,
                    actual_loss = excluded.actual_loss,
                    recovery_amount = excluded.recovery_amount,
                    reviewed_at = CURRENT_TIMESTAMP
            """, (
                duid, email, risk_score, flags, payout_amount, outcome,
                notes, reviewed_by, detection_date, datetime.now().isoformat(),
                actual_loss, recovery_amount
            ))
            
            logger.info(f"Recorded outcome '{outcome}' for DUID: {duid}")
            return True

    def get_pending_reviews(self, min_risk=50, limit=50):
        """
        Get flagged accounts that haven't been reviewed yet.
        
        Args:
            min_risk: Minimum risk score to include
            limit: Maximum accounts to return
        
        Returns:
            DataFrame of accounts pending review
        """
        import pandas as pd
        
        query = """
            SELECT fr.duid, fr.email, fr.risk_score, fr.flags, fr.payout_amount,
                   fr.analyzed_at, fr.data_type
            FROM fraud_results fr
            LEFT JOIN fraud_outcomes fo ON fr.duid = fo.duid
            WHERE fr.risk_score >= ?
              AND fo.duid IS NULL
            ORDER BY fr.risk_score DESC, fr.payout_amount DESC
            LIMIT ?
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=[min_risk, limit])
        
        return df

    def get_reviewed_outcomes(self, days=30, outcome_filter=None):
        """
        Get reviewed outcomes for analysis.
        
        Args:
            days: Number of days to look back
            outcome_filter: Filter by specific outcome (optional)
        
        Returns:
            DataFrame of reviewed outcomes
        """
        import pandas as pd
        
        query = """
            SELECT * FROM fraud_outcomes
            WHERE reviewed_at >= datetime('now', ?)
        """
        params = [f'-{days} days']
        
        if outcome_filter:
            query += " AND outcome = ?"
            params.append(outcome_filter)
        
        query += " ORDER BY reviewed_at DESC"
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        
        return df

    def get_effectiveness_metrics(self):
        """
        Calculate detection effectiveness metrics.
        
        Returns:
            Dictionary with precision, recall estimates, and other metrics
        """
        metrics = {
            'total_flagged_high': 0,
            'total_flagged_medium': 0,
            'reviewed_high': 0,
            'reviewed_medium': 0,
            'confirmed_fraud_high': 0,
            'confirmed_fraud_medium': 0,
            'false_positives_high': 0,
            'false_positives_medium': 0,
            'precision_high': None,
            'precision_medium': None,
            'total_payout_at_risk': 0,
            'confirmed_fraud_amount': 0,
            'false_positive_amount': 0,
            'recovery_amount': 0,
            'missed_fraud_count': 0,  # From low-risk samples
            'estimated_false_negative_rate': None
        }
        
        with self.get_connection() as conn:
            c = conn.cursor()
            
            # Total flagged by risk tier
            c.execute("SELECT COUNT(*) FROM fraud_results WHERE risk_score >= 50")
            metrics['total_flagged_high'] = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM fraud_results WHERE risk_score >= 25 AND risk_score < 50")
            metrics['total_flagged_medium'] = c.fetchone()[0]
            
            # Reviewed counts by tier and outcome
            c.execute("""
                SELECT outcome, COUNT(*), SUM(payout_amount), SUM(actual_loss), SUM(recovery_amount)
                FROM fraud_outcomes 
                WHERE risk_score >= 50
                GROUP BY outcome
            """)
            for row in c.fetchall():
                outcome, count, payout, loss, recovery = row
                metrics['reviewed_high'] += count
                if outcome == 'confirmed_fraud':
                    metrics['confirmed_fraud_high'] = count
                    metrics['confirmed_fraud_amount'] += (loss or 0)
                    metrics['recovery_amount'] += (recovery or 0)
                elif outcome == 'false_positive':
                    metrics['false_positives_high'] = count
                    metrics['false_positive_amount'] += (payout or 0)
            
            c.execute("""
                SELECT outcome, COUNT(*), SUM(payout_amount)
                FROM fraud_outcomes 
                WHERE risk_score >= 25 AND risk_score < 50
                GROUP BY outcome
            """)
            for row in c.fetchall():
                outcome, count, payout = row
                metrics['reviewed_medium'] += count
                if outcome == 'confirmed_fraud':
                    metrics['confirmed_fraud_medium'] = count
                elif outcome == 'false_positive':
                    metrics['false_positives_medium'] = count
            
            # Calculate precision (if we have enough data)
            reviewed_high = metrics['confirmed_fraud_high'] + metrics['false_positives_high']
            if reviewed_high > 0:
                metrics['precision_high'] = metrics['confirmed_fraud_high'] / reviewed_high
            
            reviewed_medium = metrics['confirmed_fraud_medium'] + metrics['false_positives_medium']
            if reviewed_medium > 0:
                metrics['precision_medium'] = metrics['confirmed_fraud_medium'] / reviewed_medium
            
            # Total payout at risk
            c.execute("SELECT SUM(payout_amount) FROM fraud_results WHERE risk_score >= 50")
            result = c.fetchone()[0]
            metrics['total_payout_at_risk'] = result or 0
            
            # Missed fraud from low-risk samples
            c.execute("SELECT COUNT(*) FROM low_risk_samples WHERE review_status = 'missed_fraud'")
            metrics['missed_fraud_count'] = c.fetchone()[0]
            
            # Estimate false negative rate from samples
            c.execute("SELECT COUNT(*) FROM low_risk_samples WHERE review_status IN ('missed_fraud', 'legitimate')")
            total_low_risk_reviewed = c.fetchone()[0]
            if total_low_risk_reviewed > 0:
                metrics['estimated_false_negative_rate'] = metrics['missed_fraud_count'] / total_low_risk_reviewed
        
        return metrics

    def sample_low_risk_accounts(self, count=20, max_risk=24):
        """
        Randomly sample low-risk accounts for false negative detection.
        
        Args:
            count: Number of accounts to sample
            max_risk: Maximum risk score to sample from
        
        Returns:
            DataFrame of sampled accounts
        """
        import pandas as pd
        
        with self.get_connection() as conn:
            # Get random sample of low-risk accounts not already sampled
            query = """
                SELECT fr.duid, fr.email, fr.risk_score, fr.flags, fr.payout_amount
                FROM fraud_results fr
                LEFT JOIN low_risk_samples lrs ON fr.duid = lrs.duid
                WHERE fr.risk_score <= ?
                  AND lrs.duid IS NULL
                ORDER BY RANDOM()
                LIMIT ?
            """
            df = pd.read_sql_query(query, conn, params=[max_risk, count])
            
            # Record the samples
            c = conn.cursor()
            for _, row in df.iterrows():
                c.execute("""
                    INSERT INTO low_risk_samples (duid, email, risk_score, payout_amount)
                    VALUES (?, ?, ?, ?)
                """, (row['duid'], row['email'], row['risk_score'], row['payout_amount']))
        
        return df

    def record_low_risk_review(self, duid, status, notes=None):
        """
        Record review of a low-risk sample.
        
        Args:
            duid: Account DUID
            status: 'missed_fraud' or 'legitimate'
            notes: Optional review notes
        
        Returns:
            True if successful
        """
        valid_statuses = {'missed_fraud', 'legitimate', 'reviewed'}
        if status not in valid_statuses:
            logger.error(f"Invalid status: {status}")
            return False
        
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE low_risk_samples 
                SET review_status = ?, review_notes = ?, reviewed_at = CURRENT_TIMESTAMP
                WHERE duid = ?
            """, (status, notes, duid))
            
            if c.rowcount == 0:
                logger.warning(f"No low-risk sample found for DUID: {duid}")
                return False
        
        return True

    def get_low_risk_samples(self, status='pending'):
        """
        Get low-risk samples by review status.
        
        Args:
            status: 'pending', 'reviewed', 'missed_fraud', 'legitimate', or 'all'
        
        Returns:
            DataFrame of samples
        """
        import pandas as pd
        
        query = "SELECT * FROM low_risk_samples"
        params = []
        
        if status != 'all':
            query += " WHERE review_status = ?"
            params.append(status)
        
        query += " ORDER BY sampled_at DESC"
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        
        return df

    def calculate_and_store_metrics(self, metric_date=None):
        """
        Calculate detection metrics and store them for historical tracking.
        
        Args:
            metric_date: Date to calculate metrics for (defaults to today)
        """
        if metric_date is None:
            metric_date = datetime.now().strftime('%Y-%m-%d')
        
        with self.get_connection() as conn:
            c = conn.cursor()
            
            for tier, min_score, max_score in [('high', 50, 999), ('medium', 25, 49), ('low', 0, 24)]:
                # Get counts
                c.execute("""
                    SELECT COUNT(*), SUM(payout_amount) 
                    FROM fraud_results 
                    WHERE risk_score >= ? AND risk_score <= ?
                """, (min_score, max_score))
                total_flagged, total_payout = c.fetchone()
                total_flagged = total_flagged or 0
                total_payout = total_payout or 0
                
                # Get outcome counts
                c.execute("""
                    SELECT 
                        SUM(CASE WHEN outcome = 'confirmed_fraud' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN outcome = 'false_positive' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN outcome = 'under_review' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN outcome = 'confirmed_fraud' THEN actual_loss ELSE 0 END),
                        SUM(recovery_amount)
                    FROM fraud_outcomes
                    WHERE risk_score >= ? AND risk_score <= ?
                """, (min_score, max_score))
                result = c.fetchone()
                confirmed = result[0] or 0
                false_pos = result[1] or 0
                under_review = result[2] or 0
                fraud_amount = result[3] or 0
                recovered = result[4] or 0
                
                # Calculate precision
                precision = None
                if (confirmed + false_pos) > 0:
                    precision = confirmed / (confirmed + false_pos)
                
                # Store metrics
                c.execute("""
                    INSERT INTO detection_metrics (
                        metric_date, risk_tier, total_flagged, confirmed_fraud,
                        false_positives, under_review, precision_rate,
                        total_payout_flagged, actual_fraud_amount, recovered_amount
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(metric_date, risk_tier) DO UPDATE SET
                        total_flagged = excluded.total_flagged,
                        confirmed_fraud = excluded.confirmed_fraud,
                        false_positives = excluded.false_positives,
                        under_review = excluded.under_review,
                        precision_rate = excluded.precision_rate,
                        total_payout_flagged = excluded.total_payout_flagged,
                        actual_fraud_amount = excluded.actual_fraud_amount,
                        recovered_amount = excluded.recovered_amount,
                        calculated_at = CURRENT_TIMESTAMP
                """, (
                    metric_date, tier, total_flagged, confirmed, false_pos,
                    under_review, precision, total_payout, fraud_amount, recovered
                ))
        
        logger.info(f"Calculated and stored metrics for {metric_date}")

    def get_metrics_history(self, days=30, tier=None):
        """
        Get historical detection metrics.
        
        Args:
            days: Number of days to look back
            tier: Filter by risk tier ('high', 'medium', 'low', or None for all)
        
        Returns:
            DataFrame of historical metrics
        """
        import pandas as pd
        
        query = """
            SELECT * FROM detection_metrics
            WHERE metric_date >= date('now', ?)
        """
        params = [f'-{days} days']
        
        if tier:
            query += " AND risk_tier = ?"
            params.append(tier)
        
        query += " ORDER BY metric_date DESC, risk_tier"
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        
        return df

    # ==================== BILLING CORRELATION METHODS ====================

    def get_billing_correlations(self, min_accounts=2):
        """
        DEPRECATED: processor_subscriber_id data is unreliable for fraud detection.
        Returns empty DataFrame to maintain API compatibility.
        """
        import pandas as pd
        return pd.DataFrame(columns=['processor_subscriber_id', 'proc_name', 'account_count', 
                                     'duids', 'emails', 'total_payout', 'total_sales', 
                                     'avg_chargebacks', 'names'])

    def get_billing_cluster_details(self, processor_subscriber_id):
        """
        DEPRECATED: processor_subscriber_id data is unreliable for fraud detection.
        Returns empty DataFrame to maintain API compatibility.
        """
        import pandas as pd
        return pd.DataFrame(columns=['duid', 'email', 'first_name', 'last_name',
                                     'trans_datetime', 'sale_amount', 'payout_amount',
                                     'chargeback_count', 'chargeback_amount',
                                     'credit_count', 'credit_amount',
                                     'ip', 'geo_country', 'zip', 'risk_score', 'flags'])

    def get_name_correlations(self, min_accounts=3):
        """
        Find accounts with similar billing names (potential fraud rings).
        
        Args:
            min_accounts: Minimum accounts with same name
        
        Returns:
            DataFrame with name clusters
        """
        import pandas as pd
        
        # Exact name match
        query = """
            SELECT 
                LOWER(first_name || ' ' || last_name) as full_name,
                COUNT(*) as account_count,
                COUNT(DISTINCT processor_subscriber_id) as unique_cards,
                GROUP_CONCAT(DISTINCT email) as emails,
                SUM(payout_amount) as total_payout,
                SUM(chargeback_count) as total_chargebacks
            FROM paid
            WHERE first_name IS NOT NULL AND last_name IS NOT NULL
              AND first_name != '' AND last_name != ''
            GROUP BY LOWER(first_name || ' ' || last_name)
            HAVING COUNT(*) >= ?
            ORDER BY account_count DESC
        """
        
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=[min_accounts])
        
        return df

    def get_ip_billing_correlations(self):
        """
        DEPRECATED: Relies on unreliable processor_subscriber_id data.
        Returns empty DataFrame to maintain API compatibility.
        """
        import pandas as pd
        return pd.DataFrame(columns=['ip', 'unique_cards', 'total_transactions', 
                                     'emails', 'total_payout', 'total_chargebacks'])

    def get_high_risk_billing_summary(self):
        """
        Get summary of billing-related fraud indicators.
        NOTE: Shared billing clusters by processor_subscriber_id are disabled (unreliable data).
        
        Returns:
            Dictionary with billing fraud metrics
        """
        summary = {
            'shared_billing_clusters': 0,  # Disabled - unreliable data
            'accounts_in_clusters': 0,  # Disabled - unreliable data
            'total_payout_at_risk': 0,  # Disabled - unreliable data
            'multi_card_ips': 0,
            'name_clusters': 0,
            'high_chargeback_accounts': 0
        }
        
        with self.get_connection() as conn:
            c = conn.cursor()
            
            # Shared billing clusters - DISABLED (unreliable processor_subscriber_id data)
            # Kept at 0
            
            # IPs with multiple cards - DISABLED (relies on processor_subscriber_id)
            # Kept at 0
            
            # Name clusters
            c.execute("""
                SELECT COUNT(*)
                FROM (
                    SELECT LOWER(first_name || ' ' || last_name)
                    FROM paid
                    WHERE first_name IS NOT NULL AND last_name IS NOT NULL
                    GROUP BY LOWER(first_name || ' ' || last_name)
                    HAVING COUNT(*) >= 3
                )
            """)
            summary['name_clusters'] = c.fetchone()[0] or 0
            
            # High chargeback accounts
            c.execute("SELECT COUNT(*) FROM paid WHERE chargeback_count >= 1")
            summary['high_chargeback_accounts'] = c.fetchone()[0] or 0
        
        return summary
