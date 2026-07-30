"""P6.4/P6.7c — manning_service: candidates over the shared fetch, assignment
with the eligibility hard block, the duplicate-person friendly error, the
document build, and generation over the fixed structure."""
from datetime import date, datetime

import pytest

from app.domain import manning
from app.domain.manning import ManningConflict
from app.domain.types import (
    Appointment, DayPart, DeclarationStatus, LeaveType, ManningSlotType, Rank,
    RequestStatus, Service, StatusType,
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
            status=DeclarationStatus.APPROVED,
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


# --- generation over the fixed structure (P6.7c) ------------------------------------

STRUCTURE_TOTAL = 2 + len(manning.GENERATED_DETS) * (1 + manning.DET_PERSONNEL_PER_DET)


def make_generation_cast(make_person):
    """make_cast plus enough people to fill the whole structure: a second TU
    Det Comd candidate and five more det personnel (seven for six slots)."""
    make_cast(make_person)
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS,
                platoon=2, display_name="Raybriel Wong")
    for n in range(2, 7):
        make_person(username=f"opr{n}", rank=Rank.CPL, appointment=Appointment.OPR,
                    display_name=f"Operator {n}")


def slots_of(period_id):
    return db.session.query(ManningSlot).filter_by(period_id=period_id).all()


def test_generate_fills_the_structure_and_marks_every_row_generated(app, make_person):
    make_generation_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        period = db.session.get(ManningPeriod, period_id)
        assert manning_service.generate_period(period) == (
            STRUCTURE_TOTAL, STRUCTURE_TOTAL,
        )

        rows = slots_of(period_id)
        assert len(rows) == STRUCTURE_TOTAL
        # The flag split is what regeneration keys on: nothing here is manual.
        assert all(row.is_manual is False for row in rows)
        shape = {}
        for row in rows:
            shape[(row.slot, row.det_number)] = shape.get((row.slot, row.det_number), 0) + 1
        assert shape == {
            (ManningSlotType.TU_COMD, None): 1,
            (ManningSlotType.TU_PLANNER, None): 1,
            (ManningSlotType.TU_DET_COMD, 1): 1,
            (ManningSlotType.TU_DET_COMD, 2): 1,
            (ManningSlotType.DET_PERSONNEL, 1): manning.DET_PERSONNEL_PER_DET,
            (ManningSlotType.DET_PERSONNEL, 2): manning.DET_PERSONNEL_PER_DET,
        }


def test_regenerate_preserves_manual_and_replaces_the_generated_rows(app, make_person):
    make_generation_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        period = db.session.get(ManningPeriod, period_id)
        manual = manning_service.assign_slot(
            period, ManningSlotType.TU_DET_COMD, get_person("ps2"), det_number=1,
        )
        manual_id, manual_person_id = manual.id, manual.person_id

        manning_service.generate_period(period)
        dropped = next(
            r.person_id for r in slots_of(period_id)
            if not r.is_manual and r.slot is ManningSlotType.DET_PERSONNEL
        )
        # Keyed AFTER the first pass: the second must re-plan around it, which
        # is only possible if the generated rows really were deleted.
        db.session.add(LeaveRequest(
            person_id=dropped, type=LeaveType.OFF,
            start_date=date(2026, 7, 6), end_date=date(2026, 7, 8),
            day_part=DayPart.FULL, status=RequestStatus.APPROVED,
        ))
        db.session.commit()
        manning_service.generate_period(period)

        row = db.session.get(ManningSlot, manual_id)
        assert row.is_manual is True
        assert row.person_id == manual_person_id
        assert (row.slot, row.det_number) == (ManningSlotType.TU_DET_COMD, 1)
        rows = slots_of(period_id)
        assert dropped not in {r.person_id for r in rows}
        assert len(rows) == STRUCTURE_TOTAL  # replaced, never stacked


