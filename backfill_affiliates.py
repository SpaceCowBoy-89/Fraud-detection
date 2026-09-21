#!/usr/bin/env python3
"""
Backfill webmaster_code in fraud_results from source tables.
Run this after migrate_database.py to populate missing affiliate data.
"""

import sqlite3
import sys

DB_PATH = 'fraud_detection.db'

def backfill_affiliates():
    """Backfill webmaster_code and campaign from free/paid tables into fraud_results"""
    
    print("🔄 BACKFILLING AFFILIATE DATA")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check which columns exist
    cursor.execute("PRAGMA table_info(free)")
    free_cols = {row[1] for row in cursor.fetchall()}
    
    cursor.execute("PRAGMA table_info(paid)")
    paid_cols = {row[1] for row in cursor.fetchall()}
    
    cursor.execute("PRAGMA table_info(fraud_results)")
    fraud_cols = {row[1] for row in cursor.fetchall()}
    
    print(f"\nDatabase columns found:")
    print(f"  Free table: webmaster_code={('webmaster_code' in free_cols)}, site_code={('site_code' in free_cols)}")
    print(f"  Paid table: webmaster_code={('webmaster_code' in paid_cols)}, proc_name={('proc_name' in paid_cols)}")
    print(f"  Fraud results: webmaster_code={('webmaster_code' in fraud_cols)}, campaign={('campaign' in fraud_cols)}")
    
    if 'webmaster_code' not in fraud_cols:
        print("\n❌ ERROR: fraud_results table missing webmaster_code column.")
        print("   Run migrate_database.py first!")
        return
    
    # Count null webmaster_codes
    cursor.execute("SELECT COUNT(*) FROM fraud_results WHERE webmaster_code IS NULL OR webmaster_code = ''")
    null_count = cursor.fetchone()[0]
    
    if null_count == 0:
        print("\n✓ All fraud_results already have webmaster_code populated!")
        return
    
    print(f"\n📊 Found {null_count} records with missing webmaster_code")
    
    response = input("\nBackfill from source tables? (yes/no): ").strip().lower()
    if response != 'yes':
        print("Cancelled.")
        return
    
    updated = 0
    
    # Strategy 1: Match by email from FREE table
    if 'site_code' in free_cols or 'webmaster_code' in free_cols:
        aff_col = 'webmaster_code' if 'webmaster_code' in free_cols else 'site_code'
        query = f"""
            UPDATE fraud_results
            SET webmaster_code = (
                SELECT f.{aff_col}
                FROM free f
                WHERE f.email = fraud_results.email
                AND f.{aff_col} IS NOT NULL
                LIMIT 1
            )
            WHERE (webmaster_code IS NULL OR webmaster_code = '')
            AND data_type = 'free'
        """
        cursor.execute(query)
        count = cursor.rowcount
        updated += count
        print(f"\n✓ Updated {count} free records from free.{aff_col}")
    
    # Strategy 2: Match by email from PAID table
    if 'webmaster_code' in paid_cols or 'proc_name' in paid_cols:
        aff_col = 'webmaster_code' if 'webmaster_code' in paid_cols else 'proc_name'
        query = f"""
            UPDATE fraud_results
            SET webmaster_code = (
                SELECT p.{aff_col}
                FROM paid p
                WHERE p.email = fraud_results.email
                AND p.{aff_col} IS NOT NULL
                LIMIT 1
            )
            WHERE (webmaster_code IS NULL OR webmaster_code = '')
            AND data_type = 'paid'
        """
        cursor.execute(query)
        count = cursor.rowcount
        updated += count
        print(f"✓ Updated {count} paid records from paid.{aff_col}")
    
    # Backfill campaign if column exists
    if 'campaign' in fraud_cols:
        # From free table
        if 'campaign' in free_cols:
            cursor.execute("""
                UPDATE fraud_results
                SET campaign = (
                    SELECT f.campaign
                    FROM free f
                    WHERE f.email = fraud_results.email
                    AND f.campaign IS NOT NULL
                    LIMIT 1
                )
                WHERE (campaign IS NULL OR campaign = '')
                AND data_type = 'free'
            """)
            print(f"✓ Updated {cursor.rowcount} campaign values from free table")
        
        # From paid table
        if 'campaign' in paid_cols:
            cursor.execute("""
                UPDATE fraud_results
                SET campaign = (
                    SELECT p.campaign
                    FROM paid p
                    WHERE p.email = fraud_results.email
                    AND p.campaign IS NOT NULL
                    LIMIT 1
                )
                WHERE (campaign IS NULL OR campaign = '')
                AND data_type = 'paid'
            """)
            print(f"✓ Updated {cursor.rowcount} campaign values from paid table")
    
    conn.commit()
    
    # Check remaining nulls
    cursor.execute("SELECT COUNT(*) FROM fraud_results WHERE webmaster_code IS NULL OR webmaster_code = ''")
    remaining = cursor.fetchone()[0]
    
    print("\n" + "=" * 60)
    print(f"✓ Backfill complete!")
    print(f"  Updated: {updated}")
    print(f"  Remaining NULL: {remaining}")
    
    if remaining > 0:
        print(f"\nNote: {remaining} records still have no affiliate code.")
        print("This usually means the email doesn't exist in source tables.")
    
    conn.close()

if __name__ == '__main__':
    try:
        backfill_affiliates()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)
