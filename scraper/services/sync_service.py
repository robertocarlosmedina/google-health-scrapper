import logging
from datetime import datetime, timedelta, timezone

from scraper.clients.google_health_client import GoogleHealthClient
from scraper.mappers.data_point_mapper import DataPointMapper
from scraper.models.data_types import (
    DAILY, DATA_TYPE_KINDS, DEFAULT_DATA_TYPES, INTERVAL, SAMPLE, SESSION, SLEEP)
from scraper.repositories.data_point_repository import DataPointRepository
from scraper.repositories.sync_state_repository import SyncStateRepository

logger = logging.getLogger(__name__)

BATCH_SIZE = 2000
MAX_PAGE_SIZE = 10000  # API maximum; sleep and exercise are capped at 25 (their default)


def resolve_data_types(configured: str) -> list[str]:
    """Turn the SYNC_DATA_TYPES setting into a validated list."""
    configured = configured.strip()
    if configured.lower() in ("", "default"):
        return list(DEFAULT_DATA_TYPES)
    if configured.lower() == "all":
        return sorted(DATA_TYPE_KINDS)
    names = [n.strip() for n in configured.split(",") if n.strip()]
    unknown = [n for n in names if n not in DATA_TYPE_KINDS]
    if unknown:
        raise ValueError(f"Unknown data types in SYNC_DATA_TYPES: {', '.join(unknown)}")
    return names


def _snake(kebab: str) -> str:
    """Filter fields use snake_case type names (verified against the live API)."""
    return kebab.replace("-", "_")


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_filter(data_type: str, start: datetime, end: datetime) -> str:
    """AIP-160 filter for [start, end) using the field each record kind supports.

    Field names follow https://developers.google.com/health/reference/rest/v4/users.dataTypes.dataPoints/list
    """
    kind = DATA_TYPE_KINDS[data_type]
    p = _snake(data_type)

    if kind == INTERVAL:
        field, fmt = f"{p}.interval.start_time", _rfc3339
    elif kind == SAMPLE:
        field, fmt = f"{p}.sample_time.physical_time", _rfc3339
    elif kind == DAILY:
        field, fmt = f"{p}.date", lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%d")
    elif kind == SESSION:
        field, fmt = f"{p}.interval.civil_start_time", lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    elif kind == SLEEP:
        field, fmt = "sleep.interval.end_time", _rfc3339
    else:  # pragma: no cover
        raise ValueError(kind)

    return f'{field} >= "{fmt(start)}" AND {field} < "{fmt(end)}"'


class SyncService:
    def __init__(
        self,
        client: GoogleHealthClient,
        data_point_repository: DataPointRepository,
        sync_state_repository: SyncStateRepository,
        data_types: list[str],
        initial_lookback_days: int,
        overlap_hours: int,
        window_days: int,
    ):
        self.client = client
        self.points_repo = data_point_repository
        self.state_repo = sync_state_repository
        self.data_types = data_types
        self.initial_lookback = timedelta(days=initial_lookback_days)
        self.overlap = timedelta(hours=overlap_hours)
        self.window = timedelta(days=max(window_days, 1))

    def run_once(self) -> dict[str, int]:
        """Sync every configured data type. One failing type never stops the others."""
        results: dict[str, int] = {}
        failures = 0
        for data_type in self.data_types:
            try:
                results[data_type] = self.sync_data_type(data_type)
            except Exception as e:
                failures += 1
                logger.error("Sync failed for %s: %s", data_type, e, exc_info=logger.isEnabledFor(logging.DEBUG))
                self.state_repo.mark_failure(data_type, str(e))
        logger.info(
            "Sync finished: %d points across %d types, %d failed",
            sum(results.values()), len(results), failures,
        )
        return results

    def sync_data_type(self, data_type: str) -> int:
        now = datetime.now(timezone.utc)
        state = self.state_repo.get(data_type)
        if state and state.lastSyncedAt:
            start = state.lastSyncedAt - self.overlap
        else:
            start = now - self.initial_lookback

        logger.info("Syncing %s from %s", data_type, _rfc3339(start))
        total = 0
        cursor = start
        while cursor < now:
            window_end = min(cursor + self.window, now)
            total += self._sync_window(data_type, cursor, window_end)
            # Checkpoint after each window so a long backfill resumes where it stopped.
            self.state_repo.mark_success(data_type, window_end)
            cursor = window_end

        logger.info("Synced %s: %d points", data_type, total)
        return total

    @staticmethod
    def _page_size(data_type: str) -> int | None:
        return None if DATA_TYPE_KINDS[data_type] in (SESSION, SLEEP) else MAX_PAGE_SIZE

    def _sync_window(self, data_type: str, start: datetime, end: datetime) -> int:
        filter_expr = build_filter(data_type, start, end)
        batch, written = [], 0
        for raw in self.client.list_data_points(data_type, filter_expr, page_size=self._page_size(data_type)):
            batch.append(DataPointMapper.from_api(data_type, raw))
            if len(batch) >= BATCH_SIZE:
                written += self.points_repo.upsert_many(batch)
                batch = []
        written += self.points_repo.upsert_many(batch)
        logger.debug("%s [%s, %s): %d points", data_type, _rfc3339(start), _rfc3339(end), written)
        return written
