"""Team management blueprint — admin-only user provisioning."""

from flask import Blueprint

bp = Blueprint("team", __name__, template_folder="../templates/team")

from app.team import routes  # noqa: E402, F401
