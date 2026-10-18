"""Catalogue of readable Google Health data types and how to filter each one.

Source: https://developers.google.com/health/data-types
`kind` decides which filter field the `list` endpoint accepts.
"""

INTERVAL = "interval"
SAMPLE = "sample"
DAILY = "daily"
SESSION = "session"
SLEEP = "sleep"

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
    "exercise": SESSION,
    "heart-rate": SAMPLE,
    "heart-rate-variability": SAMPLE,
    "height": SAMPLE,
    "hydration-log": SESSION,
    "nutrition-log": SESSION,
    "oxygen-saturation": SAMPLE,
    "respiratory-rate-sleep-summary": SAMPLE,
    "run-vo2-max": SAMPLE,
    "sedentary-period": INTERVAL,
    "sleep": SLEEP,
    "steps": INTERVAL,
    "swim-lengths-data": INTERVAL,
    "time-in-heart-rate-zone": INTERVAL,
    "vo2-max": SAMPLE,
    "weight": SAMPLE,
}

DEFAULT_DATA_TYPES = [
    "steps",
    "heart-rate",
    "sleep",
    "exercise",
    "active-zone-minutes",
    "distance",
    "daily-resting-heart-rate",
    "daily-heart-rate-variability",
    "daily-oxygen-saturation",
    "daily-respiratory-rate",
    "daily-vo2-max",
    "weight",
    "body-fat",
]
