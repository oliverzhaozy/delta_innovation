from app.domain.types import Appointment, Rank
from app.extensions import db
from app.models import Person
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


def test_s3_lists_people(client, make_person):
    make_person(username="opr_b")
    login(client, make_s3(make_person))
    resp = client.get("/admin/people")
    assert resp.status_code == 200
    assert b"Opr B" in resp.data


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


def test_deactivate_via_edit_blocks_login(app, client, make_person):
    victim = make_person(username="leaving")
    login(client, make_s3(make_person))
    with app.app_context():
        victim_id = db.session.query(Person.id).filter_by(username="leaving").scalar()
    resp = client.post(
        f"/admin/people/{victim_id}",
        data={
            "username": "leaving",
            "display_name": "Leaving",
            "rank": "PTE",
            "appointment": "OPR",
            "company_role": "",
            "platoon": "1",
            "service": "NSF",
            # is_active checkbox omitted -> False
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    client.post("/logout")
    resp = login(client, victim)
    assert b"Invalid credentials." in resp.data


def test_password_reset_forces_change(app, client, make_person):
    target = make_person(username="resettee")
    login(client, make_s3(make_person))
    with app.app_context():
        target_id = db.session.query(Person.id).filter_by(username="resettee").scalar()
    resp = client.post(f"/admin/people/{target_id}/reset-password", follow_redirects=True)
    assert b"Temporary password" in resp.data
    with app.app_context():
        assert db.session.get(Person, target_id).must_change_pw
