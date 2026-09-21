"""
Fraud intelligence: time-series trends, simple projections, affiliate trajectory.

Designed for the dashboard overview — plain metrics anyone can read.
"""
from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Affiliate momentum action filter (matches affiliate_actions table)
TRAJECTORY_ACTION_FILTERS = frozenset({
    'all', 'needs_action', 'not_actioned', 'actioned', 'terminated',
    'warned', 'capped', 'traffic_closed', 'monitoring', 'cleared',
})


def affiliate_matches_trajectory_action_filter(
    action: Optional[Dict[str, Any]],
    action_filter: str,
) -> bool:
    """Return True if affiliate should appear for the given momentum action filter."""
    key = (action_filter or 'all').strip().lower()
    if key not in TRAJECTORY_ACTION_FILTERS:
        key = 'all'
    if key == 'all':
        return True

    status = (action or {}).get('action_status') or None
    action_type = (action or {}).get('action_type') or None

    if key == 'needs_action':
        return not status or status in ('flagged', 'under_review')
    if key == 'not_actioned':
        return not status or status not in ('actioned', 'cleared')
    if key == 'actioned':
        return status == 'actioned'
    if key == 'terminated':
        return action_type == 'terminated'
    if key == 'warned':
        return action_type == 'warned'
    if key == 'capped':
        return action_type == 'capped'
    if key == 'traffic_closed':
        return action_type == 'traffic_closed'
    if key == 'monitoring':
        return status == 'monitoring'
    if key == 'cleared':
        return status == 'cleared'
    return True


