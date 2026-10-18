from datetime import datetime
from typing import List, Optional

from scraper.models.health_models import SyncState
from scraper.repositories.sync_state_repository import SyncStateRepository


def _to_state(row: dict) -> SyncState:
    return SyncState(
        dataType=row["data_type"],
        lastSyncedAt=row["last_synced_at"],
        lastStatus=row["last_status"],
        lastError=row["last_error"],
        updatedAt=row["updated_at"],
    )


class PostgresSyncStateRepositoryAdapter(SyncStateRepository):
    def __init__(self, conn):
        self.conn = conn

    def get(self, data_type: str) -> Optional[SyncState]:
        row = self.conn.execute("SELECT * FROM sync_state WHERE data_type = %s", (data_type,)).fetchone()
        return _to_state(row) if row else None

    def list_all(self) -> List[SyncState]:
        rows = self.conn.execute("SELECT * FROM sync_state ORDER BY data_type").fetchall()
        return [_to_state(r) for r in rows]

    def mark_success(self, data_type: str, synced_until: datetime) -> None:
        self.conn.execute(
            """
            INSERT INTO sync_state (data_type, last_synced_at, last_status, last_error, updated_at)
            VALUES (%s, %s, 'ok', NULL, now())
            ON CONFLICT (data_type) DO UPDATE SET
                last_synced_at = EXCLUDED.last_synced_at,
                last_status = 'ok', last_error = NULL, updated_at = now()
            """,
            (data_type, synced_until),
        )

    def mark_failure(self, data_type: str, error: str) -> None:
        self.conn.execute(
            """
            INSERT INTO sync_state (data_type, last_status, last_error, updated_at)
            VALUES (%s, 'error', %s, now())
            ON CONFLICT (data_type) DO UPDATE SET
                last_status = 'error', last_error = EXCLUDED.last_error, updated_at = now()
            """,
            (data_type, error[:2000]),
        )
