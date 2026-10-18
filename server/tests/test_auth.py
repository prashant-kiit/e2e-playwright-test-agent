"""Single-operator auth: login mints a cookie, protected routes require it."""

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("QA_ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("QA_SECRET_KEY", "test-key")
    return TestClient(app)


def test_protected_route_rejects_without_cookie(client):
    assert client.get("/projects").status_code == 401


def test_login_wrong_password_401(client):
    assert client.post("/auth/login", json={"password": "nope"}).status_code == 401


def test_login_then_access_protected_route(client):
    r = client.post("/auth/login", json={"password": "s3cret"})
    assert r.status_code == 200
    assert auth.COOKIE_NAME in r.cookies
    # TestClient keeps the cookie; protected routes now pass auth.
    assert client.get("/auth/me").json() == {"authenticated": True}


def test_logout_clears_cookie(client):
    client.post("/auth/login", json={"password": "s3cret"})
    client.post("/auth/logout")
    client.cookies.clear()
    assert client.get("/auth/me").status_code == 401


def test_token_roundtrip(monkeypatch):
    monkeypatch.setenv("QA_SECRET_KEY", "k")
    assert auth.verify_token(auth.mint_token()) is True
    assert auth.verify_token("garbage") is False
