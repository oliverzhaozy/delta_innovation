"""P4.4 — services/duty_service.py: availability shaping, generation, the
weekday/holiday/blocked day rule, and blocked-day writes.

The pure modules (eligibility.py, roster.py) are already pinned by their own
suites; these tests exercise the glue — one shared absence fetch, the decision
(z) rule that TP events never block, and manual-row preservation across
regeneration.
"""
import pytest
from datetime import date, datetime

from app.domain import roster
from app.domain.types import (
    Appointment, Calendar, DayPart, Duty, LeaveType,
    ParticipantCategory, PlatoonCategory, Rank, RequestStatus, StatusType,
)
from app.extensions import db
from app.models import (
    DutyAssignment, DutyBlockedDay, Event, EventParticipant, LeaveRequest,
    Person, PublicHoliday, StatusEntry,
)
from app.services import duty_service, event_service, platoon_service

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


def plant_status(app, person_id, start, end, *, in_camp, type_=StatusType.OTHER):
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


def plant_assignment(app, person_id, day, duty, *, is_manual=True):
    with app.app_context():
        row = DutyAssignment(
            date=day, duty=duty, person_id=person_id, is_manual=is_manual,
            created_by_id=person_id,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def plant_holiday(app, day, name="Test Holiday"):
    with app.app_context():
        db.session.add(PublicHoliday(date=day, name=name))
        db.session.commit()


def plant_block(app, day, person_id):
    with app.app_context():
        db.session.add(DutyBlockedDay(date=day, created_by_id=person_id))
        db.session.commit()


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
        _pools, availability, _manual = duty_service.availability_for_month(JULY)
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
        _pools, availability, _manual = duty_service.availability_for_month(JULY)
        assert availability(get_person("cos_opr"), date(2026, 7, 15)) is True


def test_availability_in_camp_status_does_not_block(app, make_person):
    make_person(username="cos_opr", rank=Rank.THREE_SG, appointment=Appointment.OPR)
    opr = pid(app, "cos_opr")
    plant_status(app, opr, date(2026, 7, 10), date(2026, 7, 12), in_camp=True)
    plant_status(app, opr, date(2026, 7, 20), date(2026, 7, 21), in_camp=False,
                 type_=StatusType.OTHER)

    with app.app_context():
        _pools, availability, _manual = duty_service.availability_for_month(JULY)
        person = get_person("cos_opr")
        # In camp is not away — an in-camp status can hold a duty.
        assert availability(person, date(2026, 7, 11)) is True
        # An out-of-camp status blocks.
        assert availability(person, date(2026, 7, 20)) is False


def test_availability_ignores_tp_events(app, make_person):
    # Decision (z) 2026-07-28: no calendar event of any shape blocks a duty —
    # participants of a multi-day conduct are in camp and can still hold one.
    make_person(username="cos_opr", rank=Rank.THREE_SG, appointment=Appointment.OPR)
    opr = pid(app, "cos_opr")
    # Multi-day TP (2300 -> 0100 next day): both covered days stay available.
    plant_event(app, opr, datetime(2026, 7, 20, 23, 0), datetime(2026, 7, 21, 1, 0))
    # Same-day TP 0800-1700.
    plant_event(app, opr, datetime(2026, 7, 22, 8, 0), datetime(2026, 7, 22, 17, 0))
    # Multi-day ARCTIC: a contingency plan, never a blocker either.
    plant_event(app, opr, datetime(2026, 7, 23, 23, 0), datetime(2026, 7, 24, 1, 0),
                calendar=Calendar.ARCTIC)

    with app.app_context():
        _pools, availability, _manual = duty_service.availability_for_month(JULY)
        person = get_person("cos_opr")
        # Not vacuous: he really is tagged in all three planted events.
        assert [
            [p.username for p in event_service.resolve_participants(ev)]
            for ev in db.session.query(Event).all()
        ] == [["cos_opr"]] * 3
        for day in range(20, 25):
            assert availability(person, date(2026, 7, day)) is True


def test_availability_manual_assignment_blocks_same_date(app, make_person):
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS)
    ps = pid(app, "ps2")
    plant_assignment(app, ps, date(2026, 7, 10), Duty.CDOS, is_manual=True)
    plant_assignment(app, ps, date(2026, 7, 13), Duty.CDOS, is_manual=False)

    with app.app_context():
        _pools, availability, manual = duty_service.availability_for_month(JULY)
        person = get_person("ps2")
        assert availability(person, date(2026, 7, 10)) is False
        # An auto row is deleted and re-planned in the same transaction, so it
        # must NOT make its own holder unavailable for that slot.
        assert availability(person, date(2026, 7, 13)) is True
        assert [r.id for r in manual] == [
            r.id for r in db.session.query(DutyAssignment).filter_by(is_manual=True).all()
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


def auto_map(first, last):
    rows = (
        db.session.query(DutyAssignment)
        .filter(
            DutyAssignment.date >= first,
            DutyAssignment.date <= last,
            DutyAssignment.is_manual.is_(False),
        )
        .all()
    )
    return {(r.date, r.duty): r.person_id for r in rows}


def test_generate_writes_rows_and_matches_pure_module(app, make_person):
    make_duty_cast(make_person)

    with app.app_context():
        actor = get_person("det1")
        duty_service.generate_month(AUG, actor)

        first, last = duty_service.month_bounds(AUG)
        # Rebuild the same inputs by hand and run the pure generator directly:
        # the service's rows must equal the pure module's output exactly.
        pools, availability, _manual = duty_service.availability_for_month(AUG)
        days = duty_service.duty_days(first, last).active
        expected = {}
        for duty in Duty:
            expected.update(roster.generate(days, {duty: pools[duty]}, availability))
        expected = {k: v for k, v in expected.items() if v is not None}

        assert auto_map(first, last) == expected
        rows = db.session.query(DutyAssignment).all()
        assert rows and all(r.is_manual is False for r in rows)
        assert all(r.created_by_id == actor.id for r in rows)


def test_generate_plans_duty_days_only(app, make_person):
    # Weekends never appear; a public holiday and a blocked weekday are cut
    # from the same one list the grid draws.
    make_duty_cast(make_person)
    plant_holiday(app, date(2026, 8, 17), "Test Holiday")  # a Monday
    plant_block(app, date(2026, 8, 18), pid(app, "det1"))  # the Tuesday after

    with app.app_context():
        duty_service.generate_month(AUG, get_person("det1"))
        dates = {r.date for r in db.session.query(DutyAssignment).all()}
        assert all(d.weekday() < 5 for d in dates)
        assert date(2026, 8, 17) not in dates
        assert date(2026, 8, 18) not in dates
        assert dates == set(duty_service.duty_days(*duty_service.month_bounds(AUG)).active)


def test_regenerate_preserves_manual_and_replans_the_rest(app, make_person):
    make_duty_cast(make_person)
    x = pid(app, "det1")
    manual_id = plant_assignment(app, x, date(2026, 8, 10), Duty.COS, is_manual=True)

    with app.app_context():
        duty_service.generate_month(AUG, get_person("ps2"))

        row = db.session.get(DutyAssignment, manual_id)
        assert row.is_manual is True
        assert row.person_id == x
        assert row.date == date(2026, 8, 10)
        first, last = duty_service.month_bounds(AUG)
        auto = auto_map(first, last)
        # The manual slot was NOT re-planned...
        assert (date(2026, 8, 10), Duty.COS) not in auto
        # ...but the rest of the month was (both duties have candidates).
        assert (date(2026, 8, 11), Duty.COS) in auto
        assert (date(2026, 8, 10), Duty.CDOS) in auto


def test_generate_blank_days_have_no_row(app, make_person):
    # COS-eligible people only: the CDOS pool is empty and blanks are the
    # ABSENCE of a row, not a person_id=None row (column is NOT NULL).
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD)

    with app.app_context():
        duty_service.generate_month(AUG, get_person("det1"))
        cdos_rows = db.session.query(DutyAssignment).filter_by(duty=Duty.CDOS).count()
        assert cdos_rows == 0
        cos_rows = db.session.query(DutyAssignment).filter_by(duty=Duty.COS).count()
        assert cos_rows == 21  # every August WEEKDAY planned for the one candidate


