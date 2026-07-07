"""P4.4 — services/duty_service.py: availability shaping, generation, confirm.

The pure modules (eligibility.py, roster.py) are already pinned by their own
suites; these tests exercise the glue — one shared absence fetch, overnight-TP
resolution, CONFIRMED preservation, and the confirm fingerprint (A4).
"""
import pytest
from datetime import date, datetime

from app.domain import roster
from app.domain.dates import iter_days
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


# --- generate_month ------------------------------------------------------------

AUG = "2026-08"


def make_duty_cast(make_person):
    """2 COS-eligible + 2 CDOS-eligible people; returns their usernames."""
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD)
    make_person(username="opr1", rank=Rank.CPL, appointment=Appointment.OPR)
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS, platoon=2)
    make_person(username="p2ic3", rank=Rank.ONE_SG, appointment=Appointment.P2IC, platoon=3)
    return ["det1", "opr1", "ps2", "p2ic3"]


def proposed_map(first, last):
    rows = (
        db.session.query(DutyAssignment)
        .filter(
            DutyAssignment.date >= first,
            DutyAssignment.date <= last,
            DutyAssignment.state == DutyState.PROPOSED,
        )
        .all()
    )
    return {(r.date, r.duty): r.person_id for r in rows}


def test_generate_writes_proposed_and_matches_pure_module(app, make_person):
    make_duty_cast(make_person)

    with app.app_context():
        actor = get_person("det1")
        duty_service.generate_month(AUG, actor)

        first, last = duty_service.month_bounds(AUG)
        # Rebuild the same inputs by hand and run the pure generator directly:
        # the service's rows must equal the pure module's output exactly.
        pools, availability, _confirmed = duty_service.availability_for_month(AUG)
        days = list(iter_days(first, last))
        expected = {}
        for duty in Duty:
            expected.update(roster.generate(days, {duty: pools[duty]}, availability))
        expected = {k: v for k, v in expected.items() if v is not None}

        assert proposed_map(first, last) == expected
        rows = db.session.query(DutyAssignment).all()
        assert rows and all(r.state is DutyState.PROPOSED for r in rows)
        assert all(r.created_by_id == actor.id for r in rows)


def test_regenerate_preserves_confirmed_and_replans_rest(app, make_person):
    make_duty_cast(make_person)
    x = pid(app, "det1")
    confirmed_id = plant_assignment(app, x, date(2026, 8, 10), Duty.COS,
                                    state=DutyState.CONFIRMED)

    with app.app_context():
        duty_service.generate_month(AUG, get_person("ps2"))

        row = db.session.get(DutyAssignment, confirmed_id)
        assert row.state is DutyState.CONFIRMED
        assert row.person_id == x
        assert row.date == date(2026, 8, 10)
        first, last = duty_service.month_bounds(AUG)
        proposed = proposed_map(first, last)
        # The confirmed slot was NOT re-planned...
        assert (date(2026, 8, 10), Duty.COS) not in proposed
        # ...but the rest of the month was (both duties have candidates).
        assert (date(2026, 8, 11), Duty.COS) in proposed
        assert (date(2026, 8, 10), Duty.CDOS) in proposed


def test_generate_blank_days_have_no_row(app, make_person):
    # COS-eligible people only: the CDOS pool is empty and blanks are the
    # ABSENCE of a row, not a person_id=None row (column is NOT NULL).
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD)

    with app.app_context():
        duty_service.generate_month(AUG, get_person("det1"))
        cdos_rows = db.session.query(DutyAssignment).filter_by(duty=Duty.CDOS).count()
        assert cdos_rows == 0
        cos_rows = db.session.query(DutyAssignment).filter_by(duty=Duty.COS).count()
        assert cos_rows == 31  # every August day planned for the one candidate


def test_generate_replaces_only_proposed(app, make_person):
    make_duty_cast(make_person)

    with app.app_context():
        first, last = duty_service.month_bounds(AUG)
        duty_service.generate_month(AUG, get_person("det1"))
        first_run = proposed_map(first, last)
        duty_service.generate_month(AUG, get_person("det1"))
        second_run = proposed_map(first, last)

        # Deterministic generator + identical inputs -> identical roster, and
        # exactly one PROPOSED row per slot (no duplicate accumulation).
        assert second_run == first_run
        total = db.session.query(DutyAssignment).count()
        assert total == len(second_run)


