"""Regression tests for the protections TestConfig normally switches off."""
import pytest

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
