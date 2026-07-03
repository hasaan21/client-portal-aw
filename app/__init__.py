"""Application factory for the AW Client Portal."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, render_template

from app.config import get_config
from app.extensions import csrf, db, login_manager, migrate


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure a Flask application instance."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config(config_name))

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    # Normalize PDF_OUTPUT_DIR to an absolute path so stored paths (and
    # Flask's send_file, which resolves relative paths against app.root_path)
    # both agree on the location regardless of CWD.
    pdf_dir = Path(app.config["PDF_OUTPUT_DIR"])
    if not pdf_dir.is_absolute():
        pdf_dir = (Path(app.root_path).parent / pdf_dir).resolve()
    app.config["PDF_OUTPUT_DIR"] = str(pdf_dir)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    _configure_logging(app)
    _init_extensions(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_healthcheck(app)
    _register_context_processors(app)

    return app


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db, directory=str(Path(app.root_path).parent / "migrations"))
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        return db.session.get(User, int(user_id))


def _register_blueprints(app: Flask) -> None:
    from app.auth import bp as auth_bp
    from app.clients import bp as clients_bp
    from app.main import bp as main_bp
    from app.reports import bp as reports_bp
    from app.team import bp as team_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(clients_bp, url_prefix="/clients")
    app.register_blueprint(reports_bp, url_prefix="/reports")
    app.register_blueprint(team_bp, url_prefix="/team")


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(403)
    def forbidden(_):  # pragma: no cover - trivial
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_):  # pragma: no cover - trivial
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_):  # pragma: no cover - trivial
        return render_template("errors/500.html"), 500


def _register_healthcheck(app: Flask) -> None:
    from sqlalchemy import text

    @app.route("/healthz")
    def healthz():
        """Liveness + readiness. Verifies DB connectivity so Railway swaps
        traffic only once migrations have finished."""
        try:
            db.session.execute(text("SELECT 1"))
            return {"status": "ok", "db": "reachable"}, 200
        except Exception as exc:
            app.logger.error("Healthcheck failed: %s", exc)
            return {"status": "degraded", "error": str(exc)}, 503


def _register_context_processors(app: Flask) -> None:
    from datetime import datetime

    @app.context_processor
    def inject_globals():
        return {
            "app_name": "AW Client Portal",
            "current_year": datetime.utcnow().year,
        }


def _configure_logging(app: Flask) -> None:
    level = logging.DEBUG if app.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    if not app.debug and os.environ.get("FLASK_ENV") != "testing":
        app.logger.setLevel(level)
