class BookingError(Exception):
    """Base domain error. `code` is a stable identifier the agent can act on."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class InvalidBooking(BookingError):
    pass


class SlotConflict(BookingError):
    pass


class BookingNotFound(BookingError):
    pass


class NotBookingOwner(BookingError):
    pass