# --- roster_fingerprint + confirm_month (A4) ------------------------------------

def test_confirm_flips_proposed_and_stamps(app, make_person):
    make_duty_cast(make_person)

    with app.app_context():
        duty_service.generate_month(AUG, get_person("det1"))
        actor = get_person("ps2")
        duty_service.confirm_month(AUG, actor, duty_service.roster_fingerprint(AUG))

        rows = db.session.query(DutyAssignment).all()
        assert rows and all(r.state is DutyState.CONFIRMED for r in rows)
        assert all(r.confirmed_by_id == actor.id for r in rows)
        assert all(r.confirmed_at is not None for r in rows)


def test_confirm_stale_fingerprint_aborts(app, make_person):
    make_duty_cast(make_person)

    with app.app_context():
        duty_service.generate_month(AUG, get_person("det1"))
        stale = duty_service.roster_fingerprint(AUG)

        # PS B edits one slot after PS A loaded the page: swap the holder to
        # the other COS candidate (UNIQUE(date, duty) untouched).
        row = db.session.query(DutyAssignment).filter_by(duty=Duty.COS).first()
        other = get_person("det1" if row.person_id == pid(app, "opr1") else "opr1")
        row.person_id = other.id
        db.session.commit()

        with pytest.raises(duty_service.RosterChanged):
            duty_service.confirm_month(AUG, get_person("ps2"), stale)
        rows = db.session.query(DutyAssignment).all()
        assert rows and all(r.state is DutyState.PROPOSED for r in rows)
        assert all(r.confirmed_by_id is None for r in rows)


def test_double_confirm_second_loses_cleanly(app, make_person):
    make_duty_cast(make_person)

    with app.app_context():
        duty_service.generate_month(AUG, get_person("det1"))
        fp = duty_service.roster_fingerprint(AUG)
        duty_service.confirm_month(AUG, get_person("ps2"), fp)
        stamped = {
            r.id: (r.confirmed_by_id, r.confirmed_at)
            for r in db.session.query(DutyAssignment).all()
        }

        # The same (now stale) fingerprint loses: nothing is PROPOSED anymore.
        with pytest.raises(duty_service.RosterChanged):
            duty_service.confirm_month(AUG, get_person("p2ic3"), fp)
        after = {
            r.id: (r.confirmed_by_id, r.confirmed_at)
            for r in db.session.query(DutyAssignment).all()
        }
        assert after == stamped


def test_confirm_does_not_touch_other_months(app, make_person):
    make_duty_cast(make_person)
    x = pid(app, "det1")
    plant_assignment(app, x, date(2026, 9, 5), Duty.COS, state=DutyState.PROPOSED)

    with app.app_context():
        duty_service.generate_month(AUG, get_person("det1"))
        duty_service.confirm_month(
            AUG, get_person("ps2"), duty_service.roster_fingerprint(AUG)
        )
        sept = (
            db.session.query(DutyAssignment)
            .filter_by(date=date(2026, 9, 5), duty=Duty.COS)
            .one()
        )
        assert sept.state is DutyState.PROPOSED
        assert sept.confirmed_by_id is None


def test_fingerprint_is_content_based(app, make_person):
    make_duty_cast(make_person)

    with app.app_context():
        duty_service.generate_month(AUG, get_person("det1"))
        before = duty_service.roster_fingerprint(AUG)
        # Same content -> same print (stability)...
        assert duty_service.roster_fingerprint(AUG) == before
        # ...single manual edit -> different print (A4's exact requirement).
        row = db.session.query(DutyAssignment).filter_by(duty=Duty.COS).first()
        other = get_person("det1" if row.person_id == pid(app, "opr1") else "opr1")
        row.person_id = other.id
        db.session.commit()
        assert duty_service.roster_fingerprint(AUG) != before


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
