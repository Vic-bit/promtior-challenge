import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from app.config import settings
from app.db import get_conn, init_db

TEST_DB = "booking_test"


@pytest.fixture(scope="session")
def test_database():
    """Point the app to its own database, so tests never touch the data used for manual testing."""
    # CREATE DATABASE can't run inside a transaction, hence autocommit.
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone()
        if not exists:
            conn.execute("CREATE DATABASE booking_test")
    settings.database_url = make_conninfo(settings.database_url, dbname=TEST_DB)


@pytest.fixture
def db(test_database):
    # Every test that touches the database starts with no bookings; seeded users are kept.
    init_db()
    with get_conn() as conn:
        conn.execute("TRUNCATE bookings, booking_slots RESTART IDENTITY")
