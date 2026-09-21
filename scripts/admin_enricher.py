"""
Admin API Enrichment Pass

Runs *after* the primary email/IP fraud analysis.  For each unenriched DUID in
fraud_results it calls the admin API and adds extra risk points based on:

  • Shared payment cards across N accounts   (+35 / +50 pts)
  • Email validated within 60 / 120 s       (+50 / +30 pts)
  • Amex card                               (+30 pts)
  • Business card                           (+40 pts)
  • Discover concentration per affiliate    (+20 pts, post-enrichment pass)
  • IP geo mismatch (state/country)         (+15 / +35 pts)
  • Login IP in high-risk country           (+30 pts)
  • Login IP ≠ CSV geo_country              (+25 pts)
  • Registration or login IP is datacenter  (+25 pts each)
  • Registration or login IP is VPN/proxy   (+20 pts each)
  • Profile image: disabled (0 pts)
  • CONTENT_REVIEW when profile pic + fast upload (<180s) or suspicious email flags

Results are written back to the fraud_results row via database.save_admin_enrichment().
Progress and errors are surfaced through a callback so callers (background task,
tests) can track them without tight coupling to the Flask app.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

import requests
from admin_api_client import AdminAPIClient
from config import Config
from database import Database
from flag_utils import (
    content_review_flag_label,
    has_content_review_flag,
    needs_content_review,
    parse_flags_cell,
)

logger = logging.getLogger(__name__)

# Back-off delays (seconds) when the API returns 429 Too Many Requests
_RATE_LIMIT_BACKOFF = [5, 15, 30]

# ──────────────────────────────────────────────────────────────────────────────
# GeoIP helpers
# ──────────────────────────────────────────────────────────────────────────────

# ASN org name fragments that indicate a datacenter / cloud / hosting provider.
# Checked case-insensitively against autonomous_system_organization.
_DATACENTER_KEYWORDS = (
    "amazon", "aws", "google", "microsoft", "azure", "digitalocean",
    "linode", "akamai", "vultr", "hetzner", "ovh", "cloudflare",
    "fastly", "rackspace", "leaseweb", "choopa", "quadranet",
    "psychz", "m247", "datacamp", "tzulo", "hostwinds", "liquidweb",
    "limewave", "serverius", "frantech", "buyvm", "heficed",
    "cogent", "zayo", "telia", "hurricane electric", "he.net",
    "hosting", "datacenter", "data center", "colocation", "colo",
    "dedicated server", "cloud hosting",
)

# ASN org name fragments that indicate a VPN, proxy, or anonymizer.
_VPN_KEYWORDS = (
    "mullvad", "nordvpn", "expressvpn", "private internet access",
    " pia ", "protonvpn", "surfshark", "ipvanish", "cyberghost",
    "purevpn", "hidemyass", "tunnelbear", "hotspotshield",
    "vpn", "proxy", "anonymizer", "anonymi", "tor exit", "tor-exit",
)


def _open_geoip_reader(path: str):
    """Open a maxminddb reader, returning None if the file doesn't exist."""
    try:
        import maxminddb
        if not os.path.exists(path):
            return None
        return maxminddb.open_database(path)
    except Exception as exc:
        logger.warning(f"Could not open GeoIP database {path}: {exc}")
        return None


def _resolve_geoip_path(config, rel_or_abs: str) -> str:
    """Resolve DB path relative to the directory that contains config.json (stable cwd)."""
    if os.path.isabs(rel_or_abs):
        return rel_or_abs
    cfg_dir = os.path.dirname(os.path.abspath(getattr(config, "config_path", "config.json")))
    return os.path.normpath(os.path.join(cfg_dir or ".", rel_or_abs))


def _lookup_city(ip: str, reader) -> dict:
    """
    Look up city-level geo for an IP using a maxminddb City reader.
    Returns dict with 'country' (ISO-2) and 'state' (ISO subdivision code).
    Returns empty dict on any error or missing data.
    """
    if not reader or not ip:
        return {}
    try:
        record = reader.get(ip)
        if not record:
            return {}
        country = (record.get("country") or {}).get("iso_code", "") or ""
        subs = record.get("subdivisions") or []
        state = subs[0].get("iso_code", "") if subs else ""
        return {"country": country.upper(), "state": state.upper()}
    except Exception:
        return {}


