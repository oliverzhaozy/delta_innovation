import datetime

from app.domain.types import Appointment, DayPart, LeaveType, Rank, RequestStatus
from app.extensions import db
from app.models import LeaveRequest, Person
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
