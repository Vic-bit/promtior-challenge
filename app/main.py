"""FastAPI application: HTTP endpoints."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.agent import booking_agent
from app.auth import create_token, get_current_user, verify_password
from app.db import get_conn, init_db

# Python only shows WARNING and above by default; INFO lets us see the agent's tool calls.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepare the database before the app starts serving requests."""
    init_db()
    yield


app = FastAPI(title="Meeting Room Booking", lifespan=lifespan)


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1)


def log_tool_calls(messages: list) -> None:
    """Log the tools the agent called in this turn and the start of each result."""
    # This turn is everything after the user's last message; earlier ones are memory.
    last_user = max(i for i, m in enumerate(messages) if m.type == "human")
    for message in messages[last_user + 1:]:
        if message.type == "ai":
            for call in message.tool_calls:
                logger.info("tool call %s %s", call["name"], call["args"])
        elif message.type == "tool":
            logger.info("tool result %s", message.content[:300])


@app.get("/health")
def health() -> dict:
    """Liveness check for the deploy platform."""
    return {"status": "ok"}


@app.post("/auth/login")
def login(body: LoginRequest) -> dict:
    """Exchange username and password for a JWT access token."""
    with get_conn() as conn:
        user = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = %s",
            (body.username,),
        ).fetchone()
    # Same error for an unknown user and a wrong password, so the API doesn't reveal which users exist.
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    return {"access_token": create_token(user["id"], user["username"]), "token_type": "bearer"}


@app.post("/chat")
def chat(body: ChatRequest, user: dict = Depends(get_current_user)) -> dict:
    """Send a message to the booking agent and return its reply."""
    # user_id comes from the token, never from the body; thread_id keeps each user's memory apart.
    config = {"configurable": {"thread_id": f"{user['id']}:{body.session_id}", "user_id": user["id"]}}
    try:
        result = booking_agent.invoke({"messages": [HumanMessage(body.message)]}, config)
    except Exception:
        # Any LLM provider failure (quota, network, bad key) becomes a clear 503; details go to the log.
        logger.exception("Agent failed")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The assistant is not available right now. Please try again.",
        )
    log_tool_calls(result["messages"])
    return {"reply": result["messages"][-1].content}
