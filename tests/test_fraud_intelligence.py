"""Tests for fraud_intelligence time-series and projection helpers."""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from fraud_intelligence import FraudIntelligence  # noqa: E402


class TestFraudIntelligence(unittest.TestCase):
    def setUp(self):
        self.fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(self.fd)
        today = datetime.now().date()
        d_early = (today - timedelta(days=20)).isoformat()
        d_late = (today - timedelta(days=3)).isoformat()
        d_late2 = (today - timedelta(days=1)).isoformat()
        conn = sqlite3.connect(self.path)
        conn.execute(
            """CREATE TABLE fraud_results (
            duid TEXT PRIMARY KEY,
            risk_score INTEGER,
            payout_amount REAL,
            trans_datetime TEXT,
            analyzed_at TEXT,
            webmaster_code TEXT
        )"""
        )
        conn.execute(
            "INSERT INTO fraud_results VALUES (?,?,?,?,?,?)",
            ("a1", 55, 100.0, d_early, d_early, "affx"),
        )
        conn.execute(
            "INSERT INTO fraud_results VALUES (?,?,?,?,?,?)",
            ("a2", 20, 50.0, d_late, d_late, "affx"),
        )
        conn.execute(
            "INSERT INTO fraud_results VALUES (?,?,?,?,?,?)",
            ("a3", 60, 200.0, d_late2, d_late2, "affy"),
        )
        conn.execute(
            "INSERT INTO fraud_results VALUES (?,?,?,?,?,?)",
            ("a4", 70, 80.0, d_late, d_late, "affx"),
        )
        conn.commit()
        conn.close()

        class _DB:
            db_path = self.path

        self.intel = FraudIntelligence(_DB())

    def tearDown(self):
        os.unlink(self.path)

    def test_projection_nonzero(self):
        p = self.intel.get_projection(lookback_days=7)
        self.assertGreaterEqual(p["period_high_risk_accounts"], 2)
        self.assertGreater(p["period_at_risk_payout"], 0)

    def test_time_series_has_points(self):
        ts = self.intel.get_time_series(days=14)
        self.assertEqual(len(ts["series"]), 14)
        total_high = sum(x["high_risk"] for x in ts["series"])
        self.assertGreaterEqual(total_high, 2)

    def test_funnel_dollars_stages(self):
        conn = sqlite3.connect(self.path)
        conn.execute(
            """CREATE TABLE fraud_outcomes (
            duid TEXT PRIMARY KEY,
            outcome TEXT,
            payout_amount REAL
        )"""
        )
        conn.execute(
            "INSERT INTO fraud_outcomes VALUES (?,?,?)", ("a1", "confirmed_fraud", 100.0)
        )
        conn.commit()
        conn.close()
        f = self.intel.get_funnel_with_dollars()
        self.assertTrue(any(s["id"] == "confirmed" for s in f["stages"]))

    def test_trajectory_action_filter(self):
        conn = sqlite3.connect(self.path)
        conn.execute(
            """CREATE TABLE affiliate_actions (
            webmaster_code TEXT PRIMARY KEY,
            action_status TEXT,
            action_type TEXT,
            actioned_at TEXT
        )"""
        )
        conn.execute(
            "INSERT INTO affiliate_actions VALUES (?,?,?,?)",
            ("affy", "actioned", "terminated", "2026-01-01"),
        )
        conn.commit()
        conn.close()

        all_traj = self.intel.get_affiliate_trajectory(weeks=4, min_accounts=1, action_filter="all")
        codes_all = {a["webmaster_code"] for a in all_traj["affiliates"]}
        self.assertIn("affx", codes_all)
        self.assertIn("affy", codes_all)

        needs = self.intel.get_affiliate_trajectory(weeks=4, min_accounts=1, action_filter="needs_action")
        codes_needs = {a["webmaster_code"] for a in needs["affiliates"]}
        self.assertIn("affx", codes_needs)
        self.assertNotIn("affy", codes_needs)

        term = self.intel.get_affiliate_trajectory(weeks=4, min_accounts=1, action_filter="terminated")
        codes_term = {a["webmaster_code"] for a in term["affiliates"]}
        self.assertEqual(codes_term, {"affy"})
        self.assertEqual(term["affiliates"][0]["action_type"], "terminated")

    def test_trajectory_excludes_whitelisted_affiliates(self):
        needs = self.intel.get_affiliate_trajectory(
            weeks=4,
            min_accounts=1,
            action_filter="all",
            exclude_affiliates_lower=frozenset({"affx"}),
        )
        codes = {a["webmaster_code"] for a in needs["affiliates"]}
        self.assertNotIn("affx", codes)
        self.assertIn("affy", codes)


if __name__ == "__main__":
    unittest.main()
