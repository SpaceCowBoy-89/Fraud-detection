"""
Supervised fraud prediction from reviewed outcomes.

Pipeline (mirrors standard ML workflow):
  1. Extract fraud_results + fraud_outcomes (confirmed_fraud / false_positive)
  2. Engineer features (risk score, flags, enrichment, email metrics)
  3. Train logistic regression with stratified cross-validation
  4. Evaluate (ROC-AUC, PR-AUC, precision, recall)
  5. Score all fraud_results with ml_fraud_probability

Requires: pip install scikit-learn
"""
from __future__ import annotations

import ast
import json
import logging
import pickle
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import importlib.util

logger = logging.getLogger(__name__)

SKLEARN_AVAILABLE = importlib.util.find_spec("sklearn") is not None

# Common fraud flags → one-hot columns (extend as patterns evolve)
KNOWN_FLAG_COLUMNS = [
    "EXCESSIVE_DOTS",
    "DIGIT_SUFFIX",
    "SCRAMBLED_PATTERN",
    "NAME_NUMBER_PATTERN",
    "SUSPICIOUS_NAME",
    "AFFILIATE_DOMAIN_CONCENTRATION",
    "THEME_CLUSTER",
    "POV_INSTANT",
    "POV_FAST",
    "IP_VELOCITY",
    "BILLING_GENDER_MISMATCH",
    "GENDER_NAME_MISMATCH",
    "WOMAN_CONCENTRATION",
    "SEQUENTIAL_EMAIL",
    "SHARED_CARD",
    "AMEX_CARD",
    "BUSINESS_CARD",
    "DISCOVER_CONCENTRATION",
    "EMAIL_VALIDATED_60S",
    "EMAIL_VALIDATED_120S",
    "IP_DIFFERENT_STATE",
    "IP_DIFFERENT_COUNTRY",
    "LOGIN_HIGH_RISK_COUNTRY",
    "REGISTRATION_IP_DATACENTER",
    "LOGIN_IP_DATACENTER",
    "REGISTRATION_IP_VPN",
    "LOGIN_IP_VPN",
    "GEO_LOGIN_COUNTRY_MISMATCH",
]


def _has_sklearn() -> bool:
    if not SKLEARN_AVAILABLE:
        raise ImportError(
            "scikit-learn is required for fraud ML. Install with: pip install scikit-learn"
        )
    return True


def parse_flags(val) -> List[str]:
    """Parse flags column from fraud_results (JSON or Python repr)."""
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip().upper() for x in val if x]
    s = str(val).strip()
    if not s:
        return []
    try:
        v = json.loads(s.replace("'", '"') if s.startswith("[") else s)
        if isinstance(v, list):
            return [str(x).strip().upper() for x in v if x]
    except Exception:
        pass
    try:
        v = ast.literal_eval(s)
        if isinstance(v, list):
            return [str(x).strip().upper() for x in v if x]
    except Exception:
        pass
    return [s.upper()] if s else []


def _normalize_flag_name(flag: str) -> str:
    """Map raw flag strings to canonical KNOWN_FLAG_COLUMNS names."""
    f = str(flag).strip().upper().replace(" ", "_")
    if f in KNOWN_FLAG_COLUMNS:
        return f
    for known in KNOWN_FLAG_COLUMNS:
        if known in f or f in known:
            return known
    return f


def load_labeled_dataset(db) -> "Any":
    """Load reviewed accounts with features for supervised training."""
    import pandas as pd

    query = """
        SELECT
            fr.duid,
            fr.risk_score,
            fr.flags,
            fr.payout_amount,
            fr.email,
            fr.data_type,
            fr.admin_risk_added,
            fr.shared_card_count,
            fr.ip_proxy,
            fr.ip_hosting,
            fr.profile_image_uploaded,
            fr.profile_image_upload_seconds,
            fr.is_business_card,
            fr.registration_ip_is_datacenter,
            fr.login_ip_is_datacenter,
            fo.outcome,
            fo.actual_loss
        FROM fraud_outcomes fo
        INNER JOIN fraud_results fr ON fr.duid = fo.duid
        WHERE fo.outcome IN ('confirmed_fraud', 'false_positive')
    """
    with db.get_connection() as conn:
        return pd.read_sql_query(query, conn)


