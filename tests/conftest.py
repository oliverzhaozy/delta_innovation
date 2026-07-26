import pytest

from app import create_app
from app.domain.types import Appointment, CompanyRole, Rank, Service
from app.extensions import db
from app.models import Person
from config import TestConfig

DEFAULT_TEST_PASSWORD = "Secret-Pass-123"


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def make_person(app):
    """Create a Person and return their username (re-query inside a context for the row)."""

    def _make(
        username="opr1",
        display_name=None,
        rank=Rank.PTE,
        appointment=Appointment.OPR,
        company_role=None,
        platoon=1,
        service=Service.NSF,
        stay_out=False,
        duty_exempt=False,
        is_active=True,
        is_admin=False,
        must_change_pw=False,
        password=DEFAULT_TEST_PASSWORD,
    ):
        with app.app_context():
            person = Person(
                username=username,
                display_name=display_name or username.replace("_", " ").title(),
                rank=rank,
                appointment=appointment,
                company_role=CompanyRole(company_role) if isinstance(company_role, str) else company_role,
                platoon=platoon,
                service=service,
                stay_out=stay_out,
                duty_exempt=duty_exempt,
                is_active=is_active,
                is_admin=is_admin,
                must_change_pw=must_change_pw,
            )
            person.set_password(password)
            db.session.add(person)
            db.session.commit()
        return username

    return _make


def login(client, username, password=DEFAULT_TEST_PASSWORD):
    return client.post(
        "/login", data={"username": username, "password": password}, follow_redirects=True
    )
