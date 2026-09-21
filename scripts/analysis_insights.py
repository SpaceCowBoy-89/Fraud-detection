"""
Actionable analysis insights for the dashboard Analysis page.

Unified rule stats, rising patterns, co-occurrence, action items, and review coverage.
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

from flag_utils import (
    catalog_flags_from_cell,
    normalize_flag_catalog_key,
    parse_flags_cell,
    precision_confidence,
    rule_status,
)

PRECISION_OUTCOMES = frozenset({"confirmed_fraud", "false_positive"})
ALL_OUTCOME_TYPES = frozenset({
    "confirmed_fraud", "false_positive", "under_review", "legitimate",
})


def _date_col_expr() -> str:
    return "COALESCE(fr.trans_datetime, fr.analyzed_at)"


def _build_filters(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    affiliate: Optional[str] = None,
    campaign: Optional[str] = None,
    min_risk: Optional[int] = None,
    max_risk: Optional[int] = None,
) -> Tuple[str, List[Any]]:
    clauses = []
    params: List[Any] = []
    if date_from:
        clauses.append(f"DATE({_date_col_expr()}) >= DATE(?)")
        params.append(date_from)
    if date_to:
        clauses.append(f"DATE({_date_col_expr()}) <= DATE(?)")
        params.append(date_to)
    if affiliate:
        clauses.append("LOWER(fr.webmaster_code) = LOWER(?)")
        params.append(affiliate.strip())
    if campaign:
        clauses.append("LOWER(fr.campaign) = LOWER(?)")
        params.append(campaign.strip())
    if min_risk is not None:
        clauses.append("fr.risk_score >= ?")
        params.append(int(min_risk))
    if max_risk is not None:
        clauses.append("fr.risk_score <= ?")
        params.append(int(max_risk))
    where = (" AND " + " AND ".join(clauses)) if clauses else ""
    return where, params


class AnalysisInsights:
    """Compute actionable metrics for the Analysis dashboard."""

    def __init__(self, db):
        self.db = db
        self.db_path = getattr(db, "db_path", "affiliate_data.db")

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _load_results_with_outcomes(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        affiliate: Optional[str] = None,
        campaign: Optional[str] = None,
        min_risk: Optional[int] = None,
        max_risk: Optional[int] = None,
    ) -> "pd.DataFrame":
        import pandas as pd

        where, params = _build_filters(
            date_from, date_to, affiliate, campaign, min_risk, max_risk,
        )
        q = f"""
            SELECT
                fr.duid,
                fr.email,
                fr.flags,
                fr.risk_score,
                fr.payout_amount,
                fr.webmaster_code,
                fr.campaign,
                fr.analyzed_at,
                fr.trans_datetime,
                fo.outcome,
                fo.payout_amount AS outcome_payout
            FROM fraud_results fr
            LEFT JOIN fraud_outcomes fo ON fr.duid = fo.duid
            WHERE fr.flags IS NOT NULL AND fr.flags != '' AND fr.flags != '[]'
            {where}
        """
        with self._conn() as conn:
            return pd.read_sql_query(q, conn, params=params)

    def compute_rule_stats(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        affiliate: Optional[str] = None,
        campaign: Optional[str] = None,
        min_reviewed: int = 1,
    ) -> Dict[str, Any]:
        """Unified per-rule stats with confidence metadata."""
        df = self._load_results_with_outcomes(date_from, date_to, affiliate, campaign)
        if df.empty:
            return {"rules": [], "summary": self._empty_rule_summary()}

        stats = defaultdict(lambda: {
            "flagged": 0,
            "reviewed": 0,
            "confirmed": 0,
            "false_positive": 0,
            "under_review": 0,
            "legitimate": 0,
            "unreviewed": 0,
            "fp_cost": 0.0,
        })

        for _, row in df.iterrows():
            outcome = row.get("outcome")
            payout = float(row.get("outcome_payout") or row.get("payout_amount") or 0)
            flags = catalog_flags_from_cell(row.get("flags"))
            for flag in flags:
                s = stats[flag]
                s["flagged"] += 1
                if outcome in PRECISION_OUTCOMES:
                    s["reviewed"] += 1
                    if outcome == "confirmed_fraud":
                        s["confirmed"] += 1
                    else:
                        s["false_positive"] += 1
                        s["fp_cost"] += payout
                elif outcome == "under_review":
                    s["under_review"] += 1
                elif outcome == "legitimate":
                    s["legitimate"] += 1
                elif outcome is None or (isinstance(outcome, float) and pd.isna(outcome)):
                    s["unreviewed"] += 1

        rules = []
        for rule, s in stats.items():
            reviewed = s["confirmed"] + s["false_positive"]
            if reviewed < min_reviewed and s["flagged"] < 3:
                continue
            precision = round(s["confirmed"] / reviewed * 100, 1) if reviewed > 0 else None
            fp_rate = round(s["false_positive"] / reviewed * 100, 1) if reviewed > 0 else None
            confidence = precision_confidence(reviewed)
            rules.append({
                "rule": rule,
                "flagged": s["flagged"],
                "reviewed": reviewed,
                "confirmed": s["confirmed"],
                "false_positive": s["false_positive"],
                "under_review": s["under_review"],
                "legitimate": s["legitimate"],
                "unreviewed": s["unreviewed"],
                "precision": precision,
                "fp_rate": fp_rate,
                "fp_cost": round(s["fp_cost"], 2),
                "confidence": confidence,
                "status": rule_status(precision, reviewed),
            })

        rules.sort(key=lambda r: (-(r["flagged"]), r["precision"] if r["precision"] is not None else 999))

        total_flagged = len(df)
        reviewed_rows = df[df["outcome"].isin(PRECISION_OUTCOMES)]
        summary = {
            "total_flagged_accounts": total_flagged,
            "total_reviewed": int(len(reviewed_rows)),
            "confirmed_fraud": int((reviewed_rows["outcome"] == "confirmed_fraud").sum()),
            "false_positive": int((reviewed_rows["outcome"] == "false_positive").sum()),
            "under_review": int((df["outcome"] == "under_review").sum()),
            "legitimate": int((df["outcome"] == "legitimate").sum()),
            "unreviewed": int(df["outcome"].isna().sum()),
        }
        if summary["total_reviewed"] > 0:
            summary["overall_precision"] = round(
                summary["confirmed_fraud"] / summary["total_reviewed"] * 100, 1,
            )
            summary["overall_fp_rate"] = round(
                summary["false_positive"] / summary["total_reviewed"] * 100, 1,
            )
        else:
            summary["overall_precision"] = None
            summary["overall_fp_rate"] = None

        return {"rules": rules, "summary": summary}

    def _empty_rule_summary(self) -> Dict[str, Any]:
        return {
            "total_flagged_accounts": 0,
            "total_reviewed": 0,
            "confirmed_fraud": 0,
            "false_positive": 0,
            "under_review": 0,
            "legitimate": 0,
            "unreviewed": 0,
            "overall_precision": None,
            "overall_fp_rate": None,
        }

    def compute_fp_analysis(self, **filters) -> Dict[str, Any]:
        """False-positive breakdown derived from unified rule stats."""
        data = self.compute_rule_stats(**filters)
        rules = data["rules"]
        flag_analysis = []
        for r in rules:
            reviewed = r["reviewed"]
            if reviewed < 3:
                continue
            flag_analysis.append({
                "flag": r["rule"],
                "fraud_count": r["confirmed"],
                "fp_count": r["false_positive"],
                "total": reviewed,
                "precision": r["precision"],
                "fp_rate": r["fp_rate"],
                "confidence": r["confidence"],
            })
        flag_analysis.sort(key=lambda x: x["precision"] if x["precision"] is not None else 100)
        summary = data["summary"]
        return {
            "flag_analysis": flag_analysis,
            "total_reviewed": summary["total_reviewed"],
            "total_fraud": summary["confirmed_fraud"],
            "total_fp": summary["false_positive"],
            "summary": summary,
        }

    def compute_fp_cost(self, **filters) -> Dict[str, Any]:
        """FP dollar impact from unified rule stats."""
        import pandas as pd

        with self._conn() as conn:
            fp_df = pd.read_sql_query("""
                SELECT fo.duid, fo.payout_amount, fo.reviewed_at
                FROM fraud_outcomes fo
                WHERE fo.outcome = 'false_positive'
                ORDER BY fo.reviewed_at DESC
            """, conn)

        rule_data = self.compute_rule_stats(**filters)
        by_flag = sorted(
            [
                {
                    "flag": r["rule"],
                    "count": r["false_positive"],
                    "cost": r["fp_cost"],
                    "avg_cost": round(r["fp_cost"] / r["false_positive"], 2) if r["false_positive"] else 0,
                    "precision": r["precision"],
                    "confidence": r["confidence"],
                }
                for r in rule_data["rules"]
                if r["false_positive"] > 0
            ],
            key=lambda x: x["cost"],
            reverse=True,
        )[:15]

        if fp_df.empty:
            return {
                "summary": {"total_fp": 0, "total_cost": 0, "avg_cost": 0, "median_cost": 0},
                "by_flag": by_flag,
                "monthly": [],
            }

        total_fp = len(fp_df)
        total_cost = float(fp_df["payout_amount"].sum())
        fp_df["month"] = pd.to_datetime(fp_df["reviewed_at"], errors="coerce").dt.to_period("M").astype(str)
        monthly = (
            fp_df.groupby("month")
            .agg(count=("duid", "count"), cost=("payout_amount", "sum"))
            .reset_index()
            .rename(columns={"month": "period"})
            .sort_values("period")
            .tail(12)
            .to_dict(orient="records")
        )
        return {
            "summary": {
                "total_fp": total_fp,
                "total_cost": round(total_cost, 2),
                "avg_cost": round(total_cost / total_fp, 2) if total_fp else 0,
                "median_cost": round(float(fp_df["payout_amount"].median()), 2),
            },
            "by_flag": by_flag,
            "monthly": monthly,
        }

    def compute_rising_patterns(
        self,
        recent_days: int = 7,
        baseline_days: int = 28,
        min_recent: int = 3,
        min_delta_pct: float = 50.0,
        **filters,
    ) -> Dict[str, Any]:
        """Compare recent window vs baseline for flags, domains, affiliates, campaigns."""
        import pandas as pd

        df = self._load_results_with_outcomes(**filters)
        if df.empty:
            return {"flags": [], "domains": [], "affiliates": [], "campaigns": [], "risk_bands": []}

        df["event_date"] = pd.to_datetime(
            df["trans_datetime"].fillna(df["analyzed_at"]), errors="coerce",
        ).dt.date
        df = df.dropna(subset=["event_date"])
        if df.empty:
            return {"flags": [], "domains": [], "affiliates": [], "campaigns": [], "risk_bands": []}

        end = df["event_date"].max()
        recent_start = end - timedelta(days=recent_days - 1)
        baseline_end = recent_start - timedelta(days=1)
        baseline_start = baseline_end - timedelta(days=baseline_days - 1)

        recent = df[(df["event_date"] >= recent_start) & (df["event_date"] <= end)]
        baseline = df[(df["event_date"] >= baseline_start) & (df["event_date"] <= baseline_end)]

        def _rising(counter_recent: Counter, counter_base: Counter, label_key: str) -> List[Dict]:
            items = []
            all_keys = set(counter_recent) | set(counter_base)
            for key in all_keys:
                r_cnt = counter_recent.get(key, 0)
                b_cnt = counter_base.get(key, 0)
                if r_cnt < min_recent:
                    continue
                base_rate = b_cnt / baseline_days if baseline_days else 0
                recent_rate = r_cnt / recent_days if recent_days else 0
                if base_rate > 0:
                    delta_pct = round((recent_rate - base_rate) / base_rate * 100, 1)
                elif recent_rate > 0:
                    delta_pct = 100.0
                else:
                    delta_pct = 0.0
                if delta_pct < min_delta_pct and r_cnt < min_recent * 2:
                    continue
                items.append({
                    label_key: key,
                    "recent_count": r_cnt,
                    "baseline_count": b_cnt,
                    "recent_rate": round(recent_rate, 2),
                    "baseline_rate": round(base_rate, 2),
                    "delta_pct": delta_pct,
                })
            items.sort(key=lambda x: (-x["delta_pct"], -x["recent_count"]))
            return items[:20]

        flag_recent, flag_base = Counter(), Counter()
        for flags in recent["flags"]:
            for f in catalog_flags_from_cell(flags):
                flag_recent[f] += 1
        for flags in baseline["flags"]:
            for f in catalog_flags_from_cell(flags):
                flag_base[f] += 1

        def _domain_counter(frame) -> Counter:
            c = Counter()
            for email in frame["email"].fillna(""):
                if "@" in str(email):
                    c[str(email).split("@")[1].lower()] += 1
            return c

        domain_recent = _domain_counter(recent)
        domain_base = _domain_counter(baseline)

        aff_recent = Counter(recent["webmaster_code"].dropna().astype(str))
        aff_base = Counter(baseline["webmaster_code"].dropna().astype(str))

        camp_recent = Counter(recent["campaign"].dropna().astype(str))
        camp_base = Counter(baseline["campaign"].dropna().astype(str))

        def _risk_band(score):
            if score >= 50:
                return "high"
            if score >= 25:
                return "medium"
            return "low"

        risk_recent = Counter(recent["risk_score"].apply(_risk_band))
        risk_base = Counter(baseline["risk_score"].apply(_risk_band))

        return {
            "window": {
                "recent_days": recent_days,
                "baseline_days": baseline_days,
                "recent_start": str(recent_start),
                "recent_end": str(end),
                "baseline_start": str(baseline_start),
                "baseline_end": str(baseline_end),
            },
            "flags": _rising(flag_recent, flag_base, "flag"),
            "domains": _rising(domain_recent, domain_base, "domain"),
            "affiliates": _rising(aff_recent, aff_base, "affiliate"),
            "campaigns": _rising(camp_recent, camp_base, "campaign"),
            "risk_bands": _rising(risk_recent, risk_base, "risk_band"),
        }

    def compute_rule_cooccurrence(
        self,
        min_reviewed: int = 5,
        max_combo_size: int = 3,
        **filters,
    ) -> Dict[str, Any]:
        """High-signal flag combinations from reviewed accounts."""
        df = self._load_results_with_outcomes(**filters)
        reviewed = df[df["outcome"].isin(PRECISION_OUTCOMES)].copy()
        if reviewed.empty:
            return {"pairs": [], "triples": []}

        pair_stats = defaultdict(lambda: {"fraud": 0, "fp": 0})
        triple_stats = defaultdict(lambda: {"fraud": 0, "fp": 0})

        for _, row in reviewed.iterrows():
            flags = sorted(set(catalog_flags_from_cell(row.get("flags"))))
            if len(flags) < 2:
                continue
            is_fraud = row["outcome"] == "confirmed_fraud"
            for combo in combinations(flags, 2):
                key = " + ".join(combo)
                if is_fraud:
                    pair_stats[key]["fraud"] += 1
                else:
                    pair_stats[key]["fp"] += 1
            if len(flags) >= 3 and max_combo_size >= 3:
                for combo in combinations(flags, 3):
                    key = " + ".join(combo)
                    if is_fraud:
                        triple_stats[key]["fraud"] += 1
                    else:
                        triple_stats[key]["fp"] += 1

        def _format(stats_dict, combo_size: int) -> List[Dict]:
            out = []
            for combo, st in stats_dict.items():
                total = st["fraud"] + st["fp"]
                if total < min_reviewed:
                    continue
                precision = round(st["fraud"] / total * 100, 1)
                out.append({
                    "combo": combo,
                    "combo_size": combo_size,
                    "confirmed_fraud": st["fraud"],
                    "false_positive": st["fp"],
                    "reviewed": total,
                    "precision": precision,
                    "confidence": precision_confidence(total),
                })
            out.sort(key=lambda x: (-x["precision"], -x["reviewed"]))
            return out[:25]

        return {
            "pairs": _format(pair_stats, 2),
            "triples": _format(triple_stats, 3),
            "min_reviewed": min_reviewed,
        }

    def compute_review_coverage(self) -> Dict[str, Any]:
        """Review and sampling coverage metrics."""
        with self._conn() as conn:
            c = conn.cursor()
            coverage = {}

            for tier, lo, hi in [("high", 50, 999), ("medium", 25, 49), ("low", 0, 24)]:
                c.execute(
                    "SELECT COUNT(*) FROM fraud_results WHERE risk_score >= ? AND risk_score <= ?",
                    (lo, hi),
                )
                total = c.fetchone()[0] or 0
                c.execute("""
                    SELECT COUNT(DISTINCT fr.duid)
                    FROM fraud_results fr
                    INNER JOIN fraud_outcomes fo ON fr.duid = fo.duid
                    WHERE fr.risk_score >= ? AND fr.risk_score <= ?
                """, (lo, hi))
                reviewed = c.fetchone()[0] or 0
                coverage[tier] = {
                    "total": total,
                    "reviewed": reviewed,
                    "pct_reviewed": round(reviewed / total * 100, 1) if total else 0,
                }

            c.execute("SELECT COUNT(*) FROM low_risk_samples")
            samples_total = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM low_risk_samples WHERE review_status = 'pending'")
            samples_pending = c.fetchone()[0] or 0
            c.execute("SELECT COUNT(*) FROM low_risk_samples WHERE review_status = 'missed_fraud'")
            missed_fraud = c.fetchone()[0] or 0
            c.execute("""
                SELECT COUNT(*) FROM low_risk_samples
                WHERE review_status IN ('missed_fraud', 'legitimate')
            """)
            samples_reviewed = c.fetchone()[0] or 0

        est_fn_rate = None
        if samples_reviewed > 0:
            est_fn_rate = round(missed_fraud / samples_reviewed * 100, 2)

        return {
            "tiers": coverage,
            "sampling": {
                "total_samples": samples_total,
                "pending": samples_pending,
                "reviewed": samples_reviewed,
                "missed_fraud": missed_fraud,
                "estimated_false_negative_rate": est_fn_rate,
            },
        }

    def compute_action_items(self, **filters) -> Dict[str, Any]:
        """Prioritized actionable cards for fraud ops."""
        items: List[Dict[str, Any]] = []
        rule_data = self.compute_rule_stats(**filters)
        rising = self.compute_rising_patterns(**filters)
        coverage = self.compute_review_coverage()

        # Unresolved confirmed fraud (resolution_status added at runtime in some DBs)
        import pandas as pd

        u_cnt, u_payout = 0, 0.0
        with self._conn() as conn:
            try:
                unresolved = pd.read_sql_query("""
                    SELECT COUNT(*) AS cnt,
                           COALESCE(SUM(payout_amount), 0) AS payout
                    FROM fraud_outcomes
                    WHERE outcome = 'confirmed_fraud'
                      AND (resolution_status IS NULL OR resolution_status = 'pending')
                """, conn)
                u_cnt = int(unresolved.iloc[0]["cnt"] or 0)
                u_payout = float(unresolved.iloc[0]["payout"] or 0)
            except Exception:
                unresolved = pd.read_sql_query("""
                    SELECT COUNT(*) AS cnt,
                           COALESCE(SUM(payout_amount), 0) AS payout
                    FROM fraud_outcomes
                    WHERE outcome = 'confirmed_fraud'
                """, conn)
                u_cnt = int(unresolved.iloc[0]["cnt"] or 0)
                u_payout = float(unresolved.iloc[0]["payout"] or 0)
        if u_cnt > 0:
            items.append({
                "id": "unresolved_fraud",
                "priority": 1,
                "severity": "high",
                "title": f"{u_cnt} confirmed fraud accounts unresolved",
                "detail": f"${u_payout:,.0f} payout awaiting closure action",
                "action": "Review Resolution queue",
                "drilldown": "resolution",
            })

        # High FP cost / low precision rules
        for r in rule_data["rules"]:
            if r["reviewed"] >= 5 and r["precision"] is not None and r["precision"] < 60:
                items.append({
                    "id": f"low_precision_{r['rule']}",
                    "priority": 2,
                    "severity": "high" if r["fp_cost"] >= 500 else "medium",
                    "title": f"{r['rule'].replace('_', ' ')} precision is {r['precision']}%",
                    "detail": (
                        f"{r['false_positive']} false positives, ${r['fp_cost']:,.0f} FP cost "
                        f"({r['confidence']} confidence, n={r['reviewed']})"
                    ),
                    "action": "Tune rule or raise threshold",
                    "drilldown": "rule_quality",
                    "flag": r["rule"],
                })
                if len([i for i in items if i["priority"] == 2]) >= 5:
                    break

        # Rising flags
        for entry in rising.get("flags", [])[:5]:
            items.append({
                "id": f"rising_flag_{entry['flag']}",
                "priority": 3,
                "severity": "medium",
                "title": f"Rising flag: {entry['flag'].replace('_', ' ')}",
                "detail": (
                    f"{entry['recent_count']} in last 7d vs {entry['baseline_count']} in prior 28d "
                    f"(+{entry['delta_pct']}% rate)"
                ),
                "action": "Investigate pattern movement",
                "drilldown": "patterns",
                "flag": entry["flag"],
            })

        # Low review coverage on high risk
        high_cov = coverage["tiers"]["high"]
        if high_cov["total"] > 0 and high_cov["pct_reviewed"] < 50:
            items.append({
                "id": "low_high_review_coverage",
                "priority": 4,
                "severity": "medium",
                "title": f"Only {high_cov['pct_reviewed']}% of high-risk accounts reviewed",
                "detail": f"{high_cov['reviewed']} of {high_cov['total']} high-risk rows have outcomes",
                "action": "Increase review throughput",
                "drilldown": "review",
            })

        # Sampling gap
        samp = coverage["sampling"]
        if samp["total_samples"] < 20 and coverage["tiers"]["low"]["total"] > 100:
            items.append({
                "id": "sampling_gap",
                "priority": 5,
                "severity": "low",
                "title": "Low-risk sampling coverage is thin",
                "detail": f"{samp['total_samples']} samples drawn; missed-fraud estimate unreliable",
                "action": "Generate sample batch",
                "drilldown": "monitoring",
            })
        elif samp.get("estimated_false_negative_rate") and samp["estimated_false_negative_rate"] >= 5:
            items.append({
                "id": "missed_fraud_in_samples",
                "priority": 4,
                "severity": "high",
                "title": f"~{samp['estimated_false_negative_rate']}% missed fraud in low-risk samples",
                "detail": f"{samp['missed_fraud']} missed fraud of {samp['reviewed']} reviewed samples",
                "action": "Review scoring thresholds",
                "drilldown": "monitoring",
            })

        # Affiliate trajectory warnings
        try:
            from fraud_intelligence import FraudIntelligence
            fi = FraudIntelligence(self.db)
            traj = fi.get_affiliate_trajectory(weeks=4, action_filter='needs_action')
            for aff in (traj.get("affiliates") or [])[:5]:
                if aff.get("direction") == "accelerating":
                    items.append({
                        "id": f"aff_trajectory_{aff.get('webmaster_code', '')}",
                        "priority": 3,
                        "severity": "medium",
                        "title": f"Affiliate {aff.get('webmaster_code')} fraud trend worsening",
                        "detail": (
                            f"Late-window high-risk {aff.get('late_high_risk_pct', '—')}% "
                            f"vs early {aff.get('early_high_risk_pct', '—')}% "
                            f"(+{aff.get('change_pp', 0)} pp)"
                        ),
                        "action": "Check affiliate actions",
                        "drilldown": "affiliates",
                        "affiliate": aff.get("webmaster_code"),
                    })
        except Exception:
            pass

        items.sort(key=lambda x: (x["priority"], {"high": 0, "medium": 1, "low": 2}[x["severity"]]))
        return {
            "items": items[:15],
            "generated_at": datetime.now().isoformat(),
            "coverage": coverage,
        }

    def compute_pattern_summary(
        self,
        min_risk: Optional[int] = None,
        **filters,
    ) -> Dict[str, Any]:
        """Flag frequency, domains, and risk distribution for Patterns tab."""
        import pandas as pd

        extra = dict(filters)
        if min_risk is not None:
            extra["min_risk"] = min_risk
        df = self._load_results_with_outcomes(**extra)
        if df.empty:
            return {"flags": [], "domains": [], "risk_distribution": [], "total_records": 0}

        flag_counts = Counter()
        for flags in df["flags"].fillna(""):
            for f in catalog_flags_from_cell(flags):
                flag_counts[f] += 1

        flags_data = [
            {"flag": f, "count": c, "pct": round(c / len(df) * 100, 1)}
            for f, c in flag_counts.most_common(20)
        ]

        domain_counts = Counter()
        for email in df["email"].fillna(""):
            if "@" in str(email):
                domain_counts[str(email).split("@")[1].lower()] += 1
        domains_data = [
            {"domain": d, "count": c, "pct": round(c / len(df) * 100, 1)}
            for d, c in domain_counts.most_common(15)
        ]

        risk_bins = [0, 25, 50, 75, 100]
        risk_labels = ["0-24", "25-49", "50-74", "75-100"]
        df = df.copy()
        df["risk_bin"] = pd.cut(
            df["risk_score"], bins=risk_bins, labels=risk_labels, include_lowest=True,
        )
        risk_dist = df["risk_bin"].value_counts().to_dict()
        risk_data = [{"range": r, "count": int(risk_dist.get(r, 0))} for r in risk_labels]

        return {
            "flags": flags_data,
            "domains": domains_data,
            "risk_distribution": risk_data,
            "total_records": len(df),
        }
