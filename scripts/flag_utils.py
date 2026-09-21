"""Shared flag parsing and catalog normalization for fraud detection."""
from __future__ import annotations

import ast
import json
import re
from typing import List


# Email / identity flags that suggest templated fraud — pair with profile pics for manual review.
CONTENT_REVIEW_SIGNAL_FLAGS = frozenset({
    'NAME_NUMBER_PATTERN',
    'SCRAMBLED_PATTERN',
    'SEQUENTIAL_EMAIL',
    'SUSPICIOUS_NAME',
    'BILLING_GENDER_MISMATCH',
    'WOMAN_CONCENTRATION',
    'GENDER_NAME_MISMATCH',
    'EXCESSIVE_DOTS',
    'DIGIT_SUFFIX',
    'WRITTEN_NUMBER_PATTERN',
    'REPEATED_WORD_PATTERN',
})


def _flag_base_name(flag: str) -> str:
    """Strip (+N) suffix and normalize for comparison."""
    raw = str(flag).strip().strip("[]' ")
    if not raw:
        return ''
    return re.sub(r"\(\+\d+\)\s*$", "", raw).strip().upper()


def has_content_review_signal(flags_str) -> bool:
    """True if flags include a pattern associated with fake/stolen profile review."""
    for raw in parse_flags_cell(flags_str):
        base = _flag_base_name(raw)
        if base in CONTENT_REVIEW_SIGNAL_FLAGS:
            return True
        if base.startswith('THEME_CLUSTER_'):
            return True
    return False


def has_content_review_flag(flags_str) -> bool:
    for raw in parse_flags_cell(flags_str):
        if _flag_base_name(raw) == 'CONTENT_REVIEW':
            return True
    return False


def needs_content_review(
    profile_image_uploaded,
    profile_image_upload_seconds,
    flags_str,
    *,
    fast_seconds: int = 180,
) -> bool:
    """
    True when an account has a profile pic and looks worth manual content review:
    fast upload after registration (< fast_seconds) OR suspicious email/identity flags.
    """
    if profile_image_uploaded is None or profile_image_uploaded == '':
        uploaded = False
    elif isinstance(profile_image_uploaded, bool):
        uploaded = profile_image_uploaded
    else:
        try:
            uploaded = bool(int(profile_image_uploaded))
        except (TypeError, ValueError):
            uploaded = bool(profile_image_uploaded)

    if not uploaded:
        return False

    if profile_image_upload_seconds is not None:
        try:
            if int(profile_image_upload_seconds) < int(fast_seconds):
                return True
        except (TypeError, ValueError):
            pass

    return has_content_review_signal(flags_str)


def content_review_flag_label(risk_pts: int = 0) -> str:
    pts = int(risk_pts or 0)
    return 'CONTENT_REVIEW' if pts <= 0 else f'CONTENT_REVIEW(+{pts})'


def parse_flags_cell(flags_str) -> List[str]:
    """Return list of raw flag strings from a fraud_results.flags cell."""
    if flags_str is None:
        return []
    if isinstance(flags_str, list):
        return [str(x).strip() for x in flags_str if x is not None and str(x).strip()]
    if not isinstance(flags_str, str):
        return []
    s = flags_str.strip()
    if not s or s == '[]':
        return []
    try:
        s_json = s.replace("'", '"')
        if s.startswith('['):
            parsed = json.loads(s_json)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if x is not None and str(x).strip()]
    except Exception:
        pass
    try:
        v = ast.literal_eval(s)
        if isinstance(v, list):
            return [str(x).strip() for x in v if x is not None and str(x).strip()]
    except Exception:
        pass
    if '|' in s:
        return [f.strip() for f in s.split('|') if f.strip()]
    return [s] if s else []


def normalize_flag_catalog_key(flag: str) -> str:
    """
    Map parameterized detection strings to a stable catalog key so views
    group geo/ASN variants instead of listing hundreds of unique strings.
    """
    raw = str(flag).strip().strip("[]' ")
    if not raw:
        return ""
    base = re.sub(r"\(\+\d+\)\s*$", "", raw).strip()
    lower = base.lower()
    prefixes = (
        ("geo_login_mismatch_", "geo_login_mismatch"),
        ("ip_country_mismatch_", "ip_country_mismatch"),
        ("ip_state_mismatch_", "ip_state_mismatch"),
        ("login_high_risk_country_", "login_high_risk_country"),
        ("registration_ip_datacenter_", "registration_ip_datacenter"),
        ("registration_ip_vpn_", "registration_ip_vpn"),
        ("login_ip_datacenter_", "login_ip_datacenter"),
        ("login_ip_vpn_", "login_ip_vpn"),
        ("discover_concentration_", "discover_concentration"),
    )
    for pref, key in prefixes:
        if lower.startswith(pref):
            return key
    if re.match(r"^shared_card_\d+_accounts$", lower):
        return "shared_card"
    if lower.startswith("shared_card_"):
        return "shared_card"
    if re.match(r"^email_validated_\d+s$", lower):
        return "email_validated"
    if lower.startswith("theme_cluster_"):
        return "theme_cluster"
    if lower.startswith("ip_velocity_"):
        return "ip_velocity"
    return base


def catalog_flags_from_cell(flags_str) -> List[str]:
    """Unique catalog-normalized flags from one flags cell."""
    seen = set()
    out = []
    for raw in parse_flags_cell(flags_str):
        key = normalize_flag_catalog_key(raw)
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def precision_confidence(reviewed: int) -> str:
    """Label precision reliability from reviewed sample size."""
    if reviewed >= 30:
        return "strong"
    if reviewed >= 10:
        return "directional"
    return "too_little_data"


def rule_status(precision, reviewed: int) -> str:
    """UI status dot: good / caution / neutral."""
    if reviewed < 10:
        return "neutral"
    if precision is None:
        return "neutral"
    if precision >= 80:
        return "good"
    if precision < 60:
        return "caution"
    return "neutral"
