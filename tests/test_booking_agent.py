import json
from datetime import datetime, time, timedelta
from string import Formatter
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage

from app.booking_agent import PROMPTS, booking_agent, system_prompt
from app.booking_agent_tools import (
    SUGGESTIONS,
    cancel_booking,
    create_booking,
    get_room_schedule,
    list_available_rooms,
    list_my_bookings,
)
from app.db import get_conn

TZ = ZoneInfo("America/Montevideo")


def at(hour: int, minute: int = 0) -> str:
    """Tomorrow at the given time, as the ISO string the LLM would send."""
    tomorrow = datetime.now(TZ).date() + timedelta(days=1)
    return datetime.combine(tomorrow, time(hour, minute)).isoformat()


def config_for(username: str) -> dict:
    with get_conn() as conn:
        user = conn.execute("SELECT id FROM users WHERE username = %s", (username,)).fetchone()
    return {"configurable": {"user_id": user["id"]}}


def book(username="User1", room="A", start=None, end=None) -> dict:
    args = {"room": room, "start": start or at(10), "end": end or at(11), "title": "Team sync", "attendees": 3}
    return create_booking.invoke(args, config=config_for(username))


def test_every_error_code_has_a_suggestion():
    codes = {
        "invalid_datetime", "invalid_room", "empty_title", "invalid_attendees", "capacity_exceeded",
        "misaligned_time", "invalid_duration", "start_in_past", "invalid_range", "slot_conflict",
        "booking_not_found", "not_booking_owner",
    }
    assert codes == set(SUGGESTIONS)


def test_user_id_is_not_visible_to_the_llm():
    for t in (create_booking, list_my_bookings, cancel_booking):
        assert "config" not in t.tool_call_schema.model_json_schema()["properties"]


def test_create_booking_returns_iso_dates(db):
    result = book(start=at(10), end=at(11))
    assert result["ok"] is True
    assert result["booking"]["start_time"].startswith(at(10))
    assert result["booking"]["start_time"].endswith("-03:00")


def test_conflict_returns_structured_error(db):
    book(start=at(10), end=at(11))
    result = book(username="User2", start=at(10, 30), end=at(11, 30))
    assert result == {
        "ok": False,
        "error": "slot_conflict",
        "detail": result["detail"],
        "suggestions": [SUGGESTIONS["slot_conflict"]],
    }


def test_invalid_date_returns_structured_error(db):
    result = book(start="mañana a las 10")
    assert result["ok"] is False
    assert result["error"] == "invalid_datetime"


def test_cancel_uses_the_user_from_config(db):
    booking_id = book(username="User1")["booking"]["id"]
    result = cancel_booking.invoke({"booking_id": booking_id}, config=config_for("User2"))
    assert result["error"] == "not_booking_owner"
    result = cancel_booking.invoke({"booking_id": booking_id}, config=config_for("User1"))
    assert result["ok"] is True
    assert result["booking"]["status"] == "cancelled"


def test_list_my_bookings_tool(db):
    book(username="User1", room="A")
    book(username="User2", room="B")
    result = list_my_bookings.invoke({}, config=config_for("User1"))
    assert [b["room"] for b in result["bookings"]] == ["A"]


def test_list_available_rooms_tool(db):
    book(room="A", start=at(10), end=at(11))
    result = list_available_rooms.invoke({"start": at(10), "end": at(11), "attendees": 8})
    assert result == {"ok": True, "rooms": [{"room": "E", "capacity": 10}]}


def test_get_room_schedule_tool(db):
    book(room="A", start=at(10), end=at(10, 30))
    result = get_room_schedule.invoke({"room": "A", "start": at(9, 30), "end": at(10, 30)})
    assert [s["available"] for s in result["slots"]] == [True, False]


def test_system_prompt_includes_current_date_and_weekday():
    prompt = system_prompt(datetime(2026, 10, 15, 9, 0, tzinfo=TZ))
    assert "jueves 2026-10-15 09:00" in prompt
    assert "America/Montevideo" in prompt
    assert "- jueves 15/10 (hoy): 2026-10-15" in prompt
    assert "- viernes 16/10 (mañana): 2026-10-16" in prompt
    assert "- domingo 18/10: 2026-10-18" in prompt


class FakeModel:
    """Stands in for Groq: returns the given replies in order, so the graph runs without an LLM."""

    def __init__(self, replies):
        self.replies = iter(replies)

    def invoke(self, messages):
        return next(self.replies)


def test_graph_runs_the_requested_tool_with_the_user_from_config(db, monkeypatch):
    book(username="User1", room="A")
    tool_call = AIMessage("", tool_calls=[{"name": "list_my_bookings", "args": {}, "id": "call_1"}])
    monkeypatch.setattr("app.booking_agent.model", FakeModel([tool_call, AIMessage("Tienes una reserva en la sala A.")]))

    config = {"configurable": {"thread_id": "test", **config_for("User1")["configurable"]}}
    result = booking_agent.invoke({"messages": [HumanMessage("¿Qué reservas tengo?")]}, config)

    tool_result = json.loads(result["messages"][2].content)
    assert [b["room"] for b in tool_result["bookings"]] == ["A"]
    assert result["messages"][-1].content == "Tienes una reserva en la sala A."


def test_prompt_variables_match_its_placeholders():
    spec = PROMPTS["booking_agent_prompt"]
    placeholders = {name for _, name, _, _ in Formatter().parse(spec["prompt"]) if name}
    assert placeholders == set(spec["variables"])


def test_graph_is_named_booking_agent():
    assert booking_agent.name == "booking_agent"
