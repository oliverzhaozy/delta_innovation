import pytest

from app import create_app
from config import ProdConfig, _PLACEHOLDER_KEY


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
