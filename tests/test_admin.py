import datetime
import json
import re

from app.domain.types import (
    COMMAND_TEAM, Appointment, DayPart, LeaveType, PlatoonCategory, Rank,
    RequestStatus,
)
from app.extensions import db
from app.models import LeaveRequest, Person
from app.services import platoon_service
from tests.conftest import login


def make_s3(make_person):
    return make_person(
        username="s3_admin",
        rank=Rank.TWO_SG,
        appointment=Appointment.DET_COMD,
        company_role="S3",
    )


def test_opr_cannot_reach_people_admin(client, make_person):
    login(client, make_person(username="opr_a"))
    assert client.get("/admin/people").status_code == 403


def test_command_team_reaches_people_admin_without_the_flag(client, make_person):
    # Owner directive 2026-08-02: PS and above are admin by appointment, so a PS
    # with is_admin unset still gets the admin pages (Opr above is the negative).
    login(client, make_person(username="ps_a", rank=Rank.TWO_SG,
                              appointment=Appointment.PS, platoon=2))
    assert client.get("/admin/people").status_code == 200


def test_person_form_carries_the_command_team_hook(client, make_person):
    # The checkbox row is hidden client-side from this list, so the list has to
    # survive in the markup — a broken Jinja expression here fails only at render.
    login(client, make_s3(make_person))
    html = client.get("/admin/people/new").get_data(as_text=True)
    assert "data-admin-row" in html
    assert "Command team — admin access is automatic" in html
    # The attribute alone, not the page: every appointment also appears as an
    # <option value>. Compared as a set — COMMAND_TEAM is an unordered frozenset.
    shipped = json.loads(re.search(r"data-command-team='([^']*)'", html).group(1))
    assert set(shipped) == {a.value for a in COMMAND_TEAM}


def test_s3_lists_people(client, make_person):
    make_person(username="opr_b")
    login(client, make_s3(make_person))
    resp = client.get("/admin/people")
    assert resp.status_code == 200
    assert b"Opr B" in resp.data


def test_people_page_is_parade_ordered(client, make_person):
    # UI-22: the People page reads the canonical parade key, so 2IC sits above
    # SM (the declaration APPOINTMENT_ORDER says otherwise) and a 3WO above an
    # LTA of the same appointment (the legal RANK_ORDER says otherwise). Names
    # alphabetize in reverse of the expected order. Since decision (dd) there is
    # no inactive tier — the OC simply heads the list, as parade order says.
    make_person(username="ord_oc", display_name="Aaa Oc", rank=Rank.CPT,
                appointment=Appointment.OC, platoon=None)
    make_person(username="ord_2ic", display_name="Zed Two", rank=Rank.LTA,
                appointment=Appointment.TWO_IC, platoon=None)
    make_person(username="ord_sm", display_name="Yan Sm", rank=Rank.THREE_WO,
                appointment=Appointment.SM, platoon=None)
    make_person(username="ord_p2ic_wo", display_name="Bee P2ic", rank=Rank.THREE_WO,
                appointment=Appointment.P2IC, platoon=1)
    make_person(username="ord_p2ic_lta", display_name="Ace P2ic", rank=Rank.LTA,
                appointment=Appointment.P2IC, platoon=2)
    login(client, make_s3(make_person))

    body = client.get("/admin/people").get_data(as_text=True)
    positions = [
        body.index(name)
        for name in ("Aaa Oc", "Zed Two", "Yan Sm", "Bee P2ic", "Ace P2ic")
    ]
    assert positions == sorted(positions)


# --- decision (ee): platoon-category sections + the config card -------------------

DEFAULT_MAPPING = {
    PlatoonCategory.STC: (2, False),
    PlatoonCategory.SENIOR: (3, True),
    PlatoonCategory.JUNIOR: (1, True),
    PlatoonCategory.BABY: (None, True),
}


