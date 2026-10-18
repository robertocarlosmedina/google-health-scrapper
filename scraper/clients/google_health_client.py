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
            allowed_methods=("GET",),
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

    def list_data_points(
        self, data_type: str, filter_expr: str | None = None, page_size: int | None = None
    ) -> Iterator[dict]:
        """Yield every data point matching the filter, following nextPageToken."""
        url = f"{self.base_url}/v4/users/me/dataTypes/{data_type}/dataPoints"
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
