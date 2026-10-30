"""Typed tables that mirror the Google Takeout CSV exports (snake_case column names).

One spec drives both the DDL (`ensure_schema`) and the upserts, so they cannot drift apart.
The raw JSON stays in `health_data_points`; these tables are derived from it.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class TypedTable:
    name: str
    columns: tuple[tuple[str, str], ...]  # (column, postgres type)
    key: tuple[str, ...]

    @property
    def column_names(self) -> list[str]:
        return [c for c, _ in self.columns]


def _ts(name: str, *value_cols: tuple[str, str], extra_key: tuple[str, ...] = (), end: bool = False) -> TypedTable:
    """Time-series table: CSV `timestamp` + values + `data_source`, keyed on (timestamp, data_source)."""
    cols: list[tuple[str, str]] = [("timestamp", "TIMESTAMPTZ")]
    if end:
        cols.append(("end_time", "TIMESTAMPTZ"))
    cols += list(value_cols) + [("data_source", "TEXT")]
    # Interval rows are only unique with their end too (phones report overlapping fragments).
    key = ("timestamp", *(("end_time",) if end else ()), *extra_key, "data_source")
    return TypedTable(name, tuple(cols), key)


def _daily(name: str, *value_cols: tuple[str, str], extra_key: tuple[str, ...] = ()) -> TypedTable:
    cols = [("date", "DATE")] + list(value_cols) + [("data_source", "TEXT")]
    return TypedTable(name, tuple(cols), ("date", *extra_key, "data_source"))


F, I, T, J, B = "DOUBLE PRECISION", "BIGINT", "TEXT", "JSONB", "BOOLEAN"
_SLEEP_STATS = [
    (f"{stage}_sleep_{stat}", F)
    for stage in ("deep", "light", "rem", "full")
    for stat in ("breaths_per_minute", "std_dev", "signal_to_noise")
]

TABLES: dict[str, TypedTable] = {t.name: t for t in [
    # --- interval series ---
    _ts("steps", ("steps", I), end=True),
    _ts("distance", ("distance_m", F), end=True),
    _ts("floors", ("floors", I), end=True),
    _ts("active_energy_burned", ("kilocalories", F), end=True),
    _ts("calories", ("calories", F), end=True),
    _ts("active_zone_minutes", ("heart_rate_zone", T), ("total_minutes", I), extra_key=("heart_rate_zone",), end=True),
    _ts("active_minutes", ("activity_level", T), ("active_minutes", I), extra_key=("activity_level",), end=True),
    _ts("activity_level", ("activity_level_type", T), end=True),
    _ts("altitude", ("gain_millimeters", I), end=True),
    _ts("sedentary_period", end=True),
    _ts("time_in_heart_rate_zone", ("heart_rate_zone_type", T), end=True),
    _ts("swim_lengths_data", ("lap_time_seconds", F), ("stroke_count", I), ("stroke_type", T), end=True),
    # --- sample series ---
    _ts("heart_rate", ("beats_per_minute", I)),
    _ts("heart_rate_variability", ("rmssd_milliseconds", F), ("high_frequency_power", F), ("low_frequency_power", F)),
    _ts("oxygen_saturation", ("oxygen_saturation_percentage", F)),
    _ts("body_fat", ("body_fat_percentage", F)),
    _ts("weight", ("weight_grams", F)),
    _ts("height", ("height_millimeters", I)),
    _ts("core_body_temperature", ("temperature_celsius", F), ("measurement_location", T)),
    _ts("blood_glucose", ("milligrams_per_deciliter", F), ("measurement_source", T), ("meal_type", T),
        ("measurement_timing", T), ("specimen", T), ("notes", T)),
    _ts("vo2_max", ("vo2_max", F), ("measurement_method", T)),
    _ts("run_vo2_max", ("run_vo2_max", F)),
    _ts("respiratory_rate_sleep_summary", *_SLEEP_STATS),
    # --- daily ---
    _daily("daily_resting_heart_rate", ("beats_per_minute", I), ("calculation_method", T)),
    _daily("daily_respiratory_rate", ("breaths_per_minute", F)),
    _daily("daily_heart_rate_variability", ("average_heart_rate_variability_milliseconds", F),
           ("non_rem_heart_rate_beats_per_minute", I), ("entropy", F),
           ("deep_sleep_rmssd_milliseconds", F)),
    _daily("daily_oxygen_saturation", ("average_percentage", F), ("lower_bound_percentage", F),
           ("upper_bound_percentage", F), ("baseline_percentage", F), ("standard_deviation_percentage", F)),
    _daily("daily_sleep_temperature_derivations", ("nightly_temperature_celsius", F),
           ("baseline_temperature_celsius", F), ("relative_nightly_stddev_30d_celsius", F)),
    _daily("daily_heart_rate_zones", ("heart_rate_zone_type", T), ("min_heart_rate_bpm", I),
           ("max_heart_rate_bpm", I), extra_key=("heart_rate_zone_type",)),
    _daily("daily_vo2_max", ("vo2_max", F), ("vo2_max_covariance", F), ("cardio_fitness_level", T), ("estimated", B)),
    # --- sessions / entities ---
    TypedTable("sleeps", (
        ("sleep_id", T), ("sleep_type", T), ("minutes_in_sleep_period", I), ("minutes_after_wake_up", I),
        ("minutes_to_fall_asleep", I), ("minutes_asleep", I), ("minutes_awake", I),
        ("start_utc_offset", T), ("sleep_start", "TIMESTAMPTZ"), ("end_utc_offset", T), ("sleep_end", "TIMESTAMPTZ"),
        ("main_sleep", B), ("stages_status", T), ("stages_summary", J), ("short_awakenings", J),
        ("data_source", T), ("sleep_created", "TIMESTAMPTZ"), ("sleep_last_updated", "TIMESTAMPTZ"),
    ), ("sleep_id",)),
    TypedTable("sleep_stages", (
        ("sleep_id", T), ("sleep_stage_type", T), ("start_utc_offset", T), ("sleep_stage_start", "TIMESTAMPTZ"),
        ("end_utc_offset", T), ("sleep_stage_end", "TIMESTAMPTZ"), ("data_source", T),
        ("sleep_stage_created", "TIMESTAMPTZ"), ("sleep_stage_last_updated", "TIMESTAMPTZ"),
    ), ("sleep_id", "sleep_stage_start")),
    TypedTable("exercises", (
        ("exercise_id", T), ("exercise_start", "TIMESTAMPTZ"), ("exercise_end", "TIMESTAMPTZ"), ("utc_offset", T),
        ("exercise_created", "TIMESTAMPTZ"), ("exercise_last_updated", "TIMESTAMPTZ"),
        ("exercise_type", T), ("activity_name", T), ("active_duration_seconds", F),
        ("calories_kcal", F), ("steps", I), ("distance_millimeters", F), ("average_pace_seconds_per_meter", F),
        ("average_heart_rate_beats_per_minute", I), ("active_zone_minutes", I),
        ("light_time_seconds", F), ("moderate_time_seconds", F), ("vigorous_time_seconds", F), ("peak_time_seconds", F),
        ("metrics_summary", J), ("exercise_metadata", J), ("data_source", T),
    ), ("exercise_id",)),
    TypedTable("electrocardiograms", (
        ("ecg_id", T), ("ecg_start", "TIMESTAMPTZ"), ("ecg_end", "TIMESTAMPTZ"), ("result_classification", T),
        ("beats_per_minute_avg", I), ("sampling_frequency_hertz", I), ("millivolts_scaling_factor", I),
        ("lead_number", I), ("waveform_samples", J), ("medical_device_info", J), ("data_source", T),
    ), ("ecg_id",)),
    TypedTable("irregular_rhythm_notifications", (
        ("irn_id", T), ("irn_start", "TIMESTAMPTZ"), ("irn_end", "TIMESTAMPTZ"), ("alert_windows", J),
        ("medical_device_info", J), ("data_source", T),
    ), ("irn_id",)),
    TypedTable("hydration_logs", (
        ("hydration_log_id", T), ("log_start", "TIMESTAMPTZ"), ("log_end", "TIMESTAMPTZ"),
        ("amount_consumed", J), ("data_source", T),
    ), ("hydration_log_id",)),
    TypedTable("nutrition_logs", (
        ("nutrition_log_id", T), ("log_start", "TIMESTAMPTZ"), ("log_end", "TIMESTAMPTZ"), ("meal_type", T),
        ("food", T), ("food_display_name", T), ("energy", J), ("energy_from_fat", J), ("total_carbohydrate", J),
        ("total_fat", J), ("nutrients", J), ("serving", J), ("data_source", T),
    ), ("nutrition_log_id",)),
    # --- account level, fetched as whole resources ---
    TypedTable("user_resources", (("resource", T), ("payload", J)), ("resource",)),
]}


def create_table_sql(table: TypedTable) -> str:
    cols = ",\n    ".join(f'"{c}" {t}' for c, t in table.columns)
    key = ", ".join(f'"{k}"' for k in table.key)
    return (
        f'CREATE TABLE IF NOT EXISTS "{table.name}" (\n    {cols},\n'
        f"    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),\n    PRIMARY KEY ({key})\n);"
    )


def schema_sql() -> str:
    return "\n\n".join(create_table_sql(t) for t in TABLES.values())
