"""P6.3 — domain/manning.py: slot eligibility over the frozen P4.2 mapping,
THE TU-Det-Comd trap regression, and the conflict tri-state (deliberately
missing an AVAILABLE member — absence of data is not presence of
availability).
"""
from datetime import date, datetime
from types import SimpleNamespace

from app.domain import manning
from app.domain.manning import ManningConflict
from app.domain.types import Appointment, ManningSlotType

START, END = date(2026, 7, 5), date(2026, 7, 13)


def person(appointment, *, is_active=True):
    return SimpleNamespace(appointment=appointment, is_active=is_active)


def absence(start, end, label="OFF"):
    return SimpleNamespace(start_date=start, end_date=end, label=label)


def declaration(start, end, destination="Japan", cancelled_at=None):
    return SimpleNamespace(
        start_date=start, end_date=end, destination=destination,
        cancelled_at=cancelled_at,
    )


# --- THE mandatory trap regression -------------------------------------------------

def test_the_tu_det_comd_trap():
    # A company-appointment Det Comd is INELIGIBLE for the slot the document
    # labels "DET COMD" (TU_DET_COMD = P2IC/PS) and eligible for
    # DET_PERSONNEL; a P2IC/PS is exactly the reverse.
    det_comd = person(Appointment.DET_COMD)
    assert not manning.slot_eligible(ManningSlotType.TU_DET_COMD, det_comd)
    assert manning.slot_eligible(ManningSlotType.DET_PERSONNEL, det_comd)
    for appt in (Appointment.P2IC, Appointment.PS):
        p = person(appt)
        assert manning.slot_eligible(ManningSlotType.TU_DET_COMD, p), appt
        assert not manning.slot_eligible(ManningSlotType.DET_PERSONNEL, p), appt


def test_slot_eligibility_over_the_frozen_mapping():
    assert manning.slot_eligible(ManningSlotType.TU_COMD, person(Appointment.OC))
    assert manning.slot_eligible(ManningSlotType.TU_COMD, person(Appointment.TWO_IC))
    assert not manning.slot_eligible(ManningSlotType.TU_COMD, person(Appointment.PC))
    assert manning.slot_eligible(ManningSlotType.TU_PLANNER, person(Appointment.PC))
    assert not manning.slot_eligible(ManningSlotType.TU_PLANNER, person(Appointment.PS))
    assert manning.slot_eligible(ManningSlotType.DET_PERSONNEL, person(Appointment.OPR))
    # Deactivated people are never eligible, whatever the appointment.
    assert not manning.slot_eligible(
        ManningSlotType.TU_COMD, person(Appointment.OC, is_active=False)
    )


# --- the conflict tri-state ---------------------------------------------------------

def test_no_available_member_exists():
    # Pinned: absence of data is not presence of availability. Declarations
    # only exist if someone declared; the enum must never say AVAILABLE.
    assert [m.name for m in ManningConflict] == ["CONFLICT", "NO_KNOWN_CONFLICT"]


def test_overlapping_absence_flags_with_reason():
    status, reasons = manning.conflict_check(
        START, END, absence_rows=[absence(date(2026, 7, 6), date(2026, 7, 7))],
    )
    assert status is ManningConflict.CONFLICT
    assert reasons == ("OFF 06 Jul – 07 Jul",)


def test_out_of_camp_status_flags_like_leave():
    # A8: the caller shapes MCs/courses into the same absence rows — a
    # 3-week course must flag exactly like leave.
    status, reasons = manning.conflict_check(
        START, END,
        absence_rows=[absence(date(2026, 6, 25), date(2026, 7, 16), label="On course")],
    )
    assert status is ManningConflict.CONFLICT
    assert "On course" in reasons[0]


def test_non_overlapping_rows_do_not_flag():
    status, reasons = manning.conflict_check(
        START, END,
        absence_rows=[absence(date(2026, 7, 14), date(2026, 7, 15))],
        overseas_rows=[declaration(date(2026, 8, 1), date(2026, 8, 5))],
    )
    assert status is ManningConflict.NO_KNOWN_CONFLICT
    assert reasons == ()


def test_declaration_flags_and_retracted_does_not():
    status, reasons = manning.conflict_check(
        START, END, overseas_rows=[declaration(date(2026, 7, 10), date(2026, 7, 12))],
    )
    assert status is ManningConflict.CONFLICT
    assert reasons == ("Overseas (Japan) 10 Jul – 12 Jul",)

    status, _ = manning.conflict_check(
        START, END,
        overseas_rows=[declaration(date(2026, 7, 10), date(2026, 7, 12),
                                   cancelled_at=datetime(2026, 7, 1, 9, 0))],
    )
    assert status is ManningConflict.NO_KNOWN_CONFLICT


def test_single_day_reason_renders_one_date():
    _status, reasons = manning.conflict_check(
        START, END, absence_rows=[absence(date(2026, 7, 6), date(2026, 7, 6), label="MC")],
    )
    assert reasons == ("MC 06 Jul",)
