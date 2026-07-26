"""P6.4 — manning_service: candidates over the shared fetch, assignment with
the eligibility hard block, the duplicate-person friendly error, and the
document build."""
from datetime import date, datetime

import pytest

from app.domain.manning import ManningConflict
from app.domain.types import (
    Appointment, DayPart, LeaveType, ManningSlotType, Rank, RequestStatus,
    Service, StatusType,
)
from app.extensions import db
from app.models import (
    LeaveRequest, ManningPeriod, ManningSlot, OverseasDeclaration, Person,
    StatusEntry,
)
from app.services import manning_service

START, END = date(2026, 7, 5), date(2026, 7, 13)


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def get_person(username):
    return db.session.query(Person).filter_by(username=username).one()


def make_cast(make_person):
    make_person(username="oc", rank=Rank.CPT, appointment=Appointment.OC,
                platoon=None, service=Service.REGULAR, display_name="Wong Li Xuan")
    make_person(username="pc1", rank=Rank.LTA, appointment=Appointment.PC,
                display_name="Quek Jing Yu")
    make_person(username="p2ic3", rank=Rank.THREE_WO, appointment=Appointment.P2IC,
                platoon=3, display_name="Wong Jingheng")
    make_person(username="det1", rank=Rank.TWO_SG, appointment=Appointment.DET_COMD,
                display_name="Jeymus Tan")
    make_person(username="opr1", rank=Rank.CPL, appointment=Appointment.OPR,
                display_name="Ang Cheng Ze")


def make_period(app, creator="oc"):
    with app.app_context():
        period = ManningPeriod(
            start_date=START, end_date=END, created_by_id=pid(app, creator),
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def test_candidates_respect_the_trap_and_order_conflicts_last(app, make_person):
    make_cast(make_person)
    period_id = make_period(app)
    # det1 (company Det Comd) is on approved leave inside the period.
    with app.app_context():
        db.session.add(LeaveRequest(
            person_id=pid(app, "det1"), type=LeaveType.OFF,
            start_date=date(2026, 7, 6), end_date=date(2026, 7, 6),
            day_part=DayPart.FULL, status=RequestStatus.APPROVED,
        ))
        db.session.commit()

        period = db.session.get(ManningPeriod, period_id)
        candidates = manning_service.candidates(period)

        # The TU_DET_COMD pick list omits the company Det Comd (the trap).
        tu_det_comd_names = [c.person.username for c in candidates[ManningSlotType.TU_DET_COMD]]
        assert tu_det_comd_names == ["p2ic3"]
        # Det Personnel: conflicted det1 is FLAGGED and sorted after, not hidden.
        det_personnel = candidates[ManningSlotType.DET_PERSONNEL]
        assert [c.person.username for c in det_personnel] == ["opr1", "det1"]
        flagged = det_personnel[1]
        assert flagged.status is ManningConflict.CONFLICT
        assert "OFF 06 Jul" in flagged.reasons[0]


def test_out_of_camp_status_and_declaration_flag_in_camp_status_does_not(app, make_person):
    make_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        db.session.add(StatusEntry(
            person_id=pid(app, "opr1"), type=StatusType.OTHER,
            start_date=date(2026, 6, 25), end_date=date(2026, 7, 16),
            day_part=DayPart.FULL, in_camp=False, created_by_id=pid(app, "opr1"),
        ))
        db.session.add(StatusEntry(
            person_id=pid(app, "det1"), type=StatusType.OTHER,
            start_date=date(2026, 7, 6), end_date=date(2026, 7, 6),
            day_part=DayPart.FULL, in_camp=True, created_by_id=pid(app, "det1"),
        ))
        db.session.add(OverseasDeclaration(
            person_id=pid(app, "pc1"), start_date=date(2026, 7, 10),
            end_date=date(2026, 7, 12), destination="Japan",
        ))
        db.session.commit()

        period = db.session.get(ManningPeriod, period_id)
        checks = {
            c.person.username: c
            for c in manning_service.candidates(period)[ManningSlotType.DET_PERSONNEL]
        }
        assert checks["opr1"].status is ManningConflict.CONFLICT  # A8: course flags
        assert checks["det1"].status is ManningConflict.NO_KNOWN_CONFLICT  # in camp

        planner = manning_service.candidates(period)[ManningSlotType.TU_PLANNER][0]
        assert planner.status is ManningConflict.CONFLICT
        assert "Overseas (Japan)" in planner.reasons[0]


def test_assign_hard_blocks_ineligible_and_duplicates_are_friendly(app, make_person):
    make_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        period = db.session.get(ManningPeriod, period_id)

        with pytest.raises(manning_service.IneligibleSlot):
            manning_service.assign_slot(
                period, ManningSlotType.TU_DET_COMD, get_person("det1"), det_number=1,
            )

        manning_service.assign_slot(
            period, ManningSlotType.TU_DET_COMD, get_person("p2ic3"), det_number=1,
        )
        # Same person into a second (eligible) slot: the UNIQUE backstop
        # answers with the friendly error, not a 500.
        with pytest.raises(manning_service.DuplicatePerson):
            manning_service.assign_slot(
                period, ManningSlotType.TU_DET_COMD, get_person("p2ic3"), det_number=2,
            )
        assert db.session.query(ManningSlot).count() == 1


def test_build_document_formats_names_and_phones(app, make_person):
    make_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        oc = get_person("oc")
        oc.phone = "9190 9702"
        db.session.commit()
        period = db.session.get(ManningPeriod, period_id)
        manning_service.assign_slot(period, ManningSlotType.TU_COMD, oc, det_number=None)
        manning_service.assign_slot(
            period, ManningSlotType.DET_PERSONNEL, get_person("opr1"), det_number=1,
        )

        doc = manning_service.build_document(period)
        assert "TASK UNIT (TU) MANNING FOR\n050726 - 130726" in doc.text
        assert "TU COMD: CPT WONG LI XUAN\n(9190 9702)" in doc.text
        assert "DET PERSONNEL: CPL ANG CHENG ZE\n( )" in doc.text  # no phone keyed
        assert doc.unfilled == ["TU PLANNER"]
