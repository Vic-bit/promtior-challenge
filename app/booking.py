"""Booking service: applies the rules, runs the SQL and raises domain exceptions."""

from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg

from app.config import settings
from app.db import get_conn
from app.exceptions import BookingNotFound, NotBookingOwner, SlotConflict
from app.rules import (
    ROOM_CAPACITY,
    SLOT_DURATION,
    generate_slots,
    validate_booking,
    validate_range,
    validate_room,
)

TZ = ZoneInfo(settings.timezone)


def to_local(moment: datetime) -> datetime:
    """Convert a datetime to office time.

    The LLM may send "2026-10-16T10:00" with no offset: it is read as office time.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=TZ)
    return moment.astimezone(TZ)


def create_booking(user_id: int, room: str, start: datetime, end: datetime, title: str, attendees: int) -> dict:
    """Validate and save a booking with one row per 30-minute slot; raise SlotConflict if any slot is taken."""
    start, end, title = to_local(start), to_local(end), title.strip()
    validate_booking(room, start, end, title, attendees, now=datetime.now(TZ))

    try:
        # Booking and slots go in one transaction: if any slot is taken, nothing is saved.
        with get_conn() as conn:
            booking = conn.execute(
                "INSERT INTO bookings (user_id, room, title, attendees, start_time, end_time)"
                " VALUES (%s, %s, %s, %s, %s, %s)"
                " RETURNING id, room, title, attendees, start_time, end_time, status",
                (user_id, room, title, attendees, start, end),
            ).fetchone()
            for slot in generate_slots(start, end):
                conn.execute(
                    "INSERT INTO booking_slots (booking_id, room, slot_start) VALUES (%s, %s, %s)",
                    (booking["id"], room, slot),
                )
    except psycopg.errors.UniqueViolation:
        raise SlotConflict(
            "slot_conflict",
            f"Room {room} is already booked for part of {start:%Y-%m-%d %H:%M}-{end:%H:%M}.",
        )
    return booking


def cancel_booking(user_id: int, booking_id: int) -> dict:
    """Cancel an active booking owned by the user and free its slots."""
    with get_conn() as conn:
        booking = conn.execute(
            "SELECT user_id FROM bookings WHERE id = %s AND status = 'active'",
            (booking_id,),
        ).fetchone()
        if booking is None:
            raise BookingNotFound("booking_not_found", f"There is no active booking with id {booking_id}.")
        if booking["user_id"] != user_id:
            raise NotBookingOwner("not_booking_owner", "You can only cancel your own bookings.")

        cancelled = conn.execute(
            "UPDATE bookings SET status = 'cancelled' WHERE id = %s"
            " RETURNING id, room, title, attendees, start_time, end_time, status",
            (booking_id,),
        ).fetchone()
        conn.execute("DELETE FROM booking_slots WHERE booking_id = %s", (booking_id,))
    return cancelled


def list_my_bookings(user_id: int) -> list[dict]:
    """Return the user's active bookings that have not ended yet, earliest first."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, room, title, attendees, start_time, end_time, status FROM bookings"
            " WHERE user_id = %s AND status = 'active' AND end_time > now()"
            " ORDER BY start_time",
            (user_id,),
        ).fetchall()


def list_available_rooms(start: datetime, end: datetime, attendees: int | None = None) -> list[dict]:
    """Return rooms with every slot free in [start, end), optionally only those that fit the attendees."""
    start, end = to_local(start), to_local(end)
    validate_range(start, end)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT room FROM booking_slots WHERE slot_start >= %s AND slot_start < %s",
            (start, end),
        ).fetchall()
    busy = {row["room"] for row in rows}
    return [
        {"room": room, "capacity": capacity}
        for room, capacity in ROOM_CAPACITY.items()
        if room not in busy and (attendees is None or capacity >= attendees)
    ]


def get_room_schedule(room: str, start: datetime, end: datetime) -> list[dict]:
    """Return each 30-minute slot of the room in [start, end) marked as available or not."""
    start, end = to_local(start), to_local(end)
    validate_room(room)
    validate_range(start, end)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT slot_start FROM booking_slots WHERE room = %s AND slot_start >= %s AND slot_start < %s",
            (room, start, end),
        ).fetchall()
    taken = {row["slot_start"] for row in rows}
    return [
        {"start": slot, "end": slot + SLOT_DURATION, "available": slot not in taken}
        for slot in generate_slots(start, end)
    ]
