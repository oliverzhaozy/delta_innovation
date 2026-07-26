"""P4.7 — CONFIRMED duties feed presence, parades, and meals through the one
build_doc pipeline. The A3 trap pinned here: the adapter row handed to the
engine covers the RESOLUTION day (duty_day is only the fetch key), so the roll
call labeled D really counts the duty of D−1 on day D.
"""
import re
from datetime import date, timedelta

from app.domain.parade import parade_line
from app.domain.presence import PresenceState
from app.domain.types import (
    Appointment, DayPart, Duty, DutyState, LeaveType, ParadeVariant, Rank,
    RequestStatus, Service,
)
from app.extensions import db
from app.models import DutyAssignment, LeaveRequest, Person
from app.services import meal_service, parade_service, presence_service
from tests.conftest import login

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


# --- build_doc owns the roll-call offset (A2) --------------------------------------

def strength_ids(built):
    return [p.id for p in built.doc.current_strength_people]


def test_roll_call_reads_duty_of_previous_day(app, make_person):
    make_stay_out_opr(make_person)
    plant_duty(app, "cos_guy", D)

    with app.app_context():
        person_id = pid(app, "cos_guy")
        # Roll call labeled D+1 covers the night D→D+1: the holder of D's duty
        # is counted present that night.
        built = parade_service.build_doc(D + timedelta(days=1), ParadeVariant.ROLL_CALL)
        assert person_id in strength_ids(built)
        # Roll call labeled D covers the night D−1→D — his duty hasn't started.
        built = parade_service.build_doc(D, ParadeVariant.ROLL_CALL)
        assert person_id not in strength_ids(built)


def test_morning_and_cos_read_duty_of_own_day(app, make_person):
    make_stay_out_opr(make_person)
    make_person(username="greeter", rank=Rank.TWO_SG, appointment=Appointment.DET_COMD)
    plant_duty(app, "cos_guy", D)

    with app.app_context():
        built = parade_service.build_doc(D, ParadeVariant.MORNING)
        assert pid(app, "cos_guy") in strength_ids(built)
        greeter = db.session.query(Person).filter_by(username="greeter").one()
        built = parade_service.build_doc(
            D, ParadeVariant.COS_MESSAGE, cos_display=parade_line(greeter)
        )
        # DUTY people are omitted like PRESENT — this document requests statuses.
        assert "Cos Guy" not in built.text


def test_meals_counters_follow_the_same_pipe(app, make_person):
    # A1's two pins, through meal_service.compute_for. The holder is a stay-out
    # NSF: without a duty he is not in any night's current strength.
    make_stay_out_opr(make_person)
    plant_duty(app, "cos_guy", D, duty=Duty.CDOS)

    with app.app_context():
        counts, imbalance = meal_service.compute_for(D)
        assert imbalance is None
        # overnight(D) reads roll_call(D+1) = the night D→D+1: counted exactly once.
        assert counts.overnight == 1
        counts, _imbalance = meal_service.compute_for(D - timedelta(days=1))
        # overnight(D-1) reads roll_call(D): his duty hasn't started that night.
        assert counts.overnight == 0

    plant_leave(app, "cos_guy", D, D + timedelta(days=1))
    with app.app_context():
        counts, imbalance = meal_service.compute_for(D)
        assert imbalance is None
        # Leave > duty, and nobody re-adds him downstream (A1's exact bug).
        assert counts.overnight == 0


# --- missing-duty page chrome (A7) --------------------------------------------------

NOTICE = "No confirmed duty for this night"


def notice_duties(html):
    """The duty labels named in the notice, or None when no notice rendered."""
    match = re.search(NOTICE + r":\s*(.*?)\s*—", html, re.S)
    return match.group(1) if match else None


def test_roll_call_page_has_no_missing_duty_notice(app, client, make_person):
    # UI-20 (owner directive 2026-07-11): the roll-call page no longer shows
    # the missing-duty notice — that chrome now lives on the meals page only.
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS, platoon=2)
    make_stay_out_opr(make_person)
    login(client, "ps2")

    page = client.get("/parade/roll-call").get_data(as_text=True)
    assert NOTICE not in page
    # The document itself still renders on a duty-less night.
    assert re.search(r'<pre id="[^"]*"[^>]*>(.*?)</pre>', page, re.S)


def test_meals_page_notice(app, client, make_person):
    make_person(username="s4", is_admin=True)
    make_stay_out_opr(make_person)
    login(client, "s4")

    # Meals for day D cover the night D→D+1 — one day later than roll_call(D).
    html = client.get(f"/meals?date={D.isoformat()}").get_data(as_text=True)
    assert notice_duties(html) == "COS, CDO/S"

    plant_duty(app, "cos_guy", D)
    html = client.get(f"/meals?date={D.isoformat()}").get_data(as_text=True)
    assert notice_duties(html) == "CDO/S"


def test_meals_notice_never_names_a_covered_duty(app, client, make_person):
    # The meals notice is derived chrome: once every duty for the night is
    # CONFIRMED, it disappears entirely rather than rendering an empty shell.
    make_person(username="s4b", is_admin=True)
    make_stay_out_opr(make_person)
    login(client, "s4b")

    plant_duty(app, "cos_guy", D, duty=Duty.COS)
    plant_duty(app, "cos_guy", D, duty=Duty.CDOS)
    html = client.get(f"/meals?date={D.isoformat()}").get_data(as_text=True)
    assert NOTICE not in html