def test_a_covering_absence_or_declaration_is_never_generated(app, make_person):
    # The pools-are-pre-filtered guarantee: the pure generator re-checks
    # nothing, so this service filter is the only thing keeping a man on
    # approved leave out of an activation det.
    make_generation_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        db.session.add(LeaveRequest(
            person_id=pid(app, "ps2"), type=LeaveType.OFF,
            start_date=date(2026, 7, 6), end_date=date(2026, 7, 8),
            day_part=DayPart.FULL, status=RequestStatus.APPROVED,
        ))
        db.session.add(OverseasDeclaration(
            person_id=pid(app, "opr6"), start_date=date(2026, 7, 10),
            end_date=date(2026, 7, 12), destination="Japan",
            status=DeclarationStatus.PENDING,
        ))
        db.session.commit()

        period = db.session.get(ManningPeriod, period_id)
        manning_service.generate_period(period)
        rows = slots_of(period_id)
        picked = {row.person_id for row in rows}
        assert pid(app, "ps2") not in picked
        assert pid(app, "opr6") not in picked  # pending declarations flag too
        # ps2 was one of only two TU Det Comd candidates: that det goes short...
        assert sum(1 for r in rows if r.slot is ManningSlotType.TU_DET_COMD) == 1
        # ...while six det personnel remain for six slots, so those still fill.
        assert sum(1 for r in rows if r.slot is ManningSlotType.DET_PERSONNEL) == 6


def test_manual_row_shrinks_its_det_and_its_person_is_not_duplicated(app, make_person):
    make_generation_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        period = db.session.get(ManningPeriod, period_id)
        manning_service.assign_slot(
            period, ManningSlotType.DET_PERSONNEL, get_person("opr1"), det_number=1,
        )
        assert manning_service.generate_period(period) == (
            STRUCTURE_TOTAL - 1, STRUCTURE_TOTAL - 1,
        )

        rows = slots_of(period_id)
        det1 = [
            r for r in rows
            if r.slot is ManningSlotType.DET_PERSONNEL and r.det_number == 1
        ]
        assert len(det1) == manning.DET_PERSONNEL_PER_DET
        assert sum(1 for r in det1 if not r.is_manual) == manning.DET_PERSONNEL_PER_DET - 1
        assert [r.person_id for r in rows].count(pid(app, "opr1")) == 1


def test_assign_slot_marks_the_row_manual(app, make_person):
    # Six older fixtures build ManningSlot directly (default False); the
    # service path must pin True or a regenerate would eat the S3's own pick.
    make_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        period = db.session.get(ManningPeriod, period_id)
        row = manning_service.assign_slot(
            period, ManningSlotType.TU_COMD, get_person("oc"), det_number=None,
        )
        assert db.session.get(ManningSlot, row.id).is_manual is True


def test_thin_pools_report_the_shortfall_in_the_counts(app, make_person):
    # make_cast has one candidate per HQ slot, ONE TU Det Comd and TWO det
    # personnel — det-level shortfalls surface nowhere else, so the counts are
    # the S3's only signal.
    make_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        period = db.session.get(ManningPeriod, period_id)
        filled, open_before = manning_service.generate_period(period)
        assert (filled, open_before) == (5, STRUCTURE_TOTAL)
        assert filled < open_before
        assert len(slots_of(period_id)) == 5


# --- priority: longest since the last activation period (display only) --------------

def make_period_between(app, start, end, creator="oc"):
    with app.app_context():
        period = ManningPeriod(
            start_date=start, end_date=end, created_by_id=pid(app, creator),
        )
        db.session.add(period)
        db.session.commit()
        return period.id


def put_in_period(app, period_id, username, slot, *, det_number=None):
    with app.app_context():
        db.session.add(ManningSlot(
            period_id=period_id, slot=slot, person_id=pid(app, username),
            det_number=det_number, is_manual=True,
        ))
        db.session.commit()


