from datetime import datetime, timedelta

from app.exceptions import InvalidBooking

ROOM_CAPACITY = {"A": 7, "B": 7, "C": 7, "D": 7, "E": 10}
SLOT_MINUTES = 30
SLOT_DURATION = timedelta(minutes=SLOT_MINUTES)
MIN_DURATION = SLOT_DURATION
MAX_DURATION = timedelta(hours=3)


def validate_room(room: str) -> None:
    if room not in ROOM_CAPACITY:
        raise InvalidBooking("invalid_room", f"Room {room!r} does not exist. Valid rooms: A, B, C, D, E.")


def validate_title(title: str) -> None:
    if not title or not title.strip():
        raise InvalidBooking("empty_title", "A booking must have a title.")


def validate_attendees(room: str, attendees: int) -> None:
    if attendees < 1:
        raise InvalidBooking("invalid_attendees", "A booking needs at least 1 attendee.")
    capacity = ROOM_CAPACITY[room]
    if attendees > capacity:
        raise InvalidBooking(
            "capacity_exceeded",
            f"Room {room} holds up to {capacity} people, but {attendees} were requested.",
        )


def validate_alignment(moment: datetime) -> None:
    if moment.minute not in (0, SLOT_MINUTES) or moment.second or moment.microsecond:
        raise InvalidBooking("misaligned_time", f"{moment:%H:%M} is not on a 30-minute boundary (:00 or :30).")


def validate_duration(start: datetime, end: datetime) -> None:
    duration = end - start
    if duration < MIN_DURATION or duration > MAX_DURATION:
        raise InvalidBooking("invalid_duration", "A booking must last between 30 minutes and 3 hours.")


def validate_not_in_past(start: datetime, now: datetime) -> None:
    # `now` is a parameter so the rule stays pure and testable at any time of day.
    if start < now:
        raise InvalidBooking("start_in_past", "A booking cannot start in the past.")


def validate_booking(room: str, start: datetime, end: datetime, title: str, attendees: int, now: datetime) -> None:
    # Room goes first because the attendee check needs its capacity.
    validate_room(room)
    validate_title(title)
    validate_attendees(room, attendees)
    validate_alignment(start)
    validate_alignment(end)
    validate_duration(start, end)
    validate_not_in_past(start, now)


def validate_range(start: datetime, end: datetime) -> None:
    # For queries (availability, schedule): same alignment as bookings, but no 3-hour cap.
    validate_alignment(start)
    validate_alignment(end)
    if end <= start:
        raise InvalidBooking("invalid_range", "The end time must be after the start time.")


def generate_slots(start: datetime, end: datetime) -> list[datetime]:
    # Half-open range [start, end): `end` is never a slot, so back-to-back bookings don't collide.
    slots = []
    current = start
    while current < end:
        slots.append(current)
        current += SLOT_DURATION
    return slots