def make_platoon_cast(make_person):
    make_person(username="cat_oc", display_name="Cee Oc", rank=Rank.CPT,
                appointment=Appointment.OC, platoon=None)
    make_person(username="cat_opr1", display_name="One Opr", rank=Rank.PTE,
                appointment=Appointment.OPR, platoon=1)
    make_person(username="cat_opr2", display_name="Two Opr", rank=Rank.PTE,
                appointment=Appointment.OPR, platoon=2)
    make_person(username="cat_opr3", display_name="Three Opr", rank=Rank.PTE,
                appointment=Appointment.OPR, platoon=3)


def category_state():
    return {
        row.category: (row.platoon, row.in_cos_pool)
        for row in platoon_service.category_rows()
    }


def test_people_page_groups_by_platoon_category(app, client, make_person):
    make_platoon_cast(make_person)
    login(client, make_s3(make_person))
    with app.app_context():
        platoon_service.set_categories(DEFAULT_MAPPING)

    body = client.get("/admin/people").get_data(as_text=True)
    headers = (
        "<h2>Command</h2>",
        "STC &mdash; Platoon 2 &middot; Excluded from COS pool",
        "Senior &mdash; Platoon 3 &middot; In COS pool",
        "Junior &mdash; Platoon 1 &middot; In COS pool",
        "<h2>Baby</h2>",
    )
    # Sections in PlatoonCategory declaration order, command first.
    positions = [body.index(header) for header in headers]
    assert positions == sorted(positions)
    # An empty category keeps its header AND says why it is empty.
    assert "No platoon assigned." in body
    # People follow their platoon's section, not the flat roster order.
    assert body.index("Two Opr") < body.index("Three Opr") < body.index("One Opr")
    assert body.index("Cee Oc") < body.index("Two Opr")


def test_people_page_shows_an_unmapped_platoon_rather_than_hiding_it(app, client, make_person):
    make_platoon_cast(make_person)
    login(client, make_s3(make_person))
    with app.app_context():
        platoon_service.set_categories({
            PlatoonCategory.STC: (2, False),
            PlatoonCategory.SENIOR: (None, True),
            PlatoonCategory.JUNIOR: (1, True),
            PlatoonCategory.BABY: (None, True),
        })

    body = client.get("/admin/people").get_data(as_text=True)
    assert "Platoon 3 &mdash; no category" in body
    assert body.index("Platoon 3 &mdash; no category") < body.index("Three Opr")


def test_people_page_shows_a_platoon_less_trooper_in_its_own_section(app, client, make_person):
    make_person(username="cat_stray", display_name="Stray Opr", rank=Rank.PTE,
                appointment=Appointment.OPR, platoon=None)
    login(client, make_s3(make_person))

    body = client.get("/admin/people").get_data(as_text=True)
    assert "<h2>No platoon</h2>" in body
    assert body.index("<h2>No platoon</h2>") < body.index("Stray Opr")


def test_platoon_categories_post_saves_the_mapping(app, client, make_person):
    login(client, make_s3(make_person))

    resp = client.post(
        "/admin/people/platoon-categories",
        data={
            "platoon_STC": "2",
            "platoon_SENIOR": "3", "in_cos_pool_SENIOR": "1",
            "platoon_JUNIOR": "1", "in_cos_pool_JUNIOR": "1",
            "platoon_BABY": "", "in_cos_pool_BABY": "1",
        },
        follow_redirects=True,
    )
    assert b"Platoon categories saved." in resp.data
    with app.app_context():
        # An unticked checkbox posts nothing at all — that is the excusal.
        assert category_state() == DEFAULT_MAPPING
        assert platoon_service.cos_excluded_platoons() == frozenset({2})


def test_platoon_categories_post_rejects_a_duplicate_platoon(app, client, make_person):
    login(client, make_s3(make_person))

    resp = client.post(
        "/admin/people/platoon-categories",
        data={"platoon_STC": "2", "platoon_SENIOR": "2", "platoon_JUNIOR": "1"},
        follow_redirects=True,
    )
    assert b"only one category" in resp.data
    with app.app_context():
        # Rejected whole: no half-written mapping.
        assert all(platoon is None for platoon, _flag in category_state().values())


