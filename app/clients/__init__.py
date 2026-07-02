"""Clients blueprint (fully built in M2)."""

from flask import Blueprint

bp = Blueprint("clients", __name__, template_folder="../templates/clients")

from app.clients import routes  # noqa: E402, F401
