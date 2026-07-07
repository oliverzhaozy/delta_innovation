"""P4.4 — services/duty_service.py: availability shaping, generation, confirm.

The pure modules (eligibility.py, roster.py) are already pinned by their own
suites; these tests exercise the glue — one shared absence fetch, overnight-TP
resolution, CONFIRMED preservation, and the confirm fingerprint (A4).
"""
import pytest
from datetime import date, datetime

from app.domain.types import (
    Appointment, Calendar, DayPart, Duty, DutyState, LeaveType,
    ParticipantCategory, Rank, RequestStatus, StatusType,
)
from app.extensions import db
from app.models import (
    DutyAssignment, Event, EventParticipant, LeaveRequest, Person, StatusEntry,
)
from app.services import duty_service

JULY = "2026-07"


def pid(app, username):
    with app.app_context():
        return db.session.query(Person).filter_by(username=username).one().id


def get_person(username):
    """Live Person row — call inside an app context."""
    return db.session.query(Person).filter_by(username=username).one()


def plant_leave(app, person_id, day, *, day_part=DayPart.FULL,
                status=RequestStatus.APPROVED):
    with app.app_context():
        db.session.add(
            LeaveRequest(
                person_id=person_id, type=LeaveType.OFF, start_date=day,
                end_date=day, day_part=day_part, status=status,
            )
        )
        db.session.commit()


def plant_status(app, person_id, start, end, *, in_camp, type_=StatusType.BRIEFING):
    with app.app_context():
        db.session.add(
            StatusEntry(
                person_id=person_id, type=type_, start_date=start, end_date=end,
                day_part=DayPart.FULL, in_camp=in_camp, created_by_id=person_id,
            )
        )
        db.session.commit()


def plant_event(app, owner_id, start_dt, end_dt, *, calendar=Calendar.TP,
                category=ParticipantCategory.NSF, title="TP exercise"):
    with app.app_context():
        event = Event(
            calendar=calendar, title=title, start_dt=start_dt, end_dt=end_dt,
            created_by_id=owner_id,
        )
        db.session.add(event)
        db.session.flush()
        db.session.add(EventParticipant(event_id=event.id, category=category, include=True))
        db.session.commit()


