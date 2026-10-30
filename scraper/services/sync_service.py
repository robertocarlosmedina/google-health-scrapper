import logging
from datetime import datetime, timedelta, timezone

from scraper.clients.google_health_client import GoogleHealthApiError, GoogleHealthClient
from scraper.mappers.data_point_mapper import DataPointMapper
from scraper.mappers.typed_mapper import TypedMapper
from scraper.models.data_types import (
    DAILY, DATA_TYPE_KINDS, DEFAULT_DATA_TYPES, INTERVAL, RECONCILE_TYPES, ROLLUP, SAMPLE, SESSION, SLEEP)
from scraper.repositories.data_point_repository import DataPointRepository
from scraper.repositories.typed_repository import TypedRepository
from scraper.repositories.sync_state_repository import SyncStateRepository

logger = logging.getLogger(__name__)

BATCH_SIZE = 2000
MAX_PAGE_SIZE = 10000  # API maximum; sleep and exercise are capped at 25 (their default)
ROLLUP_WINDOW = "60s"  # one bucket per minute, like the Takeout `calories` series
USER_RESOURCES = ("identity", "profile", "settings")  # whole-account resources, stored as-is


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
        typed_repository: TypedRepository | None = None,
    ):
        self.client = client
        self.points_repo = data_point_repository
        self.state_repo = sync_state_repository
        self.typed_repo = typed_repository
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
        self.sync_user_resources()
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

    def _fetch(self, data_type: str, start: datetime, end: datetime):
        if DATA_TYPE_KINDS[data_type] == ROLLUP:
            return self.client.roll_up(data_type, _rfc3339(start), _rfc3339(end), ROLLUP_WINDOW)
        return self.client.list_data_points(
            data_type, build_filter(data_type, start, end), page_size=self._page_size(data_type),
            reconcile=data_type in RECONCILE_TYPES,
        )

    def _store(self, data_type: str, points: list) -> int:
        """Upsert raw points, then the typed rows derived from them."""
        written = self.points_repo.upsert_many(points)
        self._store_typed(data_type, points)
        return written

    def _store_typed(self, data_type: str, points: list) -> None:
        if not self.typed_repo:
            return
        tables: dict[str, list[dict]] = {}
        for point in points:
            for table, rows in TypedMapper.rows_for(data_type, point.payload).items():
                tables.setdefault(table, []).extend(rows)
        for table, rows in tables.items():
            self.typed_repo.upsert_rows(table, rows)

    def _sync_window(self, data_type: str, start: datetime, end: datetime) -> int:
        batch, written = [], 0
        for raw in self._fetch(data_type, start, end):
            batch.append(DataPointMapper.from_api(data_type, raw))
            if len(batch) >= BATCH_SIZE:
                written += self._store(data_type, batch)
                batch = []
        written += self._store(data_type, batch)
        logger.debug("%s [%s, %s): %d points", data_type, _rfc3339(start), _rfc3339(end), written)
        return written

    def sync_user_resources(self) -> None:
        """Identity / profile / settings: small, unversioned, so just overwrite the latest copy."""
        if not self.typed_repo:
            return
        for resource in USER_RESOURCES:
            try:
                payload = self.client.get_resource(resource)
            except GoogleHealthApiError as e:
                logger.warning("Skipping user resource %s: %s", resource, e)
                continue
            self.typed_repo.upsert_rows("user_resources", [{"resource": resource, "payload": payload}])

    def rebuild_typed(self) -> dict[str, int]:
        """Re-derive the typed tables from stored raw JSON (no API calls); use after changing a mapper."""
        counts: dict[str, int] = {}
        for data_type in self.data_types:
            batch, n = [], 0
            for point in self.points_repo.iter_points(data_type):
                batch.append(point)
                if len(batch) >= BATCH_SIZE:
                    n += self._rebuild_batch(data_type, batch)
                    batch = []
            n += self._rebuild_batch(data_type, batch)
            counts[data_type] = n
            logger.info("Rebuilt typed rows for %s from %d raw points", data_type, n)
        return counts

    def _rebuild_batch(self, data_type: str, points: list) -> int:
        self._store_typed(data_type, points)
        return len(points)