def load_all_for_scoring(db) -> "Any":
    """Load all fraud_results rows for batch prediction."""
    import pandas as pd

    query = """
        SELECT
            duid,
            risk_score,
            flags,
            payout_amount,
            email,
            data_type,
            admin_risk_added,
            shared_card_count,
            ip_proxy,
            ip_hosting,
            profile_image_uploaded,
            profile_image_upload_seconds,
            is_business_card,
            registration_ip_is_datacenter,
            login_ip_is_datacenter
        FROM fraud_results
    """
    with db.get_connection() as conn:
        return pd.read_sql_query(query, conn)


def build_feature_matrix(
    df: "Any",
    flag_columns: Optional[List[str]] = None,
) -> Tuple["Any", List[str]]:
    """
    Build numeric feature matrix from fraud_results-shaped DataFrame.

    Returns:
        (X DataFrame, list of column names)
    """
    import numpy as np
    import pandas as pd

    if df.empty:
        return pd.DataFrame(), []

    flag_columns = flag_columns or list(KNOWN_FLAG_COLUMNS)
    rows = []

    for _, row in df.iterrows():
        feats: Dict[str, float] = {}
        feats["risk_score"] = float(pd.to_numeric(row.get("risk_score"), errors="coerce") or 0)
        payout = float(pd.to_numeric(row.get("payout_amount"), errors="coerce") or 0)
        feats["log_payout"] = float(np.log1p(max(payout, 0)))
        feats["admin_risk_added"] = float(pd.to_numeric(row.get("admin_risk_added"), errors="coerce") or 0)
        feats["shared_card_count"] = float(pd.to_numeric(row.get("shared_card_count"), errors="coerce") or 0)
        feats["is_paid"] = 1.0 if str(row.get("data_type") or "").lower() == "paid" else 0.0

        email = str(row.get("email") or "")
        feats["email_length"] = float(len(email))
        feats["email_dot_count"] = float(email.count("."))
        feats["email_digit_count"] = float(sum(c.isdigit() for c in email))

        flags = [_normalize_flag_name(f) for f in parse_flags(row.get("flags"))]
        feats["flag_count"] = float(len(flags))
        for col in flag_columns:
            feats[f"flag_{col}"] = 1.0 if col in flags else 0.0

        def _bool_feat(key, col):
            v = row.get(key)
            if v is None or (isinstance(v, float) and np.isnan(v)):
                feats[col] = 0.0
            else:
                feats[col] = 1.0 if v in (1, True, "1", "true", "True") else 0.0

        _bool_feat("ip_proxy", "ip_proxy")
        _bool_feat("ip_hosting", "ip_hosting")
        _bool_feat("profile_image_uploaded", "profile_image_uploaded")
        _bool_feat("is_business_card", "is_business_card")
        _bool_feat("registration_ip_is_datacenter", "registration_ip_datacenter")
        _bool_feat("login_ip_is_datacenter", "login_ip_datacenter")

        pov_sec = pd.to_numeric(row.get("profile_image_upload_seconds"), errors="coerce")
        if pov_sec is not None and not (isinstance(pov_sec, float) and np.isnan(pov_sec)):
            feats["profile_image_fast"] = 1.0 if float(pov_sec) < 60 else 0.0
        else:
            feats["profile_image_fast"] = 0.0

        rows.append(feats)

    X = pd.DataFrame(rows)
    return X.fillna(0), list(X.columns)