def _lookup_asn(ip: str, reader) -> dict:
    """
    Look up ASN org for an IP using a maxminddb ASN reader.
    Returns dict with 'asn_org', 'is_datacenter', 'is_vpn'.
    """
    if not reader or not ip:
        return {}
    try:
        record = reader.get(ip)
        if not record:
            return {}
        org = (
            record.get("autonomous_system_organization")
            or record.get("as_name")
            or ""
        ).strip()
        org_lower = org.lower()
        is_dc = any(kw in org_lower for kw in _DATACENTER_KEYWORDS)
        is_vpn = (not is_dc) and any(kw in org_lower for kw in _VPN_KEYWORDS)
        return {"asn_org": org, "is_datacenter": is_dc, "is_vpn": is_vpn}
    except Exception:
        return {}

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_EXCLUDED_ISSUERS = {
    "bank of america", "jp morgan chase", "jpmorgan chase",
    "capital one", "citi", "citibank",
}


def _issuer_excluded(card: dict) -> bool:
    """Return True if the card belongs to a major issuer we deliberately skip."""
    name = (card.get("card_issuer") or card.get("issuer") or "").lower()
    return any(exc in name for exc in _EXCLUDED_ISSUERS)


def _image_upload_seconds(image_data: dict, reg_ts: Optional[str]) -> Optional[int]:
    """
    Calculate seconds between account registration and profile image upload.
    Returns None if either timestamp is missing or un-parseable.
    """
    if not image_data or not reg_ts:
        return None
    upload_ts = image_data.get("uploaded_at") or image_data.get("created_at")
    if not upload_ts:
        return None
    try:
        formats = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]
        reg_dt = upload_dt = None
        for fmt in formats:
            try:
                if reg_dt is None:
                    reg_dt = datetime.strptime(reg_ts[:19], fmt)
            except ValueError:
                pass
            try:
                if upload_dt is None:
                    upload_dt = datetime.strptime(str(upload_ts)[:19], fmt)
            except ValueError:
                pass
        if reg_dt and upload_dt:
            return max(0, int((upload_dt - reg_dt).total_seconds()))
    except Exception:
        pass
    return None


def _email_validation_seconds(user: dict) -> Optional[int]:
    """
    Return seconds between account creation and email validation.
    Expects the API's 'user' sub-object.
    """
    reg_ts = user.get("registration_timestamp") or user.get("created_at")
    val_ts = user.get("email_validated_at") or user.get("email_validation_timestamp")
    if not reg_ts or not val_ts:
        return None
    try:
        formats = ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]
        reg_dt = val_dt = None
        for fmt in formats:
            try:
                if reg_dt is None:
                    reg_dt = datetime.strptime(str(reg_ts)[:19], fmt)
            except ValueError:
                pass
            try:
                if val_dt is None:
                    val_dt = datetime.strptime(str(val_ts)[:19], fmt)
            except ValueError:
                pass
        if reg_dt and val_dt:
            return max(0, int((val_dt - reg_dt).total_seconds()))
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Main enricher
# ──────────────────────────────────────────────────────────────────────────────

