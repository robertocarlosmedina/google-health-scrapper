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


# --- typed tables -----------------------------------------------------------------------------

from scraper.mappers.typed_mapper import EXTRACTORS, TypedMapper
from scraper.models.typed_tables import TABLES, schema_sql


def test_every_data_type_has_an_extractor():
    from scraper.models.data_types import DATA_TYPE_KINDS
    assert set(DATA_TYPE_KINDS) <= set(EXTRACTORS)


def test_extractor_tables_exist_and_keys_are_columns():
    for t in TABLES.values():
        assert set(t.key) <= set(t.column_names), t.name
    assert "CREATE TABLE IF NOT EXISTS \"steps\"" in schema_sql()


def test_distance_is_converted_to_metres():
    raw = {
        "dataSource": {"platform": "HEALTH_KIT", "device": {"displayName": "Phone"}},
        "distance": {"interval": {"startTime": "2026-10-30T20:51:43Z", "endTime": "2026-10-30T20:51:49Z"}, "millimeters": "8789"},
    }
    row = TypedMapper.rows_for("distance", raw)["distance"][0]
    assert row["distance_m"] == 8.789 and row["data_source"] == "Phone"
    assert set(row) == set(TABLES["distance"].column_names)


def test_sleep_splits_into_session_and_stages():
    raw = {
        "name": "users/1/dataTypes/sleep/dataPoints/42",
        "sleep": {
            "interval": {"startTime": "2026-10-27T23:16:00Z", "startUtcOffset": "3600s", "endTime": "2026-10-28T08:43:00Z"},
            "type": "STAGES",
            "summary": {"minutesAsleep": "552"},
            "stages": [{"startTime": "2026-10-27T23:16:00Z", "endTime": "2026-10-27T23:27:00Z", "type": "AWAKE"}],
        },
    }
    rows = TypedMapper.rows_for("sleep", raw)
    assert rows["sleeps"][0]["sleep_id"] == "42" and rows["sleeps"][0]["minutes_asleep"] == 552
    assert rows["sleeps"][0]["start_utc_offset"] == "+01:00"
    assert rows["sleep_stages"][0]["sleep_stage_type"] == "AWAKE"


def test_rollup_bucket_becomes_calories_row():
    raw = {"startTime": "2026-10-28T05:00:00Z", "endTime": "2026-10-28T05:01:00Z", "totalCalories": {"kcalSum": 1.27}}
    p = DataPointMapper.from_api("total-calories", raw)
    assert p.startTime is not None and p.endTime is not None
    assert TypedMapper.rows_for("total-calories", raw)["calories"][0]["calories"] == 1.27


def test_row_without_key_is_dropped():
    assert TypedMapper.rows_for("heart-rate", {"heartRate": {"beatsPerMinute": "60"}}) == {}
