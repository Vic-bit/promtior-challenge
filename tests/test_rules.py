from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.exceptions import InvalidBooking
from app.rules import validate_booking

TZ = ZoneInfo("America/Montevideo")
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=TZ)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 16, hour, minute, tzinfo=TZ)


def book(room="A", start=None, end=None, title="Team sync", attendees=3, now=NOW):
    validate_booking(room, start or at(10), end or at(11), title, attendees, now)


def assert_rejected(code: str, **kwargs):
    with pytest.raises(InvalidBooking) as error:
        book(**kwargs)
    assert error.value.code == code


def test_valid_booking_passes():
    book()


def test_exactly_three_hours_is_allowed():
    book(start=at(10), end=at(13))


def test_three_hours_and_a_half_is_rejected():
    assert_rejected("invalid_duration", start=at(10), end=at(13, 30))


def test_single_slot_is_allowed():
    book(start=at(10), end=at(10, 30))


def test_end_before_or_equal_to_start_is_rejected():
    assert_rejected("invalid_duration", start=at(10), end=at(10))
    assert_rejected("invalid_duration", start=at(11), end=at(10))


@pytest.mark.parametrize("start,end", [(at(10, 15), at(11)), (at(10), at(11, 45))])
def test_misaligned_times_are_rejected(start, end):
    assert_rejected("misaligned_time", start=start, end=end)


def test_seconds_are_rejected():
    assert_rejected("misaligned_time", start=at(10).replace(second=30))


def test_attendees_up_to_capacity_are_allowed():
    book(room="A", attendees=7)
    book(room="E", attendees=10)


def test_attendees_over_capacity_are_rejected():
    assert_rejected("capacity_exceeded", room="A", attendees=8)
    assert_rejected("capacity_exceeded", room="E", attendees=11)


def test_zero_attendees_is_rejected():
    assert_rejected("invalid_attendees", attendees=0)


def test_unknown_room_is_rejected():
    assert_rejected("invalid_room", room="F")


@pytest.mark.parametrize("title", ["", "   "])
def test_empty_title_is_rejected(title):
    assert_rejected("empty_title", title=title)


def test_start_in_the_past_is_rejected():
    assert_rejected("start_in_past", now=at(10, 30))


def test_start_exactly_now_is_allowed():
    book(now=at(10))
