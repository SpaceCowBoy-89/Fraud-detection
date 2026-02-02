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
os.environ['WERKZEUG_RUN_MAIN'] = 'true'

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
            
            success = db.record_fraud_outcome(duid, outcome, notes=notes, reviewed_by='dashboard')
            if success:
                logger.info(f"Outcome recorded: {duid} -> {outcome}")
                return jsonify({'status': 'ok'})
            else:
                return jsonify({'error': 'Failed to record outcome. DUID may not exist.'}), 400
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
