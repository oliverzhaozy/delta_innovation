from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.dates import today_sgt
from app.domain.types import Appointment, DeclarationStatus, ManningSlotType, Rank
from app.extensions import db
from app.models import ManningPeriod, ManningSlot, OverseasDeclaration, Person
from app.services import overseas_service
from app.services.approval_service import TransitionError
from tests.conftest import login

TODAY = today_sgt()
NEXT_WEEK = TODAY + timedelta(days=7)
LAST_WEEK = TODAY - timedelta(days=7)
YESTERDAY = TODAY - timedelta(days=1)


def declare(client, start=None, end=None, destination="Malaysia", follow=True):
    start = start or NEXT_WEEK
    end = end or NEXT_WEEK
    return client.post(
        "/overseas/declare",
        data={"start_date": start.isoformat(), "end_date": end.isoformat(), "destination": destination},
        follow_redirects=follow,
    )


def declaration_id_for(app, username):
    with app.app_context():
        return (
            db.session.query(OverseasDeclaration.id)
            .join(Person, OverseasDeclaration.person_id == Person.id)
            .filter(Person.username == username)
            .scalar()
        )


def status_of(app, declaration_id):
    with app.app_context():
        return db.session.query(OverseasDeclaration.status).filter_by(id=declaration_id).scalar()


def make_pc(make_person, username="ovs_pc"):
    return make_person(username=username, rank=Rank.LTA, appointment=Appointment.PC)


def test_date_order_check_constraint_enforced_in_db(app, make_person):
    make_person(username="ovs_dbcheck")
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username="ovs_dbcheck").scalar()
        row = OverseasDeclaration(
            person_id=pid, start_date=TODAY + timedelta(days=2), end_date=TODAY + timedelta(days=1),
            destination="Nowhere", status=DeclarationStatus.APPROVED,
        )
        db.session.add(row)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_opr_declares_and_it_appears_in_mine_and_s3_upcoming(app, client, make_person):
    make_person(username="s3_person", company_role="S3")
    login(client, make_person(username="ovs_opr", display_name="PTE Ovs Opr"))
    resp = declare(client, destination="Japan")
    assert b"Declared" in resp.data

    mine_resp = client.get("/overseas/mine")
    assert b"Japan" in mine_resp.data
    client.post("/logout")

    login(client, "s3_person")
    upcoming_resp = client.get("/overseas/upcoming")
    assert upcoming_resp.status_code == 200
    assert b"Japan" in upcoming_resp.data
    assert b"Ovs Opr" in upcoming_resp.data


# --- initial status by appointment (owner 2026-07-28) ---------------------------------


@pytest.mark.parametrize(
    "appointment, expected",
    [
        (Appointment.OPR, DeclarationStatus.PENDING),
        (Appointment.PC, DeclarationStatus.APPROVED),
        (Appointment.OC, DeclarationStatus.APPROVED),
    ],
)
def test_initial_status_by_appointment(app, client, make_person, appointment, expected):
    username = f"ovs_init_{appointment.value.lower()}"
    login(client, make_person(username=username, appointment=appointment))
    resp = declare(client, destination="Taiwan")
    assert status_of(app, declaration_id_for(app, username)) is expected
    if expected is DeclarationStatus.PENDING:
        assert b"pending PC approval" in resp.data
    else:
        assert b"pending PC approval" not in resp.data


# --- retract now DELETES (owner 2026-07-28, reversing P2.1) ---------------------------


def test_retract_deletes_the_row_from_db_mine_and_upcoming(app, client, make_person):
    make_person(username="s3_person2", company_role="S3")
    login(client, make_person(username="ovs_retract"))
    declare(client, destination="Thailand")
    decl_id = declaration_id_for(app, "ovs_retract")

    resp = client.post(f"/overseas/{decl_id}/retract", follow_redirects=True)
    assert b"Retracted" in resp.data

    with app.app_context():
        assert db.session.get(OverseasDeclaration, decl_id) is None

    mine_resp = client.get("/overseas/mine")
    assert b"Thailand" not in mine_resp.data

    client.post("/logout")
    login(client, "s3_person2")
    upcoming_resp = client.get("/overseas/upcoming")
    assert b"Thailand" not in upcoming_resp.data


