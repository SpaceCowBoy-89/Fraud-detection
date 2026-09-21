#!/usr/bin/env python3
"""
Database Migration Script - Add Missing Columns
Run this ONCE on existing database to add schema columns
"""

import sqlite3
import sys
from pathlib import Path

def check_column_exists(cursor, table, column):
    """Check if a column exists in a table"""
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns

def migrate_database(db_path='affiliate_data.db'):
    """Add missing columns to existing database"""
    print(f"Migrating database: {db_path}")
    print("=" * 80)
    
    if not Path(db_path).exists():
        print(f"❌ Database not found: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    migrations_applied = 0
    migrations_skipped = 0
    
    # Migration 1: Add columns to fraud_results table
    print("\n1. Migrating fraud_results table...")
    fraud_results_columns = [
        ('webmaster_code', 'TEXT'),
        ('campaign', 'TEXT'),
        ('trans_datetime', 'TIMESTAMP'),
        ('pov_verified', 'BOOLEAN'),
        ('pov_verified_time', 'TIMESTAMP'),
        ('user_agent', 'TEXT'),
        ('geo_country', 'TEXT'),
        ('first_name', 'TEXT'),
        ('custom_u1', 'TEXT'),
        ('ip', 'TEXT'),
        ('ad_id', 'TEXT'),
        ('ip_proxy', 'INTEGER DEFAULT 0'),
        ('ip_hosting', 'INTEGER DEFAULT 0'),
    ]
    
    for col_name, col_type in fraud_results_columns:
        if not check_column_exists(cursor, 'fraud_results', col_name):
            try:
                cursor.execute(f"ALTER TABLE fraud_results ADD COLUMN {col_name} {col_type}")
                print(f"  ✓ Added column: {col_name} ({col_type})")
                migrations_applied += 1
            except sqlite3.OperationalError as e:
                print(f"  ⚠️  Failed to add {col_name}: {e}")
        else:
            print(f"  ⊘ Column {col_name} already exists")
            migrations_skipped += 1
    
    # Migration 2: Add columns to paid table
    print("\n2. Migrating paid table...")
    paid_columns = [
        ('webmaster_code', 'TEXT'),
        ('webmaster_id', 'TEXT'),
    ]
    
    for col_name, col_type in paid_columns:
        if not check_column_exists(cursor, 'paid', col_name):
            try:
                cursor.execute(f"ALTER TABLE paid ADD COLUMN {col_name} {col_type}")
                print(f"  ✓ Added column: {col_name} ({col_type})")
                migrations_applied += 1
            except sqlite3.OperationalError as e:
                print(f"  ⚠️  Failed to add {col_name}: {e}")
        else:
            print(f"  ⊘ Column {col_name} already exists")
            migrations_skipped += 1
    
    # Migration 3: Add columns to free table
    print("\n3. Migrating free table...")
    free_columns = [
        ('webmaster_code', 'TEXT'),
        ('webmaster_id', 'TEXT'),
    ]
    
    for col_name, col_type in free_columns:
        if not check_column_exists(cursor, 'free', col_name):
            try:
                cursor.execute(f"ALTER TABLE free ADD COLUMN {col_name} {col_type}")
                print(f"  ✓ Added column: {col_name} ({col_type})")
                migrations_applied += 1
            except sqlite3.OperationalError as e:
                print(f"  ⚠️  Failed to add {col_name}: {e}")
        else:
            print(f"  ⊘ Column {col_name} already exists")
            migrations_skipped += 1
    
    # Migration 4: Add missing indexes
    print("\n4. Adding performance indexes...")
    indexes = [
        ('idx_fraud_ip', 'fraud_results', 'ip'),
        ('idx_fraud_webmaster', 'fraud_results', 'webmaster_code'),
        ('idx_fraud_campaign', 'fraud_results', 'campaign'),
        ('idx_paid_trans_dt', 'paid', 'trans_datetime'),
        ('idx_free_trans_dt', 'free', 'trans_datetime'),
        ('idx_fraud_trans_dt', 'fraud_results', 'trans_datetime'),
        ('idx_outcomes_reviewed', 'fraud_outcomes', 'reviewed_at'),
        ('idx_metrics_date', 'detection_metrics', 'metric_date'),
    ]
    
    for idx_name, table, column in indexes:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column})")
            print(f"  ✓ Created index: {idx_name} on {table}({column})")
            migrations_applied += 1
        except sqlite3.OperationalError as e:
            print(f"  ⚠️  Failed to create index {idx_name}: {e}")
    
    # Migration 5: eda_cache — align with dashboard /api/eda/run (cache_key, result_json, created_at)
    print("\n5. Migrating eda_cache table...")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='eda_cache'")
    if cursor.fetchone():
        cursor.execute("PRAGMA table_info(eda_cache)")
        eda_cols = [row[1] for row in cursor.fetchall()]
        if 'cache_key' not in eda_cols:
            cursor.execute("DROP TABLE eda_cache")
            cursor.execute('''CREATE TABLE eda_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT NOT NULL UNIQUE,
                result_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            print("  ✓ Rebuilt eda_cache (legacy schema → cache_key / result_json / created_at)")
            migrations_applied += 1
        else:
            print("  ⊘ eda_cache already matches dashboard schema")
            migrations_skipped += 1
    else:
        print("  ⊘ eda_cache not present (created on next app start)")
    
    # Commit changes
    conn.commit()
    conn.close()
    
    print("\n" + "=" * 80)
    print(f"✓ Migration complete!")
    print(f"  Applied: {migrations_applied}")
    print(f"  Skipped: {migrations_skipped}")
    print("=" * 80)
    
    return True

if __name__ == '__main__':
    # Check if database path provided
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = 'affiliate_data.db'
    
    print("\n🔄 DATABASE MIGRATION SCRIPT")
    print("This will add missing columns to your existing database.\n")
    
    response = input(f"Migrate database '{db_path}'? (yes/no): ").lower()
    
    if response in ['yes', 'y']:
        success = migrate_database(db_path)
        if success:
            print("\n✅ Database migration successful!")
            print("\nYou can now restart the dashboard.")
        else:
            print("\n❌ Migration failed!")
            sys.exit(1)
    else:
        print("\n❌ Migration cancelled.")
        sys.exit(0)
