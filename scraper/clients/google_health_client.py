import logging
from typing import Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scraper.clients.google_auth import load_access_token
from scraper.globals import GOOGLE_HEALTH_BASE_URL

logger = logging.getLogger(__name__)


class GoogleHealthApiError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Google Health API returned {status}: {body[:500]}")
        self.status = status


class GoogleHealthClient:
    """Thin client for https://health.googleapis.com/v4 (users.dataTypes.dataPoints.list)."""

    def __init__(self, base_url: str = GOOGLE_HEALTH_BASE_URL, timeout: int = 60):
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()
        retry = Retry(
            total=4,
            backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),  # rollUp is a read-only POST
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _get(self, url: str, params: dict, force_refresh: bool = False) -> requests.Response:
        return self.session.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {load_access_token(force_refresh)}"},
            timeout=self.timeout,
        )

    def _post(self, url: str, body: dict, force_refresh: bool = False) -> requests.Response:
        return self.session.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {load_access_token(force_refresh)}"},
            timeout=self.timeout,
        )

    def get_resource(self, path: str) -> dict:
        """GET a single non-paginated resource, e.g. `identity`, `profile`, `settings`."""
        url = f"{self.base_url}/v4/users/me/{path}"
        resp = self._get(url, {})
        if resp.status_code == 401:
            resp = self._get(url, {}, force_refresh=True)
        if resp.status_code != 200:
            raise GoogleHealthApiError(resp.status_code, resp.text)
        return resp.json()

    def roll_up(self, data_type: str, start: str, end: str, window: str = "60s", page_size: int = 10000) -> Iterator[dict]:
        """Yield rollup buckets for [start, end) (RFC 3339), for types that don't support `list`."""
        url = f"{self.base_url}/v4/users/me/dataTypes/{data_type}/dataPoints:rollUp"
        body: dict = {"range": {"startTime": start, "endTime": end}, "windowSize": window, "pageSize": page_size}
        while True:
            resp = self._post(url, body)
            if resp.status_code == 401:
                logger.warning("Got 401, refreshing the access token and retrying")
                resp = self._post(url, body, force_refresh=True)
            if resp.status_code != 200:
                raise GoogleHealthApiError(resp.status_code, resp.text)
            payload = resp.json()
            yield from payload.get("rollupDataPoints", [])
            token = payload.get("nextPageToken")
            if not token:
                return
            body["pageToken"] = token

    def list_data_points(
        self, data_type: str, filter_expr: str | None = None, page_size: int | None = None, reconcile: bool = False
    ) -> Iterator[dict]:
        """Yield every data point matching the filter, following nextPageToken.

        `reconcile=True` uses `dataPoints:reconcile` for types that don't support `list` (e.g. floors).
        """
        suffix = ":reconcile" if reconcile else ""
        url = f"{self.base_url}/v4/users/me/dataTypes/{data_type}/dataPoints{suffix}"
        params: dict = {}
        if filter_expr:
            params["filter"] = filter_expr
        if page_size:
            params["pageSize"] = page_size

        while True:
            resp = self._get(url, params)
            if resp.status_code == 401:
                # Token expired mid-run (e.g. laptop slept): force a refresh and retry once.
                logger.warning("Got 401, refreshing the access token and retrying")
                resp = self._get(url, params, force_refresh=True)
            if resp.status_code != 200:
                raise GoogleHealthApiError(resp.status_code, resp.text)

            body = resp.json()
            points = body.get("dataPoints", [])
            logger.debug("%s: page with %d points", data_type, len(points))
            yield from points

            token = body.get("nextPageToken")
            if not token:
                return
            params["pageToken"] = token
