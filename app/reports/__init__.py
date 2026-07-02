"""Reports blueprint (fully built in M3\u2013M6)."""

from flask import Blueprint

bp = Blueprint("reports", __name__, template_folder="../templates/reports")

from app.reports import routes  # noqa: E402, F401