def test_generate_fills_every_duty_day_despite_a_month_long_tp_event(app, make_person):
    # The symptom decision (z) fixed: a whole-company multi-day conduct (OSW
    # Manning) made every participant unavailable, so only the days it left
    # uncovered could be planned. Every active day must fill now.
    make_duty_cast(make_person)
    plant_event(app, pid(app, "det1"), datetime(2026, 8, 1, 8, 0),
                datetime(2026, 8, 31, 18, 0), title="OSW Manning")

    with app.app_context():
        event = db.session.query(Event).one()
        # The event really does cover the whole cast — without decision (z)
        # this fixture would leave the month blank.
        assert {p.username for p in event_service.resolve_participants(event)} == {
            "det1", "opr1", "ps2", "p2ic3",
        }

        duty_service.generate_month(AUG, get_person("det1"))
        first, last = duty_service.month_bounds(AUG)
        active = duty_service.duty_days(first, last).active
        assert set(auto_map(first, last)) == {(d, duty) for d in active for duty in Duty}


def test_generate_replaces_only_auto_rows(app, make_person):
    make_duty_cast(make_person)

    with app.app_context():
        first, last = duty_service.month_bounds(AUG)
        duty_service.generate_month(AUG, get_person("det1"))
        first_run = auto_map(first, last)
        duty_service.generate_month(AUG, get_person("det1"))
        second_run = auto_map(first, last)

        # Deterministic generator + identical inputs -> identical roster, and
        # exactly one row per slot (no duplicate accumulation).
        assert second_run == first_run
        total = db.session.query(DutyAssignment).count()
        assert total == len(second_run)


