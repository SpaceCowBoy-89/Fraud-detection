#!/usr/bin/env python3
"""Load and export the fraud detection flag reference catalog."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "docs" / "fraud_flags_catalog.json"
DEFAULT_EXTENDED_PATH = PROJECT_ROOT / "docs" / "fraud_flags_extended.json"


def catalog_path() -> Path:
    return DEFAULT_CATALOG_PATH


def extended_path() -> Path:
    return DEFAULT_EXTENDED_PATH


def load_extended(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or extended_path()
    if not p.is_file():
        return {"extensions": {}, "scoring_methodology": {}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_catalog(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or catalog_path()
    with open(p, encoding="utf-8") as f:
        catalog = json.load(f)
    extended = load_extended()
    extensions = extended.get("extensions") or {}
    for entry in catalog.get("flags", []):
        key = entry.get("catalog_key") or ""
        ext = extensions.get(key, {})
        for field in ("trigger", "explanation", "investigation", "score_tiers"):
            if field in ext and field not in entry:
                entry[field] = ext[field]
    catalog["scoring_methodology"] = extended.get("scoring_methodology") or {}
    return catalog


def _resolve_tier_points(tier: Dict[str, Any], risk_scores: Dict[str, Any]) -> int:
    ck = tier.get("config_key")
    if not ck:
        return int(tier.get("default_points") or 0)
    if ck in risk_scores:
        try:
            return int(risk_scores[ck])
        except (TypeError, ValueError):
            pass
    return int(tier.get("default_points") or 0)


def _resolve_score_tiers(entry: Dict[str, Any], risk_scores: Dict[str, Any]) -> List[Dict[str, Any]]:
    tiers = entry.get("score_tiers")
    if not tiers:
        ck = entry.get("points_config_key")
        return [
            {
                "condition": "When rule matches",
                "config_key": ck,
                "default_points": entry.get("default_points"),
                "active_points": _resolve_tier_points({"config_key": ck, "default_points": entry.get("default_points")}, risk_scores),
            }
        ]
    out = []
    for tier in tiers:
        row = dict(tier)
        row["active_points"] = _resolve_tier_points(tier, risk_scores)
        out.append(row)
    return out


def _format_tiers_summary(tiers: List[Dict[str, Any]]) -> str:
    parts = []
    for t in tiers:
        cond = t.get("condition") or "When rule matches"
        pts = t.get("active_points", t.get("default_points"))
        ck = t.get("config_key") or ""
        suffix = f" [{ck}]" if ck else ""
        parts.append(f"{pts} pts — {cond}{suffix}")
    return " | ".join(parts)


def _resolve_points(entry: Dict[str, Any], risk_scores: Dict[str, Any]) -> str:
    """Human-readable points for export (config-aware when numeric)."""
    return _format_tiers_summary(_resolve_score_tiers(entry, risk_scores))


def get_export_context() -> Dict[str, Any]:
    """Live thresholds and score weights from config.json."""
    try:
        from config import Config, DEFAULT_CONFIG

        cfg = Config()
        return {
            "risk_scores": dict(cfg.get("risk_scores") or {}),
            "risk_thresholds": dict(cfg.get("risk_thresholds") or DEFAULT_CONFIG.get("risk_thresholds", {})),
            "high_risk_countries": list(cfg.get("high_risk_countries") or []),
            "affiliate_domain_concentration_threshold": cfg.get("affiliate_domain_concentration_threshold"),
            "affiliate_domain_concentration_min_sample": cfg.get("affiliate_domain_concentration_min_sample"),
            "discover_concentration_threshold": cfg.get("discover_concentration_threshold"),
            "discover_concentration_min_sample": cfg.get("discover_concentration_min_sample"),
            "profile_image_fast_seconds": cfg.get("profile_image_fast_seconds"),
        }
    except Exception:
        return {"risk_scores": {}, "risk_thresholds": {}}


def get_risk_scores_from_config() -> Dict[str, Any]:
    return get_export_context().get("risk_scores") or {}


def enrich_catalog(
    catalog: Dict[str, Any],
    risk_scores: Optional[Dict[str, Any]] = None,
    export_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return catalog copy with resolved points and score tiers from config."""
    scores = risk_scores if risk_scores is not None else (export_context or {}).get("risk_scores") or {}
    out = dict(catalog)
    flags = []
    for entry in catalog.get("flags", []):
        row = dict(entry)
        tiers = _resolve_score_tiers(row, scores)
        row["score_tiers_resolved"] = tiers
        row["resolved_points"] = _format_tiers_summary(tiers)
        flags.append(row)
    out["flags"] = flags
    out["exported_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if export_context:
        out["active_config"] = export_context
        th = export_context.get("risk_thresholds") or {}
        if th:
            out["risk_thresholds"] = {
                "high": th.get("high", catalog.get("risk_thresholds", {}).get("high", 50)),
                "medium": th.get("medium", catalog.get("risk_thresholds", {}).get("medium", 25)),
                "low_max": int(th.get("medium", 25)) - 1,
            }
    return out


def catalog_rows(catalog: Dict[str, Any]) -> List[Dict[str, str]]:
    phases = catalog.get("phases") or {}
    rows = []
    for entry in catalog.get("flags", []):
        phase = entry.get("phase") or ""
        notes_parts = []
        if entry.get("notes"):
            notes_parts.append(str(entry["notes"]))
        if entry.get("stored_flag_pattern"):
            notes_parts.append(f"Stored as: {entry['stored_flag_pattern']}")
        tiers = entry.get("score_tiers_resolved") or _resolve_score_tiers(entry, {})
        score_lines = _format_tiers_summary(tiers)
        rows.append(
            {
                "catalog_key": entry.get("catalog_key") or "",
                "category": entry.get("category") or "",
                "phase": phase,
                "phase_description": phases.get(phase, ""),
                "summary": entry.get("description") or "",
                "trigger": entry.get("trigger") or "",
                "explanation": entry.get("explanation") or "",
                "investigation": entry.get("investigation") or "",
                "score_points": score_lines,
                "default_points": str(entry.get("default_points") if entry.get("default_points") is not None else ""),
                "points_config_key": entry.get("points_config_key") or "",
                "notes": " | ".join(notes_parts),
            }
        )
    return rows


def export_json(catalog: Dict[str, Any], *, pretty: bool = True) -> bytes:
    flags = catalog.get("flags") or []
    if flags and "score_tiers_resolved" not in flags[0]:
        catalog = enrich_catalog(catalog, get_risk_scores_from_config(), get_export_context())
    text = json.dumps(catalog, indent=2 if pretty else None, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def export_csv(catalog: Dict[str, Any]) -> bytes:
    if catalog.get("flags") and "score_tiers_resolved" not in catalog["flags"][0]:
        catalog = enrich_catalog(catalog, get_risk_scores_from_config(), get_export_context())
    rows = catalog_rows(catalog)
    fieldnames = [
        "catalog_key",
        "category",
        "phase",
        "phase_description",
        "summary",
        "trigger",
        "explanation",
        "investigation",
        "score_points",
        "default_points",
        "points_config_key",
        "notes",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def export_markdown(catalog: Dict[str, Any]) -> bytes:
    if catalog.get("flags") and "score_tiers_resolved" not in catalog["flags"][0]:
        catalog = enrich_catalog(catalog, get_risk_scores_from_config(), get_export_context())
    phases = catalog.get("phases") or {}
    thresholds = catalog.get("risk_thresholds") or {}
    methodology = catalog.get("scoring_methodology") or {}
    active = catalog.get("active_config") or {}
    active_scores = active.get("risk_scores") or {}

    lines = [
        "# Fraud detection flags — reference guide",
        "",
        f"_Exported: {catalog.get('exported_at', '')}_",
        "",
        "## Risk levels (account action bands)",
        "",
        f"| Level | Score range | Typical action |",
        f"|-------|-------------|----------------|",
        f"| **High** | {thresholds.get('high', 50)}+ | Immediate investigation |",
        f"| **Medium** | {thresholds.get('medium', 25)}–{int(thresholds.get('high', 50)) - 1} | Review recommended |",
        f"| **Low** | 0–{thresholds.get('low_max', 24)} | Routine monitoring |",
        "",
        "Account **risk_score** sums flag points from all applicable rules, **capped at 100**.",
        "",
        "## How scoring works",
        "",
        methodology.get("summary", ""),
        "",
    ]
    for i, step in enumerate(methodology.get("order_of_operations") or [], start=1):
        lines.append(f"{i}. {step}")
    if methodology.get("order_of_operations"):
        lines.append("")
    lines.append("**Intentionally not scored:**")
    for item in methodology.get("not_scored") or []:
        lines.append(f"- {item}")
    lines.append("")

    if active_scores:
        lines.append("## Active score weights (this environment)")
        lines.append("")
        lines.append("| Config key | Points |")
        lines.append("|------------|--------|")
        for key in sorted(active_scores.keys()):
            if key.endswith("_threshold") or key.endswith("_min_sample"):
                continue
            try:
                val = int(active_scores[key])
            except (TypeError, ValueError):
                continue
            lines.append(f"| `{key}` | {val} |")
        lines.append("")

    by_category: Dict[str, List[Dict[str, str]]] = {}
    for row in catalog_rows(catalog):
        by_category.setdefault(row["category"], []).append(row)

    for category in sorted(by_category.keys()):
        lines.append(f"## {category}")
        lines.append("")
        for row in by_category[category]:
            lines.append(f"### `{row['catalog_key']}`")
            lines.append("")
            lines.append(f"**Phase:** {row['phase']} — {row['phase_description']}")
            lines.append("")
            lines.append(f"**Summary:** {row['summary']}")
            lines.append("")
            if row["trigger"]:
                lines.append(f"**When it triggers:** {row['trigger']}")
                lines.append("")
            if row["explanation"]:
                lines.append(f"**Why it matters:** {row['explanation']}")
                lines.append("")
            lines.append(f"**Scores (active):** {row['score_points']}")
            lines.append("")
            if row["investigation"]:
                lines.append(f"**Investigation tips:** {row['investigation']}")
                lines.append("")
            if row["notes"]:
                lines.append(f"**Notes:** {row['notes']}")
                lines.append("")
            lines.append("---")
            lines.append("")

    lines.append("## Pipeline phases (glossary)")
    lines.append("")
    for key, desc in phases.items():
        lines.append(f"- **{key}:** {desc}")
    lines.append("")

    for note in catalog.get("notes") or []:
        lines.append(f"- {note}")
    lines.append("")

    return ("\n".join(lines) + "\n").encode("utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export fraud flag reference catalog")
    parser.add_argument(
        "--format",
        "-f",
        choices=("json", "csv", "md"),
        default="csv",
        help="Export format (default: csv)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Write to file (default: stdout for json/md, or fraud_flags_reference.csv)",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Path to fraud_flags_catalog.json",
    )
    parser.add_argument(
        "--use-config",
        action="store_true",
        help="Resolve point values from config.json",
    )
    args = parser.parse_args(argv)

    ctx = get_export_context() if args.use_config else {"risk_scores": {}}
    cat = enrich_catalog(load_catalog(args.catalog), ctx.get("risk_scores"), ctx if args.use_config else None)

    if args.format == "json":
        data = export_json(cat)
        default_name = "fraud_flags_reference.json"
    elif args.format == "md":
        data = export_markdown(cat)
        default_name = "fraud_flags_reference.md"
    else:
        data = export_csv(cat)
        default_name = "fraud_flags_reference.csv"

    if args.output:
        args.output.write_bytes(data)
        print(f"Wrote {args.output}", file=sys.stderr)
    elif args.format == "csv" and not sys.stdout.isatty():
        sys.stdout.buffer.write(data)
    elif args.format == "csv":
        out_path = Path(default_name)
        out_path.write_bytes(data)
        print(f"Wrote {out_path.resolve()}", file=sys.stderr)
    else:
        sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
