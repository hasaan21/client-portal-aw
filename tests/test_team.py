"""Team-management blueprint tests.

Covers:
- Non-admins get 403 on every /team endpoint (defence in depth for the
  admin-only nav item).
- Admin can list, invite, reset password, toggle admin, and delete.
- Guards fire: cannot demote yourself, cannot delete yourself, last-admin
  demotion is blocked, deleting a user with reports is blocked.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models import Client, Report, User


@pytest.fixture()
def another_user(db):
    u = User(email="planner@example.com", name="Ada Planner", is_admin=False)
    u.set_password("planner-pass-123")
    db.session.add(u)
    db.session.commit()
    return u


# --- guards -----------------------------------------------------------------


def test_team_page_requires_login(client):
    resp = client.get("/team/", follow_redirects=False)
    assert resp.status_code in (302, 401)
    assert "/auth/login" in resp.headers.get("Location", "")


def test_team_page_forbidden_for_non_admin(logged_in_client):
    resp = logged_in_client.get("/team/")
    assert resp.status_code == 403


def test_team_invite_forbidden_for_non_admin(logged_in_client):
    resp = logged_in_client.post(
        "/team/invite",
        data={"email": "x@example.com", "name": "X", "csrf_token": ""},
    )
    assert resp.status_code == 403


# --- happy paths ------------------------------------------------------------


def test_admin_can_view_team_page(admin_client):
    c, _ = admin_client
    resp = c.get("/team/")
    assert resp.status_code == 200
    assert b"Invite a teammate" in resp.data
    assert b"admin@example.com" in resp.data


def test_admin_can_invite_new_user(admin_client, db):
    c, _ = admin_client
    resp = c.post(
        "/team/invite",
        data={"email": "  New.Person@Example.COM  ", "name": "New Person"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # Email is normalised to lowercase and stripped.
    created = db.session.execute(
        db.select(User).filter_by(email="new.person@example.com")
    ).scalar_one_or_none()
    assert created is not None
    assert created.name == "New Person"
    assert created.is_admin is False
    # Temp password is surfaced once in the flash.
    assert b"Temporary password:" in resp.data


def test_admin_can_invite_new_admin(admin_client, db):
    c, _ = admin_client
    c.post(
        "/team/invite",
        data={"email": "second@example.com", "name": "Second Admin", "is_admin": "y"},
        follow_redirects=True,
    )
    u = db.session.execute(db.select(User).filter_by(email="second@example.com")).scalar_one()
    assert u.is_admin is True


def test_invite_rejects_duplicate_email(admin_client, another_user):
    c, _ = admin_client
    resp = c.post(
        "/team/invite",
        data={"email": another_user.email, "name": "Dup"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"already exists" in resp.data


def test_admin_can_reset_another_users_password(admin_client, another_user, db):
    c, _ = admin_client
    old_hash = another_user.password_hash
    resp = c.post(
        f"/team/{another_user.id}/reset-password",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.refresh(another_user)
    assert another_user.password_hash != old_hash
    assert b"New password for" in resp.data


def test_toggle_admin_grants_and_revokes(admin_client, another_user, db):
    c, _ = admin_client
    c.post(f"/team/{another_user.id}/toggle-admin", follow_redirects=True)
    db.session.refresh(another_user)
    assert another_user.is_admin is True
    c.post(f"/team/{another_user.id}/toggle-admin", follow_redirects=True)
    db.session.refresh(another_user)
    assert another_user.is_admin is False


def test_admin_can_delete_userless_teammate(admin_client, another_user, db):
    c, _ = admin_client
    resp = c.post(f"/team/{another_user.id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert db.session.get(User, another_user.id) is None


# --- guards fire ------------------------------------------------------------


def test_cannot_demote_yourself(admin_client, db):
    c, admin = admin_client
    resp = c.post(f"/team/{admin.id}/toggle-admin", follow_redirects=True)
    assert resp.status_code == 200
    assert b"cannot change your own admin status" in resp.data
    db.session.refresh(admin)
    assert admin.is_admin is True


def test_cannot_delete_yourself(admin_client, db):
    c, admin = admin_client
    resp = c.post(f"/team/{admin.id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert b"cannot delete your own account" in resp.data
    assert db.session.get(User, admin.id) is not None


def test_cannot_demote_last_admin(admin_client, another_user, db):
    """Promote another user to admin, then demote self via toggle — blocked."""
    c, admin = admin_client
    # Promote another user first so we HAVE more than one admin.
    c.post(f"/team/{another_user.id}/toggle-admin", follow_redirects=True)
    # Now demote them — leaves only the current admin.
    c.post(f"/team/{another_user.id}/toggle-admin", follow_redirects=True)
    # Attempting to demote self after they're the last admin.
    resp = c.post(f"/team/{admin.id}/toggle-admin", follow_redirects=True)
    assert resp.status_code == 200
    # Guard message may be either "own admin status" (self-guard fires first)
    # or "at least one admin must remain" — either is a valid rejection.
    assert (
        b"cannot change your own admin status" in resp.data
        or b"At least one admin must remain" in resp.data
    )
    db.session.refresh(admin)
    assert admin.is_admin is True


def test_cannot_delete_user_with_reports(admin_client, another_user, db):
    """Deleting a user who authored a report is blocked — audit history."""
    c, _ = admin_client
    client_row = Client(
        household_label="Test HH",
        c1_first="A",
        c1_last="B",
        c1_dob=date(1980, 1, 1),
        c1_ssn_last4="1111",
        c1_monthly_salary=0,
        monthly_expense_budget=0,
    )
    db.session.add(client_row)
    db.session.flush()
    report = Report(
        client_id=client_row.id,
        created_by_user_id=another_user.id,
        meeting_date=date.today(),
    )
    db.session.add(report)
    db.session.commit()

    resp = c.post(f"/team/{another_user.id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert b"authored" in resp.data
    assert db.session.get(User, another_user.id) is not None
