"""Domain exceptions. Each one carries a `code` the tools return to the agent."""


class BookingError(Exception):
    """Base domain error. `code` is a stable identifier the agent can act on."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class InvalidBooking(BookingError):
    """A booking rule was broken (room, time, duration, attendees, title or past start)."""


class SlotConflict(BookingError):
    """At least one requested slot is already taken."""


class BookingNotFound(BookingError):
    """No active booking exists with that id."""


class NotBookingOwner(BookingError):
    """The booking belongs to another user."""
