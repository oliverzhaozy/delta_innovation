"""P4.7 — CONFIRMED duties feed presence, parades, and meals through the one
build_doc pipeline. The A3 trap pinned here: the adapter row handed to the
engine covers the RESOLUTION day (duty_day is only the fetch key), so the roll
call labeled D really counts the duty of D−1 on day D.
"""
from datetime import date

from app.domain.presence import PresenceState
from app.domain.types import (
    Appointment, DayPart, Duty, DutyState, LeaveType, Rank, RequestStatus, Service,
)
from app.extensions import db
from app.models import DutyAssignment, LeaveRequest, Person
from app.services import presence_service

D = date(2026, 8, 10)  # a Monday


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def make_stay_out_opr(make_person, username="cos_guy"):
    """Stay-out NSF Opr — COS-eligible, and stay-out makes the DUTY override
    visible (a stay-in NSF is PRESENT either way)."""
    return make_person(
        username=username, rank=Rank.THREE_SG, appointment=Appointment.OPR,
        service=Service.NSF, stay_out=True,
    )


def plant_duty(app, username, day, *, duty=Duty.COS, state=DutyState.CONFIRMED):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(
            DutyAssignment(
                date=day, duty=duty, person_id=person_id, state=state,
                created_by_id=person_id,
            )
        )
        db.session.commit()


def plant_leave(app, username, start, end, *, day_part=DayPart.FULL):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(
            LeaveRequest(
                person_id=person_id, type=LeaveType.OFF, start_date=start,
                end_date=end, day_part=day_part, status=RequestStatus.APPROVED,
            )
        )
        db.session.commit()


def resolution_for(pairs, person_id):
    return next(p.resolution for p in pairs if p.person.id == person_id)


def test_confirmed_duty_reaches_resolution(app, make_person):
    make_stay_out_opr(make_person)
    plant_duty(app, "cos_guy", D)

    with app.app_context():
        res = resolution_for(presence_service.presence_inputs(D), pid(app, "cos_guy"))
        assert res.state is PresenceState.DUTY  # duty overrides stay-out


def test_duty_day_offset_fetches_other_date(app, make_person):
    make_stay_out_opr(make_person)
    plant_duty(app, "cos_guy", D)

    with app.app_context():
        # duty_day is the FETCH key only; the adapter row must cover the
        # resolution day (A3) — keyed to the assignment's own date, covers()
        # would always be False whenever duty_day != day.
        pairs = presence_service.presence_inputs(date(2026, 8, 11), duty_day=D)
        assert resolution_for(pairs, pid(app, "cos_guy")).state is PresenceState.DUTY
        # And without the offset, the 11th has no duty for him.
        pairs = presence_service.presence_inputs(date(2026, 8, 11))
        assert resolution_for(pairs, pid(app, "cos_guy")).state is PresenceState.STAY_OUT


def test_proposed_changes_nothing(app, make_person):
    make_stay_out_opr(make_person)
    plant_duty(app, "cos_guy", D, state=DutyState.PROPOSED)

    with app.app_context():
        res = resolution_for(presence_service.presence_inputs(D), pid(app, "cos_guy"))
        assert res.state is PresenceState.STAY_OUT  # drafts never move real counts


def test_leave_beats_duty(app, make_person):
    make_stay_out_opr(make_person)
    plant_duty(app, "cos_guy", D)
    plant_leave(app, "cos_guy", D, D)

    with app.app_context():
        res = resolution_for(presence_service.presence_inputs(D), pid(app, "cos_guy"))
        assert res.state is PresenceState.ABSENT  # precedence: leave > duty
