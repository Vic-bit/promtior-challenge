import pytest

from app.db import get_conn, init_db


@pytest.fixture
def db():
    # Every test that touches the database starts with no bookings; seeded users are kept.
    init_db()
    with get_conn() as conn:
        conn.execute("TRUNCATE bookings, booking_slots RESTART IDENTITY")
