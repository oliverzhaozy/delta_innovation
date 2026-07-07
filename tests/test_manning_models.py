"""P6.2 — manning tables: one-slot-per-person backstop, det_number shape,
and the document labels."""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.types import ManningSlotType
from app.extensions import db
from app.models import ManningPeriod, ManningSlot, Person

START, END = date(2026, 7, 5), date(2026, 7, 13)


def make_period(app, creator_id):
    period = ManningPeriod(start_date=START, end_date=END, created_by_id=creator_id)
    db.session.add(period)
    db.session.commit()
    return period


def test_one_slot_per_person_per_period(app, make_person):
    make_person(username="p2ic3", platoon=3)
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username="p2ic3").scalar()
        period = make_period(app, person_id)
        db.session.add(ManningSlot(
            period_id=period.id, slot=ManningSlotType.TU_DET_COMD,
            person_id=person_id, det_number=1,
        ))
        db.session.commit()
        db.session.add(ManningSlot(
            period_id=period.id, slot=ManningSlotType.DET_PERSONNEL,
            person_id=person_id, det_number=2,
        ))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_det_number_shape_is_pinned_by_check(app, make_person):
    make_person(username="oc1")
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username="oc1").scalar()
        period = make_period(app, person_id)
        # HQ slots carry no det_number...
        db.session.add(ManningSlot(
            period_id=period.id, slot=ManningSlotType.TU_COMD,
            person_id=person_id, det_number=1,
        ))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        # ...and det slots must carry one.
        db.session.add(ManningSlot(
            period_id=period.id, slot=ManningSlotType.DET_PERSONNEL,
            person_id=person_id, det_number=None,
        ))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_slot_labels_document_vs_ui():
    # The document prints "DET COMD" for the TU_DET_COMD slot — the trap is
    # in the real format, which is why the identifier stays distinct.
    assert ManningSlotType.TU_DET_COMD.label == "DET COMD"
    assert ManningSlotType.TU_DET_COMD.ui_label == "TU Det Comd (P2IC/PS)"
    assert [s.label for s in ManningSlotType] == [
        "TU COMD", "TU PLANNER", "DET COMD", "DET PERSONNEL",
    ]


def test_person_phone_is_optional(app, make_person):
    make_person(username="opr1")
    with app.app_context():
        person = db.session.query(Person).filter_by(username="opr1").one()
        assert person.phone is None
        person.phone = "9190 9702"
        db.session.commit()