def test_last_manning_end_is_the_max_end_date_per_person(app, make_person):
    make_cast(make_person)
    old = make_period_between(app, date(2026, 3, 2), date(2026, 3, 8))
    new = make_period_between(app, date(2026, 5, 4), date(2026, 5, 10))
    put_in_period(app, old, "opr1", ManningSlotType.DET_PERSONNEL, det_number=1)
    put_in_period(app, new, "opr1", ManningSlotType.DET_PERSONNEL, det_number=1)
    put_in_period(app, old, "det1", ManningSlotType.DET_PERSONNEL, det_number=2)

    with app.app_context():
        last = manning_service.last_manning_end()
        assert last[pid(app, "opr1")] == date(2026, 5, 10)   # the later period
        assert last[pid(app, "det1")] == date(2026, 3, 8)
        # Never-in-a-period people are absent from the map, not zero-dated.
        assert pid(app, "pc1") not in last
        assert isinstance(last[pid(app, "opr1")], date)


def test_slot_priority_ranks_eligible_people_never_first_then_oldest(app, make_person):
    make_cast(make_person)
    make_person(username="opr2", rank=Rank.CPL, appointment=Appointment.OPR,
                display_name="Second Operator")
    old = make_period_between(app, date(2026, 3, 2), date(2026, 3, 8))
    new = make_period_between(app, date(2026, 5, 4), date(2026, 5, 10))
    put_in_period(app, old, "opr1", ManningSlotType.DET_PERSONNEL, det_number=1)
    put_in_period(app, new, "det1", ManningSlotType.DET_PERSONNEL, det_number=1)

    with app.app_context():
        ranking = manning_service.slot_priority(manning_service.last_manning_end())
        assert [
            (p.username, last)
            for p, last in ranking[ManningSlotType.DET_PERSONNEL]
        ] == [
            ("opr2", None), ("opr1", date(2026, 3, 8)), ("det1", date(2026, 5, 10)),
        ]
        # Every slot is a key, and the trap holds here too: a company Det Comd
        # ranks for Det Personnel, never for the slot labelled DET COMD.
        assert set(ranking) == set(ManningSlotType)
        assert [p.username for p, _last in ranking[ManningSlotType.TU_DET_COMD]] == ["p2ic3"]


def test_candidates_order_by_priority_inside_each_conflict_group(app, make_person):
    make_cast(make_person)
    make_person(username="opr2", rank=Rank.CPL, appointment=Appointment.OPR,
                display_name="Second Operator")
    done = make_period_between(app, date(2026, 5, 4), date(2026, 5, 10))
    put_in_period(app, done, "opr1", ManningSlotType.DET_PERSONNEL, det_number=1)
    period_id = make_period(app)
    with app.app_context():
        # det1 conflicts, so he sorts last however long he has waited — priority
        # only decides WITHIN a conflict group.
        db.session.add(LeaveRequest(
            person_id=pid(app, "det1"), type=LeaveType.OFF,
            start_date=date(2026, 7, 6), end_date=date(2026, 7, 6),
            day_part=DayPart.FULL, status=RequestStatus.APPROVED,
        ))
        db.session.commit()

        period = db.session.get(ManningPeriod, period_id)
        rows = manning_service.candidates(period)[ManningSlotType.DET_PERSONNEL]
        assert [c.person.username for c in rows] == ["opr2", "opr1", "det1"]
        assert rows[-1].status is ManningConflict.CONFLICT


# --- reassign: swap a holder in place ------------------------------------------------

def test_reassign_swaps_the_holder_and_marks_the_row_manual(app, make_person):
    make_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        period = db.session.get(ManningPeriod, period_id)
        # A GENERATED row, so the is_manual flip is not vacuous.
        row = ManningSlot(
            period_id=period.id, slot=ManningSlotType.DET_PERSONNEL,
            person_id=pid(app, "opr1"), det_number=1, is_manual=False,
        )
        db.session.add(row)
        db.session.commit()
        row_id = row.id

        swapped = manning_service.reassign_slot(period, row_id, get_person("det1"))
        assert swapped.id == row_id          # the row keeps its identity
        assert swapped.person_id == pid(app, "det1")
        assert swapped.is_manual is True     # regeneration must now leave it be
        assert db.session.query(ManningSlot).count() == 1


