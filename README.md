# google-health-scrapper

Cron-style scraper: pulls your Fitbit / Google Health data from the
[Google Health API](https://developers.google.com/health) (`https://health.googleapis.com/v4`) and
upserts it into PostgreSQL.

## Setup

1. Google Cloud Console: create a project, enable the **Google Health API**, configure the OAuth consent
   screen (add yourself as test user) and create an OAuth client of type **Desktop app**.
2. `cp .env.example .env` and fill `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.
3. `docker compose up -d postgres` (or point `POSTGRES_*` at your own server).
4. `uv sync`
5. `uv run python main.py auth` — browser login, stores the refresh token in `token.json`.

## Run

| Command | What it does |
| --- | --- |
| `uv run python main.py run` | Long-running; syncs every `SYNC_INTERVAL_MINUTES` (default 60). |
| `uv run python main.py sync` | One sync then exit — use with system cron: `0 * * * * cd /path && uv run python main.py sync` |
| `uv run python main.py probe steps` | Print raw API data points for a type (inspect the real response shape). |
| `docker compose --profile scraper up -d` | Postgres + the scraper container (needs `token.json` from step 5). |

## How syncing works

- `SYNC_DATA_TYPES`: `default`, `all`, or a comma list of [data types](https://developers.google.com/health/data-types) (kebab-case).
- Per type, a checkpoint in `sync_state` records how far we got. Each run re-reads `SYNC_OVERLAP_HOURS`
  before it (Fitbit uploads late) in `SYNC_WINDOW_DAYS` chunks; first run goes back `SYNC_INITIAL_LOOKBACK_DAYS`.
- Data lands in `health_data_points (data_type, point_id, start_time, end_time, record_date, payload jsonb)`,
  upserted on `(data_type, point_id)`, so re-runs never duplicate. The full API JSON is kept in `payload`;
  query it with e.g. `SELECT record_date, payload->'steps'->>'count' FROM health_data_points WHERE data_type='steps'`.
- One failing data type is logged in `sync_state.last_error` and doesn't stop the others.
