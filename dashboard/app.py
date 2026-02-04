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
import secrets
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, jsonify, request, Response, session, g

# Suppress Flask dev server warning
logging.getLogger('werkzeug').setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

# Track background tasks
_running_tasks = {}

# Valid data types for validation
VALID_DATA_TYPES = {'free', 'paid', 'both'}
VALID_OUTCOMES = {'confirmed_fraud', 'false_positive', 'under_review'}


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


def create_app(db, config, api_client=None):
    """Flask app factory. Receives existing Database and Config instances."""
    app = Flask(__name__)
    app.config['JSON_SORT_KEYS'] = False
    app.config['SECRET_KEY'] = secrets.token_hex(32)
    
    # Store references for use in endpoints
    app.db = db
    app.config_obj = config
    app.api_client = api_client
    
    # Enable WAL mode on database for better concurrency
    try:
        with db.get_connection() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')  # Faster writes
            logger.info("Database WAL mode enabled")
    except Exception as e:
        logger.warning(f"Could not enable WAL mode: {e}")

    # ==================== MIDDLEWARE ====================

    @app.before_request
    def log_request():
        """Log incoming requests"""
        g.request_start = datetime.now()
        if request.path.startswith('/api/'):
            logger.debug(f"{request.method} {request.path}")

    @app.after_request
    def log_response(response):
        """Log response time for API calls"""
        if hasattr(g, 'request_start') and request.path.startswith('/api/'):
            elapsed = (datetime.now() - g.request_start).total_seconds() * 1000
            logger.debug(f"{request.path} completed in {elapsed:.1f}ms")
        return response

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Global error handler"""
        logger.error(f"Unhandled error on {request.path}: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({'error': 'Endpoint not found'}), 404

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({'error': 'Bad request', 'details': str(e)}), 400

    # ==================== ROUTES ====================

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/api/health')
    def health():
        """Health check endpoint"""
        return jsonify({
            'status': 'ok',
            'timestamp': datetime.now().isoformat(),
            'api_configured': app.api_client is not None,
            'db_connected': db is not None
        })

    @app.route('/api/search')
    def api_global_search():
        """Global search across all data"""
        try:
            query = request.args.get('q', '').strip()
            limit = request.args.get('limit', 50, type=int)
            
            if not query or len(query) < 2:
                return jsonify({'results': [], 'query': query})
            
            import pandas as pd
            results = []
            query_lower = query.lower()
            
            with db.get_connection() as conn:
                # Search fraud_results
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
                pattern = f'%{query_lower}%'
                df = pd.read_sql_query(fraud_query, conn, params=[pattern, pattern, pattern, pattern, limit])
                
                for _, row in df.iterrows():
                    results.append({
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
                'count': len(results)
            })
        except Exception as e:
            logger.error(f"Error in /api/search: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/account/<duid>')
    def api_account_details(duid):
        """Get comprehensive account details"""
        try:
            import pandas as pd
            duid = sanitize_string(duid, 100)
            
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
                
                # Get outcome history
                outcome_query = """
                    SELECT outcome, notes, recorded_at, recorded_by
                    FROM fraud_outcomes
                    WHERE duid = ?
                    ORDER BY recorded_at DESC
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
                
                # Clean up NaN values
                for key, value in account.items():
                    if pd.isna(value):
                        account[key] = None
                
                return jsonify({
                    'account': account,
                    'outcomes': outcomes,
                    'related_by_email': related_by_email,
                    'related_by_ip': related_by_ip
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
                
                # Confirmed fraud payout
                fraud_query = """
                    SELECT 
                        COUNT(DISTINCT fo.duid) as confirmed_fraud_count,
                        SUM(fr.payout_amount) as confirmed_fraud_payout
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
            return jsonify({'house_affiliates': house})
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
            limit = request.args.get('limit', 100, type=int)
            df = db.get_fraud_results(min_risk=min_risk, limit=limit)
            # Select safe columns that exist
            cols = [c for c in ['duid', 'email', 'risk_score', 'flags', 'payout_amount',
                                'data_type', 'analyzed_at', 'webmaster_code', 'campaign'] if c in df.columns]
            return jsonify(df[cols].fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/fraud-results: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/affiliates')
    def api_affiliates():
        try:
            df = db.get_affiliate_fraud_stats()
            return jsonify(df.fillna(0).to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/affiliates: {e}")
            return jsonify({'error': str(e)}), 500

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

    @app.route('/api/affiliate/<code>/details')
    def api_affiliate_details(code):
        try:
            df = db.get_fraud_by_affiliate(code, limit=200)
            cols = [c for c in ['duid', 'email', 'risk_score', 'flags', 'payout_amount',
                                'campaign', 'data_type'] if c in df.columns]
            return jsonify(df[cols].fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/affiliate/{code}/details: {e}")
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
            df = db.get_name_correlations(min_accounts=2)
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
                    LIMIT 100
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
                    LIMIT 100
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
                           fr.risk_score
                    FROM paid p
                    LEFT JOIN fraud_results fr ON p.duid = fr.duid
                    WHERE LOWER(p.first_name || ' ' || p.last_name) = LOWER(?)
                    ORDER BY fr.risk_score DESC NULLS LAST
                    LIMIT 100
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

    @app.route('/api/outcomes', methods=['POST'])
    def api_record_outcome():
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'JSON body required'}), 400
            
            duid = sanitize_string(data.get('duid', ''), 100)
            outcome = data.get('outcome')
            notes = sanitize_string(data.get('notes', ''), 1000)
            
            if not duid:
                return jsonify({'error': 'duid is required'}), 400
            
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

    @app.route('/api/pending-reviews')
    def api_pending_reviews():
        try:
            df = db.get_pending_reviews(min_risk=50, limit=50)
            cols = [c for c in ['duid', 'email', 'risk_score', 'flags', 'payout_amount',
                                'data_type', 'analyzed_at'] if c in df.columns]
            return jsonify(df[cols].fillna('').to_dict(orient='records'))
        except Exception as e:
            logger.error(f"Error in /api/pending-reviews: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/effectiveness')
    def api_effectiveness():
        try:
            metrics = db.get_effectiveness_metrics()
            return jsonify(metrics)
        except Exception as e:
            logger.error(f"Error in /api/effectiveness: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/fp-by-flag')
    def api_fp_by_flag():
        """Get false positive breakdown by flag"""
        try:
            import pandas as pd
            import json
            from collections import Counter
            
            with db.get_connection() as conn:
                # Get all reviewed outcomes with their flags
                query = """
                    SELECT fo.outcome, fr.flags, fr.risk_score
                    FROM fraud_outcomes fo
                    JOIN fraud_results fr ON fo.duid = fr.duid
                    WHERE fo.outcome IN ('confirmed_fraud', 'false_positive')
                """
                df = pd.read_sql_query(query, conn)
            
            if df.empty:
                return jsonify({'flags': [], 'summary': {'total_reviewed': 0, 'fp_count': 0, 'fraud_count': 0}})
            
            # Parse flags and count by outcome
            flag_stats = {}
            
            for _, row in df.iterrows():
                outcome = row['outcome']
                flags_str = row['flags'] or '[]'
                
                try:
                    # Parse flags
                    if isinstance(flags_str, str):
                        flags_str = flags_str.replace("'", '"')
                        flags = json.loads(flags_str) if flags_str.startswith('[') else [flags_str]
                    else:
                        flags = flags_str if isinstance(flags_str, list) else []
                    
                    for flag in flags:
                        flag = str(flag).strip("[]' ")
                        if not flag:
                            continue
                        
                        if flag not in flag_stats:
                            flag_stats[flag] = {'fraud': 0, 'fp': 0, 'total': 0}
                        
                        flag_stats[flag]['total'] += 1
                        if outcome == 'confirmed_fraud':
                            flag_stats[flag]['fraud'] += 1
                        else:
                            flag_stats[flag]['fp'] += 1
                except:
                    continue
            
            # Calculate FP rate per flag
            flags_data = []
            for flag, stats in flag_stats.items():
                if stats['total'] >= 3:  # Only show flags with enough data
                    fp_rate = round(stats['fp'] / stats['total'] * 100, 1) if stats['total'] > 0 else 0
                    flags_data.append({
                        'flag': flag,
                        'total': stats['total'],
                        'fraud_count': stats['fraud'],
                        'fp_count': stats['fp'],
                        'fp_rate': fp_rate,
                        'precision': round(100 - fp_rate, 1)
                    })
            
            # Sort by FP rate (highest first - worst performers)
            flags_data.sort(key=lambda x: x['fp_rate'], reverse=True)
            
            # Summary stats
            total_reviewed = len(df)
            fp_count = len(df[df['outcome'] == 'false_positive'])
            fraud_count = len(df[df['outcome'] == 'confirmed_fraud'])
            
            return jsonify({
                'flags': flags_data,
                'summary': {
                    'total_reviewed': total_reviewed,
                    'fp_count': fp_count,
                    'fraud_count': fraud_count,
                    'overall_fp_rate': round(fp_count / total_reviewed * 100, 1) if total_reviewed > 0 else 0,
                    'overall_precision': round(fraud_count / total_reviewed * 100, 1) if total_reviewed > 0 else 0
                }
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
        """Get pattern discovery data"""
        try:
            min_risk = request.args.get('min_risk', type=int)
            df = db.get_fraud_results(min_risk=min_risk)
            
            if df.empty:
                return jsonify({'flags': [], 'domains': [], 'risk_distribution': []})
            
            import json
            from collections import Counter
            
            # Flag frequency
            flag_counts = Counter()
            for flags_str in df['flags'].fillna('[]'):
                try:
                    if isinstance(flags_str, str):
                        # Handle various formats
                        flags_str = flags_str.replace("'", '"')
                        flags = json.loads(flags_str) if flags_str.startswith('[') else [flags_str]
                    else:
                        flags = flags_str if isinstance(flags_str, list) else []
                    for flag in flags:
                        if flag and flag != '[]':
                            flag_counts[str(flag).strip("[]' ")] += 1
                except:
                    continue
            
            flags_data = [{'flag': f, 'count': c, 'pct': round(c / len(df) * 100, 1)} 
                         for f, c in flag_counts.most_common(20)]
            
            # Email domain distribution
            domain_counts = Counter()
            for email in df['email'].fillna(''):
                if '@' in str(email):
                    domain = email.split('@')[1].lower()
                    domain_counts[domain] += 1
            
            domains_data = [{'domain': d, 'count': c, 'pct': round(c / len(df) * 100, 1)}
                          for d, c in domain_counts.most_common(15)]
            
            # Risk score distribution
            risk_bins = [0, 25, 50, 75, 100]
            risk_labels = ['0-24', '25-49', '50-74', '75-100']
            import pandas as pd
            df['risk_bin'] = pd.cut(df['risk_score'], bins=risk_bins, labels=risk_labels, include_lowest=True)
            risk_dist = df['risk_bin'].value_counts().to_dict()
            risk_data = [{'range': r, 'count': risk_dist.get(r, 0)} for r in risk_labels]
            
            return jsonify({
                'flags': flags_data,
                'domains': domains_data,
                'risk_distribution': risk_data,
                'total_records': len(df)
            })
        except Exception as e:
            logger.error(f"Error in /api/pattern-discovery: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/cluster-analysis')
    def api_cluster_analysis():
        """Get cluster analysis data"""
        try:
            df = db.get_fraud_results()
            
            if df.empty:
                return jsonify({'ip_clusters': [], 'domain_clusters': [], 'affiliate_clusters': []})
            
            from collections import Counter
            
            results = {}
            
            # IP clusters (accounts sharing same IP)
            if 'ip' in df.columns:
                ip_counts = df['ip'].value_counts()
                ip_clusters = ip_counts[ip_counts > 1].head(20)
                
                ip_data = []
                for ip, count in ip_clusters.items():
                    if ip and str(ip) not in ['', 'nan', 'None']:
                        ip_df = df[df['ip'] == ip]
                        ip_data.append({
                            'ip': str(ip),
                            'accounts': int(count),
                            'avg_risk': round(ip_df['risk_score'].mean(), 1),
                            'total_payout': float(ip_df['payout_amount'].sum()),
                            'high_risk': int((ip_df['risk_score'] >= 50).sum())
                        })
                results['ip_clusters'] = ip_data
            else:
                results['ip_clusters'] = []
            
            # Email domain clusters with risk
            domain_data = []
            for email in df['email'].fillna(''):
                if '@' in str(email):
                    domain = email.split('@')[1].lower()
                    df.loc[df['email'] == email, 'email_domain'] = domain
            
            if 'email_domain' in df.columns:
                domain_stats = df.groupby('email_domain').agg({
                    'duid': 'count',
                    'risk_score': 'mean',
                    'payout_amount': 'sum'
                }).reset_index()
                domain_stats.columns = ['domain', 'accounts', 'avg_risk', 'total_payout']
                domain_stats = domain_stats[domain_stats['accounts'] > 2].sort_values('avg_risk', ascending=False).head(15)
                results['domain_clusters'] = domain_stats.to_dict(orient='records')
            else:
                results['domain_clusters'] = []
            
            # Affiliate risk clusters
            if 'webmaster_code' in df.columns:
                aff_stats = df.groupby('webmaster_code').agg({
                    'duid': 'count',
                    'risk_score': 'mean',
                    'payout_amount': 'sum'
                }).reset_index()
                aff_stats.columns = ['affiliate', 'accounts', 'avg_risk', 'total_payout']
                aff_stats['high_risk_pct'] = df.groupby('webmaster_code').apply(
                    lambda x: (x['risk_score'] >= 50).sum() / len(x) * 100
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
        """Analyze which flags cause the most false positives"""
        try:
            import pandas as pd
            from collections import Counter

            with db.get_connection() as conn:
                # Get all outcomes with their flags
                query = """
                    SELECT fo.outcome, fr.flags, fr.risk_score
                    FROM fraud_outcomes fo
                    JOIN fraud_results fr ON fo.duid = fr.duid
                    WHERE fo.outcome IN ('confirmed_fraud', 'false_positive')
                """
                df = pd.read_sql_query(query, conn)

                if df.empty:
                    return jsonify({
                        'flag_analysis': [],
                        'total_reviewed': 0,
                        'precision_by_flag': []
                    })

                # Count flags by outcome
                fraud_flags = Counter()
                fp_flags = Counter()

                for _, row in df.iterrows():
                    try:
                        flags_str = row['flags']
                        if isinstance(flags_str, str):
                            flags_str = flags_str.replace("'", '"')
                            flags = json.loads(flags_str) if flags_str.startswith('[') else [flags_str]
                        else:
                            flags = flags_str if isinstance(flags_str, list) else []

                        for flag in flags:
                            if flag and flag != '[]':
                                flag_clean = str(flag).strip("[]' ")
                                if row['outcome'] == 'confirmed_fraud':
                                    fraud_flags[flag_clean] += 1
                                else:
                                    fp_flags[flag_clean] += 1
                    except:
                        continue

                # Calculate precision by flag
                all_flags = set(fraud_flags.keys()) | set(fp_flags.keys())
                flag_analysis = []
                for flag in all_flags:
                    fraud_count = fraud_flags.get(flag, 0)
                    fp_count = fp_flags.get(flag, 0)
                    total = fraud_count + fp_count
                    if total >= 3:  # Only include flags with enough data
                        precision = round(fraud_count / total * 100, 1) if total > 0 else 0
                        flag_analysis.append({
                            'flag': flag,
                            'fraud_count': fraud_count,
                            'fp_count': fp_count,
                            'total': total,
                            'precision': precision
                        })

                # Sort by worst precision (most FPs)
                flag_analysis.sort(key=lambda x: x['precision'])

                return jsonify({
                    'flag_analysis': flag_analysis,
                    'total_reviewed': len(df),
                    'total_fraud': len(df[df['outcome'] == 'confirmed_fraud']),
                    'total_fp': len(df[df['outcome'] == 'false_positive'])
                })
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
                        fo.duid, fo.outcome, fo.notes, fo.recorded_at,
                        fr.email, fr.risk_score, fr.payout_amount
                    FROM fraud_outcomes fo
                    LEFT JOIN fraud_results fr ON fo.duid = fr.duid
                    ORDER BY fo.recorded_at DESC
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
            return jsonify({
                'risk_scores': config.get('risk_scores', {}),
                'thresholds': {
                    'high_risk_threshold': config.get('high_risk_threshold', 50),
                    'medium_risk_threshold': config.get('medium_risk_threshold', 25),
                },
                'house_affiliates': config.get('house_affiliates', []),
                'whitelisted_affiliates': config.get('whitelisted_affiliates', []),
                'suspicious_names': config.get('suspicious_names', []),
                'major_providers': config.get('major_providers', []),
            })
        except Exception as e:
            logger.error(f"Error in /api/settings: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/settings', methods=['POST'])
    def api_update_settings():
        """Update settings"""
        try:
            data = request.get_json()
            
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
            
            if 'whitelisted_affiliates' in data:
                affiliates = [a.strip() for a in data['whitelisted_affiliates'] if a.strip()]
                config.set('whitelisted_affiliates', affiliates)
            
            config.save()
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"Error in /api/settings POST: {e}")
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

    # ==================== ACTION ENDPOINTS ====================

    @app.route('/api/run-analysis', methods=['POST'])
    def api_run_analysis():
        """Run fraud detection analysis"""
        global _running_tasks
        
        # Check if already running
        if _running_tasks.get('analysis', {}).get('status') == 'running':
            return jsonify({'error': 'Analysis already running'}), 409
        
        try:
            data = request.get_json() or {}
            analyze_all = bool(data.get('analyze_all', False))
            include_house = bool(data.get('include_house', False))  # Include house affiliates?
            
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
                    
                    results_summary = {'free': 0, 'paid': 0, 'high_risk': 0, 'house_skipped': 0}
                    
                    # Get house affiliates for filtering
                    house_affiliates = config.get_house_affiliates() if not include_house else []
                    house_affiliates_lower = set(h.lower() for h in house_affiliates if h)
                    
                    # Use validated data types only
                    valid_types = ['free', 'paid']
                    for type_idx, data_type in enumerate(valid_types):
                        _running_tasks['analysis']['progress'] = int((type_idx / len(valid_types)) * 50)
                        _running_tasks['analysis']['current_type'] = data_type
                        
                        # Get data - use parameterized query via db method
                        if analyze_all:
                            import pandas as pd
                            import sqlite3
                            conn = sqlite3.connect(db.db_path)
                            # Safe: data_type is from hardcoded valid_types list
                            df = pd.read_sql_query(f"SELECT * FROM {data_type}", conn)
                            conn.close()
                        else:
                            df = db.get_unanalyzed_records(data_type)
                        
                        if df.empty:
                            continue
                        
                        total_records = len(df)
                        
                        # Initialize detector
                        detector = EmailFraudDetector()
                        df = detector.normalize_column_names(df)
                        detector.build_repeated_word_map(df)
                        
                        # Analyze
                        results = []
                        email_col = detector.column_map.get('email')
                        processed = 0
                        
                        for idx, row in df.iterrows():
                            processed += 1
                            
                            # Get affiliate code
                            webmaster_code = detector.get_column(row, 'webmaster_code', None)
                            
                            # Skip house affiliates if not including
                            if house_affiliates_lower and webmaster_code:
                                if webmaster_code.lower() in house_affiliates_lower:
                                    results_summary['house_skipped'] += 1
                                    continue
                            
                            analysis = detector.analyze_email(row[email_col] if email_col else None)
                            analysis['DUID'] = detector.get_column(row, 'duid', 'N/A')
                            analysis['payout_amount'] = detector.get_column(row, 'payout_amount', 0)
                            analysis['data_type'] = data_type
                            analysis['webmaster_code'] = webmaster_code
                            analysis['campaign'] = detector.get_column(row, 'campaign', None)
                            results.append(analysis)
                            
                            # Update progress every 100 records
                            if processed % 100 == 0:
                                base_progress = 50 if type_idx == 1 else 0
                                record_progress = int((processed / total_records) * 50)
                                _running_tasks['analysis']['progress'] = base_progress + record_progress
                                _running_tasks['analysis']['records_processed'] = len(results)
                        
                        # Save results
                        db.save_fraud_results(results)
                        
                        # Mark as analyzed
                        duids = [r['DUID'] for r in results if r['DUID'] != 'N/A']
                        if duids:
                            db.mark_as_analyzed(duids, data_type)
                        
                        results_summary[data_type] = len(results)
                        results_summary['high_risk'] += sum(1 for r in results if r['risk_score'] >= 50)
                    
                    _running_tasks['analysis'] = {
                        'status': 'completed',
                        'completed': datetime.now().isoformat(),
                        'results': results_summary,
                        'progress': 100
                    }
                    logger.info(f"Analysis completed: {results_summary}")
                    
                except Exception as e:
                    logger.error(f"Analysis error: {e}", exc_info=True)
                    _running_tasks['analysis'] = {'status': 'error', 'error': str(e), 'progress': 0}
            
            thread = threading.Thread(target=run_analysis, daemon=True)
            thread.start()
            
            return jsonify({'status': 'started', 'message': 'Analysis started in background'})
            
        except Exception as e:
            logger.error(f"Error starting analysis: {e}")
            return jsonify({'error': str(e)}), 500

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
            return jsonify({'error': 'API client not configured. Set API key in CLI settings.'}), 400
        
        # Check if already running
        if _running_tasks.get('fetch', {}).get('status') == 'running':
            return jsonify({'error': 'Fetch already running'}), 409
        
        try:
            data = request.get_json() or {}
            data_type = data.get('data_type', 'both')
            
            # Validate data_type
            if not validate_data_type(data_type):
                return jsonify({'error': f'Invalid data_type. Must be one of: {", ".join(VALID_DATA_TYPES)}'}), 400
            
            # Validate and sanitize days
            try:
                days = int(data.get('days', 7))
                if days < 1 or days > 365:
                    return jsonify({'error': 'days must be between 1 and 365'}), 400
            except (ValueError, TypeError):
                return jsonify({'error': 'days must be a valid integer'}), 400
            
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            # Override with custom dates if provided (validate format)
            if data.get('start_date'):
                try:
                    datetime.strptime(data['start_date'], '%Y-%m-%d')
                    start_date = data['start_date']
                except ValueError:
                    return jsonify({'error': 'start_date must be in YYYY-MM-DD format'}), 400
            if data.get('end_date'):
                try:
                    datetime.strptime(data['end_date'], '%Y-%m-%d')
                    end_date = data['end_date']
                except ValueError:
                    return jsonify({'error': 'end_date must be in YYYY-MM-DD format'}), 400
            
            def run_fetch():
                global _running_tasks
                _running_tasks['fetch'] = {
                    'status': 'running', 
                    'started': datetime.now().isoformat(),
                    'progress': 0
                }
                
                try:
                    results_summary = {}
                    # Use validated data_type
                    data_types = ['free', 'paid'] if data_type == 'both' else [data_type]
                    
                    for idx, dt in enumerate(data_types):
                        _running_tasks['fetch']['progress'] = int((idx / len(data_types)) * 50)
                        _running_tasks['fetch']['current_type'] = dt
                        
                        fetched = app.api_client.fetch_data(dt, start_date, end_date)
                        
                        if fetched:
                            _running_tasks['fetch']['progress'] = 50 + int((idx / len(data_types)) * 50)
                            
                            if dt == 'paid':
                                inserted, duplicates = db.insert_paid_records(fetched)
                            else:
                                inserted, duplicates = db.insert_free_records(fetched)
                            
                            db.record_fetch(dt, start_date, end_date, inserted)
                            results_summary[dt] = {
                                'fetched': len(fetched),
                                'inserted': inserted,
                                'duplicates': duplicates
                            }
                        else:
                            results_summary[dt] = {'fetched': 0, 'inserted': 0, 'duplicates': 0}
                    
                    _running_tasks['fetch'] = {
                        'status': 'completed',
                        'completed': datetime.now().isoformat(),
                        'results': results_summary,
                        'progress': 100
                    }
                    logger.info(f"Fetch completed: {results_summary}")
                    
                except Exception as e:
                    logger.error(f"Fetch error: {e}", exc_info=True)
                    _running_tasks['fetch'] = {'status': 'error', 'error': str(e), 'progress': 0}
            
            thread = threading.Thread(target=run_fetch, daemon=True)
            thread.start()
            
            return jsonify({
                'status': 'started',
                'message': f'Fetching {data_type} data from {start_date} to {end_date}'
            })
            
        except Exception as e:
            logger.error(f"Error starting fetch: {e}")
            return jsonify({'error': str(e)}), 500

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
            
            # Cap limit for performance
            limit = min(limit, 50000)
            
            df = db.get_fraud_results(min_risk=min_risk, limit=limit)
            
            if df.empty:
                return jsonify({'error': 'No data to export'}), 404
            
            # Create CSV
            output = io.StringIO()
            cols = [c for c in ['duid', 'email', 'risk_score', 'flags', 'payout_amount',
                                'data_type', 'webmaster_code', 'campaign', 'analyzed_at'] if c in df.columns]
            df[cols].to_csv(output, index=False, quoting=csv.QUOTE_NONNUMERIC)
            
            # Generate filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            risk_suffix = f'_risk{min_risk}+' if min_risk else ''
            filename = f'fraud_results{risk_suffix}_{timestamp}.csv'
            
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename={filename}'}
            )
        except Exception as e:
            logger.error(f"Error exporting fraud results: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/export/affiliates')
    def api_export_affiliates():
        """Export affiliate stats as CSV"""
        try:
            df = db.get_affiliate_fraud_stats()
            
            if df.empty:
                return jsonify({'error': 'No affiliate data to export'}), 404
            
            output = io.StringIO()
            df.to_csv(output, index=False, quoting=csv.QUOTE_NONNUMERIC)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'affiliate_stats_{timestamp}.csv'
            
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename={filename}'}
            )
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
            
            output = io.StringIO()
            cols = [c for c in ['duid', 'email', 'risk_score', 'flags', 'payout_amount',
                                'campaign', 'data_type'] if c in df.columns]
            df[cols].to_csv(output, index=False, quoting=csv.QUOTE_NONNUMERIC)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            # Sanitize filename
            safe_code = ''.join(c for c in code if c.isalnum() or c in '-_')[:30]
            filename = f'affiliate_{safe_code}_{timestamp}.csv'
            
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename={filename}'}
            )
        except Exception as e:
            logger.error(f"Error exporting affiliate {code}: {e}")
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
            
            output = io.StringIO()
            df.to_csv(output, index=False, quoting=csv.QUOTE_NONNUMERIC)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'billing_clusters_{timestamp}.csv'
            
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename={filename}'}
            )
        except Exception as e:
            logger.error(f"Error exporting billing: {e}")
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
