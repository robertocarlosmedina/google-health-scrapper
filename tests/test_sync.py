from datetime import datetime, timezone

from scraper.mappers.data_point_mapper import DataPointMapper
from scraper.services.sync_service import build_filter, resolve_data_types

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 2, tzinfo=timezone.utc)


def test_filters_per_kind():
    assert build_filter("steps", T0, T1) == (
        'steps.interval.start_time >= "2026-10-01T00:00:00Z" AND steps.interval.start_time < "2026-10-02T00:00:00Z"'
    )
    assert "heart_rate.sample_time.physical_time" in build_filter("heart-rate", T0, T1)
    assert 'daily_resting_heart_rate.date >= "2026-10-01"' in build_filter("daily-resting-heart-rate", T0, T1)
    assert "sleep.interval.end_time" in build_filter("sleep", T0, T1)


def test_resolve_types():
    assert "steps" in resolve_data_types("default")
    assert resolve_data_types("steps, sleep") == ["steps", "sleep"]


def test_mapper_extracts_times_and_id():
    raw = {
        "name": "users/me/dataTypes/steps/dataPoints/1",
        "steps": {"interval": {"startTime": "2026-10-01T10:00:00Z", "endTime": "2026-10-01T10:01:00Z"}, "count": "5"},
    }
    p = DataPointMapper.from_api("steps", raw)
    assert p.pointId.endswith("/1")
    assert p.startTime.hour == 10 and p.endTime.minute == 1
    assert str(p.recordDate) == "2026-10-01"


def test_mapper_hash_id_when_no_name():
    a = DataPointMapper.from_api("weight", {"weight": {"sampleTime": {"physicalTime": "2026-10-01T08:00:00Z"}}})
    assert a.pointId.startswith("key:") and a.startTime is not None


def test_id_stable_when_value_is_revised():
    def pt(count):
        return {
            "dataSource": {"platform": "FITBIT", "device": {"displayName": "Google Fitbit Air"}},
            "steps": {"interval": {"startTime": "2026-10-16T16:23:00Z", "endTime": "2026-10-16T16:24:00Z"}, "count": count},
        }
    assert DataPointMapper.from_api("steps", pt("5")).pointId == DataPointMapper.from_api("steps", pt("9")).pointId
