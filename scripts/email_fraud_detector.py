import pandas as pd
import re
from collections import Counter, defaultdict
import numpy as np
from datetime import datetime
import os
import sys
import glob
from pathlib import Path
import json
import ast
import copy
import time
import requests

try:
    import gender_guesser.detector as gender
    GENDER_DETECTOR_AVAILABLE = True
except ImportError:
    GENDER_DETECTOR_AVAILABLE = False
    print("Warning: gender-guesser not installed. BILLING_GENDER_MISMATCH detection disabled.")
    print("Install with: pip install gender-guesser")

class EmailFraudDetector:
    def __init__(self, config=None):
        """
        Initialize the fraud detector.
        
        Args:
            config: Optional Config object for reading risk scores.
                    If not provided, uses default values.
        """
        self.config = config
        
        # Load risk scores from config or use defaults
        self.risk_scores = self._load_risk_scores()
        
        # Initialize gender detector if available
        self.gender_detector = gender.Detector() if GENDER_DETECTOR_AVAILABLE else None
        
        # Major email providers (common domains — not monitored for affiliate concentration)
        default_major_providers = [
            'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com',
            'aol.com', 'icloud.com', 'protonmail.com', 'mail.com',
            'privaterelay.appleid.com',
        ]
        self.major_providers = [
            d.lower().strip()
            for d in self._get_config('major_providers', default_major_providers)
            if d
        ] or default_major_providers

        # Keywords for theme detection
        self.theme_keywords = {
            'real_estate': ['realty', 'realtor', 'property', 'homes', 'estate', 'housing'],
            'construction': ['construction', 'builder', 'contractor', 'building', 'concrete'],
            'crypto': ['crypto', 'bitcoin', 'blockchain', 'btc', 'eth'],
            'finance': ['finance', 'invest', 'capital', 'trading', 'forex']
        }

        # Suspicious names - load from config or use defaults
        self.suspicious_names = self._get_config('suspicious_names', ['fatima', 'muhammed'])

        # Will be populated dynamically from the dataset
        self.repeated_words = {}
        self.repeated_patterns = {}
        self.ip_velocity_flags = {}  # IPs with suspicious signup velocity
        self.shared_ip_flags = {}    # IPs shared by multiple accounts (fraud ring / VPN / CGN)
        self.device_distribution = {'mobile': 0, 'desktop': 0, 'unknown': 0}  # Track device types
        
        # IP geolocation cache and settings
        self.ip_geolocation_cache = {}
        self.ip_geolocation_enabled = True
        self.ip_api_last_call = 0
        self.ip_api_rate_limit = 0.5  # seconds between API calls (free tier limit)
        
        # Geographic clustering flags (populated by build_geographic_cluster_maps)
        self.us_state_cluster_flags = set()  # States with 3+ accounts
        self.us_city_state_cluster_flags = set()  # City+State combinations with 3+ accounts
        self.intl_country_city_cluster_flags = set()  # Country+City combinations with 3+ accounts (non-US)

        # Gender concentration flags (populated by build_gender_concentration_map)
        # Maps affiliate/campaign key -> {'woman_pct': float, 'total': int, 'women': int}
        self.gender_concentration_flags = {}

        # Sequential email clusters (populated by build_sequential_email_map)
        # Key: (affiliate, username_stem, domain) -> {'count': int distinct suffixes, 'suffixes': list}
        self.sequential_email_flags = {}

        # Per-affiliate domain concentration (build_affiliate_domain_concentration_map)
        # Key: (affiliate, domain) -> {'pct': float, 'count': int, 'total': int}
        self.affiliate_domain_concentration_flags = {}

        # Provider/system-generated email domains (Apple relay, phone registration placeholders, etc.)
        self.privacy_relay_domains = {
            d.lower().strip()
            for d in self._get_config(
                'privacy_relay_domains',
                ['privaterelay.appleid.com', 'phone-registration.invalid'],
            )
            if d
        }
        exclude_config = self._get_config('affiliate_domain_concentration_exclude_domains', None)
        exclude_source = exclude_config if exclude_config is not None else ['gmail.com']
        self.affiliate_domain_concentration_exclude_domains = {
            d.lower().strip() for d in exclude_source if d
        }

    def _get_config(self, key, default=None):
        """Get value from config or return default"""
        if self.config:
            return self.config.get(key, default)
        return default
    
    def _load_risk_scores(self):
        """Load risk scores from config or use defaults"""
        defaults = {
            'excessive_dots': 20,
            'digit_suffix': 15,
            'scrambled_pattern': 35,
            'name_number_pattern': 40,
            'written_number_pattern': 15,
            'repeated_word_pattern': 25,
            'suspicious_name': 30,
            'billing_gender_mismatch': 35,
            'gender_name_mismatch': 35,
            'pov_instant_20s': 50,
            'pov_instant_40s': 40,
            'pov_fast_60s': 30,
            'ip_velocity_high': 30,
            'ip_velocity_medium': 5,
            'shared_ip_medium': 20,   # 3-9 accounts on same IP
            'shared_ip_high': 35,     # 10+ accounts on same IP
            'desktop_windows_10': 20,
            'desktop_other': 10,
            'us_state_cluster': 25,
            'us_city_state_cluster': 30,
            'intl_country_city_cluster': 30,
            'theme_cluster': 15,
            'woman_concentration': 25,   # Abnormally high % of WOMAN registrations from a source
            # Same stem + domain, varying numeric suffix — 4+ distinct suffixes within one affiliate
            'sequential_email': 30,
            'affiliate_domain_concentration': 20,
        }
        
        if self.config:
            config_scores = self.config.get('risk_scores', {})
            # Merge with defaults (config takes precedence)
            return {**defaults, **config_scores}
        
        return defaults
    
    def get_risk_score(self, key):
        """Get a specific risk score value"""
        return self.risk_scores.get(key, 0)

    def is_privacy_relay_domain(self, domain):
        """True when the domain uses system-generated opaque local-parts (Apple relay, phone registration, etc.)."""
        if not domain:
            return False
        return str(domain).lower().strip() in self.privacy_relay_domains

    def _domain_concentration_exclude_domains(self):
        """Domains never monitored for affiliate-level email domain concentration."""
        return self.affiliate_domain_concentration_exclude_domains | self.privacy_relay_domains
    
    def check_gender_mismatch(self, first_name, declared_gender):
        """
        Check if billing name gender matches declared gender (user1 field).
        
        Args:
            first_name: First name from billing info
            declared_gender: Declared gender from user1 field ('man', 'woman', etc.)
        
        Returns:
            dict with 'mismatch' (bool), 'predicted_gender', 'declared_gender', 'confidence'
        """
        if not self.gender_detector or not first_name or pd.isna(first_name):
            return {'mismatch': False, 'reason': 'no_data'}
        
        if not declared_gender or pd.isna(declared_gender):
            return {'mismatch': False, 'reason': 'no_declared_gender'}
        
        # Clean and capitalize first name
        first_name = str(first_name).strip().capitalize()
        declared_gender = str(declared_gender).lower().strip()
        
        # Normalize declared gender
        declared_normalized = None
        if declared_gender in ['man', 'male', 'm']:
            declared_normalized = 'male'
        elif declared_gender in ['woman', 'female', 'f']:
            declared_normalized = 'female'
        else:
            return {'mismatch': False, 'reason': 'unknown_declared_gender'}
        
        # Predict gender from first name
        predicted = self.gender_detector.get_gender(first_name)
        
        # Gender guesser returns: male, female, mostly_male, mostly_female, andy (androgynous), unknown
        predicted_normalized = None
        confidence = 'unknown'
        
        if predicted in ['male', 'mostly_male']:
            predicted_normalized = 'male'
            confidence = 'high' if predicted == 'male' else 'medium'
        elif predicted in ['female', 'mostly_female']:
            predicted_normalized = 'female'
            confidence = 'high' if predicted == 'female' else 'medium'
        elif predicted == 'andy':
            # Androgynous name - skip
            return {'mismatch': False, 'reason': 'androgynous_name'}
        else:
            # Unknown name - skip
            return {'mismatch': False, 'reason': 'unknown_name'}
        
        # Check for mismatch
        mismatch = (predicted_normalized != declared_normalized)
        
        return {
            'mismatch': mismatch,
            'predicted_gender': predicted_normalized,
            'declared_gender': declared_normalized,
            'confidence': confidence,
            'raw_prediction': predicted
        }

    def extract_name_candidates_from_username(self, username):
        """Return ordered name candidates extracted from an email local-part."""
        if not username:
            return []

        raw = str(username).lower().strip()
        if not raw:
            return []

        candidates = []

        def _add(name):
            cleaned = re.sub(r'[^a-z]', '', name or '')
            if len(cleaned) >= 3 and cleaned not in candidates:
                candidates.append(cleaned)

        head = re.split(r'[._\-+]', raw)[0]
        if not head or not head[0].isalpha():
            return []

        _add(re.sub(r'\d+$', '', head))

        name_num_name = re.match(r'^([a-z]+)\d+([a-z]+)', raw)
        if name_num_name:
            _add(name_num_name.group(1))

        leading_alpha = re.match(r'^([a-z]+)\d', raw)
        if leading_alpha:
            _add(leading_alpha.group(1))

        lead_match = re.match(r'^([a-z]+)', head)
        core = lead_match.group(1) if lead_match else ''
        if len(core) >= 6:
            for size in range(min(len(core), 12), 2, -1):
                _add(core[:size])

        return [name.capitalize() for name in candidates]

    def check_email_gender_mismatch(self, email, declared_gender):
        """
        Compare gender predicted from email username against declared gender (user1).

        Tries multiple extracted name candidates (delimiter split, prefixes, etc.).
        Skips when billing first_name already provides a stronger signal upstream.
        """
        if not self.gender_detector:
            return {'mismatch': False, 'reason': 'no_data'}

        if not email or '@' not in str(email):
            return {'mismatch': False, 'reason': 'no_data'}

        if not declared_gender or pd.isna(declared_gender):
            return {'mismatch': False, 'reason': 'no_declared_gender'}

        username = str(email).lower().split('@', 1)[0]
        for candidate in self.extract_name_candidates_from_username(username):
            result = self.check_gender_mismatch(candidate, declared_gender)
            if result.get('mismatch'):
                return {
                    **result,
                    'extracted_name': candidate,
                    'source': 'email_username',
                }
            if result.get('predicted_gender') and not result.get('mismatch'):
                if result.get('reason') not in ('androgynous_name', 'unknown_name'):
                    return {
                        'mismatch': False,
                        'reason': 'email_name_matches',
                        'extracted_name': candidate,
                    }

        return {'mismatch': False, 'reason': 'no_extractable_name'}

    def detect_device_type(self, user_agent):
        """
        Detect device type from user agent string
        Returns: 'mobile', 'desktop', or 'unknown'
        """
        if not user_agent or pd.isna(user_agent):
            return 'unknown'

        ua_lower = str(user_agent).lower()

        # Mobile indicators
        mobile_keywords = ['mobile', 'android', 'iphone', 'ipad', 'ipod', 'blackberry',
                          'windows phone', 'webos', 'symbian', 'iemobile', 'opera mini',
                          'palm', 'kindle', 'silk']

        # Desktop indicators (OS)
        desktop_keywords = ['windows nt', 'macintosh', 'mac os x', 'linux', 'x11', 'cros']

        # Check for mobile first (more specific)
        if any(keyword in ua_lower for keyword in mobile_keywords):
            return 'mobile'

        # Then check for desktop
        if any(keyword in ua_lower for keyword in desktop_keywords):
            return 'desktop'

        return 'unknown'

    def get_ip_geolocation(self, ip_address):
        """
        Get geolocation data for an IP address using ip-api.com (free tier).
        
        Args:
            ip_address: IP address to look up
            
        Returns:
            dict with keys: country_code, country, region, city, or None if lookup fails
        """
        if not ip_address or pd.isna(ip_address) or not self.ip_geolocation_enabled:
            return None
        
        ip_str = str(ip_address).strip()
        
        # Check cache first
        if ip_str in self.ip_geolocation_cache:
            return self.ip_geolocation_cache[ip_str]
        
        # Rate limiting for free tier (45 requests per minute)
        elapsed = time.time() - self.ip_api_last_call
        if elapsed < self.ip_api_rate_limit:
            time.sleep(self.ip_api_rate_limit - elapsed)
        
        try:
            # ip-api.com free tier (no API key needed)
            response = requests.get(
                f'http://ip-api.com/json/{ip_str}',
                params={'fields': 'status,countryCode,country,regionName,city'},
                timeout=5
            )
            self.ip_api_last_call = time.time()
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    result = {
                        'country_code': data.get('countryCode'),
                        'country': data.get('country'),
                        'region': data.get('regionName'),  # State/province
                        'city': data.get('city')
                    }
                    self.ip_geolocation_cache[ip_str] = result
                    return result
            
            # Cache failed lookups as None to avoid repeated API calls
            self.ip_geolocation_cache[ip_str] = None
            return None
            
        except Exception as e:
            # Silently fail - geolocation is optional
            self.ip_geolocation_cache[ip_str] = None
            return None

    def build_geographic_cluster_maps(self, df):
        """
        Build maps of geographic clusters for fraud detection.
        Identifies locations with multiple accounts (potential fraud rings).

        Uses the geo_country column already stored in the database rather than
        making live API calls, so this is fast regardless of batch size.
        For city/region clustering we use existing ip_geolocation_cache entries
        only — no new API calls are made here.
        """
        ip_col  = self.column_map.get('ip')
        geo_col = self.column_map.get('geo_country')

        if not ip_col and not geo_col:
            return

        # Track geographic occurrences using stored geo_country (country-level)
        # and cached IP geo data (city/state) for IPs already looked up.
        us_state_counts        = Counter()
        us_city_state_counts   = Counter()
        intl_country_city_counts = Counter()

        for _, row in df.iterrows():
            ip      = row.get(ip_col)  if ip_col  and ip_col  in row else None
            country = row.get(geo_col) if geo_col and geo_col in row else None

            # Prefer cached geo (populated by earlier account-detail lookups)
            geo = None
            if ip and str(ip).strip() not in ('', 'nan', 'None'):
                geo = self.ip_geolocation_cache.get(str(ip).strip())

            country_code = None
            region = None
            city   = None

            if geo:
                country_code = geo.get('country_code')
                region       = geo.get('region')
                city         = geo.get('city')
            elif country:
                # Fallback: only country-level data available from stored column
                country_code = str(country).strip().upper()[:2] if country else None

            if not country_code:
                continue

            if country_code == 'US':
                if region:
                    us_state_counts[region] += 1
                    if city:
                        us_city_state_counts[(city, region)] += 1
            elif city:
                intl_country_city_counts[(city, country_code)] += 1

        threshold = 3

        for state, count in us_state_counts.items():
            if count >= threshold:
                self.us_state_cluster_flags.add(f"{state},US")

        for (city, state), count in us_city_state_counts.items():
            if count >= threshold:
                self.us_city_state_cluster_flags.add(f"{city},{state},US")

        for (city, country_code), count in intl_country_city_counts.items():
            if count >= threshold:
                self.intl_country_city_cluster_flags.add(f"{city},{country_code}")

        total = (len(self.us_state_cluster_flags) +
                 len(self.us_city_state_cluster_flags) +
                 len(self.intl_country_city_cluster_flags))
        if total:
            print(f"Found {total} geographic clusters  "
                  f"({len(self.us_state_cluster_flags)} US states, "
                  f"{len(self.us_city_state_cluster_flags)} US cities, "
                  f"{len(self.intl_country_city_cluster_flags)} intl cities)")

    def normalize_column_names(self, df):
        """Normalize column names to handle different capitalizations"""
        # Create a mapping of lowercase column names to actual column names
        column_mapping = {col.lower(): col for col in df.columns}

        # Standard column name variations
        standard_names = {
            'email': ['email', 'Email', 'EMAIL', 'e-mail', 'E-mail'],
            'ip': ['ip', 'IP', 'Ip', 'ip address', 'IP Address'],
            'duid': ['duid', 'DUID', 'Duid'],
            'username': ['username', 'Username', 'USERNAME', 'user name', 'User Name'],
            'payout_amount': ['payout amount', 'Payout Amount', 'PAYOUT AMOUNT', 'payout_amount', 'Payout_Amount'],
            'sale_amount': ['sale amount', 'Sale Amount', 'SALE AMOUNT', 'sale_amount', 'Sale_Amount'],
            'campaign': ['campaign', 'Campaign', 'CAMPAIGN'],
            'ad_id': ['ad id', 'Ad Id', 'AD ID', 'ad_id', 'Ad_Id'],
            'transaction_date': ['transaction date', 'Transaction Date', 'TRANSACTION DATE', 'transaction_date', 'Transaction_Date'],
            'trans_datetime': [
                'trans_datetime', 'Trans_Datetime', 'TRANS_DATETIME',
                'transaction date time', 'Transaction Date Time',
                'trans_date', 'Trans_Date', 'TRANS_DATE', 'transaction date', 'Transaction Date',
            ],
            'first_name': ['first name', 'First Name', 'FIRST NAME', 'first_name', 'First_Name'],
            'last_name': ['last name', 'Last Name', 'LAST NAME', 'last_name', 'Last_Name'],
            'pov_verified': ['pov_verified', 'POV_Verified', 'POV Verified', 'POV_VERIFIED'],
            'pov_verified_time': ['pov_verified_time', 'POV_Verified_Time', 'POV Verified Time', 'POV_VERIFIED_TIME'],
            'custom_http_user_agent': ['custom_http_user_agent', 'Custom_Http_User_Agent', 'HTTP User Agent', 'user_agent', 'User Agent', 'User_Agent'],
            'webmaster_code': ['webmaster_code', 'Webmaster_Code', 'WEBMASTER_CODE', 'site_code', 'Site_Code'],
            # Free-table exports use user1; paid uses custom_u1
            'custom_u1': ['custom_u1', 'Custom_U1', 'CUSTOM_U1', 'user1', 'User1', 'USER1', 'u1'],
            'ip': ['ip', 'IP', 'Ip', 'ip_address', 'IP Address', 'ip address'],
            'geo_country': ['geo_country', 'Geo_Country', 'GEO_COUNTRY', 'country']
        }

        # Find and map columns
        self.column_map = {}
        for standard, variations in standard_names.items():
            for var in variations:
                if var.lower() in column_mapping:
                    self.column_map[standard] = column_mapping[var.lower()]
                    break

        return df

    def extract_words_from_username(self, username):
        """Extract meaningful words from email username, including number words and name components"""
        username_lower = username.lower()

        # Written number words to detect
        number_words = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']

        words = []

        # Extract number words if present
        for num_word in number_words:
            if num_word in username_lower:
                words.append(num_word)

        # Remove digits and special characters, split by common delimiters
        username_clean = re.sub(r'[0-9._-]', ' ', username_lower)
        text_words = [w for w in username_clean.split() if len(w) >= 4]  # Only words 4+ chars
        words.extend(text_words)

        # Also extract name components (e.g., "hgolding" -> ["golding"], "goldinghenry" -> ["golding", "henry"])
        # Look for common name patterns embedded in longer strings
        for word in text_words:
            if len(word) > 6:  # Only analyze longer words
                # Extract potential name components (4+ char substrings)
                for i in range(len(word) - 3):
                    for j in range(i + 4, len(word) + 1):
                        component = word[i:j]
                        if len(component) >= 4 and len(component) < len(word):
                            words.append(component)

        return list(set(words))  # Remove duplicates

    def is_scrambled(self, username):
        """Advanced scrambled pattern detection"""
        if len(username) < 6:
            return False, {}

        # Remove numbers and special chars for analysis
        letters_only = re.sub(r'[^a-z]', '', username.lower())
        if len(letters_only) < 6:
            return False, {}

        indicators = {}
        score = 0

        # 1. Consecutive consonants (more than 4 in a row)
        consonant_sequences = re.findall(r'[bcdfghjklmnpqrstvwxyz]{5,}', letters_only)
        if consonant_sequences:
            indicators['long_consonant_sequences'] = len(consonant_sequences)
            score += 2

        # 2. Very low vowel ratio
        vowels = sum(1 for c in letters_only if c in 'aeiou')
        vowel_ratio = vowels / len(letters_only) if len(letters_only) > 0 else 0
        if vowel_ratio < 0.15:
            indicators['low_vowel_ratio'] = round(vowel_ratio, 2)
            score += 1

        # 3. Repeating character patterns (like "vbvbvb" or "fgfgfg")
        repeating_patterns = re.findall(r'(.{2,3})\1{2,}', letters_only)
        if repeating_patterns:
            indicators['repeating_patterns'] = repeating_patterns
            score += 2

        # 4. High consonant-to-vowel clustering (cvccvcvc with many c's)
        consonant_clusters = re.findall(r'[bcdfghjklmnpqrstvwxyz]{3,}', letters_only)
        if len(consonant_clusters) >= 3:
            indicators['multiple_consonant_clusters'] = len(consonant_clusters)
            score += 1

        # 5. No recognizable English patterns (bigram analysis)
        common_bigrams = ['th', 'he', 'in', 'er', 'an', 're', 'on', 'at', 'en', 'nd', 'ti', 'es', 'or', 'te', 'of']
        bigram_count = sum(1 for bg in common_bigrams if bg in letters_only)
        if bigram_count == 0 and len(letters_only) > 8:
            indicators['no_common_bigrams'] = True
            score += 2

        # Scrambled if score >= 3
        return score >= 3, indicators

    def get_column(self, row, column_name, default='N/A'):
        """Safely get column value with proper name mapping"""
        actual_column = self.column_map.get(column_name)
        if actual_column and actual_column in row.index:
            value = row[actual_column]
            if pd.notna(value):
                # Try to convert to number if default is numeric
                if isinstance(default, (int, float)):
                    try:
                        return float(value) if value else default
                    except (ValueError, TypeError):
                        return default
                return value
        return default

    def analyze_email(self, email, trans_datetime=None, pov_verified=None, pov_verified_time=None, ip_address=None, user_agent=None, first_name=None, user1=None):
        """
        Analyze a single email for fraud patterns

        Args:
            email: Email address to analyze
            trans_datetime: Transaction/signup datetime (optional)
            pov_verified: Whether POV verified (optional)
            pov_verified_time: POV verification timestamp (optional)
            ip_address: IP address of signup (optional)
            user_agent: HTTP user agent string (optional)
            first_name: Billing first name - for paid records only (optional)
            user1: Declared gender field (optional)
        """
        if pd.isna(email) or not isinstance(email, str):
            return {
                'email': email,
                'risk_score': 0,
                'flags': [],
                'details': {}
            }

        email = email.lower().strip()
        risk_score = 0
        flags = []
        details = {}

        # Split email into username and domain
        if '@' not in email:
            # Data quality issue, not fraud - score 0 but flag for review
            return {
                'email': email,
                'risk_score': 0,
                'flags': ['DATA_QUALITY_MISSING_EMAIL'],
                'details': {'reason': 'No @ symbol found - data quality issue, not fraud'}
            }

        username, domain = email.split('@', 1)
        domain = domain.strip().lower()
        is_privacy_relay = self.is_privacy_relay_domain(domain)
        details['is_privacy_relay'] = is_privacy_relay

        if not is_privacy_relay:
            # 1. Multiple Dots Pattern (>3 dots)
            dot_count = username.count('.')
            if dot_count > 3:
                risk_score += self.get_risk_score('excessive_dots')
                flags.append('EXCESSIVE_DOTS')
                details['dot_count'] = dot_count

            # 2. Digit Suffix Pattern (4-5 digits at end)
            digit_suffix = re.search(r'(\d{4,5})$', username)
            if digit_suffix:
                risk_score += self.get_risk_score('digit_suffix')
                flags.append('DIGIT_SUFFIX')
                details['digit_suffix'] = digit_suffix.group(1)

            # 3. Scrambled/Random Pattern - Advanced detection
            is_scrambled_result, scrambled_indicators = self.is_scrambled(username)
            if is_scrambled_result:
                risk_score += self.get_risk_score('scrambled_pattern')
                flags.append('SCRAMBLED_PATTERN')
                details['scrambled_indicators'] = scrambled_indicators

            # 4. Name-Number-Name-Number Pattern
            # Detects patterns like: firstname12lastname4567@domain
            name_num_pattern = re.search(r'^([a-z]+)(\d+)([a-z]+)(\d+)', username)
            if name_num_pattern:
                risk_score += self.get_risk_score('name_number_pattern')
                flags.append('NAME_NUMBER_PATTERN')
                details['pattern_structure'] = f"{name_num_pattern.group(1)}-{name_num_pattern.group(2)}-{name_num_pattern.group(3)}-{name_num_pattern.group(4)}"

            # 5. Suspicious Name Detection (hardcoded patterns)
            # Check for known fraud-associated names
            suspicious_found = []
            for name in self.suspicious_names:
                if name in username:
                    suspicious_found.append(name)

            if suspicious_found:
                risk_score += self.get_risk_score('suspicious_name')
                flags.append('SUSPICIOUS_NAME')
                details['suspicious_names'] = suspicious_found

            # 5a. Written Number Word Detection (e.g., emillythree, fouremilly)
            # Check for written number words combined with names
            number_words = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten']
            has_number_word = any(num_word in username for num_word in number_words)

            if has_number_word:
                # This pattern is suspicious when combined with a name
                risk_score += self.get_risk_score('written_number_pattern')
                flags.append('WRITTEN_NUMBER_PATTERN')
                details['written_numbers'] = [nw for nw in number_words if nw in username]

            # 5b. Repeated Word Detection (dynamic pattern)
            # Check if email username contains words that appear frequently across dataset
            repeated_words_found = []
            username_words = self.extract_words_from_username(username)
            for word in username_words:
                if word in self.repeated_words and self.repeated_words[word] > 3:
                    repeated_words_found.append(f"{word}({self.repeated_words[word]}x)")

            if repeated_words_found:
                risk_score += self.get_risk_score('repeated_word_pattern')
                flags.append('REPEATED_WORD_PATTERN')
                details['repeated_words'] = repeated_words_found

            # 6. Theme Detection
            detected_themes = []
            for theme, keywords in self.theme_keywords.items():
                if any(keyword in email for keyword in keywords):
                    detected_themes.append(theme)

            if detected_themes:
                details['themes'] = detected_themes

        # 7. Domain check
        details['domain'] = domain
        details['is_major_provider'] = domain in self.major_providers
        
        # 7a. Billing Gender Mismatch (Paid Records Only)
        # Check if billing name gender matches declared gender
        if first_name and user1:
            gender_check = self.check_gender_mismatch(first_name, user1)
            if gender_check.get('mismatch'):
                risk_score += self.get_risk_score('billing_gender_mismatch')
                flags.append('BILLING_GENDER_MISMATCH')
                details['gender_mismatch'] = {
                    'billing_name': first_name,
                    'predicted_gender': gender_check['predicted_gender'],
                    'declared_gender': gender_check['declared_gender'],
                    'confidence': gender_check['confidence']
                }

        # 7b. Email username gender vs declared gender (free + paid signups)
        if user1 and 'BILLING_GENDER_MISMATCH' not in flags:
            email_gender_check = self.check_email_gender_mismatch(email, user1)
            if email_gender_check.get('mismatch'):
                risk_score += self.get_risk_score('gender_name_mismatch')
                flags.append('GENDER_NAME_MISMATCH')
                details['email_gender_mismatch'] = {
                    'extracted_name': email_gender_check.get('extracted_name'),
                    'predicted_gender': email_gender_check['predicted_gender'],
                    'declared_gender': email_gender_check['declared_gender'],
                    'confidence': email_gender_check.get('confidence'),
                    'user1_value': str(user1).lower().strip(),
                }

        # 8. POV Verified Timing Analysis (CRITICAL FRAUD INDICATOR)
        # Email validation within 60 seconds of account creation is highly suspicious
        if trans_datetime and pov_verified and pov_verified_time:
            try:
                # Parse timestamps with UTC timezone normalization
                if isinstance(trans_datetime, str):
                    signup_time = pd.to_datetime(trans_datetime, utc=True)
                else:
                    signup_time = pd.to_datetime(trans_datetime, utc=True)

                if isinstance(pov_verified_time, str):
                    verification_time = pd.to_datetime(pov_verified_time, utc=True)
                else:
                    verification_time = pd.to_datetime(pov_verified_time, utc=True)

                # Calculate validation time in seconds
                validation_seconds = (verification_time - signup_time).total_seconds()
                details['pov_validation_seconds'] = int(validation_seconds)

                # Apply risk scoring based on validation speed
                if validation_seconds <= 20:
                    # CRITICAL - Instant validation (likely automated)
                    risk_score += self.get_risk_score('pov_instant_20s')
                    flags.append('POV_INSTANT_VALIDATION_20S')
                    details['pov_risk_level'] = 'CRITICAL'
                elif validation_seconds <= 40:
                    # HIGH - Very fast validation
                    risk_score += self.get_risk_score('pov_instant_40s')
                    flags.append('POV_INSTANT_VALIDATION_40S')
                    details['pov_risk_level'] = 'HIGH'
                elif validation_seconds <= 60:
                    # MEDIUM - Fast validation
                    risk_score += self.get_risk_score('pov_fast_60s')
                    flags.append('POV_FAST_VALIDATION_60S')
                    details['pov_risk_level'] = 'MEDIUM'
                else:
                    # Normal validation time
                    details['pov_risk_level'] = 'NORMAL'

            except Exception as e:
                # If timestamp parsing fails, log but don't fail analysis
                details['pov_validation_error'] = str(e)

        # 9. IP Velocity Check (Fraud Ring Detection)
        # Check if this IP has suspicious signup velocity
        if ip_address and ip_address in self.ip_velocity_flags:
            ip_data = self.ip_velocity_flags[ip_address]
            if ip_data['risk_level'] == 'HIGH':
                risk_score += self.get_risk_score('ip_velocity_high')
            else:
                risk_score += self.get_risk_score('ip_velocity_medium')
            flags.append(f"IP_VELOCITY_{ip_data['risk_level']}")
            details['ip_velocity'] = ip_data

        # 9b. Shared IP Check (multiple accounts on the same IP — fraud ring / VPN / CGN)
        if ip_address and ip_address in self.shared_ip_flags:
            ip_data = self.shared_ip_flags[ip_address]
            if ip_data['risk_level'] == 'HIGH':
                risk_score += self.get_risk_score('shared_ip_high')
                flags.append('SHARED_IP_HIGH')
            else:
                risk_score += self.get_risk_score('shared_ip_medium')
                flags.append('SHARED_IP_MEDIUM')
            details['shared_ip'] = {
                'account_count': ip_data['account_count'],
                'risk_level': ip_data['risk_level'],
            }

        # 10. Device Type Analysis (Desktop vs Mobile)
        # Since 90% of legitimate users are mobile, desktop users are suspicious
        if user_agent:
            device_type = self.detect_device_type(user_agent)
            details['device_type'] = device_type

            # Track distribution for reporting
            self.device_distribution[device_type] += 1

            # Desktop devices are suspicious (legitimate users are 90% mobile)
            # Windows 10 is more suspicious (commonly used in fraud farms)
            if device_type == 'desktop':
                is_windows_10 = 'windows nt 10' in str(user_agent).lower()
                if is_windows_10:
                    risk_score += self.get_risk_score('desktop_windows_10')
                    flags.append('DESKTOP_DEVICE_SUSPICIOUS')
                    details['device_risk'] = 'Windows 10 desktop - common in fraud farms'
                else:
                    risk_score += self.get_risk_score('desktop_other')
                    flags.append('DESKTOP_DEVICE_SUSPICIOUS')
                    details['device_risk'] = 'Non-Windows 10 desktop'

        # 11. Geographic Clustering Analysis
        # Check if this IP's location is in a known cluster (potential fraud ring)
        if ip_address:
            geo = self.get_ip_geolocation(ip_address)
            if geo:
                country_code = geo.get('country_code')
                region = geo.get('region')  # State/province
                city = geo.get('city')
                
                details['geo_country'] = country_code
                details['geo_region'] = region
                details['geo_city'] = city
                
                # US State Clustering
                if country_code == 'US' and region:
                    state_key = f"{region},US"
                    if state_key in self.us_state_cluster_flags:
                        risk_score += self.get_risk_score('us_state_cluster')
                        flags.append('SAME_US_STATE_CLUSTER')
                        details['geo_cluster'] = f"Multiple accounts from {region}"
                
                # US City/State Clustering
                if country_code == 'US' and city and region:
                    city_state_key = f"{city},{region},US"
                    if city_state_key in self.us_city_state_cluster_flags:
                        risk_score += self.get_risk_score('us_city_state_cluster')
                        flags.append('SAME_US_CITY_STATE_CLUSTER')
                        details['geo_cluster'] = f"Multiple accounts from {city}, {region}"
                
                # International Country+City Clustering
                if country_code and country_code != 'US' and city:
                    country_city_key = f"{city},{country_code}"
                    if country_city_key in self.intl_country_city_cluster_flags:
                        risk_score += self.get_risk_score('intl_country_city_cluster')
                        flags.append('SAME_INTL_COUNTRY_CITY_CLUSTER')
                        details['geo_cluster'] = f"Multiple accounts from {city}, {country_code}"

        return {
            'email': email,
            'risk_score': min(risk_score, 100),  # Cap at 100
            'flags': flags,
            'details': details
        }

    def detect_theme_clusters(self, df):
        """Detect email theme clusters"""
        theme_groups = defaultdict(list)
        email_col = self.column_map.get('email')

        if not email_col:
            return {}

        for idx, row in df.iterrows():
            email = row[email_col]
            if pd.notna(email):
                email_lower = str(email).lower()
                for theme, keywords in self.theme_keywords.items():
                    if any(keyword in email_lower for keyword in keywords):
                        theme_groups[theme].append({
                            'email': email,
                            'DUID': self.get_column(row, 'duid', 'N/A'),
                            'payout_amount': self.get_column(row, 'payout_amount', 0)
                        })

        return dict(theme_groups)

    def build_repeated_word_map(self, df):
        """Analyze all emails to find words that appear multiple times across dataset"""
        word_frequency = Counter()
        email_col = self.column_map.get('email')

        if not email_col:
            return

        print("Building repeated word patterns map...")
        for email in df[email_col]:
            if pd.notna(email) and '@' in str(email):
                username = str(email).lower().split('@')[0]
                words = self.extract_words_from_username(username)
                for word in words:
                    word_frequency[word] += 1

        # Store words that appear more than 3 times
        self.repeated_words = {word: count for word, count in word_frequency.items() if count > 3}

        if self.repeated_words:
            print(f"Found {len(self.repeated_words)} repeated word patterns")
            # Show top patterns
            top_patterns = sorted(self.repeated_words.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"Top patterns: {', '.join([f'{word}({count}x)' for word, count in top_patterns])}")

    def build_gender_concentration_map(self, df):
        """
        Detect affiliates/campaigns with abnormally high WOMAN registration rates.

        The site baseline is ~0.9% WOMAN. Any affiliate with >=15% WOMAN
        registrations (and >=20 accounts with a known gender value) is flagged.
        These accounts are individually marked WOMAN_CONCENTRATION at analysis time.

        Threshold rationale (from production data):
          - Platform baseline : ~0.9%
          - Highest clean aff : ~8%   (googlefacemob)
          - Flag threshold    : >=15%  (~17x baseline, above any observed clean aff)
        """
        self.gender_concentration_flags = {}

        u1_col = self.column_map.get('custom_u1')
        aff_col = self.column_map.get('webmaster_code')

        if not u1_col or u1_col not in df.columns:
            return

        group_col = aff_col if (aff_col and aff_col in df.columns) else None

        # Configurable thresholds
        min_accounts = 20     # minimum accounts with a known gender to flag
        threshold_pct = 15.0  # % WOMAN that triggers the flag

        rows_with_gender = df[df[u1_col].notna() & (df[u1_col] != '')]

        if rows_with_gender.empty:
            return

        if group_col:
            groups = rows_with_gender.groupby(group_col)
        else:
            # No affiliate column — treat whole batch as one group
            groups = [('__ALL__', rows_with_gender)]

        for key, grp in groups:
            key_s = str(key).strip() if key is not None and str(key).strip() != '' else ''
            if not key_s or key_s.lower() == 'nan':
                continue
            total = len(grp)
            if total < min_accounts:
                continue
            women = (grp[u1_col].astype(str).str.upper().str.strip() == 'WOMAN').sum()
            woman_pct = women / total * 100
            if woman_pct >= threshold_pct:
                self.gender_concentration_flags[key_s] = {
                    'woman_pct': round(woman_pct, 1),
                    'women': int(women),
                    'total': int(total),
                }

        if self.gender_concentration_flags:
            print(f"Found {len(self.gender_concentration_flags)} affiliate(s) with abnormal WOMAN registration rate:")
            for k, v in self.gender_concentration_flags.items():
                print(f"  {k}: {v['women']}/{v['total']} WOMAN ({v['woman_pct']}%)")

    @staticmethod
    def _parse_sequential_local_part(local: str):
        """
        Parse local part into (stem, numeric_suffix) if it matches stem+digits (stem >= 4 letters).
        Returns None if no match.
        """
        if not local:
            return None
        local = str(local).lower().strip()
        m = re.match(r'^([a-z]{4,})(\d+)$', local)
        if not m:
            return None
        return m.group(1), m.group(2)

    def build_sequential_email_map(self, df, min_distinct_suffixes: int = 4):
        """
        Per-affiliate batch pass: find clusters of emails with the same username stem,
        same domain, and distinct trailing numeric suffixes (e.g. maucheesee71, maucheesee76).

        Suffixes need not be consecutive; only the count within the affiliate matters.
        Rows without a resolvable webmaster_code are skipped (no cross-affiliate clustering).
        """
        self.sequential_email_flags = {}
        email_col = self.column_map.get('email')
        if not email_col or email_col not in df.columns:
            return

        from collections import defaultdict

        groups = defaultdict(set)  # (affiliate, stem, domain) -> set of suffix strings

        for _, row in df.iterrows():
            raw = row.get(email_col)
            if pd.isna(raw) or raw is None:
                continue
            email = str(raw).lower().strip()
            if '@' not in email:
                continue
            local, domain = email.split('@', 1)
            domain = domain.strip().lower()
            if not domain or self.is_privacy_relay_domain(domain):
                continue

            aff = self.get_column(row, 'webmaster_code', None)
            if not aff:
                for col in ('webmaster_code', 'site_code'):
                    if col in row.index and pd.notna(row[col]) and str(row[col]).strip().lower() not in ('', 'nan'):
                        aff = row[col]
                        break
            if aff is None or (isinstance(aff, float) and pd.isna(aff)):
                continue
            aff_s = str(aff).strip()
            if not aff_s or aff_s.lower() == 'nan':
                continue

            parsed = self._parse_sequential_local_part(local)
            if not parsed:
                continue
            stem, suf = parsed
            groups[(aff_s, stem, domain)].add(suf)

        for key, suffs in groups.items():
            if len(suffs) >= min_distinct_suffixes:
                suf_list = sorted(suffs, key=lambda x: (len(x), x))
                self.sequential_email_flags[key] = {
                    'count': len(suffs),
                    'suffixes': suf_list[:100],
                }

        if self.sequential_email_flags:
            print(
                f"Found {len(self.sequential_email_flags)} per-affiliate sequential-email stem/domain cluster(s)"
            )

    def apply_sequential_email_to_results(self, results):
        """
        Add SEQUENTIAL_EMAIL flag + risk for rows that belong to a cluster from
        build_sequential_email_map. Requires webmaster_code and email on each dict.
        Idempotent if SEQUENTIAL_EMAIL already in flags.
        """
        if not results or not self.sequential_email_flags:
            return
        try:
            pts = int(self.get_risk_score('sequential_email') or 0)
        except (TypeError, ValueError):
            pts = 0

        for r in results:
            wm = str(r.get('webmaster_code') or '').strip()
            if not wm or wm.lower() == 'nan':
                continue
            raw = r.get('email')
            if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                continue
            email = str(raw).lower().strip()
            if '@' not in email:
                continue
            local, domain = email.split('@', 1)
            domain = domain.strip().lower()
            parsed = self._parse_sequential_local_part(local)
            if not parsed:
                continue
            stem, _suf = parsed
            key = (wm, stem, domain)
            if key not in self.sequential_email_flags:
                continue

            flags = r.get('flags')
            if not isinstance(flags, list):
                flags = [] if flags is None else [str(flags)]
                r['flags'] = flags
            if 'SEQUENTIAL_EMAIL' in flags:
                continue

            info = self.sequential_email_flags[key]
            if pts > 0:
                try:
                    rs = int(r.get('risk_score', 0) or 0)
                except (TypeError, ValueError):
                    rs = 0
                r['risk_score'] = min(rs + pts, 100)

            flags.append('SEQUENTIAL_EMAIL')

            det = r.get('details')
            if not isinstance(det, dict):
                det = {}
                r['details'] = det
            det['sequential_email'] = {
                'affiliate': wm,
                'stem': stem,
                'domain': domain,
                'distinct_suffixes': info['count'],
            }

    def apply_gender_concentration_to_results(self, results):
        """
        Add WOMAN_CONCENTRATION flag + risk delta to each result dict (dashboard / CLI / scheduler shape).

        Run after build_gender_concentration_map(df) and after each result has webmaster_code and custom_u1.
        """
        if not results or not self.gender_concentration_flags:
            return
        try:
            woman_risk = int(self.get_risk_score('woman_concentration') or 0)
        except (TypeError, ValueError):
            woman_risk = 0

        for r in results:
            wm = str(r.get('webmaster_code') or '').strip()
            if not wm or wm.lower() == 'nan':
                continue
            if wm not in self.gender_concentration_flags:
                continue
            u1 = r.get('custom_u1')
            if u1 is None or (isinstance(u1, float) and pd.isna(u1)):
                declared = ''
            else:
                declared = str(u1).strip().upper()
            if declared != 'WOMAN':
                continue

            flags = r.get('flags')
            if not isinstance(flags, list):
                flags = [] if flags is None else [str(flags)]
                r['flags'] = flags
            if 'WOMAN_CONCENTRATION' in flags:
                continue

            conc = self.gender_concentration_flags[wm]
            if woman_risk > 0:
                try:
                    rs = int(r.get('risk_score', 0) or 0)
                except (TypeError, ValueError):
                    rs = 0
                r['risk_score'] = min(rs + woman_risk, 100)

            flags.append('WOMAN_CONCENTRATION')

            det = r.get('details')
            if not isinstance(det, dict):
                det = {}
                r['details'] = det
            det['woman_concentration'] = {
                'affiliate': wm,
                'woman_pct': conc['woman_pct'],
                'women': conc['women'],
                'total': conc['total'],
            }

    def build_affiliate_domain_concentration_map(self, df):
        """
        Per-affiliate batch pass: flag domains (except excluded, default gmail.com only)
        that exceed a share threshold.
        """
        self.affiliate_domain_concentration_flags = {}

        email_col = self.column_map.get('email')
        if not email_col or email_col not in df.columns:
            return

        threshold_pct = float(
            self._get_config('affiliate_domain_concentration_threshold', 0.05)
        ) * 100.0
        min_sample = int(self._get_config('affiliate_domain_concentration_min_sample', 20))
        exclude = self._domain_concentration_exclude_domains()

        aff_domains = defaultdict(list)

        for _, row in df.iterrows():
            raw = row.get(email_col)
            if pd.isna(raw) or raw is None:
                continue
            email = str(raw).lower().strip()
            if '@' not in email:
                continue
            domain = email.split('@', 1)[1].strip().lower()
            if not domain:
                continue

            aff = self.get_column(row, 'webmaster_code', None)
            if not aff:
                for col in ('webmaster_code', 'site_code'):
                    if col in row.index and pd.notna(row[col]) and str(row[col]).strip().lower() not in ('', 'nan'):
                        aff = row[col]
                        break
            if not aff or str(aff).strip().lower() in ('', 'nan'):
                continue
            aff_s = str(aff).strip()
            aff_domains[aff_s].append(domain)

        for aff, domains in aff_domains.items():
            total = len(domains)
            if total < min_sample:
                continue
            counts = Counter(domains)
            for domain, count in counts.items():
                if domain in exclude:
                    continue
                pct = count / total * 100.0
                if pct >= threshold_pct:
                    self.affiliate_domain_concentration_flags[(aff, domain)] = {
                        'pct': round(pct, 2),
                        'count': int(count),
                        'total': int(total),
                    }

        if self.affiliate_domain_concentration_flags:
            print(
                f"Found {len(self.affiliate_domain_concentration_flags)} "
                "affiliate/domain concentration cluster(s)"
            )

    def apply_affiliate_domain_concentration_to_results(self, results):
        """
        Add AFFILIATE_DOMAIN_CONCENTRATION flag for rows on a concentrated domain within
        their affiliate. Run after build_affiliate_domain_concentration_map(df).
        """
        if not results or not self.affiliate_domain_concentration_flags:
            return
        try:
            pts = int(self.get_risk_score('affiliate_domain_concentration') or 0)
        except (TypeError, ValueError):
            pts = 0

        for r in results:
            wm = str(r.get('webmaster_code') or '').strip()
            if not wm or wm.lower() == 'nan':
                continue
            raw = r.get('email')
            if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                continue
            email = str(raw).lower().strip()
            if '@' not in email:
                continue
            domain = email.split('@', 1)[1].strip().lower()
            if self.is_privacy_relay_domain(domain):
                continue
            key = (wm, domain)
            if key not in self.affiliate_domain_concentration_flags:
                continue

            flags = r.get('flags')
            if not isinstance(flags, list):
                flags = [] if flags is None else [str(flags)]
                r['flags'] = flags
            if 'AFFILIATE_DOMAIN_CONCENTRATION' in flags:
                continue

            info = self.affiliate_domain_concentration_flags[key]
            if pts > 0:
                try:
                    rs = int(r.get('risk_score', 0) or 0)
                except (TypeError, ValueError):
                    rs = 0
                r['risk_score'] = min(rs + pts, 100)

            flags.append('AFFILIATE_DOMAIN_CONCENTRATION')

            det = r.get('details')
            if not isinstance(det, dict):
                det = {}
                r['details'] = det
            det['affiliate_domain_concentration'] = {
                'affiliate': wm,
                'domain': domain,
                'pct': info['pct'],
                'count': info['count'],
                'total': info['total'],
            }

    def build_ip_velocity_map(self, df, db=None):
        """
        Detect IPs with high signup velocity (fraud ring indicator).

        For incremental runs a small batch may show no velocity on its own.
        When a `db` reference is provided, historical timestamps from
        fraud_results are loaded first so velocity is evaluated across all
        time, not just the current batch.
        """
        ip_col          = self.column_map.get('ip')
        trans_datetime_col = self.column_map.get('trans_datetime')

        if not ip_col:
            return

        # Load whitelist
        whitelist = set()
        if self.config:
            whitelist = {str(ip).strip() for ip in self.config.get('whitelisted_ips', [])}

        # ── Step 1: seed from DB historical timestamps ────────────────────────
        ip_signups = defaultdict(list)

        if db is not None:
            # Determine affiliates in batch for scoped lookup
            aff_col = self.column_map.get('webmaster_code')
            batch_affiliates = set()
            if aff_col and aff_col in df.columns:
                batch_affiliates = set(df[aff_col].dropna().unique())

            for aff in (batch_affiliates or [None]):
                hist = db.get_ip_timestamps(affiliate=aff if aff else None)
                for ip_str, ts_list in hist.items():
                    if ip_str in whitelist:
                        continue
                    for ts_raw in ts_list:
                        try:
                            ip_signups[ip_str].append(pd.to_datetime(ts_raw))
                        except Exception:
                            continue

        # ── Step 2: add current batch timestamps ─────────────────────────────
        if trans_datetime_col:
            for _, row in df.iterrows():
                ip        = row.get(ip_col) if ip_col in row else None
                timestamp = row.get(trans_datetime_col) if trans_datetime_col in row else None
                if not ip or str(ip).strip() in whitelist:
                    continue
                if pd.notna(ip) and pd.notna(timestamp):
                    try:
                        ip_signups[str(ip).strip()].append(pd.to_datetime(timestamp))
                    except Exception:
                        continue

        # ── Step 3: evaluate velocity for each IP ────────────────────────────
        for ip, timestamps in ip_signups.items():
            if len(timestamps) < 3:
                continue

            timestamps_sorted = sorted(timestamps)
            one_hour_max = 0
            day_max      = 0

            for i in range(len(timestamps_sorted)):
                t0 = timestamps_sorted[i]
                one_hour_max = max(one_hour_max,
                    sum(1 for ts in timestamps_sorted if t0 <= ts <= t0 + pd.Timedelta(hours=1)))
                day_max = max(day_max,
                    sum(1 for ts in timestamps_sorted if t0 <= ts <= t0 + pd.Timedelta(days=1)))

            if one_hour_max >= 5 or day_max >= 10:
                self.ip_velocity_flags[ip] = {
                    'total_signups': len(timestamps),
                    'max_per_hour':  one_hour_max,
                    'max_per_day':   day_max,
                    'risk_level':    'HIGH' if one_hour_max >= 10 else 'MEDIUM',
                }

        if self.ip_velocity_flags:
            print(f"Found {len(self.ip_velocity_flags)} IPs with high signup velocity"
                  + (" [DB-backed]" if db else " [batch-only]"))
            top = sorted(self.ip_velocity_flags.items(),
                         key=lambda x: x[1]['max_per_hour'], reverse=True)[:3]
            for ip, data in top:
                print(f"  {ip}: {data['max_per_hour']}/hr  {data['max_per_day']}/day")

    def build_shared_ip_map(self, df, db=None):
        """
        Detect IPs used by multiple distinct accounts *within the same affiliate*.

        For incremental (new-data-only) runs the current batch may be small, so
        the same IP might not repeat within it — yet it could already have many
        accounts in fraud_results from prior runs.  When a `db` reference is
        provided we seed the count map with historical data from the DB first,
        then add the current batch on top.  This way the threshold is evaluated
        against all-time account counts, not just the current batch.

        Flagging is intentionally scoped per-affiliate so that a shared IP that
        spans many different affiliates (e.g. a QA tester or a large CGN range)
        does not create false positives against unrelated affiliates.

        Thresholds (configurable via config risk_scores):
          MEDIUM: 3–9 unique accounts on the same IP within one affiliate
          HIGH:   10+ unique accounts on the same IP within one affiliate

        IPs in the whitelisted_ips config list are skipped entirely.
        """
        ip_col   = self.column_map.get('ip')
        duid_col = self.column_map.get('duid')
        aff_col  = self.column_map.get('webmaster_code')

        if not ip_col:
            return

        # Load IP whitelist
        whitelist = set()
        if self.config:
            whitelist = {str(ip).strip() for ip in self.config.get('whitelisted_ips', [])}

        # ── Step 1: seed from DB historical counts ────────────────────────────
        # {(ip, affiliate): set_of_known_duids}  — we only need the count but
        # using sets lets us avoid double-counting DUIDs already in the batch.
        from collections import defaultdict
        ip_aff_duids: dict = defaultdict(set)

        if db is not None:
            # Determine which affiliates are present in the current batch so we
            # only pull the DB rows we actually need (fast even on large DBs).
            batch_affiliates: set = set()
            if aff_col and aff_col in df.columns:
                batch_affiliates = set(df[aff_col].dropna().unique())

            for aff in (batch_affiliates or [None]):
                hist = db.get_ip_account_counts(affiliate=aff if aff else None)
                for ip_str, count in hist.items():
                    if ip_str in whitelist:
                        continue
                    # We store a synthetic placeholder set of the right size so
                    # we can still add real batch DUIDs on top without duplication.
                    # Using frozenset-size trick: pad with negative ints as placeholders.
                    key = (ip_str, str(aff) if aff else '__unknown__')
                    ip_aff_duids[key] = set(range(-count, 0))  # placeholder historical accounts

        # ── Step 2: add current batch accounts ───────────────────────────────
        for _, row in df.iterrows():
            ip = row.get(ip_col) if ip_col in row else None
            if not ip or str(ip).strip() in ('', 'nan', 'None'):
                continue
            ip_str = str(ip).strip()
            if ip_str in whitelist:
                continue

            aff = None
            if aff_col and aff_col in row:
                aff = row.get(aff_col)
            aff = str(aff).strip() if aff else '__unknown__'

            uid = None
            if duid_col and duid_col in row:
                uid = row.get(duid_col)
            if not uid:
                uid = row.get(self.column_map.get('email', 'email'), None)
            if uid:
                key = (ip_str, aff)
                # Remove the placeholder for this DUID if it existed historically
                ip_aff_duids[key].discard(uid)
                ip_aff_duids[key].add(str(uid))

        # ── Step 3: build flag map ────────────────────────────────────────────
        self.shared_ip_flags = {}
        for (ip, aff), duids in ip_aff_duids.items():
            n = len(duids)
            if n >= 3:
                level = 'HIGH' if n >= 10 else 'MEDIUM'
                existing = self.shared_ip_flags.get(ip)
                if not existing or (level == 'HIGH' and existing['risk_level'] != 'HIGH'):
                    self.shared_ip_flags[ip] = {
                        'account_count': n,
                        'risk_level':    level,
                        'affiliate':     aff,
                    }

        flagged = len(self.shared_ip_flags)
        if flagged:
            high = sum(1 for v in self.shared_ip_flags.values() if v['risk_level'] == 'HIGH')
            med  = flagged - high
            print(f"Found {flagged} shared IPs within affiliates "
                  f"({high} HIGH ≥10 accts, {med} MEDIUM 3–9 accts)"
                  + (" [DB-backed]" if db else " [batch-only]"))
            top = sorted(self.shared_ip_flags.items(),
                         key=lambda x: x[1]['account_count'], reverse=True)[:5]
            for ip, data in top:
                print(f"  {ip}: {data['account_count']} accounts "
                      f"[{data['risk_level']}] in affiliate {data['affiliate']}")

    def detect_repeated_word_clusters(self, df):
        """Group emails by repeated words found in the dataset"""
        word_clusters = defaultdict(list)
        email_col = self.column_map.get('email')

        if not email_col or not self.repeated_words:
            return {}

        for idx, row in df.iterrows():
            email = row[email_col]
            if pd.notna(email):
                username = str(email).lower().split('@')[0]
                words = self.extract_words_from_username(username)
                for word in words:
                    if word in self.repeated_words and self.repeated_words[word] > 3:
                        word_clusters[word].append({
                            'email': email,
                            'DUID': self.get_column(row, 'duid', 'N/A'),
                            'payout_amount': self.get_column(row, 'payout_amount', 0)
                        })

        return dict(word_clusters)

    def detect_suspicious_name_clusters(self, df):
        """Detect clustering of suspicious names across accounts"""
        name_clusters = defaultdict(list)
        email_col = self.column_map.get('email')

        if not email_col:
            return {}

        for idx, row in df.iterrows():
            email = row[email_col]
            if pd.notna(email):
                email_lower = str(email).lower().split('@')[0]  # Get username only
                for name in self.suspicious_names:
                    if name in email_lower:
                        name_clusters[name].append({
                            'email': email,
                            'DUID': self.get_column(row, 'duid', 'N/A'),
                            'payout_amount': self.get_column(row, 'payout_amount', 0)
                        })

        return dict(name_clusters)

    def load_data_file(self, file_path):
        """Load data from CSV or Excel file"""
        file_extension = Path(file_path).suffix.lower()

        try:
            if file_extension == '.csv':
                df = pd.read_csv(file_path)
            elif file_extension in ['.xls', '.xlsx']:
                df = pd.read_excel(file_path)
            else:
                raise ValueError(f"Unsupported file format: {file_extension}. Supported formats: .csv, .xls, .xlsx")

            return df
        except Exception as e:
            raise Exception(f"Error loading file {file_path}: {str(e)}")

    def process_leads_file(self, file_path):
        """Process the entire leads file (CSV or Excel)"""
        print(f"Loading data from {file_path}...")
        df = self.load_data_file(file_path)

        # Normalize column names
        df = self.normalize_column_names(df)

        print(f"Analyzing {len(df)} leads...")
        print(f"Detected columns: {', '.join(self.column_map.values())}")

        # Build repeated word patterns map from entire dataset (must happen BEFORE analyzing individual emails)
        self.build_repeated_word_map(df)

        # Build IP-level pre-passes (must happen BEFORE per-account analysis)
        self.build_shared_ip_map(df)
        self.build_ip_velocity_map(df)

        # Build gender concentration map (batch-level pre-pass)
        self.build_gender_concentration_map(df)
        self.build_sequential_email_map(df)
        self.build_affiliate_domain_concentration_map(df)

        # Analyze each email
        results = []
        email_col = self.column_map.get('email')

        if not email_col:
            raise ValueError("Could not find 'Email' column in the data. Available columns: " + ", ".join(df.columns))

        for idx, row in df.iterrows():
            # Extract first_name and custom_u1 for gender mismatch check (paid records only)
            first_name = self.get_column(row, 'first_name', None)
            custom_u1 = self.get_column(row, 'custom_u1', None)
            if custom_u1 in (None, '', 'N/A') or (
                isinstance(custom_u1, float) and pd.isna(custom_u1)
            ):
                custom_u1 = self.get_column(row, 'user1', None)

            webmaster_code = self.get_column(row, 'webmaster_code', None)
            if not webmaster_code:
                for col in ('webmaster_code', 'site_code'):
                    if col in row.index and pd.notna(row[col]) and str(row[col]).strip().lower() not in ('', 'nan'):
                        webmaster_code = row[col]
                        break

            analysis = self.analyze_email(
                row[email_col],
                trans_datetime=self.get_column(row, 'trans_datetime', None),
                pov_verified=self.get_column(row, 'pov_verified', None),
                pov_verified_time=self.get_column(row, 'pov_verified_time', None),
                ip_address=self.get_column(row, 'ip', None),
                user_agent=self.get_column(row, 'user_agent', None),
                first_name=first_name,
                user1=custom_u1  # custom_u1 contains declared gender
            )
            results.append({
                **analysis,
                'webmaster_code': webmaster_code,
                'custom_u1': custom_u1,
                'DUID': self.get_column(row, 'duid', 'N/A'),
                'username': self.get_column(row, 'username', 'N/A'),
                'payout_amount': self.get_column(row, 'payout_amount', 0),
                'sale_amount': self.get_column(row, 'sale_amount', 0),
                'campaign': self.get_column(row, 'campaign', 'N/A'),
                'IP': self.get_column(row, 'ip', 'N/A'),
                'ad_id': self.get_column(row, 'ad_id', 'N/A'),
                'transaction_date': self.get_column(row, 'transaction_date', 'N/A')
            })

        results_df = pd.DataFrame(results)

        # Theme clustering
        print("Detecting theme clusters...")
        theme_clusters = self.detect_theme_clusters(df)

        # Flag accounts in theme clusters
        for theme, accounts in theme_clusters.items():
            if len(accounts) >= 3:  # Only flag if 3+ accounts with same theme
                for account in accounts:
                    mask = results_df['email'] == account['email']
                    if mask.any():
                        idx = results_df[mask].index[0]
                        results_df.at[idx, 'risk_score'] += self.get_risk_score('theme_cluster')
                        current_flags = results_df.at[idx, 'flags']
                        if isinstance(current_flags, list):
                            current_flags.append(f'THEME_CLUSTER_{theme.upper()}')
                        results_df.at[idx, 'flags'] = current_flags

        # Suspicious name clustering
        print("Detecting suspicious name patterns...")
        name_clusters = self.detect_suspicious_name_clusters(df)

        # Repeated word clustering (dynamic detection)
        print("Detecting repeated word clusters...")
        word_clusters = self.detect_repeated_word_clusters(df)

        # Gender concentration flagging (post-pass; uses per-row webmaster_code + custom_u1 on results)
        if self.gender_concentration_flags or self.sequential_email_flags or self.affiliate_domain_concentration_flags:
            print("Applying batch affiliate flags (gender / sequential email / domain concentration)...")
            recs = results_df.to_dict('records')
            self.apply_gender_concentration_to_results(recs)
            self.apply_sequential_email_to_results(recs)
            self.apply_affiliate_domain_concentration_to_results(recs)
            results_df = pd.DataFrame(recs)

        return results_df, theme_clusters, name_clusters, word_clusters

    def generate_report(self, results_df, theme_clusters, name_clusters, word_clusters, output_path='fraud_report.csv'):
        """Generate comprehensive fraud detection report"""

        # Sort by risk score
        high_risk = results_df[results_df['risk_score'] >= 50].sort_values('risk_score', ascending=False)
        medium_risk = results_df[(results_df['risk_score'] >= 25) & (results_df['risk_score'] < 50)].sort_values('risk_score', ascending=False)

        print("\n" + "="*80)
        print("EMAIL FRAUD DETECTION REPORT")
        print("="*80)
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total Leads Analyzed: {len(results_df)}")
        print(f"\nHIGH RISK (Score >= 50): {len(high_risk)} accounts")
        print(f"MEDIUM RISK (Score 25-49): {len(medium_risk)} accounts")
        print(f"LOW RISK (Score < 25): {len(results_df) - len(high_risk) - len(medium_risk)} accounts")

        # Theme cluster summary
        if theme_clusters:
            print("\n" + "-"*80)
            print("THEME CLUSTER DETECTION")
            print("-"*80)
            for theme, accounts in theme_clusters.items():
                if len(accounts) >= 3:
                    total_payout = sum(acc.get('payout_amount', 0) for acc in accounts)
                    print(f"  {theme.upper()}: {len(accounts)} accounts (Total Payout: ${total_payout:,.2f})")

        # Suspicious name cluster summary
        if name_clusters:
            print("\n" + "-"*80)
            print("SUSPICIOUS NAME PATTERNS (Hardcoded)")
            print("-"*80)
            for name, accounts in name_clusters.items():
                total_payout = sum(acc.get('payout_amount', 0) for acc in accounts)
                print(f"  {name.upper()}: {len(accounts)} accounts (Total Payout: ${total_payout:,.2f})")
                # Show first few email examples
                example_emails = [acc['email'] for acc in accounts[:3]]
                print(f"    Examples: {', '.join(example_emails)}")

        # Repeated word cluster summary (dynamic detection)
        if word_clusters:
            print("\n" + "-"*80)
            print("REPEATED WORD PATTERNS (Dynamic Detection)")
            print("-"*80)
            # Sort by frequency (most repeated first)
            sorted_clusters = sorted(word_clusters.items(), key=lambda x: len(x[1]), reverse=True)
            for word, accounts in sorted_clusters[:10]:  # Show top 10
                total_payout = sum(acc.get('payout_amount', 0) for acc in accounts)
                print(f"  '{word}': {len(accounts)} accounts (Total Payout: ${total_payout:,.2f})")
                # Show first few email examples
                example_emails = [acc['email'] for acc in accounts[:3]]
                print(f"    Examples: {', '.join(example_emails)}")

        # High risk accounts detail
        if len(high_risk) > 0:
            print("\n" + "-"*80)
            print("TOP 10 HIGH RISK ACCOUNTS")
            print("-"*80)
            for idx, row in high_risk.head(10).iterrows():
                print(f"\n  Email: {row['email']}")
                print(f"  DUID: {row['DUID']}")
                print(f"  Risk Score: {row['risk_score']}")
                print(f"  Flags: {', '.join(row['flags']) if row['flags'] else 'None'}")
                print(f"  Payout Amount: ${row['payout_amount']:,.2f}")
                if 'sale_amount' in row and pd.notna(row['sale_amount']):
                    print(f"  Sale Amount: ${row['sale_amount']:,.2f}")
                if row['details']:
                    print(f"  Details: {row['details']}")

        # Save detailed results
        results_df.to_csv(output_path, index=False)
        print(f"\n{'='*80}")
        print(f"Full detailed report saved to: {output_path}")
        print(f"{'='*80}\n")

        # Create summary CSV for high-risk accounts
        summary_columns = ['email', 'DUID', 'risk_score', 'flags', 'payout_amount', 'campaign', 'IP']
        # Add optional columns if they exist
        if 'sale_amount' in high_risk.columns:
            summary_columns.append('sale_amount')
        if 'ad_id' in high_risk.columns:
            summary_columns.append('ad_id')
        if 'transaction_date' in high_risk.columns:
            summary_columns.append('transaction_date')

        high_risk_summary = high_risk[summary_columns]
        high_risk_path = output_path.replace('.csv', '_HIGH_RISK.csv')
        high_risk_summary.to_csv(high_risk_path, index=False)
        print(f"High-risk accounts saved to: {high_risk_path}\n")

        return high_risk, medium_risk


