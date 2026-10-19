"""Agent tools: thin adapters between the LLM and the booking service."""

from datetime import datetime
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app import booking
from app.exceptions import BookingError, InvalidBooking

Room = Literal["A", "B", "C", "D", "E"]

# Fixed hint per error code, so the agent knows its next step without extra logic here.
SUGGESTIONS = {
    "invalid_datetime": "Usa formato ISO 8601, por ejemplo 2026-10-17T10:00.",
    "invalid_room": "Las salas válidas son A, B, C, D y E.",
    "empty_title": "Pide al usuario un título para la reserva.",
    "invalid_attendees": "Pide al usuario cuántas personas asisten (mínimo 1).",
    "capacity_exceeded": "Usa list_available_rooms con attendees para encontrar una sala con capacidad suficiente.",
    "misaligned_time": "Ofrece el horario más cercano que empiece en :00 o :30.",
    "invalid_duration": "La reserva debe durar entre 30 minutos y 3 horas; ofrece ajustar el horario.",
    "start_in_past": "Pide al usuario una fecha y hora futuras.",
    "outside_office_hours": "Ofrece un horario dentro del horario de la oficina.",
    "closed_day": "La oficina abre de lunes a viernes; ofrece el día hábil más cercano.",
    "invalid_range": "La hora de fin debe ser posterior a la de inicio.",
    "slot_conflict": "Usa list_available_rooms o get_room_schedule para ofrecer otra sala u horario.",
    "booking_not_found": "Usa list_my_bookings para ver las reservas activas del usuario.",
    "not_booking_owner": "Solo se pueden cancelar reservas propias; usa list_my_bookings para ver las del usuario.",
}


def parse(value: str) -> datetime:
    """Parse an ISO 8601 string sent by the LLM."""
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise InvalidBooking("invalid_datetime", f"{value!r} is not an ISO 8601 date-time.")


def to_json(row: dict) -> dict:
    """Return a copy of a row with datetimes as short ISO strings, since JSON has no date type.

    "2026-10-18T10:00" instead of "2026-10-18T10:00:00-03:00": seconds are always zero and every
    time is office time, so the short form says the same with fewer tokens.
    """
    return {
        key: value.strftime("%Y-%m-%dT%H:%M") if isinstance(value, datetime) else value
        for key, value in row.items()
    }


def group_slots(slots: list[dict]) -> list[dict]:
    """Merge back-to-back slots with the same availability into ranges, so a day fits in a few lines."""
    ranges = []
    for slot in slots:
        if ranges and ranges[-1]["available"] == slot["available"]:
            ranges[-1]["end"] = slot["end"]
        else:
            ranges.append(dict(slot))
    return ranges


def error(exc: BookingError) -> dict:
    return {"ok": False, "error": exc.code, "detail": exc.detail, "suggestions": [SUGGESTIONS[exc.code]]}


def user_id(config: RunnableConfig) -> int:
    # Comes from the JWT through /chat. It is never a tool argument, so the LLM can't change it.
    return config["configurable"]["user_id"]


@tool
def list_available_rooms(start: str, end: str, attendees: int | None = None) -> dict:
    """Lista las salas libres durante todo el rango [start, end).

    start y end son fechas ISO 8601 en hora de la oficina, por ejemplo 2026-10-17T10:00.
    Deben caer en :00 o :30. Si el usuario dijo cuántas personas asisten, pásalo en
    attendees para recibir solo las salas con capacidad suficiente.
    """
    try:
        return {"ok": True, "rooms": booking.list_available_rooms(parse(start), parse(end), attendees)}
    except BookingError as exc:
        return error(exc)


@tool
def get_room_schedule(room: Room, start: str, end: str) -> dict:
    """Muestra la agenda de una sala en [start, end) como franjas seguidas libres u ocupadas.

    start y end son fechas ISO 8601 en hora de la oficina, por ejemplo 2026-10-17T09:00.
    Deben caer en :00 o :30.
    """
    try:
        slots = booking.get_room_schedule(room, parse(start), parse(end))
        return {"ok": True, "room": room, "ranges": [to_json(r) for r in group_slots(slots)]}
    except BookingError as exc:
        return error(exc)


@tool
def create_booking(room: Room, start: str, end: str, title: str, attendees: int, config: RunnableConfig) -> dict:
    """Crea una reserva a nombre del usuario actual.

    start y end son fechas ISO 8601 en hora de la oficina, por ejemplo 2026-10-17T10:00.
    Deben caer en :00 o :30 y la duración va de 30 minutos a 3 horas.
    Todos los argumentos deben venir de lo que dijo el usuario: sala, horario, título y
    asistentes. Si falta alguno, pregúntalo; nunca uses valores de relleno.
    Llámala solo después de que el usuario confirme el resumen de la reserva.
    """
    try:
        created = booking.create_booking(user_id(config), room, parse(start), parse(end), title, attendees)
        return {"ok": True, "booking": to_json(created)}
    except BookingError as exc:
        return error(exc)


@tool
def list_my_bookings(config: RunnableConfig) -> dict:
    """Lista las reservas activas del usuario actual que todavía no terminaron, con su id."""
    bookings = booking.list_my_bookings(user_id(config))
    return {"ok": True, "bookings": [to_json(b) for b in bookings]}


@tool
def cancel_booking(booking_id: int, config: RunnableConfig) -> dict:
    """Cancela una reserva del usuario actual por su id.

    Si no conoces el id, usa list_my_bookings primero.
    Llámala solo después de que el usuario confirme qué reserva cancelar.
    """
    try:
        cancelled = booking.cancel_booking(user_id(config), booking_id)
        return {"ok": True, "booking": to_json(cancelled)}
    except BookingError as exc:
        return error(exc)


TOOLS = [list_available_rooms, get_room_schedule, create_booking, list_my_bookings, cancel_booking]
