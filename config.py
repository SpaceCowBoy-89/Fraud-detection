"""Configuration management for fraud detection system"""
import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    'api_key': '',
    # Bearer token for POST /api/webhook/ingest (override with WEBHOOK_INGEST_TOKEN env)
    'webhook_ingest_token': '',
    'risk_thresholds': {
        'high': 50,
        'medium': 25
    },
    'risk_scores': {
        # Email pattern scores
        'excessive_dots': 20,
        'digit_suffix': 15,
        'scrambled_pattern': 35,
        'name_number_pattern': 40,
        'written_number_pattern': 15,
        'repeated_word_pattern': 25,
        'suspicious_name': 30,
        
        # Billing/payment scores (paid records only)
        'billing_gender_mismatch': 35,
        # Email username name vs declared gender (user1)
        'gender_name_mismatch': 35,
        
        # POV timing scores
        'pov_instant_20s': 50,
        'pov_instant_40s': 40,
        'pov_fast_60s': 30,
        
        # IP velocity scores
        'ip_velocity_high': 30,
        'ip_velocity_medium': 5,
        'shared_ip_medium': 20,
        'shared_ip_high': 35,
        
        # Device scores
        'desktop_windows_10': 20,
        'desktop_other': 10,
        
        # Geographic clustering scores
        'us_state_cluster': 25,
        'us_city_state_cluster': 30,
        'intl_country_city_cluster': 30,
        
        # Theme clustering
        'theme_cluster': 15,

        # Per-affiliate domain concentration (see affiliate_domain_concentration_* keys below)
        'affiliate_domain_concentration': 20,
        # Baseline ~0.9% WOMAN. Flag triggers at >=15% (configurable in build_gender_concentration_map).
        'woman_concentration': 25,

        # Same username stem + domain, 4+ distinct numeric suffixes within one affiliate
        'sequential_email': 30,

        # Admin API enrichment scores (applied after initial analysis)
        # Profile image: set to 0 — not penalising absence or upload speed
        'no_profile_image': 0,
        'profile_image_instant': 0,  # legacy; fast upload uses profile_image_fast_seconds
        # Review-only flag when profile pic + fast upload or suspicious email patterns
        'content_review': 0,
        # Shared payment card across N accounts (excluding major issuers)
        'shared_card_3plus': 35,
        'shared_card_5plus': 50,
        # Login IP differs from registration IP — disabled: raw IP mismatch is not meaningful
        # (user may switch from mobile data to home WiFi). Geo-based rules below replace this.
        'ip_registration_login_mismatch': 0,
        # Email validated within 60s of account creation (most critical signal)
        'email_validated_60s': 50,
        'email_validated_120s': 30,
        # Amex card: essentially 0% baseline on dating sites — any use is suspicious
        'amex_card': 30,
        # Business card: inherently suspicious on a dating site
        'business_card': 40,
        # Discover concentration per affiliate: >10% is anomalous (baseline ~2%)
        # Applied as a post-enrichment pass across all enriched accounts
        'discover_concentration': 20,
        # Minimum % of an affiliate's accounts using Discover to trigger the flag
        'discover_concentration_threshold': 0.10,
        # Minimum number of enriched accounts an affiliate must have before
        # the Discover concentration rule is evaluated (avoids small-sample noise)
        'discover_concentration_min_sample': 10,
        # GeoIP-based IP signals (requires GeoLite2-City + GeoLite2-ASN databases)
        # Different US state between registration and login IP
        'ip_different_state': 15,
        # Different country between registration and login IP
        'ip_different_country': 35,
        # Login IP country differs from geo_country already in CSV data
        'geo_login_country_mismatch': 25,
        # Login IP resolves to a high-risk country (see high_risk_countries list)
        'login_high_risk_country': 30,
        # Registration or login IP belongs to a datacenter / cloud hosting provider
        'registration_ip_datacenter': 25,
        'login_ip_datacenter': 25,
        # Registration or login IP belongs to a known VPN / proxy / anonymizer
        'registration_ip_vpn': 20,
        'login_ip_vpn': 20,
    },
    'ip_velocity_threshold': 10,
    'repeated_word_threshold': 3,
    'whitelisted_affiliates': [],
    'house_affiliates': [],  # Internal/house affiliate codes to exclude from fraud analysis
    'qa_billing_names': [],  # Internal QA/tester full names to exclude from billing clusters
    # Admin API card_fingerprint values for internal test cards (excluded from shared-card scoring/UI)
    'whitelisted_card_fingerprints': [],
    # DUIDs used for QA / manual testing (excluded from shared-card signals list)
    'whitelisted_duids': [],
    'whitelisted_ips': [
        '73.167.181.87',     # QA testing IP — registrations and purchases
    ],
    # ISO 3166-1 alpha-2 country codes considered high-risk for dating site fraud
    'high_risk_countries': ['NG', 'GH', 'CI', 'CM', 'PH', 'RO', 'MD', 'ID'],
    # GeoIP database paths (relative to project root or absolute)
    # Download with: python3 scripts/download_geoip.py
    'geoip_city_db': 'data/GeoLite2-City.mmdb',
    'geoip_asn_db': 'data/GeoLite2-ASN.mmdb',
    'suspicious_names': ['fatima', 'muhammed'],
    # Common email providers — excluded from affiliate domain concentration monitoring
    'major_providers': [
        'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com',
        'aol.com', 'icloud.com', 'protonmail.com', 'mail.com',
        'privaterelay.appleid.com',
    ],
    # Apple Sign In, phone registration placeholders, etc. — local-part is system-generated
    'privacy_relay_domains': ['privaterelay.appleid.com', 'phone-registration.invalid'],
    # Domains excluded from affiliate-level domain concentration (gmail only by default)
    'affiliate_domain_concentration_exclude_domains': ['gmail.com'],
    'affiliate_domain_concentration_threshold': 0.05,
    'affiliate_domain_concentration_min_sample': 20,
    'admin_api': {
        'username': '',
        'password': '',
    },
    'database_path': 'affiliate_data.db',
    # Supervised ML (logistic regression on reviewed outcomes)
    'ml_model': {
        'min_labeled_samples': 30,
        'test_size': 0.2,
        'cv_folds': 5,
        'probability_threshold': 0.5,
        'models_dir': 'models',
        'random_state': 42,
    },
    'min_duid_threshold': 384046981,  # Nov 1, 2025 - filter accounts older than 3 months
    # Seconds after registration — profile pic uploaded faster than this triggers CONTENT_REVIEW
    'profile_image_fast_seconds': 180,
    'duid_reference': {
        'duid': 384046981,
        'date': '2025-11-01 00:02:00',
        'note': 'DUIDs increment by registration date. Use this to filter old accounts.'
    },
    # Scheduler (merged with user config.json; missing keys filled via _deep_merge)
    'scheduler': {
        'enabled': False,
        'hour': 14,
        'minute': 0,
        'days_back': 1,
        # After downtime: on app start, auto-run a catch-up if last completed pipeline is older than N hours
        'startup_catchup': True,
        'startup_catchup_max_days': 31,
        'startup_catchup_after_hours': 26,
        # Catch-up optimizations (see scheduler.py trigger_catchup / _run_catchup_chunked)
        'catchup_skip_enrichment': True,   # skip per-run admin enrich; use enrich_backlog job
        'catchup_chunk_days': True,        # multi-day catch-up runs one calendar day at a time
        # Health banner: flag stale only after this many hours without a completed run
        # (80h ≈ weekend + Monday morning; real outages beyond startup_catchup_max_days still surface)
        'stale_after_hours': 80,
        # macOS only: User Notifications for failures / stale schedule (set false to disable)
        'notify_macos': True,
        # After successful fetch+analyze: one quick admin API enrichment batch scoped to
        # this run (fresh high/medium risk first). Full drain uses enrich_backlog job.
        'enrich_after_pipeline': True,
        'enrich_fresh_limit': 500,
        # Unenriched rows must have trans_datetime within this many days of "today"
        # (aligns with admin API lookback) — older rows are excluded from enrichment queue.
        'enrich_lookback_days': 90,
        # After this many 401/403/5xx (non-404) failures, mark row closed as unavailable.
        'enrich_max_transient_attempts': 5,
        # If set (e.g. internal health URL or an endpoint that returns 2xx only on VPN), scheduled and
        # catchup pipelines wait until the probe succeeds — avoids 403 noise in pipeline_runs.
        # When empty and vpn_use_api_probe is true, uses affiliate API a=me as probe.
        # Example: hour 15 UTC ≈ 11:00 Eastern (EDT) if you connect VPN by 10:00 local.
        'vpn_probe_url': '',
        'vpn_use_api_probe': True,
        'vpn_probe_triggers': ['scheduled', 'catchup'],
        'vpn_probe_timeout': 8,
        'vpn_probe_method': 'get',  # 'get' or 'head'
        # Retry VPN/API probe before giving up (computer boot + VPN connect delay).
        'vpn_probe_retry_interval_seconds': 60,
        'vpn_probe_retry_max_minutes': 15,
        # Startup catch-up waits this long after app start, then waits for VPN before running.
        'startup_catchup_delay_seconds': 120,
        'startup_catchup_wait_for_vpn': True,
        # Daily coverage audit: detect zero-row calendar days and auto-fetch them.
        'coverage_audit': {
            'enabled': True,
            'lookback_days': 14,
            'interval_hours': 2,
            'min_neighbor_rows': 1000,
            'auto_fetch_missing': True,
            'detect_partial_days': True,
            'partial_fetch_ratio': 0.55,
            'partial_fetch_min_rows': 5000,
            'exclude_today_from_refetch': True,
        },
        # Drain unanalyzed free/paid rows on an interval (separate from fetch pipeline).
        'analysis_backlog': {
            'enabled': True,
            'interval_minutes': 10,
            'batch_limit': 15000,
            'lookback_days': 14,
            'priority': 'recent',
            'paid_first': True,
        },
        # After fetch+analyze, immediately drain remaining unanalyzed rows in the window.
        'immediate_drain_after_fetch': True,
        'immediate_drain_batch_limit': 5000,
        'immediate_drain_max_batches': 20,
        # MCP / PS7 source reconciliation (expected ES counts vs local fetch).
        'mcp_reconciliation': {
            'enabled': True,
            'after_fetch': True,
            'lookback_days': 90,
            'match_threshold_pct': 99.5,
            'block_analysis_on_partial': False,
            'exclude_today': True,
            'refresh_interval_hours': 6,
            'source': 'mcp_ps7_ht_signups',
            'elasticsearch_url': '',
            'elasticsearch_api_key': '',
            'mcp_url': '',
            'mcp_auth_env': 'CAMSODA_MCP_AUTH',
            'mcp_authorization': '',
            'index_pattern': 'ps7-ht-signups-{year}',
        },
        # Volume anomaly tab: MCP counts for detection, local for drill-down.
        'volume_anomalies': {
            'prefer_source_counts': True,
            'match_threshold_pct': 99.5,
            # Current calendar day is incomplete vs full-day baseline.
            'exclude_today': True,
        },
        # If true, run a one-shot admin API test before a batch; skip the batch on failure (e.g. VPN off).
        'enrich_health_check': True,
        # Periodic job: drain global unenriched fraud_results (date window via enrich_lookback_days).
        'enrich_backlog': {
            'enabled': True,
            'interval_minutes': 15,
            'batch_limit': 2000,
            'throttle_seconds': 0.25,
        },
    },
}


