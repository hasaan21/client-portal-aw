"""Configuration classes selected by FLASK_ENV."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class BaseConfig:
    """Common defaults shared across every environment."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-do-not-use-in-prod")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'portal.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    PDF_OUTPUT_DIR = os.environ.get("PDF_OUTPUT_DIR", str(BASE_DIR / "instance" / "pdfs"))

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"

    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DURATION = int(os.environ.get("REMEMBER_COOKIE_DURATION_DAYS", "14")) * 86400

    WTF_CSRF_TIME_LIMIT = 3600 * 8  # 8 hours

    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB uploads (defensive)


class DevConfig(BaseConfig):
    DEBUG = True


class ProdConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class TestConfig(BaseConfig):
    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test-secret-key"
    PDF_OUTPUT_DIR = str(Path(tempfile.gettempdir()) / "aw-portal-test-pdfs")


_CONFIG_MAP = {
    "development": DevConfig,
    "production": ProdConfig,
    "testing": TestConfig,
}


def get_config(name: str | None = None) -> type[BaseConfig]:
    """Resolve config class by name or FLASK_ENV."""
    key = (name or os.environ.get("FLASK_ENV", "development")).lower()
    return _CONFIG_MAP.get(key, DevConfig)
