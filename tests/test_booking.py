from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest

from app.booking import (
    cancel_booking,
    create_booking,
    get_room_schedule,
    list_available_rooms,
    list_my_bookings,
)
from app.db import get_conn, init_db
from app.exceptions import BookingNotFound, InvalidBooking, NotBookingOwner, SlotConflict

TZ = ZoneInfo("America/Montevideo")


def at(hour: int, minute: int = 0) -> datetime:
    # Tomorrow, so tests never hit the "start in the past" rule.
    tomorrow = datetime.now(TZ).date() + timedelta(days=1)
    return datetime.combine(tomorrow, time(hour, minute), tzinfo=TZ)


def user_id(username: str) -> int:
    with get_conn() as conn:
        return conn.execute("SELECT id FROM users WHERE username = %s", (username,)).fetchone()["id"]


def book(username="User1", room="A", start=None, end=None, title="Team sync", attendees=3) -> dict:
    return create_booking(user_id(username), room, start or at(10), end or at(11, 30), title, attendees)


def count(table: str) -> int:
    queries = {
        "bookings": "SELECT count(*) AS n FROM bookings",
        "booking_slots": "SELECT count(*) AS n FROM booking_slots",
    }
    with get_conn() as conn:
        return conn.execute(queries[table]).fetchone()["n"]


def test_init_db_is_idempotent_and_seeds_both_users(db):
    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT username FROM users ORDER BY username").fetchall()
    assert [row["username"] for row in rows] == ["User1", "User2"]


def test_database_rejects_the_same_slot_twice(db):
    slot = at(10)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with get_conn() as conn:
            booking = conn.execute(
                "INSERT INTO bookings (user_id, room, title, attendees, start_time, end_time)"
                " VALUES (%s, 'A', 'Test', 2, %s, %s) RETURNING id",
                (user_id("User1"), slot, slot),
            ).fetchone()
            for _ in range(2):
                conn.execute(
                    "INSERT INTO booking_slots (booking_id, room, slot_start) VALUES (%s, 'A', %s)",
                    (booking["id"], slot),
                )


def test_create_booking_stores_one_row_per_slot(db):
    booking = book(start=at(10), end=at(11, 30))
    assert booking["status"] == "active"
    assert booking["start_time"] == at(10)
    assert count("booking_slots") == 3


def test_naive_times_are_read_as_office_time(db):
    booking = book(start=at(10).replace(tzinfo=None), end=at(11).replace(tzinfo=None))
    assert booking["start_time"] == at(10)


def test_back_to_back_booking_at_11_30_is_allowed(db):
    book(start=at(10), end=at(11, 30))
    book(username="User2", start=at(11, 30), end=at(12))
    assert count("bookings") == 2


def test_overlapping_booking_is_rejected_and_nothing_is_saved(db):
    book(start=at(10), end=at(11, 30))
    with pytest.raises(SlotConflict):
        book(username="User2", start=at(11), end=at(12))
    assert count("bookings") == 1
    assert count("booking_slots") == 3


def test_same_time_in_another_room_is_allowed(db):
    book(room="A")
    book(room="B")
    assert count("bookings") == 2


def test_rule_violation_saves_nothing(db):
    with pytest.raises(InvalidBooking):
        book(room="A", attendees=8)
    assert count("bookings") == 0


def test_cannot_cancel_another_users_booking(db):
    booking = book(username="User1")
    with pytest.raises(NotBookingOwner):
        cancel_booking(user_id("User2"), booking["id"])


def test_cancel_frees_the_slots(db):
    booking = book(start=at(10), end=at(11))
    cancelled = cancel_booking(user_id("User1"), booking["id"])
    assert cancelled["status"] == "cancelled"
    book(username="User2", start=at(10), end=at(11))


def test_cancel_unknown_or_already_cancelled_booking(db):
    with pytest.raises(BookingNotFound):
        cancel_booking(user_id("User1"), 999)
    booking = book()
    cancel_booking(user_id("User1"), booking["id"])
    with pytest.raises(BookingNotFound):
        cancel_booking(user_id("User1"), booking["id"])


def test_list_my_bookings_shows_only_my_active_unfinished_bookings(db):
    mine = book(username="User1", room="A", start=at(10), end=at(11))
    cancelled = book(username="User1", room="B", start=at(10), end=at(11))
    cancel_booking(user_id("User1"), cancelled["id"])
    book(username="User2", room="C", start=at(10), end=at(11))
    # A finished booking can't be created through the service, so it is inserted directly.
    yesterday = at(10) - timedelta(days=2)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO bookings (user_id, room, title, attendees, start_time, end_time)"
            " VALUES (%s, 'D', 'Old', 2, %s, %s)",
            (user_id("User1"), yesterday, yesterday + timedelta(hours=1)),
        )

    assert [b["id"] for b in list_my_bookings(user_id("User1"))] == [mine["id"]]


def available(start, end, attendees=None) -> list[str]:
    return [r["room"] for r in list_available_rooms(start, end, attendees)]


def test_booked_room_is_not_available_in_its_range(db):
    book(room="A", start=at(10), end=at(11))
    assert available(at(10), at(11)) == ["B", "C", "D", "E"]


def test_room_is_available_right_after_a_booking_ends(db):
    book(room="A", start=at(10), end=at(11))
    assert available(at(11), at(12)) == ["A", "B", "C", "D", "E"]


def test_partial_overlap_makes_room_unavailable(db):
    book(room="A", start=at(10), end=at(11))
    assert "A" not in available(at(10, 30), at(11, 30))


def test_available_rooms_filter_by_capacity(db):
    assert available(at(10), at(11), attendees=8) == ["E"]
    assert available(at(10), at(11), attendees=11) == []


def test_cancelled_booking_makes_room_available_again(db):
    booking = book(room="A", start=at(10), end=at(11))
    cancel_booking(user_id("User1"), booking["id"])
    assert "A" in available(at(10), at(11))


def test_room_schedule_marks_free_and_taken_slots(db):
    book(room="A", start=at(10), end=at(11))
    schedule = get_room_schedule("A", at(9, 30), at(11, 30))
    assert [s["start"] for s in schedule] == [at(9, 30), at(10), at(10, 30), at(11)]
    assert [s["available"] for s in schedule] == [True, False, False, True]
    assert schedule[0]["end"] == at(10)


def test_room_schedule_rejects_unknown_room(db):
    with pytest.raises(InvalidBooking):
        get_room_schedule("F", at(10), at(11))
