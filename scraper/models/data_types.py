"""Catalogue of readable Google Health data types and how to filter each one.

Source: https://developers.google.com/health/data-types
`kind` decides which filter field the `list` endpoint accepts.
"""

INTERVAL = "interval"
SAMPLE = "sample"
DAILY = "daily"
SESSION = "session"
SLEEP = "sleep"
ROLLUP = "rollup"  # no `list`: read through dataPoints:rollUp in fixed windows

DATA_TYPE_KINDS: dict[str, str] = {
    "active-energy-burned": INTERVAL,
    "active-minutes": INTERVAL,
    "active-zone-minutes": INTERVAL,
    "activity-level": INTERVAL,
    "altitude": INTERVAL,
    "blood-glucose": SAMPLE,
    "body-fat": SAMPLE,
    "core-body-temperature": SAMPLE,
    "daily-heart-rate-variability": DAILY,
    "daily-heart-rate-zones": DAILY,
    "daily-oxygen-saturation": DAILY,
    "daily-respiratory-rate": DAILY,
    "daily-resting-heart-rate": DAILY,
    "daily-sleep-temperature-derivations": DAILY,
    "daily-vo2-max": DAILY,
    "distance": INTERVAL,
    "electrocardiogram": SESSION,
    "exercise": SESSION,
    "floors": INTERVAL,
    "heart-rate": SAMPLE,
    "heart-rate-variability": SAMPLE,
    "height": SAMPLE,
    "hydration-log": SESSION,
    "irregular-rhythm-notification": SESSION,
    "nutrition-log": SESSION,
    "oxygen-saturation": SAMPLE,
    "respiratory-rate-sleep-summary": SAMPLE,
    "run-vo2-max": SAMPLE,
    "sedentary-period": INTERVAL,
    "sleep": SLEEP,
    "steps": INTERVAL,
    "swim-lengths-data": INTERVAL,
    "time-in-heart-rate-zone": INTERVAL,
    "total-calories": ROLLUP,
    "vo2-max": SAMPLE,
    "weight": SAMPLE,
}

# ECG queries only accept `interval.start_time >= ...` (no upper bound, no civil time).
LOWER_BOUND_ONLY_TYPES = {"electrocardiogram"}

# Types whose `list` is unsupported but that can be read with `dataPoints:reconcile`.
RECONCILE_TYPES = {"floors"}

# calories-in-heart-rate-zone (rollup only) is skipped on purpose: it duplicates total-calories
# at the same minute granularity, and food / food-measurement-unit are a catalogue, not history.

# "default" means everything readable; narrow it with SYNC_DATA_TYPES if you want less.
DEFAULT_DATA_TYPES = sorted(DATA_TYPE_KINDS)
