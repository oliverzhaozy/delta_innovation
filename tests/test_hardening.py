"""Regression tests for the protections TestConfig normally switches off."""
import pytest
from flask_wtf.csrf import generate_csrf, validate_csrf
from itsdangerous import TimestampSigner
from wtforms import ValidationError

from app import create_app
from app.extensions import db
from config import TestConfig
from tests.conftest import DEFAULT_TEST_PASSWORD


class RateLimitConfig(TestConfig):
    RATELIMIT_ENABLED = True


class CsrfConfig(TestConfig):
    WTF_CSRF_ENABLED = True


def test_login_is_rate_limited():
    app = create_app(RateLimitConfig)
    with app.app_context():
        db.create_all()
    client = app.test_client()
    for _ in range(10):
        assert client.post("/login", data={"username": "x", "password": "y"}).status_code == 200
    assert client.post("/login", data={"username": "x", "password": "y"}).status_code == 429


def test_login_post_requires_csrf_token():
    app = create_app(CsrfConfig)
    with app.app_context():
        db.create_all()
    client = app.test_client()
    resp = client.post("/login", data={"username": "x", "password": "y"})
    assert resp.status_code == 400


def test_csrf_rejection_renders_the_branded_page():
    # Regression: with no CSRFError handler a rejected form dropped the user on
    # Werkzeug's unstyled 400, which never says that reloading fixes it.
    app = create_app(CsrfConfig)
    with app.app_context():
        db.create_all()
    client = app.test_client()
    resp = client.post("/login", data={"username": "x", "password": "y"})
    assert resp.status_code == 400
    assert b"Page expired" in resp.data


def test_csrf_token_outlives_the_old_one_hour_limit(monkeypatch):
    # Regression: Flask-WTF's 3600s default expired tokens inside a 30-day
    # login, so any page left open for an hour 400ed on submit.
    app = create_app(CsrfConfig)
    with app.test_request_context():
        original = TimestampSigner.get_timestamp
        monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: original(self) - 7200)
        token = generate_csrf()
        monkeypatch.undo()
        # Pinning the back-date: under the old default this token is expired...
        with pytest.raises(ValidationError, match="expired"):
            validate_csrf(token, time_limit=3600)
        # ...and under the configured limit it still validates.
        validate_csrf(token)


def test_logout_clears_remember_cookie(app, make_person):
    # Regression: session.clear() after logout_user() used to wipe the
    # remember-clear marker, leaving the 30-day cookie alive after sign-out.
    client = app.test_client()
    username = make_person(username="rememberer")
    client.post(
        "/login",
        data={"username": username, "password": DEFAULT_TEST_PASSWORD, "remember": "y"},
    )
    assert client.get_cookie("remember_token") is not None
    client.post("/logout")
    assert client.get_cookie("remember_token") is None
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_get_config_fails_closed(monkeypatch):
    from config import ProdConfig, get_config

    monkeypatch.delenv("APP_CONFIG", raising=False)
    assert get_config() is ProdConfig
    with pytest.raises(RuntimeError, match="Unknown APP_CONFIG"):
        get_config("production")
