"""M1 smoke tests: the app boots, health check works, login round-trips."""

from __future__ import annotations


def test_healthz_returns_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["db"] == "reachable"


def test_login_page_renders(client):
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert b"Sign in" in resp.data


def test_login_success_redirects_to_dashboard(client, user_factory):
    user_factory(email="rebecca@example.com", name="Rebecca Test", password="hunter2-hunter2")

    resp = client.post(
        "/auth/login",
        data={"email": "rebecca@example.com", "password": "hunter2-hunter2"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_login_failure_shows_401(client, user_factory):
    user_factory(email="rebecca@example.com", password="right-password")
    resp = client.post(
        "/auth/login",
        data={"email": "rebecca@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    assert b"Invalid email or password" in resp.data


def test_dashboard_requires_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_dashboard_after_login(logged_in_client):
    resp = logged_in_client.get("/")
    assert resp.status_code == 200
    assert b"Welcome" in resp.data
    assert b"Active clients" in resp.data
