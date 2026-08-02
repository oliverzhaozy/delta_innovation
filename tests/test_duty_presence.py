"""P4.7 — duties feed presence and parades through the one build_doc pipeline.
The A3 trap pinned here: the adapter row handed to the engine covers the
RESOLUTION day (duty_day is only the fetch key), so the roll call labeled D
really counts the duty of D−1 on day D.

Meals dropped out of this pipe on 2026-07-30 (decision (cc)): the indent is the
morning(D) day count alone, so no duty assignment reaches it.
"""
import re
from datetime import date, timedelta

from app.domain.parade import parade_line
from app.domain.presence import PresenceState
from app.domain.types import (
    Appointment, DayPart, Duty, LeaveType, ParadeVariant, Rank,
    RequestStatus, Service,
)
from app.extensions import db
from app.models import DutyAssignment, LeaveRequest, Person
from app.services import parade_service, presence_service
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


def plant_duty(app, username, day, *, duty=Duty.COS):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(
            DutyAssignment(
                date=day, duty=duty, person_id=person_id, created_by_id=person_id,
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


def test_duty_row_reaches_resolution(app, make_person):
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


def test_morning_reads_duty_of_own_day(app, make_person):
    make_stay_out_opr(make_person)
    plant_duty(app, "cos_guy", D)

    with app.app_context():
        built = parade_service.build_doc(D, ParadeVariant.MORNING)
        assert pid(app, "cos_guy") in strength_ids(built)


def test_cos_message_reads_duty_of_previous_day(app, make_person):
    # Owner rule (2026-08-02): holding COS/CDO-S on D never drops a person from
    # the COS message for D — that message covers the night D−1→D, when D's
    # incoming crew still stays out. So the build reads the duty of D−1, the
    # same night the roll call labeled D covers.
    make_stay_out_opr(make_person)
    make_person(username="greeter", rank=Rank.TWO_SG, appointment=Appointment.DET_COMD)
    plant_duty(app, "cos_guy", D)

    with app.app_context():
        greeter = db.session.query(Person).filter_by(username="greeter").one()
        person_id = pid(app, "cos_guy")
        # COS message for D: his duty is D's, not D−1's — stay-out flag wins.
        built = parade_service.build_doc(
            D, ParadeVariant.COS_MESSAGE, cos_display=parade_line(greeter)
        )
        assert person_id in [p.id for p in built.doc.stay_out_people]
        # COS message for D+1 covers the night D→D+1 — now he IS the duty crew
        # in camp, omitted like PRESENT (this document requests statuses).
        built = parade_service.build_doc(
            D + timedelta(days=1), ParadeVariant.COS_MESSAGE,
            cos_display=parade_line(greeter),
        )
        assert "Cos Guy" not in built.text


# --- missing-duty page chrome (A7) --------------------------------------------------

NOTICE = "No confirmed duty for this night"


def test_roll_call_page_has_no_missing_duty_notice(app, client, make_person):
    # UI-20 (owner directive 2026-07-11) took the missing-duty notice off the
    # roll-call page, leaving it on the meals page; decision (cc) (2026-07-30)
    # removed it there too, so the notice exists nowhere — pinned here because
    # a duty-less night is exactly where it used to appear.
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS, platoon=2)
    make_stay_out_opr(make_person)
    login(client, "ps2")

    page = client.get("/parade/roll-call").get_data(as_text=True)
    assert NOTICE not in page
    # The document itself still renders on a duty-less night.
    assert re.search(r'<pre id="[^"]*"[^>]*>(.*?)</pre>', page, re.S)
