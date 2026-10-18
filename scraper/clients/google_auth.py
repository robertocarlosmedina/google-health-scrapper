import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from scraper.globals import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_OAUTH_PORT, GOOGLE_TOKEN_FILE

logger = logging.getLogger(__name__)

_SCOPE_PREFIX = "https://www.googleapis.com/auth/googlehealth."
# Read-only scopes covering every data type the scraper knows about (see scraper/models/data_types.py).
SCOPES = [
    _SCOPE_PREFIX + "activity_and_fitness.readonly",
    _SCOPE_PREFIX + "health_metrics_and_measurements.readonly",
    _SCOPE_PREFIX + "sleep.readonly",
]


class AuthError(RuntimeError):
    pass


def run_consent_flow() -> None:
    """One-time interactive login: opens the browser and stores the refresh token."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise AuthError("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env first")

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [f"http://localhost:{GOOGLE_OAUTH_PORT}/" if GOOGLE_OAUTH_PORT else "http://localhost"],
            }
        },
        scopes=SCOPES,
    )
    # offline + consent forces Google to return a refresh token.
    creds = flow.run_local_server(port=GOOGLE_OAUTH_PORT, access_type="offline", prompt="consent")
    Path(GOOGLE_TOKEN_FILE).write_text(creds.to_json())
    Path(GOOGLE_TOKEN_FILE).chmod(0o600)
    logger.info("Saved credentials to %s", GOOGLE_TOKEN_FILE)


def load_access_token(force_refresh: bool = False) -> str:
    """Return a valid access token, refreshing (and persisting) it when expired or forced."""
    token_path = Path(GOOGLE_TOKEN_FILE)
    if not token_path.exists():
        raise AuthError(f"{GOOGLE_TOKEN_FILE} not found - run `uv run python main.py auth` first")

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if force_refresh or not creds.valid:
        if not creds.refresh_token:
            raise AuthError("No refresh token stored - run `uv run python main.py auth` again")
        logger.debug("Refreshing Google access token")
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    return creds.token
