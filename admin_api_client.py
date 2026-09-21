"""Client for the admin platform API (admin2.fling.com).

Provides per-DUID enrichment: shared payment methods, profile image upload
status, billing events, registration/login IPs and timestamps.

Authentication: HTTP Basic Auth (username + password stored in config.json).
"""

import logging
from datetime import datetime, timedelta

import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

BASE_URL = "https://admin2.fling.com/admin/api"


class AdminAPIClient:
    def __init__(self, username: str, password: str, timeout: int = 30):
        self.auth = HTTPBasicAuth(username, password)
        self.timeout = timeout

    def get_user_fraud_info(self, duid, date_from=None, date_to=None):
        """
        GET /user_fraud_info?duid=...&date_from=...&date_to=...

        Returns dict with: shared_payment_methods, billing_events,
        profile_image_upload, user (registration + login data).
        """
        if date_to is None:
            date_to = datetime.now().strftime("%Y-%m-%d")
        if date_from is None:
            date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        params = {
            "duid": str(duid),
            "date_from": date_from,
            "date_to": date_to,
        }

        url = f"{BASE_URL}/user_fraud_info"
        try:
            resp = requests.get(
                url, params=params, auth=self.auth, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Admin API: fetched fraud info for DUID {duid}")
            return data
        except RequestException as exc:
            logger.error(f"Admin API request failed for DUID {duid}: {exc}")
            raise

    def get_shared_card_duids(self, duid, date_from=None, date_to=None):
        """Convenience: return flat set of other DUIDs sharing any card with this DUID."""
        info = self.get_user_fraud_info(duid, date_from, date_to)
        other = set()
        for pm in info.get("shared_payment_methods") or []:
            for d in pm.get("other_duids") or []:
                other.add(str(d))
        other.discard(str(duid))
        return other

    def test_connection(self):
        """Quick connectivity check using a known-valid DUID."""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            resp = requests.get(
                f"{BASE_URL}/user_fraud_info",
                params={"duid": "363077965", "date_from": today, "date_to": today},
                auth=self.auth,
                timeout=10,
            )
            if resp.status_code == 401:
                return False, "Authentication failed — check username/password"
            if resp.status_code == 403:
                return False, "Access denied (403)"
            resp.raise_for_status()
            return True, "Connection successful"
        except RequestException as exc:
            return False, f"Connection failed: {exc}"
