"""
Advanced Pattern Detection Module

Integrates:
- PyOD: Unsupervised anomaly detection
- SHAP: Explainability for fraud detection decisions
- Alibi Detect: Drift detection for evolving fraud patterns
"""
import json
import logging
import pickle
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional, TYPE_CHECKING
import importlib.util

# NOTE:
# Importing numpy/pandas can hard-crash (segfault) in some environments when binary wheels are mismatched.
# We therefore avoid importing them at module import-time and instead import lazily inside methods.
if TYPE_CHECKING:
    import pandas as pd
    import numpy as np

def _has_module(module_name: str) -> bool:
    """
    Check module availability without importing it.
    This avoids hard crashes from optional heavy dependencies during import-time.
    """
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


# Optional deps: detect without importing (importing some ML libs can crash on some systems)
PYOD_AVAILABLE = _has_module("pyod")
SHAP_AVAILABLE = _has_module("shap")
ALIBI_AVAILABLE = _has_module("alibi_detect")

if not PYOD_AVAILABLE:
    logging.warning("PyOD not available. Install with: pip install pyod")
if not SHAP_AVAILABLE:
    logging.warning("SHAP not available. Install with: pip install shap")
if not ALIBI_AVAILABLE:
    logging.warning("Alibi Detect not available. Install with: pip install alibi-detect")

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """
    Unsupervised anomaly detection using multiple PyOD algorithms.

    Finds fraud patterns that rule-based detection might miss.
    """

    def __init__(self, contamination=0.1):
        """
        Initialize anomaly detectors.

        Args:
            contamination: Expected proportion of outliers (default 10%)
        """
        if not PYOD_AVAILABLE:
            raise ImportError("PyOD is required. Install with: pip install pyod")

        self.contamination = contamination
        # Import PyOD models lazily (only when this feature is used)
        from pyod.models.iforest import IForest
        from pyod.models.knn import KNN
        from pyod.models.lof import LOF
        self.detectors = {
            'IsolationForest': IForest(contamination=contamination, random_state=42),
            'KNN': KNN(contamination=contamination),
            'LOF': LOF(contamination=contamination)
        }
        self.fitted = False

    def prepare_features(self, df: "pd.DataFrame") -> "pd.DataFrame":
        """
        Extract features for anomaly detection from fraud results.

        Args:
            df: DataFrame with fraud detection results

        Returns:
            DataFrame with numeric features for anomaly detection
        """
        import pandas as pd
        import numpy as np

        # Handle duplicate columns by keeping only the first occurrence
        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated()]

        features = pd.DataFrame()

        # Existing risk score
        if 'risk_score' in df.columns:
            features['risk_score'] = df['risk_score']

        # Payout amount (log transform to handle outliers)
        if 'payout_amount' in df.columns:
            payout_series = df['payout_amount']
            # Ensure it's a Series, not a DataFrame
            if isinstance(payout_series, pd.DataFrame):
                payout_series = payout_series.iloc[:, 0]
            features['log_payout'] = np.log1p(payout_series.fillna(0))

        # Flag count (how many fraud indicators triggered)
        if 'flags' in df.columns:
            features['flag_count'] = df['flags'].apply(
                lambda x: len(json.loads(x)) if x and x != '[]' else 0
            )

        # Email complexity metrics
        if 'email' in df.columns:
            features['email_length'] = df['email'].fillna('').str.len()
            features['dot_count'] = df['email'].fillna('').str.count(r'\.')
            features['digit_count'] = df['email'].fillna('').str.count(r'\d')

        # POV timing (proof of verification speed)
        if 'pov_seconds' in df.columns:
            features['pov_seconds'] = df['pov_seconds'].fillna(999999)
            features['fast_pov'] = (features['pov_seconds'] < 60).astype(int)

        # Fill any remaining NaN values
        features = features.fillna(0)

        return features

    def fit_predict(self, df: "pd.DataFrame") -> Dict[str, "np.ndarray"]:
        """
        Fit detectors and predict anomalies.

        Args:
            df: DataFrame with fraud detection results

        Returns:
            Dictionary with detector results:
            - predictions: 1 = anomaly, 0 = normal
            - scores: anomaly scores (higher = more anomalous)
            - consensus: accounts flagged by multiple detectors
        """
        import numpy as np

        # Prepare features
        X = self.prepare_features(df)

        if X.empty or len(X) < 10:
            logger.warning("Insufficient data for anomaly detection (need at least 10 records)")
            return {}

        results = {}

        # Convert to numpy array to avoid feature name warnings
        X_array = X.values

        # Run each detector
        for name, detector in self.detectors.items():
            try:
                # Fit and predict (using numpy array to avoid feature name warnings)
                detector.fit(X_array)
                predictions = detector.predict(X_array)  # 1 = anomaly, 0 = normal
                scores = detector.decision_function(X_array)  # Higher = more anomalous

                results[name] = {
                    'predictions': predictions,
                    'scores': scores,
                    'anomaly_count': int(np.sum(predictions))
                }

                logger.info(f"{name} detected {results[name]['anomaly_count']} anomalies")

            except Exception as e:
                logger.error(f"Error running {name}: {e}")
                continue

        # Consensus: flagged by at least 2 detectors
        if len(results) >= 2:
            all_predictions = np.array([r['predictions'] for r in results.values()])
            consensus = np.sum(all_predictions, axis=0) >= 2
            # Build a stable consensus score (mean of min-max normalized detector scores)
            score_arrays = []
            for r in results.values():
                scores = r.get('scores')
                if scores is None:
                    continue
                scores = np.asarray(scores)
                smin = float(np.min(scores))
                smax = float(np.max(scores))
                if smax > smin:
                    score_arrays.append((scores - smin) / (smax - smin))
                else:
                    score_arrays.append(np.zeros_like(scores))

            if score_arrays:
                consensus_scores = np.mean(np.vstack(score_arrays), axis=0)
            else:
                consensus_scores = np.zeros(len(consensus), dtype=float)

            results['consensus'] = {
                'predictions': consensus.astype(int),
                'anomaly_count': int(np.sum(consensus)),
                'scores': consensus_scores
            }

        self.fitted = True
        return results

    def find_missed_fraud(self, df: "pd.DataFrame", anomaly_results: Dict,
                          risk_threshold: int = 50) -> "pd.DataFrame":
        """
        Find potential fraud cases missed by rule-based detection.

        Args:
            df: Original DataFrame with fraud results
            anomaly_results: Results from fit_predict()
            risk_threshold: Risk score threshold for rule-based detection

        Returns:
            DataFrame with newly discovered potential fraud cases
        """
        import pandas as pd
        import numpy as np

        if 'consensus' not in anomaly_results:
            logger.warning("No consensus results available")
            return pd.DataFrame()

        # Accounts with low rule-based risk but flagged by anomaly detectors
        consensus_anomalies = anomaly_results['consensus']['predictions'].astype(bool)
        low_risk_by_rules = (df['risk_score'] < risk_threshold).values

        # Create mask for newly discovered (anomaly + low rule-based risk)
        mask = consensus_anomalies & low_risk_by_rules
        
        # Reset index to ensure alignment
        df_reset = df.reset_index(drop=True)
        newly_discovered = df_reset[mask].copy()

        # Add anomaly scores using the mask on the original array
        for name, result in anomaly_results.items():
            if name != 'consensus' and 'scores' in result:
                scores = np.asarray(result['scores'])
                newly_discovered[f'{name}_score'] = scores[mask]

        return newly_discovered


