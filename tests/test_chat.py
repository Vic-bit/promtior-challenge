import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.booking import create_booking
from app.booking_agent import booking_agent
from app.db import get_conn
from app.main import app

TZ = ZoneInfo("America/Montevideo")

PASSWORD = "TechnicalChallengePromtior"


class FakeModel:
    """Stands in for Groq: returns the given replies in order, so /chat runs without an LLM."""

    def __init__(self, replies):
        self.replies = iter(replies)

    def invoke(self, messages):
        return next(self.replies)


class FailingModel:
    def invoke(self, messages):
        raise RuntimeError("Groq is down")


@pytest.fixture
def client(db):
    with TestClient(app) as client:
        yield client


def auth_header(client, username: str) -> dict:
    token = client.post("/auth/login", json={"username": username, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def send(client, username: str, message: str = "Hola", session_id: str = "s1"):
    return client.post("/chat", json={"message": message, "session_id": session_id}, headers=auth_header(client, username))


def test_chat_requires_a_token(client):
    response = client.post("/chat", json={"message": "Hola", "session_id": "s1"})
    assert response.status_code == 401


def test_chat_returns_the_agent_reply(client, monkeypatch):
    monkeypatch.setattr("app.booking_agent.model", FakeModel([AIMessage("¡Hola! ¿En qué te ayudo?")]))
    response = send(client, "User1")
    assert response.status_code == 200
    assert response.json() == {"reply": "¡Hola! ¿En qué te ayudo?"}


def test_tools_run_as_the_user_from_the_token(client, monkeypatch):
    # User2 books a room; User1 asks for their bookings and must not see it.
    create = AIMessage("", tool_calls=[{
        "name": "create_booking", "id": "c1",
        "args": {"room": "A", "start": "2099-01-01T10:00", "end": "2099-01-01T11:00", "title": "Sync", "attendees": 2},
    }])
    monkeypatch.setattr("app.booking_agent.model", FakeModel([create, AIMessage("Reservada.")]))
    send(client, "User2", session_id="u2")

    listing = AIMessage("", tool_calls=[{"name": "list_my_bookings", "id": "c2", "args": {}}])
    monkeypatch.setattr("app.booking_agent.model", FakeModel([listing, AIMessage("No tienes reservas.")]))
    send(client, "User1", session_id="u1")

    state = booking_agent.get_state({"configurable": {"thread_id": "1:u1"}})
    assert json.loads(state.values["messages"][-2].content)["bookings"] == []


def test_agent_failure_returns_503(client, monkeypatch):
    monkeypatch.setattr("app.booking_agent.model", FailingModel())
    response = send(client, "User1")
    assert response.status_code == 503
    assert response.json()["detail"] == "The assistant is not available right now. Please try again."


def test_empty_message_is_rejected(client):
    response = send(client, "User1", message="")
    assert response.status_code == 422


def test_tool_calls_are_logged(client, monkeypatch, caplog):
    listing = AIMessage("", tool_calls=[{"name": "list_my_bookings", "id": "c1", "args": {}}])
    monkeypatch.setattr("app.booking_agent.model", FakeModel([listing, AIMessage("No tienes reservas.")]))
    with caplog.at_level("INFO", logger="app.main"):
        send(client, "User1", session_id="logs")
    assert "tool call list_my_bookings {}" in caplog.text
    assert 'tool result {"ok": true, "bookings": []}' in caplog.text


def next_weekday() -> date:
    day = datetime.now(TZ).date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def test_schedule_requires_a_token(client):
    assert client.get("/schedule", params={"day": str(next_weekday())}).status_code == 401


def test_schedule_shows_every_room_and_the_taken_slots(client):
    day = next_weekday()
    with get_conn() as conn:
        user1 = conn.execute("SELECT id FROM users WHERE username = 'User1'").fetchone()["id"]
    create_booking(user1, "B", datetime.combine(day, time(10)), datetime.combine(day, time(11)), "Sync", 2)

    data = client.get("/schedule", params={"day": str(day)}, headers=auth_header(client, "User1")).json()

    assert data["open"] is True
    assert [r["room"] for r in data["rooms"]] == ["A", "B", "C", "D", "E"]
    room_b = {s["time"]: s["state"] for s in data["rooms"][1]["slots"]}
    assert len(room_b) == 20  # 08:00 to 17:30
    assert room_b["09:30"] == "free"
    assert room_b["10:00"] == "mine" and room_b["10:30"] == "mine"
    assert room_b["11:00"] == "free"


def test_schedule_on_a_weekend_is_closed(client):
    saturday = date(2026, 10, 24)
    data = client.get("/schedule", params={"day": str(saturday)}, headers=auth_header(client, "User1")).json()
    assert data == {"day": "2026-10-24", "open": False, "rooms": []}


def test_schedule_tells_my_bookings_from_other_users(client):
    day = next_weekday()
    with get_conn() as conn:
        ids = {r["username"]: r["id"] for r in conn.execute("SELECT id, username FROM users").fetchall()}
    create_booking(ids["User1"], "A", datetime.combine(day, time(10)), datetime.combine(day, time(11)), "Mine", 2)
    create_booking(ids["User2"], "B", datetime.combine(day, time(10)), datetime.combine(day, time(11)), "Theirs", 2)

    def state_at_10(username: str) -> dict:
        data = client.get("/schedule", params={"day": str(day)}, headers=auth_header(client, username)).json()
        return {r["room"]: r["slots"][4]["state"] for r in data["rooms"]}  # slot 4 = 10:00

    assert state_at_10("User1") == {"A": "mine", "B": "taken", "C": "free", "D": "free", "E": "free"}
    assert state_at_10("User2") == {"A": "taken", "B": "mine", "C": "free", "D": "free", "E": "free"}
