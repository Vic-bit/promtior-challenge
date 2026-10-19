"""Pure booking rules: no database, no LLM. Every violation raises InvalidBooking."""

from datetime import datetime, time, timedelta

from app.exceptions import InvalidBooking

ROOM_CAPACITY = {"A": 7, "B": 7, "C": 7, "D": 7, "E": 10}
SLOT_MINUTES = 30
SLOT_DURATION = timedelta(minutes=SLOT_MINUTES)
MIN_DURATION = SLOT_DURATION
MAX_DURATION = timedelta(hours=3)
OFFICE_OPEN = time(8, 0)
OFFICE_CLOSE = time(18, 0)


def validate_room(room: str) -> None:
    if room not in ROOM_CAPACITY:
        raise InvalidBooking("invalid_room", f"Room {room!r} does not exist. Valid rooms: A, B, C, D, E.")


def validate_title(title: str) -> None:
    if not title or not title.strip():
        raise InvalidBooking("empty_title", "A booking must have a title.")


def validate_attendees(room: str, attendees: int) -> None:
    """Require between 1 attendee and the room's capacity."""
    if attendees < 1:
        raise InvalidBooking("invalid_attendees", "A booking needs at least 1 attendee.")
    capacity = ROOM_CAPACITY[room]
    if attendees > capacity:
        raise InvalidBooking(
            "capacity_exceeded",
            f"Room {room} holds up to {capacity} people, but {attendees} were requested.",
        )


def validate_alignment(moment: datetime) -> None:
    """Require the time to fall exactly on :00 or :30, with no seconds."""
    if moment.minute not in (0, SLOT_MINUTES) or moment.second or moment.microsecond:
        raise InvalidBooking("misaligned_time", f"{moment:%H:%M} is not on a 30-minute boundary (:00 or :30).")


def validate_duration(start: datetime, end: datetime) -> None:
    """Require a booking length between 30 minutes and 3 hours."""
    duration = end - start
    if duration < MIN_DURATION or duration > MAX_DURATION:
        raise InvalidBooking("invalid_duration", "A booking must last between 30 minutes and 3 hours.")


def validate_not_in_past(start: datetime, now: datetime) -> None:
    """Reject bookings starting before `now`.

    `now` is a parameter so the rule stays pure and testable at any time of day.
    """
    if start < now:
        raise InvalidBooking("start_in_past", "A booking cannot start in the past.")


def validate_office_hours(start: datetime, end: datetime) -> None:
    """Require the whole range on a weekday, between OFFICE_OPEN and OFFICE_CLOSE."""
    if start.weekday() >= 5:
        raise InvalidBooking("closed_day", "The office is open Monday to Friday.")
    if start.time() < OFFICE_OPEN or end.time() > OFFICE_CLOSE or end.date() != start.date():
        raise InvalidBooking(
            "outside_office_hours",
            f"The office is open from {OFFICE_OPEN:%H:%M} to {OFFICE_CLOSE:%H:%M}.",
        )


def validate_booking_time(start: datetime, end: datetime, now: datetime) -> None:
    """Run the time rules of a booking: alignment, duration, office hours and not in the past."""
    validate_alignment(start)
    validate_alignment(end)
    validate_duration(start, end)
    validate_office_hours(start, end)
    validate_not_in_past(start, now)


def validate_booking(room: str, start: datetime, end: datetime, title: str, attendees: int, now: datetime) -> None:
    """Run every booking rule; raise InvalidBooking on the first one that fails."""
    # Room goes first because the attendee check needs its capacity.
    validate_room(room)
    validate_title(title)
    validate_attendees(room, attendees)
    validate_booking_time(start, end, now)


def validate_range(start: datetime, end: datetime) -> None:
    """Validate a query range (availability, schedule).

    Same alignment and office hours as bookings, but no 3-hour cap and no past check:
    querying is not booking.
    """
    validate_alignment(start)
    validate_alignment(end)
    if end <= start:
        raise InvalidBooking("invalid_range", "The end time must be after the start time.")
    validate_office_hours(start, end)


def generate_slots(start: datetime, end: datetime) -> list[datetime]:
    """Return the start of every 30-minute slot in [start, end).

    The range is half-open: `end` is never a slot, so back-to-back bookings don't collide.
    """
    slots = []
    current = start
    while current < end:
        slots.append(current)
        current += SLOT_DURATION
    return slots
