"""P5.2 — RO tables: the uniqueness backstops and the TBC-time shape."""
from datetime import date, time

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.types import RoRecurrence, RoSection
from app.extensions import db
from app.models import (
    RoBoilerplate, RoDocument, RoExtraItem, RoStandingItem, WeeklyKeyEvents,
)

D = date(2026, 6, 19)


def test_ro_document_date_unique(app):
    with app.app_context():
        db.session.add(RoDocument(date=D, messages=""))
        db.session.commit()
        db.session.add(RoDocument(date=D, messages="other"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_weekly_key_events_week_unique(app):
    monday = date(2026, 6, 15)
    with app.app_context():
        db.session.add(WeeklyKeyEvents(week_start=monday))
        db.session.commit()
        db.session.add(WeeklyKeyEvents(week_start=monday))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_boilerplate_section_unique(app):
    with app.app_context():
        db.session.add(RoBoilerplate(section=RoSection.SAFETY, content="- x"))
        db.session.commit()
        db.session.add(RoBoilerplate(section=RoSection.SAFETY, content="- y"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_extra_and_standing_items_allow_tbc(app):
    with app.app_context():
        doc = RoDocument(date=D, messages="")
        db.session.add(doc)
        db.session.flush()
        db.session.add(RoExtraItem(ro_document_id=doc.id, time=None, text="SBA"))
        db.session.add(RoExtraItem(ro_document_id=doc.id, time=time(18, 0), text="Report to site"))
        db.session.add(
            RoStandingItem(time=None, text="LP", recurrence=RoRecurrence.DAILY, position=20)
        )
        db.session.commit()
        assert db.session.query(RoExtraItem).filter_by(time=None).count() == 1


def test_ro_section_labels_match_the_format():
    assert [s.label for s in RoSection] == [
        "Safety Matters",
        "Administrative Matters",
        "Logistic Matters",
        "Security Matters",
        "R&D Matters",
        "Instructions",
    ]