class FraudExplainer:
    """
    Generate human-readable explanations for fraud detection decisions.

    Uses SHAP for ML models and rule-based explanations for your existing system.
    """

    def explain_fraud_decision(self, row: "pd.Series", detector_config: Dict = None) -> Dict:
        """
        Explain why an account was flagged as fraudulent.

        Args:
            row: Single row from fraud results DataFrame
            detector_config: Configuration with risk score weights

        Returns:
            Dictionary with explanation details
        """
        import pandas as pd

        explanation = {
            'email': row.get('email', 'Unknown'),
            'risk_score': int(row.get('risk_score', 0)),
            'risk_level': self._get_risk_level(row.get('risk_score', 0)),
            'reasons': [],
            'contributing_factors': {}
        }

        # Parse flags
        flags = []
        if 'flags' in row and row['flags']:
            try:
                flags = json.loads(row['flags']) if isinstance(row['flags'], str) else row['flags']
            except (json.JSONDecodeError, TypeError):
                flags = []

        # Map flags to explanations with point values
        flag_explanations = {
            'EXCESSIVE_DOTS': ('Excessive dots in email username', 25),
            'DIGIT_SUFFIX': ('Email ends with 4-5 digits', 20),
            'SCRAMBLED_PATTERN': ('Email appears randomly generated', 35),
            'NAME_NUMBER_PATTERN': ('Email follows name+number pattern', 40),
            'WRITTEN_NUMBER': ('Email contains written numbers', 25),
            'REPEATED_WORD': ('Email contains repeated words', 35),
            'SUSPICIOUS_NAME': ('Email contains suspicious name', 30),
            'DOMAIN_CONCENTRATION': ('High concentration from same domain', 30),
            'FAST_POV': ('Email verified suspiciously fast', 40),
            'GENDER_NAME_MISMATCH': ('Name/gender mismatch detected', 35),
        }

        total_points = 0
        for flag in flags:
            if flag in flag_explanations:
                reason, points = flag_explanations[flag]
                explanation['reasons'].append(f"{reason}: +{points} points")
                total_points += points

        # Add additional context
        if 'pov_seconds' in row and pd.notna(row['pov_seconds']):
            explanation['contributing_factors']['pov_verification_time'] = f"{row['pov_seconds']:.0f} seconds"

        if 'payout_amount' in row and pd.notna(row['payout_amount']):
            explanation['contributing_factors']['payout_amount'] = f"${row['payout_amount']:.2f}"

        if 'domain' in row:
            explanation['contributing_factors']['email_domain'] = row['domain']

        explanation['total_rule_points'] = total_points

        return explanation

    def _get_risk_level(self, risk_score: int) -> str:
        """Categorize risk score into level"""
        if risk_score >= 50:
            return "HIGH RISK"
        elif risk_score >= 25:
            return "MEDIUM RISK"
        else:
            return "LOW RISK"

    def batch_explain(self, df: "pd.DataFrame", min_risk: int = 50) -> List[Dict]:
        """
        Generate explanations for multiple accounts.

        Args:
            df: DataFrame with fraud results
            min_risk: Minimum risk score to explain (default: high risk only)

        Returns:
            List of explanation dictionaries
        """
        high_risk = df[df['risk_score'] >= min_risk]
        explanations = []

        for idx, row in high_risk.iterrows():
            exp = self.explain_fraud_decision(row)
            explanations.append(exp)

        return explanations