def test_retract_works_on_a_rejected_row(app, client, make_person):
    make_pc(make_person)
    login(client, make_person(username="ovs_rej_retract"))
    declare(client, destination="Cambodia")
    decl_id = declaration_id_for(app, "ovs_rej_retract")
    client.post("/logout")

    login(client, "ovs_pc")
    client.post(f"/overseas/{decl_id}/reject", follow_redirects=True)
    client.post("/logout")

    login(client, "ovs_rej_retract")
    resp = client.post(f"/overseas/{decl_id}/retract", follow_redirects=True)
    assert b"Retracted" in resp.data
    with app.app_context():
        assert db.session.get(OverseasDeclaration, decl_id) is None


def test_cannot_retract_someone_elses_declaration(app, client, make_person):
    login(client, make_person(username="ovs_victim"))
    declare(client, destination="Vietnam")
    decl_id = declaration_id_for(app, "ovs_victim")
    client.post("/logout")

    login(client, make_person(username="ovs_attacker"))
    resp = client.post(f"/overseas/{decl_id}/retract")
    assert resp.status_code == 403


# --- the PC queue ---------------------------------------------------------------------


def test_pc_approves_from_the_queue(app, client, make_person):
    make_pc(make_person)
    login(client, make_person(username="ovs_appr", display_name="PTE Ovs Appr"))
    declare(client, destination="Korea")
    decl_id = declaration_id_for(app, "ovs_appr")
    client.post("/logout")

    login(client, "ovs_pc")
    queue_resp = client.get("/overseas/queue")
    assert b"Korea" in queue_resp.data
    assert b"Ovs Appr" in queue_resp.data

    resp = client.post(f"/overseas/{decl_id}/approve", follow_redirects=True)
    assert b"Approved." in resp.data
    assert b"Korea" not in resp.data  # gone from the queue

    with app.app_context():
        row = db.session.get(OverseasDeclaration, decl_id)
        assert row.status is DeclarationStatus.APPROVED
        assert row.pc_actor.username == "ovs_pc"
        assert row.pc_at is not None


def test_pc_reject_needs_no_remark(app, client, make_person):
    # Owner 2026-08-02: the required reason box is gone — reject is one click.
    make_pc(make_person)
    login(client, make_person(username="ovs_rejectee"))
    declare(client, destination="Bali")
    decl_id = declaration_id_for(app, "ovs_rejectee")
    client.post("/logout")

    login(client, "ovs_pc")
    resp = client.post(f"/overseas/{decl_id}/reject", follow_redirects=True)
    assert b"Rejected." in resp.data
    with app.app_context():
        row = db.session.get(OverseasDeclaration, decl_id)
        assert row.status is DeclarationStatus.REJECTED
        assert row.remarks is None
        assert row.pc_actor.username == "ovs_pc"
    client.post("/logout")

    # The owner keeps seeing the row, badged.
    login(client, "ovs_rejectee")
    mine = client.get("/overseas/mine").get_data(as_text=True)
    assert "Rejected" in mine


def test_queue_flags_declarant_on_tu_manning_overlap(app, client, make_person):
    make_pc(make_person)
    login(client, make_person(username="ovs_manned"))
    declare(client, destination="Batam")
    client.post("/logout")
    login(client, make_person(username="ovs_unmanned"))
    declare(client, destination="Bintan")
    client.post("/logout")

    with app.app_context():
        manned_id = db.session.query(Person.id).filter_by(username="ovs_manned").scalar()
        unmanned_id = db.session.query(Person.id).filter_by(username="ovs_unmanned").scalar()
        creator_id = db.session.query(Person.id).filter_by(username="ovs_pc").scalar()
        overlapping = ManningPeriod(
            start_date=NEXT_WEEK, end_date=NEXT_WEEK + timedelta(days=3),
            created_by_id=creator_id,
        )
        elsewhere = ManningPeriod(
            start_date=NEXT_WEEK + timedelta(days=10), end_date=NEXT_WEEK + timedelta(days=13),
            created_by_id=creator_id,
        )
        db.session.add_all([overlapping, elsewhere])
        db.session.flush()
        db.session.add_all([
            ManningSlot(period_id=overlapping.id, slot=ManningSlotType.DET_PERSONNEL,
                        person_id=manned_id, det_number=1),
            # A slot whose period misses the trip dates must NOT flag.
            ManningSlot(period_id=elsewhere.id, slot=ManningSlotType.DET_PERSONNEL,
                        person_id=unmanned_id, det_number=1),
        ])
        db.session.commit()

    login(client, "ovs_pc")
    html = client.get("/overseas/queue").get_data(as_text=True)
    flagged_rows = [row for row in html.split("<tr>") if "On TU manning" in row]
    assert len(flagged_rows) == 1
    assert "Batam" in flagged_rows[0]


