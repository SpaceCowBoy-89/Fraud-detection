"""
Backfill ip_proxy and ip_hosting columns in fraud_results.

Uses the ip-api.com free batch endpoint (100 IPs per request, 45 req/min).
Run once to populate existing records. Future analyses will populate on the fly.

Usage:
    python scripts/backfill_ip_flags.py
"""

import sqlite3
import time
import requests
import sys
import os

DB_PATH   = os.path.join(os.path.dirname(__file__), '..', 'affiliate_data.db')
BATCH_URL = 'http://ip-api.com/batch'
BATCH_SZ  = 100
RATE_LIMIT = 44          # stay safely under 45/min
SLEEP_SEC  = 60 / RATE_LIMIT


def fetch_batch(ips: list[str]) -> dict[str, dict]:
    """Call ip-api.com batch endpoint. Returns {ip: {proxy, hosting}} map."""
    payload = [{'query': ip, 'fields': 'query,proxy,hosting,status'} for ip in ips]
    try:
        r = requests.post(BATCH_URL, json=payload, timeout=15)
        r.raise_for_status()
        result = {}
        for row in r.json():
            if row.get('status') == 'success':
                result[row['query']] = {
                    'proxy':   bool(row.get('proxy',   False)),
                    'hosting': bool(row.get('hosting', False)),
                }
        return result
    except Exception as e:
        print(f'  [warn] batch request failed: {e}')
        return {}


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')

    # Fetch distinct IPs that still need lookup
    # (ip_proxy = 0 AND ip_hosting = 0 could mean genuinely clean OR not yet looked up)
    # We re-lookup everything with ip_proxy IS NULL to be safe; for already-0 rows we skip.
    rows = conn.execute("""
        SELECT DISTINCT ip
        FROM fraud_results
        WHERE ip IS NOT NULL AND ip != ''
          AND ip_proxy IS NULL
        ORDER BY ip
    """).fetchall()

    ips = [r[0] for r in rows]
    total = len(ips)

    if total == 0:
        print('Nothing to backfill — all IPs already have proxy/hosting data.')
        conn.close()
        return

    print(f'Backfilling {total:,} unique IPs in batches of {BATCH_SZ}…')
    print(f'Estimated time: ~{(total / BATCH_SZ / RATE_LIMIT):.1f} minutes\n')

    flagged_proxy   = 0
    flagged_hosting = 0
    processed       = 0
    batches         = (total + BATCH_SZ - 1) // BATCH_SZ

    for batch_num, i in enumerate(range(0, total, BATCH_SZ), 1):
        batch = ips[i:i + BATCH_SZ]
        result = fetch_batch(batch)

        updates = []
        for ip in batch:
            geo = result.get(ip, {})
            proxy   = 1 if geo.get('proxy')   else 0
            hosting = 1 if geo.get('hosting') else 0
            updates.append((proxy, hosting, ip))
            if proxy:   flagged_proxy   += 1
            if hosting: flagged_hosting += 1

        if updates:
            conn.executemany(
                'UPDATE fraud_results SET ip_proxy=?, ip_hosting=? WHERE ip=?',
                updates
            )
            conn.commit()

        processed += len(batch)
        pct = processed / total * 100
        print(f'  Batch {batch_num}/{batches} — {processed:,}/{total:,} ({pct:.0f}%) | '
              f'proxy={flagged_proxy} hosting={flagged_hosting}', end='\r')
        sys.stdout.flush()

        # Rate-limit: sleep between batches
        if batch_num < batches:
            time.sleep(SLEEP_SEC)

    print(f'\n\nDone.')
    print(f'  IPs flagged as PROXY:            {flagged_proxy:,}')
    print(f'  IPs flagged as HOSTING/DC:       {flagged_hosting:,}')
    print(f'  IPs flagged as either:           {flagged_proxy + flagged_hosting:,}')
    print(f'  Rows updated in fraud_results:   {total:,} unique IPs')

    conn.close()


if __name__ == '__main__':
    main()
