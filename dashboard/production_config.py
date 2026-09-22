"""Runtime production guards for the fraud-detection web app."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _truthy(name: str) -> bool:
    return (os.environ.get(name) or '').strip().lower() in ('1', 'true', 'yes', 'on')


def require_flask_secret(*, testing: bool = False) -> str:
    """
    Return FLASK_SECRET_KEY.

    When REQUIRE_FLASK_SECRET_KEY=1 (or DEBUG is off and REQUIRE is unset in
    production containers), refuse to start without a non-empty key.
    Tests and local DEBUG remain allowed to generate an ephemeral key.
    """
    key = (os.environ.get('FLASK_SECRET_KEY') or '').strip()
    if key:
        return key

    if testing or _truthy('DEBUG'):
        return ''

    # Explicit opt-in, or production compose sets REQUIRE_FLASK_SECRET_KEY=1
    if _truthy('REQUIRE_FLASK_SECRET_KEY'):
        raise RuntimeError(
            'FLASK_SECRET_KEY is required when REQUIRE_FLASK_SECRET_KEY=1. '
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    return ''


def session_cookie_settings() -> dict:
    """Secure-by-default session cookie flags (Secure gated for local HTTP)."""
    secure = _truthy('SESSION_COOKIE_SECURE') or _truthy('TRUST_PROXY_HTTPS')
    samesite = (os.environ.get('SESSION_COOKIE_SAMESITE') or 'Lax').strip() or 'Lax'
    if samesite not in ('Lax', 'Strict', 'None'):
        samesite = 'Lax'
    return {
        'SESSION_COOKIE_HTTPONLY': True,
        'SESSION_COOKIE_SECURE': secure,
        'SESSION_COOKIE_SAMESITE': samesite,
    }


def warn_sqlite_concurrency() -> None:
    try:
        workers = int(os.environ.get('WEB_CONCURRENCY') or '1')
    except ValueError:
        workers = 1
    if workers > 1:
        logger.warning(
            'WEB_CONCURRENCY=%s with SQLite may cause write lock contention; '
            'prefer 1 worker unless writes are carefully serialized.',
            workers,
        )
