"""P4.5 + P4.6 — /duty/roster page, manual assignment, validated swaps.

Routes are thin wires over duty_service; these tests hit the real app so the
wiring, rights (view-for-all vs manage-for-PS), and the hard-block-vs-warn
split are pinned through actual responses, mirroring the parade page suites.
"""
from datetime import date

from app.domain.types import Appointment, Duty, DutyState, Rank
from app.extensions import db
from app.models import DutyAssignment, Person
from app.services import duty_service

AUG = "2026-08"


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def get_person(username):
    """Live Person row — call inside an app context."""
    return db.session.query(Person).filter_by(username=username).one()


def make_cos_pair(make_person):
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD)
    make_person(username="opr1", rank=Rank.CPL, appointment=Appointment.OPR)


# --- month_view ------------------------------------------------------------------

def test_month_view_blanks_derived_from_missing_rows(app, make_person):
    make_cos_pair(make_person)

    with app.app_context():
        duty_service.generate_month(AUG, get_person("det1"))
        hole = date(2026, 8, 15)
        (
            db.session.query(DutyAssignment)
            .filter_by(date=hole, duty=Duty.COS, state=DutyState.PROPOSED)
            .delete()
        )
        db.session.commit()

        view = duty_service.month_view(AUG)
        # Blanks are the ABSENCE of a row — month_view must fill the missing
        # (day, duty) slots with None before asking violations() to flag them.
        assert (hole, Duty.COS) in view.violations.blanks
        assert (hole, Duty.COS) not in view.by_slot
        assert view.first == date(2026, 8, 1)
        assert view.last == date(2026, 8, 31)
        assert len(view.days) == 31


def test_month_view_empty_pool_all_blank(app, make_person):
    make_cos_pair(make_person)  # nobody is CDOS-eligible

    with app.app_context():
        duty_service.generate_month(AUG, get_person("det1"))
        view = duty_service.month_view(AUG)
        assert view.pools[Duty.CDOS] == []
        for d in view.days:
            assert (d, Duty.CDOS) in view.violations.blanks