def _metrics_dict(y_true, y_prob, threshold: float = 0.5) -> Dict[str, Any]:
    """Classification metrics for binary labels."""
    from sklearn.metrics import (
        average_precision_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    y_pred = (y_prob >= threshold).astype(int)
    out: Dict[str, Any] = {"threshold": threshold}
    try:
        out["roc_auc"] = round(float(roc_auc_score(y_true, y_prob)), 4)
    except ValueError:
        out["roc_auc"] = None
    try:
        out["pr_auc"] = round(float(average_precision_score(y_true, y_prob)), 4)
    except ValueError:
        out["pr_auc"] = None
    out["precision"] = round(float(precision_score(y_true, y_pred, zero_division=0)), 4)
    out["recall"] = round(float(recall_score(y_true, y_pred, zero_division=0)), 4)
    out["f1"] = round(float(f1_score(y_true, y_pred, zero_division=0)), 4)
    return out


def _roc_curve_points(y_true, y_prob, n_thresholds: int = 21) -> List[Dict[str, float]]:
    from sklearn.metrics import roc_curve

    fpr, tpr, thresholds = roc_curve(y_true, y_prob)
    if len(fpr) <= n_thresholds:
        return [
            {"fpr": round(float(a), 4), "tpr": round(float(b), 4), "threshold": round(float(c), 4)}
            for a, b, c in zip(fpr, tpr, thresholds)
        ]
    indices = [int(i * (len(fpr) - 1) / (n_thresholds - 1)) for i in range(n_thresholds)]
    return [
        {
            "fpr": round(float(fpr[i]), 4),
            "tpr": round(float(tpr[i]), 4),
            "threshold": round(float(thresholds[i]), 4) if i < len(thresholds) else 0.0,
        }
        for i in indices
    ]


class FraudMLTrainer:
    """Train, evaluate, and apply a logistic regression fraud model."""

    def __init__(self, config: Optional[Dict] = None):
        cfg = (config or {}).get("ml_model", {})
        self.min_labeled_samples = int(cfg.get("min_labeled_samples", 30))
        self.test_size = float(cfg.get("test_size", 0.2))
        self.cv_folds = int(cfg.get("cv_folds", 5))
        self.probability_threshold = float(cfg.get("probability_threshold", 0.5))
        self.models_dir = Path(cfg.get("models_dir", "models"))
        self.random_state = int(cfg.get("random_state", 42))
        self.model = None
        self.scaler = None
        self.feature_names: List[str] = []
        self.flag_columns: List[str] = list(KNOWN_FLAG_COLUMNS)
        self.run_id: Optional[str] = None

    def train(self, db) -> Dict[str, Any]:
        """Full train → evaluate → save → score pipeline."""
        _has_sklearn()
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        df = load_labeled_dataset(db)
        n = len(df)
        if n < self.min_labeled_samples:
            return {
                "success": False,
                "error": (
                    f"Need at least {self.min_labeled_samples} reviewed outcomes "
                    f"(confirmed_fraud + false_positive). Found {n}."
                ),
                "labeled_count": n,
            }

        y = (df["outcome"] == "confirmed_fraud").astype(int).values
        fraud_rate = float(y.mean())
        X, self.feature_names = build_feature_matrix(df, self.flag_columns)

        if X.empty or len(self.feature_names) == 0:
            return {"success": False, "error": "Could not build feature matrix.", "labeled_count": n}

        skf = StratifiedKFold(
            n_splits=min(self.cv_folds, int(y.sum()), int(len(y) - y.sum())),
            shuffle=True,
            random_state=self.random_state,
        )
        cv_splits = skf if skf.get_n_splits() >= 2 else None

        pipeline = Pipeline([
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=self.random_state,
                ),
            ),
        ])

        X_train, X_test, y_train, y_test = train_test_split(
            X.values,
            y,
            test_size=self.test_size,
            stratify=y,
            random_state=self.random_state,
        )
        pipeline.fit(X_train, y_train)

        cv_auc_mean = None
        cv_auc_std = None
        if cv_splits is not None:
            try:
                scores = cross_val_score(
                    pipeline, X.values, y, cv=cv_splits, scoring="roc_auc", n_jobs=None
                )
                cv_auc_mean = round(float(scores.mean()), 4)
                cv_auc_std = round(float(scores.std()), 4)
            except Exception as e:
                logger.warning("Cross-validation failed: %s", e)

        y_prob_test = pipeline.predict_proba(X_test)[:, 1]
        test_metrics = _metrics_dict(y_test, y_prob_test, self.probability_threshold)
        roc_points = _roc_curve_points(y_test, y_prob_test)

        # Coefficients for explainability
        clf = pipeline.named_steps["clf"]
        coefs = clf.coef_[0]
        top_features = sorted(
            zip(self.feature_names, coefs.tolist()),
            key=lambda x: abs(x[1]),
            reverse=True,
        )[:15]

        self.run_id = uuid.uuid4().hex[:12]
        self.models_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = self.models_dir / f"fraud_lr_{self.run_id}.pkl"
        artifact = {
            "pipeline": pipeline,
            "feature_names": self.feature_names,
            "flag_columns": self.flag_columns,
            "probability_threshold": self.probability_threshold,
            "trained_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(artifact_path, "wb") as f:
            pickle.dump(artifact, f)

        metrics_payload = {
            "labeled_count": n,
            "fraud_rate": round(fraud_rate, 4),
            "test_metrics": test_metrics,
            "cv_roc_auc_mean": cv_auc_mean,
            "cv_roc_auc_std": cv_auc_std,
            "roc_curve": roc_points,
            "top_features": [
                {"name": name, "coefficient": round(coef, 4)} for name, coef in top_features
            ],
        }

        db.save_ml_model(
            run_id=self.run_id,
            labeled_samples=n,
            fraud_rate=fraud_rate,
            test_roc_auc=test_metrics.get("roc_auc"),
            cv_roc_auc_mean=cv_auc_mean,
            cv_roc_auc_std=cv_auc_std,
            test_precision=test_metrics.get("precision"),
            test_recall=test_metrics.get("recall"),
            test_pr_auc=test_metrics.get("pr_auc"),
            optimal_threshold=self.probability_threshold,
            feature_names=self.feature_names,
            metrics_json=metrics_payload,
            artifact_path=str(artifact_path),
        )

        scored = self.score_all(db, artifact_path=artifact_path)
        metrics_payload["scored_accounts"] = scored

        return {
            "success": True,
            "run_id": self.run_id,
            "artifact_path": str(artifact_path),
            **metrics_payload,
        }

    def score_all(self, db, artifact_path: Optional[Path] = None) -> int:
        """Apply active model to all fraud_results; returns count updated."""
        _has_sklearn()

        if artifact_path is None:
            active = db.get_active_ml_model()
            if not active or not active.get("artifact_path"):
                return 0
            artifact_path = Path(active["artifact_path"])
        else:
            artifact_path = Path(artifact_path)

        if not artifact_path.exists():
            logger.warning("ML artifact not found: %s", artifact_path)
            return 0

        with open(artifact_path, "rb") as f:
            artifact = pickle.load(f)

        pipeline = artifact["pipeline"]
        self.feature_names = artifact["feature_names"]
        self.flag_columns = artifact.get("flag_columns", KNOWN_FLAG_COLUMNS)
        run_id = artifact_path.stem.replace("fraud_lr_", "")

        df = load_all_for_scoring(db)
        if df.empty:
            return 0

        X, _ = build_feature_matrix(df, self.flag_columns)
        # Align columns (older models may differ slightly)
        for col in self.feature_names:
            if col not in X.columns:
                X[col] = 0.0
        X = X[self.feature_names]

        probs = pipeline.predict_proba(X.values)[:, 1]
        updates = [
            (float(p), run_id, str(duid))
            for p, duid in zip(probs, df["duid"].astype(str))
        ]
        return db.update_ml_predictions(updates)

    @staticmethod
    def compare_to_rules(db, config: Optional[Dict] = None) -> Dict[str, Any]:
        """Compare ML probabilities vs rule-based risk_score on labeled set."""
        import pandas as pd

        active = db.get_active_ml_model()
        df = load_labeled_dataset(db)
        if df.empty:
            return {"labeled_count": 0, "comparison": None}

        threshold = int((config or {}).get("risk_thresholds", {}).get("high", 50))
        y = (df["outcome"] == "confirmed_fraud").astype(int)

        with db.get_connection() as conn:
            probs_df = pd.read_sql_query(
                "SELECT duid, ml_fraud_probability FROM fraud_results WHERE ml_fraud_probability IS NOT NULL",
                conn,
            )
        if not probs_df.empty:
            df = df.merge(probs_df, on="duid", how="left")
        else:
            df["ml_fraud_probability"] = None

        ml_threshold = float(
            (active or {}).get("optimal_threshold")
            or (config or {}).get("ml_model", {}).get("probability_threshold", 0.5)
        )

        def _rule_metrics():
            scores = pd.to_numeric(df["risk_score"], errors="coerce").fillna(0)
            pred = (scores >= threshold).astype(int)
            tp = int(((pred == 1) & (y == 1)).sum())
            fp = int(((pred == 1) & (y == 0)).sum())
            fn = int(((pred == 0) & (y == 1)).sum())
            prec = tp / (tp + fp) if (tp + fp) else None
            rec = tp / (tp + fn) if (tp + fn) else None
            return {
                "method": "rules",
                "threshold": threshold,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": round(prec * 100, 2) if prec is not None else None,
                "recall": round(rec * 100, 2) if rec is not None else None,
            }

        def _ml_metrics():
            if df["ml_fraud_probability"].isna().all():
                return None
            prob = pd.to_numeric(df["ml_fraud_probability"], errors="coerce").fillna(0)
            pred = (prob >= ml_threshold).astype(int)
            tp = int(((pred == 1) & (y == 1)).sum())
            fp = int(((pred == 1) & (y == 0)).sum())
            fn = int(((pred == 0) & (y == 1)).sum())
            prec = tp / (tp + fp) if (tp + fp) else None
            rec = tp / (tp + fn) if (tp + fn) else None
            return {
                "method": "ml",
                "threshold": ml_threshold,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": round(prec * 100, 2) if prec is not None else None,
                "recall": round(rec * 100, 2) if rec is not None else None,
            }

        return {
            "labeled_count": int(len(df)),
            "rules": _rule_metrics(),
            "ml": _ml_metrics(),
            "active_model": active,
        }


def train_fraud_model(db, config: Optional[Dict] = None) -> Dict[str, Any]:
    """Entry point for CLI / API / scheduler."""
    trainer = FraudMLTrainer(config)
    return trainer.train(db)


def get_ml_status(db) -> Dict[str, Any]:
    """Return active model metadata and training readiness."""
    active = db.get_active_ml_model()
    import pandas as pd

    with db.get_connection() as conn:
        counts = pd.read_sql_query(
            """
            SELECT outcome, COUNT(*) AS cnt
            FROM fraud_outcomes
            WHERE outcome IN ('confirmed_fraud', 'false_positive')
            GROUP BY outcome
            """,
            conn,
        )
    labeled = int(counts["cnt"].sum()) if not counts.empty else 0
    fraud_n = int(counts[counts["outcome"] == "confirmed_fraud"]["cnt"].sum()) if not counts.empty else 0
    fp_n = int(counts[counts["outcome"] == "false_positive"]["cnt"].sum()) if not counts.empty else 0

    min_samples = 30

    return {
        "sklearn_available": SKLEARN_AVAILABLE,
        "labeled_count": labeled,
        "confirmed_fraud_count": fraud_n,
        "false_positive_count": fp_n,
        "ready_to_train": labeled >= min_samples and SKLEARN_AVAILABLE,
        "min_labeled_samples": min_samples,
        "active_model": active,
    }
