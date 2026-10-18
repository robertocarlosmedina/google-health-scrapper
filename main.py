import argparse
import json
import logging
import sys

from scraper.helpers.logging import setupLogging
setupLogging()

from scraper import globals as g
from scraper.adapters.postgres_data_point_adapter import PostgresDataPointRepositoryAdapter
from scraper.adapters.postgres_sync_state_adapter import PostgresSyncStateRepositoryAdapter
from scraper.clients.google_auth import AuthError, run_consent_flow
from scraper.clients.google_health_client import GoogleHealthClient
from scraper.db_connectors.postgres_connector import ensure_schema, postgres_connector
from scraper.services.sync_service import SyncService, resolve_data_types

logger = logging.getLogger(__name__)


def build_service() -> SyncService:
    conn = postgres_connector(g.POSTGRES_DB, g.POSTGRES_HOST, g.POSTGRES_PORT, g.POSTGRES_USER, g.POSTGRES_PASSWORD)
    ensure_schema(conn)
    return SyncService(
        client=GoogleHealthClient(),
        data_point_repository=PostgresDataPointRepositoryAdapter(conn),
        sync_state_repository=PostgresSyncStateRepositoryAdapter(conn),
        data_types=resolve_data_types(g.SYNC_DATA_TYPES),
        initial_lookback_days=g.SYNC_INITIAL_LOOKBACK_DAYS,
        overlap_hours=g.SYNC_OVERLAP_HOURS,
        window_days=g.SYNC_WINDOW_DAYS,
    )


def cmd_auth(_args) -> int:
    run_consent_flow()
    return 0


def cmd_sync(_args) -> int:
    """Single sync, exit. Use this from system cron / launchd / k8s CronJob."""
    build_service().run_once()
    return 0


def cmd_run(_args) -> int:
    """Long-running process: sync every SYNC_INTERVAL_MINUTES."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    if g.SYNC_INTERVAL_MINUTES <= 0:
        logger.error("SYNC_INTERVAL_MINUTES must be > 0 for `run`; use `sync` with system cron instead")
        return 2

    service = build_service()

    def job():
        try:
            service.run_once()
        except Exception:
            logger.exception("Sync job crashed")

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        job, "interval", minutes=g.SYNC_INTERVAL_MINUTES,
        max_instances=1, coalesce=True, id="google-health-sync",
    )
    logger.info("Scheduler started: syncing every %d min", g.SYNC_INTERVAL_MINUTES)
    if g.SYNC_ON_START:
        job()
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
    return 0


def cmd_probe(args) -> int:
    """Print one raw page of a data type, to inspect the API's real response shape."""
    client = GoogleHealthClient()
    for i, point in enumerate(client.list_data_points(args.data_type, page_size=args.limit)):
        if i >= args.limit:
            break
        print(json.dumps(point, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Google Health -> PostgreSQL scraper")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("auth", help="one-time Google login, stores the refresh token").set_defaults(func=cmd_auth)
    sub.add_parser("sync", help="run a single sync and exit (for system cron)").set_defaults(func=cmd_sync)
    sub.add_parser("run", help="run forever, syncing on SYNC_INTERVAL_MINUTES").set_defaults(func=cmd_run)
    probe = sub.add_parser("probe", help="print raw data points for one data type")
    probe.add_argument("data_type")
    probe.add_argument("--limit", type=int, default=3)
    probe.set_defaults(func=cmd_probe)

    args = parser.parse_args()
    logger.info("%s GOOGLE HEALTH SCRAPER (%s) %s", "-" * 12, args.command, "-" * 12)
    try:
        return args.func(args)
    except AuthError as e:
        logger.error("%s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
