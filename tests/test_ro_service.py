"""P5.4 — ro_service: fetch-or-create, assembly over live rows, A9 rights.

A9's two-day rule: editing the RO dated D requires CONFIRMED CDOS of D or
D−1 (the compiling evening), fallback command team. Duty names come from
CONFIRMED rows dated D only.
"""
from datetime import date, datetime, time, timedelta

from app.domain.types import (
    Appointment, Calendar, Duty, DutyState, Rank, RoRecurrence, RoSection,
    Service,
)
from app.extensions import db
from app.models import (
    DutyAssignment, Event, Person, RoBoilerplate, RoDocument, RoStandingItem,
    WeeklyKeyEvents,
)
from app.services import ro_service

FRI = date(2026, 6, 19)


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def get_person(username):
    return db.session.query(Person).filter_by(username=username).one()


def plant_duty(app, username, day, *, duty=Duty.CDOS, state=DutyState.CONFIRMED):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(
            DutyAssignment(
                date=day, duty=duty, person_id=person_id, state=state,
                created_by_id=person_id,
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
    # team) but its plumbing must not crash when a CONFIRMED CDOS row exists.
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


def test_build_assembles_duties_tp_and_standing(app, make_person):
    make_person(username="cdos_guy", rank=Rank.TWO_SG, appointment=Appointment.PS,
                platoon=2, display_name="Quek Jing Yu")
    make_person(username="cos_guy", rank=Rank.CPL, appointment=Appointment.OPR,
                display_name="Ang Cheng Ze")
    plant_duty(app, "cdos_guy", FRI, duty=Duty.CDOS)
    plant_duty(app, "cos_guy", FRI, duty=Duty.COS)
    # A PROPOSED row on the next day must not leak into any document.
    plant_duty(app, "cos_guy", FRI + timedelta(days=1), duty=Duty.COS,
               state=DutyState.PROPOSED)

    with app.app_context():
        db.session.add(RoStandingItem(
            time=time(6, 0), text="Roll call & Breakfast",
            recurrence=RoRecurrence.DAILY, position=10,
        ))
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
        db.session.add(WeeklyKeyEvents(week_start=date(2026, 6, 15), fri="Site Testing"))
        db.session.commit()

        doc = ro_service.build(FRI)
        assert doc.missing_duties == []
        assert "CDO/CDS: 2SG QUEK JING YU" in doc.text
        assert "COS: CPL ANG CHENG ZE" in doc.text
        assert "0600H\n- Roll call & Breakfast" in doc.text
        assert "0900H\n- Site Testing" in doc.text
        assert "Contingency X" not in doc.text  # ARCTIC never enters the RO
        assert "- Stay safe." in doc.text
        assert "Fri - Site Testing" in doc.text

        # The next day has no CONFIRMED duty: placeholder + report, and the
        # PROPOSED draft stayed invisible.
        doc = ro_service.build(FRI + timedelta(days=1))
        assert "COS: [NO CONFIRMED DUTY]" in doc.text
        assert set(doc.missing_duties) == {"CDO/CDS", "COS"}


def test_set_week_normalizes_to_monday(app):
    with app.app_context():
        row = ro_service.set_week(date(2026, 6, 17), fri="IPPT")  # a Wednesday
        assert row.week_start == date(2026, 6, 15)
        # Same week again updates in place — the unique week_start holds.
        row2 = ro_service.set_week(date(2026, 6, 19), mon="Wolf PT")
        assert row2.id == row.id
        assert row2.fri == "IPPT" and row2.mon == "Wolf PT"
        assert db.session.query(WeeklyKeyEvents).count() == 1


def test_extra_item_add_and_remove(app):
    with app.app_context():
        doc = ro_service.fetch_or_create(FRI)
        item = ro_service.add_extra_item(doc, time_=time(18, 0), text="Report to site")
        assert "1800H\n- Report to site" in ro_service.build(FRI).text
        assert ro_service.remove_extra_item(item.id) is True
        assert "Report to site" not in ro_service.build(FRI).text
        assert ro_service.remove_extra_item(item.id) is False