def _deep_merge(base, override):
    """Recursively merge override into base (dicts only). Lists and scalars are replaced."""
    if not isinstance(base, dict):
        return override
    result = dict(base)
    for k, v in (override or {}).items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def normalize_affiliate_code_list(entries):
    """Split affiliate codes on newlines and commas (one code per token)."""
    out = []
    seen_lower = set()
    for entry in entries or []:
        if entry is None:
            continue
        for part in str(entry).replace(',', '\n').split('\n'):
            code = part.strip()
            if not code:
                continue
            key = code.lower()
            if key in seen_lower:
                continue
            seen_lower.add(key)
            out.append(code)
    return out


class Config:
    def __init__(self, config_path='config.json'):
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self):
        """Load configuration from file or create default"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                return _deep_merge(DEFAULT_CONFIG, config)
            except Exception as e:
                print(f"Error loading config: {e}")
                return DEFAULT_CONFIG.copy()
        else:
            # Create default config file
            self.save_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()

    def save_config(self, config=None):
        """Save configuration to file"""
        if config is None:
            config = self.config

        try:
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def save(self):
        """Alias for save_config (used by dashboard routes)."""
        return self.save_config()

    def get(self, key, default=None):
        """Get configuration value"""
        keys = key.split('.')
        value = self.config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key, value):
        """Set configuration value"""
        keys = key.split('.')

        # Navigate to the nested location
        current = self.config
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]

        # Set the value
        current[keys[-1]] = value

        # Save to file
        return self.save_config()

    def get_api_key(self):
        """Get API key from config or environment"""
        api_key = self.get('api_key')

        if not api_key:
            # Try environment variable
            api_key = os.getenv('FRAUD_DETECTION_API_KEY')

        return api_key

    def set_api_key(self, api_key):
        """Set API key"""
        return self.set('api_key', api_key)

    def get_admin_api_credentials(self):
        """Return (username, password) for scheduler/CLI admin enrichment (env or config).

        The web dashboard uses per-user session login (POST /api/auth/admin2/login), not this.
        """
        section = self.get('admin_api', {})
        username = (section.get('username') or os.getenv('ADMIN_API_USERNAME') or '').strip()
        password = (section.get('password') or os.getenv('ADMIN_API_PASSWORD') or '').strip()
        return username, password

    def set_admin_api_credentials(self, username, password):
        return self.set('admin_api', {'username': username, 'password': password})

    def get_webhook_ingest_token(self):
        """Token for webhook ingest; env WEBHOOK_INGEST_TOKEN wins over config file."""
        tok = os.getenv('WEBHOOK_INGEST_TOKEN')
        if tok and str(tok).strip():
            return str(tok).strip()
        return (self.get('webhook_ingest_token') or '').strip()

    def set_webhook_ingest_token(self, token):
        """Persist webhook token to config (no effect if WEBHOOK_INGEST_TOKEN env is set)."""
        return self.set('webhook_ingest_token', token or '')

    def get_risk_threshold(self, level):
        """Get risk threshold for specific level"""
        return self.get(f'risk_thresholds.{level}', DEFAULT_CONFIG['risk_thresholds'].get(level, 0))

    def get_detection_weight(self, pattern):
        """Alias for risk score weight (legacy name)."""
        return self.get(f'risk_scores.{pattern}', DEFAULT_CONFIG['risk_scores'].get(pattern, 0))

    def get_whitelisted_affiliates(self):
        """Normalized whitelist (handles comma-separated legacy entries)."""
        return normalize_affiliate_code_list(self.get('whitelisted_affiliates', []))

    def add_whitelisted_affiliate(self, affiliate_id):
        """Add affiliate to whitelist"""
        code = str(affiliate_id or '').strip()
        if not code:
            return True
        whitelist = self.get_whitelisted_affiliates()
        if code.lower() not in {a.lower() for a in whitelist}:
            whitelist.append(code)
            return self.set('whitelisted_affiliates', whitelist)
        return True

    def remove_whitelisted_affiliate(self, affiliate_id):
        """Remove affiliate from whitelist"""
        needle = str(affiliate_id or '').strip().lower()
        if not needle:
            return True
        whitelist = [
            a for a in self.get_whitelisted_affiliates()
            if a.lower() != needle
        ]
        return self.set('whitelisted_affiliates', whitelist)

    def is_whitelisted(self, affiliate_id):
        """Check if affiliate is whitelisted (case-insensitive)."""
        if affiliate_id is None:
            return False
        needle = str(affiliate_id).strip().lower()
        return needle in {a.lower() for a in self.get_whitelisted_affiliates()}

    def get_affiliate_analysis_skip_codes_lower(self, include_house_in_analysis: bool = False):
        """Lowercased webmaster codes skipped during fraud analysis.

        Whitelisted affiliates are always skipped. House affiliates are skipped unless
        include_house_in_analysis is True (e.g. dashboard re-run with house included).
        """
        skip = {a.lower() for a in self.get_whitelisted_affiliates()}
        if not include_house_in_analysis:
            skip.update(
                str(h).strip().lower()
                for h in (self.get('house_affiliates') or [])
                if h and str(h).strip()
            )
        return skip

    def add_house_affiliate(self, affiliate_id):
        """Add affiliate to house/internal list"""
        house = self.get('house_affiliates', [])
        if affiliate_id not in house:
            house.append(affiliate_id)
            return self.set('house_affiliates', house)
        return True

    def remove_house_affiliate(self, affiliate_id):
        """Remove affiliate from house/internal list"""
        house = self.get('house_affiliates', [])
        if affiliate_id in house:
            house.remove(affiliate_id)
            return self.set('house_affiliates', house)
        return True

    def is_house_affiliate(self, affiliate_id):
        """Check if affiliate is a house/internal affiliate"""
        if not affiliate_id:
            return False
        house = self.get('house_affiliates', [])
        # Case-insensitive comparison
        affiliate_lower = affiliate_id.lower() if isinstance(affiliate_id, str) else str(affiliate_id).lower()
        return any(h.lower() == affiliate_lower for h in house if h)

    def get_house_affiliates(self):
        """Get list of house/internal affiliates"""
        return self.get('house_affiliates', [])

    def get_qa_billing_names(self):
        """Get list of internal QA/tester billing names to exclude"""
        return [n.lower().strip() for n in self.get('qa_billing_names', []) if n.strip()]

    def add_qa_billing_name(self, name):
        """Add a QA billing name to exclusion list"""
        names = self.get('qa_billing_names', [])
        name_lower = name.strip().lower()
        if name_lower not in [n.lower() for n in names]:
            names.append(name.strip())
            return self.set('qa_billing_names', names)
        return True

    def remove_qa_billing_name(self, name):
        """Remove a QA billing name from exclusion list"""
        names = self.get('qa_billing_names', [])
        name_lower = name.strip().lower()
        names = [n for n in names if n.lower() != name_lower]
        return self.set('qa_billing_names', names)

    def is_qa_billing_name(self, full_name):
        """Check if a billing name belongs to a known QA tester"""
        if not full_name:
            return False
        return full_name.strip().lower() in self.get_qa_billing_names()

    def get_whitelisted_card_fingerprints(self):
        """Payment-method fingerprints (admin API) treated as internal test cards."""
        return [f.strip() for f in self.get('whitelisted_card_fingerprints', []) if f and str(f).strip()]

    def is_whitelisted_card_fingerprint(self, fingerprint) -> bool:
        if not fingerprint:
            return False
        fp = str(fingerprint).strip()
        return fp in set(self.get_whitelisted_card_fingerprints())

    def get_whitelisted_duids(self):
        """DUIDs excluded from shared-card investigation lists and link counts."""
        return [str(d).strip() for d in self.get('whitelisted_duids', []) if d is not None and str(d).strip()]

    def is_whitelisted_duid(self, duid) -> bool:
        if duid is None:
            return False
        return str(duid).strip() in set(self.get_whitelisted_duids())

    # ── IP whitelist helpers ─────────────────────────────────────────────────

    def get_whitelisted_ips(self):
        """Get list of whitelisted IPs (never flagged during analysis)."""
        return list(self.get('whitelisted_ips', []))

    def add_whitelisted_ip(self, ip: str, note: str = '') -> bool:
        """Add an IP to the whitelist."""
        ip = ip.strip()
        ips = self.get('whitelisted_ips', [])
        if ip not in ips:
            ips.append(ip)
            return self.set('whitelisted_ips', ips)
        return True

    def remove_whitelisted_ip(self, ip: str) -> bool:
        """Remove an IP from the whitelist."""
        ip = ip.strip()
        ips = [i for i in self.get('whitelisted_ips', []) if i != ip]
        return self.set('whitelisted_ips', ips)

    def is_whitelisted_ip(self, ip: str) -> bool:
        """Return True if the IP is on the whitelist."""
        return ip.strip() in set(self.get('whitelisted_ips', []))

    def export_config(self, export_path):
        """Export configuration to another file"""
        try:
            with open(export_path, 'w') as f:
                json.dump(self.config, f, indent=2)
            return True
        except Exception as e:
            print(f"Error exporting config: {e}")
            return False

    def reset_to_defaults(self):
        """Reset configuration to defaults"""
        # Keep API key
        api_key = self.get('api_key')
        self.config = DEFAULT_CONFIG.copy()
        if api_key:
            self.config['api_key'] = api_key
        return self.save_config()