class DriftDetector:
    """
    Monitor for changes in fraud patterns over time.

    Alerts when fraud patterns evolve so you can update detection rules.
    """

    def __init__(self, reference_window_days: int = 30):
        """
        Initialize drift detector.

        Args:
            reference_window_days: Days of historical data to use as reference
        """
        if not ALIBI_AVAILABLE:
            raise ImportError("Alibi Detect is required. Install with: pip install alibi-detect")

        self.reference_window_days = reference_window_days
        # Import lazily (only when drift detection is used)
        from alibi_detect.cd import TabularDrift
        self._TabularDrift = TabularDrift
        self.detector = None
        self.reference_data = None
        self.drift_history_path = Path("drift_history.json")

    def set_reference_data(self, df: "pd.DataFrame"):
        """
        Set reference (historical) data for drift comparison.

        Args:
            df: DataFrame with historical fraud data
        """
        # Prepare features for drift detection
        features = self._prepare_drift_features(df)

        if len(features) < 100:
            logger.warning(f"Insufficient reference data ({len(features)} rows). Need at least 100.")
            return

        self.reference_data = features.values

        # Initialize drift detector
        self.detector = self._TabularDrift(
            self.reference_data,
            p_val=0.05,  # 5% significance level
            categories_per_feature=None
        )

        logger.info(f"Reference data set: {len(self.reference_data)} records")

    def check_drift(self, df: "pd.DataFrame") -> Dict:
        """
        Check if current data has drifted from reference.

        Args:
            df: DataFrame with current fraud data

        Returns:
            Dictionary with drift detection results
        """
        if self.detector is None:
            raise ValueError("Must set reference data first using set_reference_data()")

        # Prepare current data features
        current_features = self._prepare_drift_features(df)

        if len(current_features) < 20:
            logger.warning("Insufficient current data for drift detection")
            return {'error': 'Insufficient data'}

        # Run drift detection
        result = self.detector.predict(current_features.values)

        drift_result = {
            'is_drift': bool(result['data']['is_drift']),
            'p_value': float(result['data']['p_val']),
            'timestamp': datetime.now().isoformat(),
            'reference_size': len(self.reference_data),
            'current_size': len(current_features),
            'features_checked': list(current_features.columns)
        }

        # Save to history
        self._save_drift_history(drift_result)

        if drift_result['is_drift']:
            logger.warning("⚠️  DRIFT DETECTED: Fraud patterns have changed!")
            logger.warning(f"   p-value: {drift_result['p_value']:.4f}")
        else:
            logger.info(f"✓ No significant drift detected (p-value: {drift_result['p_value']:.4f})")

        return drift_result

    def _prepare_drift_features(self, df: "pd.DataFrame") -> "pd.DataFrame":
        """Prepare features for drift detection"""
        import pandas as pd
        import numpy as np

        features = pd.DataFrame()

        # Risk score distribution
        if 'risk_score' in df.columns:
            features['risk_score'] = df['risk_score']

        # Flag patterns (count of flags)
        if 'flags' in df.columns:
            features['flag_count'] = df['flags'].apply(
                lambda x: len(json.loads(x)) if x and x != '[]' else 0
            )

        # Email patterns
        if 'email' in df.columns:
            features['dot_count'] = df['email'].fillna('').str.count(r'\.')
            features['digit_count'] = df['email'].fillna('').str.count(r'\d')

        # POV timing
        if 'pov_seconds' in df.columns:
            features['pov_seconds'] = df['pov_seconds'].fillna(999999).clip(0, 10000)

        # Payout amounts (log scale)
        if 'payout_amount' in df.columns:
            features['log_payout'] = np.log1p(df['payout_amount'].fillna(0))

        # Fill NaN values
        features = features.fillna(0)

        return features

    def _save_drift_history(self, drift_result: Dict):
        """Save drift detection result to history"""
        history = []

        # Load existing history
        if self.drift_history_path.exists():
            try:
                with open(self.drift_history_path, 'r') as f:
                    history = json.load(f)
            except Exception as e:
                logger.error(f"Error loading drift history: {e}")

        # Append new result
        history.append(drift_result)

        # Keep only last 100 results
        history = history[-100:]

        # Save
        try:
            with open(self.drift_history_path, 'w') as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving drift history: {e}")

    def get_drift_history(self) -> List[Dict]:
        """Get historical drift detection results"""
        if not self.drift_history_path.exists():
            return []

        try:
            with open(self.drift_history_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading drift history: {e}")
            return []