def find_data_files(data_dir='../data'):
    """Find all CSV and Excel files in the data directory"""
    data_path = Path(__file__).parent / data_dir
    if not data_path.exists():
        return []

    patterns = ['*.csv', '*.xls', '*.xlsx']
    files = []
    for pattern in patterns:
        files.extend(data_path.glob(pattern))

    return sorted(files)


def select_file_interactive(files):
    """Allow user to select a file interactively"""
    if not files:
        print("No data files found in the data/ directory.")
        print("Supported formats: .csv, .xls, .xlsx")
        return None

    print("\nAvailable data files:")
    print("-" * 60)
    for i, file in enumerate(files, 1):
        file_size = file.stat().st_size / 1024  # Size in KB
        print(f"  {i}. {file.name} ({file_size:.1f} KB)")

    print("-" * 60)

    while True:
        try:
            choice = input("\nSelect file number (or 'q' to quit): ").strip()
            if choice.lower() == 'q':
                return None
            choice = int(choice)
            if 1 <= choice <= len(files):
                return files[choice - 1]
            else:
                print(f"Please enter a number between 1 and {len(files)}")
        except ValueError:
            print("Please enter a valid number or 'q' to quit")
        except KeyboardInterrupt:
            print("\n\nOperation cancelled.")
            return None


