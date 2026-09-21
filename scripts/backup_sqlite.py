#!/usr/bin/env python3
"""
Online SQLite backup (uses sqlite3.Connection.backup — safe with WAL).

Examples:
  python scripts/backup_sqlite.py
  DB_PATH=/data/affiliate_data.db python scripts/backup_sqlite.py --dest /backup --keep 14

Environment defaults:
  DB_PATH     database file (default affiliate_data.db)
  BACKUP_DIR  output directory (default backups)
  BACKUP_KEEP number of newest backups to retain (default 30, 0 = no pruning)
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def backup_db(src: Path, dest_dir: Path) -> Path:
    """Copy database using SQLite online backup API."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"{src.stem}_{ts}.db"

    src_conn = sqlite3.connect(str(src), timeout=120.0)
    try:
        dest_conn = sqlite3.connect(str(dest), timeout=120.0)
        try:
            with dest_conn:
                src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()
    return dest


def prune_backups(dest_dir: Path, stem: str, keep: int) -> None:
    """Keep the ``keep`` newest files matching ``{stem}_*.db``."""
    if keep <= 0:
        return
    pattern = f"{stem}_*.db"
    files = sorted(dest_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backup SQLite database (online backup)")
    p.add_argument(
        "--db",
        default=os.environ.get("DB_PATH", "affiliate_data.db"),
        help="Path to SQLite database file",
    )
    p.add_argument(
        "--dest",
        default=os.environ.get("BACKUP_DIR", "backups"),
        help="Directory to write backup files",
    )
    p.add_argument(
        "--keep",
        type=int,
        default=int(os.environ.get("BACKUP_KEEP", "30")),
        help="Retain this many newest backups (0 disables pruning)",
    )
    args = p.parse_args(argv)

    src = Path(args.db).expanduser().resolve()
    if not src.is_file():
        print(f"Error: database not found: {src}", file=sys.stderr)
        return 1

    dest_dir = Path(args.dest).expanduser().resolve()
    out = backup_db(src, dest_dir)
    print(f"Backup written: {out}")
    prune_backups(dest_dir, src.stem, args.keep)
    if args.keep > 0:
        print(f"Pruned old backups (kept {args.keep} newest matching {src.stem}_*.db)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
