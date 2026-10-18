from datetime import datetime
from typing import List

from scraper.mappers.data_point_mapper import DataPointMapper
from scraper.models.health_models import DataPoint
from scraper.repositories.data_point_repository import DataPointRepository

UPSERT_SQL = """
INSERT INTO health_data_points (data_type, point_id, start_time, end_time, record_date, payload)
VALUES (%(data_type)s, %(point_id)s, %(start_time)s, %(end_time)s, %(record_date)s, %(payload)s::jsonb)
ON CONFLICT (data_type, point_id) DO UPDATE SET
    start_time  = EXCLUDED.start_time,
    end_time    = EXCLUDED.end_time,
    record_date = EXCLUDED.record_date,
    payload     = EXCLUDED.payload,
    updated_at  = now()
"""


class PostgresDataPointRepositoryAdapter(DataPointRepository):
    def __init__(self, conn):
        self.conn = conn

    def upsert_many(self, data_points: List[DataPoint]) -> int:
        if not data_points:
            return 0
        # De-duplicate within the batch: ON CONFLICT can't hit the same key twice per statement.
        rows = {(p.dataType, p.pointId): DataPointMapper.to_row(p) for p in data_points}
        with self.conn.transaction():
            with self.conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, list(rows.values()))
        return len(rows)

    def count(self, data_type: str) -> int:
        row = self.conn.execute(
            "SELECT count(*) AS n FROM health_data_points WHERE data_type = %s", (data_type,)
        ).fetchone()
        return row["n"]

    def latest_start_time(self, data_type: str) -> datetime | None:
        row = self.conn.execute(
            "SELECT max(start_time) AS t FROM health_data_points WHERE data_type = %s", (data_type,)
        ).fetchone()
        return row["t"]
