"""Dev-only user switcher: works with the flag on, doesn't exist with it off."""
import pytest

from app import create_app
from app.domain.types import Appointment, Rank
from app.extensions import db
from app.models import Person
from config import ProdConfig, TestConfig
from tests.conftest import login


class SwitcherTestConfig(TestConfig):
    DEV_LOGIN_SWITCHER = True


@pytest.fixture()
def app():
    # Overrides conftest's app fixture for this module only, so conftest's
    # client/make_person fixtures bind to the flag-on app.
    app = create_app(SwitcherTestConfig)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def test_flag_off_route_and_dropdown_absent():
    plain = create_app(TestConfig)
    client = plain.test_client()
    assert client.post("/dev/switch/1").status_code == 404
    assert b"Dev: switch user" not in client.get("/login").data


def test_prod_refuses_to_boot_with_flag_on():
    class BadProdConfig(ProdConfig):
        SECRET_KEY = "a-real-enough-secret"
        DEV_LOGIN_SWITCHER = True

    with pytest.raises(RuntimeError, match="DEV_LOGIN_SWITCHER"):
        create_app(BadProdConfig)


def test_switch_logs_in_without_password(app, client, make_person):
    username = make_person(username="alpha")
    resp = client.post(f"/dev/switch/{_pid(app, username)}")
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["_user_id"] == str(_pid(app, username))
    assert client.get("/", follow_redirects=False).status_code == 200


def test_switch_swaps_profiles(app, client, make_person):
    alpha = make_person(username="alpha")
    bravo = make_person(username="bravo", platoon=2)
    login(client, alpha)
    client.post(f"/dev/switch/{_pid(app, bravo)}")
    with client.session_transaction() as sess:
        assert sess["_user_id"] == str(_pid(app, bravo))


def test_switch_rotates_session(app, client, make_person):
    username = make_person(username="alpha")
    with client.session_transaction() as sess:
        sess["marker"] = "pre-switch"
    client.post(f"/dev/switch/{_pid(app, username)}")
    with client.session_transaction() as sess:
        assert "marker" not in sess


def test_switch_into_must_change_pw_account_not_bounced(app, client, make_person):
    username = make_person(username="fresh", must_change_pw=True)
    client.post(f"/dev/switch/{_pid(app, username)}")
    assert client.get("/", follow_redirects=False).status_code == 200


def test_real_login_with_must_change_pw_still_bounced(client, make_person):
    # The hook exemption keys on the switch marker, not on the flag alone.
    username = make_person(username="fresh", must_change_pw=True)
    login(client, username)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/password" in resp.headers["Location"]


def test_switch_to_unknown_person_is_404(app, client, make_person):
    make_person(username="present")
    assert client.post("/dev/switch/99999").status_code == 404


def test_dropdown_lists_profiles_not_names(client, make_person):
    make_person(username="alpha", display_name="Alpha One")
    make_person(username="bravo", display_name="Bravo Two", platoon=2)  # same profile
    make_person(username="charlie", display_name="Charlie Three", company_role="S3")
    make_person(username="delta", display_name="Delta Four", is_admin=True)
    html = client.get("/login").data.decode()
    assert "Dev: switch user" in html
    # Profiles, not people: no names, duplicates collapsed, variants kept apart.
    for name in ("Alpha One", "Bravo Two", "Charlie Three", "Delta Four"):
        assert name not in html
    assert html.count(">Opr</button>") == 1
    assert ">Opr (S3)</button>" in html
    assert ">Opr (admin)</button>" in html
    # Nobody holds PC, so that profile has no representative at all.
    assert ">PC</button>" not in html


def test_dropdown_collapses_command_team_admin_variants(client, make_person):
    # Command team is admin by appointment (policy.is_admin), so the stored
    # flag is not a distinct profile: one PS entry, never "PS (admin)".
    make_person(username="ps_plain", rank=Rank.SSG, appointment=Appointment.PS)
    make_person(username="ps_flagged", rank=Rank.SSG, appointment=Appointment.PS, platoon=2, is_admin=True)
    make_person(username="opr_admin", is_admin=True)  # non-command-team keeps the suffix
    html = client.get("/login").data.decode()
    assert html.count(">PS</button>") == 1
    assert "PS (admin)" not in html
    assert ">Opr (admin)</button>" in html
