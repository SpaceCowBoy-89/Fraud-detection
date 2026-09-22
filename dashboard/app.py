"""
Flask web dashboard for fraud detection system.

Provides API endpoints and serves the single-page dashboard.
Designed to run in a daemon thread alongside the CLI.
"""

import threading
import webbrowser
import logging
import json
import sys
import os
import csv
import io
import re
import secrets
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, jsonify, request, Response, session, g

# Project root (for api_client when updating API key from Settings)
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_SCRIPTS = _ROOT / 'scripts'
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from flag_utils import (  # noqa: E402
    parse_flags_cell,
    normalize_flag_catalog_key,
    catalog_flags_from_cell,
    precision_confidence,
    rule_status,
    needs_content_review,
    has_content_review_flag,
)
from analysis_insights import AnalysisInsights  # noqa: E402
from fraud_flags_reference import (  # noqa: E402
    load_catalog as load_flag_reference_catalog,
    enrich_catalog as enrich_flag_reference_catalog,
    export_csv as export_flag_reference_csv,
    export_json as export_flag_reference_json,
    export_markdown as export_flag_reference_markdown,
    get_export_context,
)
from api_client import APIClient
from admin_api_client import AdminAPIClient
from .admin_credentials import (
    SESSION_SEALED_KEY,
    SESSION_SKIP_KEY,
    admin_client_from_session,
    admin_login_required,
    dashboard_gate_enabled,
    mask_username,
    seal_admin_credentials,
    session_auth_status,
    session_is_authenticated,
)
from .production_config import (
    require_flask_secret,
    session_cookie_settings,
    warn_sqlite_concurrency,
)
from .api_errors import api_error

# Suppress Flask dev server warning
logging.getLogger('werkzeug').setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

# Track background tasks
_running_tasks = {}

# Valid data types for validation
VALID_DATA_TYPES = {'free', 'paid', 'both'}
VALID_OUTCOMES = {'confirmed_fraud', 'false_positive', 'under_review'}

VALID_AFFILIATE_ACTION_STATUS = frozenset({
    'flagged', 'under_review', 'actioned', 'cleared', 'monitoring',
})
VALID_AFFILIATE_ACTION_TYPE = frozenset({
    'traffic_closed', 'payout_withheld', 'clawback_requested', 'clawback_received',
    'terminated', 'warned', 'capped', 'no_action',
})
VALID_AFFILIATE_TRIGGER_REASON = frozenset({
    'high_fraud_rate', 'discover_concentration', 'shared_card', 'shared_ip',
    'woman_concentration', 'sequential_email', 'account_reviews', 'enrichment',
    'manual', 'other',
})


def validate_data_type(data_type):
    """Validate data_type parameter to prevent SQL injection"""
    if data_type not in VALID_DATA_TYPES:
        return None
    return data_type


def validate_outcome(outcome):
    """Validate outcome parameter"""
    if outcome not in VALID_OUTCOMES:
        return None
    return outcome


def sanitize_string(s, max_length=500):
    """Sanitize string input"""
    if not isinstance(s, str):
        return ''
    return s.strip()[:max_length]


def sanitize_for_json(obj):
    """Recursively replace NaN/Infinity with None so Flask jsonify produces valid JSON."""
    import math
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


def _analysis_filters_from_request():
    """Shared query params for Analysis insight endpoints."""
    return {
        'date_from': request.args.get('date_from', '').strip() or None,
        'date_to': request.args.get('date_to', '').strip() or None,
        'affiliate': request.args.get('affiliate', '').strip() or None,
        'campaign': request.args.get('campaign', '').strip() or None,
    }


def row_matches_flag_catalog(flags_str, catalog_key):
    """True if this row's flags cell includes catalog_key (after normalization)."""
    if not catalog_key:
        return False
    target = normalize_flag_catalog_key(catalog_key)
    target_l = target.lower()
    legacy = str(catalog_key).strip("[]' ").lower()
    for f in parse_flags_cell(flags_str):
        raw = str(f).strip("[]' ")
        if not raw:
            continue
        if raw.lower() == legacy:
            return True
        if normalize_flag_catalog_key(raw).lower() == target_l:
            return True
    return False


def count_catalog_flags(flags_series, total=None):
    """Count individual catalog-normalized flags across a pandas Series of flag cells."""
    from collections import Counter
    flag_counts = Counter()
    for flags_str in flags_series.dropna():
        seen = set()
        for f in parse_flags_cell(flags_str):
            key = normalize_flag_catalog_key(f)
            if key and key not in seen:
                seen.add(key)
                flag_counts[key] += 1
    denom = total if total is not None else max(sum(flag_counts.values()), 1)
    return [
        {'flag': k, 'count': v, 'pct': round(v / denom * 100, 1) if denom else 0}
        for k, v in flag_counts.most_common()
    ]


def _run_fraud_analysis_on_dataframe(db, config, data_type, df):
    """
    Preprocess + score rows in df, write fraud_results, mark source rows analyzed.
    Used by webhook ingest when analyze=true. Does not touch global analysis task status.
    """
    import pandas as pd
    from pathlib import Path

    if df is None or df.empty:
        return {'analyzed': 0, 'high_risk': 0, 'results': []}

    scripts_dir = Path(__file__).resolve().parent.parent / 'scripts'
    sys.path.insert(0, str(scripts_dir))
    from email_fraud_detector import EmailFraudDetector
    from data_preprocessor import DataPreprocessor

    preprocessor = DataPreprocessor()
    df, _quality = preprocessor.preprocess_batch(df.copy())

    detector = EmailFraudDetector(config)
    df = detector.normalize_column_names(df)
    detector.build_repeated_word_map(df)
    detector.build_geographic_cluster_maps(df)
    detector.build_shared_ip_map(df, db=db)
    detector.build_ip_velocity_map(df, db=db)
    detector.build_gender_concentration_map(df)
    detector.build_sequential_email_map(df)
    detector.build_affiliate_domain_concentration_map(df)

    results = []
    email_col = detector.column_map.get('email')
    high_th = int(config.get_risk_threshold('high') or 50)
    skip_codes = config.get_affiliate_analysis_skip_codes_lower(include_house_in_analysis=False)

    for _idx, row in df.iterrows():
        duid_val = detector.get_column(row, 'duid', None)
        if duid_val is None or str(duid_val).strip() == '':
            continue

        webmaster_code = detector.get_column(row, 'webmaster_code', None)
        if not webmaster_code:
            for col in ('webmaster_code', 'site_code'):
                if col in row.index and pd.notna(row[col]) and row[col] != '':
                    webmaster_code = row[col]
                    break
        if skip_codes and webmaster_code and str(webmaster_code).strip().lower() in skip_codes:
            continue
        campaign = detector.get_column(row, 'campaign', None)
        if not campaign and 'campaign' in row.index and pd.notna(row['campaign']):
            campaign = row['campaign']

        analysis = detector.analyze_email(
            row[email_col] if email_col else None,
            trans_datetime=detector.get_column(row, 'trans_datetime', None),
            pov_verified=detector.get_column(row, 'pov_verified', None),
            pov_verified_time=detector.get_column(row, 'pov_verified_time', None),
            ip_address=detector.get_column(row, 'ip', None),
            user_agent=detector.get_column(row, 'custom_http_user_agent', None),
            first_name=detector.get_column(row, 'first_name', None),
            user1=(
                detector.get_column(row, 'custom_u1', None)
                or detector.get_column(row, 'user1', None)
            ),
        )
        analysis['DUID'] = duid_val
        analysis['payout_amount'] = detector.get_column(row, 'payout_amount', 0)
        analysis['data_type'] = data_type
        analysis['webmaster_code'] = webmaster_code
        analysis['campaign'] = campaign
        analysis['ad_id'] = detector.get_column(row, 'ad_id', None)
        analysis['trans_datetime'] = detector.get_column(row, 'trans_datetime', None)
        analysis['pov_verified'] = detector.get_column(row, 'pov_verified', None)
        analysis['pov_verified_time'] = detector.get_column(row, 'pov_verified_time', None)
        analysis['user_agent'] = detector.get_column(row, 'custom_http_user_agent', None)
        src_geo = detector.get_column(row, 'geo_country', None)
        analysis['geo_country'] = src_geo or analysis.get('geo_country')
        analysis['ip'] = detector.get_column(row, 'ip', None)
        analysis['first_name'] = detector.get_column(row, 'first_name', None)
        analysis['custom_u1'] = (
            detector.get_column(row, 'custom_u1', None)
            or detector.get_column(row, 'user1', None)
        )
        results.append(analysis)

    detector.apply_gender_concentration_to_results(results)
    detector.apply_sequential_email_to_results(results)
    detector.apply_affiliate_domain_concentration_to_results(results)
    db.save_fraud_results(results)
    duids = [r['DUID'] for r in results if r.get('DUID') not in (None, 'N/A')]
    if duids:
        db.mark_as_analyzed(duids, data_type)

    return {
        'analyzed': len(results),
        'high_risk': sum(1 for r in results if r.get('risk_score', 0) >= high_th),
        'results': [
            {
                'duid': r.get('DUID'),
                'email': r.get('email'),
                'risk_score': r.get('risk_score'),
                'flags': r.get('flags'),
            }
            for r in results
        ],
    }


def validate_duid(duid):
    """
    Validate DUID parameter
    
    Args:
        duid: DUID value to validate
        
    Returns:
        str: Valid DUID or None if invalid
    """
    if duid is None:
        return None

    duid_str = str(duid).strip()
    if not duid_str or duid_str.lower() in ("none", "null", "undefined"):
        return None

    # Plain digit string (common case)
    if duid_str.isdigit():
        pass
    else:
        # Accept float-like strings from DB/pandas (e.g. "384046981.0") but not fractional IDs
        try:
            as_float = float(duid_str)
        except (ValueError, OverflowError):
            logger.warning(f"Invalid DUID format (not numeric): {duid_str[:50]}")
            return None
        if not as_float.is_integer():
            logger.warning(f"Invalid DUID format (fractional): {duid_str[:50]}")
            return None
        duid_str = str(int(as_float))

    if len(duid_str) > 20:
        logger.warning(f"Invalid DUID format (too long): {len(duid_str)} digits")
        return None

    return duid_str


def _merge_attribution_from_raw(conn, duid, account, pd):
    """Fill empty webmaster_code, campaign, ad_id from paid/free when fraud_results omits them."""
    keys = ('webmaster_code', 'campaign', 'ad_id')
    for table in ('paid', 'free'):
        if all(account.get(k) not in (None, '', 'None') for k in keys):
            break
        try:
            row_df = pd.read_sql_query(
                f'SELECT webmaster_code, campaign, ad_id FROM {table} WHERE duid = ? LIMIT 1',
                conn,
                params=[duid],
            )
        except Exception:
            continue
        if row_df.empty:
            continue
        row = row_df.iloc[0].to_dict()
        for k in keys:
            if account.get(k) not in (None, '', 'None'):
                continue
            v = row.get(k)
            if pd.isna(v):
                v = None
            if v is not None and str(v).strip() and str(v).lower() != 'none':
                account[k] = v