def test_second_action_loses_the_claim(app, client, make_person):
    make_pc(make_person)
    login(client, make_person(username="ovs_double"))
    declare(client, destination="Perth")
    decl_id = declaration_id_for(app, "ovs_double")
    client.post("/logout")

    login(client, "ovs_pc")
    client.post(f"/overseas/{decl_id}/approve", follow_redirects=True)
    resp = client.post(f"/overseas/{decl_id}/approve", follow_redirects=True)
    assert b"already actioned" in resp.data
    assert status_of(app, decl_id) is DeclarationStatus.APPROVED


def test_service_forbids_actioning_your_own_declaration(app, client, make_person):
    # Structurally unreachable through routing (a PC's own row is auto-APPROVED),
    # but the guard has to survive a routing change.
    login(client, make_pc(make_person, username="ovs_selfpc"))
    declare(client, destination="Bangkok")
    decl_id = declaration_id_for(app, "ovs_selfpc")

    with app.app_context():
        row = db.session.get(OverseasDeclaration, decl_id)
        actor = db.session.get(Person, row.person_id)
        with pytest.raises(TransitionError):
            overseas_service.pc_approve(row, actor)
        with pytest.raises(TransitionError):
            overseas_service.pc_reject(row, actor)


def test_non_pc_forbidden_on_queue_and_actions(app, client, make_person):
    make_pc(make_person)
    login(client, make_person(username="ovs_nonpc"))
    declare(client, destination="Manila")
    decl_id = declaration_id_for(app, "ovs_nonpc")

    assert client.get("/overseas/queue").status_code == 403
    assert client.post(f"/overseas/{decl_id}/approve").status_code == 403
    assert client.post(f"/overseas/{decl_id}/reject").status_code == 403


def test_pc_badge_counts_pending_declarations(app, client, make_person):
    make_pc(make_person)
    login(client, make_person(username="ovs_badge"))
    declare(client, destination="Hanoi")
    client.post("/logout")

    login(client, "ovs_pc")
    html = client.get("/overseas/queue").get_data(as_text=True)
    assert "Leave (1)" in html


# --- what the S3 sees -----------------------------------------------------------------


def test_pending_shows_on_upcoming_and_rejected_does_not(app, client, make_person):
    make_person(username="s3_person4", company_role="S3")
    make_pc(make_person)
    login(client, make_person(username="ovs_pending"))
    declare(client, destination="Penang")
    client.post("/logout")

    login(client, make_person(username="ovs_rejected"))
    declare(client, destination="Phuket")
    decl_id = declaration_id_for(app, "ovs_rejected")
    client.post("/logout")

    login(client, "ovs_pc")
    client.post(f"/overseas/{decl_id}/reject", follow_redirects=True)
    client.post("/logout")

    login(client, "s3_person4")
    html = client.get("/overseas/upcoming").get_data(as_text=True)
    assert "Penang" in html
    assert "Pending" in html
    assert "Phuket" not in html


def test_non_s3_forbidden_on_upcoming(client, make_person):
    login(client, make_person(username="ovs_plain"))
    assert client.get("/overseas/upcoming").status_code == 403


def test_past_declaration_is_deleted_on_page_load(app, client, make_person):
    make_person(username="s3_person3", company_role="S3")
    login(client, make_person(username="ovs_past"))
    # Not following the redirect: /overseas/mine is one of the pages that purges.
    declare(client, start=LAST_WEEK, end=YESTERDAY, destination="Indonesia", follow=False)
    decl_id = declaration_id_for(app, "ovs_past")
    assert decl_id is not None

    mine = client.get("/overseas/mine")
    assert b"Indonesia" not in mine.data
    with app.app_context():
        assert db.session.get(OverseasDeclaration, decl_id) is None


def test_upcoming_purges_expired_rows_too(app, client, make_person):
    make_person(username="s3_person5", company_role="S3")
    login(client, make_person(username="ovs_past2"))
    declare(client, start=LAST_WEEK, end=YESTERDAY, destination="Batam", follow=False)
    decl_id = declaration_id_for(app, "ovs_past2")
    client.post("/logout")

    login(client, "s3_person5")
    resp = client.get("/overseas/upcoming")
    assert b"Batam" not in resp.data
    with app.app_context():
        assert db.session.get(OverseasDeclaration, decl_id) is None


def test_end_before_start_rejected_by_form(client, make_person):
    login(client, make_person(username="ovs_rev"))
    resp = declare(client, start=NEXT_WEEK, end=NEXT_WEEK - timedelta(days=1))
    assert b"before start date" in resp.data