def test_reassign_hard_blocks_an_ineligible_person(app, make_person):
    make_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        period = db.session.get(ManningPeriod, period_id)
        row = manning_service.assign_slot(
            period, ManningSlotType.TU_DET_COMD, get_person("p2ic3"), det_number=1,
        )
        # The trap through the in-place edit: a company Det Comd can never take
        # over the slot the document labels DET COMD.
        with pytest.raises(manning_service.IneligibleSlot):
            manning_service.reassign_slot(period, row.id, get_person("det1"))
        assert db.session.get(ManningSlot, row.id).person_id == pid(app, "p2ic3")


def test_reassign_to_someone_already_in_the_period_is_the_friendly_duplicate(
    app, make_person
):
    make_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        period = db.session.get(ManningPeriod, period_id)
        manning_service.assign_slot(
            period, ManningSlotType.DET_PERSONNEL, get_person("opr1"), det_number=1,
        )
        target = manning_service.assign_slot(
            period, ManningSlotType.DET_PERSONNEL, get_person("det1"), det_number=2,
        )
        with pytest.raises(manning_service.DuplicatePerson):
            manning_service.reassign_slot(period, target.id, get_person("opr1"))
        db.session.rollback()
        # The UNIQUE backstop answered; both rows survive untouched.
        assert db.session.get(ManningSlot, target.id).person_id == pid(app, "det1")
        assert db.session.query(ManningSlot).count() == 2


def test_reassigning_a_slot_to_its_own_holder_is_a_defined_no_op(app, make_person):
    # An accidental resubmit of an unchanged select must not flash a duplicate.
    make_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        period = db.session.get(ManningPeriod, period_id)
        row = manning_service.assign_slot(
            period, ManningSlotType.TU_COMD, get_person("oc"), det_number=None,
        )
        again = manning_service.reassign_slot(period, row.id, get_person("oc"))
        assert again.person_id == pid(app, "oc")
        assert db.session.query(ManningSlot).count() == 1


def test_reassign_refuses_a_slot_from_another_period(app, make_person):
    # Object-level check: the role proves who the S3 is, never that this slot
    # belongs to the period in the URL.
    make_cast(make_person)
    mine = make_period(app)
    theirs = make_period_between(app, date(2026, 9, 1), date(2026, 9, 5))
    put_in_period(app, theirs, "opr1", ManningSlotType.DET_PERSONNEL, det_number=1)
    with app.app_context():
        foreign_id = (
            db.session.query(ManningSlot.id).filter_by(period_id=theirs).scalar()
        )
        period = db.session.get(ManningPeriod, mine)
        assert manning_service.reassign_slot(period, foreign_id, get_person("det1")) is None
        # Untouched: refusal is not a silent edit somewhere else.
        assert db.session.get(ManningSlot, foreign_id).person_id == pid(app, "opr1")
        assert manning_service.reassign_slot(period, 9999, get_person("det1")) is None


def test_open_positions_is_the_structure_minus_what_is_already_there(app, make_person):
    make_cast(make_person)
    period_id = make_period(app)
    with app.app_context():
        period = db.session.get(ManningPeriod, period_id)
        assert len(manning_service.open_positions(period)) == STRUCTURE_TOTAL
        # Fill order: HQ, then the det comds, then the personnel.
        assert manning_service.open_positions(period)[:3] == [
            (ManningSlotType.TU_COMD, None),
            (ManningSlotType.TU_PLANNER, None),
            (ManningSlotType.TU_DET_COMD, 1),
        ]

        manning_service.assign_slot(
            period, ManningSlotType.TU_COMD, get_person("oc"), det_number=None,
        )
        db.session.refresh(period)
        remaining = manning_service.open_positions(period)
        assert (ManningSlotType.TU_COMD, None) not in remaining
        assert len(remaining) == STRUCTURE_TOTAL - 1

        # A row OUTSIDE the structure (det 3) satisfies none of it — the page's
        # open lines and the generate flash's count agree because both read this.
        manning_service.assign_slot(
            period, ManningSlotType.DET_PERSONNEL, get_person("opr1"), det_number=3,
        )
        db.session.refresh(period)
        assert len(manning_service.open_positions(period)) == STRUCTURE_TOTAL - 1
