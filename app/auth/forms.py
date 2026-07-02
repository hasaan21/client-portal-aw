"""WTForms used by the auth blueprint."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField
from wtforms.validators import DataRequired, Email, Length


class LoginForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[DataRequired(), Email(), Length(max=255)],
        render_kw={"autocomplete": "email", "autofocus": True},
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=6, max=200)],
        render_kw={"autocomplete": "current-password"},
    )
    remember = BooleanField("Keep me signed in", default=False)
