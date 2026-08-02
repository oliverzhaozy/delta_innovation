"""Admin "View as": read-only impersonation.

The security properties pinned here are the reason the feature exists in this
shape rather than as the dev switcher: it needs a login, it needs admin, and it
can only ever READ. Writes are blocked app-wide by method, so these tests use
/parade/override — the least-gated write in the app (open to every logged-in
user, owner decision 2026-07-31). If that one is refused, all of them are.
"""
from app.domain.types import Appointment, CompanyRole, Rank
from app.extensions import db
from app.models import Person
from tests.conftest import login


def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def _admin(make_person, username="s3boss"):
    return make_person(username=username, company_role=CompanyRole.S3, is_admin=True)


def test_non_admin_cannot_view_as(app, client, make_person):
    make_person(username="opr")
    target = make_person(username="target", platoon=2)
    login(client, "opr")
    assert client.post(f"/admin/people/{_pid(app, target)}/view-as").status_code == 403


def test_anonymous_cannot_view_as(app, client, make_person):
    target = make_person(username="target")
    resp = client.post(f"/admin/people/{_pid(app, target)}/view-as")
    # Deny-by-default sends anonymous callers to login, never straight in.
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_admin_views_as_target(app, client, make_person):
    _admin(make_person)
    target = make_person(username="target", platoon=2)
    login(client, "s3boss")
    resp = client.post(f"/admin/people/{_pid(app, target)}/view-as")
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["_user_id"] == str(_pid(app, target))
        assert sess["impersonator_id"] == _pid(app, "s3boss")


def test_bar_names_the_viewed_person_and_carries_the_way_back(app, client, make_person):
    _admin(make_person)
    target = make_person(username="target", display_name="Tan Wei", rank=Rank.CPL, platoon=2)
    login(client, "s3boss")
    client.post(f"/admin/people/{_pid(app, target)}/view-as")
    html = client.get("/").get_data(as_text=True)
    assert "CPL Tan Wei" in html
    assert "read-only" in html
    assert "/admin/people/view-as/stop" in html


def test_writes_are_blocked_while_viewing_as(app, client, make_person):
    _admin(make_person)
    target = make_person(username="target", platoon=2)
    login(client, "s3boss")
    client.post(f"/admin/people/{_pid(app, target)}/view-as")
    assert client.post("/parade/override").status_code == 403


def test_view_as_cannot_be_chained(app, client, make_person):
    # An admin viewing as ANOTHER admin still passes can_impersonate, so the
    # write block is what stops the marker being overwritten and the way back
    # to the original account being lost.
    _admin(make_person)
    oc = make_person(username="oc", appointment=Appointment.OC, rank=Rank.CPT, platoon=None)
    third = make_person(username="third", platoon=3)
    login(client, "s3boss")
    client.post(f"/admin/people/{_pid(app, oc)}/view-as")
    assert client.post(f"/admin/people/{_pid(app, third)}/view-as").status_code == 403
    with client.session_transaction() as sess:
        assert sess["impersonator_id"] == _pid(app, "s3boss")


def test_stop_returns_to_the_admin(app, client, make_person):
    _admin(make_person)
    target = make_person(username="target", platoon=2)
    login(client, "s3boss")
    client.post(f"/admin/people/{_pid(app, target)}/view-as")
    resp = client.post("/admin/people/view-as/stop")
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["_user_id"] == str(_pid(app, "s3boss"))
        assert "impersonator_id" not in sess
    # Writing works again once the admin is back in their own account.
    assert client.post("/parade/override").status_code != 403


def test_stop_without_an_active_view_as_is_404(app, client, make_person):
    _admin(make_person)
    login(client, "s3boss")
    assert client.post("/admin/people/view-as/stop").status_code == 404


def test_logout_still_works_while_viewing_as(app, client, make_person):
    _admin(make_person)
    target = make_person(username="target", platoon=2)
    login(client, "s3boss")
    client.post(f"/admin/people/{_pid(app, target)}/view-as")
    resp = client.post("/logout")
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert "_user_id" not in sess
        assert "impersonator_id" not in sess


def test_viewing_as_self_is_refused(app, client, make_person):
    _admin(make_person)
    login(client, "s3boss")
    resp = client.post(f"/admin/people/{_pid(app, 's3boss')}/view-as", follow_redirects=True)
    assert "already signed in as yourself" in resp.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert "impersonator_id" not in sess


def test_forced_password_change_is_skipped_while_viewing_as(app, client, make_person):
    _admin(make_person)
    target = make_person(username="target", platoon=2, must_change_pw=True)
    login(client, "s3boss")
    client.post(f"/admin/people/{_pid(app, target)}/view-as")
    # Their own login would bounce to /password; a read-only view has nothing
    # to set, so it lands on the dashboard instead of a dead end.
    assert client.get("/").status_code == 200


def test_people_page_offers_view_as_to_admins_only(app, client, make_person):
    _admin(make_person)
    make_person(username="target", platoon=2)
    login(client, "s3boss")
    assert "View as" in client.get("/admin/people").get_data(as_text=True)


def test_people_page_hides_view_as_while_already_viewing_as(app, client, make_person):
    _admin(make_person)
    oc = make_person(username="oc", appointment=Appointment.OC, rank=Rank.CPT, platoon=None)
    login(client, "s3boss")
    client.post(f"/admin/people/{_pid(app, oc)}/view-as")
    html = client.get("/admin/people").get_data(as_text=True)
    assert "View as" not in html
    assert "Return to my account" in html


def test_unrouted_post_still_404s_while_viewing_as(app, client, make_person):
    # The write block keys on method, so it must not turn missing URLs into 403s.
    _admin(make_person)
    target = make_person(username="target", platoon=2)
    login(client, "s3boss")
    client.post(f"/admin/people/{_pid(app, target)}/view-as")
    assert client.post("/no/such/url").status_code == 404
