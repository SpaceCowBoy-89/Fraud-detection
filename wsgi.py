"""
WSGI entrypoint for production HTTP servers (gunicorn, waitress).

Usage:
  gunicorn -w 1 -b 0.0.0.0:5050 wsgi:application

Docker image defaults to gunicorn via Dockerfile CMD.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from logging_config import configure_logging

configure_logging("fraud-detection-web")

from run import build_app  # noqa: E402

application = build_app()
