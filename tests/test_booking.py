from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg
import pytest

from app.db import get_conn, init_db

TZ = ZoneInfo("America/Montevideo")


def test_init_db_is_idempotent_and_seeds_both_users(db):
    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT username FROM users ORDER BY username").fetchall()
    assert [row["username"] for row in rows] == ["User1", "User2"]


def test_database_rejects_the_same_slot_twice(db):
    slot = datetime(2026, 10, 16, 10, 0, tzinfo=TZ)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with get_conn() as conn:
            booking = conn.execute(
                "INSERT INTO bookings (user_id, room, title, attendees, start_time, end_time)"
                " VALUES (1, 'A', 'Test', 2, %s, %s) RETURNING id",
                (slot, slot),
            ).fetchone()
            for _ in range(2):
                conn.execute(
                    "INSERT INTO booking_slots (booking_id, room, slot_start) VALUES (%s, 'A', %s)",
                    (booking["id"], slot),
                )
