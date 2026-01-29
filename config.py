"""Configuration management for fraud detection system"""
import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    'api_key': '',
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
        'domain_concentration': 20,
        
        # POV timing scores
        'pov_instant_20s': 50,
        'pov_instant_40s': 40,
        'pov_fast_60s': 30,
        
        # IP velocity scores
        'ip_velocity_high': 30,
        'ip_velocity_medium': 5,
        
        # Device scores
        'desktop_windows_10': 20,
        'desktop_other': 10,
        
        # Geographic clustering scores
        'us_state_cluster': 25,
        'us_city_state_cluster': 30,
        'intl_country_city_cluster': 30,
        
        # Theme clustering
        'theme_cluster': 15
    },
    'detection_weights': {
        # Deprecated - use risk_scores instead
        'excessive_dots': 20,
        'digit_suffix': 15,
        'scrambled_pattern': 35,
        'name_number_pattern': 40,
        'written_number': 15,
        'repeated_word': 25,
        'suspicious_name': 30,
        'domain_concentration': 20
    },
    'ip_velocity_threshold': 10,
    'repeated_word_threshold': 3,
    'whitelisted_affiliates': [],
    'high_risk_countries': [],
    'suspicious_names': ['fatima', 'muhammed'],
    'database_path': 'affiliate_data.db'
}


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
                # Merge with defaults in case new keys were added
                return {**DEFAULT_CONFIG, **config}
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

    def get_risk_threshold(self, level):
        """Get risk threshold for specific level"""
        return self.get(f'risk_thresholds.{level}', DEFAULT_CONFIG['risk_thresholds'].get(level, 0))

    def get_detection_weight(self, pattern):
        """Get detection weight for specific pattern"""
        return self.get(f'detection_weights.{pattern}', DEFAULT_CONFIG['detection_weights'].get(pattern, 0))

    def add_whitelisted_affiliate(self, affiliate_id):
        """Add affiliate to whitelist"""
        whitelist = self.get('whitelisted_affiliates', [])
        if affiliate_id not in whitelist:
            whitelist.append(affiliate_id)
            return self.set('whitelisted_affiliates', whitelist)
        return True

    def remove_whitelisted_affiliate(self, affiliate_id):
        """Remove affiliate from whitelist"""
        whitelist = self.get('whitelisted_affiliates', [])
        if affiliate_id in whitelist:
            whitelist.remove(affiliate_id)
            return self.set('whitelisted_affiliates', whitelist)
        return True

    def is_whitelisted(self, affiliate_id):
        """Check if affiliate is whitelisted"""
        whitelist = self.get('whitelisted_affiliates', [])
        return affiliate_id in whitelist

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
