from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.exceptions import InvalidBooking
from app.rules import generate_slots, validate_booking, validate_range

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


def test_slots_exclude_the_end_time():
    assert generate_slots(at(10), at(11, 30)) == [at(10), at(10, 30), at(11)]


def test_slot_count_for_min_and_max_duration():
    assert len(generate_slots(at(10), at(10, 30))) == 1
    assert len(generate_slots(at(10), at(13))) == 6


def test_back_to_back_bookings_share_no_slots():
    first = set(generate_slots(at(10), at(11, 30)))
    second = set(generate_slots(at(11, 30), at(12)))
    assert first.isdisjoint(second)


def test_overlapping_bookings_share_a_slot():
    first = set(generate_slots(at(10), at(11, 30)))
    second = set(generate_slots(at(11), at(12)))
    assert first & second == {at(11)}


def test_range_longer_than_three_hours_is_allowed_for_queries():
    validate_range(at(9), at(14))


def test_misaligned_range_is_rejected():
    with pytest.raises(InvalidBooking) as error:
        validate_range(at(9, 15), at(10))
    assert error.value.code == "misaligned_time"


def test_inverted_range_is_rejected():
    with pytest.raises(InvalidBooking) as error:
        validate_range(at(11), at(10))
    assert error.value.code == "invalid_range"


def test_booking_at_opening_and_closing_time_is_allowed():
    book(start=at(8), end=at(9))
    book(start=at(17), end=at(18))


@pytest.mark.parametrize("start,end", [
    (at(7, 30), at(9)),     # starts before opening
    (at(17), at(18, 30)),   # ends after closing
    (at(6), at(8)),         # ends right at opening, but starts before
])
def test_booking_outside_office_hours_is_rejected(start, end):
    assert_rejected("outside_office_hours", start=start, end=end)


@pytest.mark.parametrize("day", [17, 18])  # Saturday and Sunday
def test_weekend_booking_is_rejected(day):
    saturday_or_sunday = datetime(2026, 10, day, 10, 0, tzinfo=TZ)
    assert_rejected("closed_day", start=saturday_or_sunday, end=saturday_or_sunday.replace(hour=11))


def test_query_outside_office_hours_is_rejected():
    with pytest.raises(InvalidBooking) as error:
        validate_range(at(3), at(4))
    assert error.value.code == "outside_office_hours"


def test_query_running_into_the_next_day_is_rejected():
    with pytest.raises(InvalidBooking) as error:
        validate_range(at(8), at(8) + timedelta(days=1))
    assert error.value.code == "outside_office_hours"


def test_weekend_query_is_rejected():
    saturday = datetime(2026, 10, 17, 8, 0, tzinfo=TZ)
    with pytest.raises(InvalidBooking) as error:
        validate_range(saturday, saturday.replace(hour=18))
    assert error.value.code == "closed_day"
