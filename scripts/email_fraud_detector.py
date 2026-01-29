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
import time
import requests

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
        
        # Major email providers to whitelist for domain concentration
        self.major_providers = [
            'gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com',
            'aol.com', 'icloud.com', 'protonmail.com', 'mail.com'
        ]

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
            'domain_concentration': 20,
            'pov_instant_20s': 50,
            'pov_instant_40s': 40,
            'pov_fast_60s': 30,
            'ip_velocity_high': 30,
            'ip_velocity_medium': 5,
            'desktop_windows_10': 20,
            'desktop_other': 10,
            'us_state_cluster': 25,
            'us_city_state_cluster': 30,
            'intl_country_city_cluster': 30,
            'theme_cluster': 15
        }
        
        if self.config:
            config_scores = self.config.get('risk_scores', {})
            # Merge with defaults (config takes precedence)
            return {**defaults, **config_scores}
        
        return defaults
    
    def get_risk_score(self, key):
        """Get a specific risk score value"""
        return self.risk_scores.get(key, 0)

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
        
        Args:
            df: DataFrame with IP addresses
        """
        ip_col = self.column_map.get('ip')
        if not ip_col:
            return
        
        print("Building geographic cluster maps (this may take a moment)...")
        
        # Track geographic occurrences
        us_state_counts = Counter()  # state -> count
        us_city_state_counts = Counter()  # (city, state) -> count
        intl_country_city_counts = Counter()  # (city, country_code) -> count
        
        # Get unique IPs to minimize API calls
        unique_ips = df[ip_col].dropna().unique()
        
        for ip in unique_ips:
            geo = self.get_ip_geolocation(ip)
            if not geo:
                continue
            
            country_code = geo.get('country_code')
            region = geo.get('region')  # State/province
            city = geo.get('city')
            
            if country_code == 'US' and region:
                us_state_counts[region] += 1
                if city:
                    us_city_state_counts[(city, region)] += 1
            elif country_code and country_code != 'US' and city:
                intl_country_city_counts[(city, country_code)] += 1
        
        # Flag locations with 3+ accounts as suspicious clusters
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
        
        print(f"  Found {len(self.us_state_cluster_flags)} US state clusters")
        print(f"  Found {len(self.us_city_state_cluster_flags)} US city/state clusters")
        print(f"  Found {len(self.intl_country_city_cluster_flags)} international city clusters")

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
            'trans_datetime': ['trans_datetime', 'Trans_Datetime', 'TRANS_DATETIME', 'transaction date time', 'Transaction Date Time'],
            'first_name': ['first name', 'First Name', 'FIRST NAME', 'first_name', 'First_Name'],
            'last_name': ['last name', 'Last Name', 'LAST NAME', 'last_name', 'Last_Name'],
            'pov_verified': ['pov_verified', 'POV_Verified', 'POV Verified', 'POV_VERIFIED'],
            'pov_verified_time': ['pov_verified_time', 'POV_Verified_Time', 'POV Verified Time', 'POV_VERIFIED_TIME'],
            'custom_http_user_agent': ['custom_http_user_agent', 'Custom_Http_User_Agent', 'HTTP User Agent', 'user_agent', 'User Agent', 'User_Agent']
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

    def analyze_email(self, email, trans_datetime=None, pov_verified=None, pov_verified_time=None, ip_address=None, user_agent=None):
        """
        Analyze a single email for fraud patterns

        Args:
            email: Email address to analyze
            trans_datetime: Transaction/signup datetime (optional)
            pov_verified: Whether POV verified (optional)
            pov_verified_time: POV verification timestamp (optional)
            ip_address: IP address of signup (optional)
            user_agent: HTTP user agent string (optional)
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
            return {
                'email': email,
                'risk_score': 100,
                'flags': ['INVALID_EMAIL'],
                'details': {'reason': 'No @ symbol found'}
            }

        username, domain = email.split('@', 1)

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

        # 8. POV Verified Timing Analysis (CRITICAL FRAUD INDICATOR)
        # Email validation within 60 seconds of account creation is highly suspicious
        if trans_datetime and pov_verified and pov_verified_time:
            try:
                # Parse timestamps
                if isinstance(trans_datetime, str):
                    signup_time = pd.to_datetime(trans_datetime)
                else:
                    signup_time = trans_datetime

                if isinstance(pov_verified_time, str):
                    verification_time = pd.to_datetime(pov_verified_time)
                else:
                    verification_time = pov_verified_time

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

    def analyze_domain_concentration(self, df):
        """Analyze domain concentration across all emails"""
        domains = []
        email_col = self.column_map.get('email')
        if not email_col:
            return {}

        for email in df[email_col]:
            if pd.notna(email) and '@' in str(email):
                domain = str(email).lower().split('@')[1]
                if domain not in self.major_providers:
                    domains.append(domain)

        if not domains:
            return {}

        domain_counts = Counter(domains)
        total_non_major = len(domains)

        concentration_flags = {}
        for domain, count in domain_counts.items():
            percentage = (count / total_non_major) * 100
            if percentage > 90:
                concentration_flags[domain] = {
                    'count': count,
                    'percentage': round(percentage, 2),
                    'risk': 'CRITICAL'
                }
            elif percentage > 50:
                concentration_flags[domain] = {
                    'count': count,
                    'percentage': round(percentage, 2),
                    'risk': 'HIGH'
                }

        return concentration_flags

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

    def build_ip_velocity_map(self, df):
        """Detect IPs with high signup velocity (fraud ring indicator)"""
        ip_col = self.column_map.get('ip')
        trans_datetime_col = self.column_map.get('trans_datetime')

        if not ip_col or not trans_datetime_col:
            return

        print("Analyzing IP velocity patterns...")

        # Group by IP and analyze signup timing
        ip_signups = defaultdict(list)

        for idx, row in df.iterrows():
            ip = row.get(ip_col) if ip_col in row else None
            timestamp = row.get(trans_datetime_col) if trans_datetime_col in row else None

            if pd.notna(ip) and pd.notna(timestamp):
                try:
                    ts = pd.to_datetime(timestamp)
                    ip_signups[ip].append(ts)
                except:
                    continue

        # Analyze velocity for each IP
        for ip, timestamps in ip_signups.items():
            if len(timestamps) < 3:  # Need at least 3 signups to be suspicious
                continue

            timestamps_sorted = sorted(timestamps)

            # Check various time windows
            # 1 hour window: 5+ signups
            # 24 hour window: 10+ signups
            one_hour_max = 0
            day_max = 0

            for i in range(len(timestamps_sorted)):
                # Count signups within 1 hour
                one_hour_count = sum(1 for ts in timestamps_sorted if timestamps_sorted[i] <= ts <= timestamps_sorted[i] + pd.Timedelta(hours=1))
                one_hour_max = max(one_hour_max, one_hour_count)

                # Count signups within 24 hours
                day_count = sum(1 for ts in timestamps_sorted if timestamps_sorted[i] <= ts <= timestamps_sorted[i] + pd.Timedelta(days=1))
                day_max = max(day_max, day_count)

            # Flag suspicious IPs
            if one_hour_max >= 5 or day_max >= 10:
                self.ip_velocity_flags[ip] = {
                    'total_signups': len(timestamps),
                    'max_per_hour': one_hour_max,
                    'max_per_day': day_max,
                    'risk_level': 'HIGH' if one_hour_max >= 10 else 'MEDIUM'
                }

        if self.ip_velocity_flags:
            print(f"Found {len(self.ip_velocity_flags)} suspicious IPs with high signup velocity")
            # Show top IPs
            top_ips = sorted(self.ip_velocity_flags.items(), key=lambda x: x[1]['max_per_hour'], reverse=True)[:3]
            for ip, data in top_ips:
                print(f"  {ip}: {data['max_per_hour']} signups/hour, {data['max_per_day']} signups/day")

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

        # Analyze each email
        results = []
        email_col = self.column_map.get('email')

        if not email_col:
            raise ValueError("Could not find 'Email' column in the data. Available columns: " + ", ".join(df.columns))

        for idx, row in df.iterrows():
            analysis = self.analyze_email(row[email_col])
            results.append({
                **analysis,
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

        # Domain concentration analysis
        print("\nAnalyzing domain concentration...")
        domain_concentration = self.analyze_domain_concentration(df)

        # Flag accounts from concentrated domains
        if domain_concentration:
            for idx, row in results_df.iterrows():
                domain = row['details'].get('domain', '')
                if domain in domain_concentration:
                    results_df.at[idx, 'risk_score'] += 30
                    current_flags = results_df.at[idx, 'flags']
                    if isinstance(current_flags, list):
                        current_flags.append('DOMAIN_CONCENTRATION')
                    results_df.at[idx, 'flags'] = current_flags

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
                        results_df.at[idx, 'risk_score'] += 15
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

        return results_df, domain_concentration, theme_clusters, name_clusters, word_clusters

    def generate_report(self, results_df, domain_concentration, theme_clusters, name_clusters, word_clusters, output_path='fraud_report.csv'):
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

        # Domain concentration summary
        if domain_concentration:
            print("\n" + "-"*80)
            print("DOMAIN CONCENTRATION ALERTS")
            print("-"*80)
            for domain, info in domain_concentration.items():
                print(f"  {domain}: {info['count']} accounts ({info['percentage']}%) - {info['risk']} RISK")

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
        results_df, domain_concentration, theme_clusters, name_clusters, word_clusters = detector.process_leads_file(str(input_file))
        high_risk, medium_risk = detector.generate_report(
            results_df,
            domain_concentration,
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
        print("6. Check accounts with DOMAIN_CONCENTRATION + other flags")

    except Exception as e:
        print(f"\nERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
