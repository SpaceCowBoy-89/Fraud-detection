#!/usr/bin/env python3
"""One-off analysis backlog drain for a date range."""
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from config import Config
from database import Database
from pipeline_analysis import drain_unanalyzed_for_range


def main():
    lookback = 14
    cfg = Config(str(ROOT / 'config.json'))
    db = Database(cfg.get('database_path', 'affiliate_data.db'))
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=lookback - 1)
    print(f'Draining {start} -> {end}', flush=True)
    before = db.get_analysis_backlog_count(lookback_days=lookback)
    print(f'Backlog before: {before:,}', flush=True)
    summary = drain_unanalyzed_for_range(
        db,
        cfg,
        start.isoformat(),
        end.isoformat(),
        batch_limit=15000,
        max_batches=20,
        paid_first=True,
    )
    after = db.get_analysis_backlog_count(lookback_days=lookback)
    print(
        f'Done. analyzed={summary.get("analyzed"):,} '
        f'high_risk={summary.get("high_risk"):,} backlog={after:,}',
        flush=True,
    )
    for day in summary.get('days') or []:
        print(
            f"  {day['day']}: analyzed={day['analyzed']:,} "
            f"remaining={day['remaining']:,} complete={day['complete']}",
            flush=True,
        )


if __name__ == '__main__':
    main()
