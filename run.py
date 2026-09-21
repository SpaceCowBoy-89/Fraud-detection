#!/usr/bin/env python3
"""
Standalone entry point for the Fraud Detection web application.

Usage:
    python run.py
    PORT=8080 python run.py
    python run.py --port 8080 --host 127.0.0.1

Production (gunicorn):
    gunicorn -w 1 -b 0.0.0.0:5050 wsgi:application
"""
import argparse
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger('fraud-detection')


def build_app(config_path=None, database_path=None):
    """
    Construct the Flask app (used by ``python run.py``, ``wsgi.py``, and tests).

    Args:
        config_path: Path to config.json (default: CONFIG_PATH env or ``config.json``).
        database_path: SQLite file path (default: DB_PATH env or config ``database_path``).
    """
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from database import Database
    from config import Config
    from api_client import APIClient
    from dashboard.app import create_app

    cfg_path = config_path or os.environ.get('CONFIG_PATH', 'config.json')
    cfg = Config(cfg_path)

    db_path = database_path or os.getenv('DB_PATH') or cfg.get(
        'database_path', 'affiliate_data.db'
    )
    db = Database(db_path)

    api_key = cfg.get_api_key()
    api_client = APIClient(api_key) if api_key else None

    return create_app(db, cfg, api_client=api_client)


def main():
    from logging_config import configure_logging

    configure_logging('fraud-detection')

    parser = argparse.ArgumentParser(description='Fraud Detection Web Application')
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '5050')))
    parser.add_argument('--host', default=os.getenv('HOST', '0.0.0.0'))
    parser.add_argument(
        '--debug',
        action='store_true',
        default=os.getenv('DEBUG', '').lower() in ('1', 'true', 'yes'),
    )
    args = parser.parse_args()

    app = build_app()

    logger.info('Starting Fraud Detection on http://%s:%s', args.host, args.port)
    if not app.api_client:
        logger.warning(
            'No affiliate API key configured — fetch from network disabled. '
            'Set in Settings or FRAUD_DETECTION_API_KEY.'
        )

    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=args.debug)


if __name__ == '__main__':
    main()
