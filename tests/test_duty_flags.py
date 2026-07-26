"""P4.9 — warn-only, derived-at-render clash surfaces for leave-vs-duty.

Nothing is stored and nothing is blocked: the leave detail page lists the
requester's CONFIRMED duties in range, the roster page flags absent holders
(A8: the predicate is presence.resolve, NOT a leave-table join — an MC flags
exactly like leave), and roll call names the absent holder in chrome. The PS resolves via manual replace; approval is never
blocked and nobody is auto-reassigned.
"""
from datetime import date, timedelta

from app.domain.dates import today_sgt
from app.domain.types import (
    Appointment, BalanceKind, DayPart, Duty, DutyState,
    LeaveType, LedgerSource, Rank, RequestStatus, Service, StatusType,
)
from app.extensions import db
from app.models import DutyAssignment, LeaveRequest, LedgerEntry, Person, StatusEntry
from app.services import approval_service, duty_service, ledger_service
from tests.conftest import login

WED = date(2026, 8, 5)
THU = date(2026, 8, 6)
AUG = "2026-08"


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def make_cast(make_person):
    """Requester Opr + their PC (platoon 1) + the OC."""
    make_person(username="opr1", rank=Rank.THREE_SG, appointment=Appointment.OPR)
    make_person(username="pc1", rank=Rank.LTA, appointment=Appointment.PC)
    make_person(username="oc", rank=Rank.CPT, appointment=Appointment.OC,
                platoon=None, service=Service.REGULAR)


