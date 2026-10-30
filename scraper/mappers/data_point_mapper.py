import hashlib
import json
from datetime import date, datetime
from typing import Any, Optional

from scraper.models.health_models import DataPoint


def _parse_dt(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date(value: Any) -> Optional[date]:
    """Accept 'YYYY-MM-DD' or a {year, month, day} object."""
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    if isinstance(value, dict) and {"year", "month", "day"} <= value.keys():
        try:
            return date(int(value["year"]), int(value["month"]), int(value["day"]))
        except (ValueError, TypeError):
            return None
    return None


class DataPointMapper:
    """Maps raw Google Health API data points to/from storage rows.

    The per-type payload shape differs a lot, so the full JSON is kept as-is and
    only the time fields (interval / sampleTime / date) are lifted to columns.
    """

    @staticmethod
    def from_api(data_type: str, raw: dict) -> DataPoint:
        start = end = record_date = None

        # Rollup buckets (e.g. total-calories) carry their window at the top level.
        start, end = _parse_dt(raw.get("startTime")), _parse_dt(raw.get("endTime"))

        for value in raw.values():
            if not isinstance(value, dict):
                continue
            interval = value.get("interval")
            if isinstance(interval, dict):
                start = _parse_dt(interval.get("startTime"))
                end = _parse_dt(interval.get("endTime"))
            sample_time = value.get("sampleTime")
            if isinstance(sample_time, dict):
                start = start or _parse_dt(sample_time.get("physicalTime"))
            if "date" in value:
                record_date = _parse_date(value["date"])

        if record_date is None and start is not None:
            record_date = start.date()

        return DataPoint(
            dataType=data_type,
            pointId=DataPointMapper._point_id(raw, start, end, record_date),
            payload=raw,
            startTime=start,
            endTime=end,
            recordDate=record_date,
        )

    @staticmethod
    def _point_id(raw: dict, start: Optional[datetime], end: Optional[datetime], record_date: Optional[date]) -> str:
        """Stable identity: API `name` if present, else source + time key.

        Real responses carry no `name`, and hashing the payload would turn every revised
        value (e.g. a corrected step count) into a duplicate row, so the key is built
        from the data source and the point's time position only.
        """
        name = raw.get("name")
        if isinstance(name, str) and name:
            return name

        source = raw.get("dataSource") or {}
        device = (source.get("device") or {}).get("displayName", "")
        parts = [
            source.get("platform", ""), device, source.get("recordingMethod", ""),
            start.isoformat() if start else "", end.isoformat() if end else "",
            record_date.isoformat() if record_date else "",
        ]
        if not (start or record_date):  # nothing positional to key on: fall back to content
            parts.append(json.dumps(raw, sort_keys=True, separators=(",", ":")))
        return "key:" + hashlib.sha256("|".join(parts).encode()).hexdigest()

    @staticmethod
    def to_row(point: DataPoint) -> dict:
        return {
            "data_type": point.dataType,
            "point_id": point.pointId,
            "start_time": point.startTime,
            "end_time": point.endTime,
            "record_date": point.recordDate,
            "payload": json.dumps(point.payload),
        }
