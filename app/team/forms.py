"""Forms for the Team management blueprint."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField
from wtforms.validators import DataRequired, Email, Length


def _strip_lower(value):
    """Trim + lowercase — normalizes copy-pasted emails before validation."""
    if isinstance(value, str):
        return value.strip().lower()
    return value


def _strip(value):
    if isinstance(value, str):
        return value.strip()
    return value


class InviteUserForm(FlaskForm):
    """Add a new teammate. A temp password is generated server-side and
    surfaced to the admin ONCE via a flash — never stored plaintext."""

    email = StringField(
        "Email",
        filters=[_strip_lower],
        validators=[DataRequired(), Email(), Length(max=255)],
        render_kw={"autocomplete": "off"},
    )
    name = StringField(
        "Full name",
        filters=[_strip],
        validators=[DataRequired(), Length(max=120)],
        render_kw={"autocomplete": "off"},
    )
    is_admin = BooleanField(
        "Grant admin access",
        default=False,
        description="Admins can add / remove / reset teammates.",
    )


class EmptyForm(FlaskForm):
    """CSRF-only form for POST-only actions (reset password, toggle admin,
    delete). Keeping a single class avoids form-class sprawl."""
