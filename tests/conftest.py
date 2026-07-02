"""Shared pytest fixtures."""

from __future__ import annotations

import os

import pytest

os.environ["FLASK_ENV"] = "testing"

from app import create_app
from app.extensions import db as _db
from app.models import User


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def user_factory(db):
    def _make(email="user@example.com", name="Test User", password="correct-horse", is_admin=False):
        u = User(email=email, name=name, is_admin=is_admin)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        return u

    return _make


@pytest.fixture()
def logged_in_client(client, user_factory):
    user = user_factory(password="correct-horse-battery-staple")
    resp = client.post(
        "/auth/login",
        data={"email": user.email, "password": "correct-horse-battery-staple"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    return client
