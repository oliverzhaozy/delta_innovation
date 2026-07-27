"""P9.4 — ON COURSE derived from the TP calendar.

There is no course table and no course status: a TP event labelled
`TpLabel.ON_COURSE` makes every one of its resolved participants out of camp for
every DATE the event covers (clock times ignored — owner decision 3). These tests
pin the day rule, the precedence position (a keyed status beats a derived course,
a course beats stay-out), the category mapping, and the fact that every downstream
consumer of the shared fetch inherits it: the away panel, duty availability, the
duty absent-holder flag, manning conflicts, and the NSF meal counters. The
month-calendar NSF OFF/LEAVE layer must NOT: it filters on source == "leave".
"""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.domain import manning
from app.domain.dates import format_ddmmyy_range
from app.domain.events import event_days
from app.domain.parade import _absent_category, parade_line
from app.domain.presence import PresenceState, resolve
from app.domain.types import (
    Appointment,
    ArcticLabel,
    Calendar,
    CourseAbsenceType,
    DayPart,
    Duty,
    DutyState,
    LeaveType,
    ParadeVariant,
    ParticipantCategory,
    Rank,
    RequestStatus,
    Service,
    StatusType,
    TpLabel,
)
from app.extensions import db
from app.models import (
    DutyAssignment,
    Event,
    EventParticipant,
    LeaveRequest,
    ManningPeriod,
    Person,
)
from app.services import duty_service, manning_service, meal_service, parade_service, presence_service

DAY = date(2026, 8, 5)  # a Wednesday
NEXT = DAY + timedelta(days=1)


# --- planting helpers -------------------------------------------------------

def plant_course(app, *, title="Sig Course", start_dt=None, end_dt=None,
                 people=(), categories=(), excluded=(), label=TpLabel.ON_COURSE.value,
                 calendar=Calendar.TP):
    """A TP event carrying the course label, with person and/or category
    participant rows. `excluded` adds include=False person rows (the S3 carve-out
    from a category)."""
    start_dt = start_dt or datetime.combine(DAY, datetime.min.time())
    end_dt = end_dt or datetime(DAY.year, DAY.month, DAY.day, 23, 59)
    with app.app_context():
        actor = db.session.query(Person.id).first()[0]
        event = Event(calendar=calendar, title=title, start_dt=start_dt, end_dt=end_dt,
                      label=label, created_by_id=actor)
        db.session.add(event)
        db.session.flush()
        for username in people:
            pid = db.session.query(Person.id).filter_by(username=username).scalar()
            db.session.add(EventParticipant(event_id=event.id, person_id=pid, include=True))
        for category in categories:
            db.session.add(EventParticipant(event_id=event.id, category=category, include=True))
        for username in excluded:
            pid = db.session.query(Person.id).filter_by(username=username).scalar()
            db.session.add(EventParticipant(event_id=event.id, person_id=pid, include=False))
        db.session.commit()
        return event.id


def plant_leave(app, username, *, start=DAY, end=DAY, type_=LeaveType.OFF):
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(LeaveRequest(person_id=pid, type=type_, start_date=start, end_date=end,
                                    day_part=DayPart.FULL, status=RequestStatus.APPROVED))
        db.session.commit()


def cover(start=DAY, end=DAY):
    """A course cover shaped exactly as presence_service synthesizes one."""
    return presence_service._CourseCover(
        id=1, person=None, person_id=1, type=CourseAbsenceType.COURSE,
        start_date=start, end_date=end, day_part=DayPart.FULL, remarks="Sig Course",
    )


def person_like(service=Service.NSF, stay_out=False, is_active=True):
    return SimpleNamespace(is_active=is_active, stay_out=stay_out, service=service)


def course_suffix(start=DAY, end=DAY, title="Sig Course"):
    """The suffix every ON COURSE line carries (owner 2026-07-27): the TP event
    title uppercased, then the DATES the event covers — the span `event_days`
    derives, not the clock times."""
    return f"({title.upper()}: {format_ddmmyy_range(start, end)})"


def leave_like(start=DAY, end=DAY, type_=LeaveType.OFF):
    return SimpleNamespace(type=type_, start_date=start, end_date=end, day_part=DayPart.FULL)


def status_like(type_=StatusType.MC, start=DAY, end=DAY, in_camp=False):
    return SimpleNamespace(type=type_, start_date=start, end_date=end,
                           day_part=DayPart.FULL, in_camp=in_camp)


# --- event_days: the ONE owner of the times-ignored rule --------------------

def test_event_days_ignores_clock_times_and_covers_both_calendar_days():
    # 23:00 on D to 01:00 on D+1 — two minutes of the second day, but the rule is
    # dates only, so BOTH days are fully covered (owner decision 3).
    first, last = event_days(datetime(2026, 8, 5, 23, 0), datetime(2026, 8, 6, 1, 0))
    assert (first, last) == (date(2026, 8, 5), date(2026, 8, 6))


