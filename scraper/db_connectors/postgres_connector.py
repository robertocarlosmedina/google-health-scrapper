import logging
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from scraper.models.typed_tables import schema_sql

SCHEMA_FILE = Path(__file__).parent / "sql" / "schema.sql"


def postgres_connector(db_name, host, port, user, password) -> psycopg.Connection:
    logging.info("Connecting to PostgreSQL at %s:%s/%s", host, port, db_name)

    try:
        conn = psycopg.connect(
            dbname=db_name,
            host=host,
            port=port,
            user=user,
            password=password,
            connect_timeout=5,
            autocommit=True,
            row_factory=dict_row,
        )
        logging.info("Connected to PostgreSQL successfully")
        return conn
    except psycopg.OperationalError as e:
        logging.error("Could not connect to PostgreSQL: %s", e)
        raise


def ensure_schema(conn: psycopg.Connection) -> None:
    """Create tables if missing (idempotent)."""
    conn.execute(SCHEMA_FILE.read_text())
    conn.execute(schema_sql())  # typed tables are generated from scraper/models/typed_tables.py
    logging.info("Database schema is up to date")