# --- duty_days: the one owner of "which dates carry a duty" ---------------------

SAT = date(2026, 8, 15)
MON_HOLIDAY = date(2026, 8, 17)
TUE_BLOCKED = date(2026, 8, 18)


def test_duty_days_splits_weekdays_from_active_days(app, make_person):
    make_duty_cast(make_person)
    plant_holiday(app, MON_HOLIDAY, "Test Holiday")
    plant_block(app, TUE_BLOCKED, pid(app, "det1"))

    with app.app_context():
        first, last = duty_service.month_bounds(AUG)
        days = duty_service.duty_days(first, last)
        assert len(days.weekdays) == 21 and SAT not in days.weekdays
        assert MON_HOLIDAY in days.weekdays and TUE_BLOCKED in days.weekdays
        assert days.holidays == {MON_HOLIDAY: "Test Holiday"}
        assert days.blocked == frozenset({TUE_BLOCKED})
        assert days.active == [
            d for d in days.weekdays if d not in (MON_HOLIDAY, TUE_BLOCKED)
        ]


# --- manual assignment on a non-duty day is LAW, not a warning ------------------

def assign_on(day, username, duty=Duty.COS):
    duty_service.assign(
        day, duty, get_person(username),
        actor=get_person(username), override_availability=True,
    )


def test_assign_on_weekend_holiday_or_blocked_day_hard_fails(app, make_person):
    make_duty_cast(make_person)
    plant_holiday(app, MON_HOLIDAY, "Test Holiday")
    plant_block(app, TUE_BLOCKED, pid(app, "det1"))

    with app.app_context():
        for day in (SAT, MON_HOLIDAY, TUE_BLOCKED):
            with pytest.raises(duty_service.IneligibleAssignment):
                assign_on(day, "det1")
        assert db.session.query(DutyAssignment).count() == 0
        # ...and the working day beside them still takes the assignment.
        assign_on(date(2026, 8, 19), "det1")
        assert db.session.query(DutyAssignment).one().is_manual is True


# --- blocking a day ------------------------------------------------------------

def test_block_deletes_that_date_s_assignments_in_one_transaction(app, make_person):
    make_duty_cast(make_person)
    day = date(2026, 8, 19)  # a Wednesday
    plant_assignment(app, pid(app, "det1"), day, Duty.COS)
    plant_assignment(app, pid(app, "ps2"), day, Duty.CDOS)
    plant_assignment(app, pid(app, "det1"), date(2026, 8, 20), Duty.COS)

    with app.app_context():
        removed = duty_service.block_day(day, get_person("ps2"))
        # Stored-value order, the same one every duty query uses.
        assert removed == ["CDO/S: 2SG Ps2", "COS: 3SG Det1"]
        assert db.session.query(DutyBlockedDay).one().date == day
        # Only that date's rows went; the next day's holder is untouched.
        remaining = db.session.query(DutyAssignment).all()
        assert [r.date for r in remaining] == [date(2026, 8, 20)]
        assert day not in duty_service.duty_days(day, day).active


def test_block_rejects_weekends_holidays_and_a_second_block(app, make_person):
    make_duty_cast(make_person)
    plant_holiday(app, MON_HOLIDAY, "Test Holiday")

    with app.app_context():
        actor = get_person("ps2")
        with pytest.raises(duty_service.NotBlockable):
            duty_service.block_day(SAT, actor)
        with pytest.raises(duty_service.NotBlockable):
            duty_service.block_day(MON_HOLIDAY, actor)
        duty_service.block_day(TUE_BLOCKED, actor)
        with pytest.raises(duty_service.NotBlockable):
            duty_service.block_day(TUE_BLOCKED, actor)
        assert db.session.query(DutyBlockedDay).count() == 1


