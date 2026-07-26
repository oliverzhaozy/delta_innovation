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
    # Flask-Login's default is no SameSite attribute at all — set it explicitly.
    REMEMBER_COOKIE_SAMESITE = "Lax"
    # Why 30 days: most access is from phones; frequent re-login kills adoption.
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    # Dev-only quick user switcher (password bypass) — off everywhere except
    # DevConfig; ProdConfig.validate refuses to boot with it on.
    DEV_LOGIN_SWITCHER = False
    # Trust X-Forwarded-* from exactly one reverse proxy. Only prod runs behind
    # one (Caddy); trusting these headers without a proxy lets clients spoof
    # remote_addr, so everywhere else stays False.
    PROXY_FIX = False

    @classmethod
    def validate(cls, app):
        """Hook for configs that must refuse to boot; no-op by default."""


class DevConfig(Config):
    DEBUG = True
    DEV_LOGIN_SWITCHER = True


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-key"
    SQLALCHEMY_DATABASE_URI = "sqlite://"  # in-memory
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ProdConfig(Config):
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    PROXY_FIX = True

    @classmethod
    def validate(cls, app):
        # A missing/placeholder key means forgeable session cookies; debug on an
        # internet-facing host is remote code execution. Refuse to boot on either.
        if app.config["SECRET_KEY"] in (None, "", _PLACEHOLDER_KEY):
            raise RuntimeError("SECRET_KEY must be set to a real secret in production")
        if app.debug:
            raise RuntimeError("Debug mode must be off in production")
        # The switcher logs in as anyone without a password.
        if app.config["DEV_LOGIN_SWITCHER"]:
            raise RuntimeError("DEV_LOGIN_SWITCHER must be off in production")


CONFIGS = {"dev": DevConfig, "test": TestConfig, "prod": ProdConfig}


def get_config(name=None):
    # Fail CLOSED: an unset APP_CONFIG means prod semantics, so a host with a
    # missing/partial environment hits ProdConfig.validate and refuses to boot
    # instead of silently serving with the placeholder key. Dev gets
    # APP_CONFIG=dev from .flaskenv via the flask CLI.
    name = (name or os.environ.get("APP_CONFIG") or "prod").lower()
    if name not in CONFIGS:
        raise RuntimeError(f"Unknown APP_CONFIG {name!r}; expected one of {sorted(CONFIGS)}")
    return CONFIGS[name]
