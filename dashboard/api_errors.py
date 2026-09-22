"""API error helpers — keep client responses generic outside DEBUG/TESTING."""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from flask import current_app, jsonify

logger = logging.getLogger(__name__)


def _expose_details() -> bool:
    try:
        if current_app.config.get('TESTING') or current_app.config.get('DEBUG'):
            return True
    except RuntimeError:
        pass
    return (os.environ.get('DEBUG') or '').strip().lower() in ('1', 'true', 'yes', 'on')


def api_error(
    message: str,
    status: int = 500,
    *,
    details: Any = None,
    code: Optional[str] = None,
    extra: Optional[dict] = None,
    log_exc: bool = False,
):
    """Build a JSON error response; omit exception details outside debug/testing."""
    body: dict = {'error': message}
    if code:
        body['code'] = code
    if extra:
        body.update(extra)
    if details is not None and _expose_details():
        body['details'] = str(details)
    if log_exc:
        logger.exception('%s', message)
    elif status >= 500:
        logger.error('%s: %s', message, details)
    return jsonify(body), status
