#!/usr/bin/env python3
"""
Initialize database tables if they don't exist.
Run this before migrate_database.py if you have a fresh database.
"""

import sqlite3
import sys
import os

DB_PATH = 'affiliate_data.db'

def init_database():
    """Create database tables if they don't exist"""
    
    print("🔄 DATABASE INITIALIZATION")
    print("=" * 60)
    
    if not os.path.exists(DB_PATH):
        print(f"Creating new database: {DB_PATH}")
    else:
        print(f"Using existing database: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = {row[0] for row in cursor.fetchall()}
    
    print(f"\nExisting tables: {existing_tables or 'None'}")
    
    tables_created = []
    
    # Create paid table
    if 'paid' not in existing_tables:
        print("\nCreating 'paid' table...")
        cursor.execute("""
            CREATE TABLE paid (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT,
                last_name TEXT,
                email TEXT NOT NULL,
                ip TEXT,
                sale_amount REAL,
                payout_amount REAL,
                campaign TEXT,
                duid TEXT,
                ad_id TEXT,
                trans_datetime TIMESTAMP,
                data_source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                proc_name TEXT,
                processor_subscriber_id TEXT,
                pov_verified BOOLEAN,
                pov_verified_time TIMESTAMP,
                user_agent TEXT,
                geo_country TEXT,
                custom_u1 TEXT,
                webmaster_code TEXT,
                webmaster_id TEXT
            )
        """)
        tables_created.append('paid')
        print("✓ Created 'paid' table")
    
    # Create free table
    if 'free' not in existing_tables:
        print("\nCreating 'free' table...")
        cursor.execute("""
            CREATE TABLE free (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                ip TEXT,
                duid TEXT,
                username TEXT,
                payout_amount REAL,
                campaign TEXT,
                ad_id TEXT,
                trans_datetime TIMESTAMP,
                data_source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                site_code TEXT,
                account_creation_timestamp TIMESTAMP,
                email_validation_timestamp TIMESTAMP,
                validation_time_seconds REAL,
                pov_verified BOOLEAN,
                pov_verified_time TIMESTAMP,
                user_agent TEXT,
                geo_country TEXT,
                custom_u1 TEXT,
                webmaster_code TEXT,
                webmaster_id TEXT
            )
        """)
        tables_created.append('free')
        print("✓ Created 'free' table")
    
    # Create fraud_results table
    if 'fraud_results' not in existing_tables:
        print("\nCreating 'fraud_results' table...")
        cursor.execute("""
            CREATE TABLE fraud_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                duid TEXT,
                email TEXT NOT NULL,
                risk_score INTEGER,
                flags TEXT,
                payout_amount REAL,
                data_type TEXT,
                analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                webmaster_code TEXT,
                campaign TEXT,
                ad_id TEXT,
                trans_datetime TIMESTAMP,
                ip_proxy INTEGER DEFAULT 0,
                ip_hosting INTEGER DEFAULT 0,
                pov_verified BOOLEAN,
                pov_verified_time TIMESTAMP,
                user_agent TEXT,
                geo_country TEXT,
                first_name TEXT,
                custom_u1 TEXT,
                ip TEXT
            )
        """)
        tables_created.append('fraud_results')
        print("✓ Created 'fraud_results' table")
    
    # Create fraud_outcomes table
    if 'fraud_outcomes' not in existing_tables:
        print("\nCreating 'fraud_outcomes' table...")
        cursor.execute("""
            CREATE TABLE fraud_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                duid TEXT NOT NULL,
                outcome TEXT NOT NULL,
                outcome_notes TEXT,
                reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(duid)
            )
        """)
        tables_created.append('fraud_outcomes')
        print("✓ Created 'fraud_outcomes' table")
    
    # Create business_metrics table
    if 'business_metrics' not in existing_tables:
        print("\nCreating 'business_metrics' table...")
        cursor.execute("""
            CREATE TABLE business_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_date DATE NOT NULL,
                total_accounts INTEGER,
                flagged_accounts INTEGER,
                confirmed_fraud INTEGER,
                false_positives INTEGER,
                fraud_loss_prevented REAL,
                review_time_avg_minutes REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        tables_created.append('business_metrics')
        print("✓ Created 'business_metrics' table")
    
    # Create industry_benchmarks table
    if 'industry_benchmarks' not in existing_tables:
        print("\nCreating 'industry_benchmarks' table...")
        cursor.execute("""
            CREATE TABLE industry_benchmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                industry TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        tables_created.append('industry_benchmarks')
        print("✓ Created 'industry_benchmarks' table")
        
        # Seed benchmark data
        benchmarks = [
            ('dating', 'fraud_rate_pct', 2.5, 'Industry average 2024'),
            ('dating', 'false_positive_rate_pct', 5.0, 'Industry average 2024'),
            ('dating', 'avg_review_time_minutes', 8.0, 'Industry average 2024')
        ]
        cursor.executemany("""
            INSERT INTO industry_benchmarks (industry, metric_name, metric_value, source)
            VALUES (?, ?, ?, ?)
        """, benchmarks)
        print("  ✓ Seeded industry benchmarks")
    
    # Create eda_cache table
    if 'eda_cache' not in existing_tables:
        print("\nCreating 'eda_cache' table...")
        cursor.execute("""
            CREATE TABLE eda_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT UNIQUE NOT NULL,
                result_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        tables_created.append('eda_cache')
        print("✓ Created 'eda_cache' table")
    
    # Create indexes
    print("\nCreating indexes...")
    indexes_created = 0
    
    index_queries = [
        "CREATE INDEX IF NOT EXISTS idx_paid_email ON paid(email)",
        "CREATE INDEX IF NOT EXISTS idx_paid_duid ON paid(duid)",
        "CREATE INDEX IF NOT EXISTS idx_free_email ON free(email)",
        "CREATE INDEX IF NOT EXISTS idx_free_duid ON free(duid)",
        "CREATE INDEX IF NOT EXISTS idx_fraud_email ON fraud_results(email)",
        "CREATE INDEX IF NOT EXISTS idx_fraud_duid ON fraud_results(duid)",
        "CREATE INDEX IF NOT EXISTS idx_fraud_risk ON fraud_results(risk_score)",
        "CREATE INDEX IF NOT EXISTS idx_fraud_type ON fraud_results(data_type)",
        "CREATE INDEX IF NOT EXISTS idx_fraud_ip ON fraud_results(ip)",
        "CREATE INDEX IF NOT EXISTS idx_fraud_webmaster ON fraud_results(webmaster_code)",
        "CREATE INDEX IF NOT EXISTS idx_fraud_campaign ON fraud_results(campaign)",
        "CREATE INDEX IF NOT EXISTS idx_outcomes_duid ON fraud_outcomes(duid)"
    ]
    
    for query in index_queries:
        try:
            cursor.execute(query)
            indexes_created += 1
        except sqlite3.Error as e:
            print(f"  ⚠️  Index creation skipped: {e}")
    
    print(f"✓ Created {indexes_created} indexes")
    
    conn.commit()
    conn.close()
    
    print("\n" + "=" * 60)
    if tables_created:
        print(f"✅ Initialized {len(tables_created)} tables:")
        for table in tables_created:
            print(f"   • {table}")
    else:
        print("✅ All tables already exist")
    print(f"✓ Created {indexes_created} indexes")
    print("\nDatabase is ready!")

if __name__ == '__main__':
    try:
        init_database()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
