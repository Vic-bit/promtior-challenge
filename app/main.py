from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from app.auth import create_token, verify_password
from app.db import get_conn, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Meeting Room Booking", lifespan=lifespan)


class LoginRequest(BaseModel):
    username: str
    password: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/auth/login")
def login(body: LoginRequest) -> dict:
    with get_conn() as conn:
        user = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = %s",
            (body.username,),
        ).fetchone()
    # Same error for an unknown user and a wrong password, so the API doesn't reveal which users exist.
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    return {"access_token": create_token(user["id"], user["username"]), "token_type": "bearer"}