def plant_request(app, username, start=WED, end=THU, *,
                  status=RequestStatus.PENDING_OC):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        row = LeaveRequest(
            person_id=person_id, type=LeaveType.OFF, start_date=start,
            end_date=end, day_part=DayPart.FULL, status=status,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def plant_duty(app, username, day, *, duty=Duty.COS, state=DutyState.CONFIRMED):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        row = DutyAssignment(
            date=day, duty=duty, person_id=person_id, state=state,
            created_by_id=person_id,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


# --- leave-detail duty panel (Task 1, B1) --------------------------------------------

def test_leave_detail_shows_confirmed_duties_in_range(app, client, make_person):
    make_cast(make_person)
    req_id = plant_request(app, "opr1")
    plant_duty(app, "opr1", WED)
    plant_duty(app, "opr1", THU, duty=Duty.CDOS, state=DutyState.PROPOSED)

    for viewer in ("opr1", "pc1", "oc"):
        login(client, viewer)
        html = client.get(f"/leave/{req_id}").get_data(as_text=True)
        assert "Confirmed duties on these dates" in html, viewer
        assert "COS — confirmed" in html, viewer
        # The PROPOSED CDO/S draft is not real and must not appear.
        assert html.count("— confirmed") == 1, viewer
        client.post("/logout")


def test_leave_detail_no_duties_message(app, client, make_person):
    make_cast(make_person)
    req_id = plant_request(app, "opr1")
    login(client, "opr1")

    html = client.get(f"/leave/{req_id}").get_data(as_text=True)
    assert "No confirmed duties on these dates." in html


# --- roster absence flags (Task 2, A8) -----------------------------------------------

def plant_mc(app, username, start, end):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(
            StatusEntry(
                person_id=person_id, type=StatusType.MC, start_date=start,
                end_date=end, day_part=DayPart.FULL, in_camp=False,
                created_by_id=person_id,
            )
        )
        db.session.commit()


def plant_approved_leave(app, username, start, end, *, day_part=DayPart.FULL):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        row = LeaveRequest(
            person_id=person_id, type=LeaveType.OFF, start_date=start,
            end_date=end, day_part=day_part, status=RequestStatus.APPROVED,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def flags(app):
    with app.app_context():
        return duty_service.month_view(AUG).absent_flags


def test_roster_flags_absent_confirmed_holder_mc(app, client, make_person):
    # THE A8 PIN: an MC is a StatusEntry, not leave — a leave-table join
    # misses the most common real conflict.
    make_cast(make_person)
    aid = plant_duty(app, "opr1", WED)
    plant_mc(app, "opr1", WED, WED)

    assert aid in flags(app)
    login(client, "opr1")
    html = client.get(f"/duty/roster?month={AUG}").get_data(as_text=True)
    assert "holder absent" in html


def test_roster_flags_every_absent_holder_in_one_pass(app, client, make_person):
    # Two holders, two duties, two dates, two absence SOURCES — one month_view
    # call must flag both, because the predicate is presence, not a per-source
    # query. (The regular's absence is an MC status: regulars carry no in-app
    # leave since P9.3 — theirs lives in ARCTIC FOE.)
    make_cast(make_person)
    make_person(username="p2ic3", rank=Rank.SSG, appointment=Appointment.P2IC,
                platoon=3, service=Service.REGULAR)
    cdos_id = plant_duty(app, "p2ic3", WED, duty=Duty.CDOS)
    plant_mc(app, "p2ic3", WED, WED)
    cos_id = plant_duty(app, "opr1", THU)
    plant_approved_leave(app, "opr1", THU, THU)

    flagged = flags(app)
    assert cdos_id in flagged and cos_id in flagged


def test_pm_half_day_does_not_flag(app, make_person):
    # PM off = present for the night documents; the engine owns day-part logic.
    make_cast(make_person)
    aid = plant_duty(app, "opr1", WED)
    plant_approved_leave(app, "opr1", WED, WED, day_part=DayPart.PM)

    assert aid not in flags(app)


def test_cancelling_leave_clears_flag(app, make_person):
    make_cast(make_person)
    aid = plant_duty(app, "opr1", WED)
    req_id = plant_approved_leave(app, "opr1", WED, WED)
    assert aid in flags(app)

    with app.app_context():
        req = db.session.get(LeaveRequest, req_id)
        oc = db.session.query(Person).filter_by(username="oc").one()
        approval_service.cancel_approved(req, oc)
    # Derived at render, never stored: the flag vanished with zero flag-writes.
    assert aid not in flags(app)


def test_roll_call_chrome_names_absent_holder(app, client, make_person):
    # The roll-call page is fixed to today, whose night is (today−1)→today, so
    # the duty is planted on today−1 and the MC on today.
    make_cast(make_person)
    today = today_sgt()
    plant_duty(app, "opr1", today - timedelta(days=1))  # covers the night (today−1)→today
    plant_mc(app, "opr1", today, today)
    login(client, "opr1")

    html = client.get("/parade/roll-call").get_data(as_text=True)
    normalized = " ".join(html.split())
    assert "3SG Opr1 is absent (MC) tonight — resolve on the duty roster." in normalized


def test_approval_not_blocked_by_confirmed_duty(app, make_person):
    # WARN-ONLY PIN: the OC saw the panel; approving still succeeds, the ledger
    # debits once, and the assignment names the same person (nothing reassigned).
    make_cast(make_person)
    aid = plant_duty(app, "opr1", WED)
    req_id = plant_request(app, "opr1", WED, THU, status=RequestStatus.PENDING_OC)
    with app.app_context():
        opr_id = db.session.query(Person.id).filter_by(username="opr1").scalar()
        oc = db.session.query(Person).filter_by(username="oc").one()
        ledger_service.post_entry(
            person_id=opr_id, kind=BalanceKind.OFF, delta_half_days=10,
            reason="opening balance", source=LedgerSource.MANUAL, created_by_id=oc.id,
        )
        db.session.commit()

        req = db.session.get(LeaveRequest, req_id)
        approval_service.oc_approve(req, oc)

        assert req.status is RequestStatus.APPROVED
        debits = (
            db.session.query(LedgerEntry)
            .filter(LedgerEntry.leave_request_id == req_id, LedgerEntry.delta_half_days < 0)
            .all()
        )
        assert len(debits) == 1  # exactly one deduction, no double-debit
        row = db.session.get(DutyAssignment, aid)
        assert row.person_id == opr_id and row.state is DutyState.CONFIRMED
    assert aid in flags(app)  # ...and the roster page now flags the clash
