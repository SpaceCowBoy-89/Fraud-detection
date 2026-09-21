"""Per-user admin2 credentials in Flask session (encrypted token, not plaintext in config)."""

from __future__ import annotations

import os
from typing import Optional, Tuple

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from admin_api_client import AdminAPIClient

SESSION_SEALED_KEY = 'admin_api_sealed'
SESSION_SKIP_KEY = 'admin2_skipped'
SEAL_SALT = 'fraud-dashboard-admin-api'
DEFAULT_MAX_AGE_SECONDS = 60 * 60 * 12  # 12 hours


def admin_login_required() -> bool:
    """When false, disables admin2 gate (local dev only)."""
    val = (os.environ.get('ADMIN2_LOGIN_REQUIRED') or '1').strip().lower()
    return val not in ('0', 'false', 'no', 'off')


def dashboard_gate_enabled() -> bool:
    """When true, valid admin2 session is required for all dashboard API access."""
    explicit = os.environ.get('ADMIN2_GATE_DASHBOARD')
    if explicit is not None and str(explicit).strip() != '':
        return str(explicit).strip().lower() not in ('0', 'false', 'no', 'off')
    return admin_login_required()


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt=SEAL_SALT)


def seal_admin_credentials(username: str, password: str, secret_key: str) -> str:
    return _serializer(secret_key).dumps({'u': username.strip(), 'p': password})


def unseal_admin_credentials(
    token: str, secret_key: str, max_age: int = DEFAULT_MAX_AGE_SECONDS
) -> Optional[Tuple[str, str]]:
    if not token or not secret_key:
        return None
    try:
        data = _serializer(secret_key).loads(token, max_age=max_age)
        u = (data.get('u') or '').strip()
        p = data.get('p') or ''
        if u and p:
            return u, p
    except (BadSignature, SignatureExpired, TypeError, KeyError):
        return None
    return None


def credentials_from_session(session, secret_key: str) -> Optional[Tuple[str, str]]:
    token = session.get(SESSION_SEALED_KEY)
    if not token:
        return None
    return unseal_admin_credentials(token, secret_key)


def admin_client_from_session(session, secret_key: str) -> Optional[AdminAPIClient]:
    creds = credentials_from_session(session, secret_key)
    if not creds:
        return None
    return AdminAPIClient(creds[0], creds[1])


def mask_username(username: str) -> str:
    u = (username or '').strip()
    if len(u) <= 2:
        return '***'
    return u[:3] + '***'


def session_is_authenticated(session, secret_key: str) -> bool:
    return credentials_from_session(session, secret_key) is not None


def session_auth_status(session, secret_key: str) -> dict:
    creds = credentials_from_session(session, secret_key)
    gate = dashboard_gate_enabled()
    authenticated = creds is not None
    return {
        'authenticated': authenticated,
        'skipped': False,
        'username_preview': mask_username(creds[0]) if creds else '',
        'login_required': gate,
        'dashboard_gate': gate,
        'can_browse': authenticated or not gate,
    }
