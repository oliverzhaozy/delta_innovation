"""P5.4 — ro_service: fetch-or-create, assembly over live rows, A9 rights.

A9's two-day rule: editing the RO dated D requires the CDOS of D or D−1 (the
compiling evening), fallback command team. Duty names come from rows dated D
only.
"""
from datetime import date, datetime, time, timedelta

from app.domain.events import all_day_bounds
from app.domain.types import (
    Appointment, Calendar, Duty, Rank, RoSection, Service, TpLabel,
)
from app.extensions import db
from app.models import (
    DutyAssignment, Event, Person, PublicHoliday, RoBoilerplate, RoDocument,
)
from app.services import ro_service

FRI = date(2026, 6, 19)


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def get_person(username):
    return db.session.query(Person).filter_by(username=username).one()


def plant_duty(app, username, day, *, duty=Duty.CDOS):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(
            DutyAssignment(
                date=day, duty=duty, person_id=person_id, created_by_id=person_id,
            )
        )
        db.session.commit()


def test_fetch_or_create_is_idempotent(app):
    with app.app_context():
        first = ro_service.fetch_or_create(FRI)
        second = ro_service.fetch_or_create(FRI)
        assert first.id == second.id
        assert db.session.query(RoDocument).count() == 1


def test_can_edit_ro_wide_fallback(app, make_person):
    # Decision (p): any command-team appointment edits any day's RO; the A9
    # duty window is subsumed (every CDO/S-eligible appointment is command
    # team) but its plumbing must not crash when a CDOS row exists.
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.P2IC, platoon=2)
    make_person(username="opr1", rank=Rank.CPL, appointment=Appointment.OPR)
    make_person(username="oc", rank=Rank.CPT, appointment=Appointment.OC,
                platoon=None, service=Service.REGULAR)
    plant_duty(app, "ps2", FRI)

    with app.app_context():
        holder, opr, oc = get_person("ps2"), get_person("opr1"), get_person("oc")
        for day in (FRI, FRI + timedelta(days=1), FRI + timedelta(days=9)):
            assert ro_service.can_edit_ro_for(holder, day) is True
            assert ro_service.can_edit_ro_for(oc, day) is True
            # An Opr can never hold CDO/S, so no path grants an Opr edit rights.
            assert ro_service.can_edit_ro_for(opr, day) is False


def test_build_assembles_duties_tp_and_derived_key_events(app, make_person):
    make_person(username="cdos_guy", rank=Rank.TWO_SG, appointment=Appointment.PS,
                platoon=2, display_name="Quek Jing Yu")
    make_person(username="cos_guy", rank=Rank.CPL, appointment=Appointment.OPR,
                display_name="Ang Cheng Ze")
    plant_duty(app, "cdos_guy", FRI, duty=Duty.CDOS)
    plant_duty(app, "cos_guy", FRI, duty=Duty.COS)

    with app.app_context():
        db.session.add(RoBoilerplate(section=RoSection.SAFETY, content="- Stay safe."))
        db.session.add(Event(
            calendar=Calendar.TP, title="Site Testing",
            start_dt=datetime(2026, 6, 19, 9, 0), end_dt=datetime(2026, 6, 19, 17, 0),
            created_by_id=pid(app, "cdos_guy"),
        ))
        db.session.add(Event(
            calendar=Calendar.ARCTIC, title="Contingency X",
            start_dt=datetime(2026, 6, 19, 10, 0), end_dt=datetime(2026, 6, 19, 12, 0),
            created_by_id=pid(app, "cdos_guy"),
        ))
        db.session.add(PublicHoliday(date=date(2026, 6, 17), name="Hari Raya Haji"))
        db.session.commit()

        doc = ro_service.build(FRI)
        assert doc.missing_duties == []
        assert "CDO/CDS: 2SG QUEK JING YU" in doc.text
        assert "COS: CPL ANG CHENG ZE" in doc.text
        assert "0900H\n- Site Testing" in doc.text
        assert "Contingency X" not in doc.text  # ARCTIC never enters the RO
        assert "- Stay safe." in doc.text
        # Key events derive from TP: the conduct on its day, the holiday's
        # name on its empty day, Garage Maintenance on the rest.
        assert "Fri - Site Testing" in doc.text
        assert "Wed - Hari Raya Haji" in doc.text
        assert "Mon - Garage Maintenance" in doc.text

        # The next day has no duty at all: placeholder + report.
        doc = ro_service.build(FRI + timedelta(days=1))
        assert "COS: [NO CONFIRMED DUTY]" in doc.text
        assert set(doc.missing_duties) == {"CDO/CDS", "COS"}


