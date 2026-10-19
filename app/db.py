"""Database access: connections, schema creation and user seed."""

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from app.auth import hash_password
from app.config import settings

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
SEED_USERS = ["User1", "User2"]
SEED_PASSWORD = "TechnicalChallengePromtior"


def get_conn() -> psycopg.Connection:
    """Open a new connection that returns rows as dicts.

    Use it as `with get_conn() as conn:` -> commits on success, rolls back on error.
    """
    # The session time zone makes Postgres return office time instead of UTC.
    return psycopg.connect(
        settings.database_url,
        row_factory=dict_row,
        options=f"-c timezone={settings.timezone}",
    )


def init_db() -> None:
    """Create the tables if missing and seed User1 and User2. Safe to run on every startup."""
    with get_conn() as conn:
        conn.execute(SCHEMA_PATH.read_text())
        for username in SEED_USERS:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s, %s) ON CONFLICT (username) DO NOTHING",
                (username, hash_password(SEED_PASSWORD)),
            )