def test_unblock_reports_whether_anything_was_blocked(app, make_person):
    make_duty_cast(make_person)

    with app.app_context():
        duty_service.block_day(TUE_BLOCKED, get_person("ps2"))
        assert duty_service.unblock_day(TUE_BLOCKED) is True
        assert duty_service.unblock_day(TUE_BLOCKED) is False
        assert db.session.query(DutyBlockedDay).count() == 0
        assert TUE_BLOCKED in duty_service.duty_days(TUE_BLOCKED, TUE_BLOCKED).active


# --- decision (ee): a platoon excused the COS pool ------------------------------

def excuse_platoon(number, category=PlatoonCategory.STC):
    """Map `number` to a category that is OUT of the COS pool. Call inside an
    app context."""
    platoon_service.set_categories({category: (number, False)})


def test_generation_never_picks_an_excused_platoon(app, make_person):
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD,
                platoon=1)
    make_person(username="opr2", rank=Rank.CPL, appointment=Appointment.OPR, platoon=2)

    with app.app_context():
        excuse_platoon(2)
        duty_service.generate_month(AUG, get_person("det1"))
        holders = {r.person_id for r in db.session.query(DutyAssignment).all()}
        assert holders == {get_person("det1").id}


def test_excused_platoon_leaves_the_auto_pool_but_stays_assignable(app, make_person):
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD,
                platoon=1)
    make_person(username="opr2", rank=Rank.CPL, appointment=Appointment.OPR, platoon=2)
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS, platoon=2)

    with app.app_context():
        excuse_platoon(2)
        pools, _availability, _manual = duty_service.availability_for_month(AUG)
        assert [p.username for p in pools[Duty.COS]] == ["det1"]
        # CDO/S is NEVER platoon-filtered: the toggle is about COS, and platoon
        # 2's PS does CDO/S regardless.
        assert [p.username for p in pools[Duty.CDOS]] == ["ps2"]

        view = duty_service.month_view(AUG)
        assert [p.username for p in view.pools[Duty.COS]] == ["det1"]
        # The unfiltered pool is what keeps the excused man keyable-with-a-warning.
        assert [p.username for p in view.assignable_pools[Duty.COS]] == ["det1", "opr2"]


def test_manual_assign_of_an_excused_platoon_warns_then_succeeds(app, make_person):
    make_person(username="opr2", rank=Rank.CPL, appointment=Appointment.OPR, platoon=2)
    make_person(username="ps3", rank=Rank.TWO_SG, appointment=Appointment.PS, platoon=3)
    day = date(2026, 8, 5)

    with app.app_context():
        excuse_platoon(2)
        with pytest.raises(duty_service.NeedsAvailabilityConfirm) as caught:
            duty_service.assign(
                day, Duty.COS, get_person("opr2"),
                actor=get_person("ps3"), override_availability=False,
            )
        # Soft warning, NOT duty_exempt's hard block: the reason names the
        # platoon and its category, and the confirm goes through.
        assert caught.value.reasons == [
            "Platoon 2 (STC) is excluded from the COS pool"
        ]
        assert db.session.query(DutyAssignment).count() == 0

        row = duty_service.assign(
            day, Duty.COS, get_person("opr2"),
            actor=get_person("ps3"), override_availability=True,
        )
        assert row.is_manual is True
        assert row.person_id == get_person("opr2").id


def test_cdos_assignment_from_an_excused_platoon_does_not_even_warn(app, make_person):
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS, platoon=2)

    with app.app_context():
        excuse_platoon(2)
        row = duty_service.assign(
            date(2026, 8, 5), Duty.CDOS, get_person("ps2"),
            actor=get_person("ps2"), override_availability=False,
        )
        assert row.duty is Duty.CDOS


def test_spread_violations_ignore_an_excused_platoon(app, make_person):
    # A man sitting at zero picks is exactly what the spread rule surfaces — but
    # an EXCUSED man is not in the auto pool at all, so he must not count.
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD,
                platoon=1)
    make_person(username="det2", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD,
                platoon=2)

    with app.app_context():
        excuse_platoon(2)
        duty_service.generate_month(AUG, get_person("det1"))
        view = duty_service.month_view(AUG)
        assert [p.username for p in view.pools[Duty.COS]] == ["det1"]
        assert Duty.COS not in view.violations.spread
        # Not vacuous: the very same rows DO breach once platoon 2 is back in
        # the pool — det1 holds all 21 weekdays and det2 none.
        platoon_service.set_categories({PlatoonCategory.STC: (2, True)})
        assert duty_service.month_view(AUG).violations.spread[Duty.COS] == (0, 21)