def test_course_events_excluded_from_timeline_and_key_events(app, make_person):
    # Owner 2026-07-28: a TP event labelled Course never enters the RO — not
    # the timeline, not the key events. The conduct spans Wed–Fri, so without
    # the filter it would surface in the built day's timeline AND on three
    # key-event lines.
    make_person(username="s3_guy", rank=Rank.TWO_SG, appointment=Appointment.PS,
                platoon=2, display_name="Quek Jing Yu")
    wed = date(2026, 6, 17)

    with app.app_context():
        author_id = pid(app, "s3_guy")
        db.session.add(Event(
            calendar=Calendar.TP, title="Signal Course",
            label=TpLabel.ON_COURSE.value,
            start_dt=datetime(2026, 6, 17, 8, 0), end_dt=datetime(2026, 6, 19, 17, 0),
            created_by_id=author_id,
        ))
        db.session.add(Event(
            calendar=Calendar.TP, title="Coy IPPT", label=TpLabel.IPPT.value,
            start_dt=datetime(2026, 6, 17, 9, 0), end_dt=datetime(2026, 6, 17, 12, 0),
            created_by_id=author_id,
        ))
        # NULL-label guard: SQL three-valued logic drops unlabeled rows from a
        # bare `!=` filter, so an unlabeled event is asserted present too.
        db.session.add(Event(
            calendar=Calendar.TP, title="Site Testing", label=None,
            start_dt=datetime(2026, 6, 17, 13, 0), end_dt=datetime(2026, 6, 17, 17, 0),
            created_by_id=author_id,
        ))
        db.session.commit()

        text = ro_service.build(wed).text
        assert "Signal Course" not in text
        assert "0900H\n- Coy IPPT" in text
        assert "1300H\n- Site Testing" in text
        assert "Wed - Coy IPPT, Site Testing" in text
        # The Course's remaining days fall back to the empty-day filler.
        assert "Thurs - Garage Maintenance" in text


def test_all_day_tp_event_renders_tbc_through_build(app, make_person):
    # Owner 2026-07-28: an all-day conduct starting on the RO's day carries no
    # keyed timing, so it prints under TBC — never the 0000H its stored bounds
    # would otherwise imply.
    make_person(username="s3_all_day", rank=Rank.TWO_SG, appointment=Appointment.PS,
                platoon=2, display_name="Quek Jing Yu")

    with app.app_context():
        start_dt, end_dt = all_day_bounds(FRI, FRI)
        db.session.add(Event(
            calendar=Calendar.TP, title="Coy Admin Day", all_day=True,
            start_dt=start_dt, end_dt=end_dt,
            created_by_id=pid(app, "s3_all_day"),
        ))
        db.session.commit()

        text = ro_service.build(FRI).text
        assert "TBC\n- Coy Admin Day" in text
        assert "0000H" not in text


def test_extra_item_add_and_remove(app):
    with app.app_context():
        doc = ro_service.fetch_or_create(FRI)
        item = ro_service.add_extra_item(doc, time_=time(18, 0), text="Report to site")
        assert "1800H\n- Report to site" in ro_service.build(FRI).text
        assert ro_service.remove_extra_item(item.id) is True
        assert "Report to site" not in ro_service.build(FRI).text
        assert ro_service.remove_extra_item(item.id) is False
