"""App configuration, selected by the APP_CONFIG env var: dev (default) / test / prod."""
import os
from datetime import timedelta

_PLACEHOLDER_KEY = "dev-only-placeholder-key"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", _PLACEHOLDER_KEY)
    # Relative sqlite path -> Flask instance folder (instance/delta.db).
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///delta.db")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    # Why 30 days: most access is from phones; frequent re-login kills adoption.
    REMEMBER_COOKIE_DURATION = timedelta(days=30)

    @classmethod
    def validate(cls, app):
        """Hook for configs that must refuse to boot; no-op by default."""


class DevConfig(Config):
    DEBUG = True


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"  # in-memory
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ProdConfig(Config):
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True

    @classmethod
    def validate(cls, app):
        # A missing/placeholder key means forgeable session cookies; debug on an
        # internet-facing host is remote code execution. Refuse to boot on either.
        if app.config["SECRET_KEY"] in (None, "", _PLACEHOLDER_KEY):
            raise RuntimeError("SECRET_KEY must be set to a real secret in production")
        if app.debug:
            raise RuntimeError("Debug mode must be off in production")


CONFIGS = {"dev": DevConfig, "test": TestConfig, "prod": ProdConfig}


def get_config(name=None):
    return CONFIGS[(name or os.environ.get("APP_CONFIG", "dev")).lower()]
