"""Turns a raw Google Health API data point into rows for the typed tables (see models/typed_tables.py).

Every extractor takes the raw API dict and returns {table_name: [row, ...]}. Units follow the
Takeout CSVs where the API differs (e.g. distance in metres), and unknown fields stay in raw JSON.
"""
from datetime import datetime
from typing import Any, Callable, Optional

from scraper.models.typed_tables import TABLES

Rows = dict[str, list[dict]]
Extractor = Callable[[dict], Rows]


# --- primitives -------------------------------------------------------------------------------

def _dt(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _int(value: Any) -> Optional[int]:
    try:
        return None if value is None else int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _seconds(value: Any) -> Optional[float]:
    """Protobuf duration string ('900s', '0.5s') -> seconds."""
    if isinstance(value, str) and value.endswith("s"):
        return _float(value[:-1])
    return None


def _offset(value: Any) -> Optional[str]:
    """'3600s' -> '+01:00', matching the CSVs' utc_offset columns."""
    secs = _seconds(value)
    if secs is None:
        return None
    total = int(secs)
    sign = "-" if total < 0 else "+"
    hours, rem = divmod(abs(total), 3600)
    return f"{sign}{hours:02d}:{rem // 60:02d}"


def _date(value: Any) -> Optional[str]:
    if isinstance(value, dict) and {"year", "month", "day"} <= value.keys():
        return f"{int(value['year']):04d}-{int(value['month']):02d}-{int(value['day']):02d}"
    return value[:10] if isinstance(value, str) else None


def _point_id(raw: dict) -> Optional[str]:
    name = raw.get("name")
    return name.rsplit("/", 1)[-1] if isinstance(name, str) and name else None


def data_source(raw: dict) -> str:
    """Human label for the origin, in the spirit of the CSVs' `data source` column."""
    src = raw.get("dataSource") or {}
    device = src.get("device") or {}
    if device.get("displayName"):
        return device["displayName"]
    if device.get("manufacturer"):
        return " ".join(filter(None, [device["manufacturer"], str(device.get("formFactor", "")).title()]))
    app = (src.get("application") or {}).get("packageName")
    return app or src.get("platform") or "unknown"


def _value(raw: dict, key: str) -> dict:
    v = raw.get(key)
    return v if isinstance(v, dict) else {}


# --- extractor factories ----------------------------------------------------------------------

def interval_series(key: str, table: str, values: Callable[[dict], dict]) -> Extractor:
    """interval { startTime, endTime } -> one row per point."""
    def extract(raw: dict) -> Rows:
        v = _value(raw, key)
        interval = v.get("interval") or {}
        start = _dt(interval.get("startTime"))
        if start is None:
            return {}
        row = {"timestamp": start, "end_time": _dt(interval.get("endTime")), "data_source": data_source(raw)}
        return {table: [{**row, **values(v)}]}
    return extract


def sample_series(key: str, table: str, values: Callable[[dict], dict]) -> Extractor:
    """sampleTime { physicalTime } -> one row per point."""
    def extract(raw: dict) -> Rows:
        v = _value(raw, key)
        ts = _dt((v.get("sampleTime") or {}).get("physicalTime"))
        if ts is None:
            return {}
        return {table: [{"timestamp": ts, "data_source": data_source(raw), **values(v)}]}
    return extract


def daily(key: str, table: str, values: Callable[[dict], dict]) -> Extractor:
    def extract(raw: dict) -> Rows:
        v = _value(raw, key)
        day = _date(v.get("date"))
        if day is None:
            return {}
        return {table: [{"date": day, "data_source": data_source(raw), **values(v)}]}
    return extract


# --- per type value mappers -------------------------------------------------------------------

def _stats(v: dict, stage: str) -> dict:
    s = v.get(f"{stage}SleepStats") or {}
    return {
        f"{stage}_sleep_breaths_per_minute": _float(s.get("breathsPerMinute")),
        f"{stage}_sleep_std_dev": _float(s.get("standardDeviation")),
        f"{stage}_sleep_signal_to_noise": _float(s.get("signalToNoise")),
    }


def _active_minutes(raw: dict) -> Rows:
    v = _value(raw, "activeMinutes")
    interval = v.get("interval") or {}
    start = _dt(interval.get("startTime"))
    if start is None:
        return {}
    rows = [
        {"timestamp": start, "end_time": _dt(interval.get("endTime")), "data_source": data_source(raw),
         "activity_level": e.get("activityLevel") or "UNSPECIFIED", "active_minutes": _int(e.get("activeMinutes"))}
        for e in v.get("activeMinutesByActivityLevel") or []
    ]
    return {"active_minutes": rows}


def _daily_heart_rate_zones(raw: dict) -> Rows:
    v = _value(raw, "dailyHeartRateZones")
    day = _date(v.get("date"))
    if day is None:
        return {}
    rows = [
        {"date": day, "data_source": data_source(raw),
         "heart_rate_zone_type": z.get("heartRateZoneType") or "UNSPECIFIED",
         "min_heart_rate_bpm": _int(z.get("minBeatsPerMinute")), "max_heart_rate_bpm": _int(z.get("maxBeatsPerMinute"))}
        for z in v.get("heartRateZones") or []
    ]
    return {"daily_heart_rate_zones": rows}


def _swim_lap(raw: dict) -> Rows:
    rows = interval_series("swimLengthsData", "swim_lengths_data", lambda v: {
        "stroke_count": _int(v.get("strokeCount")), "stroke_type": v.get("strokeType"),
    })(raw)
    for row in rows.get("swim_lengths_data", []):
        if row["end_time"]:
            row["lap_time_seconds"] = (row["end_time"] - row["timestamp"]).total_seconds()
    return rows


def _total_calories(raw: dict) -> Rows:
    """Rollup bucket (startTime/endTime/totalCalories{kcalSum}); not a regular data point."""
    start = _dt(raw.get("startTime"))
    if start is None:
        return {}
    return {"calories": [{
        "timestamp": start, "end_time": _dt(raw.get("endTime")), "data_source": "all sources",
        "calories": _float(_value(raw, "totalCalories").get("kcalSum")),
    }]}


def _sleep(raw: dict) -> Rows:
    v = _value(raw, "sleep")
    sleep_id = _point_id(raw)
    interval = v.get("interval") or {}
    if not sleep_id or not interval.get("startTime"):
        return {}
    summary, meta, source = v.get("summary") or {}, v.get("metadata") or {}, data_source(raw)
    sleep = {
        "sleep_id": sleep_id, "sleep_type": v.get("type"),
        "minutes_in_sleep_period": _int(summary.get("minutesInSleepPeriod")),
        "minutes_after_wake_up": _int(summary.get("minutesAfterWakeUp")),
        "minutes_to_fall_asleep": _int(summary.get("minutesToFallAsleep")),
        "minutes_asleep": _int(summary.get("minutesAsleep")),
        "minutes_awake": _int(summary.get("minutesAwake")),
        "start_utc_offset": _offset(interval.get("startUtcOffset")), "sleep_start": _dt(interval.get("startTime")),
        "end_utc_offset": _offset(interval.get("endUtcOffset")), "sleep_end": _dt(interval.get("endTime")),
        "main_sleep": meta.get("mainSleep"), "stages_status": meta.get("stagesStatus"),
        "stages_summary": summary.get("stagesSummary"), "short_awakenings": v.get("shortAwakenings"),
        "data_source": source, "sleep_created": _dt(v.get("createTime")), "sleep_last_updated": _dt(v.get("updateTime")),
    }
    stages = [
        {"sleep_id": sleep_id, "sleep_stage_type": s.get("type"),
         "start_utc_offset": _offset(s.get("startUtcOffset")), "sleep_stage_start": _dt(s.get("startTime")),
         "end_utc_offset": _offset(s.get("endUtcOffset")), "sleep_stage_end": _dt(s.get("endTime")),
         "data_source": source, "sleep_stage_created": _dt(s.get("createTime")),
         "sleep_stage_last_updated": _dt(s.get("updateTime"))}
        for s in v.get("stages") or [] if s.get("startTime")
    ]
    return {"sleeps": [sleep], "sleep_stages": stages}


def _exercise(raw: dict) -> Rows:
    v = _value(raw, "exercise")
    exercise_id = _point_id(raw)
    interval = v.get("interval") or {}
    if not exercise_id or not interval.get("startTime"):
        return {}
    m = v.get("metricsSummary") or {}
    zones = m.get("heartRateZoneDurations") or {}
    return {"exercises": [{
        "exercise_id": exercise_id, "exercise_start": _dt(interval.get("startTime")),
        "exercise_end": _dt(interval.get("endTime")), "utc_offset": _offset(interval.get("startUtcOffset")),
        "exercise_created": _dt(v.get("createTime")), "exercise_last_updated": _dt(v.get("updateTime")),
        "exercise_type": v.get("exerciseType"), "activity_name": v.get("displayName"),
        "active_duration_seconds": _seconds(v.get("activeDuration")),
        "calories_kcal": _float(m.get("caloriesKcal")), "steps": _int(m.get("steps")),
        "distance_millimeters": _float(m.get("distanceMillimeters")),
        "average_pace_seconds_per_meter": _float(m.get("averagePaceSecondsPerMeter")),
        "average_heart_rate_beats_per_minute": _int(m.get("averageHeartRateBeatsPerMinute")),
        "active_zone_minutes": _int(m.get("activeZoneMinutes")),
        "light_time_seconds": _seconds(zones.get("lightTime")), "moderate_time_seconds": _seconds(zones.get("moderateTime")),
        "vigorous_time_seconds": _seconds(zones.get("vigorousTime")), "peak_time_seconds": _seconds(zones.get("peakTime")),
        "metrics_summary": m, "exercise_metadata": v.get("exerciseMetadata"), "data_source": data_source(raw),
    }]}


def _session(key: str, table: str, id_col: str, start_col: str, end_col: str, values: Callable[[dict], dict]) -> Extractor:
    def extract(raw: dict) -> Rows:
        v = _value(raw, key)
        point_id, interval = _point_id(raw), v.get("interval") or {}
        if not point_id:
            return {}
        row = {id_col: point_id, start_col: _dt(interval.get("startTime")), end_col: _dt(interval.get("endTime")),
               "data_source": data_source(raw), **values(v)}
        return {table: [row]}
    return extract


EXTRACTORS: dict[str, Extractor] = {
    "steps": interval_series("steps", "steps", lambda v: {"steps": _int(v.get("count"))}),
    "distance": interval_series("distance", "distance", lambda v: {
        "distance_m": None if v.get("millimeters") is None else _float(v["millimeters"]) / 1000}),
    "floors": interval_series("floors", "floors", lambda v: {"floors": _int(v.get("count"))}),
    "active-energy-burned": interval_series("activeEnergyBurned", "active_energy_burned", lambda v: {"kilocalories": _float(v.get("kcal"))}),
    "total-calories": _total_calories,
    "active-zone-minutes": interval_series("activeZoneMinutes", "active_zone_minutes", lambda v: {
        "heart_rate_zone": v.get("heartRateZone") or "UNSPECIFIED", "total_minutes": _int(v.get("activeZoneMinutes"))}),
    "active-minutes": _active_minutes,
    "activity-level": interval_series("activityLevel", "activity_level", lambda v: {"activity_level_type": v.get("activityLevelType")}),
    "altitude": interval_series("altitude", "altitude", lambda v: {"gain_millimeters": _int(v.get("gainMillimeters"))}),
    "sedentary-period": interval_series("sedentaryPeriod", "sedentary_period", lambda v: {}),
    "time-in-heart-rate-zone": interval_series("timeInHeartRateZone", "time_in_heart_rate_zone", lambda v: {"heart_rate_zone_type": v.get("heartRateZoneType")}),
    "swim-lengths-data": _swim_lap,
    "heart-rate": sample_series("heartRate", "heart_rate", lambda v: {"beats_per_minute": _int(v.get("beatsPerMinute"))}),
    "heart-rate-variability": sample_series("heartRateVariability", "heart_rate_variability", lambda v: {
        "rmssd_milliseconds": _float(v.get("rootMeanSquareOfSuccessiveDifferencesMilliseconds")),
        "high_frequency_power": _float((v.get("metadata") or {}).get("highFrequencyPower")),
        "low_frequency_power": _float((v.get("metadata") or {}).get("lowFrequencyPower"))}),
    "oxygen-saturation": sample_series("oxygenSaturation", "oxygen_saturation", lambda v: {"oxygen_saturation_percentage": _float(v.get("percentage"))}),
    "body-fat": sample_series("bodyFat", "body_fat", lambda v: {"body_fat_percentage": _float(v.get("percentage"))}),
    "weight": sample_series("weight", "weight", lambda v: {"weight_grams": _float(v.get("weightGrams"))}),
    "height": sample_series("height", "height", lambda v: {"height_millimeters": _int(v.get("heightMillimeters"))}),
    "core-body-temperature": sample_series("coreBodyTemperature", "core_body_temperature", lambda v: {
        "temperature_celsius": _float(v.get("temperatureCelsius")), "measurement_location": v.get("measurementLocation")}),
    "blood-glucose": sample_series("bloodGlucose", "blood_glucose", lambda v: {
        "milligrams_per_deciliter": _float(v.get("bloodGlucoseMilligramsPerDeciliter")),
        "measurement_source": v.get("measurementSource"), "meal_type": v.get("mealType"),
        "measurement_timing": v.get("measurementTiming"), "specimen": v.get("specimen"), "notes": v.get("notes")}),
    "vo2-max": sample_series("vo2Max", "vo2_max", lambda v: {"vo2_max": _float(v.get("vo2Max")), "measurement_method": v.get("measurementMethod")}),
    "run-vo2-max": sample_series("runVo2Max", "run_vo2_max", lambda v: {"run_vo2_max": _float(v.get("runVo2Max"))}),
    "respiratory-rate-sleep-summary": sample_series("respiratoryRateSleepSummary", "respiratory_rate_sleep_summary", lambda v: {
        **_stats(v, "deep"), **_stats(v, "light"), **_stats(v, "rem"), **_stats(v, "full")}),
    "daily-resting-heart-rate": daily("dailyRestingHeartRate", "daily_resting_heart_rate", lambda v: {
        "beats_per_minute": _int(v.get("beatsPerMinute")),
        "calculation_method": (v.get("dailyRestingHeartRateMetadata") or {}).get("calculationMethod")}),
    "daily-respiratory-rate": daily("dailyRespiratoryRate", "daily_respiratory_rate", lambda v: {"breaths_per_minute": _float(v.get("breathsPerMinute"))}),
    "daily-heart-rate-variability": daily("dailyHeartRateVariability", "daily_heart_rate_variability", lambda v: {
        "average_heart_rate_variability_milliseconds": _float(v.get("averageHeartRateVariabilityMilliseconds")),
        "non_rem_heart_rate_beats_per_minute": _int(v.get("nonRemHeartRateBeatsPerMinute")),
        "entropy": _float(v.get("entropy")),
        "deep_sleep_rmssd_milliseconds": _float(v.get("deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds"))}),
    "daily-oxygen-saturation": daily("dailyOxygenSaturation", "daily_oxygen_saturation", lambda v: {
        "average_percentage": _float(v.get("averagePercentage")), "lower_bound_percentage": _float(v.get("lowerBoundPercentage")),
        "upper_bound_percentage": _float(v.get("upperBoundPercentage")), "baseline_percentage": _float(v.get("baselinePercentage")),
        "standard_deviation_percentage": _float(v.get("standardDeviationPercentage"))}),
    "daily-sleep-temperature-derivations": daily("dailySleepTemperatureDerivations", "daily_sleep_temperature_derivations", lambda v: {
        "nightly_temperature_celsius": _float(v.get("nightlyTemperatureCelsius")),
        "baseline_temperature_celsius": _float(v.get("baselineTemperatureCelsius")),
        "relative_nightly_stddev_30d_celsius": _float(v.get("relativeNightlyStddev30dCelsius"))}),
    "daily-heart-rate-zones": _daily_heart_rate_zones,
    "daily-vo2-max": daily("dailyVo2Max", "daily_vo2_max", lambda v: {
        "vo2_max": _float(v.get("vo2Max")), "vo2_max_covariance": _float(v.get("vo2MaxCovariance")),
        "cardio_fitness_level": v.get("cardioFitnessLevel"), "estimated": v.get("estimated")}),
    "sleep": _sleep,
    "exercise": _exercise,
    "electrocardiogram": _session("electrocardiogram", "electrocardiograms", "ecg_id", "ecg_start", "ecg_end", lambda v: {
        "result_classification": v.get("resultClassification"), "beats_per_minute_avg": _int(v.get("beatsPerMinuteAvg")),
        "sampling_frequency_hertz": _int(v.get("samplingFrequencyHertz")), "millivolts_scaling_factor": _int(v.get("millivoltsScalingFactor")),
        "lead_number": _int(v.get("leadNumber")), "waveform_samples": v.get("waveformSamples"),
        "medical_device_info": v.get("medicalDeviceInfo")}),
    "irregular-rhythm-notification": _session("irregularRhythmNotification", "irregular_rhythm_notifications", "irn_id", "irn_start", "irn_end", lambda v: {
        "alert_windows": v.get("alertWindows"), "medical_device_info": v.get("medicalDeviceInfo")}),
    "hydration-log": _session("hydrationLog", "hydration_logs", "hydration_log_id", "log_start", "log_end", lambda v: {
        "amount_consumed": v.get("amountConsumed")}),
    "nutrition-log": _session("nutritionLog", "nutrition_logs", "nutrition_log_id", "log_start", "log_end", lambda v: {
        "meal_type": v.get("mealType"), "food": v.get("food"), "food_display_name": v.get("foodDisplayName"),
        "energy": v.get("energy"), "energy_from_fat": v.get("energyFromFat"), "total_carbohydrate": v.get("totalCarbohydrate"),
        "total_fat": v.get("totalFat"), "nutrients": v.get("nutrients"), "serving": v.get("serving")}),
}


class TypedMapper:
    @staticmethod
    def rows_for(data_type: str, raw: dict) -> Rows:
        """Typed rows for one raw point; unknown data types yield nothing (raw JSON still holds them)."""
        extractor = EXTRACTORS.get(data_type)
        if extractor is None:
            return {}
        rows = extractor(raw)
        # Fill every declared column so executemany sees a uniform shape; drop rows missing a key.
        out: Rows = {}
        for table, table_rows in rows.items():
            spec = TABLES[table]
            kept = []
            for row in table_rows:
                if any(row.get(k) is None for k in spec.key):
                    continue
                kept.append({c: row.get(c) for c in spec.column_names})
            if kept:
                out[table] = kept
        return out