class FraudIntelligence:
    """Trends, projections, and per-affiliate trajectory from fraud_results + outcomes."""

    def __init__(self, db):
        self.db = db
        self.db_path = getattr(db, "db_path", "affiliate_data.db")

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def get_time_series(self, days: int = 90) -> Dict[str, Any]:
        """
        Daily counts: analyzed accounts, high-risk count, high-risk payout sum.
        Uses calendar day of COALESCE(trans_datetime, analyzed_at).
        """
        days = max(7, min(int(days), 365))
        end = datetime.now().date()
        start = end - timedelta(days=days - 1)

        q = """
            SELECT
                date(COALESCE(NULLIF(TRIM(trans_datetime), ''), analyzed_at)) AS d,
                COUNT(*) AS analyzed,
                SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) AS high_risk,
                SUM(CASE WHEN risk_score >= 50 THEN COALESCE(payout_amount, 0) ELSE 0 END) AS at_risk_payout
            FROM fraud_results
            WHERE date(COALESCE(NULLIF(TRIM(trans_datetime), ''), analyzed_at)) >= date(?)
              AND date(COALESCE(NULLIF(TRIM(trans_datetime), ''), analyzed_at)) <= date(?)
            GROUP BY d
            ORDER BY d
        """
        with self._conn() as conn:
            df = pd.read_sql_query(q, conn, params=[start.isoformat(), end.isoformat()])

        idx = pd.date_range(start=start, end=end, freq="D")
        series: List[Dict[str, Any]] = []
        if df.empty:
            for d in idx:
                series.append(
                    {
                        "date": d.strftime("%Y-%m-%d"),
                        "analyzed": 0,
                        "high_risk": 0,
                        "at_risk_payout": 0.0,
                    }
                )
        else:
            df["d"] = pd.to_datetime(df["d"])
            df = df.set_index("d").reindex(idx).fillna(0)
            for d in idx:
                row = df.loc[d]
                series.append(
                    {
                        "date": d.strftime("%Y-%m-%d"),
                        "analyzed": int(row["analyzed"] or 0),
                        "high_risk": int(row["high_risk"] or 0),
                        "at_risk_payout": float(row["at_risk_payout"] or 0),
                    }
                )

        return {"granularity": "daily", "days": days, "series": series}

    def get_projection(self, lookback_days: int = 14) -> Dict[str, Any]:
        """
        Linear extrapolation from recent daily averages (not ML).
        """
        lookback_days = max(7, min(int(lookback_days), 90))
        end = datetime.now().date()
        start = end - timedelta(days=lookback_days - 1)

        q = """
            SELECT
                SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) AS high_risk,
                SUM(CASE WHEN risk_score >= 50 THEN COALESCE(payout_amount, 0) ELSE 0 END) AS at_risk_payout
            FROM fraud_results
            WHERE date(COALESCE(NULLIF(TRIM(trans_datetime), ''), analyzed_at)) >= date(?)
              AND date(COALESCE(NULLIF(TRIM(trans_datetime), ''), analyzed_at)) <= date(?)
        """
        with self._conn() as conn:
            row = pd.read_sql_query(q, conn, params=[start.isoformat(), end.isoformat()]).iloc[0]

        high = float(row.get("high_risk") or 0)
        payout = float(row.get("at_risk_payout") or 0)
        n = float(lookback_days)
        daily_high = high / n if n else 0.0
        daily_payout = payout / n if n else 0.0

        return {
            "lookback_days": lookback_days,
            "period_high_risk_accounts": int(high),
            "period_at_risk_payout": round(payout, 2),
            "avg_daily_high_risk": round(daily_high, 2),
            "avg_daily_at_risk_payout": round(daily_payout, 2),
            "projected_monthly_high_risk": round(daily_high * 30, 1),
            "projected_monthly_at_risk_payout": round(daily_payout * 30, 2),
            "explanation": (
                f"Based on the last {lookback_days} days: if this pace continues, "
                f"about {round(daily_payout * 30, 0):,.0f} in high-risk payout could surface per month "
                f"({round(daily_high * 30, 0):,.0f} high-risk accounts)."
            ),
        }

    def _load_affiliate_actions_map(self) -> Dict[str, Dict[str, Any]]:
        """webmaster_code (lower) → action fields from affiliate_actions."""
        try:
            with self._conn() as conn:
                df = pd.read_sql_query(
                    """
                    SELECT webmaster_code, action_status, action_type, actioned_at
                    FROM affiliate_actions
                    """,
                    conn,
                )
        except Exception:
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for _, row in df.iterrows():
            code = str(row.get('webmaster_code') or '').strip()
            if not code:
                continue
            out[code.lower()] = {
                'action_status': row.get('action_status') or None,
                'action_type': row.get('action_type') or None,
                'actioned_at': row.get('actioned_at') or None,
            }
        return out

    def get_affiliate_trajectory(
        self,
        weeks: int = 4,
        min_accounts: int = 15,
        action_filter: str = 'needs_action',
        exclude_affiliates_lower: Optional[frozenset] = None,
    ) -> Dict[str, Any]:
        """
        Compare fraud-rate in first half vs second half of the window (by ISO week).
        """
        weeks = max(2, min(int(weeks), 12))
        days = weeks * 7
        end = datetime.now().date()
        start = end - timedelta(days=days - 1)

        q = """
            SELECT
                webmaster_code AS aff,
                strftime('%Y-%W', COALESCE(NULLIF(TRIM(trans_datetime), ''), analyzed_at)) AS yw,
                COUNT(*) AS total,
                SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) AS high_risk
            FROM fraud_results
            WHERE webmaster_code IS NOT NULL AND TRIM(webmaster_code) != ''
              AND date(COALESCE(NULLIF(TRIM(trans_datetime), ''), analyzed_at)) >= date(?)
              AND date(COALESCE(NULLIF(TRIM(trans_datetime), ''), analyzed_at)) <= date(?)
            GROUP BY aff, yw
        """
        with self._conn() as conn:
            df = pd.read_sql_query(q, conn, params=[start.isoformat(), end.isoformat()])

        if df.empty:
            return {"weeks": weeks, "affiliates": [], "note": "No affiliate data in range."}

        # Order weeks chronologically
        week_keys = sorted(df["yw"].dropna().unique().tolist())
        if len(week_keys) < 2:
            return {"weeks": weeks, "affiliates": [], "note": "Need at least two weeks of data."}

        mid = len(week_keys) // 2
        early_weeks = set(week_keys[:mid])
        late_weeks = set(week_keys[mid:])
        actions_map = self._load_affiliate_actions_map()

        by_aff: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "early_total": 0,
                "early_high": 0,
                "late_total": 0,
                "late_high": 0,
            }
        )

        for _, row in df.iterrows():
            aff = row["aff"]
            yw = row["yw"]
            t = int(row["total"] or 0)
            h = int(row["high_risk"] or 0)
            if yw in early_weeks:
                by_aff[aff]["early_total"] += t
                by_aff[aff]["early_high"] += h
            if yw in late_weeks:
                by_aff[aff]["late_total"] += t
                by_aff[aff]["late_high"] += h

        skip = exclude_affiliates_lower or frozenset()
        out: List[Dict[str, Any]] = []
        for aff, agg in by_aff.items():
            if skip and str(aff).strip().lower() in skip:
                continue
            vol = agg["early_total"] + agg["late_total"]
            if vol < min_accounts:
                continue
            er = (agg["early_high"] / agg["early_total"] * 100) if agg["early_total"] else 0.0
            lr = (agg["late_high"] / agg["late_total"] * 100) if agg["late_total"] else 0.0
            delta = lr - er
            if lr > er * 1.2 and delta > 3:
                direction = "accelerating"
                hint = "High-risk share is rising — prioritize review."
            elif lr < er * 0.8 and delta < -3:
                direction = "improving"
                hint = "High-risk share is falling vs earlier weeks."
            else:
                direction = "stable"
                hint = "Roughly flat vs earlier weeks."

            act = actions_map.get(str(aff).strip().lower())
            if not affiliate_matches_trajectory_action_filter(act, action_filter):
                continue

            out.append(
                {
                    "webmaster_code": aff,
                    "accounts_in_window": vol,
                    "early_high_risk_pct": round(er, 1),
                    "late_high_risk_pct": round(lr, 1),
                    "change_pp": round(delta, 1),
                    "direction": direction,
                    "hint": hint,
                    "action_status": (act or {}).get("action_status"),
                    "action_type": (act or {}).get("action_type"),
                    "actioned_at": (act or {}).get("actioned_at"),
                }
            )

        out.sort(key=lambda x: (-x["late_high_risk_pct"], -x["accounts_in_window"]))
        filt_key = (action_filter or 'needs_action').strip().lower()
        if filt_key not in TRAJECTORY_ACTION_FILTERS:
            filt_key = 'needs_action'
        return {
            "weeks": weeks,
            "week_span": f"{start.isoformat()} → {end.isoformat()}",
            "action_filter": filt_key,
            "affiliates": out[:25],
        }

    def get_funnel_with_dollars(
        self,
        analyzed_date_from: Optional[str] = None,
        analyzed_date_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Same logical funnel as /api/detection-funnel with dollar amounts per stage.
        Outcome counts include only high-risk accounts (score ≥ 50) in the analysis-date window.
        """
        bounds = ""
        params: list = []
        if analyzed_date_from:
            bounds += " AND DATE(analyzed_at) >= DATE(?)"
            params.append(analyzed_date_from)
        if analyzed_date_to:
            bounds += " AND DATE(analyzed_at) <= DATE(?)"
            params.append(analyzed_date_to)

        bounds_fr = ""
        params_fr: list = []
        if analyzed_date_from:
            bounds_fr += " AND DATE(fr.analyzed_at) >= DATE(?)"
            params_fr.append(analyzed_date_from)
        if analyzed_date_to:
            bounds_fr += " AND DATE(fr.analyzed_at) <= DATE(?)"
            params_fr.append(analyzed_date_to)

        with self._conn() as conn:
            q = f"""
                SELECT
                    COUNT(*) AS total_analyzed,
                    SUM(CASE WHEN risk_score >= 50 THEN 1 ELSE 0 END) AS high_risk,
                    SUM(CASE WHEN risk_score >= 25 AND risk_score < 50 THEN 1 ELSE 0 END) AS medium_risk,
                    SUM(CASE WHEN risk_score >= 50 THEN COALESCE(payout_amount, 0) ELSE 0 END) AS high_risk_payout,
                    SUM(COALESCE(payout_amount, 0)) AS total_payout_analyzed
                FROM fraud_results
                WHERE 1=1{bounds}
            """
            totals = pd.read_sql_query(q, conn, params=params).iloc[0].to_dict()

            oq = f"""
                SELECT
                    COUNT(*) AS reviewed,
                    SUM(CASE WHEN fo.outcome='confirmed_fraud' THEN 1 ELSE 0 END) AS confirmed,
                    SUM(CASE WHEN fo.outcome='false_positive' THEN 1 ELSE 0 END) AS false_positives,
                    SUM(CASE WHEN fo.outcome='under_review' THEN 1 ELSE 0 END) AS under_review,
                    SUM(CASE WHEN fo.outcome='confirmed_fraud' THEN COALESCE(fo.payout_amount, 0) ELSE 0 END) AS confirmed_payout
                FROM fraud_outcomes fo
                INNER JOIN fraud_results fr ON fo.duid = fr.duid
                WHERE fr.risk_score >= 50{bounds_fr}
            """
            outcomes = pd.read_sql_query(oq, conn, params=params_fr).iloc[0].to_dict()

        total = int(totals.get("total_analyzed") or 0)
        high = int(totals.get("high_risk") or 0)
        reviewed = int(outcomes.get("reviewed") or 0)
        confirmed = int(outcomes.get("confirmed") or 0)

        def pct(num: float, den: int) -> float:
            return round(num / den * 100, 1) if den > 0 else 0.0

        stages = [
            {
                "id": "analyzed",
                "label": "Accounts analyzed",
                "count": total,
                "amount": float(totals.get("total_payout_analyzed") or 0),
                "pct_of_prior": 100.0,
            },
            {
                "id": "flagged_high",
                "label": "Flagged high risk (≥50)",
                "count": high,
                "amount": float(totals.get("high_risk_payout") or 0),
                "pct_of_prior": pct(high, total),
            },
            {
                "id": "reviewed",
                "label": "Reviewed (outcome recorded)",
                "count": reviewed,
                "amount": None,
                "pct_of_prior": pct(reviewed, high) if high else 0.0,
            },
            {
                "id": "confirmed",
                "label": "Confirmed fraud",
                "count": confirmed,
                "amount": float(outcomes.get("confirmed_payout") or 0),
                "pct_of_prior": pct(confirmed, reviewed) if reviewed else 0.0,
            },
        ]

        return {"stages": stages, "pending_high_risk": max(0, high - reviewed)}

    def get_dashboard_bundle(
        self,
        days: int = 90,
        lookback: int = 14,
        trajectory_weeks: int = 4,
        trajectory_action_filter: str = 'needs_action',
        funnel_analyzed_date_from: Optional[str] = None,
        funnel_analyzed_date_to: Optional[str] = None,
        exclude_affiliates_lower: Optional[frozenset] = None,
    ) -> Dict[str, Any]:
        return {
            "generated_at": datetime.now().isoformat(),
            "time_series": self.get_time_series(days=days),
            "projection": self.get_projection(lookback_days=lookback),
            "affiliate_trajectory": self.get_affiliate_trajectory(
                weeks=trajectory_weeks,
                action_filter=trajectory_action_filter,
                exclude_affiliates_lower=exclude_affiliates_lower,
            ),
            "funnel_dollars": self.get_funnel_with_dollars(
                analyzed_date_from=funnel_analyzed_date_from,
                analyzed_date_to=funnel_analyzed_date_to,
            ),
        }
