import os
from dotenv import load_dotenv


load_dotenv()


def _bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


POSTGRES_DB = os.environ.get("POSTGRES_DB", "google_health")
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", 5432))
POSTGRES_USER = os.environ.get("POSTGRES_USER", "")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_OAUTH_PORT = int(os.environ.get("GOOGLE_OAUTH_PORT", 0))
GOOGLE_TOKEN_FILE = os.environ.get("GOOGLE_TOKEN_FILE", "token.json")
GOOGLE_HEALTH_BASE_URL = os.environ.get("GOOGLE_HEALTH_BASE_URL", "https://health.googleapis.com").rstrip("/")

SYNC_INTERVAL_MINUTES = int(os.environ.get("SYNC_INTERVAL_MINUTES", 60))
SYNC_ON_START = _bool("SYNC_ON_START", "true")
SYNC_DATA_TYPES = os.environ.get("SYNC_DATA_TYPES", "default")
SYNC_INITIAL_LOOKBACK_DAYS = int(os.environ.get("SYNC_INITIAL_LOOKBACK_DAYS", 30))
SYNC_OVERLAP_HOURS = int(os.environ.get("SYNC_OVERLAP_HOURS", 48))
SYNC_WINDOW_DAYS = int(os.environ.get("SYNC_WINDOW_DAYS", 7))
