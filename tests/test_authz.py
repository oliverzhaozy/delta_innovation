import pytest

from app import create_app
from app.authz import require
from app.domain import policy
from app.domain.types import Appointment, Rank
from app.extensions import db
from config import TestConfig
from tests.conftest import login


@pytest.fixture()
def app():
    """App with a ledger-guarded probe route registered before first request."""
    app = create_app(TestConfig)

    @app.route("/_test/ledger")
    @require(policy.can_manage_ledger)
    def _test_ledger():
        return "ledger ok"

    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_anonymous_is_redirected_to_login(client):
    resp = client.get("/_test/ledger")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_opr_gets_403(client, make_person):
    username = make_person(username="opr_probe")
    login(client, username)
    assert client.get("/_test/ledger").status_code == 403


def test_s3_gets_200(client, make_person):
    username = make_person(
        username="s3_probe",
        rank=Rank.TWO_SG,
        appointment=Appointment.DET_COMD,
        company_role="S3",
    )
    login(client, username)
    resp = client.get("/_test/ledger")
    assert resp.status_code == 200
    assert b"ledger ok" in resp.data


def test_admin_flag_also_passes(client, make_person):
    username = make_person(username="admin_probe", is_admin=True)
    login(client, username)
    assert client.get("/_test/ledger").status_code == 200
