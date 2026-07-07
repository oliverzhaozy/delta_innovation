"""P3b.6 (pre-flight addendum A2) — parade_service.build_doc.

One function owns the presence_inputs -> categorize/compute -> render pipeline
(and, from P4.7 on, the duty_day offset convention). Before it existed the
pipeline was re-derived at six route call sites — an offset convention added at
five of six sites would make the page and the archival snapshot silently
diverge. Hence the permanent invariant pinned here: for every variant, the
finalize route's stored text equals the GET page's rendered text for identical
inputs.
"""
import html
import re
from datetime import date

from app.domain import parade as parade_domain
from app.domain.types import Appointment, ParadeVariant, StatusType
from app.extensions import db
from app.models import ParadeSnapshot, Person, StatusEntry
from app.services import parade_service, presence_service
from tests.conftest import login

DAY = date(2026, 7, 8)  # Wednesday — same convention as the other parade tests


def _person(app, username):
    with app.app_context():
        return db.session.query(Person).filter_by(username=username).one()


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
    make_person(username="off_guy", display_name="CFC Daniel Lim")
    _plant_mc(app, "off_guy")
    with app.app_context():
        pairs = presence_service.presence_inputs(DAY)
        expected = parade_domain.render_morning(parade_domain.categorize(DAY, pairs, "morning"))
        built = parade_service.build_doc(DAY, ParadeVariant.MORNING)
        assert built.text == expected
        assert built.doc is not None
        assert len(built.pairs) == len(pairs)


def test_build_doc_roll_call_matches_domain_pipeline(app, make_person):
    make_person(username="off_guy", display_name="CFC Daniel Lim")
    _plant_mc(app, "off_guy")
    with app.app_context():
        pairs = presence_service.presence_inputs(DAY)
        expected = parade_domain.render_roll_call(parade_domain.categorize(DAY, pairs, "roll_call"))
        built = parade_service.build_doc(DAY, ParadeVariant.ROLL_CALL)
        assert built.text == expected


def test_build_doc_cos_message_uses_cos_person(app, make_person):
    make_person(username="cos_guy", appointment=Appointment.OPR, display_name="CPL Marcus Tan")
    make_person(username="off_guy", display_name="CFC Daniel Lim")
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


# --- permanent invariant: page text == finalized snapshot text ----------------

def _pre_text(page_data: bytes) -> str:
    m = re.search(rb'<pre id="[^"]*"[^>]*>(.*?)</pre>', page_data, re.S)
    assert m, "page rendered no document <pre>"
    return html.unescape(m.group(1).decode())


def _latest_snapshot_text(app, variant):
    with app.app_context():
        snap = (
            db.session.query(ParadeSnapshot)
            .filter_by(variant=variant)
            .order_by(ParadeSnapshot.id.desc())
            .first()
        )
        assert snap is not None
        return snap.rendered_text


def test_page_equals_snapshot_morning(app, client, make_person):
    make_person(username="ps_keyer", appointment=Appointment.PS)
    make_person(username="off_guy", display_name="CFC Daniel Lim")
    _plant_mc(app, "off_guy")
    login(client, "ps_keyer")

    page = client.get(f"/parade/morning?date={DAY.isoformat()}")
    client.post("/parade/morning/finalize", data={"date": DAY.isoformat()})
    assert _pre_text(page.data) == _latest_snapshot_text(app, ParadeVariant.MORNING)


def test_page_equals_snapshot_roll_call(app, client, make_person):
    make_person(username="ps_keyer", appointment=Appointment.PS)
    make_person(username="off_guy", display_name="CFC Daniel Lim")
    _plant_mc(app, "off_guy")
    login(client, "ps_keyer")

    page = client.get(f"/parade/roll-call?date={DAY.isoformat()}")
    client.post("/parade/roll-call/finalize", data={"date": DAY.isoformat()})
    assert _pre_text(page.data) == _latest_snapshot_text(app, ParadeVariant.ROLL_CALL)


def test_page_equals_snapshot_cos_message(app, client, make_person):
    make_person(username="ps_keyer", appointment=Appointment.PS)
    make_person(username="off_guy", display_name="CFC Daniel Lim")
    _plant_mc(app, "off_guy")
    login(client, "ps_keyer")
    keyer = _person(app, "ps_keyer")

    page = client.get(f"/parade/cos-message?date={DAY.isoformat()}&cos={keyer.id}")
    client.post(
        "/parade/cos-message/finalize", data={"date": DAY.isoformat(), "cos": str(keyer.id)}
    )
    assert _pre_text(page.data) == _latest_snapshot_text(app, ParadeVariant.COS_MESSAGE)