class AdminEnricher:
    """
    Iterates over unenriched DUIDs, pulls admin API data, scores additional
    risk factors, and writes the enriched data back to the database.

    Parameters
    ----------
    db       : Database instance (or path string)
    client   : AdminAPIClient instance (or None — will try to build from config)
    config   : Config instance (or None — will load default config)
    throttle : seconds to sleep between API calls (default 0.25)
    """

    def __init__(
        self,
        db: Optional[Database] = None,
        client: Optional[AdminAPIClient] = None,
        config: Optional[Config] = None,
        throttle: float = 0.25,
    ):
        self.config = config or Config()
        self.db = db or Database(self.config.get("database_path", "affiliate_data.db"))
        self.throttle = throttle

        if client is not None:
            self.client = client
        else:
            creds = self.config.get_admin_api_credentials()
            username = creds.get("username") or ""
            password = creds.get("password") or ""
            self.client = AdminAPIClient(username, password) if username else None

        self._scores = self.config.get("risk_scores", {})
        self._profile_image_fast_seconds = int(
            self.config.get("profile_image_fast_seconds", 180) or 180
        )

        # GeoIP readers — None if database files haven't been downloaded yet.
        # Download with: python3 scripts/download_geoip.py
        city_db = _resolve_geoip_path(self.config, self.config.get("geoip_city_db", "data/GeoLite2-City.mmdb"))
        asn_db = _resolve_geoip_path(self.config, self.config.get("geoip_asn_db", "data/GeoLite2-ASN.mmdb"))
        self._city_reader = _open_geoip_reader(city_db)
        self._asn_reader = _open_geoip_reader(asn_db)
        if self._city_reader:
            logger.info(f"GeoIP City database loaded: {city_db}")
        else:
            logger.info(f"GeoIP City database not found — geo mismatch rules disabled ({city_db})")
        if self._asn_reader:
            logger.info(f"GeoIP ASN database loaded: {asn_db}")
        else:
            logger.info(f"GeoIP ASN database not found — datacenter/VPN rules disabled ({asn_db})")

    # ── public ────────────────────────────────────────────────────────────────

    def run(
        self,
        limit: int = 500,
        progress_cb: Optional[Callable[[dict], None]] = None,
        since_analyzed_at: Optional[str] = None,
    ) -> dict:
        """
        Enrich up to `limit` unenriched DUIDs.

        progress_cb receives a dict:
          { total, done, skipped, enriched, errors, unavailable, current_duid }

        404 from the admin API closes the row (not in API). 401/403/5xx increment
        per-row attempts; after `enrich_max_transient_attempts` the row is closed
        as unavailable. 429 is retried with back-off, then left unenriched.

        Args:
            since_analyzed_at: If set, only enrich accounts analyzed at/after this
                               timestamp (e.g. to target just the last pipeline run).

        Returns summary dict.
        """
        if not self.client:
            return {"error": "Admin API not configured — set credentials in Settings."}

        sched = self.config.get("scheduler", {}) or {}
        lookback = int(sched.get("enrich_lookback_days", 90) or 90)
        lookback = max(1, min(lookback, 3650))
        max_t = int(sched.get("enrich_max_transient_attempts", 5) or 5)
        max_t = max(1, min(max_t, 50))
        health = sched.get("enrich_health_check", True) is not False

        if health:
            try:
                ok, msg = self.client.test_connection()
            except Exception as exc:  # pragma: no cover
                ok, msg = False, str(exc)
            if not ok:
                logger.warning("Enrichment pre-flight failed: %s", msg)
                return {
                    "error": msg or "Admin API pre-flight failed (VPN? credentials?)",
                    "total": 0,
                    "enriched": 0,
                    "unavailable": 0,
                    "skipped": 0,
                    "errors": 0,
                }

        duids = self.db.get_unenriched_duids(
            limit=limit,
            since_analyzed_at=since_analyzed_at,
            lookback_days=lookback,
        )
        total = len(duids)
        enriched = skipped = errors = unavailable = 0

        date_from = (datetime.now() - timedelta(days=lookback)).strftime("%Y-%m-%d")
        date_to = datetime.now().strftime("%Y-%m-%d")

        # Pre-fetch existing geo_country for all target DUIDs in one query
        # so we can cross-reference login IP country against the CSV geo source.
        existing_geo: dict = {}
        if duids:
            placeholders = ",".join("?" * len(duids))
            with self.db.get_connection() as conn:
                rows = conn.execute(
                    f"SELECT duid, geo_country FROM fraud_results WHERE duid IN ({placeholders})",
                    duids
                ).fetchall()
            existing_geo = {str(r[0]): (r[1] or "").upper() for r in rows}

        for i, duid in enumerate(duids):
            if progress_cb:
                progress_cb({
                    "total": total,
                    "done": i,
                    "enriched": enriched,
                    "skipped": skipped,
                    "errors": errors,
                    "unavailable": unavailable,
                    "current_duid": duid,
                })

            kind, payload = self._fetch_fraud_info(duid, date_from, date_to)
            if kind == "ok":
                csv_geo_country = existing_geo.get(str(duid), "")
                existing_flags = self._get_existing_flags(duid)
                result = self._score(
                    duid,
                    payload,
                    csv_geo_country=csv_geo_country,
                    existing_flags=existing_flags,
                )
                self.db.save_admin_enrichment(duid, result)
                enriched += 1
            elif kind == "not_found":
                self.db.mark_admin_enrichment_unavailable(duid, "api_404", 404)
                unavailable += 1
            elif kind == "forbidden":
                code = int(payload)
                n = self.db.increment_enrich_failure(duid, code)
                if n >= max_t:
                    self.db.mark_admin_enrichment_unavailable(duid, "api_401_403", code)
                    unavailable += 1
                else:
                    errors += 1
            elif kind == "rate_limited":
                errors += 1
            elif kind == "http":
                code = int(payload)
                n = self.db.increment_enrich_failure(duid, code)
                if n >= max_t:
                    self.db.mark_admin_enrichment_unavailable(duid, f"api_http_{code}", code)
                    unavailable += 1
                else:
                    errors += 1
            elif kind == "network":
                n = self.db.increment_enrich_failure(duid, 0)
                if n >= max_t:
                    self.db.mark_admin_enrichment_unavailable(duid, "network", 0)
                    unavailable += 1
                else:
                    errors += 1
                    if payload:
                        logger.warning("Enrichment network error for DUID %s: %s", duid, payload)
            else:  # pragma: no cover
                logger.warning("Enrichment: unknown result kind for DUID %s: %s", duid, kind)
                errors += 1

            if self.throttle > 0 and i < total - 1:
                time.sleep(self.throttle)

        summary = {
            "total": total,
            "enriched": enriched,
            "unavailable": unavailable,
            "skipped": skipped,
            "errors": errors,
        }
        logger.info(f"Enrichment complete: {summary}")

        # ── Discover concentration pass ───────────────────────────────────────
        # Runs after the main loop so it has full picture of card_types data.
        discover_flagged = self._apply_discover_concentration()
        summary["discover_concentration_flagged"] = discover_flagged

        content_review_flagged = self._apply_content_review_flags()
        summary["content_review_flagged"] = content_review_flagged

        return summary

    # ── private ───────────────────────────────────────────────────────────────

    def _apply_discover_concentration(self) -> int:
        """
        Post-enrichment pass: flag accounts from affiliates where Discover cards
        exceed the configured threshold (default 10% of that affiliate's accounts).

        Only affiliates with at least discover_concentration_min_sample (default 10)
        enriched accounts are evaluated to avoid small-sample noise.

        Returns the number of accounts newly flagged.
        """
        threshold = float(self.config.get("risk_scores", {}).get(
            "discover_concentration_threshold",
            self._scores.get("discover_concentration_threshold", 0.10)
        ))
        pts = self._scores.get("discover_concentration", 20)
        min_sample = int(self._scores.get("discover_concentration_min_sample", 10))

        if pts <= 0:
            return 0

        affiliate_stats = self.db.get_discover_affiliate_stats()
        flagged = 0

        for stat in affiliate_stats:
            total = stat["total"]
            discover_count = stat["discover_count"]
            if total < min_sample or discover_count == 0:
                continue
            pct = discover_count / total
            if pct > threshold:
                pct_display = round(pct * 100, 1)
                flag = f"discover_concentration_{pct_display}pct_at_{stat['webmaster_code']}(+{pts})"
                for duid in stat["discover_duids"]:
                    self.db.apply_concentration_flag(duid, flag, pts)
                    flagged += 1
                logger.info(
                    f"Discover concentration: {stat['webmaster_code']} "
                    f"{pct_display}% ({discover_count}/{total}) — flagged {len(stat['discover_duids'])} accounts"
                )

        return flagged

    def _get_existing_flags(self, duid: str) -> list:
        try:
            with self.db.get_connection() as conn:
                row = conn.execute(
                    "SELECT flags FROM fraud_results WHERE duid = ?",
                    (str(duid),),
                ).fetchone()
            return parse_flags_cell(row[0] if row else None)
        except Exception:
            return []

    def _apply_content_review_flags(self) -> int:
        """
        Post-enrichment pass: flag enriched accounts with profile pics that warrant
        manual content review (fast upload or suspicious email/identity flags).
        """
        pts = int(self._scores.get("content_review", 0) or 0)
        fast_seconds = self._profile_image_fast_seconds
        flagged = 0

        with self.db.get_connection() as conn:
            rows = conn.execute(
                """SELECT duid, flags, profile_image_uploaded, profile_image_upload_seconds
                   FROM fraud_results
                   WHERE admin_enriched = 1
                     AND profile_image_uploaded = 1"""
            ).fetchall()

        flag_label = content_review_flag_label(pts)
        for duid, flags_raw, uploaded, upload_seconds in rows:
            if has_content_review_flag(flags_raw):
                continue
            if not needs_content_review(
                uploaded,
                upload_seconds,
                flags_raw,
                fast_seconds=fast_seconds,
            ):
                continue
            self.db.apply_concentration_flag(str(duid), flag_label, pts)
            flagged += 1

        if flagged:
            logger.info(
                "Content review: flagged %s accounts (fast upload <%ss or suspicious email flags)",
                flagged,
                fast_seconds,
            )
        return flagged

    def _fetch_fraud_info(
        self, duid: str, date_from: str, date_to: str
    ):
        """
        Call the admin API with automatic 429 back-off.

        Returns a (kind, payload) tuple:
          ("ok", dict)           — success
          ("not_found", None)    — HTTP 404, no user in window
          ("forbidden", code)    — HTTP 401 / 403 (VPN, IP, auth)
          ("rate_limited", None) — 429 with retries exhausted
          ("http", int)         — other HTTP error status
          ("network", str)      — connection / timeout / other RequestException
        """
        for wait in [0] + _RATE_LIMIT_BACKOFF:
            if wait:
                logger.info("Rate-limited — waiting %ss for DUID %s", wait, duid)
                time.sleep(wait)
            try:
                return ("ok", self.client.get_user_fraud_info(duid, date_from, date_to))
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else 0
                if code == 429:
                    continue
                if code == 404:
                    return ("not_found", None)
                if code in (401, 403):
                    return ("forbidden", code)
                return ("http", code)
            except requests.RequestException as exc:
                return ("network", str(exc))
        logger.warning("Gave up on DUID %s after 429 back-off retries (rate limited)", duid)
        return ("rate_limited", None)

    def _score(
        self,
        duid: str,
        data: dict,
        csv_geo_country: str = "",
        existing_flags: Optional[list] = None,
    ) -> dict:
        """
        Translate raw admin API response into a risk delta + structured fields.

        csv_geo_country: ISO-2 country code from the original CSV/leads data,
                         used to cross-reference against login IP country.
        """
        risk_added = 0
        flags: list = []

        user = data.get("user") or {}

        # ── Registration & login timestamps / IPs ─────────────────────────────
        registration_timestamp = (
            user.get("registration_timestamp")
            or user.get("created_at")
        )
        registration_ip = (
            user.get("registration_ip")
            or user.get("signup_ip")
        )
        # Admin API nests IPs under first_login / last_login objects (see dashboard account_detail).
        first_login = user.get("first_login") if isinstance(user.get("first_login"), dict) else {}
        last_login = user.get("last_login") if isinstance(user.get("last_login"), dict) else {}
        login_ip = (
            user.get("last_login_ip")
            or user.get("login_ip")
            or (last_login.get("ip") or "").strip()
            or (first_login.get("ip") or "").strip()
        ) or None

        # ── GeoIP lookups ─────────────────────────────────────────────────────
        reg_geo  = _lookup_city(registration_ip, self._city_reader)
        login_geo = _lookup_city(login_ip,       self._city_reader)
        reg_asn  = _lookup_asn(registration_ip,  self._asn_reader)
        login_asn = _lookup_asn(login_ip,        self._asn_reader)

        reg_country   = reg_geo.get("country", "")
        login_country = login_geo.get("country", "")
        reg_state     = reg_geo.get("state", "")
        login_state   = login_geo.get("state", "")

        # Country mismatch between registration and login IPs
        if reg_country and login_country and reg_country != login_country:
            pts = self._scores.get("ip_different_country", 35)
            if pts > 0:
                risk_added += pts
                flags.append(f"ip_country_mismatch_{reg_country}→{login_country}(+{pts})")
        elif reg_country and login_country and reg_country == login_country:
            # Same country — check for cross-state move (US most meaningful)
            if reg_state and login_state and reg_state != login_state:
                pts = self._scores.get("ip_different_state", 15)
                if pts > 0:
                    risk_added += pts
                    flags.append(f"ip_state_mismatch_{reg_state}→{login_state}(+{pts})")

        # Login IP in high-risk country
        high_risk = [c.upper() for c in self.config.get("high_risk_countries", [])]
        if login_country and login_country in high_risk:
            pts = self._scores.get("login_high_risk_country", 30)
            if pts > 0:
                risk_added += pts
                flags.append(f"login_high_risk_country_{login_country}(+{pts})")

        # Login IP country vs. CSV geo_country (cross-source mismatch)
        if login_country and csv_geo_country and login_country != csv_geo_country:
            pts = self._scores.get("geo_login_country_mismatch", 25)
            if pts > 0:
                risk_added += pts
                flags.append(f"geo_login_mismatch_{csv_geo_country}→{login_country}(+{pts})")

        # Datacenter / VPN detection — registration IP
        if reg_asn:
            if reg_asn.get("is_datacenter"):
                pts = self._scores.get("registration_ip_datacenter", 25)
                if pts > 0:
                    risk_added += pts
                    flags.append(f"registration_ip_datacenter_{reg_asn['asn_org']}(+{pts})")
            elif reg_asn.get("is_vpn"):
                pts = self._scores.get("registration_ip_vpn", 20)
                if pts > 0:
                    risk_added += pts
                    flags.append(f"registration_ip_vpn_{reg_asn['asn_org']}(+{pts})")

        # Datacenter / VPN detection — login IP
        if login_asn:
            if login_asn.get("is_datacenter"):
                pts = self._scores.get("login_ip_datacenter", 25)
                if pts > 0:
                    risk_added += pts
                    flags.append(f"login_ip_datacenter_{login_asn['asn_org']}(+{pts})")
            elif login_asn.get("is_vpn"):
                pts = self._scores.get("login_ip_vpn", 20)
                if pts > 0:
                    risk_added += pts
                    flags.append(f"login_ip_vpn_{login_asn['asn_org']}(+{pts})")

        # ── Email validation timing ───────────────────────────────────────────
        val_secs = _email_validation_seconds(user)
        if val_secs is not None:
            if val_secs <= 60:
                pts = self._scores.get("email_validated_60s", 50)
                if pts > 0:
                    risk_added += pts
                    flags.append(f"email_validated_{val_secs}s(+{pts})")
            elif val_secs <= 120:
                pts = self._scores.get("email_validated_120s", 30)
                if pts > 0:
                    risk_added += pts
                    flags.append(f"email_validated_{val_secs}s(+{pts})")

        # ── Shared payment cards ──────────────────────────────────────────────
        shared_payment_methods = data.get("shared_payment_methods") or []
        whitelisted_fps = set(self.config.get_whitelisted_card_fingerprints())
        whitelisted_duids = set(self.config.get_whitelisted_duids())
        # Count distinct other DUIDs across non-excluded cards (skip test cards / QA DUIDs)
        other_duids: set = set()
        for pm in shared_payment_methods:
            if _issuer_excluded(pm):
                continue
            fp = (pm.get("card_fingerprint") or "").strip()
            if fp and fp in whitelisted_fps:
                continue
            for d in pm.get("other_duids") or []:
                ds = str(d).strip()
                if ds and ds != str(duid) and ds not in whitelisted_duids:
                    other_duids.add(ds)

        shared_card_count = len(other_duids)
        if shared_card_count >= 5:
            pts = self._scores.get("shared_card_5plus", 50)
            if pts > 0:
                risk_added += pts
                flags.append(f"shared_card_{shared_card_count}_accounts(+{pts})")
        elif shared_card_count >= 3:
            pts = self._scores.get("shared_card_3plus", 35)
            if pts > 0:
                risk_added += pts
                flags.append(f"shared_card_{shared_card_count}_accounts(+{pts})")

        # ── Card type + business card ─────────────────────────────────────────
        # Combine all payment method objects (user's own + shared)
        all_cards = list(data.get("payment_methods") or []) + list(shared_payment_methods)
        card_types_seen: set = set()
        is_business_card = False

        _BUSINESS_KEYWORDS = ("business", "corporate", "commercial", "company", "enterprise")

        for card in all_cards:
            raw_type = (card.get("cardType") or "").strip().lower()
            card_desc = (card.get("cardDescription") or "").strip().lower()

            # Normalise to canonical type name
            if "amex" in raw_type or "american express" in raw_type:
                card_types_seen.add("amex")
            elif "discover" in raw_type:
                card_types_seen.add("discover")
            elif "visa" in raw_type:
                card_types_seen.add("visa")
            elif "master" in raw_type:
                card_types_seen.add("mastercard")
            elif raw_type:
                card_types_seen.add(raw_type)

            # Business card detection via description field
            if any(kw in card_desc for kw in _BUSINESS_KEYWORDS):
                is_business_card = True

        # Score: Amex (near-0% baseline on dating sites)
        if "amex" in card_types_seen:
            pts = self._scores.get("amex_card", 30)
            if pts > 0:
                risk_added += pts
                flags.append(f"amex_card(+{pts})")

        # Score: business card (inherently suspicious on a dating site)
        if is_business_card:
            pts = self._scores.get("business_card", 40)
            if pts > 0:
                risk_added += pts
                flags.append(f"business_card(+{pts})")

        # Note: Discover concentration is handled as a post-enrichment pass
        # in _apply_discover_concentration() called at the end of run().

        # ── Profile image ─────────────────────────────────────────────────────
        image_data = data.get("profile_image_upload") or {}
        profile_image_uploaded: Optional[bool] = None
        profile_image_upload_seconds: Optional[int] = None

        if image_data:
            profile_image_uploaded = bool(
                image_data.get("uploaded") or image_data.get("exists")
            )
            if profile_image_uploaded and registration_timestamp:
                profile_image_upload_seconds = _image_upload_seconds(
                    image_data, registration_timestamp
                )

        prior_flags = existing_flags if existing_flags is not None else []
        if needs_content_review(
            profile_image_uploaded,
            profile_image_upload_seconds,
            prior_flags,
            fast_seconds=self._profile_image_fast_seconds,
        ):
            pts = int(self._scores.get("content_review", 0) or 0)
            flags.append(content_review_flag_label(pts))
            if pts > 0:
                risk_added += pts

        return {
            "risk_added": risk_added,
            "flags": flags,
            "registration_timestamp": registration_timestamp,
            "registration_ip": registration_ip,
            "login_ip": login_ip,
            "shared_card_count": shared_card_count,
            "profile_image_uploaded": profile_image_uploaded,
            "profile_image_upload_seconds": profile_image_upload_seconds,
            "card_types": sorted(card_types_seen),
            "is_business_card": is_business_card,
            "registration_ip_country": reg_country or None,
            "registration_ip_state":   reg_state or None,
            "login_ip_country":        login_country or None,
            "login_ip_state":          login_state or None,
            "registration_ip_asn":     reg_asn.get("asn_org") if reg_asn else None,
            "login_ip_asn":            login_asn.get("asn_org") if login_asn else None,
            "registration_ip_is_datacenter": reg_asn.get("is_datacenter") if reg_asn else None,
            "login_ip_is_datacenter":        login_asn.get("is_datacenter") if login_asn else None,
        }