def test_event_days_single_day_and_month_rollover():
    assert event_days(datetime(2026, 8, 5, 8, 0), datetime(2026, 8, 5, 17, 0)) == (DAY, DAY)
    assert event_days(datetime(2026, 8, 31, 8, 0), datetime(2026, 9, 2, 9, 0)) == (
        date(2026, 8, 31), date(2026, 9, 2),
    )


# --- the pure engine: mapping and precedence -------------------------------

def test_absent_category_maps_a_course_cover_to_on_course():
    assert _absent_category(cover()) == "on_course"


def test_a_covering_course_makes_absent():
    res = resolve(person_like(), DAY, courses=[cover()])
    assert res.state is PresenceState.ABSENT
    assert res.row.type is CourseAbsenceType.COURSE


def test_a_non_covering_course_does_nothing():
    res = resolve(person_like(), DAY, courses=[cover(start=NEXT, end=NEXT)])
    assert res.state is PresenceState.PRESENT
    assert res.conflicts == ()


def test_leave_beats_course_and_the_course_surfaces_as_a_conflict():
    lv = leave_like()
    c = cover()
    res = resolve(person_like(), DAY, leaves=[lv], courses=[c])
    assert res.row is lv
    assert res.conflicts == (c,)


def test_out_of_camp_status_beats_course_and_the_course_surfaces_as_a_conflict():
    # The COS keyed the MC deliberately; the course cover is inferred, so the
    # keyed row wins — but nothing it hid is dropped.
    mc = status_like()
    c = cover()
    res = resolve(person_like(), DAY, statuses=[mc], courses=[c])
    assert res.row is mc
    assert res.conflicts == (c,)


def test_course_beats_stay_out_so_a_regular_participant_lands_on_course():
    res = resolve(person_like(service=Service.REGULAR), DAY, courses=[cover()])
    assert res.state is PresenceState.ABSENT
    assert _absent_category(res.row) == "on_course"


def test_course_beats_duty():
    duty_cover = SimpleNamespace(start_date=DAY, end_date=DAY)
    res = resolve(person_like(), DAY, courses=[cover()], duties=[duty_cover])
    assert res.state is PresenceState.ABSENT


# --- through build_doc: the participant prints under ON COURSE --------------

def _cast(make_person):
    make_person(username="crs_ps", appointment=Appointment.PS, rank=Rank.TWO_SG,
                display_name="Keyer Ps")
    make_person(username="crs_go", display_name="Goes Oncourse", platoon=2)
    make_person(username="crs_stay", display_name="Stays Back", platoon=2)


@pytest.mark.parametrize("variant", list(ParadeVariant))
def test_participant_appears_under_on_course_on_every_variant(app, make_person, variant):
    _cast(make_person)
    plant_course(app, people=["crs_go"])
    with app.app_context():
        cos = db.session.query(Person).filter_by(username="crs_ps").one()
        day = DAY
        built = parade_service.build_doc(day, variant, cos_display=parade_line(cos))
        assert built.imbalance is None
        line = f"PTE GOES ONCOURSE {course_suffix()}"
        assert built.doc.on_course == (line,)
        assert f"ON COURSE (1):\n1. {line}" in built.text
        assert "PTE STAYS BACK" not in built.doc.on_course


def test_a_category_participant_row_expands_to_its_members(app, make_person):
    _cast(make_person)
    plant_course(app, categories=[ParticipantCategory.PLATOON_2])
    with app.app_context():
        built = parade_service.build_doc(DAY, ParadeVariant.MORNING)
        assert set(built.doc.on_course) == {
            f"PTE GOES ONCOURSE {course_suffix()}",
            f"PTE STAYS BACK {course_suffix()}",
        }


def test_an_excluded_person_is_carved_out_of_the_category(app, make_person):
    _cast(make_person)
    plant_course(app, categories=[ParticipantCategory.PLATOON_2], excluded=["crs_stay"])
    with app.app_context():
        built = parade_service.build_doc(DAY, ParadeVariant.MORNING)
        assert built.doc.on_course == (f"PTE GOES ONCOURSE {course_suffix()}",)


def test_an_unlabelled_tp_event_is_not_a_course(app, make_person):
    _cast(make_person)
    plant_course(app, people=["crs_go"], label=None)
    with app.app_context():
        assert parade_service.build_doc(DAY, ParadeVariant.MORNING).doc.on_course == ()


def test_an_arctic_on_course_event_is_not_a_course(app, make_person):
    # ArcticLabel.ON_COURSE ("On Course") is a different string on a different
    # calendar — only TP's "Course" label drives the parade block.
    _cast(make_person)
    plant_course(app, people=["crs_go"], calendar=Calendar.ARCTIC,
                 label=ArcticLabel.ON_COURSE.value)
    with app.app_context():
        assert parade_service.build_doc(DAY, ParadeVariant.MORNING).doc.on_course == ()