def plant_assignment(app, person_id, day, duty, *, state=DutyState.CONFIRMED):
    with app.app_context():
        row = DutyAssignment(
            date=day, duty=duty, person_id=person_id, state=state,
            created_by_id=person_id,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


# --- month_bounds --------------------------------------------------------------

def test_month_bounds():
    assert duty_service.month_bounds("2026-07") == (date(2026, 7, 1), date(2026, 7, 31))
    assert duty_service.month_bounds("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert duty_service.month_bounds("2028-02") == (date(2028, 2, 1), date(2028, 2, 29))
    with pytest.raises(ValueError):
        duty_service.month_bounds("garbage")
    with pytest.raises(ValueError):
        duty_service.month_bounds("2026-13")


# --- availability shaping ------------------------------------------------------

def test_availability_pm_half_day_blocks(app, make_person):
    make_person(username="cos_opr", rank=Rank.THREE_SG, appointment=Appointment.OPR)
    opr = pid(app, "cos_opr")
    plant_leave(app, opr, date(2026, 7, 15), day_part=DayPart.PM)

    with app.app_context():
        _pools, availability, _confirmed = duty_service.availability_for_month(JULY)
        person = get_person("cos_opr")
        # Decision (d): ANY day_part blocks auto-pick, even though the parade
        # engine counts a PM as present — the two deliberately disagree.
        assert availability(person, date(2026, 7, 15)) is False
        assert availability(person, date(2026, 7, 16)) is True


def test_availability_pending_leave_does_not_block(app, make_person):
    make_person(username="cos_opr", rank=Rank.THREE_SG, appointment=Appointment.OPR)
    opr = pid(app, "cos_opr")
    plant_leave(app, opr, date(2026, 7, 15), status=RequestStatus.PENDING_PC)

    with app.app_context():
        _pools, availability, _confirmed = duty_service.availability_for_month(JULY)
        assert availability(get_person("cos_opr"), date(2026, 7, 15)) is True


def test_availability_in_camp_status_does_not_block(app, make_person):
    make_person(username="cos_opr", rank=Rank.THREE_SG, appointment=Appointment.OPR)
    opr = pid(app, "cos_opr")
    plant_status(app, opr, date(2026, 7, 10), date(2026, 7, 12), in_camp=True)
    plant_status(app, opr, date(2026, 7, 20), date(2026, 7, 21), in_camp=False,
                 type_=StatusType.COURSE)

    with app.app_context():
        _pools, availability, _confirmed = duty_service.availability_for_month(JULY)
        person = get_person("cos_opr")
        # In camp is not away — a briefing can hold a duty.
        assert availability(person, date(2026, 7, 11)) is True
        # An out-of-camp course blocks.
        assert availability(person, date(2026, 7, 20)) is False


def test_availability_overnight_tp_event_blocks_day_event_does_not(app, make_person):
    make_person(username="cos_opr", rank=Rank.THREE_SG, appointment=Appointment.OPR)
    opr = pid(app, "cos_opr")
    # Overnight TP (2300 -> 0100 next day): blocks BOTH covered days.
    plant_event(app, opr, datetime(2026, 7, 20, 23, 0), datetime(2026, 7, 21, 1, 0))
    # Same-day TP 0800-1700: never blocks (overnight = end date after start date).
    plant_event(app, opr, datetime(2026, 7, 22, 8, 0), datetime(2026, 7, 22, 17, 0))
    # Overnight ARCTIC: contingency plan, not a scheduled conduct — never blocks.
    plant_event(app, opr, datetime(2026, 7, 23, 23, 0), datetime(2026, 7, 24, 1, 0),
                calendar=Calendar.ARCTIC)

    with app.app_context():
        _pools, availability, _confirmed = duty_service.availability_for_month(JULY)
        person = get_person("cos_opr")
        assert availability(person, date(2026, 7, 20)) is False
        assert availability(person, date(2026, 7, 21)) is False
        assert availability(person, date(2026, 7, 22)) is True
        assert availability(person, date(2026, 7, 23)) is True
        assert availability(person, date(2026, 7, 24)) is True


def test_availability_confirmed_assignment_blocks_same_date(app, make_person):
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS)
    ps = pid(app, "ps2")
    plant_assignment(app, ps, date(2026, 7, 10), Duty.CDOS, state=DutyState.CONFIRMED)
    plant_assignment(app, ps, date(2026, 7, 12), Duty.CDOS, state=DutyState.PROPOSED)

    with app.app_context():
        _pools, availability, confirmed = duty_service.availability_for_month(JULY)
        person = get_person("ps2")
        assert availability(person, date(2026, 7, 10)) is False
        # A PROPOSED draft never blocks — only the roster of record does.
        assert availability(person, date(2026, 7, 12)) is True
        assert [r.id for r in confirmed] == [
            r.id for r in db.session.query(DutyAssignment).filter_by(
                state=DutyState.CONFIRMED
            ).all()
        ]


def test_pools_shape(app, make_person):
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD)
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS, platoon=2)
    make_person(username="ps3", rank=Rank.THREE_SG, appointment=Appointment.PS, platoon=3)

    with app.app_context():
        pools, _availability, _confirmed = duty_service.availability_for_month(JULY)
        assert set(pools) == set(Duty)
        assert [p.username for p in pools[Duty.COS]] == ["det1"]
        assert [p.username for p in pools[Duty.CDOS]] == ["ps2"]
        # The known gap: a 3SG PS satisfies neither rule and appears in NO pool.
        for members in pools.values():
            assert "ps3" not in [p.username for p in members]