def create_app(db, config, api_client=None):
    """Flask app factory. Receives existing Database and Config instances."""
    app = Flask(__name__)
    app.config['JSON_SORT_KEYS'] = False
    testing = bool(app.config.get('TESTING')) or bool(os.environ.get('PYTEST_CURRENT_TEST'))
    secret = require_flask_secret(testing=testing)
    # Stable secret across gunicorn workers when set (recommended in Docker / multi-worker).
    app.config['SECRET_KEY'] = secret or secrets.token_hex(32)
    for _ck, _cv in session_cookie_settings().items():
        app.config[_ck] = _cv
    warn_sqlite_concurrency()

    # ── Scheduler ────────────────────────────────────────────────────────────
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scheduler import FraudPipelineScheduler
    app_scheduler = FraudPipelineScheduler(db, config, api_client)
    app.scheduler = app_scheduler
    if os.environ.get('SKIP_EMBEDDED_SCHEDULER', '').lower() in ('1', 'true', 'yes'):
        logger.info(
            'SKIP_EMBEDDED_SCHEDULER is set — embedded APScheduler not started '
            '(use a standalone `python scheduler.py` process if scheduling is enabled).'
        )
    else:
        app_scheduler.start()

    # Store references for use in endpoints
    app.db = db
    app.config_obj = config
    app.api_client = api_client

    def _admin_client_for_request():
        """Admin2 client from the signed-in user's session (not config/env on web)."""
        return admin_client_from_session(session, app.config['SECRET_KEY'])

    def _scheduler_admin_configured():
        """Env/config admin creds — used by scheduler enrichment only."""
        u, p = config.get_admin_api_credentials()
        return bool(u and p)

    app._admin_client_for_request = _admin_client_for_request

    # Enable WAL mode on database for better concurrency
    try:
        with db.get_connection() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')  # Faster writes
            logger.info("Database WAL mode enabled")
    except Exception as e:
        logger.warning(f"Could not enable WAL mode: {e}")

    try:
        stale_hours = float((config.get('scheduler') or {}).get('stale_run_hours', 12) or 12)
        n = db.fail_stale_pipeline_runs(stale_hours=stale_hours)
        if n:
            logger.info('Cleared %s stale pipeline_runs on startup (>%sh)', n, stale_hours)
    except Exception as e:
        logger.warning('fail_stale_pipeline_runs on startup: %s', e)

    # ==================== MIDDLEWARE ====================

    @app.before_request
    def log_request():
        """Log incoming requests"""
        g.request_start = datetime.now()
        if request.path.startswith('/api/'):
            logger.debug(f"{request.method} {request.path}")

    @app.before_request
    def require_admin2_for_dashboard():
        """Block API use until the user signs in with valid admin2 credentials."""
        if not dashboard_gate_enabled():
            return None
        path = request.path or ''
        if path.startswith('/static/'):
            return None
        if path in ('/api/health', '/api/health/live', '/api/health/ready'):
            return None
        # Flag definitions only (no account data) — shareable with Fraud/Ops without admin2
        if path in ('/api/export/flag-reference', '/api/flags/reference'):
            return None
        if path.startswith('/api/auth/admin2'):
            return None
        if session_is_authenticated(session, app.config['SECRET_KEY']):
            return None
        if path.startswith('/api/'):
            return jsonify({'error': 'Admin2 sign-in required', 'code': 'admin2_auth_required'}), 401
        return None

    @app.after_request
    def log_response(response):
        """Log response time for API calls; short private cache for safe read-only GETs."""
        if hasattr(g, 'request_start') and request.path.startswith('/api/'):
            elapsed = (datetime.now() - g.request_start).total_seconds() * 1000
            logger.debug(f"{request.path} completed in {elapsed:.1f}ms")
        if (
            request.method == 'GET'
            and request.path.startswith('/api/')
            and 200 <= response.status_code < 300
        ):
            p = request.path
            # Avoid caching exports, job polling, or paths that match action segments
            if (
                p.startswith('/api/export/')
                or p in ('/api/analysis-status', '/api/fetch-status')
                or '/run' in p
                or '/configure' in p
            ):
                pass
            else:
                response.headers['Cache-Control'] = 'private, max-age=30'
        return response

    from werkzeug.exceptions import HTTPException

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        """Preserve 4xx/redirect semantics — do not fold into generic 500."""
        return jsonify({'error': e.name or 'Error', 'code': e.code}), e.code

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Global error handler — generic body outside DEBUG/TESTING."""
        logger.error(f"Unhandled error on {request.path}: {e}", exc_info=True)
        return api_error('Internal server error', 500, details=e)

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({'error': 'Endpoint not found'}), 404

    @app.errorhandler(400)
    def bad_request(e):
        return api_error('Bad request', 400, details=e)

    # ==================== ROUTES ====================

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/account/<duid>')
    def account_detail_page(duid):
        """Dedicated account detail page with shareable URL."""
        duid = validate_duid(duid)
        if not duid:
            return "Invalid DUID", 400
        return render_template('account_detail.html', duid=duid)

    @app.route('/affiliate/<code>')
    def affiliate_detail_page(code):
        """Dedicated affiliate detail page with shareable URL."""
        from markupsafe import escape
        code = str(escape(code))[:100]
        if not code:
            return "Invalid affiliate code", 400
        return render_template('affiliate_detail.html', code=code)

    @app.route('/cluster/<cluster_type>/<path:cluster_id>')
    def cluster_detail_page(cluster_type, cluster_id):
        """Dedicated cluster investigation page."""
        from markupsafe import escape
        valid_types = {'ip', 'domain', 'name', 'affiliate'}
        cluster_type = str(escape(cluster_type))[:20]
        if cluster_type not in valid_types:
            return "Invalid cluster type", 400
        cluster_id = str(escape(cluster_id))[:200]
        if not cluster_id:
            return "Invalid cluster ID", 400
        return render_template('cluster_detail.html',
                               cluster_type=cluster_type,
                               cluster_id=cluster_id)

    @app.route('/embed')
    def embed():
        """Dashboard in embed mode — sidebar hidden, top tab bar shown."""
        return render_template('index.html', embed_mode=True)

    @app.route('/widget/<duid>')
    def account_widget(duid):
        """Standalone account fraud widget page for iframing into account detail pages."""
        duid = validate_duid(duid)
        if not duid:
            return "Invalid DUID", 400
        return render_template('widget.html', duid=duid)

    @app.route('/api/health')
    @app.route('/api/health/live')
    def health_live():
        """Liveness: process is up (no database dependency)."""
        return jsonify({
            'status': 'ok',
            'check': 'live',
            'timestamp': datetime.now().isoformat(),
            # Backward compatible fields (legacy clients)
            'api_configured': app.api_client is not None,
            'db_connected': True,
        })

    @app.route('/api/auth/admin2/status')
    def api_admin2_status():
        """Whether the browser session has admin2 credentials (per-user, not shared config)."""
        return jsonify(session_auth_status(session, app.config['SECRET_KEY']))

    @app.route('/api/auth/admin2/login', methods=['POST'])
    def api_admin2_login():
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()
        password = data.get('password') or ''
        if not username or not password:
            return jsonify({'error': 'Username and password are required'}), 400
        client = AdminAPIClient(username, password)
        ok, message = client.test_connection()
        if not ok:
            return jsonify({'error': message or 'Authentication failed'}), 401
        session[SESSION_SEALED_KEY] = seal_admin_credentials(
            username, password, app.config['SECRET_KEY']
        )
        session.pop(SESSION_SKIP_KEY, None)
        session.modified = True
        return jsonify({'ok': True, 'username_preview': mask_username(username)})

    @app.route('/api/auth/admin2/logout', methods=['POST'])
    def api_admin2_logout():
        session.pop(SESSION_SEALED_KEY, None)
        session.pop(SESSION_SKIP_KEY, None)
        session.modified = True
        return jsonify({'ok': True})

    @app.route('/api/auth/admin2/skip', methods=['POST'])
    def api_admin2_skip():
        """Deprecated — dashboard access requires admin2 when gate is enabled."""
        if dashboard_gate_enabled():
            return jsonify({'error': 'Admin2 sign-in is required to use this dashboard'}), 403
        session[SESSION_SKIP_KEY] = True
        session.modified = True
        return jsonify({'ok': True, 'skipped': True})

    @app.route('/api/health/ready')
    def health_ready():
        """Readiness: database reachable + lightweight operational snapshot."""
        out = {
            'ready': True,
            'check': 'ready',
            'timestamp': datetime.now().isoformat(),
        }
        try:
            with db.get_connection() as conn:
                conn.execute('SELECT 1')
            out['database'] = 'ok'
        except Exception as e:
            logger.error('Readiness DB check failed: %s', e, exc_info=True)
            return api_error(
                'Database unavailable',
                503,
                details=e,
                extra={
                    'ready': False,
                    'check': 'ready',
                    'database': 'error',
                    'timestamp': datetime.now().isoformat(),
                },
            )

        out['api_configured'] = app.api_client is not None
        out['admin_api_configured'] = _scheduler_admin_configured()
        out['webhook_configured'] = bool(config.get_webhook_ingest_token())

        try:
            last_ok = db.get_last_pipeline_run(status='completed')
            if last_ok:
                out['last_completed_pipeline'] = {
                    'run_id': last_ok.get('run_id'),
                    'started_at': last_ok.get('started_at'),
                    'completed_at': last_ok.get('completed_at'),
                    'duration_seconds': last_ok.get('duration_seconds'),
                    'records_analyzed': last_ok.get('records_analyzed'),
                    'high_risk_found': last_ok.get('high_risk_found'),
                }
            last_any = db.get_last_pipeline_run()
            if last_any and last_any.get('status') != 'completed':
                out['last_pipeline_run'] = {
                    'run_id': last_any.get('run_id'),
                    'status': last_any.get('status'),
                    'started_at': last_any.get('started_at'),
                    'error_message': (last_any.get('error_message') or '')[:300],
                }
        except Exception as e:
            logger.debug('last pipeline for readiness: %s', e)

        try:
            lb = int((config.get('scheduler') or {}).get('enrich_lookback_days', 90) or 90)
            out['enrichment_backlog'] = int(
                db.get_enrichment_backlog_count(lookback_days=lb)
            )
        except Exception as e:
            logger.debug('enrichment backlog for readiness: %s', e)
            out['enrichment_backlog'] = None

        try:
            sched = app.scheduler.get_status()
            out['scheduler'] = {
                'scheduler_available': sched.get('scheduler_available'),
                'scheduler_running': sched.get('scheduler_running'),
                'enabled': sched.get('enabled'),
                'next_run': sched.get('next_run'),
            }
            ch = sched.get('coverage_health') or {}
            if ch.get('degraded'):
                out['coverage_degraded'] = True
                out['coverage_message'] = ch.get('message')
            ab = sched.get('analysis_backlog_count')
            if ab is not None:
                out['analysis_backlog_count'] = ab
        except Exception as e:
            logger.debug('scheduler status for readiness: %s', e)
            out['scheduler'] = None

        return jsonify(out)

    @app.route('/api/search')
    def api_global_search():
        """Global search scoped by context (accounts, affiliates, or campaigns)."""
        try:
            query = request.args.get('q', '').strip()
            limit = request.args.get('limit', 50, type=int)
            scope = request.args.get('scope', 'accounts')  # 'accounts' | 'affiliates' | 'campaigns'

            if not query or len(query) < 2:
                return jsonify({'results': [], 'query': query})

            import pandas as pd
            results = []
            query_lower = query.lower()
            pattern = f'%{query_lower}%'

            with db.get_connection() as conn:

                if scope == 'affiliates':
                    # Search affiliate summary from fraud_results
                    aff_query = """
                        SELECT webmaster_code,
                               COUNT(*) AS total_accounts,
                               SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) AS high_risk_count,
                               ROUND(AVG(risk_score), 1) AS avg_risk_score,
                               COALESCE(SUM(payout_amount), 0) AS total_payout
                        FROM fraud_results
                        WHERE webmaster_code IS NOT NULL
                          AND LOWER(webmaster_code) LIKE ?
                        GROUP BY webmaster_code
                        ORDER BY total_payout DESC
                        LIMIT ?
                    """
                    df = pd.read_sql_query(aff_query, conn, params=[pattern, limit])
                    for _, row in df.iterrows():
                        results.append({
                            'type': 'affiliate',
                            'webmaster_code': row['webmaster_code'],
                            'total_accounts': int(row['total_accounts']),
                            'high_risk_count': int(row['high_risk_count']),
                            'avg_risk_score': float(row['avg_risk_score']) if row['avg_risk_score'] else None,
                            'total_payout': round(float(row['total_payout']), 2),
                            'match_type': 'affiliate',
                        })

                elif scope == 'campaigns':
                    # Search campaigns from fraud_results
                    camp_query = """
                        SELECT campaign,
                               COUNT(*) AS total_accounts,
                               SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) AS high_risk_count,
                               ROUND(AVG(risk_score), 1) AS avg_risk_score,
                               COALESCE(SUM(payout_amount), 0) AS total_payout
                        FROM fraud_results
                        WHERE campaign IS NOT NULL AND campaign != ''
                          AND LOWER(campaign) LIKE ?
                        GROUP BY campaign
                        ORDER BY total_payout DESC
                        LIMIT ?
                    """
                    df = pd.read_sql_query(camp_query, conn, params=[pattern, limit])
                    for _, row in df.iterrows():
                        results.append({
                            'type': 'campaign',
                            'campaign': row['campaign'],
                            'total_accounts': int(row['total_accounts']),
                            'high_risk_count': int(row['high_risk_count']),
                            'avg_risk_score': float(row['avg_risk_score']) if row['avg_risk_score'] else None,
                            'total_payout': round(float(row['total_payout']), 2),
                            'match_type': 'campaign',
                        })

                else:
                    # Default: account search (overview / review tabs)
                    fraud_query = """
                        SELECT duid, email, risk_score, flags, payout_amount, data_type,
                               webmaster_code, campaign, analyzed_at, 'fraud_result' as source
                        FROM fraud_results
                        WHERE LOWER(email) LIKE ?
                           OR LOWER(duid) LIKE ?
                           OR LOWER(webmaster_code) LIKE ?
                           OR LOWER(campaign) LIKE ?
                        ORDER BY risk_score DESC
                        LIMIT ?
                    """
                    df = pd.read_sql_query(fraud_query, conn, params=[pattern, pattern, pattern, pattern, limit])
                    for _, row in df.iterrows():
                        results.append({
                            'type': 'account',
                            'duid': row['duid'],
                            'email': row['email'],
                            'risk_score': row['risk_score'],
                            'flags': row['flags'],
                            'payout_amount': row['payout_amount'],
                            'data_type': row['data_type'],
                            'webmaster_code': row['webmaster_code'],
                            'campaign': row['campaign'],
                            'source': 'analyzed',
                            'match_type': 'email' if query_lower in str(row['email']).lower() else
                                         'duid' if query_lower in str(row['duid']).lower() else
                                         'affiliate' if query_lower in str(row['webmaster_code']).lower() else 'campaign'
                        })

                    # Also search raw data if not enough results
                    if len(results) < limit:
                        remaining = limit - len(results)
                        existing_duids = {r['duid'] for r in results}

                        for table in ['paid', 'free']:
                            try:
                                raw_query = f"""
                                    SELECT duid, email, payout_amount, webmaster_code, campaign,
                                           '{table}' as data_type
                                    FROM {table}
                                    WHERE (LOWER(email) LIKE ? OR LOWER(duid) LIKE ?
                                           OR LOWER(webmaster_code) LIKE ?)
                                      AND duid NOT IN ({','.join(['?']*len(existing_duids)) if existing_duids else "''"})
                                    LIMIT ?
                                """
                                params = [pattern, pattern, pattern] + list(existing_duids) + [remaining]
                                raw_df = pd.read_sql_query(raw_query, conn, params=params)

                                for _, row in raw_df.iterrows():
                                    if row['duid'] not in existing_duids:
                                        results.append({
                                            'type': 'account',
                                            'duid': row['duid'],
                                            'email': row['email'],
                                            'risk_score': None,
                                            'flags': None,
                                            'payout_amount': row['payout_amount'],
                                            'data_type': row['data_type'],
                                            'webmaster_code': row['webmaster_code'],
                                            'campaign': row['campaign'],
                                            'source': 'raw',
                                            'match_type': 'email' if query_lower in str(row['email']).lower() else 'duid'
                                        })
                                        existing_duids.add(row['duid'])
                            except Exception as e:
                                logger.warning(f"Error searching {table}: {e}")

            return jsonify({
                'results': results[:limit],
                'query': query,
                'scope': scope,
                'count': len(results),
            })
        except Exception as e:
            logger.error(f"Error in /api/search: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/account/<duid>')
    def api_account_details(duid):
        """Get comprehensive account details"""
        try:
            import pandas as pd
            
            # Validate DUID format
            duid = validate_duid(duid)
            if not duid:
                return jsonify({'error': 'Invalid DUID format'}), 400
            
            with db.get_connection() as conn:
                # Get main account info from fraud_results
                account = None
                fraud_query = """
                    SELECT * FROM fraud_results WHERE duid = ? LIMIT 1
                """
                df = pd.read_sql_query(fraud_query, conn, params=[duid])
                
                if not df.empty:
                    account = df.iloc[0].to_dict()
                    account['source'] = 'analyzed'
                else:
                    # Try raw tables
                    for table in ['paid', 'free']:
                        try:
                            raw_query = f"SELECT * FROM {table} WHERE duid = ? LIMIT 1"
                            raw_df = pd.read_sql_query(raw_query, conn, params=[duid])
                            if not raw_df.empty:
                                account = raw_df.iloc[0].to_dict()
                                account['source'] = 'raw'
                                account['data_type'] = table
                                break
                        except:
                            continue
                
                if not account:
                    return jsonify({'error': 'Account not found'}), 404

                _merge_attribution_from_raw(conn, duid, account, pd)

                # Get outcome history
                outcome_query = """
                    SELECT outcome, outcome_notes AS notes, reviewed_at AS recorded_at, reviewed_by AS recorded_by
                    FROM fraud_outcomes
                    WHERE duid = ?
                    ORDER BY reviewed_at DESC
                """
                outcomes_df = pd.read_sql_query(outcome_query, conn, params=[duid])
                outcomes = outcomes_df.to_dict(orient='records') if not outcomes_df.empty else []
                
                # Find related accounts by email pattern
                related_by_email = []
                email = account.get('email', '')
                if email and '@' in email:
                    username = email.split('@')[0]
                    # Look for similar usernames (first 5 chars match)
                    if len(username) >= 5:
                        email_pattern = username[:5] + '%'
                        related_query = """
                            SELECT duid, email, risk_score, webmaster_code
                            FROM fraud_results
                            WHERE email LIKE ? AND duid != ?
                            ORDER BY risk_score DESC
                            LIMIT 10
                        """
                        related_df = pd.read_sql_query(related_query, conn, params=[email_pattern, duid])
                        related_by_email = related_df.to_dict(orient='records')
                
                # Find related accounts by IP (if available)
                related_by_ip = []
                ip = account.get('ip')
                if ip and ip not in ['', 'None', None]:
                    ip_query = """
                        SELECT duid, email, risk_score, webmaster_code
                        FROM fraud_results
                        WHERE ip = ? AND duid != ?
                        ORDER BY risk_score DESC
                        LIMIT 10
                    """
                    try:
                        ip_df = pd.read_sql_query(ip_query, conn, params=[ip, duid])
                        related_by_ip = ip_df.to_dict(orient='records')
                    except:
                        pass

                # IP geolocation enrichment (ISP, city, org) via ip-api.com
                ip_geo = {}
                if ip and ip not in ['', 'None', None]:
                    try:
                        import requests as req
                        geo_resp = req.get(
                            f'http://ip-api.com/json/{ip}',
                            params={'fields': 'status,country,countryCode,regionName,city,isp,org,as,proxy,hosting'},
                            timeout=4
                        )
                        if geo_resp.status_code == 200:
                            geo_data = geo_resp.json()
                            if geo_data.get('status') == 'success':
                                ip_geo = {
                                    'country':     geo_data.get('country'),
                                    'country_code': geo_data.get('countryCode'),
                                    'region':      geo_data.get('regionName'),
                                    'city':        geo_data.get('city'),
                                    'isp':         geo_data.get('isp'),
                                    'org':         geo_data.get('org'),
                                    'as':          geo_data.get('as'),
                                    'proxy':       geo_data.get('proxy'),
                                    'hosting':     geo_data.get('hosting'),
                                }
                                # Persist flags back to fraud_results so affiliate page can filter on them
                                db.save_ip_flags(
                                    duid,
                                    ip_proxy=bool(ip_geo.get('proxy')),
                                    ip_hosting=bool(ip_geo.get('hosting'))
                                )
                    except Exception as geo_err:
                        logger.debug(f"IP geo lookup failed for {ip}: {geo_err}")
                
                # Clean up NaN values
                for key, value in account.items():
                    if pd.isna(value):
                        account[key] = None

                # ── Admin platform enrichment (shared cards, image upload, reg/login IPs) ──
                admin_data = None
                admin_client = _admin_client_for_request()
                if admin_client:
                    try:
                        admin_data = admin_client.get_user_fraud_info(duid)
                    except Exception as admin_err:
                        logger.warning(f"Admin API lookup failed for {duid}: {admin_err}")
                        admin_data = {'error': str(admin_err)}

                return jsonify({
                    'account': account,
                    'outcomes': outcomes,
                    'related_by_email': related_by_email,
                    'related_by_ip': related_by_ip,
                    'ip_geo': ip_geo,
                    'admin': admin_data,
                })
        except Exception as e:
            logger.error(f"Error in /api/account/{duid}: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/revenue-impact')
    def api_revenue_impact():
        """Get revenue impact metrics"""
        try:
            import pandas as pd
            
            with db.get_connection() as conn:
                # Total payout from all analyzed accounts
                total_query = """
                    SELECT 
                        COUNT(*) as total_accounts,
                        SUM(payout_amount) as total_payout,
                        SUM(CASE WHEN risk_score >= 50 THEN payout_amount ELSE 0 END) as high_risk_payout,
                        SUM(CASE WHEN risk_score >= 25 AND risk_score < 50 THEN payout_amount ELSE 0 END) as medium_risk_payout,
                        SUM(CASE WHEN risk_score < 25 THEN payout_amount ELSE 0 END) as low_risk_payout,
                        COUNT(CASE WHEN risk_score >= 50 THEN 1 END) as high_risk_count,
                        COUNT(CASE WHEN risk_score >= 25 AND risk_score < 50 THEN 1 END) as medium_risk_count
                    FROM fraud_results
                """
                totals = pd.read_sql_query(total_query, conn).iloc[0].to_dict()
                
                # Confirmed fraud payout (actual_loss when set; else payout at review)
                fraud_query = """
                    SELECT 
                        COUNT(DISTINCT fo.duid) as confirmed_fraud_count,
                        SUM(COALESCE(NULLIF(fo.actual_loss, 0), fo.payout_amount, 0)) as confirmed_fraud_payout
                    FROM fraud_outcomes fo
                    JOIN fraud_results fr ON fo.duid = fr.duid
                    WHERE fo.outcome = 'confirmed_fraud'
                """
                fraud_stats = pd.read_sql_query(fraud_query, conn).iloc[0].to_dict()
                
                # False positives
                fp_query = """
                    SELECT 
                        COUNT(DISTINCT fo.duid) as false_positive_count,
                        SUM(fr.payout_amount) as false_positive_payout
                    FROM fraud_outcomes fo
                    JOIN fraud_results fr ON fo.duid = fr.duid
                    WHERE fo.outcome = 'false_positive'
                """
                fp_stats = pd.read_sql_query(fp_query, conn).iloc[0].to_dict()
                
                # Revenue impact over time (last 30 days)
                timeline_query = """
                    SELECT 
                        DATE(fr.analyzed_at) as date,
                        SUM(fr.payout_amount) as total_payout,
                        SUM(CASE WHEN fr.risk_score >= 50 THEN fr.payout_amount ELSE 0 END) as at_risk_payout,
                        COUNT(CASE WHEN fr.risk_score >= 50 THEN 1 END) as high_risk_count
                    FROM fraud_results fr
                    WHERE fr.analyzed_at >= DATE('now', '-30 days')
                    GROUP BY DATE(fr.analyzed_at)
                    ORDER BY date
                """
                timeline = pd.read_sql_query(timeline_query, conn)
                timeline_data = timeline.fillna(0).to_dict(orient='records')
                
                # Calculate metrics
                confirmed_payout = fraud_stats.get('confirmed_fraud_payout') or 0
                fp_payout = fp_stats.get('false_positive_payout') or 0
                high_risk_payout = totals.get('high_risk_payout') or 0
                total_payout = totals.get('total_payout') or 0
                
                # Precision estimate (if we have outcomes)
                total_reviewed = (fraud_stats.get('confirmed_fraud_count') or 0) + (fp_stats.get('false_positive_count') or 0)
                precision = 0
                if total_reviewed > 0:
                    precision = (fraud_stats.get('confirmed_fraud_count') or 0) / total_reviewed
                
                # Estimated savings (confirmed fraud payout that would have been lost)
                estimated_savings = confirmed_payout
                
                # Potential additional savings (unreviewed high-risk)
                unreviewed_at_risk = high_risk_payout - confirmed_payout - fp_payout
                
                return jsonify({
                    'totals': {
                        'total_accounts': int(totals.get('total_accounts') or 0),
                        'total_payout': float(total_payout),
                        'high_risk_payout': float(high_risk_payout),
                        'medium_risk_payout': float(totals.get('medium_risk_payout') or 0),
                        'low_risk_payout': float(totals.get('low_risk_payout') or 0),
                        'high_risk_count': int(totals.get('high_risk_count') or 0),
                        'medium_risk_count': int(totals.get('medium_risk_count') or 0),
                    },
                    'confirmed': {
                        'fraud_count': int(fraud_stats.get('confirmed_fraud_count') or 0),
                        'fraud_payout': float(confirmed_payout),
                        'false_positive_count': int(fp_stats.get('false_positive_count') or 0),
                        'false_positive_payout': float(fp_payout),
                    },
                    'impact': {
                        'estimated_savings': float(estimated_savings),
                        'potential_savings': float(unreviewed_at_risk) if unreviewed_at_risk > 0 else 0,
                        'precision': round(precision * 100, 1),
                        'fraud_rate': round((totals.get('high_risk_count') or 0) / max(totals.get('total_accounts') or 1, 1) * 100, 1),
                    },
                    'timeline': timeline_data
                })
        except Exception as e:
            logger.error(f"Error in /api/revenue-impact: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/house-affiliates')
    def api_house_affiliates():
        """Get list of house affiliates"""
        try:
            house = config.get_house_affiliates()
            return jsonify({
                'house_affiliates': house,
                'whitelisted_affiliates': config.get_whitelisted_affiliates(),
            })
        except Exception as e:
            logger.error(f"Error in /api/house-affiliates: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/house-affiliates', methods=['POST'])
    def api_update_house_affiliates():
        """Update house affiliates list"""
        try:
            data = request.get_json() or {}
            action = data.get('action')
            affiliate = sanitize_string(data.get('affiliate', ''), 100)
            
            if action == 'add' and affiliate:
                config.add_house_affiliate(affiliate)
                logger.info(f"Added house affiliate: {affiliate}")
                return jsonify({'status': 'ok', 'message': f'Added {affiliate}'})
            elif action == 'remove' and affiliate:
                config.remove_house_affiliate(affiliate)
                logger.info(f"Removed house affiliate: {affiliate}")
                return jsonify({'status': 'ok', 'message': f'Removed {affiliate}'})
            elif action == 'set':
                affiliates = data.get('affiliates', [])
                if isinstance(affiliates, list):
                    config.set('house_affiliates', [sanitize_string(a, 100) for a in affiliates if a])
                    return jsonify({'status': 'ok', 'message': f'Set {len(affiliates)} house affiliates'})
            else:
                return jsonify({'error': 'Invalid action. Use add, remove, or set'}), 400
            
            return jsonify({'error': 'Missing required parameters'}), 400
        except Exception as e:
            logger.error(f"Error updating house affiliates: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/stats')
    def api_stats():
        try:
            stats = db.get_fraud_statistics()
            
            # Add velocity metrics (compare last 7 days vs previous 7 days)
            import pandas as pd
            with db.get_connection() as conn:
                velocity_query = """
                    SELECT 
                        SUM(CASE WHEN analyzed_at >= DATE('now', '-7 days') THEN 1 ELSE 0 END) as recent_total,
                        SUM(CASE WHEN analyzed_at >= DATE('now', '-14 days') AND analyzed_at < DATE('now', '-7 days') THEN 1 ELSE 0 END) as prev_total,
                        SUM(CASE WHEN analyzed_at >= DATE('now', '-7 days') AND risk_score >= 50 THEN 1 ELSE 0 END) as recent_high_risk,
                        SUM(CASE WHEN analyzed_at >= DATE('now', '-14 days') AND analyzed_at < DATE('now', '-7 days') AND risk_score >= 50 THEN 1 ELSE 0 END) as prev_high_risk,
                        SUM(CASE WHEN analyzed_at >= DATE('now', '-7 days') AND risk_score >= 50 THEN payout_amount ELSE 0 END) as recent_at_risk,
                        SUM(CASE WHEN analyzed_at >= DATE('now', '-14 days') AND analyzed_at < DATE('now', '-7 days') AND risk_score >= 50 THEN payout_amount ELSE 0 END) as prev_at_risk
                    FROM fraud_results
                """
                velocity = pd.read_sql_query(velocity_query, conn).iloc[0].to_dict()
            
            # Calculate % changes
            def calc_change(recent, prev):
                if not prev or prev == 0:
                    return None
                return round((recent - prev) / prev * 100, 1)
            
            stats['velocity'] = {
                'total_change': calc_change(velocity.get('recent_total') or 0, velocity.get('prev_total') or 0),
                'high_risk_change': calc_change(velocity.get('recent_high_risk') or 0, velocity.get('prev_high_risk') or 0),
                'revenue_change': calc_change(velocity.get('recent_at_risk') or 0, velocity.get('prev_at_risk') or 0),
                'recent_high_risk': int(velocity.get('recent_high_risk') or 0),
                'prev_high_risk': int(velocity.get('prev_high_risk') or 0),
            }
            
            # Add paid vs free breakdown
            with db.get_connection() as conn:
                breakdown_query = """
                    SELECT 
                        data_type,
                        COUNT(*) as total,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) as high_risk,
                        SUM(CASE WHEN risk_score >= 25 AND risk_score < 50 THEN 1 ELSE 0 END) as medium_risk,
                        SUM(CASE WHEN risk_score >= 50 THEN payout_amount ELSE 0 END) as high_risk_payout
                    FROM fraud_results
                    GROUP BY data_type
                """
                breakdown = pd.read_sql_query(breakdown_query, conn)
                stats['by_type'] = breakdown.to_dict(orient='records')
            
            return jsonify(stats)
        except Exception as e:
            logger.error(f"Error in /api/stats: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/fraud-results')
    def api_fraud_results():
        try:
            min_risk = request.args.get('min_risk', type=int)
            max_risk = request.args.get('max_risk', type=int)
            limit = max(1, min(request.args.get('limit', 100, type=int), 50_000))
            # By default exclude accounts already reviewed; pass ?exclude_reviewed=0 to see all
            exclude_reviewed = request.args.get('exclude_reviewed', '1') != '0'
            outcome = (request.args.get('outcome', '') or '').strip()
            if outcome not in ('', 'any', 'confirmed_fraud', 'false_positive', 'under_review'):
                return jsonify({'error': 'Invalid outcome filter'}), 400
            outcome_arg = '__any__' if outcome == 'any' else (outcome if outcome else None)
            if exclude_reviewed and outcome_arg:
                return jsonify({'error': 'Cannot combine exclude_reviewed with outcome filter'}), 400
            analyzed_date_from = request.args.get('analyzed_date_from', '').strip() or None
            analyzed_date_to = request.args.get('analyzed_date_to', '').strip() or None
            total = db.count_fraud_results(
                min_risk=min_risk,
                max_risk=max_risk,
                exclude_reviewed=exclude_reviewed,
                outcome=outcome_arg,
                analyzed_date_from=analyzed_date_from,
                analyzed_date_to=analyzed_date_to,
            )
            df = db.get_fraud_results(
                min_risk=min_risk,
                max_risk=max_risk,
                limit=limit,
                exclude_reviewed=exclude_reviewed,
                outcome=outcome_arg,
                analyzed_date_from=analyzed_date_from,
                analyzed_date_to=analyzed_date_to,
            )
            # Select safe columns that exist
            cols = [c for c in ['duid', 'email', 'risk_score', 'flags', 'payout_amount',
                                'data_type', 'analyzed_at', 'webmaster_code', 'campaign'] if c in df.columns]
            records = df[cols].fillna('').to_dict(orient='records')
            return jsonify({
                'records': records,
                'total': int(total),
                'limit': limit,
                'truncated': int(total) > len(records),
            })
        except Exception as e:
            logger.error(f"Error in /api/fraud-results: {e}")
            return api_error('Failed to load fraud results', 500, details=e)

    @app.route('/api/affiliates')
    def api_affiliates():
        try:
            df = db.get_affiliate_fraud_stats()
            return jsonify(df.fillna(0).to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/affiliates: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/campaigns')
    def api_campaigns():
        """Get distinct campaigns from source tables for filter dropdowns."""
        try:
            import pandas as pd
            with db.get_connection() as conn:
                df = pd.read_sql_query("""
                    SELECT campaign,
                           COUNT(DISTINCT duid) AS account_count
                    FROM (
                        SELECT campaign, duid FROM free
                         WHERE campaign IS NOT NULL AND campaign != ''
                        UNION ALL
                        SELECT campaign, duid FROM paid
                         WHERE campaign IS NOT NULL AND campaign != ''
                    )
                    GROUP BY campaign
                    ORDER BY account_count DESC
                """, conn)
            return jsonify(df.fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/campaigns: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/source-affiliates')
    def api_source_affiliates():
        """Get affiliates from source data (free/paid tables) for filtering"""
        try:
            import sqlite3
            import pandas as pd
            conn = sqlite3.connect(db.db_path)
            cursor = conn.cursor()
            
            # Check which columns exist in each table
            cursor.execute("PRAGMA table_info(free)")
            free_columns = [row[1] for row in cursor.fetchall()]
            
            cursor.execute("PRAGMA table_info(paid)")
            paid_columns = [row[1] for row in cursor.fetchall()]
            
            logger.info(f"Free table columns: {free_columns}")
            logger.info(f"Paid table columns: {paid_columns}")
            
            # Determine the correct affiliate column for free table
            free_affiliate_col = None
            if 'webmaster_code' in free_columns:
                free_affiliate_col = 'webmaster_code'
            elif 'site_code' in free_columns:
                free_affiliate_col = 'site_code'
            
            # Determine the correct affiliate column for paid table
            paid_affiliate_col = None
            if 'webmaster_code' in paid_columns:
                paid_affiliate_col = 'webmaster_code'
            elif 'site_code' in paid_columns:
                paid_affiliate_col = 'site_code'
            
            results = []
            
            # Get affiliates from free table
            if free_affiliate_col:
                free_query = f"SELECT {free_affiliate_col} as code, COUNT(*) as count FROM free WHERE {free_affiliate_col} IS NOT NULL AND TRIM({free_affiliate_col}) != '' GROUP BY {free_affiliate_col}"
                free_df = pd.read_sql_query(free_query, conn)
                logger.info(f"Found {len(free_df)} affiliates from free table using {free_affiliate_col}")
                results.append(free_df)
            else:
                logger.warning("No affiliate column found in free table")
            
            # Get affiliates from paid table  
            if paid_affiliate_col:
                paid_query = f"SELECT {paid_affiliate_col} as code, COUNT(*) as count FROM paid WHERE {paid_affiliate_col} IS NOT NULL AND TRIM({paid_affiliate_col}) != '' GROUP BY {paid_affiliate_col}"
                paid_df = pd.read_sql_query(paid_query, conn)
                logger.info(f"Found {len(paid_df)} affiliates from paid table using {paid_affiliate_col}")
                results.append(paid_df)
            else:
                logger.warning("No affiliate column found in paid table")
            
            conn.close()
            
            # Combine and aggregate
            if results:
                combined = pd.concat(results, ignore_index=True)
                if not combined.empty:
                    affiliates = combined.groupby('code')['count'].sum().reset_index()
                    affiliates.columns = ['code', 'total_accounts']
                    affiliates = affiliates.sort_values('total_accounts', ascending=False)
                    result = affiliates.to_dict(orient='records')
                else:
                    result = []
            else:
                result = []
            
            logger.info(f"Found {len(result)} total source affiliates")
            return jsonify({'affiliates': result})
            
        except Exception as e:
            logger.error(f"Error in /api/source-affiliates: {e}", exc_info=True)
            return jsonify({'error': str(e), 'affiliates': []}), 500

    @app.route('/api/backfill-affiliates', methods=['POST'])
    def api_backfill_affiliates():
        """Backfill missing affiliate data from source tables"""
        try:
            result = db.backfill_affiliates()
            logger.info(f"Backfill affiliates result: {result}")
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error in /api/backfill-affiliates: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/rescore-woman-concentration', methods=['POST'])
    def api_rescore_woman_concentration():
        """
        Re-apply WOMAN concentration flags to existing fraud_results only.
        Does not re-run full fraud analysis or touch free/paid source rows.
        """
        try:
            scripts_dir = Path(__file__).resolve().parent.parent / 'scripts'
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            from email_fraud_detector import rescore_woman_concentration_from_fraud_results_table

            out = rescore_woman_concentration_from_fraud_results_table(db, app.config_obj)
            out['database_path'] = getattr(db, 'db_path', None)
            logger.info(f"Rescore woman concentration: {out}")
            return jsonify(sanitize_for_json(out))
        except Exception as e:
            logger.error(f"Error in /api/rescore-woman-concentration: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/rescore-sequential-email', methods=['POST'])
    def api_rescore_sequential_email():
        """Re-apply SEQUENTIAL_EMAIL flags on saved fraud_results only."""
        try:
            scripts_dir = Path(__file__).resolve().parent.parent / 'scripts'
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            from email_fraud_detector import rescore_sequential_email_from_fraud_results_table

            out = rescore_sequential_email_from_fraud_results_table(db, app.config_obj)
            out['database_path'] = getattr(db, 'db_path', None)
            logger.info(f"Rescore sequential email: {out}")
            return jsonify(sanitize_for_json(out))
        except Exception as e:
            logger.error(f"Error in /api/rescore-sequential-email: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/affiliate/<code>/details')
    def api_affiliate_details(code):
        try:
            import pandas as pd
            code = sanitize_string(code, 100)
            if not code:
                return jsonify({'error': 'Invalid affiliate code'}), 400

            page      = max(1, int(request.args.get('page', 1)))
            # UI uses ≤200; CSV export requests up to 5000 rows
            page_size = max(10, min(int(request.args.get('page_size', 100)), 5000))
            risk_min  = request.args.get('risk_min', '')       # '', '25', or '50'
            search_q  = request.args.get('q', '').strip().lower()
            campaign_filter = request.args.get('campaign', '').strip()
            data_type = request.args.get('data_type', '')      # '', 'paid', 'free'
            sort_col  = request.args.get('sort', 'risk_score')
            sort_dir  = request.args.get('dir', 'desc')

            valid_sort_cols = {'risk_score', 'payout_amount', 'email', 'campaign', 'data_type', 'duid', 'ip_proxy', 'ip_hosting', 'trans_datetime'}
            if sort_col not in valid_sort_cols:
                sort_col = 'risk_score'
            sort_dir = 'ASC' if sort_dir == 'asc' else 'DESC'

            # Build WHERE clause (fr.* for JOIN queries; bare for single-table count)
            where_fr = ["fr.webmaster_code = ?"]
            where_bare = ["webmaster_code = ?"]
            params = [code]

            if risk_min in ('25', '50'):
                where_fr.append("fr.risk_score >= ?")
                where_bare.append("risk_score >= ?")
                params.append(int(risk_min))

            if data_type in ('paid', 'free'):
                where_fr.append("fr.data_type = ?")
                where_bare.append("data_type = ?")
                params.append(data_type)

            ip_flag = request.args.get('ip_flag', '')   # 'proxy', 'hosting', 'either'
            profile_pic = request.args.get('profile_pic', '')  # 'has', 'none', 'not_enriched', 'content_review'
            if ip_flag == 'proxy':
                where_fr.append("fr.ip_proxy = 1")
                where_bare.append("ip_proxy = 1")
            elif ip_flag == 'hosting':
                where_fr.append("fr.ip_hosting = 1")
                where_bare.append("ip_hosting = 1")
            elif ip_flag == 'either':
                where_fr.append("(fr.ip_proxy = 1 OR fr.ip_hosting = 1)")
                where_bare.append("(ip_proxy = 1 OR ip_hosting = 1)")

            if profile_pic == 'has':
                where_fr.append("fr.profile_image_uploaded = 1")
                where_bare.append("profile_image_uploaded = 1")
            elif profile_pic == 'none':
                where_fr.append("fr.admin_enriched = 1 AND fr.profile_image_uploaded = 0")
                where_bare.append("admin_enriched = 1 AND profile_image_uploaded = 0")
            elif profile_pic == 'not_enriched':
                where_fr.append("COALESCE(fr.admin_enriched, 0) = 0")
                where_bare.append("COALESCE(admin_enriched, 0) = 0")
            elif profile_pic == 'content_review':
                where_fr.append("fr.flags LIKE '%CONTENT_REVIEW%'")
                where_bare.append("flags LIKE '%CONTENT_REVIEW%'")

            date_from = request.args.get('date_from', '').strip()
            date_to   = request.args.get('date_to',   '').strip()
            if date_from:
                where_fr.append("DATE(fr.trans_datetime) >= ?")
                where_bare.append("DATE(trans_datetime) >= ?")
                params.append(date_from)
            if date_to:
                where_fr.append("DATE(fr.trans_datetime) <= ?")
                where_bare.append("DATE(trans_datetime) <= ?")
                params.append(date_to)

            if campaign_filter:
                where_fr.append("LOWER(fr.campaign) = LOWER(?)")
                where_bare.append("LOWER(campaign) = LOWER(?)")
                params.append(campaign_filter)

            if search_q:
                where_fr.append(
                    "(LOWER(fr.email) LIKE ? OR LOWER(fr.campaign) LIKE ? OR LOWER(fr.duid) LIKE ? OR LOWER(fr.flags) LIKE ?)"
                )
                where_bare.append(
                    "(LOWER(email) LIKE ? OR LOWER(campaign) LIKE ? OR LOWER(duid) LIKE ? OR LOWER(flags) LIKE ?)"
                )
                like = f'%{search_q}%'
                params.extend([like, like, like, like])

            where_sql_fr = ' AND '.join(where_fr)
            where_sql_bare = ' AND '.join(where_bare)

            with db.get_connection() as conn:
                # Total count (same filters as list)
                count_row = conn.execute(
                    f"SELECT COUNT(*) FROM fraud_results WHERE {where_sql_bare}", params
                ).fetchone()
                total = count_row[0] if count_row else 0

                # Review / confirmed fraud totals for this affiliate (not narrowed by table filters)
                oc = conn.execute(
                    """
                    SELECT
                        SUM(CASE WHEN fo.outcome = 'confirmed_fraud' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN fo.outcome = 'confirmed_fraud'
                            THEN COALESCE(NULLIF(fo.actual_loss, 0), fo.payout_amount, 0) ELSE 0 END),
                        SUM(CASE WHEN fo.outcome = 'false_positive' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN fo.outcome = 'false_positive'
                            THEN COALESCE(fo.payout_amount, 0) ELSE 0 END)
                    FROM fraud_results fr
                    LEFT JOIN fraud_outcomes fo ON fr.duid = fo.duid
                    WHERE fr.webmaster_code = ?
                    """,
                    (code,),
                ).fetchone()
                outcome_summary = {
                    'confirmed_fraud_count': int(oc[0] or 0),
                    'confirmed_fraud_payout': float(oc[1] or 0),
                    'false_positive_count': int(oc[2] or 0),
                    'false_positive_payout': float(oc[3] or 0),
                }

                # Paged rows (include review outcome + attributed fraud $)
                offset = (page - 1) * page_size
                rows_df = pd.read_sql_query(
                    f"""SELECT fr.duid, fr.email, fr.risk_score, fr.flags, fr.payout_amount,
                               fr.campaign, fr.ad_id, fr.trans_datetime, fr.data_type, fr.webmaster_code,
                               fr.custom_u1, fr.geo_country, fr.ip, fr.ip_proxy, fr.ip_hosting,
                               fr.profile_image_uploaded, fr.profile_image_upload_seconds, fr.admin_enriched,
                               fo.outcome AS review_outcome,
                               CASE WHEN fo.outcome = 'confirmed_fraud'
                                    THEN COALESCE(NULLIF(fo.actual_loss, 0), fo.payout_amount, 0)
                                    ELSE NULL END AS confirmed_fraud_payout
                        FROM fraud_results fr
                        LEFT JOIN fraud_outcomes fo ON fr.duid = fo.duid
                        WHERE {where_sql_fr}
                        ORDER BY fr.{sort_col} {sort_dir}
                        LIMIT ? OFFSET ?""",
                    conn,
                    params=params + [page_size, offset]
                )

                camp_rows = conn.execute(
                    """
                    SELECT DISTINCT campaign
                    FROM fraud_results
                    WHERE webmaster_code = ?
                      AND campaign IS NOT NULL
                      AND TRIM(campaign) != ''
                    ORDER BY campaign COLLATE NOCASE
                    """,
                    (code,),
                ).fetchall()
                campaigns = [r[0] for r in camp_rows if r[0]]

            action_row = db.get_affiliate_action(code)
            fast_seconds = int(app.config_obj.get('profile_image_fast_seconds', 180) or 180)
            accounts = rows_df.fillna('').to_dict(orient='records')
            for rec in accounts:
                flags = rec.get('flags')
                rec['needs_content_review'] = (
                    'Y' if (
                        has_content_review_flag(flags)
                        or needs_content_review(
                            rec.get('profile_image_uploaded'),
                            rec.get('profile_image_upload_seconds'),
                            flags,
                            fast_seconds=fast_seconds,
                        )
                    ) else 'N'
                )
                duid = rec.get('duid')
                rec['review_url'] = f'/account/{duid}' if duid not in (None, '') else ''

            return jsonify({
                'accounts':   accounts,
                'total':      total,
                'page':       page,
                'page_size':  page_size,
                'pages':      max(1, -(-total // page_size)),  # ceiling division
                'outcome_summary': outcome_summary,
                'affiliate_action': action_row,
                'campaigns': campaigns,
            })
        except Exception as e:
            logger.error(f"Error in /api/affiliate/{code}/details: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/campaign/<campaign>/accounts')
    def api_campaign_accounts(campaign):
        """Get individual accounts for a specific campaign"""
        try:
            import pandas as pd
            campaign = sanitize_string(campaign, 200)
            if not campaign:
                return jsonify({'error': 'Campaign parameter required'}), 400

            with db.get_connection() as conn:
                query = """
                    SELECT duid, email, risk_score, flags, payout_amount,
                           webmaster_code, data_type, campaign
                    FROM fraud_results
                    WHERE campaign = ?
                    ORDER BY risk_score DESC
                    LIMIT 500
                """
                df = pd.read_sql_query(query, conn, params=[campaign])

            return jsonify(df.fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/campaign/{campaign}/accounts: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/billing')
    def api_billing():
        try:
            df = db.get_billing_correlations(min_accounts=2)
            return jsonify(df.fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/billing: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/billing/names')
    def api_billing_names():
        try:
            qa_names = config.get_qa_billing_names()
            df = db.get_name_correlations(min_accounts=2, exclude_names=qa_names)
            return jsonify(df.fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/billing/names: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/billing/ips')
    def api_billing_ips():
        try:
            df = db.get_ip_billing_correlations()
            return jsonify(df.fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/billing/ips: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/billing/cluster/<billing_id>')
    def api_billing_cluster_details(billing_id):
        """Get accounts in a billing cluster"""
        try:
            billing_id = sanitize_string(billing_id, 100)
            df = db.get_billing_cluster_details(billing_id)
            if df is None or df.empty:
                return jsonify([])
            return jsonify(df.fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/billing/cluster: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/cluster/ip/<ip>')
    def api_cluster_by_ip(ip):
        """Get accounts sharing an IP address"""
        try:
            import pandas as pd
            ip = sanitize_string(ip, 50)
            
            with db.get_connection() as conn:
                query = """
                    SELECT duid, email, risk_score, flags, payout_amount, webmaster_code, campaign
                    FROM fraud_results
                    WHERE ip = ?
                    ORDER BY risk_score DESC
                    LIMIT 2000
                """
                df = pd.read_sql_query(query, conn, params=[ip])
            
            return jsonify(df.fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/cluster/ip: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/cluster/domain/<domain>')
    def api_cluster_by_domain(domain):
        """Get accounts by email domain"""
        try:
            import pandas as pd
            domain = sanitize_string(domain, 100)
            
            with db.get_connection() as conn:
                query = """
                    SELECT duid, email, risk_score, flags, payout_amount, webmaster_code, campaign
                    FROM fraud_results
                    WHERE LOWER(email) LIKE ?
                    ORDER BY risk_score DESC
                    LIMIT 2000
                """
                df = pd.read_sql_query(query, conn, params=[f'%@{domain.lower()}'])
            
            return jsonify(df.fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/cluster/domain: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/billing/name/<name>')
    def api_billing_by_name(name):
        """Get accounts by billing name"""
        try:
            import pandas as pd
            name = sanitize_string(name, 100)
            
            with db.get_connection() as conn:
                query = """
                    SELECT p.duid, p.email, p.first_name, p.last_name, p.payout_amount, 
                           p.webmaster_code, p.processor_subscriber_id,
                           p.campaign, p.trans_datetime,
                           fr.risk_score, fr.flags, fr.ip
                    FROM paid p
                    LEFT JOIN fraud_results fr ON p.duid = fr.duid
                    WHERE LOWER(p.first_name || ' ' || p.last_name) = LOWER(?)
                    ORDER BY fr.risk_score DESC NULLS LAST
                    LIMIT 200
                """
                df = pd.read_sql_query(query, conn, params=[name])
            
            return jsonify(df.fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/billing/name: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/billing/summary')
    def api_billing_summary():
        try:
            summary = db.get_high_risk_billing_summary()
            return jsonify(summary)
        except Exception as e:
            logger.error(f"Error in /api/billing/summary: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/cluster-detail/<cluster_type>/<path:cluster_id>')
    def api_cluster_detail(cluster_type, cluster_id):
        """Full cluster investigation data for the dedicated cluster page (paginated)."""
        try:
            import pandas as pd
            from collections import Counter

            valid_types = {'ip', 'domain', 'name', 'affiliate'}
            cluster_type = sanitize_string(cluster_type, 20)
            if cluster_type not in valid_types:
                return jsonify({'error': 'Invalid cluster type'}), 400
            cluster_id = sanitize_string(cluster_id, 200)
            if not cluster_id:
                return jsonify({'error': 'Invalid cluster ID'}), 400

            page = max(1, int(request.args.get('page', 1)))
            per_page = min(500, max(10, int(request.args.get('per_page', 100))))
            offset = (page - 1) * per_page

            def _agg_ip(cur, ip):
                row = cur.execute("""
                    SELECT COUNT(*) AS c,
                           SUM(CASE WHEN CAST(risk_score AS REAL) >= 50 THEN 1 ELSE 0 END) AS hr,
                           SUM(CASE WHEN CAST(risk_score AS REAL) >= 25 AND CAST(risk_score AS REAL) < 50 THEN 1 ELSE 0 END) AS mr,
                           AVG(CAST(risk_score AS REAL)) AS av,
                           SUM(CAST(COALESCE(payout_amount, 0) AS REAL)) AS tp,
                           COUNT(DISTINCT NULLIF(webmaster_code, '')) AS ua,
                           COUNT(DISTINCT NULLIF(ip, '')) AS ui
                    FROM fraud_results WHERE ip = ?
                """, (ip,)).fetchone()
                return row

            def _agg_domain(cur, dom):
                like = f'%@{dom.lower()}'
                row = cur.execute("""
                    SELECT COUNT(*) AS c,
                           SUM(CASE WHEN CAST(risk_score AS REAL) >= 50 THEN 1 ELSE 0 END) AS hr,
                           SUM(CASE WHEN CAST(risk_score AS REAL) >= 25 AND CAST(risk_score AS REAL) < 50 THEN 1 ELSE 0 END) AS mr,
                           AVG(CAST(risk_score AS REAL)) AS av,
                           SUM(CAST(COALESCE(payout_amount, 0) AS REAL)) AS tp,
                           COUNT(DISTINCT NULLIF(webmaster_code, '')) AS ua,
                           COUNT(DISTINCT NULLIF(ip, '')) AS ui
                    FROM fraud_results WHERE LOWER(email) LIKE ?
                """, (like,)).fetchone()
                return row

            def _agg_affiliate(cur, code):
                row = cur.execute("""
                    SELECT COUNT(*) AS c,
                           SUM(CASE WHEN CAST(risk_score AS REAL) >= 50 THEN 1 ELSE 0 END) AS hr,
                           SUM(CASE WHEN CAST(risk_score AS REAL) >= 25 AND CAST(risk_score AS REAL) < 50 THEN 1 ELSE 0 END) AS mr,
                           AVG(CAST(risk_score AS REAL)) AS av,
                           SUM(CAST(COALESCE(payout_amount, 0) AS REAL)) AS tp,
                           COUNT(DISTINCT NULLIF(webmaster_code, '')) AS ua,
                           COUNT(DISTINCT NULLIF(ip, '')) AS ui
                    FROM fraud_results WHERE webmaster_code = ?
                """, (code,)).fetchone()
                return row

            def _agg_name(cur, name):
                row = cur.execute("""
                    SELECT COUNT(*) AS c,
                           SUM(CASE WHEN COALESCE(CAST(fr.risk_score AS REAL), 0) >= 50 THEN 1 ELSE 0 END) AS hr,
                           SUM(CASE WHEN COALESCE(CAST(fr.risk_score AS REAL), 0) >= 25
                                    AND COALESCE(CAST(fr.risk_score AS REAL), 0) < 50 THEN 1 ELSE 0 END) AS mr,
                           AVG(COALESCE(CAST(fr.risk_score AS REAL), 0)) AS av,
                           SUM(CAST(COALESCE(p.payout_amount, 0) AS REAL)) AS tp,
                           COUNT(DISTINCT NULLIF(p.webmaster_code, '')) AS ua,
                           COUNT(DISTINCT NULLIF(fr.ip, '')) AS ui,
                           COUNT(DISTINCT NULLIF(p.processor_subscriber_id, '')) AS uc
                    FROM paid p
                    LEFT JOIN fraud_results fr ON p.duid = fr.duid
                    WHERE LOWER(TRIM(p.first_name || ' ' || p.last_name)) = LOWER(TRIM(?))
                """, (name,)).fetchone()
                return row

            with db.get_connection() as conn:
                cur = conn.cursor()

                if cluster_type == 'ip':
                    agg = _agg_ip(cur, cluster_id)
                    total = int(agg[0] or 0)
                    accounts_df = pd.read_sql_query("""
                        SELECT duid, email, risk_score, flags, payout_amount,
                               webmaster_code, campaign, ip, data_type, trans_datetime
                        FROM fraud_results
                        WHERE ip = ?
                        ORDER BY CAST(risk_score AS REAL) DESC
                        LIMIT ? OFFSET ?
                    """, conn, params=[cluster_id, per_page, offset])
                    summary_extra = {}

                elif cluster_type == 'domain':
                    like = f'%@{cluster_id.lower()}'
                    agg = _agg_domain(cur, cluster_id)
                    total = int(agg[0] or 0)
                    accounts_df = pd.read_sql_query("""
                        SELECT duid, email, risk_score, flags, payout_amount,
                               webmaster_code, campaign, ip, data_type, trans_datetime
                        FROM fraud_results
                        WHERE LOWER(email) LIKE ?
                        ORDER BY CAST(risk_score AS REAL) DESC
                        LIMIT ? OFFSET ?
                    """, conn, params=[like, per_page, offset])
                    summary_extra = {}

                elif cluster_type == 'name':
                    agg = _agg_name(cur, cluster_id)
                    total = int(agg[0] or 0)
                    accounts_df = pd.read_sql_query("""
                        SELECT p.duid, p.email, p.first_name, p.last_name,
                               p.payout_amount, p.webmaster_code, p.processor_subscriber_id,
                               p.campaign, p.trans_datetime,
                               fr.risk_score, fr.flags, fr.ip
                        FROM paid p
                        LEFT JOIN fraud_results fr ON p.duid = fr.duid
                        WHERE LOWER(TRIM(p.first_name || ' ' || p.last_name)) = LOWER(TRIM(?))
                        ORDER BY COALESCE(CAST(fr.risk_score AS REAL), 0) DESC
                        LIMIT ? OFFSET ?
                    """, conn, params=[cluster_id, per_page, offset])
                    summary_extra = {'unique_cards': int(agg[7] or 0)}

                else:  # affiliate
                    agg = _agg_affiliate(cur, cluster_id)
                    total = int(agg[0] or 0)
                    accounts_df = pd.read_sql_query("""
                        SELECT duid, email, risk_score, flags, payout_amount,
                               webmaster_code, campaign, ip, data_type, trans_datetime
                        FROM fraud_results
                        WHERE webmaster_code = ?
                        ORDER BY CAST(risk_score AS REAL) DESC
                        LIMIT ? OFFSET ?
                    """, conn, params=[cluster_id, per_page, offset])
                    summary_extra = {}

            total_pages = max(1, (total + per_page - 1) // per_page) if total else 1

            if total == 0:
                return jsonify({
                    'summary': {},
                    'accounts': [],
                    'flag_breakdown': {},
                    'pagination': {'page': 1, 'per_page': per_page, 'total': 0, 'total_pages': 1},
                })

            accounts_df = accounts_df.fillna('')

            c, hr, mr, av, tp, ua, ui = agg[0], agg[1], agg[2], agg[3], agg[4], agg[5], agg[6]
            high_risk = int(hr or 0)
            med_risk = int(mr or 0)
            avg_risk = round(float(av or 0), 1)
            total_payout = round(float(tp or 0), 2)

            # Flag breakdown: sample up to 5000 rows for performance
            all_flags = []
            with db.get_connection() as conn2:
                if cluster_type == 'ip':
                    flag_rows = conn2.execute(
                        "SELECT flags FROM fraud_results WHERE ip = ? LIMIT 5000",
                        (cluster_id,)
                    ).fetchall()
                elif cluster_type == 'domain':
                    flag_rows = conn2.execute(
                        "SELECT flags FROM fraud_results WHERE LOWER(email) LIKE ? LIMIT 5000",
                        (f'%@{cluster_id.lower()}',)
                    ).fetchall()
                elif cluster_type == 'name':
                    flag_rows = conn2.execute("""
                        SELECT fr.flags FROM paid p
                        LEFT JOIN fraud_results fr ON p.duid = fr.duid
                        WHERE LOWER(TRIM(p.first_name || ' ' || p.last_name)) = LOWER(TRIM(?))
                        LIMIT 5000
                    """, (cluster_id,)).fetchall()
                else:
                    flag_rows = conn2.execute(
                        "SELECT flags FROM fraud_results WHERE webmaster_code = ? LIMIT 5000",
                        (cluster_id,)
                    ).fetchall()
            for (flags_val,) in flag_rows:
                if flags_val:
                    cleaned = str(flags_val).replace('[', '').replace(']', '').replace("'", '')
                    for f in cleaned.split(','):
                        f = f.strip()
                        if f:
                            all_flags.append(f)
            flag_counts = dict(Counter(all_flags).most_common(15))

            summary = {
                'total_accounts': int(c or 0),
                'high_risk': high_risk,
                'medium_risk': med_risk,
                'avg_risk': avg_risk,
                'total_payout': total_payout,
                'unique_affiliates': int(ua or 0),
                'unique_ips': int(ui or 0),
                **summary_extra
            }

            return jsonify({
                'summary': summary,
                'accounts': accounts_df.to_dict(orient='records'),
                'flag_breakdown': flag_counts,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total,
                    'total_pages': total_pages,
                },
            })

        except Exception as e:
            logger.error(f"Error in /api/cluster-detail/{cluster_type}/{cluster_id}: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/billing/shared-card-signals')
    def api_billing_shared_card_signals():
        """Accounts with admin-enriched shared-card signal (count of other DUIDs on same card)."""
        try:
            import pandas as pd
            whitelisted_duids = set(config.get_whitelisted_duids())
            skip_affiliates = config.get_affiliate_analysis_skip_codes_lower(
                include_house_in_analysis=False
            )
            with db.get_connection() as conn:
                df = pd.read_sql_query("""
                    SELECT duid, email, risk_score, flags, payout_amount, webmaster_code,
                           shared_card_count, admin_enrichment_flags
                    FROM fraud_results
                    WHERE admin_enriched = 1 AND COALESCE(shared_card_count, 0) >= 1
                    ORDER BY shared_card_count DESC, CAST(risk_score AS REAL) DESC
                    LIMIT 500
                """, conn)
            if not df.empty:
                if whitelisted_duids:
                    df = df[~df['duid'].astype(str).isin(whitelisted_duids)]
                if skip_affiliates and 'webmaster_code' in df.columns:
                    codes = df['webmaster_code'].astype(str).str.strip().str.lower()
                    df = df[~codes.isin(skip_affiliates)]
            return jsonify(df.fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/billing/shared-card-signals: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/outcomes', methods=['POST'])
    def api_record_outcome():
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'JSON body required'}), 400
            
            duid = data.get('duid', '')
            
            # Validate DUID format
            duid = validate_duid(duid)
            if not duid:
                return jsonify({'error': 'Invalid DUID format'}), 400
            
            outcome = data.get('outcome')
            notes = sanitize_string(data.get('notes', ''), 1000)
            
            # Validate outcome
            if not validate_outcome(outcome):
                return jsonify({'error': f'Invalid outcome. Must be one of: {", ".join(VALID_OUTCOMES)}'}), 400
            
            # Retry logic for database lock
            import time
            max_retries = 3
            retry_delay = 0.1  # 100ms
            
            for attempt in range(max_retries):
                try:
                    success = db.record_fraud_outcome(duid, outcome, notes=notes, reviewed_by='dashboard')
                    if success:
                        logger.info(f"Outcome recorded: {duid} -> {outcome}")
                        return jsonify({'status': 'ok'})
                    else:
                        return jsonify({'error': 'Failed to record outcome. DUID may not exist.'}), 400
                except Exception as db_error:
                    if 'database is locked' in str(db_error) and attempt < max_retries - 1:
                        logger.warning(f"Database locked, retry {attempt + 1}/{max_retries}")
                        time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                        continue
                    raise
                    
        except Exception as e:
            logger.error(f"Error in POST /api/outcomes: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/affiliate-actions', methods=['GET'])
    def api_list_affiliate_actions():
        """All affiliate-level tool actions (badges, filters)."""
        try:
            rows = db.list_affiliate_actions()
            return jsonify(rows)
        except Exception as e:
            logger.error(f"Error in GET /api/affiliate-actions: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/affiliate-actions', methods=['POST'])
    def api_upsert_affiliate_action():
        """Create or update affiliate action from fraud-tool review."""
        try:
            data = request.get_json() or {}
            code = sanitize_string(data.get('webmaster_code', ''), 100)
            if not code:
                return jsonify({'error': 'webmaster_code required'}), 400

            status = sanitize_string(data.get('action_status', ''), 40).lower()
            if status not in VALID_AFFILIATE_ACTION_STATUS:
                return jsonify({
                    'error': f'Invalid action_status. Must be one of: {", ".join(sorted(VALID_AFFILIATE_ACTION_STATUS))}',
                }), 400

            raw_type = data.get('action_type')
            action_type = None
            if raw_type is not None and str(raw_type).strip():
                action_type = sanitize_string(str(raw_type), 80).lower()
                if action_type not in VALID_AFFILIATE_ACTION_TYPE:
                    return jsonify({
                        'error': f'Invalid action_type. Must be one of: {", ".join(sorted(VALID_AFFILIATE_ACTION_TYPE))}',
                    }), 400

            tr = sanitize_string(data.get('trigger_reason', ''), 80).lower()
            if tr and tr not in VALID_AFFILIATE_TRIGGER_REASON:
                tr = 'other'
            trigger_reason = tr or None

            notes = sanitize_string(data.get('notes', ''), 2000)
            updated_by = sanitize_string(data.get('updated_by', ''), 120) or 'dashboard'

            existing_row = db.get_affiliate_action(code)
            if 'actioned_at' in data:
                raw_aa = data.get('actioned_at')
                if raw_aa is None:
                    actioned_at = None
                elif isinstance(raw_aa, str) and not raw_aa.strip():
                    actioned_at = None
                else:
                    actioned_at = sanitize_string(str(raw_aa), 64) or None
            else:
                # Client omitted the field (older clients): keep prior timestamp on update.
                actioned_at = (existing_row or {}).get('actioned_at')

            trigger_run_id = sanitize_string(data.get('trigger_run_id', ''), 64) or None

            db.upsert_affiliate_action(
                code, status,
                action_type=action_type,
                trigger_reason=trigger_reason,
                notes=notes or None,
                updated_by=updated_by,
                actioned_at=actioned_at,
                trigger_run_id=trigger_run_id,
            )
            row = db.get_affiliate_action(code)
            return jsonify({'status': 'ok', 'affiliate_action': row})
        except Exception as e:
            logger.error(f"Error in POST /api/affiliate-actions: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/affiliate-actions/<path:code>', methods=['DELETE'])
    def api_delete_affiliate_action(code):
        try:
            code = sanitize_string(code, 100)
            if not code:
                return jsonify({'error': 'Invalid code'}), 400
            n = db.delete_affiliate_action(code)
            return jsonify({'status': 'ok', 'deleted': n})
        except Exception as e:
            logger.error(f"Error in DELETE /api/affiliate-actions: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/outcomes/bulk-import', methods=['POST'])
    def api_bulk_import_outcomes():
        """
        Bulk-mark accounts as confirmed_fraud from an uploaded CSV.

        Accepts multipart/form-data with:
          - file:    CSV file (must have a 'duid' column; email/risk_score used for matching fallback)
          - outcome: one of confirmed_fraud | false_positive | under_review  (default: confirmed_fraud)
          - notes:   optional free-text note applied to all records
        """
        try:
            import io
            import pandas as pd

            f = request.files.get('file')
            if not f:
                return jsonify({'error': 'No file uploaded'}), 400

            outcome = request.form.get('outcome', 'confirmed_fraud')
            if outcome not in VALID_OUTCOMES:
                return jsonify({'error': f'Invalid outcome. Must be one of: {", ".join(VALID_OUTCOMES)}'}), 400

            notes = sanitize_string(request.form.get('notes', ''), 1000)
            reviewed_by = 'bulk_import'

            try:
                df = pd.read_csv(io.StringIO(f.read().decode('utf-8', errors='replace')))
            except Exception as parse_err:
                return jsonify({'error': f'Could not parse CSV: {parse_err}'}), 400

            # Normalise column names to lowercase
            df.columns = [c.strip().lower() for c in df.columns]

            # Require at least a duid or email column
            if 'duid' not in df.columns and 'email' not in df.columns:
                return jsonify({'error': 'CSV must contain a "duid" or "email" column'}), 400

            imported = 0
            skipped  = 0
            errors   = []

            for _, row in df.iterrows():
                duid = str(row.get('duid', '') or '').strip()

                # pandas reads integer columns as float when NaNs are present
                # e.g. "10026479.0" → strip the decimal part
                if duid.endswith('.0') and duid[:-2].isdigit():
                    duid = duid[:-2]

                # Fallback: look up DUID by email if not provided
                if not duid or duid in ('nan', 'N/A', ''):
                    email = str(row.get('email', '') or '').strip().lower()
                    if not email or email == 'nan':
                        skipped += 1
                        errors.append(f"Row {_ + 2}: no DUID or email")
                        continue
                    try:
                        with db.get_connection() as conn:
                            row_db = conn.execute(
                                "SELECT duid FROM fraud_results WHERE LOWER(email) = ? LIMIT 1", [email]
                            ).fetchone()
                        duid = str(row_db[0]) if row_db else None
                        if not duid:
                            skipped += 1
                            errors.append(f"email not found in DB: {email}")
                            continue
                    except Exception as lookup_err:
                        duid = None
                        skipped += 1
                        errors.append(f"DB lookup error: {lookup_err}")
                        continue

                if not duid:
                    skipped += 1
                    continue

                duid = validate_duid(duid)
                if not duid:
                    skipped += 1
                    errors.append(f"Invalid DUID format: {str(row.get('duid', ''))[:30]}")
                    continue

                try:
                    success = db.record_fraud_outcome(duid, outcome, notes=notes, reviewed_by=reviewed_by)
                    if success:
                        imported += 1
                    else:
                        skipped += 1
                        errors.append(f"DUID not found in fraud_results: {duid}")
                except Exception as row_err:
                    errors.append(str(row_err))
                    skipped += 1

            logger.info(f"Bulk import: {imported} marked as {outcome}, {skipped} skipped")
            return jsonify({
                'status':   'ok',
                'imported': imported,
                'skipped':  skipped,
                'outcome':  outcome,
                'errors':   errors[:10],   # return at most 10 row-level errors
            })

        except Exception as e:
            logger.error(f"Error in /api/outcomes/bulk-import: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/pending-reviews')
    def api_pending_reviews():
        try:
            limit = max(1, min(request.args.get('limit', 200, type=int), 5000))
            min_risk = request.args.get('min_risk', 50, type=int) or 50
            total = db.count_pending_reviews(min_risk=min_risk)
            df = db.get_pending_reviews(min_risk=min_risk, limit=limit)
            cols = [c for c in ['duid', 'email', 'risk_score', 'flags', 'payout_amount',
                                'data_type', 'analyzed_at'] if c in df.columns]
            records = df[cols].fillna('').to_dict(orient='records')
            return jsonify({
                'records': records,
                'total': int(total),
                'limit': limit,
                'truncated': int(total) > len(records),
            })
        except Exception as e:
            logger.error(f"Error in /api/pending-reviews: {e}")
            return api_error('Failed to load pending reviews', 500, details=e)

    # ── BA FEATURE 1 + 2 + 3: Digest / Deltas / Backlog ──────────────────
    @app.route('/api/overview/digest')
    def api_overview_digest():
        """Today's digest: counts for today, deltas vs yesterday and last week, backlog age."""
        try:
            import pandas as pd
            with db.get_connection() as conn:
                q = """
                    SELECT
                        -- Today
                        SUM(CASE WHEN DATE(analyzed_at)=DATE('now','localtime') THEN 1 ELSE 0 END)                             AS today_analyzed,
                        SUM(CASE WHEN DATE(analyzed_at)=DATE('now','localtime') AND risk_score>=50 THEN 1 ELSE 0 END)          AS today_high,
                        SUM(CASE WHEN DATE(analyzed_at)=DATE('now','localtime') AND risk_score>=50 THEN payout_amount ELSE 0 END) AS today_revenue,
                        -- Yesterday
                        SUM(CASE WHEN DATE(analyzed_at)=DATE('now','localtime','-1 day') THEN 1 ELSE 0 END)                    AS yest_analyzed,
                        SUM(CASE WHEN DATE(analyzed_at)=DATE('now','localtime','-1 day') AND risk_score>=50 THEN 1 ELSE 0 END)  AS yest_high,
                        SUM(CASE WHEN DATE(analyzed_at)=DATE('now','localtime','-1 day') AND risk_score>=50 THEN payout_amount ELSE 0 END) AS yest_revenue,
                        -- Last 7 days vs prev 7 days (for week-over-week)
                        SUM(CASE WHEN analyzed_at >= DATE('now','-7 days') THEN 1 ELSE 0 END)                                  AS week_analyzed,
                        SUM(CASE WHEN analyzed_at >= DATE('now','-7 days') AND risk_score>=50 THEN 1 ELSE 0 END)               AS week_high,
                        SUM(CASE WHEN analyzed_at >= DATE('now','-14 days') AND analyzed_at < DATE('now','-7 days') THEN 1 ELSE 0 END) AS prev_week_analyzed,
                        SUM(CASE WHEN analyzed_at >= DATE('now','-14 days') AND analyzed_at < DATE('now','-7 days') AND risk_score>=50 THEN 1 ELSE 0 END) AS prev_week_high
                    FROM fraud_results
                """
                row = pd.read_sql_query(q, conn).iloc[0].to_dict()

                # Outcomes today
                oq = """
                    SELECT
                        SUM(CASE WHEN DATE(reviewed_at)=DATE('now','localtime') THEN 1 ELSE 0 END)                                     AS today_reviewed,
                        SUM(CASE WHEN DATE(reviewed_at)=DATE('now','localtime') AND outcome='confirmed_fraud' THEN 1 ELSE 0 END)        AS today_confirmed,
                        SUM(CASE WHEN DATE(reviewed_at)=DATE('now','localtime') AND outcome='false_positive' THEN 1 ELSE 0 END)         AS today_fp
                    FROM fraud_outcomes
                """
                orow = pd.read_sql_query(oq, conn).iloc[0].to_dict()

                # Backlog buckets: pending reviews by age
                bq = """
                    SELECT
                        COUNT(*) AS total_pending,
                        SUM(CASE WHEN (julianday('now') - julianday(fr.analyzed_at)) * 24 >= 72 THEN 1 ELSE 0 END) AS over_72h,
                        SUM(CASE WHEN (julianday('now') - julianday(fr.analyzed_at)) * 24 >= 48
                                  AND (julianday('now') - julianday(fr.analyzed_at)) * 24 < 72 THEN 1 ELSE 0 END) AS over_48h,
                        SUM(CASE WHEN (julianday('now') - julianday(fr.analyzed_at)) * 24 >= 24
                                  AND (julianday('now') - julianday(fr.analyzed_at)) * 24 < 48 THEN 1 ELSE 0 END) AS over_24h,
                        SUM(CASE WHEN (julianday('now') - julianday(fr.analyzed_at)) * 24 < 24 THEN 1 ELSE 0 END)  AS under_24h,
                        SUM(CASE WHEN fr.risk_score >= 50 THEN fr.payout_amount ELSE 0 END) AS pending_payout
                    FROM fraud_results fr
                    LEFT JOIN fraud_outcomes fo ON fr.duid = fo.duid
                    WHERE fo.duid IS NULL AND fr.risk_score >= 50
                """
                brow = pd.read_sql_query(bq, conn).iloc[0].to_dict()

            def pct_delta(new_val, old_val):
                new_val = float(new_val or 0)
                old_val = float(old_val or 0)
                if old_val == 0:
                    return None
                return round((new_val - old_val) / old_val * 100, 1)

            return jsonify({
                'today': {
                    'analyzed':  int(row.get('today_analyzed') or 0),
                    'high_risk': int(row.get('today_high') or 0),
                    'revenue':   float(row.get('today_revenue') or 0),
                    'reviewed':  int(orow.get('today_reviewed') or 0),
                    'confirmed': int(orow.get('today_confirmed') or 0),
                    'false_positives': int(orow.get('today_fp') or 0),
                },
                'deltas': {
                    'analyzed_vs_yesterday':  pct_delta(row.get('today_analyzed'), row.get('yest_analyzed')),
                    'high_vs_yesterday':      pct_delta(row.get('today_high'), row.get('yest_high')),
                    'revenue_vs_yesterday':   pct_delta(row.get('today_revenue'), row.get('yest_revenue')),
                    'analyzed_vs_last_week':  pct_delta(row.get('week_analyzed'), row.get('prev_week_analyzed')),
                    'high_vs_last_week':      pct_delta(row.get('week_high'), row.get('prev_week_high')),
                },
                'backlog': {
                    'total_pending': int(brow.get('total_pending') or 0),
                    'over_72h':      int(brow.get('over_72h') or 0),
                    'over_48h':      int(brow.get('over_48h') or 0),
                    'over_24h':      int(brow.get('over_24h') or 0),
                    'under_24h':     int(brow.get('under_24h') or 0),
                    'pending_payout':float(brow.get('pending_payout') or 0),
                }
            })
        except Exception as e:
            logger.error(f"Error in /api/overview/digest: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    # ── BA FEATURE 4: Rule-level performance table ────────────────────────
    @app.route('/api/rule-performance')
    def api_rule_performance():
        """Per-rule precision, false positive rate, and total flagged counts."""
        try:
            insights = AnalysisInsights(db)
            data = insights.compute_rule_stats(**_analysis_filters_from_request())
            return jsonify({
                'rules': data['rules'],
                'summary': data['summary'],
            })
        except Exception as e:
            logger.error(f"Error in /api/rule-performance: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    # ── ITEM 5: Detection Funnel ──────────────────────────────────────────
    @app.route('/api/detection-funnel')
    def api_detection_funnel():
        """Full detection pipeline funnel: analyzed → flagged → reviewed → outcome."""
        try:
            import pandas as pd
            date_from = request.args.get('date_from', '').strip() or None
            date_to = request.args.get('date_to', '').strip() or None

            def _bounds(prefix: str):
                """prefix '' for bare fraud_results column, 'fr.' for join query."""
                col = f'{prefix}analyzed_at'
                parts, p = [], []
                if date_from:
                    parts.append(f'DATE({col}) >= DATE(?)')
                    p.append(date_from)
                if date_to:
                    parts.append(f'DATE({col}) <= DATE(?)')
                    p.append(date_to)
                return (' AND ' + ' AND '.join(parts)) if parts else '', p

            where_totals, params_totals = _bounds('')
            where_fr, params_fr = _bounds('fr.')
            with db.get_connection() as conn:
                q = f"""
                    SELECT
                        COUNT(*) AS total_analyzed,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) AS high_risk,
                        SUM(CASE WHEN risk_score >= 25 AND risk_score < 50 THEN 1 ELSE 0 END) AS medium_risk,
                        SUM(CASE WHEN risk_score >= 50 THEN payout_amount ELSE 0 END) AS high_risk_payout
                    FROM fraud_results
                    WHERE 1=1{where_totals}
                """
                totals = pd.read_sql_query(q, conn, params=params_totals).iloc[0].to_dict()

                oq = f"""
                    SELECT
                        COUNT(*) AS total_reviewed,
                        SUM(CASE WHEN fo.outcome='confirmed_fraud' THEN 1 ELSE 0 END) AS confirmed,
                        SUM(CASE WHEN fo.outcome='false_positive' THEN 1 ELSE 0 END) AS false_positives,
                        SUM(CASE WHEN fo.outcome='under_review' THEN 1 ELSE 0 END) AS under_review
                    FROM fraud_outcomes fo
                    INNER JOIN fraud_results fr ON fo.duid = fr.duid
                    WHERE fr.risk_score >= 50{where_fr}
                """
                outcomes = pd.read_sql_query(oq, conn, params=params_fr).iloc[0].to_dict()

            total     = int(totals.get('total_analyzed') or 0)
            high      = int(totals.get('high_risk')     or 0)
            medium    = int(totals.get('medium_risk')   or 0)
            reviewed  = int(outcomes.get('total_reviewed')   or 0)
            confirmed = int(outcomes.get('confirmed')        or 0)
            fp        = int(outcomes.get('false_positives')  or 0)
            in_review = int(outcomes.get('under_review')     or 0)
            pending   = max(0, high - reviewed)

            def pct(num, den):
                return round(num / den * 100, 1) if den > 0 else 0

            return jsonify({
                'total_analyzed':  total,
                'medium_risk':     medium,
                'high_risk':       high,
                'high_risk_pct':   pct(high, total),
                'reviewed':        reviewed,
                'review_rate':     pct(reviewed, high),
                'confirmed':       confirmed,
                'false_positives': fp,
                'under_review':    in_review,
                'pending':         pending,
                'precision':       pct(confirmed, reviewed) if reviewed > 0 else None,
                'fp_rate':         pct(fp, reviewed) if reviewed > 0 else None,
                'high_risk_payout':float(totals.get('high_risk_payout') or 0),
                'reviewed_scope_note': (
                    'Reviewed counts are high-risk accounts (score ≥ 50) with a row in fraud_outcomes, '
                    'using the same analysis-date window as the rest of this funnel.'
                ),
                'filters': {
                    'date_from': date_from,
                    'date_to': date_to,
                },
            })
        except Exception as e:
            logger.error(f"Error in /api/detection-funnel: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/fraud-intelligence')
    def api_fraud_intelligence():
        """Trends, simple projections, affiliate trajectory, funnel with dollar context."""
        try:
            days = max(7, min(int(request.args.get('days', 90)), 365))
            lookback = max(7, min(int(request.args.get('lookback', 14)), 90))
            weeks = max(2, min(int(request.args.get('weeks', 4)), 12))
            analyzed_date_from = request.args.get('analyzed_date_from', '').strip() or None
            analyzed_date_to = request.args.get('analyzed_date_to', '').strip() or None
            trajectory_action_filter = (
                request.args.get('trajectory_action_filter', 'needs_action') or 'needs_action'
            ).strip().lower()

            sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
            from fraud_intelligence import FraudIntelligence, TRAJECTORY_ACTION_FILTERS

            if trajectory_action_filter not in TRAJECTORY_ACTION_FILTERS:
                trajectory_action_filter = 'needs_action'

            intel = FraudIntelligence(db)
            skip_affiliates = frozenset(
                config.get_affiliate_analysis_skip_codes_lower(include_house_in_analysis=False)
            )
            bundle = intel.get_dashboard_bundle(
                days=days,
                lookback=lookback,
                trajectory_weeks=weeks,
                trajectory_action_filter=trajectory_action_filter,
                funnel_analyzed_date_from=analyzed_date_from,
                funnel_analyzed_date_to=analyzed_date_to,
                exclude_affiliates_lower=skip_affiliates,
            )
            return jsonify(bundle)
        except Exception as e:
            logger.error(f"Error in /api/fraud-intelligence: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    # ── Enrichment ────────────────────────────────────────────────────────────

    @app.route('/api/enrich', methods=['POST'])
    def api_start_enrichment():
        """Start admin API enrichment pass in the background."""
        global _running_tasks
        if _running_tasks.get('enrich', {}).get('status') == 'running':
            return jsonify({'error': 'Enrichment already running'}), 409

        stale_hours = float((config.get('scheduler') or {}).get('stale_run_hours', 12) or 12)
        lock_holder = f"web-enrich-{os.getpid()}"
        if not db.try_acquire_named_lock('pipeline', lock_holder, stale_hours=stale_hours, meta={'source': 'manual_web_enrich'}):
            return jsonify({'error': 'Pipeline already running (scheduler or another job holds the lock)'}), 409

        body = request.json or {}
        last_run_only = bool(body.get('last_run_only', False))
        force = bool(body.get('force', False))

        since_analyzed_at = None
        if last_run_only:
            since_analyzed_at = db.get_last_run_analyzed_at()

        # If force, reset enrichment flags for the targeted accounts first
        reset_count = 0
        if force and last_run_only:
            reset_count = db.reset_enrichment_for_last_run()
            logger.info(f"Force re-enrich: reset {reset_count} accounts from last run")
        elif force and not last_run_only:
            # Full force not allowed — too destructive on large DBs
            db.release_named_lock('pipeline', lock_holder)
            return jsonify({'error': 'Force re-enrich is only supported with "Last run only"'}), 400

        # Count how many will actually be processed
        duids_preview = db.get_unenriched_duids(limit=100_000, since_analyzed_at=since_analyzed_at)
        actual_count = len(duids_preview)
        limit = actual_count if last_run_only else min(int(body.get('limit', 500)), 2000)

        enrich_client = _admin_client_for_request()
        if not enrich_client:
            db.release_named_lock('pipeline', lock_holder)
            return jsonify({
                'error': 'Admin2 not signed in. Use the login prompt or Settings → Admin platform API.',
            }), 401

        _running_tasks['enrich'] = {
            'status': 'running',
            'started': datetime.now().isoformat(),
            'total': actual_count,
            'done': 0,
            'enriched': 0,
            'errors': 0,
            'current_duid': None,
            'last_run_only': last_run_only,
        }

        def run_enrich():
            global _running_tasks
            try:
                sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
                from admin_enricher import AdminEnricher
                enricher = AdminEnricher(db=db, client=enrich_client, config=app.config_obj)

                def on_progress(p):
                    _running_tasks['enrich'].update(p)

                summary = enricher.run(limit=limit, progress_cb=on_progress, since_analyzed_at=since_analyzed_at)
                _running_tasks['enrich'] = {
                    'status': 'completed',
                    'completed': datetime.now().isoformat(),
                    **summary,
                }
            except Exception as exc:
                logger.error(f"Enrichment task error: {exc}", exc_info=True)
                _running_tasks['enrich'] = {
                    'status': 'error',
                    'error': str(exc),
                }
            finally:
                try:
                    db.release_named_lock('pipeline', lock_holder)
                except Exception as lock_err:
                    logger.warning('Failed to release pipeline lock: %s', lock_err)

        threading.Thread(target=run_enrich, daemon=True).start()
        return jsonify({'status': 'started', 'total': actual_count, 'last_run_only': last_run_only})

    @app.route('/api/enrich/status')
    def api_enrich_status():
        """Poll enrichment task status."""
        status = dict(_running_tasks.get('enrich', {'status': 'idle'}))
        _lb = int((app.config_obj.config.get('scheduler') or {}).get('enrich_lookback_days', 90) or 90)
        status['backlog'] = db.get_enrichment_backlog_count(lookback_days=_lb)
        return jsonify(status)

    # ── ITEM 7: Geographic Breakdown ──────────────────────────────────────
    @app.route('/api/geo-breakdown')
    def api_geo_breakdown():
        """Fraud breakdown by country (geo_country field)."""
        try:
            import pandas as pd
            with db.get_connection() as conn:
                q = """
                    SELECT
                        COALESCE(NULLIF(TRIM(geo_country),''), 'Unknown') AS country,
                        COUNT(*) AS total,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) AS high_risk,
                        SUM(CASE WHEN risk_score >= 25 AND risk_score < 50 THEN 1 ELSE 0 END) AS medium_risk,
                        ROUND(AVG(risk_score), 1) AS avg_risk,
                        SUM(CASE WHEN risk_score >= 50 THEN payout_amount ELSE 0 END) AS payout_at_risk,
                        ROUND(SUM(CASE WHEN risk_score >= 50 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) AS fraud_rate
                    FROM fraud_results
                    GROUP BY country
                    ORDER BY total DESC
                    LIMIT 30
                """
                df = pd.read_sql_query(q, conn)

            if df.empty:
                return jsonify({'countries': [], 'has_data': False})

            # Also compute share of total
            grand_total = df['total'].sum()
            df['share_pct'] = (df['total'] / grand_total * 100).round(1)

            # 7-day spike vs prior 7 days per country
            with db.get_connection() as conn:
                spike_q = """
                    SELECT
                        COALESCE(NULLIF(TRIM(geo_country),''), 'Unknown') AS country,
                        SUM(CASE WHEN analyzed_at >= DATE('now','-7 days') AND risk_score>=50 THEN 1 ELSE 0 END) AS week_high,
                        SUM(CASE WHEN analyzed_at >= DATE('now','-14 days') AND analyzed_at < DATE('now','-7 days') AND risk_score>=50 THEN 1 ELSE 0 END) AS prev_week_high
                    FROM fraud_results
                    GROUP BY country
                """
                spike_df = pd.read_sql_query(spike_q, conn)

            spike_map = {}
            for _, r in spike_df.iterrows():
                prev = float(r.get('prev_week_high') or 0)
                curr = float(r.get('week_high') or 0)
                spike_map[r['country']] = round((curr - prev) / prev * 100, 1) if prev > 0 else None

            records = df.fillna(0).to_dict(orient='records')
            for r in records:
                r['wow_delta'] = spike_map.get(r['country'])

            return jsonify({'countries': records, 'has_data': True, 'grand_total': int(grand_total)})
        except Exception as e:
            logger.error(f"Error in /api/geo-breakdown: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    # ── ITEM 8: Affiliate sparklines (7-day high-risk per affiliate) ───────
    @app.route('/api/affiliate-sparklines')
    def api_affiliate_sparklines():
        """Returns 7-day daily high-risk count for each affiliate (for sparklines)."""
        try:
            import pandas as pd
            with db.get_connection() as conn:
                q = """
                    SELECT
                        webmaster_code,
                        DATE(analyzed_at) AS day,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) AS high_risk
                    FROM fraud_results
                    WHERE analyzed_at >= DATE('now', '-7 days')
                      AND webmaster_code IS NOT NULL AND webmaster_code != ''
                    GROUP BY webmaster_code, day
                    ORDER BY webmaster_code, day
                """
                df = pd.read_sql_query(q, conn)

            if df.empty:
                return jsonify({'sparklines': {}})

            # Build complete 7-day date range
            import datetime
            today = datetime.date.today()
            dates = [(today - datetime.timedelta(days=6-i)).isoformat() for i in range(7)]

            sparklines = {}
            for code, group in df.groupby('webmaster_code'):
                day_map = dict(zip(group['day'], group['high_risk']))
                sparklines[code] = [int(day_map.get(d, 0)) for d in dates]

            return jsonify({'sparklines': sparklines, 'dates': dates})
        except Exception as e:
            logger.error(f"Error in /api/affiliate-sparklines: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    # ── ITEM 9: Week-over-Week Trends (current + prior period) ────────────
    @app.route('/api/temporal-wow')
    def api_temporal_wow():
        """Daily high-risk counts for current period AND prior period (WoW comparison)."""
        try:
            import pandas as pd
            days = request.args.get('days', 14, type=int)

            with db.get_connection() as conn:
                q = """
                    SELECT
                        DATE(analyzed_at) AS day,
                        COUNT(*) AS total,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) AS high_risk,
                        ROUND(AVG(risk_score), 1) AS avg_risk
                    FROM fraud_results
                    WHERE analyzed_at >= DATE('now', :cutoff)
                    GROUP BY day
                    ORDER BY day
                """
                cutoff = f'-{days * 2} days'
                df = pd.read_sql_query(q, conn, params={'cutoff': cutoff})

            if df.empty:
                return jsonify({'current': [], 'prior': [], 'dates': []})

            import datetime
            today = datetime.date.today()
            current_start = today - datetime.timedelta(days=days - 1)
            prior_start   = today - datetime.timedelta(days=days * 2 - 1)
            prior_end     = current_start - datetime.timedelta(days=1)

            df['day'] = pd.to_datetime(df['day']).dt.date

            current_df = df[df['day'] >= current_start].copy()
            prior_df   = df[(df['day'] >= prior_start) & (df['day'] <= prior_end)].copy()

            # Normalise prior dates so both series align on x-axis (shift prior forward by `days`)
            prior_df['aligned_day'] = prior_df['day'].apply(
                lambda d: (d + datetime.timedelta(days=days)).isoformat()
            )
            current_df['aligned_day'] = current_df['day'].apply(lambda d: d.isoformat())

            def to_series(frame, day_col='aligned_day'):
                return [
                    {'date': r[day_col], 'total': int(r['total']),
                     'high_risk': int(r['high_risk']), 'avg_risk': float(r['avg_risk'])}
                    for _, r in frame.iterrows()
                ]

            return jsonify({
                'current': to_series(current_df),
                'prior':   to_series(prior_df),
                'days':    days,
            })
        except Exception as e:
            logger.error(f"Error in /api/temporal-wow: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    # ── BA FEATURE 5: Campaign fraud rate ranking (enhanced) ──────────────
    @app.route('/api/campaign-ranking')
    def api_campaign_ranking():
        """Campaigns ranked by fraud rate with WoW delta and payout at risk."""
        try:
            import pandas as pd
            with db.get_connection() as conn:
                q = """
                    SELECT
                        campaign,
                        COUNT(*) AS total,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) AS high_risk,
                        ROUND(SUM(CASE WHEN risk_score >= 50 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) AS fraud_rate,
                        SUM(CASE WHEN risk_score >= 50 THEN payout_amount ELSE 0 END) AS payout_at_risk,
                        SUM(payout_amount) AS total_payout,
                        ROUND(AVG(risk_score), 1) AS avg_risk,
                        COUNT(DISTINCT webmaster_code) AS affiliate_count,
                        -- This week vs last week
                        SUM(CASE WHEN analyzed_at >= DATE('now','-7 days') AND risk_score>=50 THEN 1 ELSE 0 END) AS week_high,
                        SUM(CASE WHEN analyzed_at >= DATE('now','-14 days') AND analyzed_at < DATE('now','-7 days') AND risk_score>=50 THEN 1 ELSE 0 END) AS prev_week_high
                    FROM fraud_results
                    WHERE campaign IS NOT NULL AND campaign != ''
                    GROUP BY campaign
                    HAVING total >= 5
                    ORDER BY fraud_rate DESC, payout_at_risk DESC
                    LIMIT 50
                """
                df = pd.read_sql_query(q, conn)

            if df.empty:
                return jsonify({'campaigns': []})

            records = df.fillna(0).to_dict(orient='records')

            # Calculate WoW delta for each campaign
            for r in records:
                prev = float(r.get('prev_week_high') or 0)
                curr = float(r.get('week_high') or 0)
                r['wow_delta'] = round((curr - prev) / prev * 100, 1) if prev > 0 else None

            return jsonify({'campaigns': records})

        except Exception as e:
            logger.error(f"Error in /api/campaign-ranking: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/effectiveness')
    def api_effectiveness():
        try:
            db.calculate_and_store_metrics()
            metrics = db.get_effectiveness_metrics()
            return jsonify(metrics)
        except Exception as e:
            logger.error(f"Error in /api/effectiveness: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/fp-by-flag')
    def api_fp_by_flag():
        """Get false positive breakdown by flag (unified rule stats)."""
        try:
            insights = AnalysisInsights(db)
            data = insights.compute_fp_analysis(**_analysis_filters_from_request())
            summary = data.get('summary') or {}
            return jsonify({
                'flags': [
                    {
                        'flag': f['flag'],
                        'total': f['total'],
                        'fraud_count': f['fraud_count'],
                        'fp_count': f['fp_count'],
                        'fp_rate': f.get('fp_rate'),
                        'precision': f['precision'],
                        'confidence': f.get('confidence'),
                    }
                    for f in data.get('flag_analysis', [])
                ],
                'summary': {
                    'total_reviewed': summary.get('total_reviewed', 0),
                    'fp_count': summary.get('false_positive', 0),
                    'fraud_count': summary.get('confirmed_fraud', 0),
                    'overall_fp_rate': summary.get('overall_fp_rate'),
                    'overall_precision': summary.get('overall_precision'),
                },
            })
        except Exception as e:
            logger.error(f"Error in /api/fp-by-flag: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/metrics-history')
    def api_metrics_history():
        try:
            days = request.args.get('days', 30, type=int)
            df = db.get_metrics_history(days=days)
            return jsonify(df.fillna(0).to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/metrics-history: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/cross-affiliate')
    def api_cross_affiliate():
        try:
            patterns = db.get_cross_affiliate_patterns()
            return jsonify(patterns)
        except Exception as e:
            logger.error(f"Error in /api/cross-affiliate: {e}")
            return jsonify({'error': str(e)}), 500

    # ── RECENT SPIKES (shared cross-tab cache) ────────────────────────────
    @app.route('/api/recent-spikes')
    def api_recent_spikes():
        """
        Lightweight endpoint consumed by every tab on load.
        Returns which affiliates and campaigns had a per-entity volume spike
        (count > 2× their 14-day avg, or z > 2) in the last 7 days.
        Also returns the most recent global spike date for the alert banner.
        """
        try:
            import pandas as pd
            import numpy as np

            with db.get_connection() as conn:
                # Per-affiliate daily counts, last 21 days
                aff_q = """
                    SELECT
                        webmaster_code,
                        DATE(analyzed_at)                                        AS day,
                        COUNT(*)                                                 AS total,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END)        AS high_risk
                    FROM fraud_results
                    WHERE analyzed_at >= DATE('now', '-21 days')
                      AND webmaster_code IS NOT NULL AND webmaster_code != ''
                    GROUP BY webmaster_code, day
                    ORDER BY webmaster_code, day
                """
                aff_df = pd.read_sql_query(aff_q, conn)

                # Per-campaign daily counts, last 21 days
                camp_q = """
                    SELECT
                        campaign,
                        DATE(analyzed_at)                                        AS day,
                        COUNT(*)                                                 AS total,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END)        AS high_risk
                    FROM fraud_results
                    WHERE analyzed_at >= DATE('now', '-21 days')
                      AND campaign IS NOT NULL AND campaign != ''
                    GROUP BY campaign, day
                    ORDER BY campaign, day
                """
                camp_df = pd.read_sql_query(camp_q, conn)

            cutoff_7 = (pd.Timestamp.now() - pd.Timedelta(days=7)).date().isoformat()

            def detect_entity_spikes(df, key_col):
                spikes = []
                for key, group in df.groupby(key_col):
                    group = group.sort_values('day').reset_index(drop=True)
                    if len(group) < 4:
                        continue
                    # Baseline = days older than 7 days ago
                    baseline = group[group['day'] < cutoff_7]['total']
                    if len(baseline) < 3:
                        continue
                    b_mean = float(baseline.mean())
                    b_std  = float(baseline.std()) if len(baseline) > 1 else 0

                    # Check each day in last 7 days
                    recent = group[group['day'] >= cutoff_7]
                    for _, row in recent.iterrows():
                        count = float(row['total'])
                        z = (count - b_mean) / b_std if b_std > 0 else 0
                        if z >= 2.0 or (b_mean > 0 and count >= b_mean * 2):
                            spikes.append({
                                key_col:       key,
                                'spike_date':  row['day'],
                                'count':       int(row['total']),
                                'high_risk':   int(row['high_risk']),
                                'baseline_avg':round(b_mean, 1),
                                'z_score':     round(z, 2),
                                'pct_above':   round((count - b_mean) / b_mean * 100, 1) if b_mean > 0 else None,
                            })
                # Keep only the most recent spike per entity
                seen = {}
                for s in sorted(spikes, key=lambda x: x['spike_date'], reverse=True):
                    k = s[key_col]
                    if k not in seen:
                        seen[k] = s
                return list(seen.values())

            aff_spikes  = detect_entity_spikes(aff_df, 'webmaster_code') if not aff_df.empty else []
            camp_spikes = detect_entity_spikes(camp_df, 'campaign')      if not camp_df.empty else []

            # Build lookup maps for fast frontend use
            aff_map  = {s['webmaster_code']: s for s in aff_spikes}
            camp_map = {s['campaign']:        s for s in camp_spikes}

            return jsonify({
                'affiliates':  aff_spikes,
                'campaigns':   camp_spikes,
                'aff_map':     aff_map,
                'camp_map':    camp_map,
                'has_spikes':  len(aff_spikes) > 0 or len(camp_spikes) > 0,
            })

        except Exception as e:
            logger.error(f"Error in /api/recent-spikes: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/affiliate-spikes')
    def api_affiliate_spikes():
        """
        Per-affiliate volume spikes over a lookback window (hybrid MCP + local).

        Scoring uses PS7/MCP source counts by event date when configured,
        otherwise local free/paid by trans_datetime — same model as Volume Anomalies.
        Current day and local-only partial-fetch days are excluded from the list.
        """
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
            from affiliate_spikes import detect_affiliate_spikes, paginate_spikes

            lookback = max(7, min(request.args.get('days', 30, type=int), 90))
            page = max(request.args.get('page', 1, type=int), 1)
            per_page = min(max(request.args.get('per_page', 20, type=int), 1), 100)
            min_z = float(request.args.get('min_z', 2.0))
            min_count = max(request.args.get('min_count', 5, type=int), 1)
            level_filter = (request.args.get('level') or 'all').strip().lower()
            sort_key = (request.args.get('sort') or 'z_score').strip().lower()

            result = detect_affiliate_spikes(
                db,
                app.config_obj,
                lookback_days=lookback,
                min_z=min_z,
                min_count=min_count,
                level_filter=level_filter,
                sort_key=sort_key,
            )
            result = paginate_spikes(result, page=page, per_page=per_page)
            return jsonify(sanitize_for_json(result))

        except Exception as e:
            logger.error(f"Error in /api/affiliate-spikes: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    # ── SPIKE DETECTION ──────────────────────────────────────────────────
    @app.route('/api/spike-analysis')
    def api_spike_analysis():
        """
        Detect statistically anomalous signup days (z-score > 2).
        Returns full daily series with z-scores + a list of spike days.
        Lookback: 60 days. Baseline: rolling 14-day window.
        """
        try:
            import pandas as pd
            import numpy as np

            lookback = request.args.get('days', 60, type=int)

            with db.get_connection() as conn:
                q = """
                    SELECT
                        DATE(analyzed_at)                                                      AS day,
                        COUNT(*)                                                               AS total,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END)                     AS high_risk,
                        SUM(CASE WHEN risk_score >= 25 AND risk_score < 50 THEN 1 ELSE 0 END) AS medium_risk,
                        ROUND(AVG(risk_score), 1)                                              AS avg_risk,
                        SUM(CASE WHEN risk_score >= 50 THEN payout_amount ELSE 0 END)         AS payout_at_risk,
                        COUNT(DISTINCT webmaster_code)                                         AS affiliate_count,
                        COUNT(DISTINCT campaign)                                               AS campaign_count
                    FROM fraud_results
                    WHERE analyzed_at >= DATE('now', :cutoff)
                    GROUP BY day
                    ORDER BY day
                """
                df = pd.read_sql_query(q, conn, params={'cutoff': f'-{lookback} days'})

            if df.empty:
                return jsonify({'daily': [], 'spikes': [], 'baseline': {}})

            df['day'] = df['day'].astype(str)

            # Rolling baseline: 14-day rolling mean & std (min 7 days of data)
            df['rolling_mean'] = (
                df['total'].rolling(window=14, min_periods=7, center=False).mean().shift(1)
            )
            df['rolling_std'] = (
                df['total'].rolling(window=14, min_periods=7, center=False).std().shift(1)
            )

            # Z-score: how many standard deviations above rolling baseline
            df['z_score'] = np.where(
                (df['rolling_std'] > 0) & df['rolling_mean'].notna(),
                (df['total'] - df['rolling_mean']) / df['rolling_std'],
                np.nan
            )
            df['z_score'] = df['z_score'].round(2)

            # High-risk z-score separately
            df['hr_rolling_mean'] = (
                df['high_risk'].rolling(window=14, min_periods=7, center=False).mean().shift(1)
            )
            df['hr_rolling_std'] = (
                df['high_risk'].rolling(window=14, min_periods=7, center=False).std().shift(1)
            )
            df['hr_z_score'] = np.where(
                (df['hr_rolling_std'] > 0) & df['hr_rolling_mean'].notna(),
                (df['high_risk'] - df['hr_rolling_mean']) / df['hr_rolling_std'],
                np.nan
            )
            df['hr_z_score'] = df['hr_z_score'].round(2)

            # Overall baseline stats
            overall_mean = float(df['total'].mean())
            overall_std  = float(df['total'].std())

            # Spike classification
            def classify(z):
                if pd.isna(z): return 'normal'
                if z >= 3.0:   return 'severe'
                if z >= 2.0:   return 'spike'
                if z >= 1.5:   return 'elevated'
                return 'normal'

            df['spike_level'] = df['z_score'].apply(classify)

            # Build spike list (z >= 2.0, most recent first)
            spike_df = df[df['z_score'] >= 2.0].sort_values('z_score', ascending=False)
            spikes = []
            for _, row in spike_df.iterrows():
                pct_above = (
                    round((row['total'] - row['rolling_mean']) / row['rolling_mean'] * 100, 1)
                    if (row['rolling_mean'] and row['rolling_mean'] > 0) else None
                )
                spikes.append({
                    'date':           row['day'],
                    'total':          int(row['total']),
                    'high_risk':      int(row['high_risk']),
                    'z_score':        float(row['z_score']),
                    'hr_z_score':     float(row['hr_z_score']) if not pd.isna(row['hr_z_score']) else None,
                    'rolling_mean':   round(float(row['rolling_mean']), 1) if not pd.isna(row['rolling_mean']) else None,
                    'pct_above_avg':  pct_above,
                    'payout_at_risk': float(row['payout_at_risk']),
                    'spike_level':    row['spike_level'],
                })

            # Daily series for chart
            daily_records = []
            for _, row in df.iterrows():
                daily_records.append({
                    'date':          row['day'],
                    'total':         int(row['total']),
                    'high_risk':     int(row['high_risk']),
                    'avg_risk':      float(row['avg_risk']) if not pd.isna(row['avg_risk']) else 0,
                    'payout_at_risk':float(row['payout_at_risk']),
                    'z_score':       float(row['z_score'])        if not pd.isna(row['z_score'])    else None,
                    'hr_z_score':    float(row['hr_z_score'])     if not pd.isna(row['hr_z_score']) else None,
                    'rolling_mean':  round(float(row['rolling_mean']), 1) if not pd.isna(row['rolling_mean']) else None,
                    'spike_level':   row['spike_level'],
                })

            return jsonify(sanitize_for_json({
                'daily':    daily_records,
                'spikes':   spikes,
                'baseline': {
                    'mean': round(overall_mean, 1),
                    'std':  round(overall_std,  1),
                    'days': len(df),
                }
            }))

        except Exception as e:
            logger.error(f"Error in /api/spike-analysis: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    # ── VOLUME ANOMALIES (registrations + sales, trans_datetime) ─────────
    @app.route('/api/volume-anomalies')
    def api_volume_anomalies():
        """
        Detect registration and sales surges/dips using trans_datetime (event date).
        Hybrid: PS7/MCP source counts for z-scoring when configured; partial local
        fetch days excluded from anomalies unless source counts were used.
        Current calendar day excluded by default (incomplete vs full-day baseline).
        """
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
            from volume_anomalies import (
                analyze_volume_anomalies,
                apply_hybrid_metadata,
                build_hybrid_volume_series,
            )

            lookback = max(14, min(request.args.get('days', 60, type=int), 365))

            reg_df, sales_df, day_meta, hybrid_info = build_hybrid_volume_series(
                db, app.config_obj, lookback_days=lookback,
            )
            result = analyze_volume_anomalies(reg_df, sales_df)
            result = apply_hybrid_metadata(result, day_meta)
            result['lookback_days'] = lookback
            result['hybrid'] = hybrid_info
            return jsonify(sanitize_for_json(result))

        except Exception as e:
            logger.error(f"Error in /api/volume-anomalies: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/volume-anomalies/drill/<date>')
    def api_volume_anomalies_drill(date):
        """Affiliate breakdown for registration/sales volume on an anomaly date."""
        try:
            import pandas as pd
            import re as re_module

            if not re_module.match(r'^\d{4}-\d{2}-\d{2}$', date):
                return jsonify({'error': 'Invalid date format'}), 400

            with db.get_connection() as conn:
                reg_day_q = """
                    SELECT webmaster_code, COUNT(*) AS count
                    FROM free
                    WHERE DATE(trans_datetime) = ?
                      AND webmaster_code IS NOT NULL AND TRIM(webmaster_code) != ''
                    GROUP BY webmaster_code
                    ORDER BY count DESC
                """
                reg_base_q = """
                    SELECT webmaster_code, DATE(trans_datetime) AS day, COUNT(*) AS daily_count
                    FROM free
                    WHERE trans_datetime >= DATE(?, '-14 days')
                      AND DATE(trans_datetime) != ?
                      AND webmaster_code IS NOT NULL AND TRIM(webmaster_code) != ''
                    GROUP BY webmaster_code, day
                """
                sales_day_q = """
                    SELECT webmaster_code, COUNT(*) AS count
                    FROM paid
                    WHERE DATE(trans_datetime) = ?
                      AND webmaster_code IS NOT NULL AND TRIM(webmaster_code) != ''
                    GROUP BY webmaster_code
                    ORDER BY count DESC
                """
                sales_base_q = """
                    SELECT webmaster_code, DATE(trans_datetime) AS day, COUNT(*) AS daily_count
                    FROM paid
                    WHERE trans_datetime >= DATE(?, '-14 days')
                      AND DATE(trans_datetime) != ?
                      AND webmaster_code IS NOT NULL AND TRIM(webmaster_code) != ''
                    GROUP BY webmaster_code, day
                """
                reg_day = pd.read_sql_query(reg_day_q, conn, params=[date])
                reg_base = pd.read_sql_query(reg_base_q, conn, params=[date, date])
                sales_day = pd.read_sql_query(sales_day_q, conn, params=[date])
                sales_base = pd.read_sql_query(sales_base_q, conn, params=[date, date])

                totals_q = """
                    SELECT
                        (SELECT COUNT(*) FROM free WHERE DATE(trans_datetime) = ?) AS registrations,
                        (SELECT COUNT(*) FROM paid WHERE DATE(trans_datetime) = ?) AS sales
                """
                totals = pd.read_sql_query(totals_q, conn, params=[date, date]).iloc[0].to_dict()

            rec_by_day = db.get_reconciliation_results(date, date)
            rec = rec_by_day.get(date) or {}
            local_reg = int(totals.get('registrations') or 0)
            local_sales = int(totals.get('sales') or 0)
            match_pct = rec.get('local_match_pct')
            rec_status = rec.get('reconciliation_status')
            partial_fetch = rec_status == 'partial' or (
                match_pct is not None and float(match_pct) < 99.5
            )

            def _merge_baseline(day_df, base_df, key='webmaster_code'):
                if day_df.empty:
                    return []
                if base_df.empty:
                    day_df = day_df.copy()
                    day_df['avg_daily'] = None
                else:
                    aff_base = base_df.groupby(key).agg(avg_daily=('daily_count', 'mean')).reset_index()
                    day_df = day_df.merge(aff_base, on=key, how='left')

                total = int(day_df['count'].sum()) or 1
                rows = []
                for _, r in day_df.sort_values('count', ascending=False).head(25).iterrows():
                    avg = r.get('avg_daily')
                    vs = None
                    if avg is not None and not pd.isna(avg) and avg > 0:
                        vs = round((r['count'] - avg) / avg * 100, 1)
                    rows.append({
                        'webmaster_code': r[key] or 'Unknown',
                        'count': int(r['count']),
                        'share_pct': round(r['count'] / total * 100, 1),
                        'avg_daily': round(float(avg), 1) if avg is not None and not pd.isna(avg) else None,
                        'vs_baseline_pct': vs,
                    })
                return rows

            return jsonify({
                'date': date,
                'registrations': local_reg,
                'sales': local_sales,
                'source_registrations': rec.get('source_expected_free'),
                'source_sales': rec.get('source_expected_paid'),
                'local_match_pct': match_pct,
                'partial_fetch': partial_fetch,
                'reconciliation_status': rec_status,
                'conversion_rate': round(
                    local_sales / local_reg * 100, 2
                ) if local_reg > 0 else None,
                'registration_affiliates': _merge_baseline(reg_day, reg_base),
                'sales_affiliates': _merge_baseline(sales_day, sales_base),
            })

        except Exception as e:
            logger.error(f"Error in /api/volume-anomalies/drill/{date}: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/spike-drill/<date>')
    def api_spike_drill(date):
        """
        For a given date (YYYY-MM-DD), return:
        - Affiliate breakdown (who contributed most vs their daily avg)
        - Campaign breakdown
        - Top flags
        - Sample accounts
        - Comparison to prior 14-day baseline for each affiliate
        """
        try:
            import pandas as pd
            import re as re_module

            # Validate date format
            if not re_module.match(r'^\d{4}-\d{2}-\d{2}$', date):
                return jsonify({'error': 'Invalid date format'}), 400

            with db.get_connection() as conn:
                # Accounts on spike day
                day_q = """
                    SELECT duid, email, risk_score, payout_amount, flags,
                           webmaster_code, campaign, data_type, analyzed_at
                    FROM fraud_results
                    WHERE DATE(analyzed_at) = ?
                    ORDER BY risk_score DESC
                """
                day_df = pd.read_sql_query(day_q, conn, params=[date])

                # 14-day baseline (exclude spike day)
                base_q = """
                    SELECT
                        DATE(analyzed_at)                                             AS day,
                        webmaster_code,
                        COUNT(*)                                                      AS daily_count,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END)            AS daily_high
                    FROM fraud_results
                    WHERE analyzed_at >= DATE(?, '-14 days')
                      AND DATE(analyzed_at) != ?
                    GROUP BY day, webmaster_code
                """
                base_df = pd.read_sql_query(base_q, conn, params=[date, date])

            if day_df.empty:
                return jsonify({'date': date, 'total': 0, 'affiliates': [], 'campaigns': [], 'flags': [], 'sample': []})

            total_on_day   = len(day_df)
            high_risk_count = int((day_df['risk_score'] >= 50).sum())

            # Affiliate breakdown
            aff_day = day_df.groupby('webmaster_code').agg(
                count=('duid', 'count'),
                high_risk=('risk_score', lambda x: (x >= 50).sum()),
                avg_risk=('risk_score', 'mean'),
                payout=('payout_amount', 'sum')
            ).reset_index()
            aff_day['share_pct'] = (aff_day['count'] / total_on_day * 100).round(1)

            # Compute each affiliate's baseline daily average
            if not base_df.empty:
                aff_base = base_df.groupby('webmaster_code').agg(
                    avg_daily=('daily_count', 'mean'),
                    avg_daily_high=('daily_high', 'mean')
                ).reset_index()
                aff_day = aff_day.merge(aff_base, on='webmaster_code', how='left')
            else:
                aff_day['avg_daily']      = None
                aff_day['avg_daily_high'] = None

            def delta_pct(curr, base):
                if base is None or base == 0 or pd.isna(base):
                    return None
                return round((curr - base) / base * 100, 1)

            affiliates = []
            for _, r in aff_day.sort_values('count', ascending=False).iterrows():
                affiliates.append({
                    'webmaster_code': r['webmaster_code'] or 'Unknown',
                    'count':          int(r['count']),
                    'high_risk':      int(r['high_risk']),
                    'avg_risk':       round(float(r['avg_risk']), 1),
                    'payout':         float(r['payout']),
                    'share_pct':      float(r['share_pct']),
                    'avg_daily':      round(float(r['avg_daily']), 1) if r['avg_daily'] is not None and not pd.isna(r['avg_daily']) else None,
                    'vs_baseline':    delta_pct(r['count'], r.get('avg_daily')),
                })

            # Campaign breakdown
            camp_day = day_df.groupby('campaign').agg(
                count=('duid', 'count'),
                high_risk=('risk_score', lambda x: (x >= 50).sum()),
                avg_risk=('risk_score', 'mean'),
            ).reset_index()
            camp_day['share_pct'] = (camp_day['count'] / total_on_day * 100).round(1)
            campaigns = camp_day.sort_values('count', ascending=False).head(10).fillna('').to_dict(orient='records')
            for c in campaigns:
                c['count']     = int(c['count'])
                c['high_risk'] = int(c['high_risk'])
                c['avg_risk']  = round(float(c['avg_risk']), 1)
                c['share_pct'] = float(c['share_pct'])

            flags_list = count_catalog_flags(day_df['flags'], total=total_on_day)[:10]

            # Sample accounts (top 20 by risk)
            sample_cols = [c for c in ['duid', 'email', 'risk_score', 'flags', 'payout_amount',
                                        'webmaster_code', 'campaign', 'data_type'] if c in day_df.columns]
            sample = day_df[sample_cols].head(20).fillna('').to_dict(orient='records')

            top_aff = affiliates[0] if affiliates else None
            top_camp = campaigns[0] if campaigns else None
            top_flag = flags_list[0] if flags_list else None
            insight_parts = []
            if top_aff and top_aff.get('share_pct', 0) >= 50:
                insight_parts.append(
                    f"affiliate {top_aff['webmaster_code']} ({top_aff['count']} accounts, "
                    f"{top_aff['share_pct']}% of spike)"
                )
            if top_camp and top_camp.get('share_pct', 0) >= 50:
                insight_parts.append(
                    f"campaign {top_camp.get('campaign') or 'Unknown'} ({top_camp['count']} accounts)"
                )
            if top_flag:
                insight_parts.append(
                    f"top signal {top_flag['flag']} ({top_flag['count']} accounts, {top_flag['pct']}%)"
                )
            insight_summary = (
                'Spike driven mainly by ' + ', '.join(insight_parts) + '.'
                if insight_parts
                else f'{total_on_day} signups with {high_risk_count} high-risk accounts.'
            )

            return jsonify({
                'date':        date,
                'total':       total_on_day,
                'high_risk':   high_risk_count,
                'affiliates':  affiliates,
                'campaigns':   campaigns,
                'flags':       flags_list,
                'sample':      sample,
                'insight': {
                    'summary': insight_summary,
                    'top_affiliate': top_aff,
                    'top_campaign': top_camp,
                    'top_flag': top_flag,
                },
            })

        except Exception as e:
            logger.error(f"Error in /api/spike-drill/{date}: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/spike-drill/<date>/affiliate/<path:code>')
    def api_spike_drill_affiliate(date, code):
        """
        Accounts for a specific affiliate on a specific spike date (event date),
        plus that affiliate's 14-day baseline for comparison.

        Uses trans_datetime (same event-date basis as hybrid affiliate spikes).
        """
        try:
            import pandas as pd
            import re as re_module

            if not re_module.match(r'^\d{4}-\d{2}-\d{2}$', date):
                return jsonify({'error': 'Invalid date format'}), 400

            code = sanitize_string(code, 200)
            page = max(request.args.get('page', 1, type=int), 1)
            per_page = min(max(request.args.get('per_page', 25, type=int), 1), 100)
            flag_filter = sanitize_string(request.args.get('flag', ''), 100)

            with db.get_connection() as conn:
                # All analyzed accounts for this affiliate on the event day
                day_q = """
                    SELECT duid, email, risk_score, payout_amount, flags,
                           webmaster_code, campaign, data_type, analyzed_at,
                           geo_country, first_name, trans_datetime
                    FROM fraud_results
                    WHERE DATE(trans_datetime) = ?
                      AND lower(webmaster_code) = lower(?)
                    ORDER BY risk_score DESC
                """
                day_df = pd.read_sql_query(day_q, conn, params=[date, code])

                # 14-day baseline for this affiliate (daily counts by event date)
                base_q = """
                    SELECT
                        DATE(trans_datetime)                                       AS day,
                        COUNT(*)                                                   AS total,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END)         AS high_risk,
                        ROUND(AVG(risk_score), 1)                                 AS avg_risk,
                        SUM(payout_amount)                                        AS payout
                    FROM fraud_results
                    WHERE trans_datetime >= DATE(?, '-14 days')
                      AND DATE(trans_datetime) != ?
                      AND lower(webmaster_code) = lower(?)
                    GROUP BY day
                    ORDER BY day
                """
                base_df = pd.read_sql_query(base_q, conn, params=[date, date, code])

            if day_df.empty:
                return jsonify({
                    'date': date, 'affiliate': code,
                    'accounts': [], 'total': 0,
                    'baseline': None, 'baseline_daily': []
                })

            # Summary for the spike day
            total       = len(day_df)
            high_risk   = int((day_df['risk_score'] >= 50).sum())
            avg_risk    = round(float(day_df['risk_score'].mean()), 1)
            total_payout= float(day_df['payout_amount'].sum())

            # Baseline stats
            baseline = None
            if not base_df.empty:
                baseline = {
                    'avg_daily':       round(float(base_df['total'].mean()), 1),
                    'avg_high_risk':   round(float(base_df['high_risk'].mean()), 1),
                    'avg_avg_risk':    round(float(base_df['avg_risk'].mean()), 1),
                    'days_of_data':    len(base_df),
                }
                prev = baseline['avg_daily']
                baseline['vs_baseline_pct'] = round((total - prev) / prev * 100, 1) if prev > 0 else None

            top_flags = count_catalog_flags(day_df['flags'], total=total)[:8]

            # Campaign split for this affiliate on this day
            camp_split = (
                day_df.groupby('campaign')
                .agg(count=('duid','count'), high_risk=('risk_score', lambda x: (x>=50).sum()))
                .reset_index()
                .sort_values('count', ascending=False)
                .head(8)
                .fillna('')
                .to_dict(orient='records')
            )
            for c in camp_split:
                c['count']     = int(c['count'])
                c['high_risk'] = int(c['high_risk'])

            # Account list (paginated, optional flag filter)
            accounts_df = day_df
            if flag_filter:
                accounts_df = day_df[
                    day_df['flags'].apply(lambda x: row_matches_flag_catalog(x, flag_filter))
                ]
            accounts_total = len(accounts_df)
            total_pages = max((accounts_total + per_page - 1) // per_page, 1)
            page = min(page, total_pages)
            offset = (page - 1) * per_page
            cols = [c for c in ['duid','email','risk_score','payout_amount','flags',
                                 'campaign','data_type','geo_country','first_name']
                    if c in day_df.columns]
            page_df = accounts_df.iloc[offset:offset + per_page]
            accounts = page_df[cols].fillna('').to_dict(orient='records')

            return jsonify({
                'date':       date,
                'affiliate':  code,
                'total':      total,
                'high_risk':  high_risk,
                'avg_risk':   avg_risk,
                'total_payout': total_payout,
                'baseline':   baseline,
                'top_flags':  top_flags,
                'camp_split': camp_split,
                'accounts':   accounts,
                'accounts_total': accounts_total,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_pages': total_pages,
                    'flag_filter': flag_filter or None,
                },
                'baseline_daily': base_df.fillna(0).to_dict(orient='records') if not base_df.empty else [],
            })

        except Exception as e:
            logger.error(f"Error in /api/spike-drill/{date}/affiliate/{code}: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/spike-drill/<date>/campaign/<path:campaign>')
    def api_spike_drill_campaign(date, campaign):
        """
        Accounts for a specific campaign on a spike date, with baseline and breakdowns.
        """
        try:
            import pandas as pd
            import re as re_module

            if not re_module.match(r'^\d{4}-\d{2}-\d{2}$', date):
                return jsonify({'error': 'Invalid date format'}), 400

            campaign = sanitize_string(campaign, 200)
            page = max(request.args.get('page', 1, type=int), 1)
            per_page = min(max(request.args.get('per_page', 25, type=int), 1), 100)
            flag_filter = sanitize_string(request.args.get('flag', ''), 100)

            with db.get_connection() as conn:
                day_q = """
                    SELECT duid, email, risk_score, payout_amount, flags,
                           webmaster_code, campaign, data_type, analyzed_at,
                           geo_country, first_name
                    FROM fraud_results
                    WHERE DATE(analyzed_at) = ?
                      AND campaign = ?
                    ORDER BY risk_score DESC
                """
                day_df = pd.read_sql_query(day_q, conn, params=[date, campaign])

                base_q = """
                    SELECT
                        DATE(analyzed_at)                                          AS day,
                        COUNT(*)                                                   AS total,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END)         AS high_risk,
                        ROUND(AVG(risk_score), 1)                                 AS avg_risk,
                        SUM(payout_amount)                                        AS payout
                    FROM fraud_results
                    WHERE analyzed_at >= DATE(?, '-14 days')
                      AND DATE(analyzed_at) != ?
                      AND campaign = ?
                    GROUP BY day
                    ORDER BY day
                """
                base_df = pd.read_sql_query(base_q, conn, params=[date, date, campaign])

            if day_df.empty:
                return jsonify({
                    'date': date, 'campaign': campaign,
                    'accounts': [], 'total': 0,
                    'baseline': None, 'baseline_daily': [],
                })

            total = len(day_df)
            high_risk = int((day_df['risk_score'] >= 50).sum())
            avg_risk = round(float(day_df['risk_score'].mean()), 1)
            total_payout = float(day_df['payout_amount'].sum())

            baseline = None
            if not base_df.empty:
                baseline = {
                    'avg_daily': round(float(base_df['total'].mean()), 1),
                    'avg_high_risk': round(float(base_df['high_risk'].mean()), 1),
                    'avg_avg_risk': round(float(base_df['avg_risk'].mean()), 1),
                    'days_of_data': len(base_df),
                }
                prev = baseline['avg_daily']
                baseline['vs_baseline_pct'] = round((total - prev) / prev * 100, 1) if prev > 0 else None

            top_flags = count_catalog_flags(day_df['flags'], total=total)[:8]

            aff_split = (
                day_df.groupby('webmaster_code')
                .agg(count=('duid', 'count'), high_risk=('risk_score', lambda x: (x >= 50).sum()))
                .reset_index()
                .sort_values('count', ascending=False)
                .head(8)
                .fillna('')
                .to_dict(orient='records')
            )
            for a in aff_split:
                a['count'] = int(a['count'])
                a['high_risk'] = int(a['high_risk'])

            accounts_df = day_df
            if flag_filter:
                accounts_df = day_df[
                    day_df['flags'].apply(lambda x: row_matches_flag_catalog(x, flag_filter))
                ]
            accounts_total = len(accounts_df)
            total_pages = max((accounts_total + per_page - 1) // per_page, 1)
            page = min(page, total_pages)
            offset = (page - 1) * per_page
            cols = [c for c in ['duid', 'email', 'risk_score', 'payout_amount', 'flags',
                                 'campaign', 'data_type', 'geo_country', 'first_name', 'webmaster_code']
                    if c in day_df.columns]
            accounts = accounts_df.iloc[offset:offset + per_page][cols].fillna('').to_dict(orient='records')

            return jsonify({
                'date': date,
                'campaign': campaign,
                'total': total,
                'high_risk': high_risk,
                'avg_risk': avg_risk,
                'total_payout': total_payout,
                'baseline': baseline,
                'top_flags': top_flags,
                'aff_split': aff_split,
                'accounts': accounts,
                'accounts_total': accounts_total,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total_pages': total_pages,
                    'flag_filter': flag_filter or None,
                },
                'baseline_daily': base_df.fillna(0).to_dict(orient='records') if not base_df.empty else [],
            })

        except Exception as e:
            logger.error(f"Error in /api/spike-drill/{date}/campaign/{campaign}: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/funnel')
    def api_funnel():
        """Lead-to-sale funnel: free signups → paid conversion → high-risk among paid."""
        try:
            affiliate = sanitize_string(request.args.get('affiliate', ''), 100)
            campaign = sanitize_string(request.args.get('campaign', ''), 200)
            date_from = request.args.get('date_from', '').strip()
            date_to = request.args.get('date_to', '').strip()
            high_t = request.args.get('threshold', type=int)
            if high_t is None:
                high_t = int(config.get('risk_thresholds', {}).get('high', 50))

            clauses = []
            params: list = []
            if affiliate:
                clauses.append("f.webmaster_code = ?")
                params.append(affiliate)
            if campaign:
                clauses.append(
                    "LOWER(TRIM(REPLACE(f.campaign, '.', ''))) = LOWER(TRIM(REPLACE(?, '.', '')))"
                )
                params.append(campaign.rstrip('. '))
            if date_from:
                clauses.append("DATE(f.trans_datetime) >= ?")
                params.append(date_from)
            if date_to:
                clauses.append("DATE(f.trans_datetime) <= ?")
                params.append(date_to)
            where_f = " AND ".join(clauses) if clauses else "1=1"

            with db.get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    f"SELECT COUNT(DISTINCT f.duid) FROM free f WHERE {where_f}",  # noqa: S608
                    params,
                )
                free_cnt = int(cur.fetchone()[0] or 0)

                cur.execute(
                    f"""
                    SELECT COUNT(DISTINCT f.duid) FROM free f
                    INNER JOIN paid p ON p.duid = f.duid
                    WHERE {where_f}
                    """,  # noqa: S608
                    params,
                )
                conv_cnt = int(cur.fetchone()[0] or 0)

                cur.execute(
                    f"""
                    SELECT COUNT(*) AS hr_cnt,
                           IFNULL(SUM(t.payout_amount), 0) AS pay_sum
                    FROM (
                        SELECT DISTINCT f.duid, p.payout_amount AS payout_amount
                        FROM free f
                        INNER JOIN paid p ON p.duid = f.duid
                        INNER JOIN fraud_results fr ON fr.duid = f.duid
                        WHERE {where_f} AND fr.risk_score >= ?
                    ) t
                    """,  # noqa: S608
                    params + [high_t],
                )
                row = cur.fetchone()
                hr_cnt = int(row[0] or 0)
                payout_at_risk = float(row[1] or 0)

                def _affiliate_campaign_row(r, key_field: str):
                    label, fn, cn, hn, pr = r[0], int(r[1] or 0), int(r[2] or 0), int(r[3] or 0), float(r[4] or 0)
                    conv_pct = round(cn / fn * 100, 2) if fn else 0
                    return {
                        key_field: label or '',
                        'free_signups': fn,
                        'converted_paid': cn,
                        'high_risk_paid': hn,
                        'payout_at_risk': pr,
                        'conversion_rate': conv_pct,
                        'fraud_among_converted_pct': round(hn / cn * 100, 2) if cn else 0,
                        'non_conversion_pct': round(100 - conv_pct, 2) if fn else 0,
                        'high_risk_pct_of_free': round(hn / fn * 100, 2) if fn else 0,
                    }

                by_affiliate = []
                if not affiliate:
                    aff_clauses = []
                    aff_params: list = []
                    if date_from:
                        aff_clauses.append("DATE(f.trans_datetime) >= ?")
                        aff_params.append(date_from)
                    if date_to:
                        aff_clauses.append("DATE(f.trans_datetime) <= ?")
                        aff_params.append(date_to)
                    if campaign:
                        aff_clauses.append(
                            "LOWER(TRIM(REPLACE(f.campaign, '.', ''))) = "
                            "LOWER(TRIM(REPLACE(?, '.', '')))"
                        )
                        aff_params.append(campaign.rstrip('. '))
                    where_a = " AND ".join(aff_clauses) if aff_clauses else "1=1"
                    cur.execute(
                        f"""
                        SELECT f.webmaster_code,
                               COUNT(DISTINCT f.duid) AS free_n,
                               COUNT(DISTINCT CASE WHEN p.duid IS NOT NULL THEN f.duid END) AS conv_n,
                               COUNT(DISTINCT CASE WHEN p.duid IS NOT NULL AND fr.risk_score >= ?
                                    THEN f.duid END) AS hr_n,
                               IFNULL(SUM(CASE WHEN p.duid IS NOT NULL AND fr.risk_score >= ?
                                    THEN (SELECT p2.payout_amount FROM paid p2 WHERE p2.duid = f.duid LIMIT 1)
                                    ELSE 0 END), 0) AS pay_risk
                        FROM free f
                        LEFT JOIN paid p ON p.duid = f.duid
                        LEFT JOIN fraud_results fr ON fr.duid = f.duid
                        WHERE {where_a} AND f.webmaster_code IS NOT NULL AND TRIM(f.webmaster_code) != ''
                        GROUP BY f.webmaster_code
                        ORDER BY free_n DESC
                        LIMIT 20
                        """,  # noqa: S608
                        aff_params + [high_t, high_t],
                    )
                    for r in cur.fetchall():
                        by_affiliate.append(_affiliate_campaign_row(r, 'affiliate'))

                by_campaign = []
                if not campaign:
                    camp_clauses = []
                    camp_params: list = []
                    if affiliate:
                        camp_clauses.append("f.webmaster_code = ?")
                        camp_params.append(affiliate)
                    if date_from:
                        camp_clauses.append("DATE(f.trans_datetime) >= ?")
                        camp_params.append(date_from)
                    if date_to:
                        camp_clauses.append("DATE(f.trans_datetime) <= ?")
                        camp_params.append(date_to)
                    where_c = " AND ".join(camp_clauses) if camp_clauses else "1=1"
                    cur.execute(
                        f"""
                        SELECT f.campaign,
                               COUNT(DISTINCT f.duid) AS free_n,
                               COUNT(DISTINCT CASE WHEN p.duid IS NOT NULL THEN f.duid END) AS conv_n,
                               COUNT(DISTINCT CASE WHEN p.duid IS NOT NULL AND fr.risk_score >= ?
                                    THEN f.duid END) AS hr_n,
                               IFNULL(SUM(CASE WHEN p.duid IS NOT NULL AND fr.risk_score >= ?
                                    THEN (SELECT p2.payout_amount FROM paid p2 WHERE p2.duid = f.duid LIMIT 1)
                                    ELSE 0 END), 0) AS pay_risk
                        FROM free f
                        LEFT JOIN paid p ON p.duid = f.duid
                        LEFT JOIN fraud_results fr ON fr.duid = f.duid
                        WHERE {where_c}
                          AND f.campaign IS NOT NULL AND TRIM(f.campaign) != ''
                        GROUP BY f.campaign
                        ORDER BY free_n DESC
                        LIMIT 20
                        """,  # noqa: S608
                        camp_params + [high_t, high_t],
                    )
                    for r in cur.fetchall():
                        by_campaign.append(_affiliate_campaign_row(r, 'campaign'))

            return jsonify(sanitize_for_json({
                'free_signups': free_cnt,
                'converted_paid': conv_cnt,
                'high_risk_paid': hr_cnt,
                'payout_at_risk': payout_at_risk,
                'high_risk_threshold': high_t,
                'conversion_rate': round(conv_cnt / free_cnt * 100, 2) if free_cnt else 0,
                'fraud_among_converted_pct': round(hr_cnt / conv_cnt * 100, 2) if conv_cnt else 0,
                'filters': {
                    'affiliate': affiliate or None,
                    'campaign': campaign or None,
                    'date_from': date_from or None,
                    'date_to': date_to or None,
                },
                'by_affiliate': by_affiliate,
                'by_campaign': by_campaign,
            }))
        except Exception as e:
            logger.error(f"Error in /api/funnel: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/model-performance')
    def api_model_performance():
        """Precision/recall vs outcomes, threshold curve, weekly trend, per-flag precision."""
        try:
            import json as json_lib
            import pandas as pd

            with db.get_connection() as conn:
                df = pd.read_sql_query(
                    """
                    SELECT fr.duid, fr.risk_score, fr.flags, fr.analyzed_at, fo.outcome
                    FROM fraud_outcomes fo
                    JOIN fraud_results fr ON fr.duid = fo.duid
                    WHERE fo.outcome IN ('confirmed_fraud', 'false_positive')
                    """,
                    conn,
                )

            if df.empty:
                return jsonify({
                    'reviewed_count': 0,
                    'thresholds': [],
                    'at_default': None,
                    'weekly': [],
                    'by_flag': [],
                    'default_threshold': int(config.get('risk_thresholds', {}).get('high', 50)),
                })

            df['risk_score'] = pd.to_numeric(df['risk_score'], errors='coerce').fillna(0).astype(int)
            is_fraud = df['outcome'] == 'confirmed_fraud'
            is_fp = df['outcome'] == 'false_positive'

            def metrics_at_threshold(t: int):
                tp = int(((df['risk_score'] >= t) & is_fraud).sum())
                fp = int(((df['risk_score'] >= t) & is_fp).sum())
                fn = int(((df['risk_score'] < t) & is_fraud).sum())
                tn = int(((df['risk_score'] < t) & is_fp).sum())
                prec = tp / (tp + fp) if (tp + fp) else None
                rec = tp / (tp + fn) if (tp + fn) else None
                f1 = (2 * prec * rec / (prec + rec)) if prec is not None and rec is not None and (prec + rec) > 0 else None
                return {
                    'threshold': t, 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
                    'precision': round(prec * 100, 2) if prec is not None else None,
                    'recall': round(rec * 100, 2) if rec is not None else None,
                    'f1': round(f1 * 100, 2) if f1 is not None else None,
                }

            thresh_list = [25, 30, 35, 40, 45, 50, 55, 60, 70, 80]
            thresholds = [metrics_at_threshold(t) for t in thresh_list]
            default_t = int(config.get('risk_thresholds', {}).get('high', 50))
            at_default = metrics_at_threshold(default_t)

            df['analyzed_at'] = pd.to_datetime(df['analyzed_at'], errors='coerce')
            df = df.dropna(subset=['analyzed_at'])
            weekly = []
            if not df.empty:
                df['week'] = df['analyzed_at'].dt.to_period('W').astype(str)
                for week, g in df.groupby('week'):
                    is_fraud_w = g['outcome'] == 'confirmed_fraud'
                    is_fp_w = g['outcome'] == 'false_positive'
                    tp = int(((g['risk_score'] >= default_t) & is_fraud_w).sum())
                    fp = int(((g['risk_score'] >= default_t) & is_fp_w).sum())
                    fn = int(((g['risk_score'] < default_t) & is_fraud_w).sum())
                    tn = int(((g['risk_score'] < default_t) & is_fp_w).sum())
                    prec = tp / (tp + fp) if (tp + fp) else None
                    rec = tp / (tp + fn) if (tp + fn) else None
                    f1 = (
                        (2 * prec * rec / (prec + rec))
                        if prec is not None and rec is not None and (prec + rec) > 0
                        else None
                    )
                    weekly.append({
                        'week': week,
                        'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
                        'precision': round(prec * 100, 2) if prec is not None else None,
                        'recall': round(rec * 100, 2) if rec is not None else None,
                        'f1': round(f1 * 100, 2) if f1 is not None else None,
                    })

            def parse_flags(val):
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return []
                s = str(val).strip()
                if not s:
                    return []
                try:
                    return json_lib.loads(s.replace("'", '"'))
                except Exception:
                    return [s] if s else []

            flag_stats = {}
            for _, row in df.iterrows():
                for fl in parse_flags(row['flags']):
                    fl = str(fl).strip().upper()
                    if not fl:
                        continue
                    if fl not in flag_stats:
                        flag_stats[fl] = {'fraud': 0, 'fp': 0}
                    if row['outcome'] == 'confirmed_fraud':
                        flag_stats[fl]['fraud'] += 1
                    else:
                        flag_stats[fl]['fp'] += 1

            by_flag = []
            for fl, st in sorted(flag_stats.items(), key=lambda x: -(x[1]['fraud'] + x[1]['fp']))[:40]:
                tot = st['fraud'] + st['fp']
                prec = st['fraud'] / tot * 100 if tot else None
                by_flag.append({
                    'flag': fl.replace('_', ' '),
                    'confirmed_fraud': st['fraud'],
                    'false_positive': st['fp'],
                    'total': tot,
                    'precision_pct': round(prec, 2) if prec is not None else None,
                })

            payload = sanitize_for_json({
                'reviewed_count': int(len(df)),
                'default_threshold': default_t,
                'at_default': at_default,
                'thresholds': thresholds,
                'weekly': weekly,
                'by_flag': by_flag,
            })
            return jsonify(payload)
        except Exception as e:
            logger.error(f"Error in /api/model-performance: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/ml/status')
    def api_ml_status():
        """Supervised ML readiness and active model metadata."""
        try:
            from scripts.fraud_ml_model import get_ml_status

            status = get_ml_status(db)
            ml_cfg = config.get('ml_model', {})
            status['min_labeled_samples'] = int(ml_cfg.get('min_labeled_samples', 30))
            status['ready_to_train'] = (
                status.get('labeled_count', 0) >= status['min_labeled_samples']
                and status.get('sklearn_available', False)
            )
            active = status.get('active_model')
            if active:
                status['active_model'] = sanitize_for_json({
                    k: active.get(k)
                    for k in (
                        'run_id', 'trained_at', 'labeled_samples', 'fraud_rate',
                        'test_roc_auc', 'cv_roc_auc_mean', 'cv_roc_auc_std',
                        'test_precision', 'test_recall', 'test_pr_auc',
                        'optimal_threshold', 'artifact_path',
                    )
                })
                metrics = active.get('metrics') or {}
                status['roc_curve'] = metrics.get('roc_curve', [])
                status['top_features'] = metrics.get('top_features', [])
            return jsonify(sanitize_for_json(status))
        except Exception as e:
            logger.error(f"Error in /api/ml/status: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/ml/train', methods=['POST'])
    def api_ml_train():
        """Train logistic regression on reviewed outcomes and score all accounts."""
        try:
            from scripts.fraud_ml_model import train_fraud_model

            result = train_fraud_model(db, config)
            if not result.get('success'):
                return jsonify(sanitize_for_json(result)), 400
            return jsonify(sanitize_for_json(result))
        except ImportError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Error in /api/ml/train: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/ml/compare')
    def api_ml_compare():
        """Compare rule-based threshold vs ML probabilities on labeled outcomes."""
        try:
            from scripts.fraud_ml_model import FraudMLTrainer

            payload = FraudMLTrainer.compare_to_rules(db, config)
            return jsonify(sanitize_for_json(payload))
        except Exception as e:
            logger.error(f"Error in /api/ml/compare: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/temporal-analysis')
    def api_temporal_analysis():
        """Get temporal fraud trends"""
        try:
            days = request.args.get('days', 30, type=int)
            df = db.get_fraud_results()
            
            if df.empty:
                return jsonify({'daily': [], 'hourly': [], 'weekday': []})
            
            import pandas as pd
            df['analyzed_at'] = pd.to_datetime(df['analyzed_at'])
            
            # Filter to requested days
            cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
            df = df[df['analyzed_at'] >= cutoff]
            
            # Daily trends
            daily = df.groupby(df['analyzed_at'].dt.date).agg({
                'duid': 'count',
                'risk_score': 'mean',
                'payout_amount': 'sum'
            }).reset_index()
            daily.columns = ['date', 'count', 'avg_risk', 'total_payout']
            daily['date'] = daily['date'].astype(str)
            
            # High risk by day
            high_risk_df = df[df['risk_score'] >= 50]
            high_daily = high_risk_df.groupby(high_risk_df['analyzed_at'].dt.date).size().reset_index()
            high_daily.columns = ['date', 'high_risk_count']
            high_daily['date'] = high_daily['date'].astype(str)
            
            # Merge
            daily = daily.merge(high_daily, on='date', how='left').fillna(0)
            
            # Hourly distribution
            hourly = df.groupby(df['analyzed_at'].dt.hour).agg({
                'duid': 'count',
                'risk_score': 'mean'
            }).reset_index()
            hourly.columns = ['hour', 'count', 'avg_risk']
            
            # Weekday distribution
            weekday = df.groupby(df['analyzed_at'].dt.dayofweek).agg({
                'duid': 'count',
                'risk_score': 'mean'
            }).reset_index()
            weekday.columns = ['weekday', 'count', 'avg_risk']
            weekday['weekday_name'] = weekday['weekday'].map({
                0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri', 5: 'Sat', 6: 'Sun'
            })
            
            return jsonify({
                'daily': daily.to_dict(orient='records'),
                'hourly': hourly.to_dict(orient='records'),
                'weekday': weekday.to_dict(orient='records')
            })
        except Exception as e:
            logger.error(f"Error in /api/temporal-analysis: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/pattern-discovery')
    def api_pattern_discovery():
        """Pattern summary: flag frequency, domains, risk distribution."""
        try:
            filters = _analysis_filters_from_request()
            min_risk = request.args.get('min_risk', type=int)
            insights = AnalysisInsights(db)
            return jsonify(insights.compute_pattern_summary(min_risk=min_risk, **filters))
        except Exception as e:
            logger.error(f"Error in /api/pattern-discovery: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/analysis/action-items')
    def api_analysis_action_items():
        """Prioritized actionable cards for fraud ops."""
        try:
            insights = AnalysisInsights(db)
            return jsonify(insights.compute_action_items(**_analysis_filters_from_request()))
        except Exception as e:
            logger.error(f"Error in /api/analysis/action-items: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/analysis/rising-patterns')
    def api_analysis_rising_patterns():
        """Rising flags, domains, affiliates, and campaigns vs baseline."""
        try:
            recent_days = request.args.get('recent_days', 7, type=int)
            baseline_days = request.args.get('baseline_days', 28, type=int)
            insights = AnalysisInsights(db)
            return jsonify(insights.compute_rising_patterns(
                recent_days=recent_days,
                baseline_days=baseline_days,
                **_analysis_filters_from_request(),
            ))
        except Exception as e:
            logger.error(f"Error in /api/analysis/rising-patterns: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/analysis/rule-cooccurrence')
    def api_analysis_rule_cooccurrence():
        """High-signal flag combinations from reviewed accounts."""
        try:
            min_reviewed = request.args.get('min_reviewed', 5, type=int)
            insights = AnalysisInsights(db)
            return jsonify(insights.compute_rule_cooccurrence(
                min_reviewed=min_reviewed,
                **_analysis_filters_from_request(),
            ))
        except Exception as e:
            logger.error(f"Error in /api/analysis/rule-cooccurrence: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/analysis/review-coverage')
    def api_analysis_review_coverage():
        """Review and sampling coverage metrics."""
        try:
            insights = AnalysisInsights(db)
            return jsonify(insights.compute_review_coverage())
        except Exception as e:
            logger.error(f"Error in /api/analysis/review-coverage: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/analysis/review-queue')
    def api_analysis_review_queue():
        """High-risk accounts pending human review (no outcome recorded)."""
        try:
            min_risk = request.args.get('min_risk', 50, type=int)
            limit = min(request.args.get('limit', 200, type=int), 1000)
            trans_date = sanitize_string(request.args.get('trans_date', ''), 10)
            affiliate = sanitize_string(request.args.get('affiliate', ''), 100)

            df = db.get_fraud_results(
                min_risk=min_risk,
                limit=limit * 3 if affiliate else limit,
                exclude_reviewed=True,
            )
            if df.empty:
                return jsonify({'accounts': [], 'total': 0})

            if trans_date and 'trans_datetime' in df.columns:
                import pandas as pd
                df = df[pd.to_datetime(df['trans_datetime']).dt.strftime('%Y-%m-%d') == trans_date]
            if affiliate and 'webmaster_code' in df.columns:
                df = df[df['webmaster_code'].astype(str).str.lower() == affiliate.lower()]

            df = df.head(limit)
            accounts = []
            for _, row in df.iterrows():
                accounts.append({
                    'duid': row.get('duid'),
                    'email': row.get('email'),
                    'risk_score': int(row.get('risk_score') or 0),
                    'payout_amount': float(row.get('payout_amount') or 0),
                    'data_type': row.get('data_type'),
                    'affiliate': row.get('webmaster_code'),
                    'campaign': row.get('campaign'),
                    'flags': row.get('flags'),
                    'trans_datetime': row.get('trans_datetime'),
                    'analyzed_at': row.get('analyzed_at'),
                })
            return jsonify({'accounts': accounts, 'total': len(accounts), 'min_risk': min_risk})
        except Exception as e:
            logger.error(f"Error in /api/analysis/review-queue: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/analysis/drilldown')
    def api_analysis_drilldown():
        """Account-level drill-down from analysis aggregates."""
        try:
            import pandas as pd

            drill_type = sanitize_string(request.args.get('type', ''), 20).lower()
            value = sanitize_string(request.args.get('value', ''), 200)
            page = request.args.get('page', 1, type=int)
            per_page = min(request.args.get('per_page', 50, type=int), 200)
            min_risk = request.args.get('min_risk', type=int)

            if not drill_type or not value:
                return jsonify({'error': 'type and value are required'}), 400

            with db.get_connection() as conn:
                df = pd.read_sql_query(
                    """
                    SELECT duid, email, risk_score, payout_amount, data_type,
                           webmaster_code, campaign, flags, trans_datetime, analyzed_at
                    FROM fraud_results
                    WHERE 1=1
                    """,
                    conn,
                )

            if df.empty:
                return jsonify({'accounts': [], 'total': 0, 'page': page, 'total_pages': 0})

            if drill_type == 'day':
                df = df[pd.to_datetime(df['trans_datetime']).dt.strftime('%Y-%m-%d') == value[:10]]
            elif drill_type == 'affiliate':
                df = df[df['webmaster_code'].astype(str).str.lower() == value.lower()]
            elif drill_type == 'campaign':
                df = df[df['campaign'].astype(str).str.lower() == value.lower()]
            elif drill_type == 'flag':
                mask = df['flags'].apply(lambda x: _row_matches_flag_catalog(x, value))
                df = df[mask]
            elif drill_type == 'domain':
                domain = value.lower().lstrip('@')
                df = df[df['email'].astype(str).str.lower().str.endswith('@' + domain)]
            else:
                return jsonify({'error': f'Unsupported drilldown type: {drill_type}'}), 400

            if min_risk is not None:
                df = df[df['risk_score'] >= min_risk]

            for col in ('trans_datetime', 'analyzed_at'):
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors='coerce')
            df = df.sort_values(
                ['risk_score', 'trans_datetime', 'analyzed_at'],
                ascending=[False, False, False],
                na_position='last',
            )
            total = len(df)
            total_pages = max(1, (total + per_page - 1) // per_page)
            start = (page - 1) * per_page
            page_df = df.iloc[start:start + per_page]

            accounts = []
            for _, row in page_df.iterrows():
                accounts.append({
                    'duid': row['duid'],
                    'email': row['email'],
                    'risk_score': int(row['risk_score']) if pd.notna(row['risk_score']) else 0,
                    'payout_amount': float(row['payout_amount']) if pd.notna(row['payout_amount']) else 0,
                    'data_type': row['data_type'],
                    'affiliate': row['webmaster_code'],
                    'campaign': row['campaign'],
                    'flags': row['flags'],
                    'trans_datetime': row['trans_datetime'],
                    'analyzed_at': row['analyzed_at'],
                })

            return jsonify({
                'type': drill_type,
                'value': value,
                'accounts': accounts,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': total_pages,
            })
        except Exception as e:
            logger.error(f"Error in /api/analysis/drilldown: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/cluster-analysis')
    def api_cluster_analysis():
        """Get cluster analysis data"""
        try:
            import pandas as pd
            from collections import Counter

            hide_house = request.args.get('hide_house', 'true').lower() != 'false'
            wl_set = {a.lower() for a in config.get_whitelisted_affiliates()}
            exclude_set = set(wl_set)
            if hide_house:
                exclude_set |= {
                    str(h).strip().lower()
                    for h in (config.get('house_affiliates') or [])
                    if h and str(h).strip()
                }

            with db.get_connection() as conn:
                # Query fraud_results directly — one row per DUID, no join inflation
                base_q = """
                    SELECT duid, ip, email, risk_score, payout_amount, webmaster_code
                    FROM fraud_results
                    WHERE ip IS NOT NULL AND ip != '' AND ip != 'nan'
                """
                df = pd.read_sql_query(base_q, conn)

            if df.empty:
                return jsonify({'ip_clusters': [], 'domain_clusters': [], 'affiliate_clusters': []})

            if exclude_set:
                df = df[~df['webmaster_code'].str.lower().isin(exclude_set)]

            results = {}

            # IP clusters — group by IP, count distinct DUIDs
            ip_stats = (
                df.groupby('ip')
                .agg(
                    accounts=('duid', 'nunique'),
                    avg_risk=('risk_score', 'mean'),
                    total_payout=('payout_amount', 'sum'),
                    high_risk=('risk_score', lambda x: (x >= 50).sum()),
                )
                .reset_index()
            )
            ip_stats = ip_stats[ip_stats['accounts'] > 1].sort_values('accounts', ascending=False).head(20)
            ip_stats['avg_risk'] = ip_stats['avg_risk'].round(1)
            results['ip_clusters'] = ip_stats.to_dict(orient='records')
            
            # Email domain clusters
            df['email_domain'] = df['email'].str.lower().str.extract(r'@(.+)$', expand=False)
            domain_stats = (
                df[df['email_domain'].notna()]
                .groupby('email_domain')
                .agg(accounts=('duid', 'nunique'), avg_risk=('risk_score', 'mean'), total_payout=('payout_amount', 'sum'))
                .reset_index()
                .rename(columns={'email_domain': 'domain'})
            )
            domain_stats = domain_stats[domain_stats['accounts'] > 2].sort_values('avg_risk', ascending=False).head(15)
            results['domain_clusters'] = domain_stats.round(1).to_dict(orient='records')

            # Affiliate risk clusters
            aff_df = df[df['webmaster_code'].notna() & (df['webmaster_code'] != '')]
            if len(aff_df) >= 5:
                aff_stats = (
                    aff_df.groupby('webmaster_code')
                    .agg(accounts=('duid', 'nunique'), avg_risk=('risk_score', 'mean'), total_payout=('payout_amount', 'sum'))
                    .reset_index()
                    .rename(columns={'webmaster_code': 'affiliate'})
                )
                aff_stats['high_risk_pct'] = aff_df.groupby('webmaster_code').apply(
                    lambda g: round((g['risk_score'] >= 50).sum() / len(g) * 100, 1)
                ).values
                aff_stats = aff_stats.sort_values('high_risk_pct', ascending=False).head(15)
                results['affiliate_clusters'] = aff_stats.round(1).to_dict(orient='records')
            else:
                results['affiliate_clusters'] = []

            return jsonify(results)
        except Exception as e:
            logger.error(f"Error in /api/cluster-analysis: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/bulk-outcomes', methods=['POST'])
    def api_bulk_outcomes():
        """Record outcomes for multiple accounts at once"""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'JSON body required'}), 400

            duids = data.get('duids', [])
            outcome = data.get('outcome')
            notes = sanitize_string(data.get('notes', ''), 1000)

            if not duids or not isinstance(duids, list):
                return jsonify({'error': 'duids array is required'}), 400
            if len(duids) > 100:
                return jsonify({'error': 'Maximum 100 accounts per bulk operation'}), 400
            if not validate_outcome(outcome):
                return jsonify({'error': f'Invalid outcome. Must be one of: {", ".join(VALID_OUTCOMES)}'}), 400

            import time
            success_count = 0
            failed = []
            for duid in duids:
                duid = sanitize_string(str(duid), 100)
                if not duid:
                    failed.append(duid)
                    continue
                    
                # Retry logic for each record
                max_retries = 3
                retry_delay = 0.1
                success = False
                
                for attempt in range(max_retries):
                    try:
                        if db.record_fraud_outcome(duid, outcome, notes=notes, reviewed_by='dashboard-bulk'):
                            success_count += 1
                            success = True
                            break
                    except Exception as db_error:
                        if 'database is locked' in str(db_error) and attempt < max_retries - 1:
                            time.sleep(retry_delay * (attempt + 1))
                            continue
                        break
                
                if not success:
                    failed.append(duid)

            logger.info(f"Bulk outcome: {success_count} succeeded, {len(failed)} failed -> {outcome}")
            return jsonify({
                'status': 'ok',
                'success_count': success_count,
                'failed_count': len(failed),
                'failed_duids': failed[:10]
            })
        except Exception as e:
            logger.error(f"Error in POST /api/bulk-outcomes: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/campaign-analysis')
    def api_campaign_analysis():
        """Get fraud analysis grouped by campaign"""
        try:
            import pandas as pd
            min_accounts = request.args.get('min_accounts', 5, type=int)

            with db.get_connection() as conn:
                query = """
                    SELECT
                        campaign,
                        COUNT(*) as total_accounts,
                        COUNT(CASE WHEN risk_score >= 50 THEN 1 END) as high_risk_count,
                        COUNT(CASE WHEN risk_score >= 25 AND risk_score < 50 THEN 1 END) as medium_risk_count,
                        ROUND(AVG(risk_score), 1) as avg_risk_score,
                        SUM(payout_amount) as total_payout,
                        SUM(CASE WHEN risk_score >= 50 THEN payout_amount ELSE 0 END) as high_risk_payout,
                        COUNT(DISTINCT webmaster_code) as affiliate_count,
                        ROUND(COUNT(CASE WHEN risk_score >= 50 THEN 1 END) * 100.0 / COUNT(*), 1) as high_risk_pct
                    FROM fraud_results
                    WHERE campaign IS NOT NULL AND campaign != ''
                    GROUP BY campaign
                    HAVING total_accounts >= ?
                    ORDER BY high_risk_pct DESC, high_risk_count DESC
                    LIMIT 100
                """
                df = pd.read_sql_query(query, conn, params=[min_accounts])

                return jsonify({
                    'campaigns': df.fillna(0).to_dict(orient='records'),
                    'total_campaigns': len(df)
                })
        except Exception as e:
            logger.error(f"Error in /api/campaign-analysis: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/affiliate-comparison')
    def api_affiliate_comparison():
        """Compare multiple affiliates side-by-side"""
        try:
            import pandas as pd
            codes = request.args.get('codes', '')
            code_list = [sanitize_string(c.strip(), 100) for c in codes.split(',') if c.strip()]

            if not code_list or len(code_list) > 5:
                return jsonify({'error': 'Provide 1-5 affiliate codes separated by commas'}), 400

            with db.get_connection() as conn:
                placeholders = ','.join(['?'] * len(code_list))
                query = f"""
                    SELECT
                        webmaster_code,
                        COUNT(*) as total_accounts,
                        COUNT(CASE WHEN risk_score >= 50 THEN 1 END) as high_risk_count,
                        COUNT(CASE WHEN risk_score >= 25 AND risk_score < 50 THEN 1 END) as medium_risk_count,
                        ROUND(AVG(risk_score), 1) as avg_risk_score,
                        SUM(payout_amount) as total_payout,
                        SUM(CASE WHEN risk_score >= 50 THEN payout_amount ELSE 0 END) as high_risk_payout,
                        ROUND(COUNT(CASE WHEN risk_score >= 50 THEN 1 END) * 100.0 / COUNT(*), 1) as high_risk_pct,
                        COUNT(DISTINCT campaign) as campaign_count,
                        MIN(analyzed_at) as first_seen,
                        MAX(analyzed_at) as last_seen
                    FROM fraud_results
                    WHERE webmaster_code IN ({placeholders})
                    GROUP BY webmaster_code
                """
                df = pd.read_sql_query(query, conn, params=code_list)

                # Get top flags for each affiliate
                flags_query = f"""
                    SELECT webmaster_code, flags FROM fraud_results
                    WHERE webmaster_code IN ({placeholders}) AND risk_score >= 50
                """
                flags_df = pd.read_sql_query(flags_query, conn, params=code_list)

                from collections import Counter
                affiliate_flags = {}
                for code in code_list:
                    code_flags = flags_df[flags_df['webmaster_code'] == code]['flags'].tolist()
                    flag_counts = Counter()
                    for flags_str in code_flags:
                        try:
                            if isinstance(flags_str, str):
                                flags_str = flags_str.replace("'", '"')
                                flags = json.loads(flags_str) if flags_str.startswith('[') else [flags_str]
                            else:
                                flags = flags_str if isinstance(flags_str, list) else []
                            for flag in flags:
                                if flag and flag != '[]':
                                    flag_counts[str(flag).strip("[]' ")] += 1
                        except:
                            continue
                    affiliate_flags[code] = [{'flag': f, 'count': c} for f, c in flag_counts.most_common(5)]

                result = df.fillna(0).to_dict(orient='records')
                for r in result:
                    r['top_flags'] = affiliate_flags.get(r['webmaster_code'], [])

                return jsonify({'affiliates': result})
        except Exception as e:
            logger.error(f"Error in /api/affiliate-comparison: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/false-positive-analysis')
    def api_false_positive_analysis():
        """Analyze which flags cause the most false positives (unified rule stats)."""
        try:
            insights = AnalysisInsights(db)
            return jsonify(insights.compute_fp_analysis(**_analysis_filters_from_request()))
        except Exception as e:
            logger.error(f"Error in /api/false-positive-analysis: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/activity-log')
    def api_activity_log():
        """Get recent activity (outcomes recorded, analyses run, etc.)"""
        try:
            import pandas as pd
            limit = request.args.get('limit', 50, type=int)

            with db.get_connection() as conn:
                # Recent outcomes
                outcomes_query = """
                    SELECT
                        fo.duid, fo.outcome, fo.outcome_notes as notes, fo.reviewed_at as recorded_at,
                        fr.email, fr.risk_score, fr.payout_amount
                    FROM fraud_outcomes fo
                    LEFT JOIN fraud_results fr ON fo.duid = fr.duid
                    ORDER BY fo.reviewed_at DESC
                    LIMIT ?
                """
                outcomes_df = pd.read_sql_query(outcomes_query, conn, params=[limit])

                activities = []
                for _, row in outcomes_df.iterrows():
                    activities.append({
                        'type': 'outcome',
                        'timestamp': row['recorded_at'],
                        'duid': row['duid'],
                        'email': row['email'],
                        'outcome': row['outcome'],
                        'risk_score': row['risk_score'],
                        'payout_amount': row['payout_amount'],
                        'notes': row['notes']
                    })

                # Sort by timestamp
                activities.sort(key=lambda x: x['timestamp'] or '', reverse=True)

                return jsonify({
                    'activities': activities[:limit],
                    'count': len(activities)
                })
        except Exception as e:
            logger.error(f"Error in /api/activity-log: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/saved-filters')
    def api_get_saved_filters():
        """Get saved filter presets"""
        try:
            filters = config.get('saved_filters', [])
            return jsonify({'filters': filters})
        except Exception as e:
            logger.error(f"Error in /api/saved-filters: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/saved-filters', methods=['POST'])
    def api_save_filter():
        """Save a new filter preset"""
        try:
            data = request.get_json()
            name = sanitize_string(data.get('name', ''), 50)
            filter_config = data.get('filter', {})

            if not name:
                return jsonify({'error': 'Filter name is required'}), 400

            filters = config.get('saved_filters', [])

            # Remove existing filter with same name
            filters = [f for f in filters if f.get('name') != name]

            filters.append({
                'name': name,
                'filter': filter_config,
                'created_at': datetime.now().isoformat()
            })

            # Keep max 20 filters
            filters = filters[-20:]
            config.set('saved_filters', filters)
            config.save()

            return jsonify({'status': 'ok', 'filters': filters})
        except Exception as e:
            logger.error(f"Error saving filter: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/saved-filters/<name>', methods=['DELETE'])
    def api_delete_filter(name):
        """Delete a saved filter"""
        try:
            name = sanitize_string(name, 50)
            filters = config.get('saved_filters', [])
            filters = [f for f in filters if f.get('name') != name]
            config.set('saved_filters', filters)
            config.save()
            return jsonify({'status': 'ok'})
        except Exception as e:
            logger.error(f"Error deleting filter: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/settings')
    def api_get_settings():
        """Get all settings"""
        try:
            file_api_key = (config.config.get('api_key') or '').strip()
            env_api = bool((os.getenv('FRAUD_DETECTION_API_KEY') or '').strip())
            eff_api = (config.get_api_key() or '').strip()
            if env_api:
                api_key_source = 'environment'
            elif file_api_key:
                api_key_source = 'file'
            else:
                api_key_source = 'none'
            api_key_masked = ''
            if eff_api and len(eff_api) > 4:
                api_key_masked = '************' + eff_api[-4:]
            elif eff_api:
                api_key_masked = '****'

            wt_env = bool((os.getenv('WEBHOOK_INGEST_TOKEN') or '').strip())
            wt_file = (config.config.get('webhook_ingest_token') or '').strip()
            eff_wt = config.get_webhook_ingest_token()
            if wt_env:
                webhook_token_source = 'environment'
            elif wt_file:
                webhook_token_source = 'file'
            else:
                webhook_token_source = 'none'
            webhook_token_masked = ''
            if eff_wt and len(eff_wt) > 4:
                webhook_token_masked = '************' + eff_wt[-4:]
            elif eff_wt:
                webhook_token_masked = '****'

            return jsonify({
                'risk_scores': config.get('risk_scores', {}),
                'thresholds': {
                    'high_risk_threshold': config.get('high_risk_threshold', 50),
                    'medium_risk_threshold': config.get('medium_risk_threshold', 25),
                },
                'house_affiliates': config.get('house_affiliates', []),
                'whitelisted_affiliates': config.get_whitelisted_affiliates(),
                'suspicious_names': config.get('suspicious_names', []),
                'major_providers': config.get('major_providers', []),
                'qa_billing_names': config.get('qa_billing_names', []),
                'whitelisted_card_fingerprints': config.get('whitelisted_card_fingerprints', []),
                'whitelisted_duids': config.get('whitelisted_duids', []),
                'whitelisted_ips': config.get('whitelisted_ips', []),
                'api_key_configured': bool(eff_api),
                'api_key_source': api_key_source,
                'api_key_masked': api_key_masked,
                'admin_api_configured': _admin_client_for_request() is not None,
                'admin_api_username': session_auth_status(session, app.config['SECRET_KEY']).get(
                    'username_preview', ''
                ),
                'scheduler_admin_configured': _scheduler_admin_configured(),
                'admin2_login_required': admin_login_required(),
                'webhook_ingest_configured': bool(eff_wt),
                'webhook_token_source': webhook_token_source,
                'webhook_token_masked': webhook_token_masked,
            })
        except Exception as e:
            logger.error(f"Error in /api/settings: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/admin-api/test')
    def api_test_admin_api():
        """Test admin API credentials — returns ok/error immediately."""
        try:
            client = _admin_client_for_request()
            if not client:
                return jsonify({
                    'ok': False,
                    'message': 'Not signed in to admin2. Sign in via the login prompt or Settings.',
                })
            ok, message = client.test_connection()
            return jsonify({'ok': ok, 'message': message})
        except Exception as exc:
            return jsonify({'ok': False, 'message': str(exc)}), 500

    @app.route('/api/settings', methods=['POST'])
    def api_update_settings():
        """Update settings"""
        try:
            data = request.get_json() or {}
            response_extra = {}

            if data.get('regenerate_webhook_token'):
                if (os.getenv('WEBHOOK_INGEST_TOKEN') or '').strip():
                    return jsonify({'error': 'Webhook token is set via WEBHOOK_INGEST_TOKEN; unset env to manage in UI.'}), 400
                new_tok = secrets.token_urlsafe(32)
                config.set('webhook_ingest_token', new_tok)
                config.save_config()
                response_extra['webhook_ingest_token'] = new_tok

            if isinstance(data.get('webhook_ingest_token'), str) and data['webhook_ingest_token'].strip():
                if (os.getenv('WEBHOOK_INGEST_TOKEN') or '').strip():
                    return jsonify({'error': 'Webhook token is set via WEBHOOK_INGEST_TOKEN; unset env to manage in UI.'}), 400
                config.set('webhook_ingest_token', data['webhook_ingest_token'].strip())
                config.save_config()

            if isinstance(data.get('api_key'), str) and data['api_key'].strip():
                config.set('api_key', data['api_key'].strip())
                config.save_config()
                app.api_client = APIClient(config.get_api_key())

            # Admin2: session login only (POST /api/auth/admin2/login). Env ADMIN_API_* is for scheduler.

            if 'risk_scores' in data:
                for key, value in data['risk_scores'].items():
                    if isinstance(value, (int, float)) and 0 <= value <= 100:
                        config.set(f'risk_scores.{key}', int(value))
            
            if 'thresholds' in data:
                for key, value in data['thresholds'].items():
                    if isinstance(value, (int, float)) and 0 <= value <= 100:
                        config.set(key, int(value))
            
            if 'suspicious_names' in data:
                names = [n.strip().lower() for n in data['suspicious_names'] if n.strip()]
                config.set('suspicious_names', names)

            if 'qa_billing_names' in data:
                names = [n.strip() for n in data['qa_billing_names'] if n.strip()]
                config.set('qa_billing_names', names)

            if 'whitelisted_card_fingerprints' in data:
                fps = [f.strip() for f in data['whitelisted_card_fingerprints'] if f and str(f).strip()]
                config.set('whitelisted_card_fingerprints', fps)

            if 'whitelisted_duids' in data:
                duids = []
                for d in data['whitelisted_duids']:
                    if not d:
                        continue
                    s = str(d).strip()
                    if s.isdigit():
                        duids.append(s)
                config.set('whitelisted_duids', duids)

            if 'whitelisted_affiliates' in data:
                from config import normalize_affiliate_code_list
                affiliates = normalize_affiliate_code_list(data['whitelisted_affiliates'])
                config.set('whitelisted_affiliates', affiliates)

            if 'whitelisted_ips' in data:
                import re
                ip_pattern = re.compile(r'^\d{1,3}(?:\.\d{1,3}){3}$')
                ips = [i.strip() for i in data['whitelisted_ips'] if i.strip() and ip_pattern.match(i.strip())]
                config.set('whitelisted_ips', ips)
            
            config.save()
            out = {'success': True}
            out.update(response_extra)
            return jsonify(out)
        except Exception as e:
            logger.error(f"Error in /api/settings POST: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/test-email', methods=['POST'])
    def api_test_email():
        """Score a single email without persisting (CLI parity)."""
        try:
            data = request.get_json() or {}
            email = (data.get('email') or '').strip()
            if not email or '@' not in email:
                return jsonify({'error': 'Valid email required'}), 400

            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
            from email_fraud_detector import EmailFraudDetector

            detector = EmailFraudDetector(config)
            out = detector.analyze_email(
                email,
                trans_datetime=data.get('trans_datetime'),
                pov_verified=data.get('pov_verified'),
                pov_verified_time=data.get('pov_verified_time'),
                ip_address=data.get('ip_address'),
                user_agent=data.get('user_agent'),
                first_name=data.get('first_name'),
                user1=data.get('user1'),
            )
            return jsonify(sanitize_for_json(out))
        except Exception as e:
            logger.error(f"Error in /api/test-email: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/logs')
    def api_logs():
        """Tail of fraud_detection.log (last N lines)."""
        try:
            lines = request.args.get('lines', '100')
            try:
                n = max(1, min(int(lines), 500))
            except (TypeError, ValueError):
                n = 100
            log_path = Path(os.getenv('FRAUD_DETECTION_LOG_PATH', 'fraud_detection.log')).resolve()
            if not log_path.is_file():
                return jsonify({'lines': [], 'path': str(log_path), 'message': 'Log file not found'})
            raw = log_path.read_text(encoding='utf-8', errors='replace').splitlines()
            tail = raw[-n:] if len(raw) > n else raw
            return jsonify({'lines': tail, 'path': str(log_path), 'total_lines': len(raw)})
        except Exception as e:
            logger.error(f"Error in /api/logs: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/webhook/activity')
    def api_webhook_activity():
        try:
            limit = request.args.get('limit', '20')
            try:
                lim = int(limit)
            except (TypeError, ValueError):
                lim = 20
            rows = db.get_recent_webhook_ingests(lim)
            return jsonify({'events': rows})
        except Exception as e:
            logger.error(f"Error in /api/webhook/activity: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/webhook/ingest', methods=['POST'])
    def api_webhook_ingest():
        """Push free/paid records; Bearer token auth."""
        auth = request.headers.get('Authorization', '') or ''
        token = ''
        if auth.lower().startswith('bearer '):
            token = auth[7:].strip()
        elif request.headers.get('X-Webhook-Token'):
            token = request.headers.get('X-Webhook-Token', '').strip()

        expected = config.get_webhook_ingest_token()
        if not expected:
            return jsonify({'error': 'Webhook ingest is not configured (set webhook_ingest_token or WEBHOOK_INGEST_TOKEN).'}), 503
        if not token or token != expected:
            return jsonify({'error': 'Unauthorized'}), 401

        try:
            body = request.get_json(force=True, silent=True)
            if not isinstance(body, dict):
                return jsonify({'error': 'JSON object required'}), 400

            analyze = bool(body.get('analyze', False))
            free_list = []
            paid_list = []

            if isinstance(body.get('records'), dict):
                free_list = body['records'].get('free') or []
                paid_list = body['records'].get('paid') or []
            elif isinstance(body.get('free'), list) or isinstance(body.get('paid'), list):
                free_list = body.get('free') or []
                paid_list = body.get('paid') or []
            elif body.get('type') in ('free', 'paid'):
                rec = body.get('records')
                if isinstance(rec, list):
                    chunk = rec
                elif isinstance(rec, dict):
                    chunk = [rec]
                else:
                    return jsonify({'error': 'When using type=free|paid, provide records array or object'}), 400
                if body['type'] == 'free':
                    free_list = chunk
                else:
                    paid_list = chunk
            else:
                return jsonify({
                    'error': 'Expected keys: {free:[], paid:[]} or {records:{free:[],paid:[]}} or {type, records}',
                }), 400

            if not isinstance(free_list, list):
                free_list = []
            if not isinstance(paid_list, list):
                paid_list = []

            total_in = len(free_list) + len(paid_list)
            if total_in > 5000:
                return jsonify({'error': 'Maximum 5000 records per request'}), 400

            fi, fd = db.insert_free_records(free_list) if free_list else (0, 0)
            pi, pd_ = db.insert_paid_records(paid_list) if paid_list else (0, 0)
            err_est = max(0, len(free_list) - fi - fd) + max(0, len(paid_list) - pi - pd_)

            summary = {
                'free_inserted': fi,
                'free_duplicates': fd,
                'paid_inserted': pi,
                'paid_duplicates': pd_,
                'analyze': analyze,
            }
            analysis_payload = None
            analyzed_count = 0

            if analyze and (free_list or paid_list):
                new_free_duids = [
                    str(r.get('duid') or r.get('DUID'))
                    for r in free_list
                    if r.get('duid') or r.get('DUID')
                ]
                new_paid_duids = [
                    str(r.get('duid') or r.get('DUID'))
                    for r in paid_list
                    if r.get('duid') or r.get('DUID')
                ]
                agg_results = []
                if new_free_duids:
                    df_f = db.get_records_by_duids('free', new_free_duids)
                    if not df_f.empty:
                        ar = _run_fraud_analysis_on_dataframe(db, config, 'free', df_f)
                        analyzed_count += ar.get('analyzed', 0)
                        agg_results.extend(ar.get('results') or [])
                if new_paid_duids:
                    df_p = db.get_records_by_duids('paid', new_paid_duids)
                    if not df_p.empty:
                        ar = _run_fraud_analysis_on_dataframe(db, config, 'paid', df_p)
                        analyzed_count += ar.get('analyzed', 0)
                        agg_results.extend(ar.get('results') or [])
                analysis_payload = {'results': agg_results, 'analyzed_count': analyzed_count}

            msg = f'ingest free={fi}/{len(free_list)} paid={pi}/{len(paid_list)} analyze={analyze}'
            db.log_webhook_ingest(
                free_inserted=fi,
                free_duplicates=fd,
                paid_inserted=pi,
                paid_duplicates=pd_,
                errors=err_est,
                analyzed_count=analyzed_count,
                message=msg,
            )

            out = dict(summary)
            if analysis_payload is not None:
                out['analysis'] = sanitize_for_json(analysis_payload)
            return jsonify(out)
        except Exception as e:
            logger.error(f"Webhook ingest error: {e}", exc_info=True)
            try:
                db.log_webhook_ingest(errors=1, message=f'error: {str(e)[:200]}')
            except Exception:
                pass
            return jsonify({'error': str(e)}), 500

    @app.route('/api/low-risk-samples')
    def api_low_risk_samples():
        """Get low-risk samples for review"""
        try:
            status = request.args.get('status', 'pending')
            df = db.get_low_risk_samples(status=status)
            if df is None or df.empty:
                return jsonify([])
            return jsonify(df.fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/low-risk-samples: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/low-risk-samples', methods=['POST'])
    def api_create_low_risk_sample():
        """Create new low-risk sample batch"""
        try:
            data = request.get_json()
            count = data.get('count', 20)
            max_risk = data.get('max_risk', 24)
            
            # Use the database's sample method
            df = db.sample_low_risk_accounts(count=count, max_risk=max_risk)
            
            if df is None or df.empty:
                return jsonify({'error': 'No low-risk records available for sampling'}), 400
            
            return jsonify({'success': True, 'count': len(df)})
        except Exception as e:
            logger.error(f"Error creating low-risk samples: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/low-risk-samples/<duid>/review', methods=['POST'])
    def api_review_low_risk_sample(duid):
        """Record low-risk sample review (missed_fraud or legitimate)."""
        try:
            data = request.get_json() or {}
            status = (data.get('status') or '').strip().lower()
            notes = data.get('notes') or 'Low-risk sample review'

            if status in ('confirmed_fraud', 'missed_fraud', 'fraud'):
                sample_status = 'missed_fraud'
                outcome = 'confirmed_fraud'
            elif status in ('false_positive', 'legitimate', 'ok'):
                sample_status = 'legitimate'
                outcome = 'false_positive'
            else:
                return jsonify({'error': 'status must be missed_fraud or legitimate'}), 400

            if not db.record_low_risk_review(duid, sample_status, notes):
                return jsonify({'error': 'Sample not found'}), 404

            # Also record outcome for effectiveness metrics when fraud_results row exists
            try:
                db.record_fraud_outcome(
                    duid=duid,
                    outcome=outcome,
                    notes=notes,
                    reviewed_by=data.get('reviewed_by'),
                )
            except Exception as exc:
                logger.warning("Low-risk sample outcome not recorded for %s: %s", duid, exc)

            return jsonify({'success': True, 'duid': duid, 'sample_status': sample_status})
        except Exception as e:
            logger.error(f"Error in /api/low-risk-samples/{duid}/review: {e}")
            return jsonify({'error': str(e)}), 500

    # ==================== ACTION ENDPOINTS ====================

    @app.route('/api/run-analysis', methods=['POST'])
    def api_run_analysis():
        """Run fraud detection analysis"""
        global _running_tasks
        
        # Check if already running (in-process or cross-process lease)
        if _running_tasks.get('analysis', {}).get('status') == 'running':
            return jsonify({'error': 'Analysis already running'}), 409

        stale_hours = float((config.get('scheduler') or {}).get('stale_run_hours', 12) or 12)
        lock_holder = f"web-analysis-{os.getpid()}"
        if not db.try_acquire_named_lock('pipeline', lock_holder, stale_hours=stale_hours, meta={'source': 'manual_web_analysis'}):
            return jsonify({'error': 'Pipeline already running (scheduler or another job holds the lock)'}), 409
        
        try:
            data = request.get_json() or {}
            analyze_all = bool(data.get('analyze_all', False))
            include_house = bool(data.get('include_house', False))  # Include house affiliates?
            
            # Extract date range
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            
            # Validate date range
            if start_date and end_date:
                try:
                    datetime.strptime(start_date, '%Y-%m-%d')
                    datetime.strptime(end_date, '%Y-%m-%d')
                except ValueError:
                    db.release_named_lock('pipeline', lock_holder)
                    return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
            
            # Extract filters
            filters = data.get('filters', {})
            filter_affiliates = filters.get('affiliates', []) if filters else []
            filter_campaigns = filters.get('campaigns', []) if filters else []
            
            # DEBUG: Log received filters
            logger.info(f"Analysis started with filters - Affiliates: {filter_affiliates}, Campaigns: {filter_campaigns}, Date range: {start_date} to {end_date}")
            
            # Validate filters
            if filter_affiliates and not isinstance(filter_affiliates, list):
                db.release_named_lock('pipeline', lock_holder)
                return jsonify({'error': 'filters.affiliates must be a list'}), 400
            if filter_campaigns and not isinstance(filter_campaigns, list):
                db.release_named_lock('pipeline', lock_holder)
                return jsonify({'error': 'filters.campaigns must be a list'}), 400

            analysis_admin_client = _admin_client_for_request()

            # Run in background thread
            def run_analysis():
                global _running_tasks
                _running_tasks['analysis'] = {
                    'status': 'running', 
                    'started': datetime.now().isoformat(),
                    'progress': 0
                }
                
                try:
                    # Import detector
                    sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
                    from email_fraud_detector import EmailFraudDetector
                    
                    results_summary = {'free': 0, 'paid': 0, 'high_risk': 0, 'house_skipped': 0, 'duid_filtered': 0}
                    high_th = int(config.get_risk_threshold('high') or 50)

                    skip_affiliate_lower = config.get_affiliate_analysis_skip_codes_lower(
                        include_house_in_analysis=include_house
                    )
                    
                    # Get DUID threshold
                    min_duid = config.get('min_duid_threshold', 0)
                    
                    # Use validated data types only
                    valid_types = ['free', 'paid']
                    import pandas as pd
                    for type_idx, data_type in enumerate(valid_types):
                        _running_tasks['analysis']['progress'] = int((type_idx / len(valid_types)) * 50)
                        _running_tasks['analysis']['current_type'] = data_type
                        
                        # Get data - use parameterized query via db method
                        if analyze_all:
                            # Safe: data_type is from hardcoded valid_types list
                            where_parts = []
                            params = []

                            # Add date range filter if specified
                            if start_date and end_date:
                                where_parts.append(db.SQL_TRANS_DATE_BETWEEN)
                                params.extend([start_date, end_date])

                            with db.get_connection() as conn:
                                # Push affiliate filter into SQL when re-analyzing so we
                                # don't load the entire table when only one affiliate is needed
                                if filter_affiliates:
                                    aff_col_sql = next(
                                        (c for c in ['webmaster_code', 'site_code']
                                         if c in pd.read_sql_query(
                                             f"PRAGMA table_info({data_type})", conn  # noqa: S608
                                         )['name'].tolist()),
                                        None
                                    )
                                    if aff_col_sql:
                                        placeholders = ','.join('?' * len(filter_affiliates))
                                        where_parts.append(f"LOWER({aff_col_sql}) IN ({placeholders})")
                                        params.extend(a.lower() for a in filter_affiliates)

                                query = f"SELECT * FROM {data_type}"  # noqa: S608
                                if where_parts:
                                    query += " WHERE " + " AND ".join(where_parts)

                                df = pd.read_sql_query(query, conn, params=params if params else None)
                        else:
                            df = db.get_unanalyzed_records(data_type)
                            
                            # Apply date filter to unanalyzed records
                            if start_date and end_date and not df.empty:
                                _day = pd.to_datetime(df['trans_datetime'], errors='coerce').dt.date
                                s_d = datetime.strptime(start_date, '%Y-%m-%d').date()
                                e_d = datetime.strptime(end_date, '%Y-%m-%d').date()
                                df = df[(_day >= s_d) & (_day <= e_d)]
                        
                        if df.empty:
                            continue
                        
                        # ============================================================
                        # APPLY AFFILIATE / CAMPAIGN FILTERS BEFORE PREPROCESSING
                        # (filter early so preprocessing count matches analyzed count)
                        # ============================================================
                        if filter_affiliates:
                            aff_col = next((c for c in ['webmaster_code', 'site_code'] if c in df.columns), None)
                            if aff_col:
                                norm_aff_filter = {a.lower() for a in filter_affiliates}
                                df = df[df[aff_col].astype(str).str.lower().isin(norm_aff_filter)]
                                if df.empty:
                                    continue

                        if filter_campaigns:
                            camp_col = next((c for c in ['campaign'] if c in df.columns), None)
                            if camp_col:
                                # Normalize both sides: strip trailing dots/spaces so that
                                # "346369" matches stored value "346369." from the API
                                norm_filter = {c.rstrip('. ').lower() for c in filter_campaigns}
                                df = df[df[camp_col].astype(str).str.rstrip('. ').str.lower().isin(norm_filter)]
                                if df.empty:
                                    continue

                        # Apply DUID threshold filter early too
                        if min_duid and min_duid > 0:
                            duid_col = next((c for c in ['duid', 'DUID'] if c in df.columns), None)
                            if duid_col:
                                df[duid_col] = pd.to_numeric(df[duid_col], errors='coerce')
                                df = df[df[duid_col].isna() | (df[duid_col] >= min_duid)]
                                if df.empty:
                                    continue

                        # Apply house + whitelisted affiliate filter early
                        if skip_affiliate_lower:
                            aff_col = next((c for c in ['webmaster_code', 'site_code'] if c in df.columns), None)
                            if aff_col:
                                df = df[~df[aff_col].astype(str).str.lower().isin(skip_affiliate_lower)]
                                if df.empty:
                                    continue

                        total_records = len(df)
                        
                        # ============================================================
                        # STEP 1: PREPROCESSING (Automatic Data Cleaning)
                        # ============================================================
                        sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
                        from data_preprocessor import DataPreprocessor
                        
                        preprocessor = DataPreprocessor()
                        df, quality_report = preprocessor.preprocess_batch(df)
                        
                        # Log preprocessing summary
                        if quality_report:
                            issues = quality_report.get('issues_fixed', 0)
                            if issues > 0:
                                logger.info(f"Preprocessing fixed {issues} data quality issues in {data_type} data")
                        
                        # ============================================================
                        # STEP 2: FRAUD DETECTION
                        # ============================================================
                        detector = EmailFraudDetector(config)
                        df = detector.normalize_column_names(df)
                        detector.build_repeated_word_map(df)
                        detector.build_geographic_cluster_maps(df)
                        detector.build_shared_ip_map(df, db=db)
                        detector.build_ip_velocity_map(df, db=db)
                        detector.build_gender_concentration_map(df)
                        detector.build_sequential_email_map(df)
                        detector.build_affiliate_domain_concentration_map(df)
                        
                        # Analyze
                        results = []
                        email_col = detector.column_map.get('email')
                        processed = 0
                        
                        for idx, row in df.iterrows():
                            processed += 1

                            _duid = detector.get_column(row, 'duid', None)
                            if _duid is None or str(_duid).strip() == '':
                                continue
                            
                            # Get affiliate code — try column_map first, then direct row access
                            webmaster_code = detector.get_column(row, 'webmaster_code', None)
                            if not webmaster_code:
                                for col in ['webmaster_code', 'site_code']:
                                    if col in row.index and pd.notna(row[col]) and row[col] != '':
                                        webmaster_code = row[col]
                                        break
                            campaign = detector.get_column(row, 'campaign', None)
                            if not campaign:
                                if 'campaign' in row.index and pd.notna(row['campaign']):
                                    campaign = row['campaign']
                            
                            # Pass ALL fields for complete fraud detection
                            analysis = detector.analyze_email(
                                row[email_col] if email_col else None,
                                trans_datetime=detector.get_column(row, 'trans_datetime', None),
                                pov_verified=detector.get_column(row, 'pov_verified', None),
                                pov_verified_time=detector.get_column(row, 'pov_verified_time', None),
                                ip_address=detector.get_column(row, 'ip', None),
                                user_agent=detector.get_column(row, 'custom_http_user_agent', None),
                                first_name=detector.get_column(row, 'first_name', None),
                                user1=(
                                    detector.get_column(row, 'custom_u1', None)
                                    or detector.get_column(row, 'user1', None)
                                ),
                            )
                            analysis['DUID'] = _duid
                            analysis['payout_amount'] = detector.get_column(row, 'payout_amount', 0)
                            analysis['data_type'] = data_type
                            analysis['webmaster_code'] = webmaster_code
                            analysis['campaign'] = campaign
                            analysis['ad_id'] = detector.get_column(row, 'ad_id', None)
                            # Store additional fields for re-analysis capability
                            analysis['trans_datetime'] = detector.get_column(row, 'trans_datetime', None)
                            analysis['pov_verified'] = detector.get_column(row, 'pov_verified', None)
                            analysis['pov_verified_time'] = detector.get_column(row, 'pov_verified_time', None)
                            analysis['user_agent'] = detector.get_column(row, 'custom_http_user_agent', None)
                            # geo_country: prefer source row value, fall back to what the IP lookup found
                            src_geo = detector.get_column(row, 'geo_country', None)
                            analysis['geo_country'] = src_geo or analysis.get('geo_country')
                            analysis['ip'] = detector.get_column(row, 'ip', None)
                            analysis['first_name'] = detector.get_column(row, 'first_name', None)
                            # custom_u1: paid uses 'custom_u1', free uses 'user1'
                            analysis['custom_u1'] = (
                                detector.get_column(row, 'custom_u1', None) or
                                detector.get_column(row, 'user1', None)
                            )
                            results.append(analysis)
                            
                            # Update progress every 100 records
                            if processed % 100 == 0:
                                base_progress = 50 if type_idx == 1 else 0
                                record_progress = int((processed / total_records) * 50)
                                _running_tasks['analysis']['progress'] = base_progress + record_progress
                                _running_tasks['analysis']['records_processed'] = len(results)
                        
                        detector.apply_gender_concentration_to_results(results)
                        detector.apply_sequential_email_to_results(results)
                        detector.apply_affiliate_domain_concentration_to_results(results)
                        # Save results
                        db.save_fraud_results(results)
                        
                        # Mark as analyzed
                        duids = [r['DUID'] for r in results if r.get('DUID') not in (None, '', 'N/A')]
                        if duids:
                            db.mark_as_analyzed(duids, data_type)
                        
                        results_summary[data_type] = len(results)
                        results_summary['high_risk'] += sum(1 for r in results if r['risk_score'] >= high_th)
                        
                        # Log filtering stats
                        if filter_affiliates or filter_campaigns:
                            logger.info(f"{data_type}: Total records: {total_records}, Analyzed: {len(results)}")
                    
                    _running_tasks['analysis'] = {
                        'status': 'completed',
                        'completed': datetime.now().isoformat(),
                        'results': results_summary,
                        'progress': 100
                    }
                    logger.info(f"Analysis completed: {results_summary}")

                    # Auto-trigger admin API enrichment pass if user is signed in to admin2
                    if analysis_admin_client:
                        try:
                            sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
                            from admin_enricher import AdminEnricher
                            _running_tasks['enrich'] = {
                                'status': 'running',
                                'started': datetime.now().isoformat(),
                                'total': 0, 'done': 0,
                                'enriched': 0, 'errors': 0,
                                'current_duid': None,
                                'auto': True,
                            }
                            def _auto_enrich():
                                global _running_tasks
                                try:
                                    enricher = AdminEnricher(
                                        db=db,
                                        client=analysis_admin_client,
                                        config=app.config_obj,
                                    )
                                    summary = enricher.run(
                                        limit=500,
                                        progress_cb=lambda p: _running_tasks['enrich'].update(p),
                                    )
                                    _running_tasks['enrich'] = {
                                        'status': 'completed',
                                        'completed': datetime.now().isoformat(),
                                        'auto': True,
                                        **summary,
                                    }
                                except Exception as _e:
                                    logger.warning(f"Auto-enrichment failed: {_e}")
                                    _running_tasks['enrich'] = {
                                        'status': 'error',
                                        'error': str(_e),
                                        'auto': True,
                                    }
                            threading.Thread(target=_auto_enrich, daemon=True).start()
                        except Exception as _imp_err:
                            logger.warning(f"Could not start auto-enrichment: {_imp_err}")
                    
                except Exception as e:
                    logger.error(f"Analysis error: {e}", exc_info=True)
                    _running_tasks['analysis'] = {'status': 'error', 'error': str(e), 'progress': 0}
                finally:
                    try:
                        db.release_named_lock('pipeline', lock_holder)
                    except Exception as lock_err:
                        logger.warning('Failed to release pipeline lock: %s', lock_err)
            
            thread = threading.Thread(target=run_analysis, daemon=True)
            thread.start()
            
            return jsonify({'status': 'started', 'message': 'Analysis started in background'})
            
        except Exception as e:
            try:
                db.release_named_lock('pipeline', lock_holder)
            except Exception:
                pass
            logger.error(f"Error starting analysis: {e}")
            return api_error('Failed to start analysis', 500, details=e)

    @app.route('/api/analysis-status')
    def api_analysis_status():
        """Get status of running analysis"""
        status = _running_tasks.get('analysis', {'status': 'idle'})
        return jsonify(status)

    @app.route('/api/fetch-data', methods=['POST'])
    def api_fetch_data():
        """Fetch data from API"""
        global _running_tasks
        
        if not app.api_client:
            return jsonify({'error': 'API client not configured. Set the affiliate API key in Settings.'}), 400
        
        # Check if already running
        if _running_tasks.get('fetch', {}).get('status') == 'running':
            return jsonify({'error': 'Fetch already running'}), 409

        stale_hours = float((config.get('scheduler') or {}).get('stale_run_hours', 12) or 12)
        lock_holder = f"web-fetch-{os.getpid()}"
        if not db.try_acquire_named_lock('pipeline', lock_holder, stale_hours=stale_hours, meta={'source': 'manual_web_fetch'}):
            return jsonify({'error': 'Pipeline already running (scheduler or another job holds the lock)'}), 409
        
        try:
            data = request.get_json() or {}
            data_type = data.get('data_type', 'both')
            
            # Validate data_type
            if not validate_data_type(data_type):
                db.release_named_lock('pipeline', lock_holder)
                return jsonify({'error': f'Invalid data_type. Must be one of: {", ".join(VALID_DATA_TYPES)}'}), 400
            
            # Validate and sanitize days
            try:
                days = int(data.get('days', 7))
                if days < 1 or days > 365:
                    db.release_named_lock('pipeline', lock_holder)
                    return jsonify({'error': 'days must be between 1 and 365'}), 400
            except (ValueError, TypeError):
                db.release_named_lock('pipeline', lock_holder)
                return jsonify({'error': 'days must be a valid integer'}), 400
            
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            # Override with custom dates if provided (validate format)
            if data.get('start_date'):
                try:
                    datetime.strptime(data['start_date'], '%Y-%m-%d')
                    start_date = data['start_date']
                except ValueError:
                    db.release_named_lock('pipeline', lock_holder)
                    return jsonify({'error': 'start_date must be in YYYY-MM-DD format'}), 400
            if data.get('end_date'):
                try:
                    datetime.strptime(data['end_date'], '%Y-%m-%d')
                    end_date = data['end_date']
                except ValueError:
                    db.release_named_lock('pipeline', lock_holder)
                    return jsonify({'error': 'end_date must be in YYYY-MM-DD format'}), 400
            
            # Extract and validate filters
            filters = data.get('filters', {})
            validated_filters = {}
            
            if filters.get('webmaster_code'):
                validated_filters['webmaster_code'] = sanitize_string(filters['webmaster_code'], 100)
            
            if filters.get('campaign'):
                validated_filters['campaign'] = sanitize_string(filters['campaign'], 100)
            
            def run_fetch():
                global _running_tasks
                
                try:
                    results_summary = {}
                    # Use validated data_type
                    data_types = ['free', 'paid'] if data_type == 'both' else [data_type]
                    
                    for idx, dt in enumerate(data_types):
                        _running_tasks['fetch']['progress'] = int((idx / len(data_types)) * 50)
                        _running_tasks['fetch']['current_type'] = dt
                        
                        try:
                            fetched = app.api_client.fetch_data(dt, start_date, end_date, validated_filters if validated_filters else None)
                        except Exception as fetch_err:
                            # Extract the API's error message from the response body if available
                            err_detail = str(fetch_err)
                            http_status = None
                            cause = getattr(fetch_err, 'response', None)
                            if cause is not None:
                                body = cause.text[:300] if cause.text else ''
                                http_status = cause.status_code
                                err_detail = f"HTTP {http_status} from API. Response: {body}"
                            logger.error(f"Fetch failed for {dt}: {err_detail}")
                            db.record_fetch(
                                dt,
                                start_date,
                                end_date,
                                0,
                                records_returned=0,
                                records_duplicates=0,
                                filters=validated_filters or None,
                                http_status=http_status,
                                error_message=err_detail,
                            )
                            results_summary[dt] = {
                                'fetched': 0, 'inserted': 0, 'duplicates': 0,
                                'error': err_detail
                            }
                            continue  # skip to next data type instead of aborting everything
                        
                        if fetched:
                            _running_tasks['fetch']['progress'] = 50 + int((idx / len(data_types)) * 50)
                            
                            if dt == 'paid':
                                inserted, duplicates = db.insert_paid_records(fetched)
                            else:
                                inserted, duplicates = db.insert_free_records(fetched)
                            
                            db.record_fetch(
                                dt,
                                start_date,
                                end_date,
                                inserted,
                                records_returned=len(fetched),
                                records_duplicates=duplicates,
                                filters=validated_filters or None,
                            )
                            results_summary[dt] = {
                                'fetched': len(fetched),
                                'inserted': inserted,
                                'duplicates': duplicates
                            }
                        else:
                            db.record_fetch(
                                dt,
                                start_date,
                                end_date,
                                0,
                                records_returned=0,
                                records_duplicates=0,
                                filters=validated_filters or None,
                            )
                            results_summary[dt] = {'fetched': 0, 'inserted': 0, 'duplicates': 0}
                    
                    # Mark completed even if some data types errored
                    any_error = any('error' in v for v in results_summary.values())
                    _running_tasks['fetch'] = {
                        'status': 'completed_with_errors' if any_error else 'completed',
                        'completed': datetime.now().isoformat(),
                        'results': results_summary,
                        'progress': 100
                    }
                    logger.info(f"Fetch completed: {results_summary}")
                    
                except Exception as e:
                    logger.error(f"Fetch error: {e}", exc_info=True)
                    _running_tasks['fetch'] = {'status': 'error', 'error': str(e), 'progress': 0}
                finally:
                    try:
                        db.release_named_lock('pipeline', lock_holder)
                    except Exception as lock_err:
                        logger.warning('Failed to release pipeline lock: %s', lock_err)
            
            # Set status to running BEFORE starting thread to avoid race condition
            _running_tasks['fetch'] = {
                'status': 'running',
                'started': datetime.now().isoformat(),
                'progress': 0
            }

            thread = threading.Thread(target=run_fetch, daemon=True)
            thread.start()
            
            return jsonify({
                'status': 'started',
                'message': f'Fetching {data_type} data from {start_date} to {end_date}'
            })
            
        except Exception as e:
            try:
                db.release_named_lock('pipeline', lock_holder)
            except Exception:
                pass
            logger.error(f"Error starting fetch: {e}")
            return api_error('Failed to start fetch', 500, details=e)

    @app.route('/api/fetch-status')
    def api_fetch_status():
        """Get status of running fetch"""
        status = _running_tasks.get('fetch', {'status': 'idle'})
        return jsonify(status)

    @app.route('/api/clear-task-status', methods=['POST'])
    def api_clear_task_status():
        """Clear completed task status"""
        global _running_tasks
        data = request.get_json() or {}
        task = sanitize_string(data.get('task', ''), 50)
        if task in _running_tasks:
            del _running_tasks[task]
        return jsonify({'status': 'ok'})

    # ==================== EXPORT ENDPOINTS ====================

    @app.route('/api/export/fraud-results')
    def api_export_fraud_results():
        """Export fraud results as CSV"""
        try:
            min_risk = request.args.get('min_risk', type=int)
            limit = request.args.get('limit', 10000, type=int)
            trans_date_from = sanitize_string(request.args.get('trans_date_from', ''), 10) or None
            trans_date_to = sanitize_string(request.args.get('trans_date_to', ''), 10) or None
            outcome = sanitize_string(request.args.get('outcome', ''), 50) or None
            exclude_reviewed = request.args.get('exclude_reviewed', '').lower() in ('1', 'true', 'yes')
            
            # Cap limit for performance
            limit = min(limit, 50000)
            
            df = db.get_fraud_results(
                min_risk=min_risk,
                limit=limit,
                exclude_reviewed=exclude_reviewed,
                outcome=outcome,
                analyzed_date_from=trans_date_from,
                analyzed_date_to=trans_date_to,
            )
            
            if df.empty:
                return jsonify({'error': 'No data to export'}), 404
            
            # Create CSV
            export_df = _fraud_export_columns(df)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            risk_suffix = f'_risk{min_risk}+' if min_risk else ''
            filename = f'fraud_results{risk_suffix}_{timestamp}.csv'
            return _csv_response(export_df, filename)
        except Exception as e:
            logger.error(f"Error exporting fraud results: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/export/flag-reference')
    def api_export_flag_reference():
        """Export fraud flag definitions for stakeholders (CSV, JSON, or Markdown)."""
        try:
            fmt = sanitize_string(request.args.get('format', 'csv'), 10).lower() or 'csv'
            if fmt not in ('csv', 'json', 'md', 'markdown'):
                return jsonify({'error': 'format must be csv, json, or md'}), 400
            if fmt == 'markdown':
                fmt = 'md'

            ctx = get_export_context()
            catalog = enrich_flag_reference_catalog(
                load_flag_reference_catalog(),
                ctx.get("risk_scores"),
                ctx,
            )
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            base = f'fraud_flags_reference_{timestamp}'

            if fmt == 'json':
                body = export_flag_reference_json(catalog)
                return Response(
                    body,
                    mimetype='application/json; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename={base}.json'},
                )
            if fmt == 'md':
                body = export_flag_reference_markdown(catalog)
                return Response(
                    body,
                    mimetype='text/markdown; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename={base}.md'},
                )
            body = export_flag_reference_csv(catalog)
            return Response(
                body,
                mimetype='text/csv; charset=utf-8',
                headers={'Content-Disposition': f'attachment; filename={base}.csv'},
            )
        except Exception as e:
            logger.error(f"Error exporting flag reference: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/flags/reference')
    def api_flags_reference():
        """JSON flag catalog (same data as export; uses live config risk scores)."""
        try:
            ctx = get_export_context()
            catalog = enrich_flag_reference_catalog(
                load_flag_reference_catalog(),
                ctx.get("risk_scores"),
                ctx,
            )
            return jsonify(catalog)
        except Exception as e:
            logger.error(f"Error loading flag reference: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/export/affiliates')
    def api_export_affiliates():
        """Export affiliate stats as CSV"""
        try:
            df = db.get_affiliate_fraud_stats()
            
            if df.empty:
                return jsonify({'error': 'No affiliate data to export'}), 404
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'affiliate_stats_{timestamp}.csv'
            return _csv_response(_prepare_export_df(df), filename)
        except Exception as e:
            logger.error(f"Error exporting affiliates: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/export/affiliate/<code>')
    def api_export_affiliate_details(code):
        """Export specific affiliate's fraud results as CSV"""
        try:
            # Sanitize affiliate code
            code = sanitize_string(code, 100)
            if not code:
                return jsonify({'error': 'Invalid affiliate code'}), 400
            
            df = db.get_fraud_by_affiliate(code, limit=10000)
            
            if df.empty:
                return jsonify({'error': 'No data found for this affiliate'}), 404
            
            export_df = _fraud_export_columns(df)

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_code = ''.join(c for c in code if c.isalnum() or c in '-_')[:30]
            filename = f'affiliate_{safe_code}_{timestamp}.csv'
            return _csv_response(export_df, filename)
        except Exception as e:
            logger.error(f"Error exporting affiliate {code}: {e}")
            return jsonify({'error': str(e)}), 500

    # ==================== FLAGS DASHBOARD ENDPOINTS ====================

    def _parse_flags_cell(flags_str):
        """Return list of raw flag strings from a fraud_results.flags cell."""
        return parse_flags_cell(flags_str)

    def _normalize_flags_for_export(flags_val):
        """
        Convert a flags cell (Python repr list, JSON array, or plain string) to a
        clean pipe-separated ASCII string safe for CSV export:
          - Strips list brackets and quote chars
          - Replaces Unicode arrow (→ / \\u2192) with plain ASCII '->'
          - No commas → no column-shifting in Excel/Sheets
        Returns '' for empty/null values.
        """
        flags = _parse_flags_cell(flags_val)
        if not flags:
            return ''
        cleaned = []
        for f in flags:
            s = str(f).strip().strip("'\"[]")
            s = s.replace('\u2192', '->').replace('→', '->')
            if s:
                cleaned.append(s)
        return ' | '.join(cleaned)

    FRAUD_EXPORT_BASE_COLS = [
        'duid', 'email', 'risk_score', 'flags', 'payout_amount',
        'data_type', 'webmaster_code', 'campaign', 'analyzed_at',
        'profile_image_uploaded', 'profile_image_upload_seconds',
        'admin_enriched', 'needs_content_review', 'review_url',
    ]

    AFFILIATE_EXPORT_BASE_COLS = [
        'duid', 'email', 'risk_score', 'payout_amount', 'trans_datetime',
        'campaign', 'ad_id', 'data_type', 'flags', 'review_outcome',
        'confirmed_fraud_payout', 'custom_u1', 'geo_country', 'ip',
        'profile_image_uploaded', 'profile_image_upload_seconds',
        'admin_enriched', 'needs_content_review', 'review_url',
    ]

    def _bool_export(val):
        if val is None or val == '':
            return ''
        try:
            return 'Y' if bool(int(val)) else 'N'
        except (TypeError, ValueError):
            return 'Y' if val else 'N'

    def _prepare_export_df(df):
        """Normalise columns that are unsafe for raw CSV export."""
        df = df.copy()
        fast_seconds = int(app.config_obj.get('profile_image_fast_seconds', 180) or 180)

        if 'flags' in df.columns:
            df['flags'] = df['flags'].apply(_normalize_flags_for_export)
        if 'details' in df.columns:
            df['details'] = df['details'].apply(
                lambda v: str(v).replace('\u2192', '->').replace('→', '->') if v else ''
            )

        if 'profile_image_uploaded' in df.columns:
            df['profile_image_uploaded'] = df['profile_image_uploaded'].apply(_bool_export)
        if 'admin_enriched' in df.columns:
            df['admin_enriched'] = df['admin_enriched'].apply(_bool_export)

        if 'needs_content_review' not in df.columns and 'duid' in df.columns:
            def _review_row(row):
                if has_content_review_flag(row.get('flags')):
                    return 'Y'
                return 'Y' if needs_content_review(
                    row.get('profile_image_uploaded'),
                    row.get('profile_image_upload_seconds'),
                    row.get('flags'),
                    fast_seconds=fast_seconds,
                ) else 'N'

            df['needs_content_review'] = df.apply(_review_row, axis=1)

        if 'review_url' not in df.columns and 'duid' in df.columns:
            df['review_url'] = df['duid'].apply(
                lambda d: f'/account/{d}' if d not in (None, '') else ''
            )

        return df

    def _fraud_export_columns(df):
        cols = [c for c in FRAUD_EXPORT_BASE_COLS if c in df.columns]
        return _prepare_export_df(df[cols])

    def _csv_response(df, filename):
        """Return a UTF-8 BOM CSV Response so Excel opens it correctly."""
        output = io.StringIO()
        df.to_csv(output, index=False, quoting=csv.QUOTE_ALL)
        content = '\ufeff' + output.getvalue()  # UTF-8 BOM tells Excel to use UTF-8
        return Response(
            content.encode('utf-8'),
            mimetype='text/csv; charset=utf-8',
            headers={'Content-Disposition': f'attachment; filename={filename}'}
        )

    def _normalize_flag_catalog_key(flag):
        """
        Map parameterized detection strings to a stable catalog key so the Flags
        tab lists ~tens of rules instead of hundreds (e.g. every geo pair / ASN name).
        """
        return normalize_flag_catalog_key(flag)

    def _row_matches_flag_catalog(flags_str, catalog_key):
        """True if this row should count for the Flags dashboard entry catalog_key."""
        return row_matches_flag_catalog(flags_str, catalog_key)

    @app.route('/api/flags/list')
    def api_flags_list():
        """Get unique flags with counts (catalog keys; parameterized variants merged)."""
        try:
            import pandas as pd
            from collections import Counter

            with db.get_connection() as conn:
                query = "SELECT flags FROM fraud_results WHERE flags IS NOT NULL AND flags != '' AND flags != '[]'"
                df = pd.read_sql_query(query, conn)

            flag_counts = Counter()

            for flags_str in df['flags']:
                for flag in _parse_flags_cell(flags_str):
                    flag_clean = str(flag).strip("[]' ")
                    if flag_clean:
                        flag_counts[_normalize_flag_catalog_key(flag_clean)] += 1

            flags_list = [{'flag': f, 'count': c} for f, c in flag_counts.most_common() if f]

            return jsonify({
                'flags': flags_list,
                'total_unique': len(flags_list)
            })
        except Exception as e:
            logger.error(f"Error in /api/flags/list: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/flags/<flag>/summary')
    def api_flag_summary(flag):
        """Get summary stats for a specific flag"""
        try:
            import pandas as pd

            flag = sanitize_string(flag, 100)
            if not flag:
                return jsonify({'error': 'Flag parameter required'}), 400

            with db.get_connection() as conn:
                # Get all records - we'll filter in Python since flags is JSON
                query = """
                    SELECT duid, email, risk_score, payout_amount, data_type,
                           webmaster_code, flags
                    FROM fraud_results
                    WHERE flags IS NOT NULL AND flags != '' AND flags != '[]'
                """
                df = pd.read_sql_query(query, conn)

            mask = df['flags'].apply(lambda x: _row_matches_flag_catalog(x, flag))
            filtered_df = df[mask]

            if filtered_df.empty:
                return jsonify({
                    'flag': flag,
                    'total_affected': 0,
                    'paid_count': 0,
                    'free_count': 0,
                    'avg_risk_score': 0,
                    'total_payout': 0,
                    'high_risk_count': 0,
                    'medium_risk_count': 0,
                    'low_risk_count': 0
                })

            # Calculate stats
            total = len(filtered_df)
            paid_count = len(filtered_df[filtered_df['data_type'] == 'paid'])
            free_count = len(filtered_df[filtered_df['data_type'] == 'free'])
            avg_risk = filtered_df['risk_score'].mean()
            total_payout = filtered_df['payout_amount'].sum()
            high_risk = len(filtered_df[filtered_df['risk_score'] >= 50])
            medium_risk = len(filtered_df[(filtered_df['risk_score'] >= 25) & (filtered_df['risk_score'] < 50)])
            low_risk = len(filtered_df[filtered_df['risk_score'] < 25])

            # Get outcome stats if available
            with db.get_connection() as conn:
                duids = filtered_df['duid'].tolist()
                if duids:
                    placeholders = ','.join(['?'] * len(duids))
                    outcome_query = f"""
                        SELECT outcome, COUNT(*) as count
                        FROM fraud_outcomes
                        WHERE duid IN ({placeholders})
                        GROUP BY outcome
                    """
                    outcome_df = pd.read_sql_query(outcome_query, conn, params=duids)
                    outcomes = dict(zip(outcome_df['outcome'], outcome_df['count']))
                else:
                    outcomes = {}

            return jsonify({
                'flag': flag,
                'total_affected': int(total),
                'paid_count': int(paid_count),
                'free_count': int(free_count),
                'paid_pct': round(paid_count / total * 100, 1) if total > 0 else 0,
                'free_pct': round(free_count / total * 100, 1) if total > 0 else 0,
                'avg_risk_score': round(float(avg_risk), 1),
                'total_payout': float(total_payout),
                'high_risk_count': int(high_risk),
                'medium_risk_count': int(medium_risk),
                'low_risk_count': int(low_risk),
                'outcomes': {
                    'confirmed_fraud': int(outcomes.get('confirmed_fraud', 0)),
                    'false_positive': int(outcomes.get('false_positive', 0)),
                    'under_review': int(outcomes.get('under_review', 0))
                }
            })
        except Exception as e:
            logger.error(f"Error in /api/flags/{flag}/summary: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/flags/<flag>/affiliates')
    def api_flag_affiliates(flag):
        """Get affiliate breakdown for a specific flag"""
        try:
            import pandas as pd

            flag = sanitize_string(flag, 100)
            if not flag:
                return jsonify({'error': 'Flag parameter required'}), 400

            with db.get_connection() as conn:
                query = """
                    SELECT duid, risk_score, payout_amount, data_type,
                           webmaster_code, flags
                    FROM fraud_results
                    WHERE flags IS NOT NULL AND flags != '' AND flags != '[]'
                      AND webmaster_code IS NOT NULL AND webmaster_code != ''
                """
                df = pd.read_sql_query(query, conn)

            mask = df['flags'].apply(lambda x: _row_matches_flag_catalog(x, flag))
            filtered_df = df[mask]

            if filtered_df.empty:
                return jsonify({'affiliates': [], 'total': 0})

            # Group by affiliate
            aff_stats = filtered_df.groupby('webmaster_code').agg({
                'duid': 'count',
                'risk_score': 'mean',
                'payout_amount': 'sum',
                'data_type': lambda x: (x == 'paid').sum()
            }).reset_index()

            aff_stats.columns = ['affiliate', 'count', 'avg_risk', 'total_payout', 'paid_count']
            aff_stats['free_count'] = aff_stats['count'] - aff_stats['paid_count']
            aff_stats = aff_stats.sort_values('count', ascending=False).head(50)

            affiliates = []
            for _, row in aff_stats.iterrows():
                affiliates.append({
                    'affiliate': row['affiliate'],
                    'count': int(row['count']),
                    'avg_risk': round(float(row['avg_risk']), 1),
                    'total_payout': float(row['total_payout']),
                    'paid_count': int(row['paid_count']),
                    'free_count': int(row['free_count']),
                    'paid_pct': round(row['paid_count'] / row['count'] * 100, 1) if row['count'] > 0 else 0
                })

            return jsonify({
                'affiliates': affiliates,
                'total': len(affiliates)
            })
        except Exception as e:
            logger.error(f"Error in /api/flags/{flag}/affiliates: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/flags/<flag>/accounts')
    def api_flag_accounts(flag):
        """Get paginated accounts affected by a specific flag"""
        try:
            import pandas as pd

            flag = sanitize_string(flag, 100)
            if not flag:
                return jsonify({'error': 'Flag parameter required'}), 400

            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 50, type=int)
            per_page = min(per_page, 100)  # Cap at 100
            data_type_filter = request.args.get('data_type', '')
            affiliate_filter = sanitize_string(request.args.get('affiliate', ''), 100)

            with db.get_connection() as conn:
                query = """
                    SELECT duid, email, risk_score, payout_amount, data_type,
                           webmaster_code, campaign, flags, analyzed_at
                    FROM fraud_results
                    WHERE flags IS NOT NULL AND flags != '' AND flags != '[]'
                """
                df = pd.read_sql_query(query, conn)

            mask = df['flags'].apply(lambda x: _row_matches_flag_catalog(x, flag))
            filtered_df = df[mask]

            # Apply additional filters
            if data_type_filter and data_type_filter in ['paid', 'free']:
                filtered_df = filtered_df[filtered_df['data_type'] == data_type_filter]

            if affiliate_filter:
                filtered_df = filtered_df[filtered_df['webmaster_code'] == affiliate_filter]

            # Sort by risk score desc
            filtered_df = filtered_df.sort_values('risk_score', ascending=False)

            total = len(filtered_df)
            total_pages = (total + per_page - 1) // per_page

            # Paginate
            start = (page - 1) * per_page
            end = start + per_page
            page_df = filtered_df.iloc[start:end]

            accounts = []
            for _, row in page_df.iterrows():
                accounts.append({
                    'duid': row['duid'],
                    'email': row['email'],
                    'risk_score': int(row['risk_score']) if pd.notna(row['risk_score']) else 0,
                    'payout_amount': float(row['payout_amount']) if pd.notna(row['payout_amount']) else 0,
                    'data_type': row['data_type'],
                    'affiliate': row['webmaster_code'],
                    'campaign': row['campaign'],
                    'flags': row['flags'],
                    'analyzed_at': row['analyzed_at']
                })

            return jsonify({
                'accounts': accounts,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': total_pages
            })
        except Exception as e:
            logger.error(f"Error in /api/flags/{flag}/accounts: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/flags/<flag>/cooccurrence')
    def api_flag_cooccurrence(flag):
        """Get flags that commonly appear alongside this flag"""
        try:
            import pandas as pd
            from collections import Counter

            flag = sanitize_string(flag, 100)
            if not flag:
                return jsonify({'error': 'Flag parameter required'}), 400

            with db.get_connection() as conn:
                query = "SELECT flags FROM fraud_results WHERE flags IS NOT NULL AND flags != '' AND flags != '[]'"
                df = pd.read_sql_query(query, conn)

            cooccurrence = Counter()
            total_with_flag = 0

            sel_cat = _normalize_flag_catalog_key(flag)
            sel_l = str(flag).strip("[]' ").lower()
            for flags_str in df['flags']:
                try:
                    clean_flags = [str(f).strip("[]' ") for f in _parse_flags_cell(flags_str) if str(f).strip("[]' ")]
                    if not clean_flags:
                        continue
                    if not any(
                        f.lower() == sel_l or _normalize_flag_catalog_key(f).lower() == sel_cat.lower()
                        for f in clean_flags
                    ):
                        continue
                    total_with_flag += 1
                    others = set()
                    for f in clean_flags:
                        if f.lower() == sel_l:
                            continue
                        if _normalize_flag_catalog_key(f).lower() == sel_cat.lower():
                            continue
                        others.add(_normalize_flag_catalog_key(f))
                    for o in others:
                        cooccurrence[o] += 1
                except Exception:
                    continue

            cooccur_list = []
            for co_flag, count in cooccurrence.most_common(15):
                cooccur_list.append({
                    'flag': co_flag,
                    'count': count,
                    'pct': round(count / total_with_flag * 100, 1) if total_with_flag > 0 else 0
                })

            return jsonify({
                'cooccurrence': cooccur_list,
                'total_with_flag': total_with_flag
            })
        except Exception as e:
            logger.error(f"Error in /api/flags/{flag}/cooccurrence: {e}")
            return jsonify({'error': str(e)}), 500

    # ==================== EXPLORE / EDA ENDPOINTS ====================

    @app.route('/api/explore/summary')
    def api_explore_summary():
        """Quick overview stats for the Explore dashboard"""
        try:
            import pandas as pd

            with db.get_connection() as conn:
                # Total records by table
                totals_query = """
                    SELECT
                        (SELECT COUNT(*) FROM fraud_results) as fraud_results_count,
                        (SELECT COUNT(*) FROM paid) as paid_count,
                        (SELECT COUNT(*) FROM free) as free_count
                """
                totals = pd.read_sql_query(totals_query, conn).iloc[0].to_dict()

                # Date range of data
                date_query = """
                    SELECT MIN(analyzed_at) as earliest, MAX(analyzed_at) as latest
                    FROM fraud_results
                """
                date_range = pd.read_sql_query(date_query, conn).iloc[0].to_dict()

                # Risk breakdown
                risk_query = """
                    SELECT
                        COUNT(CASE WHEN risk_score >= 50 THEN 1 END) as high_risk,
                        COUNT(CASE WHEN risk_score >= 25 AND risk_score < 50 THEN 1 END) as medium_risk,
                        COUNT(CASE WHEN risk_score < 25 THEN 1 END) as low_risk
                    FROM fraud_results
                """
                risk_breakdown = pd.read_sql_query(risk_query, conn).iloc[0].to_dict()

                # Outcome breakdown
                outcome_query = """
                    SELECT
                        COUNT(DISTINCT CASE WHEN fo.outcome = 'confirmed_fraud' THEN fo.duid END) as confirmed_fraud,
                        COUNT(DISTINCT CASE WHEN fo.outcome = 'false_positive' THEN fo.duid END) as false_positive,
                        COUNT(DISTINCT CASE WHEN fo.outcome = 'under_review' THEN fo.duid END) as under_review
                    FROM fraud_outcomes fo
                """
                outcomes = pd.read_sql_query(outcome_query, conn).iloc[0].to_dict()

                # Unreviewed count
                reviewed_duids = """
                    SELECT COUNT(*) as unreviewed
                    FROM fraud_results fr
                    WHERE NOT EXISTS (
                        SELECT 1 FROM fraud_outcomes fo WHERE fo.duid = fr.duid
                    )
                """
                unreviewed = pd.read_sql_query(reviewed_duids, conn).iloc[0]['unreviewed']

                # Data completeness score (% of key fields populated)
                completeness_query = """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN email IS NOT NULL AND email != '' THEN 1 ELSE 0 END) as has_email,
                        SUM(CASE WHEN duid IS NOT NULL AND duid != '' THEN 1 ELSE 0 END) as has_duid,
                        SUM(CASE WHEN risk_score IS NOT NULL THEN 1 ELSE 0 END) as has_risk,
                        SUM(CASE WHEN flags IS NOT NULL AND flags != '' AND flags != '[]' THEN 1 ELSE 0 END) as has_flags,
                        SUM(CASE WHEN payout_amount IS NOT NULL THEN 1 ELSE 0 END) as has_payout,
                        SUM(CASE WHEN webmaster_code IS NOT NULL AND webmaster_code != '' THEN 1 ELSE 0 END) as has_affiliate
                    FROM fraud_results
                """
                completeness = pd.read_sql_query(completeness_query, conn).iloc[0].to_dict()
                total = completeness.get('total') or 1
                completeness_score = round(
                    (completeness.get('has_email', 0) + completeness.get('has_duid', 0) +
                     completeness.get('has_risk', 0) + completeness.get('has_flags', 0) +
                     completeness.get('has_payout', 0) + completeness.get('has_affiliate', 0))
                    / (total * 6) * 100, 1
                )

                return jsonify({
                    'record_counts': {
                        'fraud_results': int(totals.get('fraud_results_count') or 0),
                        'paid': int(totals.get('paid_count') or 0),
                        'free': int(totals.get('free_count') or 0)
                    },
                    'date_range': {
                        'earliest': date_range.get('earliest'),
                        'latest': date_range.get('latest')
                    },
                    'risk_breakdown': {
                        'high': int(risk_breakdown.get('high_risk') or 0),
                        'medium': int(risk_breakdown.get('medium_risk') or 0),
                        'low': int(risk_breakdown.get('low_risk') or 0)
                    },
                    'outcome_breakdown': {
                        'confirmed_fraud': int(outcomes.get('confirmed_fraud') or 0),
                        'false_positive': int(outcomes.get('false_positive') or 0),
                        'under_review': int(outcomes.get('under_review') or 0),
                        'unreviewed': int(unreviewed or 0)
                    },
                    'completeness_score': completeness_score
                })
        except Exception as e:
            logger.error(f"Error in /api/explore/summary: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/explore/completeness')
    def api_explore_completeness():
        """Field-by-field data quality analysis"""
        try:
            import pandas as pd

            with db.get_connection() as conn:
                # Get completeness for each field
                query = """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN email IS NOT NULL AND email != '' THEN 1 ELSE 0 END) as email_filled,
                        SUM(CASE WHEN duid IS NOT NULL AND duid != '' THEN 1 ELSE 0 END) as duid_filled,
                        SUM(CASE WHEN risk_score IS NOT NULL THEN 1 ELSE 0 END) as risk_score_filled,
                        SUM(CASE WHEN flags IS NOT NULL AND flags != '' AND flags != '[]' THEN 1 ELSE 0 END) as flags_filled,
                        SUM(CASE WHEN payout_amount IS NOT NULL AND payout_amount > 0 THEN 1 ELSE 0 END) as payout_amount_filled,
                        SUM(CASE WHEN webmaster_code IS NOT NULL AND webmaster_code != '' THEN 1 ELSE 0 END) as webmaster_code_filled,
                        SUM(CASE WHEN campaign IS NOT NULL AND campaign != '' THEN 1 ELSE 0 END) as campaign_filled,
                        SUM(CASE WHEN data_type IS NOT NULL AND data_type != '' THEN 1 ELSE 0 END) as data_type_filled,
                        SUM(CASE WHEN ip IS NOT NULL AND ip != '' THEN 1 ELSE 0 END) as ip_filled,
                        SUM(CASE WHEN analyzed_at IS NOT NULL THEN 1 ELSE 0 END) as analyzed_at_filled
                    FROM fraud_results
                """
                result = pd.read_sql_query(query, conn).iloc[0].to_dict()

                total = result.get('total') or 1
                fields = []
                field_names = {
                    'email': 'Email',
                    'duid': 'DUID',
                    'risk_score': 'Risk Score',
                    'flags': 'Flags',
                    'payout_amount': 'Payout Amount',
                    'webmaster_code': 'Affiliate Code',
                    'campaign': 'Campaign',
                    'data_type': 'Data Type',
                    'ip': 'IP Address',
                    'analyzed_at': 'Analysis Date'
                }

                for key, label in field_names.items():
                    filled = result.get(f'{key}_filled', 0) or 0
                    missing = total - filled
                    pct = round(filled / total * 100, 1) if total > 0 else 0
                    fields.append({
                        'field': key,
                        'label': label,
                        'filled': int(filled),
                        'missing': int(missing),
                        'total': int(total),
                        'percent_complete': pct,
                        'quality': 'good' if pct >= 90 else 'warning' if pct >= 50 else 'poor'
                    })

                # Sort by completeness (worst first)
                fields.sort(key=lambda x: x['percent_complete'])

                return jsonify({
                    'fields': fields,
                    'total_records': int(total)
                })
        except Exception as e:
            logger.error(f"Error in /api/explore/completeness: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/explore/distributions')
    def api_explore_distributions():
        """Distribution analysis for selected fields"""
        try:
            import pandas as pd
            import numpy as np

            field = request.args.get('field', 'risk_score')

            # Whitelist of allowed fields
            allowed_fields = {'risk_score', 'payout_amount', 'data_type', 'flags'}
            if field not in allowed_fields:
                return jsonify({'error': f'Invalid field. Allowed: {", ".join(allowed_fields)}'}), 400

            with db.get_connection() as conn:
                if field in ['risk_score', 'payout_amount']:
                    # Numeric field - return histogram data
                    query = f"SELECT {field} FROM fraud_results WHERE {field} IS NOT NULL"
                    df = pd.read_sql_query(query, conn)

                    if df.empty:
                        return jsonify({'type': 'numeric', 'data': [], 'stats': {}})

                    values = df[field].dropna()

                    # Calculate histogram bins
                    if field == 'risk_score':
                        bins = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
                    else:
                        # Dynamic bins for payout
                        min_val = float(values.min())
                        max_val = float(values.max())
                        bins = list(np.linspace(min_val, max_val, 11))

                    hist, bin_edges = np.histogram(values, bins=bins)

                    histogram_data = []
                    for i in range(len(hist)):
                        histogram_data.append({
                            'bin_start': round(float(bin_edges[i]), 2),
                            'bin_end': round(float(bin_edges[i+1]), 2),
                            'count': int(hist[i]),
                            'label': f'{round(bin_edges[i])}-{round(bin_edges[i+1])}'
                        })

                    stats = {
                        'min': round(float(values.min()), 2),
                        'max': round(float(values.max()), 2),
                        'mean': round(float(values.mean()), 2),
                        'median': round(float(values.median()), 2),
                        'std': round(float(values.std()), 2),
                        'count': int(len(values))
                    }

                    return jsonify({
                        'type': 'numeric',
                        'field': field,
                        'histogram': histogram_data,
                        'stats': stats
                    })

                elif field == 'data_type':
                    # Categorical field - return value counts
                    query = """
                        SELECT data_type, COUNT(*) as count
                        FROM fraud_results
                        WHERE data_type IS NOT NULL AND data_type != ''
                        GROUP BY data_type
                        ORDER BY count DESC
                    """
                    df = pd.read_sql_query(query, conn)

                    total = df['count'].sum()
                    categories = []
                    for _, row in df.iterrows():
                        categories.append({
                            'value': row['data_type'],
                            'count': int(row['count']),
                            'percent': round(row['count'] / total * 100, 1) if total > 0 else 0
                        })

                    return jsonify({
                        'type': 'categorical',
                        'field': field,
                        'categories': categories,
                        'total': int(total)
                    })

                elif field == 'flags':
                    # Parse and count individual flags
                    query = "SELECT flags FROM fraud_results WHERE flags IS NOT NULL AND flags != '' AND flags != '[]'"
                    df = pd.read_sql_query(query, conn)

                    from collections import Counter
                    flag_counts = Counter()

                    for flags_str in df['flags']:
                        try:
                            if isinstance(flags_str, str):
                                flags_str = flags_str.replace("'", '"')
                                flags = json.loads(flags_str) if flags_str.startswith('[') else [flags_str]
                            else:
                                flags = flags_str if isinstance(flags_str, list) else []

                            for flag in flags:
                                flag_clean = str(flag).strip("[]' ")
                                if flag_clean:
                                    flag_counts[flag_clean] += 1
                        except:
                            continue

                    total = sum(flag_counts.values())
                    categories = []
                    for flag, count in flag_counts.most_common(20):
                        categories.append({
                            'value': flag,
                            'count': count,
                            'percent': round(count / total * 100, 1) if total > 0 else 0
                        })

                    return jsonify({
                        'type': 'categorical',
                        'field': field,
                        'categories': categories,
                        'total': int(total)
                    })

        except Exception as e:
            logger.error(f"Error in /api/explore/distributions: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/explore/correlations')
    def api_explore_correlations():
        """Flag effectiveness analysis"""
        try:
            import pandas as pd
            from collections import Counter

            with db.get_connection() as conn:
                # Get all reviewed outcomes with their flags and risk scores
                query = """
                    SELECT fo.outcome, fr.flags, fr.risk_score
                    FROM fraud_outcomes fo
                    JOIN fraud_results fr ON fo.duid = fr.duid
                    WHERE fo.outcome IN ('confirmed_fraud', 'false_positive')
                """
                df = pd.read_sql_query(query, conn)

                if df.empty:
                    return jsonify({
                        'flag_effectiveness': [],
                        'risk_bin_fraud_rate': [],
                        'total_reviewed': 0
                    })

                # Per-flag effectiveness
                flag_stats = {}
                for _, row in df.iterrows():
                    outcome = row['outcome']
                    flags_str = row['flags'] or '[]'

                    try:
                        if isinstance(flags_str, str):
                            flags_str = flags_str.replace("'", '"')
                            flags = json.loads(flags_str) if flags_str.startswith('[') else [flags_str]
                        else:
                            flags = flags_str if isinstance(flags_str, list) else []

                        for flag in flags:
                            flag_clean = str(flag).strip("[]' ")
                            if not flag_clean:
                                continue

                            if flag_clean not in flag_stats:
                                flag_stats[flag_clean] = {'total': 0, 'fraud': 0, 'fp': 0}

                            flag_stats[flag_clean]['total'] += 1
                            if outcome == 'confirmed_fraud':
                                flag_stats[flag_clean]['fraud'] += 1
                            else:
                                flag_stats[flag_clean]['fp'] += 1
                    except:
                        continue

                flag_effectiveness = []
                for flag, stats in flag_stats.items():
                    if stats['total'] >= 3:
                        precision = round(stats['fraud'] / stats['total'] * 100, 1) if stats['total'] > 0 else 0
                        strength = 'strong' if precision >= 70 else 'moderate' if precision >= 40 else 'weak'
                        flag_effectiveness.append({
                            'flag': flag,
                            'total_flagged': stats['total'],
                            'confirmed_fraud': stats['fraud'],
                            'false_positives': stats['fp'],
                            'precision': precision,
                            'strength': strength
                        })

                # Sort by precision (highest first)
                flag_effectiveness.sort(key=lambda x: x['precision'], reverse=True)

                # Risk score vs actual fraud rate by bin
                risk_bins = [
                    (0, 25, '0-24 (Low)'),
                    (25, 50, '25-49 (Medium)'),
                    (50, 75, '50-74 (High)'),
                    (75, 101, '75-100 (Critical)')
                ]

                risk_bin_fraud_rate = []
                for low, high, label in risk_bins:
                    bin_df = df[(df['risk_score'] >= low) & (df['risk_score'] < high)]
                    total = len(bin_df)
                    fraud = len(bin_df[bin_df['outcome'] == 'confirmed_fraud'])

                    risk_bin_fraud_rate.append({
                        'bin': label,
                        'total_reviewed': total,
                        'confirmed_fraud': fraud,
                        'fraud_rate': round(fraud / total * 100, 1) if total > 0 else 0
                    })

                return jsonify({
                    'flag_effectiveness': flag_effectiveness,
                    'risk_bin_fraud_rate': risk_bin_fraud_rate,
                    'total_reviewed': len(df)
                })
        except Exception as e:
            logger.error(f"Error in /api/explore/correlations: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/explore/outliers')
    def api_explore_outliers():
        """Anomaly detection"""
        try:
            import pandas as pd
            import numpy as np

            with db.get_connection() as conn:
                outliers = {
                    'payout_outliers': [],
                    'unusual_affiliates': [],
                    'flag_combinations': [],
                    'temporal_spikes': []
                }

                # 1. Payout outliers (z-score > 3)
                payout_query = """
                    SELECT duid, email, payout_amount, risk_score, webmaster_code
                    FROM fraud_results
                    WHERE payout_amount IS NOT NULL AND payout_amount > 0
                """
                payout_df = pd.read_sql_query(payout_query, conn)

                if not payout_df.empty and len(payout_df) > 10:
                    mean_payout = payout_df['payout_amount'].mean()
                    std_payout = payout_df['payout_amount'].std()

                    if std_payout > 0:
                        payout_df['z_score'] = (payout_df['payout_amount'] - mean_payout) / std_payout
                        high_outliers = payout_df[payout_df['z_score'] > 3].sort_values('z_score', ascending=False).head(10)

                        for _, row in high_outliers.iterrows():
                            outliers['payout_outliers'].append({
                                'duid': row['duid'],
                                'email': row['email'],
                                'payout_amount': float(row['payout_amount']),
                                'risk_score': int(row['risk_score']) if pd.notna(row['risk_score']) else None,
                                'z_score': round(float(row['z_score']), 2),
                                'affiliate': row['webmaster_code']
                            })

                # 2. Unusual affiliates (100% high-risk rate with min 5 accounts)
                affiliate_query = """
                    SELECT
                        webmaster_code,
                        COUNT(*) as total,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) as high_risk,
                        AVG(risk_score) as avg_risk,
                        SUM(payout_amount) as total_payout
                    FROM fraud_results
                    WHERE webmaster_code IS NOT NULL AND webmaster_code != ''
                    GROUP BY webmaster_code
                    HAVING total >= 5
                """
                aff_df = pd.read_sql_query(affiliate_query, conn)

                if not aff_df.empty:
                    aff_df['high_risk_pct'] = aff_df['high_risk'] / aff_df['total'] * 100
                    unusual_aff = aff_df[aff_df['high_risk_pct'] >= 80].sort_values('high_risk_pct', ascending=False).head(10)

                    for _, row in unusual_aff.iterrows():
                        outliers['unusual_affiliates'].append({
                            'affiliate': row['webmaster_code'],
                            'total_accounts': int(row['total']),
                            'high_risk_count': int(row['high_risk']),
                            'high_risk_pct': round(float(row['high_risk_pct']), 1),
                            'avg_risk': round(float(row['avg_risk']), 1),
                            'total_payout': float(row['total_payout'])
                        })

                # 3. Suspicious flag combinations (frequently co-occurring)
                flags_query = """
                    SELECT flags FROM fraud_results
                    WHERE flags IS NOT NULL AND flags != '' AND flags != '[]'
                    AND risk_score >= 50
                """
                flags_df = pd.read_sql_query(flags_query, conn)

                from collections import Counter
                combo_counts = Counter()

                for flags_str in flags_df['flags']:
                    try:
                        if isinstance(flags_str, str):
                            flags_str = flags_str.replace("'", '"')
                            flags = json.loads(flags_str) if flags_str.startswith('[') else [flags_str]
                        else:
                            flags = flags_str if isinstance(flags_str, list) else []

                        # Clean flags
                        clean_flags = [str(f).strip("[]' ") for f in flags if str(f).strip("[]' ")]

                        # Count pairs
                        if len(clean_flags) >= 2:
                            clean_flags.sort()
                            for i in range(len(clean_flags)):
                                for j in range(i+1, len(clean_flags)):
                                    combo = f"{clean_flags[i]} + {clean_flags[j]}"
                                    combo_counts[combo] += 1
                    except:
                        continue

                for combo, count in combo_counts.most_common(10):
                    if count >= 5:
                        outliers['flag_combinations'].append({
                            'combination': combo,
                            'count': count
                        })

                # 4. Temporal spikes (days with abnormal volume)
                temporal_query = """
                    SELECT DATE(analyzed_at) as date,
                           COUNT(*) as count,
                           SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) as high_risk
                    FROM fraud_results
                    WHERE analyzed_at >= DATE('now', '-30 days')
                    GROUP BY DATE(analyzed_at)
                    ORDER BY date
                """
                temporal_df = pd.read_sql_query(temporal_query, conn)

                if not temporal_df.empty and len(temporal_df) > 7:
                    mean_count = temporal_df['count'].mean()
                    std_count = temporal_df['count'].std()

                    if std_count > 0:
                        temporal_df['z_score'] = (temporal_df['count'] - mean_count) / std_count
                        spikes = temporal_df[temporal_df['z_score'] > 2].sort_values('z_score', ascending=False).head(5)

                        for _, row in spikes.iterrows():
                            outliers['temporal_spikes'].append({
                                'date': row['date'],
                                'count': int(row['count']),
                                'high_risk': int(row['high_risk']),
                                'z_score': round(float(row['z_score']), 2),
                                'vs_average': f"+{round((row['count'] - mean_count) / mean_count * 100)}%"
                            })

                return jsonify(outliers)
        except Exception as e:
            logger.error(f"Error in /api/explore/outliers: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/export/billing')
    def api_export_billing():
        """Export billing correlations as CSV"""
        try:
            df = db.get_billing_correlations(min_accounts=2)

            if df.empty:
                return jsonify({'error': 'No billing data to export'}), 404

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'billing_clusters_{timestamp}.csv'
            return _csv_response(_prepare_export_df(df), filename)
        except Exception as e:
            logger.error(f"Error exporting billing: {e}")
            return jsonify({'error': str(e)}), 500

    # ==================== EDA ENDPOINTS ====================
    
    @app.route('/api/eda/run', methods=['POST'])
    def api_run_eda():
        """Run EDA analysis with caching"""
        try:
            data = request.get_json() or {}
            data_type = data.get('data_type', 'free')
            start_date = data.get('start_date')
            end_date = data.get('end_date')
            affiliate = data.get('affiliate', '').strip() or None
            force_refresh = data.get('force_refresh', False)

            # Validate data type
            if data_type not in ['free', 'paid', 'fraud']:
                return jsonify({'error': 'Invalid data_type'}), 400

            # Sanitise affiliate code
            if affiliate:
                affiliate = sanitize_string(affiliate, 100)

            # ============================================================
            # CACHING LAYER
            # ============================================================
            import hashlib
            import json as json_lib

            # Generate cache key from parameters (affiliate-aware)
            cache_params = f"{data_type}_{start_date}_{end_date}_{affiliate or ''}"
            cache_key = hashlib.md5(cache_params.encode()).hexdigest()
            
            # Check cache if not forcing refresh
            if not force_refresh:
                try:
                    conn = sqlite3.connect(db.db_path)
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT result_json, created_at 
                        FROM eda_cache 
                        WHERE cache_key = ?
                        AND datetime(created_at) > datetime('now', '-1 hour')
                    """, (cache_key,))
                    
                    cached = cursor.fetchone()
                    conn.close()
                    
                    if cached:
                        logger.info(f"EDA cache hit: {cache_key}")
                        results = json_lib.loads(cached[0])
                        results['cached'] = True
                        results['cached_at'] = cached[1]
                        return jsonify(results)
                    
                except Exception as cache_err:
                    logger.warning(f"Cache lookup failed: {cache_err}")
            
            # ============================================================
            # RUN ANALYSIS (cache miss or force refresh)
            # ============================================================
            sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
            from eda_analyzer import EDAAnalyzer
            
            analyzer = EDAAnalyzer(db=db)
            results = analyzer.run_full_analysis(data_type, start_date, end_date, affiliate=affiliate)
            results = sanitize_for_json(results)
            results['cached'] = False
            
            # ============================================================
            # STORE IN CACHE
            # ============================================================
            try:
                conn = sqlite3.connect(db.db_path)
                cursor = conn.cursor()
                
                # Delete old cache for this key
                cursor.execute("DELETE FROM eda_cache WHERE cache_key = ?", (cache_key,))
                
                # Insert new cache
                cursor.execute("""
                    INSERT INTO eda_cache (cache_key, result_json, created_at)
                    VALUES (?, ?, datetime('now'))
                """, (cache_key, json_lib.dumps(results)))
                
                # Clean up old cache entries (older than 24 hours)
                cursor.execute("""
                    DELETE FROM eda_cache 
                    WHERE datetime(created_at) < datetime('now', '-24 hours')
                """)
                
                conn.commit()
                conn.close()
                logger.info(f"EDA results cached: {cache_key}")
                
            except Exception as cache_err:
                logger.warning(f"Failed to cache EDA results: {cache_err}")
            
            return jsonify(results)
            
        except Exception as e:
            logger.error(f"Error in /api/eda/run: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/eda/export-pdf', methods=['POST'])
    def api_eda_export_pdf():
        """Export EDA report as PDF"""
        try:
            data = request.get_json() or {}
            eda_results = data.get('results', {})
            dataset_type = data.get('dataset', 'combined')
            
            if not eda_results:
                return jsonify({'error': 'No EDA results provided'}), 400
            
            # Import PDF generator
            sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
            from pdf_generator import EDAReportGenerator
            
            # Generate filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"eda_report_{dataset_type}_{timestamp}.pdf"
            output_dir = Path(__file__).parent.parent / 'reports' / 'eda_reports'
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / filename
            
            # Generate PDF
            generator = EDAReportGenerator()
            pdf_path = generator.generate_pdf(eda_results, output_path, dataset_type)
            
            logger.info(f"Generated EDA PDF report: {pdf_path}")
            
            return jsonify({
                'success': True,
                'filename': filename,
                'path': str(pdf_path.relative_to(Path(__file__).parent.parent)),
                'message': 'PDF report generated successfully'
            })
            
        except Exception as e:
            logger.error(f"Error generating PDF: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
        except Exception as e:
            logger.error(f"Error in /api/eda/export-pdf: {e}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/eda/auto-flag-outliers', methods=['POST'])
    def api_auto_flag_outliers():
        """Auto-flag outliers for manual review"""
        try:
            data = request.get_json() or {}
            outliers = data.get('outliers', [])
            
            if not outliers:
                return jsonify({'error': 'No outliers provided'}), 400
            
            # Prepare bulk outcome data
            flagged_count = 0
            failed = []
            
            for outlier in outliers:
                duid = outlier.get('duid')
                email = outlier.get('email')
                reason = outlier.get('reason', 'Statistical outlier detected')
                
                if not duid:
                    failed.append({'email': email, 'reason': 'Missing DUID'})
                    continue
                
                try:
                    # Create a fraud outcome record with "review_needed" status
                    outcome_notes = f"Auto-flagged by EDA: {reason}"
                    
                    # Use existing database method
                    db.record_outcome(
                        duid=str(duid),
                        outcome='review_needed',
                        notes=outcome_notes
                    )
                    flagged_count += 1
                    
                except Exception as e:
                    failed.append({'duid': duid, 'email': email, 'reason': str(e)})
                    logger.error(f"Failed to flag outlier {duid}: {e}")
            
            response = {
                'flagged': flagged_count,
                'failed': len(failed),
                'details': failed if failed else None
            }
            
            logger.info(f"Auto-flagged {flagged_count} outliers for review")
            
            return jsonify(response)
            
        except Exception as e:
            logger.error(f"Error in /api/eda/auto-flag-outliers: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500
    
    # ==================== BUSINESS METRICS ENDPOINTS ====================
    
    def _sanitize_for_json(obj):
        """Convert numpy types to Python native types for JSON serialization"""
        import numpy as np
        if isinstance(obj, dict):
            return {k: _sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_sanitize_for_json(item) for item in obj]
        elif isinstance(obj, (np.bool_, np.bool8)):
            return bool(obj)
        elif isinstance(obj, (np.int_, np.intc, np.intp, np.int8, np.int16, np.int32, np.int64)):
            return int(obj)
        elif isinstance(obj, (np.float_, np.float16, np.float32, np.float64)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        else:
            return obj
    
    @app.route('/api/business/metrics')
    def api_business_metrics():
        """Get comprehensive business metrics"""
        try:
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            
            # Import business analytics
            sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
            from business_analytics import BusinessAnalytics
            
            analytics = BusinessAnalytics(db=db)
            metrics = analytics.get_all_metrics(start_date, end_date)
            
            # Sanitize numpy types for JSON serialization
            metrics = _sanitize_for_json(metrics)
            
            return jsonify(metrics)
        except Exception as e:
            logger.error(f"Error in /api/business/metrics: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/business/stakeholder/<stakeholder_type>')
    def api_stakeholder_metrics(stakeholder_type):
        """Get stakeholder-specific metrics"""
        try:
            if stakeholder_type not in ['finance', 'marketing', 'operations']:
                return jsonify({'error': 'Invalid stakeholder type'}), 400
            
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            
            sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
            from business_analytics import BusinessAnalytics
            
            analytics = BusinessAnalytics(db=db)
            metrics = analytics.get_stakeholder_metrics(stakeholder_type, start_date, end_date)
            
            # Sanitize numpy types for JSON serialization
            metrics = _sanitize_for_json(metrics)
            
            return jsonify(metrics)
        except Exception as e:
            logger.error(f"Error in /api/business/stakeholder: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    # ═══════════════════════════════════════════════════════════
    # PIPELINE SCHEDULER
    # ═══════════════════════════════════════════════════════════

    @app.route('/api/scheduler/status')
    def api_scheduler_status():
        try:
            return jsonify(app.scheduler.get_status())
        except Exception as e:
            logger.error(f"Error in /api/scheduler/status: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/scheduler/history')
    def api_scheduler_history():
        try:
            limit = min(int(request.args.get('limit', 20)), 100)
            return jsonify(app.scheduler.get_history(limit=limit))
        except Exception as e:
            logger.error(f"Error in /api/scheduler/history: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/scheduler/run', methods=['POST'])
    def api_scheduler_run():
        """Trigger an immediate pipeline run."""
        try:
            data = request.get_json() or {}
            days_back = max(1, min(int(data.get('days_back', 1)), 90))
            if app.scheduler.trigger_now(days_back=days_back):
                return jsonify({'status': 'started', 'days_back': days_back})
            return jsonify({'error': 'Could not start pipeline'}), 500
        except Exception as e:
            logger.error(f"Error in /api/scheduler/run: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/scheduler/configure', methods=['POST'])
    def api_scheduler_configure():
        """Update the schedule (enable/disable, time, lookback window)."""
        try:
            data = request.get_json() or {}
            enabled   = bool(data.get('enabled', False))
            hour      = max(0, min(int(data.get('hour', 14)), 23))
            minute    = max(0, min(int(data.get('minute', 0)), 59))
            days_back = max(1, min(int(data.get('days_back', 1)), 90))
            app.scheduler.update_schedule(
                enabled=enabled, hour=hour, minute=minute, days_back=days_back
            )
            extra_keys = (
                'startup_catchup', 'notify_macos',
                'startup_catchup_max_days', 'startup_catchup_after_hours',
                'catchup_skip_enrichment', 'catchup_chunk_days',
                'stale_after_hours',
                'enrich_after_pipeline', 'enrich_fresh_limit', 'enrich_backlog',
                'enrich_lookback_days', 'enrich_max_transient_attempts', 'enrich_health_check',
            )
            if any(k in data for k in extra_keys):
                merged = dict(app.config_obj.config.get('scheduler', {}))
                if 'startup_catchup' in data:
                    merged['startup_catchup'] = bool(data['startup_catchup'])
                if 'notify_macos' in data:
                    merged['notify_macos'] = bool(data['notify_macos'])
                if 'startup_catchup_max_days' in data:
                    merged['startup_catchup_max_days'] = max(
                        1, min(int(data['startup_catchup_max_days']), 90)
                    )
                if 'startup_catchup_after_hours' in data:
                    merged['startup_catchup_after_hours'] = max(
                        1.0, min(float(data['startup_catchup_after_hours']), 168.0)
                    )
                if 'catchup_skip_enrichment' in data:
                    merged['catchup_skip_enrichment'] = bool(data['catchup_skip_enrichment'])
                if 'catchup_chunk_days' in data:
                    merged['catchup_chunk_days'] = bool(data['catchup_chunk_days'])
                if 'stale_after_hours' in data:
                    merged['stale_after_hours'] = max(
                        1.0, min(float(data['stale_after_hours']), 24 * 90)
                    )
                if 'enrich_after_pipeline' in data:
                    merged['enrich_after_pipeline'] = bool(data['enrich_after_pipeline'])
                if 'enrich_fresh_limit' in data:
                    merged['enrich_fresh_limit'] = max(
                        0, min(int(data['enrich_fresh_limit']), 50_000)
                    )
                if isinstance(data.get('enrich_backlog'), dict):
                    eb = dict(merged.get('enrich_backlog') or {})
                    eb_in = data['enrich_backlog']
                    if 'enabled' in eb_in:
                        eb['enabled'] = bool(eb_in['enabled'])
                    if 'interval_minutes' in eb_in:
                        eb['interval_minutes'] = max(
                            1, min(int(eb_in['interval_minutes']), 24 * 60)
                        )
                    if 'batch_limit' in eb_in:
                        eb['batch_limit'] = max(
                            1, min(int(eb_in['batch_limit']), 50_000)
                        )
                    if 'throttle_seconds' in eb_in:
                        eb['throttle_seconds'] = max(
                            0.0, min(float(eb_in['throttle_seconds']), 60.0)
                        )
                    merged['enrich_backlog'] = eb
                if 'enrich_lookback_days' in data:
                    merged['enrich_lookback_days'] = max(
                        1, min(int(data['enrich_lookback_days']), 3650)
                    )
                if 'enrich_max_transient_attempts' in data:
                    merged['enrich_max_transient_attempts'] = max(
                        1, min(int(data['enrich_max_transient_attempts']), 50)
                    )
                if 'enrich_health_check' in data:
                    merged['enrich_health_check'] = bool(data['enrich_health_check'])
                app.config_obj.set('scheduler', merged)
                try:
                    app.scheduler._register_enrich_backlog_job()
                except Exception as reg_err:
                    logger.debug('Re-register enrich backlog: %s', reg_err)
            return jsonify({'status': 'ok', 'enabled': enabled,
                            'schedule': f'{hour:02d}:{minute:02d} UTC daily',
                            'days_back': days_back})
        except Exception as e:
            logger.error(f"Error in /api/scheduler/configure: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/scheduler/catchup-suggestion')
    def api_scheduler_catchup_suggestion():
        try:
            return jsonify(app.scheduler.compute_catchup_suggestion())
        except Exception as e:
            logger.error(f"Error in /api/scheduler/catchup-suggestion: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/scheduler/coverage')
    def api_scheduler_coverage():
        """Daily fetch/analysis coverage and missing-date detection."""
        try:
            return jsonify(app.scheduler.compute_coverage_health())
        except Exception as e:
            logger.error(f"Error in /api/scheduler/coverage: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/scheduler/reconciliation/day/<day>')
    def api_scheduler_reconciliation_day(day):
        """Affiliate-level MCP vs local reconciliation for one calendar day."""
        try:
            day = sanitize_string(day, 10)
            if len(day) != 10:
                return jsonify({'error': 'day must be YYYY-MM-DD'}), 400
            scripts_path = str(Path(__file__).resolve().parent.parent / 'scripts')
            if scripts_path not in sys.path:
                sys.path.insert(0, scripts_path)
            from source_reconciliation import build_source_client, reconcile_affiliates_for_day

            client = build_source_client(app.config_obj)
            payload = reconcile_affiliates_for_day(
                db, app.config_obj, client, day,
            )
            return jsonify(payload)
        except Exception as e:
            logger.error(f"Error in /api/scheduler/reconciliation/day/{day}: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/scheduler/run-day', methods=['POST'])
    def api_scheduler_run_day():
        """Fetch + analyze a single calendar day immediately."""
        try:
            data = request.get_json() or {}
            day = sanitize_string(data.get('day', ''), 10)
            if len(day) != 10:
                return jsonify({'error': 'day must be YYYY-MM-DD'}), 400
            if app.scheduler.trigger_day(day, trigger='manual'):
                return jsonify({'status': 'started', 'day': day})
            return jsonify({'error': 'Could not start pipeline'}), 500
        except Exception as e:
            logger.error(f"Error in /api/scheduler/run-day: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/scheduler/run-catchup', methods=['POST'])
    def api_scheduler_run_catchup():
        """Run a catch-up pipeline (run_type=catchup). Body: use_suggestion or days_back."""
        try:
            data = request.get_json() or {}
            if data.get('use_suggestion'):
                sug = app.scheduler.compute_catchup_suggestion()
                days = int(sug.get('days_back') or 0)
                if days < 1:
                    return jsonify({
                        'error': sug.get('message') or 'No catch-up needed',
                        'suggestion': sug,
                    }), 400
                if app.scheduler.trigger_catchup(days_back=days):
                    sched = app.config_obj.config.get('scheduler', {}) or {}
                    chunked = bool(sched.get('catchup_chunk_days', True)) and days > 1
                    return jsonify({
                        'status': 'started',
                        'days_back': days,
                        'chunked': chunked,
                        'suggestion': sug,
                    })
                return jsonify({'error': 'Could not start pipeline'}), 500
            days_back = max(1, min(int(data.get('days_back', 1)), 90))
            if app.scheduler.trigger_catchup(days_back=days_back):
                sched = app.config_obj.config.get('scheduler', {}) or {}
                chunked = bool(sched.get('catchup_chunk_days', True)) and days_back > 1
                return jsonify({
                    'status': 'started',
                    'days_back': days_back,
                    'chunked': chunked,
                })
            return jsonify({'error': 'Could not start pipeline'}), 500
        except Exception as e:
            logger.error(f"Error in /api/scheduler/run-catchup: {e}")
            return jsonify({'error': str(e)}), 500

    # ═══════════════════════════════════════════════════════════
    # AFFILIATE VALUE VS FRAUD MATRIX
    # ═══════════════════════════════════════════════════════════

    @app.route('/api/affiliate/value-fraud-matrix')
    def api_affiliate_value_fraud_matrix():
        """
        Per-affiliate: total payout (revenue proxy), fraud rate, and clean payout.
        Powers the 2×2 scatter plot and the ranked decision table.

        Integrates fraud_outcomes to show confirmed fraud rates and actioned status
        so already-reviewed affiliates are distinguished from ones needing attention.
        """
        try:
            import pandas as pd
            with db.get_connection() as conn:
                # Ensure resolution columns exist
                try:
                    conn.execute("ALTER TABLE fraud_outcomes ADD COLUMN resolution_status TEXT DEFAULT 'pending'")
                    conn.commit()
                except Exception:
                    pass

                df = pd.read_sql_query("""
                    SELECT
                        webmaster_code,
                        COUNT(*)                                                              AS total_accounts,
                        SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END)                    AS high_risk_count,
                        SUM(CASE WHEN risk_score < 50 THEN 1 ELSE 0 END)                     AS clean_count,
                        ROUND(AVG(risk_score), 1)                                             AS avg_risk_score,
                        COALESCE(SUM(payout_amount), 0)                                      AS total_payout,
                        COALESCE(SUM(CASE WHEN risk_score < 50 THEN payout_amount ELSE 0 END), 0) AS clean_payout,
                        COALESCE(SUM(CASE WHEN risk_score >= 50 THEN payout_amount ELSE 0 END), 0) AS fraud_payout,
                        ROUND(
                            100.0 * SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) / COUNT(*), 1
                        )                                                                     AS fraud_rate,
                        SUM(CASE WHEN analyzed_at IS NOT NULL
                                  AND datetime(analyzed_at) >= datetime('now', '-30 days')
                             THEN 1 ELSE 0 END)                                              AS accounts_30d,
                        SUM(CASE WHEN risk_score >= 50
                                  AND analyzed_at IS NOT NULL
                                  AND datetime(analyzed_at) >= datetime('now', '-30 days')
                             THEN 1 ELSE 0 END)                                              AS high_risk_30d
                    FROM fraud_results
                    WHERE webmaster_code IS NOT NULL AND webmaster_code != ''
                    GROUP BY webmaster_code
                    HAVING total_accounts >= 5
                    ORDER BY total_payout DESC
                """, conn)

                # Per-affiliate confirmed fraud outcomes (LEFT JOIN against fraud_results duid)
                outcomes_df = pd.read_sql_query("""
                    SELECT
                        fr.webmaster_code,
                        COUNT(fo.duid)                                                              AS reviewed_count,
                        SUM(CASE WHEN fo.outcome = 'confirmed_fraud' THEN 1 ELSE 0 END)            AS confirmed_count,
                        SUM(CASE WHEN fo.outcome IN ('false_positive','legitimate') THEN 1 ELSE 0 END) AS fp_count,
                        SUM(CASE WHEN fo.outcome = 'confirmed_fraud'
                                  AND COALESCE(fo.resolution_status,'pending') != 'pending'
                             THEN 1 ELSE 0 END)                                                     AS actioned_count
                    FROM fraud_results fr
                    JOIN fraud_outcomes fo ON fr.duid = fo.duid
                    WHERE fr.webmaster_code IS NOT NULL AND fr.webmaster_code != ''
                    GROUP BY fr.webmaster_code
                """, conn)

            if df.empty:
                return jsonify({'matrix': [], 'summary': {}})

            skip_affiliates = config.get_affiliate_analysis_skip_codes_lower(
                include_house_in_analysis=False
            )
            if skip_affiliates:
                df = df[~df['webmaster_code'].astype(str).str.strip().str.lower().isin(skip_affiliates)]

            if df.empty:
                return jsonify({'matrix': [], 'summary': {}})

            # Merge outcomes into main frame
            if not outcomes_df.empty:
                df = df.merge(outcomes_df, on='webmaster_code', how='left')
            else:
                df['reviewed_count'] = 0
                df['confirmed_count'] = 0
                df['fp_count']        = 0
                df['actioned_count']  = 0

            df[['reviewed_count', 'confirmed_count', 'fp_count', 'actioned_count']] = \
                df[['reviewed_count', 'confirmed_count', 'fp_count', 'actioned_count']].fillna(0).astype(int)

            df['accounts_30d'] = df['accounts_30d'].fillna(0).astype(int)
            df['high_risk_30d'] = df['high_risk_30d'].fillna(0).astype(int)
            MIN_30D_SAMPLE = 5

            def fraud_rate_30d(row):
                n = int(row['accounts_30d'])
                if n < MIN_30D_SAMPLE:
                    return None
                return round(100.0 * int(row['high_risk_30d']) / n, 1)

            df['fraud_rate_30d'] = df.apply(fraud_rate_30d, axis=1)

            # Confirmed fraud rate (only for affiliates with enough reviews)
            df['confirmed_rate'] = df.apply(
                lambda r: round(100.0 * r['confirmed_count'] / r['reviewed_count'], 1)
                          if r['reviewed_count'] >= 3 else None,
                axis=1
            )

            # Quadrant thresholds: median payout + median fraud rate (relative)
            med_payout     = float(df['total_payout'].median())
            med_fraud_rate = float(df['fraud_rate'].median())

            # Absolute confirmed-fraud threshold: ≥3 confirmed + confirmed_rate ≥ 40%
            CONFIRMED_FRAUD_THRESHOLD = 40.0
            CONFIRMED_MIN_REVIEWS     = 3

            def quadrant(row):
                # If affiliate has been actioned → show as 'actioned' (not noise)
                if row['actioned_count'] >= 1:
                    return 'actioned'

                high_val  = row['total_payout']  >= med_payout
                high_risk = row['fraud_rate']     >= med_fraud_rate

                # Absolute override: enough reviews and confirmed rate is high → always investigate
                confirmed_high = (
                    row['confirmed_count'] >= CONFIRMED_MIN_REVIEWS
                    and row['confirmed_rate'] is not None
                    and row['confirmed_rate'] >= CONFIRMED_FRAUD_THRESHOLD
                )
                if confirmed_high:
                    return 'investigate'

                if high_val and not high_risk:     return 'keep'
                if high_val and high_risk:         return 'investigate'
                if not high_val and not high_risk: return 'monitor'
                return 'review'

            df['quadrant'] = df.apply(quadrant, axis=1)

            signal_map = {
                'keep':        '✓ Keep',
                'investigate': '⚠ Investigate',
                'monitor':     '○ Monitor',
                'review':      '✗ Review',
                'actioned':    '✔ Actioned',
            }
            df['signal'] = df['quadrant'].map(signal_map)

            records = []
            for _, r in df.iterrows():
                records.append({
                    'webmaster_code':  r['webmaster_code'],
                    'total_accounts':  int(r['total_accounts']),
                    'high_risk_count': int(r['high_risk_count']),
                    'clean_count':     int(r['clean_count']),
                    'avg_risk_score':  float(r['avg_risk_score']),
                    'total_payout':    round(float(r['total_payout']), 2),
                    'clean_payout':    round(float(r['clean_payout']), 2),
                    'fraud_payout':    round(float(r['fraud_payout']), 2),
                    'fraud_rate':      float(r['fraud_rate']),
                    'reviewed_count':  int(r['reviewed_count']),
                    'confirmed_count': int(r['confirmed_count']),
                    'fp_count':        int(r['fp_count']),
                    'actioned_count':  int(r['actioned_count']),
                    'confirmed_rate':  r['confirmed_rate'],  # None if < 3 reviews
                    'accounts_30d':    int(r['accounts_30d']),
                    'high_risk_30d':   int(r['high_risk_30d']),
                    'fraud_rate_30d':  r['fraud_rate_30d'],
                    'quadrant':        r['quadrant'],
                    'signal':          r['signal'],
                })

            quad_counts = df['quadrant'].value_counts().to_dict()
            return jsonify(sanitize_for_json({
                'matrix': records,
                'thresholds': {
                    'median_payout':     round(med_payout, 2),
                    'median_fraud_rate': round(med_fraud_rate, 1),
                    'confirmed_fraud_threshold': CONFIRMED_FRAUD_THRESHOLD,
                    'confirmed_min_reviews':     CONFIRMED_MIN_REVIEWS,
                    'fraud_rate_30d_min_sample': MIN_30D_SAMPLE,
                },
                'summary': {
                    'keep':        int(quad_counts.get('keep', 0)),
                    'investigate': int(quad_counts.get('investigate', 0)),
                    'monitor':     int(quad_counts.get('monitor', 0)),
                    'review':      int(quad_counts.get('review', 0)),
                    'actioned':    int(quad_counts.get('actioned', 0)),
                    'total':       len(df),
                }
            }))
        except Exception as e:
            logger.error(f"Error in /api/affiliate/value-fraud-matrix: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/analytics/outcome-score-buckets')
    def api_outcome_score_buckets():
        """
        Reviewed accounts only: risk_score buckets vs fraud_outcomes.
        Use to sanity-check the high-risk threshold (e.g. 50) and tiering.
        """
        try:
            import pandas as pd

            with db.get_connection() as conn:
                df = pd.read_sql_query("""
                    SELECT fr.risk_score, fo.outcome
                    FROM fraud_results fr
                    INNER JOIN fraud_outcomes fo ON fr.duid = fo.duid
                """, conn)

            if df.empty:
                return jsonify({'buckets': [], 'totals': {'reviewed': 0}})

            def bucket_label(score):
                try:
                    s = int(score) if score is not None and not pd.isna(score) else 0
                except (TypeError, ValueError):
                    s = 0
                if s < 25:
                    return '0-24', 0
                if s < 50:
                    return '25-49', 1
                if s < 75:
                    return '50-74', 2
                if s < 100:
                    return '75-99', 3
                return '100+', 4

            rows = []
            for _, r in df.iterrows():
                label, order = bucket_label(r['risk_score'])
                rows.append({
                    'bucket': label,
                    'bucket_order': order,
                    'outcome': r['outcome'] or '',
                })
            bdf = pd.DataFrame(rows)
            bdf['is_confirmed'] = (bdf['outcome'] == 'confirmed_fraud').astype(int)
            bdf['is_fp'] = (bdf['outcome'] == 'false_positive').astype(int)
            bdf['is_legit'] = (bdf['outcome'] == 'legitimate').astype(int)
            bdf['is_review'] = (bdf['outcome'] == 'under_review').astype(int)

            g = bdf.groupby(['bucket', 'bucket_order'], sort=False)
            out = g.agg(
                reviewed=('outcome', 'count'),
                confirmed_fraud=('is_confirmed', 'sum'),
                false_positive=('is_fp', 'sum'),
                legitimate=('is_legit', 'sum'),
                under_review=('is_review', 'sum'),
            ).reset_index()
            out = out.sort_values('bucket_order')

            records = []
            for _, r in out.iterrows():
                n = int(r['reviewed'])
                cf = int(r['confirmed_fraud'])
                fp = int(r['false_positive'])
                lg = int(r['legitimate'])
                closed = cf + fp + lg
                records.append({
                    'bucket': r['bucket'],
                    'reviewed': n,
                    'confirmed_fraud': cf,
                    'false_positive': fp,
                    'legitimate': lg,
                    'under_review': int(r['under_review']),
                    'confirmed_rate': round(100.0 * cf / n, 1) if n else 0.0,
                    'precision_closed_pct': round(100.0 * cf / closed, 1) if closed else None,
                })

            totals = {
                'reviewed': int(len(df)),
                'confirmed_fraud': int((df['outcome'] == 'confirmed_fraud').sum()),
                'false_positive': int((df['outcome'] == 'false_positive').sum()),
                'legitimate': int((df['outcome'] == 'legitimate').sum()),
                'under_review': int((df['outcome'] == 'under_review').sum()),
            }
            return jsonify({'buckets': records, 'totals': totals})
        except Exception as e:
            logger.error(f"Error in /api/analytics/outcome-score-buckets: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/analytics/flag-outcome-precision')
    def api_flag_outcome_precision():
        """
        Per detection flag: outcome mix among reviewed accounts that had that flag.
        """
        try:
            import pandas as pd
            from email_fraud_detector import parse_fraud_results_flags

            with db.get_connection() as conn:
                df = pd.read_sql_query("""
                    SELECT fr.flags, fo.outcome
                    FROM fraud_results fr
                    INNER JOIN fraud_outcomes fo ON fr.duid = fo.duid
                """, conn)

            if df.empty:
                return jsonify({'flags': []})

            tally = {}
            for _, r in df.iterrows():
                outcome = r['outcome'] or ''
                for flag in parse_fraud_results_flags(r['flags']):
                    if not flag:
                        continue
                    key = str(flag).strip()
                    if not key:
                        continue
                    if key not in tally:
                        tally[key] = {
                            'confirmed_fraud': 0,
                            'false_positive': 0,
                            'legitimate': 0,
                            'under_review': 0,
                        }
                    if outcome == 'confirmed_fraud':
                        tally[key]['confirmed_fraud'] += 1
                    elif outcome == 'false_positive':
                        tally[key]['false_positive'] += 1
                    elif outcome == 'legitimate':
                        tally[key]['legitimate'] += 1
                    elif outcome == 'under_review':
                        tally[key]['under_review'] += 1

            records = []
            for flag, c in tally.items():
                n = sum(c.values())
                closed = c['confirmed_fraud'] + c['false_positive'] + c['legitimate']
                records.append({
                    'flag': flag,
                    'reviewed': n,
                    'confirmed_fraud': c['confirmed_fraud'],
                    'false_positive': c['false_positive'],
                    'legitimate': c['legitimate'],
                    'under_review': c['under_review'],
                    'confirmed_rate_pct': round(100.0 * c['confirmed_fraud'] / n, 1) if n else 0.0,
                    'precision_closed_pct': round(100.0 * c['confirmed_fraud'] / closed, 1) if closed else None,
                })

            records.sort(key=lambda x: (-x['reviewed'], x['flag']))
            return jsonify({'flags': records})
        except Exception as e:
            logger.error(f"Error in /api/analytics/flag-outcome-precision: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    # ═══════════════════════════════════════════════════════════
    # RESOLUTION TRACKING
    # ═══════════════════════════════════════════════════════════

    @app.route('/api/resolution/summary')
    def api_resolution_summary():
        """
        Close-the-loop metrics: of confirmed-fraud outcomes, how many were
        actioned (suspended / clawback requested / received)?
        """
        try:
            import pandas as pd
            with db.get_connection() as conn:
                # Ensure column exists (no-op if already there)
                try:
                    conn.execute("ALTER TABLE fraud_outcomes ADD COLUMN resolution_status TEXT DEFAULT 'pending'")
                    conn.execute("ALTER TABLE fraud_outcomes ADD COLUMN resolved_at TIMESTAMP")
                    conn.commit()
                except Exception:
                    pass  # columns already exist

                df = pd.read_sql_query("""
                    SELECT
                        outcome,
                        COALESCE(resolution_status, 'pending') AS resolution_status,
                        COUNT(*)              AS count,
                        COALESCE(SUM(payout_amount), 0) AS payout_sum,
                        COALESCE(SUM(recovery_amount), 0) AS recovered_sum
                    FROM fraud_outcomes
                    GROUP BY outcome, resolution_status
                    ORDER BY outcome, resolution_status
                """, conn)

                # Unresolved confirmed fraud (pending action)
                unresolved = pd.read_sql_query("""
                    SELECT fo.duid, fo.email, fo.risk_score, fo.payout_amount,
                           fo.reviewed_at,
                           COALESCE(fo.resolution_status, 'pending') AS resolution_status
                    FROM fraud_outcomes fo
                    WHERE fo.outcome = 'confirmed_fraud'
                      AND (fo.resolution_status IS NULL OR fo.resolution_status = 'pending')
                    ORDER BY fo.payout_amount DESC
                    LIMIT 50
                """, conn)

            # ── Summary metrics ───────────────────────────────────
            confirmed = df[df['outcome'] == 'confirmed_fraud']
            total_confirmed  = int(confirmed['count'].sum()) if not confirmed.empty else 0
            actioned_statuses = {'suspended', 'clawback_requested', 'clawback_received', 'no_action'}
            actioned = int(confirmed[confirmed['resolution_status'].isin(actioned_statuses)]['count'].sum()) if not confirmed.empty else 0
            suspended = int(confirmed[confirmed['resolution_status'] == 'suspended']['count'].sum()) if not confirmed.empty else 0
            clawback_req = int(confirmed[confirmed['resolution_status'] == 'clawback_requested']['count'].sum()) if not confirmed.empty else 0
            clawback_recv = int(confirmed[confirmed['resolution_status'] == 'clawback_received']['count'].sum()) if not confirmed.empty else 0
            total_recovered = float(confirmed['recovered_sum'].sum()) if not confirmed.empty else 0.0

            fp_df = df[df['outcome'] == 'false_positive']
            total_fp = int(fp_df['count'].sum()) if not fp_df.empty else 0
            fp_cleared = int(fp_df[fp_df['resolution_status'] == 'cleared']['count'].sum()) if not fp_df.empty else 0

            closure_rate = round(actioned / total_confirmed * 100, 1) if total_confirmed > 0 else 0.0

            return jsonify({
                'summary': {
                    'total_confirmed':   total_confirmed,
                    'actioned':          actioned,
                    'closure_rate':      closure_rate,
                    'suspended':         suspended,
                    'clawback_requested': clawback_req,
                    'clawback_received': clawback_recv,
                    'total_recovered':   round(total_recovered, 2),
                    'total_fp':          total_fp,
                    'fp_cleared':        fp_cleared,
                },
                'breakdown': df.fillna(0).to_dict(orient='records'),
                'unresolved': unresolved.fillna('').to_dict(orient='records'),
            })
        except Exception as e:
            logger.error(f"Error in /api/resolution/summary: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/resolution/update', methods=['POST'])
    def api_resolution_update():
        """Update the resolution_status for a confirmed-fraud outcome."""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'JSON body required'}), 400

            duid   = validate_duid(data.get('duid', ''))
            status = data.get('status', '').strip()

            VALID_RESOLUTION = {'pending', 'suspended', 'clawback_requested',
                                 'clawback_received', 'no_action', 'cleared', 'monitoring'}
            if not duid:
                return jsonify({'error': 'Invalid DUID'}), 400
            if status not in VALID_RESOLUTION:
                return jsonify({'error': f'Invalid status. Must be one of: {", ".join(sorted(VALID_RESOLUTION))}'}), 400

            recovery = float(data.get('recovery_amount', 0) or 0)

            with db.get_connection() as conn:
                conn.execute("""
                    UPDATE fraud_outcomes
                    SET resolution_status = ?,
                        resolved_at       = CURRENT_TIMESTAMP,
                        recovery_amount   = CASE WHEN ? > 0 THEN ? ELSE recovery_amount END
                    WHERE duid = ?
                """, (status, recovery, recovery, duid))
                conn.commit()

            logger.info(f"Resolution updated: {duid} -> {status}")
            return jsonify({'status': 'ok'})
        except Exception as e:
            logger.error(f"Error in /api/resolution/update: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    # ═══════════════════════════════════════════════════════════
    # FALSE POSITIVE COST
    # ═══════════════════════════════════════════════════════════

    @app.route('/api/false-positive-cost')
    def api_false_positive_cost():
        """Quantify the revenue impact of false positives (unified rule stats)."""
        try:
            insights = AnalysisInsights(db)
            return jsonify(insights.compute_fp_cost(**_analysis_filters_from_request()))
        except Exception as e:
            logger.error(f"Error in /api/false-positive-cost: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    return app


_dashboard_thread = None
_dashboard_running = False


def launch_dashboard(db, config, port=5050, open_browser=True, api_client=None):
    """
    Launch the Flask dashboard in a daemon thread.

    Returns True if started, False if already running.
    """
    global _dashboard_thread, _dashboard_running

    if _dashboard_running and _dashboard_thread and _dashboard_thread.is_alive():
        if open_browser:
            webbrowser.open(f'http://localhost:{port}')
        return False  # Already running

    app = create_app(db, config, api_client=api_client)

    def run_server():
        global _dashboard_running
        _dashboard_running = True
        try:
            app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)
        except Exception as e:
            logger.error(f"Dashboard server error: {e}")
        finally:
            _dashboard_running = False

    _dashboard_thread = threading.Thread(target=run_server, daemon=True)
    _dashboard_thread.start()

    if open_browser:
        # Small delay to let server start
        import time
        time.sleep(0.5)
        webbrowser.open(f'http://localhost:{port}')

    return True