def get_output_path(input_file, reports_dir='../reports'):
    """Generate output path based on input file name"""
    reports_path = Path(__file__).parent / reports_dir
    reports_path.mkdir(exist_ok=True)

    input_name = Path(input_file).stem  # Get filename without extension
    output_file = reports_path / f"{input_name}_fraud_report.csv"

    return str(output_file)


def parse_fraud_results_flags(val):
    """Parse flags column from fraud_results (JSON or Python repr)."""
    if val is None:
        return []
    if isinstance(val, list):
        return list(val)
    s = str(val).strip()
    if not s:
        return []
    try:
        return json.loads(s.replace("'", '"') if s.startswith('[') else '[]')
    except Exception:
        pass
    try:
        v = ast.literal_eval(s)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def parse_fraud_results_details(val):
    """Parse details column from fraud_results (Python repr or JSON object)."""
    if val is None:
        return {}
    if isinstance(val, dict):
        return dict(val)
    s = str(val).strip()
    if not s or s == '{}':
        return {}
    try:
        v = ast.literal_eval(s)
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    try:
        d = json.loads(s)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def normalize_duid_join_key(val):
    """
    Canonical DUID string for matching fraud_results ↔ free/paid.

    Pandas/SQLite often disagree on ``384046981`` vs ``384046981.0`` vs int/float;
    plain ``=`` joins then miss. Use this for lookup keys only.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        s = str(val).strip()
    except Exception:
        return None
    if not s or s.lower() in ('nan', 'none'):
        return None
    if re.fullmatch(r'-?\d+\.0', s):
        s = s[:-2]
    try:
        f = float(s)
        if abs(f - int(f)) < 1e-9 and abs(f) < 1e15:
            return str(int(f))
    except (ValueError, OverflowError):
        pass
    return s


def _first_nonempty_str(*vals):
    for v in vals:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        t = str(v).strip()
        if t and t.lower() not in ('nan', 'none'):
            return t
    return None


def _merged_fraud_results_for_rescore(db):
    """
    Load fraud_results and overlay email / webmaster_code / custom_u1 from free & paid
    using normalize_duid_join_key (fixes float/string DUID mismatches).

    Returns:
        (DataFrame with columns id, duid, email, webmaster_code, custom_u1, risk_score, flags, details,
         dict stats: fraud_results_rows, free_rows, paid_rows)
    """
    stats = {'fraud_results_rows': 0, 'free_rows': 0, 'paid_rows': 0}
    with db.get_connection() as conn:
        fr = pd.read_sql_query(
            """SELECT id, duid, email, webmaster_code, custom_u1, data_type,
                      risk_score, flags, details
               FROM fraud_results""",
            conn,
        )
        try:
            free = pd.read_sql_query(
                'SELECT duid, email, user1, webmaster_code, site_code FROM free',
                conn,
            )
        except Exception:
            free = pd.DataFrame()
        try:
            paid = pd.read_sql_query(
                'SELECT duid, email, custom_u1, webmaster_code FROM paid',
                conn,
            )
        except Exception:
            paid = pd.DataFrame()

    stats['fraud_results_rows'] = int(len(fr))
    stats['free_rows'] = int(len(free)) if not free.empty else 0
    stats['paid_rows'] = int(len(paid)) if not paid.empty else 0

    free_by = {}
    if not free.empty:
        for _, r in free.iterrows():
            dk = normalize_duid_join_key(r.get('duid'))
            if dk:
                free_by[dk] = r
    paid_by = {}
    if not paid.empty:
        for _, r in paid.iterrows():
            dk = normalize_duid_join_key(r.get('duid'))
            if dk:
                paid_by[dk] = r

    rows = []
    for _, row in fr.iterrows():
        dk = normalize_duid_join_key(row.get('duid'))
        frow = free_by.get(dk) if dk else None
        prow = paid_by.get(dk) if dk else None
        fe = frow if frow is not None else None
        pe = prow if prow is not None else None

        email = _first_nonempty_str(
            row.get('email'),
            pe['email'] if pe is not None else None,
            fe['email'] if fe is not None else None,
        )
        wm = _first_nonempty_str(
            row.get('webmaster_code'),
            pe['webmaster_code'] if pe is not None else None,
            fe['webmaster_code'] if fe is not None else None,
            fe['site_code'] if fe is not None else None,
        )
        u1 = _first_nonempty_str(
            row.get('custom_u1'),
            pe['custom_u1'] if pe is not None else None,
            fe['user1'] if fe is not None else None,
        )

        rows.append({
            'id': row.get('id'),
            'duid': row['duid'],
            'email': email,
            'webmaster_code': wm,
            'custom_u1': u1,
            'risk_score': row.get('risk_score'),
            'flags': row.get('flags'),
            'details': row.get('details'),
        })

    return pd.DataFrame(rows), stats


def rescore_woman_concentration_from_fraud_results_table(db, config=None):
    """
    Re-apply WOMAN concentration flags to existing fraud_results rows only.

    Reads fraud_results; resolves ``custom_u1`` / ``webmaster_code`` from ``paid`` /
    ``free`` when columns on ``fraud_results`` are empty (same idea as save-time backfill).
    Matches free/paid rows by **normalized DUID** so float/string mismatches still join.
    Idempotent: rows that already have WOMAN_CONCENTRATION are skipped.

    Returns a summary dict suitable for JSON APIs.
    """
    merged, stats = _merged_fraud_results_for_rescore(db)
    if merged.empty:
        return {
            'updated': 0,
            'rows_considered': 0,
            'affiliates_over_threshold': 0,
            'message': 'fraud_results table is empty.',
            **stats,
        }

    df = merged[
        merged['custom_u1'].notna()
        & (merged['custom_u1'].astype(str).str.strip() != '')
    ].copy()

    if df.empty:
        return {
            'updated': 0,
            'rows_considered': 0,
            'affiliates_over_threshold': 0,
            'message': (
                'No rows with resolvable declared gender '
                '(fraud_results.custom_u1 and paid/free are still empty for these DUIDs).'
            ),
            **stats,
        }

    detector = EmailFraudDetector(config)
    detector.normalize_column_names(df)
    detector.build_gender_concentration_map(df)

    if not detector.gender_concentration_flags:
        return {
            'updated': 0,
            'rows_considered': int(len(df)),
            'affiliates_over_threshold': 0,
            'message': 'No affiliate exceeds the woman concentration threshold.',
            **stats,
        }

    results = []
    for _, row in df.iterrows():
        duid = row.get('duid')
        if duid is None or str(duid).strip() == '':
            continue
        rid = row.get('id')
        if rid is None or (isinstance(rid, float) and pd.isna(rid)):
            continue
        results.append({
            '_fr_id': int(rid),
            'DUID': duid,
            'webmaster_code': row.get('webmaster_code'),
            'custom_u1': row.get('custom_u1'),
            'risk_score': int(row['risk_score']) if pd.notna(row.get('risk_score')) else 0,
            'flags': parse_fraud_results_flags(row.get('flags')),
            'details': parse_fraud_results_details(row.get('details')),
        })

    snapshots = {}
    for r in results:
        rid = r.get('_fr_id')
        if rid is None:
            continue
        snapshots[int(rid)] = (
            int(r.get('risk_score') or 0),
            copy.deepcopy(r['flags']),
            copy.deepcopy(r['details']),
        )

    detector.apply_gender_concentration_to_results(results)

    updated = 0
    with db.get_connection() as conn:
        cur = conn.cursor()
        for r in results:
            rid = r.get('_fr_id')
            if rid is None or int(rid) not in snapshots:
                continue
            old_rs, old_flags, old_det = snapshots[int(rid)]
            new_rs = int(r.get('risk_score') or 0)
            new_flags = r['flags']
            new_det = r['details']
            if (
                old_rs == new_rs
                and old_flags == new_flags
                and old_det == new_det
            ):
                continue
            cur.execute(
                """UPDATE fraud_results
                   SET risk_score = ?, flags = ?, details = ?
                   WHERE id = ?""",
                (new_rs, str(new_flags), str(new_det), int(rid)),
            )
            if cur.rowcount:
                updated += 1

    out = {
        'updated': updated,
        'rows_considered': len(results),
        'affiliates_over_threshold': len(detector.gender_concentration_flags),
        'affiliates': sorted(detector.gender_concentration_flags.keys()),
    }
    out.update(stats)
    return out


def rescore_sequential_email_from_fraud_results_table(db, config=None):
    """
    Re-apply SEQUENTIAL_EMAIL flags on existing fraud_results only (no full re-analysis).

    Resolves ``email`` / ``webmaster_code`` from ``paid`` / ``free`` when ``fraud_results``
    columns are empty, using **normalized DUID** keys so joins match despite type drift.

    Idempotent for rows that already list SEQUENTIAL_EMAIL.
    """
    merged, stats = _merged_fraud_results_for_rescore(db)
    if merged.empty:
        return {
            'updated': 0,
            'rows_considered': 0,
            'clusters_found': 0,
            'message': 'fraud_results table is empty.',
            **stats,
        }

    em = merged['email'].astype(str)
    df = merged[
        merged['email'].notna()
        & (em.str.strip() != '')
        & em.str.lower().str.contains('@', regex=False)
    ].copy()

    if df.empty:
        return {
            'updated': 0,
            'rows_considered': 0,
            'clusters_found': 0,
            'message': (
                'No rows with a resolvable email address '
                '(fraud_results.email and paid/free.email are still empty for these DUIDs).'
            ),
            **stats,
        }

    detector = EmailFraudDetector(config)
    detector.normalize_column_names(df)
    detector.build_sequential_email_map(df)

    if not detector.sequential_email_flags:
        return {
            'updated': 0,
            'rows_considered': int(len(df)),
            'clusters_found': 0,
            'message': 'No per-affiliate sequential email clusters (need 4+ distinct numeric suffixes per stem/domain).',
            **stats,
        }

    results = []
    for _, row in df.iterrows():
        duid = row.get('duid')
        if duid is None or str(duid).strip() == '':
            continue
        rid = row.get('id')
        if rid is None or (isinstance(rid, float) and pd.isna(rid)):
            continue
        results.append({
            '_fr_id': int(rid),
            'DUID': duid,
            'email': row.get('email'),
            'webmaster_code': row.get('webmaster_code'),
            'risk_score': int(row['risk_score']) if pd.notna(row.get('risk_score')) else 0,
            'flags': parse_fraud_results_flags(row.get('flags')),
            'details': parse_fraud_results_details(row.get('details')),
        })

    snapshots = {}
    for r in results:
        rid = r.get('_fr_id')
        if rid is None:
            continue
        snapshots[int(rid)] = (
            int(r.get('risk_score') or 0),
            copy.deepcopy(r['flags']),
            copy.deepcopy(r['details']),
        )

    detector.apply_sequential_email_to_results(results)

    updated = 0
    with db.get_connection() as conn:
        cur = conn.cursor()
        for r in results:
            rid = r.get('_fr_id')
            if rid is None or int(rid) not in snapshots:
                continue
            old_rs, old_flags, old_det = snapshots[int(rid)]
            new_rs = int(r.get('risk_score') or 0)
            new_flags = r['flags']
            new_det = r['details']
            if (
                old_rs == new_rs
                and old_flags == new_flags
                and old_det == new_det
            ):
                continue
            cur.execute(
                """UPDATE fraud_results
                   SET risk_score = ?, flags = ?, details = ?
                   WHERE id = ?""",
                (new_rs, str(new_flags), str(new_det), int(rid)),
            )
            if cur.rowcount:
                updated += 1

    cluster_summary = [
        {'affiliate': k[0], 'stem': k[1], 'domain': k[2], 'distinct_suffixes': v['count']}
        for k, v in sorted(detector.sequential_email_flags.items(), key=lambda x: (-x[1]['count'], x[0][0]))
    ]

    out = {
        'updated': updated,
        'rows_considered': len(results),
        'clusters_found': len(detector.sequential_email_flags),
        'clusters': cluster_summary[:50],
    }
    out.update(stats)
    return out


# Main execution
if __name__ == "__main__":
    print("="*80)
    print("EMAIL FRAUD DETECTION SYSTEM")
    print("="*80)

    detector = EmailFraudDetector()
    input_file = None

    # Check for command-line argument
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
        if not os.path.exists(input_file):
            print(f"\nERROR: File not found: {input_file}")
            sys.exit(1)
    else:
        # Interactive file selection
        available_files = find_data_files()
        input_file = select_file_interactive(available_files)

        if input_file is None:
            print("\nNo file selected. Exiting.")
            sys.exit(0)

    # Generate output path based on input file name
    output_path = get_output_path(input_file)

    try:
        results_df, theme_clusters, name_clusters, word_clusters = detector.process_leads_file(str(input_file))
        high_risk, medium_risk = detector.generate_report(
            results_df,
            theme_clusters,
            name_clusters,
            word_clusters,
            output_path=output_path
        )

        print("✓ Analysis complete!")
        print("\nNext Steps:")
        high_risk_path = output_path.replace('.csv', '_HIGH_RISK.csv')
        print(f"1. Review {high_risk_path} for priority investigations")
        print(f"2. Check {output_path} for complete analysis")
        print("3. Focus on accounts with REPEATED_WORD_PATTERN (dynamic detection)")
        print("4. Review accounts with NAME_NUMBER_PATTERN and SUSPICIOUS_NAME flags")
        print("5. Investigate accounts with SCRAMBLED_PATTERN (improved detection)")
        print("6. Check accounts with AFFILIATE_DOMAIN_CONCENTRATION + other flags")

    except Exception as e:
        print(f"\nERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
