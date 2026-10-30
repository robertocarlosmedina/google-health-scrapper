-- Read-model for dashboards (Grafana). Everything here is derived from the typed tables and is idempotent
-- (CREATE OR REPLACE); to change the columns of an existing view, DROP it first.
--
-- Conventions
--   * "device" collapses the many data_source spellings into Fitbit / Phone / <other>: the watch was renamed
--     ("Google Fitbit Air" -> "Fitbit Air") and both names carry the same readings for the days they overlap.
--   * Rows are de-duplicated per (time, device) before aggregating, so the rename overlap never double counts.
--   * Per-day series (steps, distance, ...) keep ONE device per day: the one that recorded the most, because the
--     watch and the phone both count the same walk.
--   * Local dates use the time zone from the Fitbit settings (health_tz()), falling back to UTC.

CREATE OR REPLACE FUNCTION health_tz() RETURNS text LANGUAGE sql STABLE AS $$
    SELECT coalesce((SELECT payload->>'timeZone' FROM user_resources WHERE resource = 'settings'), 'UTC')
$$;

CREATE OR REPLACE FUNCTION health_device(data_source text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN data_source ILIKE '%fitbit%' THEN 'Fitbit'
        WHEN data_source ILIKE '%phone%' THEN 'Phone'
        ELSE coalesce(nullif(data_source, ''), 'Unknown')
    END
$$;

-- ---------------------------------------------------------------- activity (daily totals)

CREATE OR REPLACE VIEW v_steps_daily AS
SELECT DISTINCT ON (date) date, steps, device FROM (
    SELECT (timestamp AT TIME ZONE health_tz())::date AS date, device, sum(steps) AS steps
    FROM (SELECT DISTINCT ON (timestamp, end_time, health_device(data_source))
                 timestamp, steps, health_device(data_source) AS device FROM steps) s
    GROUP BY 1, 2
) d ORDER BY date, steps DESC;

CREATE OR REPLACE VIEW v_distance_daily AS
SELECT DISTINCT ON (date) date, distance_km, device FROM (
    SELECT (timestamp AT TIME ZONE health_tz())::date AS date, device, sum(distance_m) / 1000.0 AS distance_km
    FROM (SELECT DISTINCT ON (timestamp, end_time, health_device(data_source))
                 timestamp, distance_m, health_device(data_source) AS device FROM distance) s
    GROUP BY 1, 2
) d ORDER BY date, distance_km DESC;

CREATE OR REPLACE VIEW v_floors_daily AS
SELECT DISTINCT ON (date) date, floors, device FROM (
    SELECT (timestamp AT TIME ZONE health_tz())::date AS date, device, sum(floors) AS floors
    FROM (SELECT DISTINCT ON (timestamp, end_time, health_device(data_source))
                 timestamp, floors, health_device(data_source) AS device FROM floors) s
    GROUP BY 1, 2
) d ORDER BY date, floors DESC;

-- total calories (rollup, one source "all sources") next to the active part burned
CREATE OR REPLACE VIEW v_calories_daily AS
SELECT coalesce(c.date, a.date) AS date, c.calories, a.active_kcal
FROM (SELECT (timestamp AT TIME ZONE health_tz())::date AS date, sum(calories) AS calories
      FROM calories GROUP BY 1) c
FULL JOIN (SELECT date, sum(kcal) AS active_kcal FROM (
               SELECT DISTINCT ON (timestamp, end_time, health_device(data_source))
                      (timestamp AT TIME ZONE health_tz())::date AS date, kilocalories AS kcal
               FROM active_energy_burned) x GROUP BY 1) a ON a.date = c.date;

-- steps per hour of the day, for the "when do I move" heatmap (same device as the daily total)
CREATE OR REPLACE VIEW v_steps_hourly AS
SELECT date_trunc('hour', s.timestamp AT TIME ZONE health_tz()) AT TIME ZONE health_tz() AS hour,
       extract(hour FROM s.timestamp AT TIME ZONE health_tz())::int AS hour_of_day,
       (s.timestamp AT TIME ZONE health_tz())::date AS date,
       sum(s.steps) AS steps
FROM (SELECT DISTINCT ON (timestamp, end_time, health_device(data_source))
             timestamp, steps, health_device(data_source) AS device FROM steps) s
JOIN v_steps_daily d ON d.date = (s.timestamp AT TIME ZONE health_tz())::date AND d.device = s.device
GROUP BY 1, 2, 3;

CREATE OR REPLACE VIEW v_active_minutes_daily AS
SELECT (timestamp AT TIME ZONE health_tz())::date AS date, activity_level, sum(active_minutes) AS minutes
FROM (SELECT DISTINCT ON (timestamp, end_time, activity_level, health_device(data_source))
             timestamp, activity_level, active_minutes FROM active_minutes) x
GROUP BY 1, 2;

CREATE OR REPLACE VIEW v_active_zone_minutes_daily AS
SELECT (timestamp AT TIME ZONE health_tz())::date AS date, heart_rate_zone, sum(total_minutes) AS minutes
FROM (SELECT DISTINCT ON (timestamp, end_time, heart_rate_zone, health_device(data_source))
             timestamp, heart_rate_zone, total_minutes FROM active_zone_minutes) x
GROUP BY 1, 2;

-- minutes per activity level (SEDENTARY ... VERY_ACTIVE) from the interval series
CREATE OR REPLACE VIEW v_activity_level_daily AS
SELECT (timestamp AT TIME ZONE health_tz())::date AS date, activity_level_type AS level,
       sum(extract(epoch FROM end_time - timestamp) / 60.0) AS minutes
FROM (SELECT DISTINCT ON (timestamp, end_time, health_device(data_source))
             timestamp, end_time, activity_level_type FROM activity_level) x
GROUP BY 1, 2;

CREATE OR REPLACE VIEW v_time_in_hr_zone_daily AS
SELECT (timestamp AT TIME ZONE health_tz())::date AS date, heart_rate_zone_type AS zone,
       sum(extract(epoch FROM end_time - timestamp) / 60.0) AS minutes
FROM (SELECT DISTINCT ON (timestamp, end_time, heart_rate_zone_type, health_device(data_source))
             timestamp, end_time, heart_rate_zone_type FROM time_in_heart_rate_zone) x
GROUP BY 1, 2;

-- ---------------------------------------------------------------- heart and recovery

-- raw samples (about 650k rows): always filter by timestamp and bucket in the query
CREATE OR REPLACE VIEW v_heart_rate AS
SELECT DISTINCT ON (timestamp, health_device(data_source))
       timestamp, beats_per_minute AS bpm, health_device(data_source) AS device
FROM heart_rate;

CREATE OR REPLACE VIEW v_heart_rate_daily AS
SELECT (timestamp AT TIME ZONE health_tz())::date AS date,
       min(bpm) AS min_bpm, round(avg(bpm), 1) AS avg_bpm, max(bpm) AS max_bpm, count(*) AS samples
FROM v_heart_rate GROUP BY 1;

CREATE OR REPLACE VIEW v_resting_hr AS
SELECT DISTINCT ON (date) date, beats_per_minute AS bpm, calculation_method
FROM daily_resting_heart_rate ORDER BY date, updated_at DESC;

CREATE OR REPLACE VIEW v_hrv_daily AS
SELECT DISTINCT ON (date) date, average_heart_rate_variability_milliseconds AS avg_ms,
       deep_sleep_rmssd_milliseconds AS deep_sleep_ms, non_rem_heart_rate_beats_per_minute AS non_rem_hr, entropy
FROM daily_heart_rate_variability ORDER BY date, updated_at DESC;

CREATE OR REPLACE VIEW v_spo2_daily AS
SELECT DISTINCT ON (date) date, average_percentage AS avg_pct, lower_bound_percentage AS low_pct,
       upper_bound_percentage AS high_pct, baseline_percentage AS baseline_pct
FROM daily_oxygen_saturation ORDER BY date, updated_at DESC;

CREATE OR REPLACE VIEW v_respiratory_rate_daily AS
SELECT DISTINCT ON (date) date, breaths_per_minute
FROM daily_respiratory_rate ORDER BY date, updated_at DESC;

CREATE OR REPLACE VIEW v_skin_temperature AS
SELECT DISTINCT ON (date) date, nightly_temperature_celsius AS nightly_c,
       nullif(baseline_temperature_celsius, 'NaN') AS baseline_c,  -- the API sends NaN until a baseline exists
       nightly_temperature_celsius - nullif(baseline_temperature_celsius, 'NaN') AS delta_c
FROM daily_sleep_temperature_derivations ORDER BY date, updated_at DESC;

CREATE OR REPLACE VIEW v_vo2_max_daily AS
SELECT DISTINCT ON (date) date, vo2_max, cardio_fitness_level, estimated
FROM daily_vo2_max ORDER BY date, updated_at DESC;

-- latest heart rate zone boundaries (one row per zone)
CREATE OR REPLACE VIEW v_hr_zones AS
SELECT DISTINCT ON (heart_rate_zone_type) heart_rate_zone_type AS zone, min_heart_rate_bpm AS min_bpm,
       max_heart_rate_bpm AS max_bpm, date
FROM daily_heart_rate_zones ORDER BY heart_rate_zone_type, date DESC;

-- ECG without the waveform (large); the classification is what the dashboard needs
CREATE OR REPLACE VIEW v_ecg AS
SELECT ecg_id, ecg_start AS started, ecg_end AS ended, result_classification AS classification,
       beats_per_minute_avg AS avg_bpm, sampling_frequency_hertz AS hertz, lead_number, data_source
FROM electrocardiograms;

CREATE OR REPLACE VIEW v_irregular_rhythm AS
SELECT irn_id, irn_start AS started, irn_end AS ended, alert_windows, data_source
FROM irregular_rhythm_notifications;

-- ---------------------------------------------------------------- sleep

-- one row per night; stage minutes come from the stages summary (counts and minutes are strings there)
CREATE OR REPLACE VIEW v_sleep AS
SELECT s.sleep_id, (s.sleep_end AT TIME ZONE health_tz())::date AS date, s.sleep_start AS started, s.sleep_end AS ended,
       s.main_sleep, s.minutes_in_sleep_period AS minutes_in_bed, s.minutes_asleep, s.minutes_awake,
       s.minutes_to_fall_asleep, s.minutes_after_wake_up,
       round(100.0 * s.minutes_asleep / nullif(s.minutes_in_sleep_period, 0), 1) AS efficiency_pct,
       (SELECT sum((e->>'minutes')::int) FROM jsonb_array_elements(s.stages_summary) e WHERE e->>'type' = 'DEEP') AS deep_min,
       (SELECT sum((e->>'minutes')::int) FROM jsonb_array_elements(s.stages_summary) e WHERE e->>'type' = 'LIGHT') AS light_min,
       (SELECT sum((e->>'minutes')::int) FROM jsonb_array_elements(s.stages_summary) e WHERE e->>'type' = 'REM') AS rem_min,
       (SELECT sum((e->>'minutes')::int) FROM jsonb_array_elements(s.stages_summary) e WHERE e->>'type' = 'AWAKE') AS awake_min,
       extract(hour FROM s.sleep_start AT TIME ZONE health_tz()) + extract(minute FROM s.sleep_start AT TIME ZONE health_tz()) / 60.0 AS bedtime_hour,
       extract(hour FROM s.sleep_end AT TIME ZONE health_tz()) + extract(minute FROM s.sleep_end AT TIME ZONE health_tz()) / 60.0 AS wake_hour
FROM (SELECT DISTINCT ON (sleep_start, sleep_end) * FROM sleeps ORDER BY sleep_start, sleep_end, sleep_last_updated DESC NULLS LAST) s;

CREATE OR REPLACE VIEW v_sleep_stages AS
SELECT sleep_id, sleep_stage_type AS stage, sleep_stage_start AS started, sleep_stage_end AS ended,
       extract(epoch FROM sleep_stage_end - sleep_stage_start) / 60.0 AS minutes
FROM sleep_stages;

CREATE OR REPLACE VIEW v_sleep_breathing AS
SELECT timestamp, deep_sleep_breaths_per_minute AS deep, light_sleep_breaths_per_minute AS light,
       rem_sleep_breaths_per_minute AS rem, full_sleep_breaths_per_minute AS full
FROM respiratory_rate_sleep_summary;

-- ---------------------------------------------------------------- workouts and body

CREATE OR REPLACE VIEW v_exercises AS
SELECT exercise_id, exercise_start AS started, exercise_end AS ended,
       (exercise_start AT TIME ZONE health_tz())::date AS date,
       exercise_type AS type, activity_name AS name,
       round((active_duration_seconds / 60.0)::numeric, 1) AS duration_min,
       calories_kcal AS kcal, steps, round((distance_millimeters / 1000000.0)::numeric, 2) AS distance_km,
       round((average_pace_seconds_per_meter * 1000 / 60.0)::numeric, 2) AS pace_min_per_km,
       average_heart_rate_beats_per_minute AS avg_bpm, active_zone_minutes AS zone_minutes,
       round((light_time_seconds / 60.0)::numeric, 1) AS light_min,
       round((moderate_time_seconds / 60.0)::numeric, 1) AS moderate_min,
       round((vigorous_time_seconds / 60.0)::numeric, 1) AS vigorous_min,
       round((peak_time_seconds / 60.0)::numeric, 1) AS peak_min
FROM (SELECT DISTINCT ON (exercise_start, exercise_type) * FROM exercises
      ORDER BY exercise_start, exercise_type, exercise_last_updated DESC NULLS LAST) e;

CREATE OR REPLACE VIEW v_swim_laps AS
SELECT timestamp, end_time, lap_time_seconds, stroke_count, stroke_type
FROM swim_lengths_data;

CREATE OR REPLACE VIEW v_weight AS
SELECT timestamp, round((weight_grams / 1000.0)::numeric, 2) AS kg, data_source
FROM weight;

CREATE OR REPLACE VIEW v_body_fat AS
SELECT timestamp, body_fat_percentage AS pct, data_source FROM body_fat;

-- latest profile numbers for the stat tiles (age, height, weight, BMI)
CREATE OR REPLACE VIEW v_body_latest AS
SELECT (SELECT round((weight_grams / 1000.0)::numeric, 1) FROM weight ORDER BY timestamp DESC LIMIT 1) AS weight_kg,
       (SELECT height_millimeters / 10.0 FROM height ORDER BY timestamp DESC LIMIT 1) AS height_cm,
       (SELECT (payload->>'age')::int FROM user_resources WHERE resource = 'profile') AS age,
       (SELECT round((w.weight_grams / 1000.0 / power(h.height_millimeters / 1000.0, 2))::numeric, 1)
          FROM (SELECT weight_grams FROM weight ORDER BY timestamp DESC LIMIT 1) w,
               (SELECT height_millimeters FROM height ORDER BY timestamp DESC LIMIT 1) h) AS bmi;

-- ---------------------------------------------------------------- nutrition (raw JSON until real data shows the shape)

CREATE OR REPLACE VIEW v_hydration AS
SELECT hydration_log_id, log_start AS logged_at, amount_consumed, data_source FROM hydration_logs;

CREATE OR REPLACE VIEW v_nutrition AS
SELECT nutrition_log_id, log_start AS logged_at, meal_type, food_display_name AS food, energy, total_carbohydrate,
       total_fat, serving, data_source
FROM nutrition_logs;

-- ---------------------------------------------------------------- pipeline health

CREATE OR REPLACE VIEW v_sync_status AS
SELECT data_type, last_synced_at,
       round(extract(epoch FROM now() - last_synced_at) / 60.0) AS minutes_ago,
       CASE WHEN last_error IS NOT NULL AND last_error <> '' THEN 'FAILED' ELSE 'OK' END AS status,
       left(regexp_replace(coalesce(last_error, ''), '\s+', ' ', 'g'), 160) AS last_error
FROM sync_state;

CREATE OR REPLACE VIEW v_table_stats AS
SELECT relname AS table_name, n_live_tup AS rows, pg_total_relation_size(relid) AS bytes
FROM pg_stat_user_tables;
