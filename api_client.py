"""API client for fetching affiliate data with retry logic and filters"""
import requests
import time
import logging
from datetime import datetime, timedelta
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)


class APIClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = 'https://api7.hugetraffic.com/main.php'
        self.max_retries = 3
        self.timeout = 30

    def fetch_data(self, data_type, start_date, end_date, filters=None):
        """
        Fetch data from API with retry logic

        Args:
            data_type: 'paid' or 'free'
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            filters: Optional dict with filter parameters
        """
        params = {
            'api_key': self.api_key,
            'a': 'member.sales_data_export',
            'v': 'json',
            'start_date': start_date,
            'end_date': end_date,
        }

        # Set data type
        if data_type == 'paid':
            params['search_paid'] = 1
        elif data_type == 'free':
            params['search_free'] = 1

        # Apply optional filters
        if filters:
            # POV Verified filter
            if filters.get('pov_verified') is not None:
                params['pov_verified'] = 1 if filters['pov_verified'] else 0

            # User Agent filter
            if filters.get('custom_http_user_agent'):
                params['custom_http_user_agent'] = filters['custom_http_user_agent']

            # Chargeback count filter (for paid)
            if filters.get('chargeback_count') is not None:
                params['chargeback_count'] = filters['chargeback_count']

            # Credit count filter (for paid)
            if filters.get('credit_count') is not None:
                params['credit_count'] = filters['credit_count']

            # Site code filter (for free)
            if filters.get('site_code'):
                params['site_code'] = filters['site_code']

            # Webmaster code filter
            if filters.get('webmaster_code'):
                params['webmaster_code'] = filters['webmaster_code']

            # Email domain filter
            if filters.get('email_domain'):
                params['email_domain'] = filters['email_domain']

            # Campaign filter
            if filters.get('campaign'):
                params['campaign'] = filters['campaign']

        label = 'paid' if params.get('search_paid') else 'free' if params.get('search_free') else 'export'
        return self._make_request_with_retry(params, label=label)

    def _make_request_with_retry(self, params, label='export'):
        """Make API request with exponential backoff retry"""
        for attempt in range(self.max_retries):
            try:
                logger.info(f"API request attempt {attempt + 1}/{self.max_retries}")

                response = requests.get(
                    self.base_url,
                    params=params,
                    timeout=self.timeout
                )

                # Check for HTTP errors — log the body first so we can see what the API said
                if not response.ok:
                    body_preview = response.text[:500] if response.text else '(empty body)'
                    logger.error(
                        f"API HTTP {response.status_code} for {label} "
                        f"[attempt {attempt + 1}]. Response body: {body_preview}"
                    )
                    response.raise_for_status()

                # Parse JSON
                data = response.json()

                # Check if API returned data
                if not data:
                    logger.warning("API returned empty data")
                    return []

                # Check for API error messages
                if isinstance(data, dict) and 'error' in data:
                    raise Exception(f"API Error: {data['error']}")

                # Handle different response formats
                # API might return a dict with 'data' key or direct list
                if isinstance(data, dict):
                    # Log the top-level keys for debugging
                    logger.info(f"API response keys: {list(data.keys())}")

                    # Check for common wrapper keys
                    if 'member_sales_data_export' in data:
                        data = data['member_sales_data_export']
                        logger.info(f"Extracted member_sales_data_export, type: {type(data)}")

                        # member_sales_data_export is a dict with structure:
                        # {'server_real_name': ..., 'status': ..., 'result': {'colmap': ..., 'data': [...]}, 'execution_time': ...}
                        if isinstance(data, dict):
                            # Check for 'result' key which contains the actual data
                            if 'result' in data:
                                data = data['result']
                                logger.info(f"Extracted result, type: {type(data)}")

                                # result contains {'colmap': ..., 'data': [...]}
                                if isinstance(data, dict) and 'data' in data:
                                    data = data['data']
                                    logger.info(f"Extracted data array, length: {len(data) if isinstance(data, list) else 'not a list'}")
                                else:
                                    logger.error(f"Result dict missing 'data' key. Keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
                                    return []
                            else:
                                logger.error(f"member_sales_data_export missing 'result' key. Keys: {list(data.keys())}")
                                return []
                    elif 'data' in data:
                        data = data['data']
                    elif 'results' in data:
                        data = data['results']
                    elif 'records' in data:
                        data = data['records']
                    else:
                        # If dict but no known wrapper, might be single record
                        data = [data]

                # Ensure data is a list
                if not isinstance(data, list):
                    logger.error(f"Unexpected data type: {type(data)}, value: {str(data)[:200]}")
                    return []

                # Validate records are dictionaries
                valid_records = []
                for i, record in enumerate(data):
                    if isinstance(record, dict):
                        valid_records.append(record)
                    else:
                        logger.warning(f"Skipping invalid record at index {i}: {type(record)}")

                logger.info(f"Successfully fetched {len(valid_records)} valid records")
                return valid_records

            except RequestException as e:
                logger.error(f"Request failed (attempt {attempt + 1}): {e}")

                if attempt < self.max_retries - 1:
                    # Exponential backoff: 2, 4, 8 seconds
                    wait_time = 2 ** attempt
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    logger.error("Max retries exceeded")
                    raise

            except ValueError as e:
                logger.error(f"Failed to parse JSON response: {e}")
                raise

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise

        return []

    def probe_connectivity(self, timeout=8):
        """
        Lightweight auth/connectivity probe (a=me).
        Returns True when VPN/API access is ready; False on 403/timeout/etc.
        """
        if not self.api_key:
            return False
        try:
            response = requests.get(
                self.base_url,
                params={'api_key': self.api_key, 'a': 'me'},
                timeout=timeout,
            )
            return 200 <= response.status_code < 400
        except RequestException:
            return False

    def test_connection(self):
        """Test API connection"""
        ok = self.probe_connectivity(timeout=10)
        if ok:
            logger.info("API connection test successful")
            return True, "Connection successful"
        logger.error("API connection test failed (probe a=me did not succeed)")
        return False, "Connection failed: API probe (a=me) did not return success"