def test_the_course_expires_with_its_date_range(app, make_person):
    _cast(make_person)
    plant_course(app, start_dt=datetime.combine(DAY, datetime.min.time()),
                 end_dt=datetime(DAY.year, DAY.month, DAY.day, 23, 0), people=["crs_go"])
    with app.app_context():
        assert parade_service.build_doc(DAY, ParadeVariant.MORNING).doc.on_course == (
            f"PTE GOES ONCOURSE {course_suffix()}",
        )
        # The next day is not covered — the participant is back in strength.
        after = parade_service.build_doc(NEXT, ParadeVariant.MORNING).doc
        assert after.on_course == ()
        assert "PTE GOES ONCOURSE" in after.current_strength


def test_a_night_straddling_course_covers_both_days(app, make_person):
    _cast(make_person)
    plant_course(app, start_dt=datetime(DAY.year, DAY.month, DAY.day, 23, 0),
                 end_dt=datetime(NEXT.year, NEXT.month, NEXT.day, 1, 0), people=["crs_go"])
    with app.app_context():
        # Both days quote the SAME span — the line reports the event's range,
        # not the day the document is for.
        line = f"PTE GOES ONCOURSE {course_suffix(end=NEXT)}"
        for day in (DAY, NEXT):
            doc = parade_service.build_doc(day, ParadeVariant.MORNING).doc
            assert doc.on_course == (line,), day


# --- downstream consumers of the shared fetch ------------------------------

def test_away_rows_carry_source_course_and_the_event_title_as_remarks(app, make_person):
    _cast(make_person)
    plant_course(app, title="Sig Specialist Course", people=["crs_go"])
    with app.app_context():
        rows = presence_service.absences_on(DAY)
        (row,) = [r for r in rows if r.source == "course"]
        assert row.label == "On course"
        assert row.remarks == "Sig Specialist Course"
        assert row.in_camp is False


def test_nsf_leave_calendar_layer_excludes_course_rows(app, make_person):
    _cast(make_person)
    plant_course(app, people=["crs_go"])
    plant_leave(app, "crs_stay")
    with app.app_context():
        layer = presence_service.nsf_leave_between(DAY, DAY)[DAY]
        assert {r.person.username for r in layer} == {"crs_stay"}


def test_duty_availability_is_false_while_on_course(app, make_person):
    make_person(username="crs_det", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD,
                display_name="Det Oncourse")
    plant_course(app, people=["crs_det"])
    with app.app_context():
        _pools, availability, _rows = duty_service.availability_for_month("2026-08")
        person = db.session.query(Person).filter_by(username="crs_det").one()
        assert availability(person, DAY) is False
        assert availability(person, NEXT) is True


def test_roster_flags_a_confirmed_holder_who_is_on_course(app, make_person):
    make_person(username="crs_det2", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD,
                display_name="Det Holder")
    plant_course(app, people=["crs_det2"])
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username="crs_det2").scalar()
        row = DutyAssignment(date=DAY, duty=Duty.COS, person_id=pid,
                             state=DutyState.CONFIRMED, created_by_id=pid)
        db.session.add(row)
        db.session.commit()
        assert row.id in duty_service.month_view("2026-08").absent_flags


def test_manning_conflict_is_flagged_for_a_course(app, make_person):
    make_person(username="crs_p2ic", rank=Rank.MSG, appointment=Appointment.P2IC,
                platoon=None, service=Service.REGULAR, display_name="Ptwoic Oncourse")
    plant_course(app, people=["crs_p2ic"])
    with app.app_context():
        period = ManningPeriod(
            start_date=DAY, end_date=DAY + timedelta(days=6),
            created_by_id=db.session.query(Person.id).first()[0],
        )
        db.session.add(period)
        db.session.commit()
        pid = db.session.query(Person.id).filter_by(username="crs_p2ic").scalar()
        status, reasons = manning_service.conflict_map(period)[pid]
        assert status is manning.ManningConflict.CONFLICT
        assert any("On course" in r for r in reasons)


def test_nsf_meal_counts_drop_when_an_nsf_goes_on_course(app, make_person):
    make_person(username="crs_m1", display_name="Meal One")
    make_person(username="crs_m2", display_name="Meal Two")
    with app.app_context():
        before, imbalance = meal_service.compute_for(DAY)
        assert imbalance is None
    plant_course(app, start_dt=datetime.combine(DAY, datetime.min.time()),
                 end_dt=datetime(NEXT.year, NEXT.month, NEXT.day, 12, 0), people=["crs_m1"])
    with app.app_context():
        after, imbalance = meal_service.compute_for(DAY)
        assert imbalance is None
        assert after.day_in_camp == before.day_in_camp - 1
        assert after.overnight == before.overnight - 1
