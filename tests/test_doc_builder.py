"""P3b.6 (pre-flight addendum A2) — parade_service.build_doc.

One function owns the presence_inputs -> categorize/compute -> render pipeline
(and, from P4.7 on, the duty_day offset convention). Before it existed the
pipeline was re-derived at several route call sites — an offset convention added
at some but not all of them would make the parade surfaces silently diverge.
Hence the invariant pinned here: for every variant, build_doc's text equals the
domain pipeline's render for identical inputs.
"""
from datetime import date

from app.domain import parade as parade_domain
from app.domain.types import Appointment, ParadeVariant, Rank, StatusType
from app.extensions import db
from app.models import Person, StatusEntry
from app.services import parade_service, presence_service

DAY = date(2026, 7, 8)  # Wednesday — same convention as the other parade tests


def _plant_mc(app, username, day=DAY):
    # A covering out-of-camp status makes every variant's document non-trivial,
    # so text comparisons exercise category lines, not just headers.
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(
            StatusEntry(
                person_id=person_id, type=StatusType.MC, start_date=day, end_date=day,
                in_camp=False, created_by_id=person_id,
            )
        )
        db.session.commit()


# --- build_doc: one owner for the pipeline -----------------------------------

def test_build_doc_morning_matches_domain_pipeline(app, make_person):
    make_person(username="off_guy", display_name="Daniel Lim", rank=Rank.CFC)
    _plant_mc(app, "off_guy")
    with app.app_context():
        pairs = presence_service.presence_inputs(DAY)
        expected = parade_domain.render_morning(parade_domain.categorize(DAY, pairs, "morning"))
        built = parade_service.build_doc(DAY, ParadeVariant.MORNING)
        assert built.text == expected
        assert built.doc is not None
        assert len(built.pairs) == len(pairs)


def test_build_doc_roll_call_matches_domain_pipeline(app, make_person):
    make_person(username="off_guy", display_name="Daniel Lim", rank=Rank.CFC)
    _plant_mc(app, "off_guy")
    with app.app_context():
        pairs = presence_service.presence_inputs(DAY)
        expected = parade_domain.render_roll_call(parade_domain.categorize(DAY, pairs, "roll_call"))
        built = parade_service.build_doc(DAY, ParadeVariant.ROLL_CALL)
        assert built.text == expected


def test_build_doc_cos_message_uses_cos_person(app, make_person):
    make_person(username="cos_guy", appointment=Appointment.OPR, display_name="Marcus Tan",
                rank=Rank.CPL)
    make_person(username="off_guy", display_name="Daniel Lim", rank=Rank.CFC)
    _plant_mc(app, "off_guy")
    with app.app_context():
        cos = db.session.query(Person).filter_by(username="cos_guy").one()
        pairs = presence_service.presence_inputs(DAY)
        expected = parade_domain.render_cos(parade_domain.compute_cos_message(DAY, cos, pairs))
        built = parade_service.build_doc(DAY, ParadeVariant.COS_MESSAGE, cos_person=cos)
        assert built.text == expected


def test_build_doc_imbalance_becomes_a_field_not_an_exception(app, make_person, monkeypatch):
    # The GET pages must keep rendering the conflicts panel (off .pairs) even
    # when the document is refused — so build_doc converts ParadeImbalance to
    # a value at the service boundary instead of losing pairs to a raise.
    make_person(username="off_guy")

    def _boom(day, pairs, variant):
        raise parade_domain.ParadeImbalance("induced for test")

    monkeypatch.setattr(parade_domain, "categorize", _boom)
    with app.app_context():
        built = parade_service.build_doc(DAY, ParadeVariant.MORNING)
        assert built.imbalance == "induced for test"
        assert built.text is None
        assert built.doc is None
        assert len(built.pairs) > 0  # conflicts panel still has its input


def test_build_doc_success_has_no_imbalance(app, make_person):
    make_person(username="off_guy")
    with app.app_context():
        built = parade_service.build_doc(DAY, ParadeVariant.MORNING)
        assert built.imbalance is None


def test_build_doc_cos_message_without_cos_person_raises(app, make_person):
    make_person(username="off_guy")
    with app.app_context():
        try:
            parade_service.build_doc(DAY, ParadeVariant.COS_MESSAGE)
        except ValueError:
            pass
        else:
            raise AssertionError("COS_MESSAGE without cos_person must raise ValueError")