def test_pools_shape(app, make_person):
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD)
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS, platoon=2)
    make_person(username="ps3", rank=Rank.THREE_SG, appointment=Appointment.PS, platoon=3)

    with app.app_context():
        pools, _availability, _manual = duty_service.availability_for_month(JULY)
        assert set(pools) == set(Duty)
        assert [p.username for p in pools[Duty.COS]] == ["det1"]
        assert [p.username for p in pools[Duty.CDOS]] == ["ps2"]
        # The known gap: a 3SG PS satisfies neither rule and appears in NO pool.
        for members in pools.values():
            assert "ps3" not in [p.username for p in members]


# --- last-done map + the month_view fields the pages read (priority counters) -----

def plant_duty(app, username, day, duty=Duty.COS):
    with app.app_context():
        person_id = get_person(username).id
        db.session.add(DutyAssignment(
            date=day, duty=duty, person_id=person_id, is_manual=True,
            created_by_id=person_id,
        ))
        db.session.commit()


def test_last_duty_dates_is_the_max_per_person_per_duty(app, make_person):
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD)
    make_person(username="opr2", rank=Rank.CPL, appointment=Appointment.OPR, platoon=2)
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS, platoon=2)
    plant_duty(app, "det1", date(2026, 7, 6))
    plant_duty(app, "det1", date(2026, 7, 20))     # the later one wins
    plant_duty(app, "det1", date(2026, 7, 8))
    plant_duty(app, "ps2", date(2026, 7, 7), duty=Duty.CDOS)

    with app.app_context():
        last = duty_service.last_duty_dates()
        # Both duties are always keys, even with no rows at all for one of them.
        assert set(last) == set(Duty)
        assert last[Duty.COS] == {get_person("det1").id: date(2026, 7, 20)}
        assert last[Duty.CDOS] == {get_person("ps2").id: date(2026, 7, 7)}
        # A real date object, not the string SQLite stores.
        assert isinstance(last[Duty.COS][get_person("det1").id], date)
        # Never-done people are ABSENT from the map, not zero-dated.
        assert get_person("opr2").id not in last[Duty.COS]


def test_last_duty_dates_counts_future_rows(app, make_person):
    # A turn already on the books is a turn: the map must see next month's row,
    # which is what sinks that person down the priority ranking.
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD)
    plant_duty(app, "det1", date(2026, 12, 1))

    with app.app_context():
        assert duty_service.last_duty_dates()[Duty.COS] == {
            get_person("det1").id: date(2026, 12, 1)
        }


def test_month_view_priority_ranks_the_auto_pool_and_dropdowns_the_assignable_one(
    app, make_person
):
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD,
                platoon=1)
    make_person(username="opr2", rank=Rank.CPL, appointment=Appointment.OPR, platoon=2)
    plant_duty(app, "det1", date(2026, 7, 6))

    with app.app_context():
        excuse_platoon(2)
        view = duty_service.month_view(JULY)
        # The panel describes the rotation the GENERATOR runs, so the excused
        # platoon is absent from it...
        assert [(p.username, last) for p, last in view.priority[Duty.COS]] == [
            ("det1", date(2026, 7, 6))
        ]
        # ...while the dropdown keeps them, never-done first.
        assert [(p.username, last) for p, last in view.assignable_priority[Duty.COS]] == [
            ("opr2", None), ("det1", date(2026, 7, 6)),
        ]
        assert view.priority[Duty.CDOS] == []


def test_month_view_unavailable_marks_cover_the_assignable_pool(app, make_person):
    # The ⚠ mark must reach an EXCUSED person too — they are still keyable, so
    # the warning has to be visible before the click, not only after it.
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD,
                platoon=1)
    make_person(username="opr2", rank=Rank.CPL, appointment=Appointment.OPR, platoon=2)
    away = date(2026, 7, 8)
    plant_leave(app, pid(app, "opr2"), away)
    plant_leave(app, pid(app, "det1"), date(2026, 7, 9))

    with app.app_context():
        excuse_platoon(2)
        view = duty_service.month_view(JULY)
        assert (get_person("opr2").id, away) in view.unavailable
        assert (get_person("det1").id, date(2026, 7, 9)) in view.unavailable
        assert (get_person("det1").id, away) not in view.unavailable
        # Weekends and holidays are not duty days, so they carry no mark at all.
        assert not any(d.weekday() >= 5 for _person_id, d in view.unavailable)