def test_platoon_categories_post_rejects_a_platoon_outside_1_to_3(app, client, make_person):
    login(client, make_s3(make_person))
    resp = client.post("/admin/people/platoon-categories", data={"platoon_STC": "9"})
    assert resp.status_code == 400


def test_opr_cannot_key_platoon_categories(client, make_person):
    login(client, make_person(username="opr_cat"))
    resp = client.post("/admin/people/platoon-categories", data={})
    assert resp.status_code == 403


def test_create_person_end_to_end(app, client, make_person):
    login(client, make_s3(make_person))
    resp = client.post(
        "/admin/people/new",
        data={
            "username": "new_guy",
            "display_name": "PTE New Guy",
            "rank": "PTE",
            "appointment": "OPR",
            "company_role": "",
            "platoon": "2",
            "service": "NSF",
        },
        follow_redirects=True,
    )
    assert b"Temporary password" in resp.data
    with app.app_context():
        created = db.session.query(Person).filter_by(username="new_guy").one()
        assert created.platoon == 2
        assert created.must_change_pw


def test_duplicate_username_rejected(app, client, make_person):
    make_person(username="taken")
    login(client, make_s3(make_person))
    resp = client.post(
        "/admin/people/new",
        data={
            "username": "taken",
            "display_name": "PTE Dup",
            "rank": "PTE",
            "appointment": "OPR",
            "company_role": "",
            "platoon": "1",
            "service": "NSF",
        },
        follow_redirects=True,
    )
    assert b"already taken" in resp.data
    with app.app_context():
        assert db.session.query(Person).filter_by(username="taken").count() == 1


def test_delete_person_without_history(app, client, make_person):
    make_person(username="mistake")
    login(client, make_s3(make_person))
    with app.app_context():
        target_id = db.session.query(Person.id).filter_by(username="mistake").scalar()
    resp = client.post(f"/admin/people/{target_id}/delete", follow_redirects=True)
    assert b"Deleted" in resp.data
    with app.app_context():
        assert db.session.get(Person, target_id) is None


def test_delete_person_with_history_cascades(app, client, make_person):
    # Decision (dd) inverts the old rule: history no longer blocks the delete,
    # it goes with the person, and the flash names what was removed.
    make_person(username="hashistory")
    login(client, make_s3(make_person))
    with app.app_context():
        target_id = db.session.query(Person.id).filter_by(username="hashistory").scalar()
        db.session.add(
            LeaveRequest(
                person_id=target_id,
                type=LeaveType.OFF,
                start_date=datetime.date(2026, 1, 1),
                end_date=datetime.date(2026, 1, 1),
                day_part=DayPart.FULL,
                status=RequestStatus.APPROVED,
            )
        )
        db.session.commit()
    resp = client.post(f"/admin/people/{target_id}/delete", follow_redirects=True)
    assert b"leave_request (1)" in resp.data
    with app.app_context():
        assert db.session.get(Person, target_id) is None
        assert db.session.query(LeaveRequest).filter_by(person_id=target_id).count() == 0


def test_cannot_delete_own_account(app, client, make_person):
    make_s3(make_person)
    login(client, "s3_admin")
    with app.app_context():
        own_id = db.session.query(Person.id).filter_by(username="s3_admin").scalar()
    resp = client.post(f"/admin/people/{own_id}/delete", follow_redirects=True)
    assert b"can&#39;t delete your own account" in resp.data
    with app.app_context():
        assert db.session.get(Person, own_id) is not None


def test_password_reset_forces_change(app, client, make_person):
    target = make_person(username="resettee")
    login(client, make_s3(make_person))
    with app.app_context():
        target_id = db.session.query(Person.id).filter_by(username="resettee").scalar()
    resp = client.post(f"/admin/people/{target_id}/reset-password", follow_redirects=True)
    assert b"Temporary password" in resp.data
    with app.app_context():
        assert db.session.get(Person, target_id).must_change_pw
