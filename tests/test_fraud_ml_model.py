"""Tests for supervised fraud ML pipeline."""
import json
import sys
import tempfile
import os
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from database import Database

from scripts.fraud_ml_model import (
    SKLEARN_AVAILABLE,
    build_feature_matrix,
    parse_flags,
    train_fraud_model,
    get_ml_status,
    FraudMLTrainer,
    KNOWN_FLAG_COLUMNS,
)

pytestmark = pytest.mark.skipif(not SKLEARN_AVAILABLE, reason="scikit-learn not available")


@pytest.fixture
def ml_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    yield db
    os.unlink(path)


def _insert_labeled_pair(db, duid, risk, flags, outcome, email="test@example.com"):
    flags_json = json.dumps(flags)
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO fraud_results (
                duid, email, risk_score, flags, payout_amount, data_type
            ) VALUES (?, ?, ?, ?, ?, 'paid')""",
            (duid, email, risk, flags_json, 50.0),
        )
        conn.execute(
            """INSERT INTO fraud_outcomes (
                duid, email, risk_score, flags, payout_amount, outcome
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (duid, email, risk, flags_json, 50.0, outcome),
        )


def test_parse_flags_json_and_repr():
    assert parse_flags('["A", "B"]') == ["A", "B"]
    assert parse_flags("['X']") == ["X"]


def test_build_feature_matrix_flag_columns():
    import pandas as pd

    df = pd.DataFrame([
        {
            "risk_score": 60,
            "flags": '["NAME_NUMBER_PATTERN"]',
            "payout_amount": 100,
            "email": "john43murphy@gmail.com",
            "data_type": "paid",
        }
    ])
    X, cols = build_feature_matrix(df, KNOWN_FLAG_COLUMNS[:5])
    assert "risk_score" in cols
    assert X["flag_NAME_NUMBER_PATTERN"].iloc[0] == 1.0


def test_train_insufficient_labels(ml_db):
    result = train_fraud_model(ml_db, {"ml_model": {"min_labeled_samples": 30}})
    assert result["success"] is False
    assert "30" in result["error"]


def test_train_and_score(ml_db):
    for i in range(20):
        _insert_labeled_pair(
            ml_db,
            f"fraud{i}",
            70 + (i % 10),
            ["NAME_NUMBER_PATTERN", "SUSPICIOUS_NAME"],
            "confirmed_fraud",
            email=f"fraud{i}@test.com",
        )
    for i in range(20):
        _insert_labeled_pair(
            ml_db,
            f"legit{i}",
            10 + (i % 5),
            [],
            "false_positive",
            email=f"legit{i}@test.com",
        )

    cfg = {
        "ml_model": {
            "min_labeled_samples": 30,
            "test_size": 0.25,
            "cv_folds": 3,
            "models_dir": tempfile.mkdtemp(),
        },
        "risk_thresholds": {"high": 50},
    }
    result = train_fraud_model(ml_db, cfg)
    assert result["success"] is True
    assert result.get("test_metrics", {}).get("roc_auc") is not None
    assert result["scored_accounts"] == 40

    status = get_ml_status(ml_db)
    assert status["active_model"] is not None

    with ml_db.get_connection() as conn:
        row = conn.execute(
            "SELECT ml_fraud_probability FROM fraud_results WHERE duid = 'fraud0'"
        ).fetchone()
    assert row[0] is not None
    assert 0 <= row[0] <= 1

    cmp = FraudMLTrainer.compare_to_rules(ml_db, cfg)
    assert cmp["labeled_count"] == 40
    assert cmp["rules"] is not None
