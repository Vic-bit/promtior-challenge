from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.auth import ALGORITHM, create_token, get_current_user, hash_password, verify_password
from app.config import settings
from app.main import app

PASSWORD = "TechnicalChallengePromtior"


@pytest.fixture
def client(db):
    # The `with` block runs the app's startup, which creates the tables and seeds the users.
    with TestClient(app) as client:
        yield client


def current_user(token: str) -> dict:
    return get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))


def test_password_hash_verification():
    password_hash = hash_password(PASSWORD)
    assert password_hash != PASSWORD
    assert verify_password(PASSWORD, password_hash)
    assert not verify_password("wrong", password_hash)


def test_token_round_trip():
    assert current_user(create_token(1, "User1")) == {"id": 1, "username": "User1"}


def test_expired_token_is_rejected():
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    token = jwt.encode({"sub": "1", "username": "User1", "exp": expired}, settings.jwt_secret, algorithm=ALGORITHM)
    with pytest.raises(HTTPException) as error:
        current_user(token)
    assert error.value.status_code == 401


def test_token_signed_with_another_secret_is_rejected():
    token = jwt.encode({"sub": "1", "username": "User1"}, "not-the-real-secret-" * 2, algorithm=ALGORITHM)
    with pytest.raises(HTTPException) as error:
        current_user(token)
    assert error.value.status_code == 401


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_login_returns_a_token_for_the_logged_in_user(client):
    response = client.post("/auth/login", json={"username": "User1", "password": PASSWORD})
    assert response.status_code == 200
    assert current_user(response.json()["access_token"])["username"] == "User1"


@pytest.mark.parametrize("username,password", [("User1", "wrong"), ("Nobody", PASSWORD)])
def test_login_failures_return_the_same_401(client, username, password):
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"
