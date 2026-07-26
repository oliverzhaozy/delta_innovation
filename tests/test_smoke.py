import pytest
from flask import request

from app import create_app
from config import ProdConfig, TestConfig, _PLACEHOLDER_KEY


def _echo_client(config_class):
    """Client for an app with a route echoing what Flask believes about the caller."""
    app = create_app(config_class)

    @app.route("/_echo_caller")
    def _echo_caller():
        return {"addr": request.remote_addr, "scheme": request.scheme}

    return app.test_client()


_FORWARDED = {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"}


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_index_requires_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_prod_refuses_placeholder_secret(monkeypatch):
    monkeypatch.setattr(ProdConfig, "SECRET_KEY", _PLACEHOLDER_KEY)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(ProdConfig)


def test_prod_refuses_debug(monkeypatch):
    monkeypatch.setattr(ProdConfig, "SECRET_KEY", "a-real-secret")
    monkeypatch.setattr(ProdConfig, "DEBUG", True, raising=False)
    with pytest.raises(RuntimeError, match="Debug"):
        create_app(ProdConfig)


def test_prod_trusts_one_proxy_hop(monkeypatch):
    # ProxyFix on: the client IP and scheme come from Caddy's X-Forwarded-*,
    # so rate limits key per client and Secure cookies survive the proxy.
    monkeypatch.setattr(ProdConfig, "SECRET_KEY", "a-real-secret")
    resp = _echo_client(ProdConfig).get("/_echo_caller", headers=_FORWARDED)
    assert resp.get_json() == {"addr": "203.0.113.9", "scheme": "https"}


def test_test_config_ignores_forwarded_headers():
    # ProxyFix off: without a proxy in front, these headers are client-forged.
    resp = _echo_client(TestConfig).get("/_echo_caller", headers=_FORWARDED)
    body = resp.get_json()
    assert body["addr"] != "203.0.113.9"
    assert body["scheme"] == "http"
