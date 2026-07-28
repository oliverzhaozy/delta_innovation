"""P6.3 — domain/manning.py: slot eligibility over the frozen P4.2 mapping,
THE TU-Det-Comd trap regression, and the conflict tri-state (deliberately
missing an AVAILABLE member — absence of data is not presence of
availability).
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app.domain import manning
from app.domain.manning import ManningConflict
from app.domain.types import Appointment, DeclarationStatus, ManningSlotType

START, END = date(2026, 7, 5), date(2026, 7, 13)


def person(appointment, *, is_active=True):
    return SimpleNamespace(appointment=appointment, is_active=is_active)


def absence(start, end, label="OFF"):
    return SimpleNamespace(start_date=start, end_date=end, label=label)


def declaration(start, end, destination="Japan", status=DeclarationStatus.APPROVED):
    return SimpleNamespace(
        start_date=start, end_date=end, destination=destination, status=status,
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


def test_declaration_flags_and_rejected_does_not():
    status, reasons = manning.conflict_check(
        START, END, overseas_rows=[declaration(date(2026, 7, 10), date(2026, 7, 12))],
    )
    assert status is ManningConflict.CONFLICT
    assert reasons == ("Overseas (Japan) 10 Jul – 12 Jul",)

    status, _ = manning.conflict_check(
        START, END,
        overseas_rows=[declaration(date(2026, 7, 10), date(2026, 7, 12),
                                   status=DeclarationStatus.REJECTED)],
    )
    assert status is ManningConflict.NO_KNOWN_CONFLICT


def test_pending_declaration_flags():
    # Owner 2026-07-28: a declaration a PC has not decided yet is still a risk
    # the S3 must see — only REJECTED is nothing.
    status, reasons = manning.conflict_check(
        START, END,
        overseas_rows=[declaration(date(2026, 7, 10), date(2026, 7, 12),
                                   status=DeclarationStatus.PENDING)],
    )
    assert status is ManningConflict.CONFLICT
    assert reasons == ("Overseas (Japan) 10 Jul – 12 Jul",)


def test_single_day_reason_renders_one_date():
    _status, reasons = manning.conflict_check(
        START, END, absence_rows=[absence(date(2026, 7, 6), date(2026, 7, 6), label="MC")],
    )
    assert reasons == ("MC 06 Jul",)


# --- the document render (P6.5) -----------------------------------------------------

def slot_row(slot, det_number, name, phone):
    return SimpleNamespace(slot=slot, det_number=det_number, name=name, phone=phone)


SAMPLE_SLOTS = [
    slot_row(ManningSlotType.TU_COMD, None, "CPT WONG LI XUAN", "9190 9702"),
    slot_row(ManningSlotType.TU_PLANNER, None, "LTA QUEK JING YU", "9736 3276"),
    slot_row(ManningSlotType.TU_DET_COMD, 1, "3WO WONG JINGHENG", "9798 3466"),
    slot_row(ManningSlotType.DET_PERSONNEL, 1, "2SG JEYMUS TAN", "8518 3687"),
    slot_row(ManningSlotType.DET_PERSONNEL, 1, "3SG WONG WEI XUAN", "9683 9858"),
    slot_row(ManningSlotType.DET_PERSONNEL, 1, "CPL ANG CHENG ZE", "8435 8990"),
    slot_row(ManningSlotType.TU_DET_COMD, 2, "2SG RAYBRIEL WONG", "9382 3212"),
    slot_row(ManningSlotType.DET_PERSONNEL, 2, "3SG LOY QIYUAN", "9673 7123"),
    slot_row(ManningSlotType.DET_PERSONNEL, 2, "3SG XU XIANGRUI", "8218 8905"),
    slot_row(ManningSlotType.DET_PERSONNEL, 2, "LCP SAMUEL LIM", "9838 7704"),
]

# The owner's sample normalized per decision (l-bis): no trailing spaces.
GOLDEN = "\n".join([
    "TASK UNIT (TU) MANNING FOR",
    "050726 - 130726",
    "",
    "TU COMD: CPT WONG LI XUAN",
    "(9190 9702)",
    "TU PLANNER: LTA QUEK JING YU",
    "(9736 3276)",
    "",
    "TU 1",
    "DET COMD: 3WO WONG JINGHENG",
    "(9798 3466)",
    "DET PERSONNEL: 2SG JEYMUS TAN",
    "(8518 3687)",
    "DET PERSONNEL: 3SG WONG WEI XUAN",
    "(9683 9858)",
    "DET PERSONNEL: CPL ANG CHENG ZE",
    "(8435 8990)",
    "",
    "TU 2",
    "DET COMD: 2SG RAYBRIEL WONG",
    "(9382 3212)",
    "DET PERSONNEL: 3SG LOY QIYUAN",
    "(9673 7123)",
    "DET PERSONNEL: 3SG XU XIANGRUI",
    "(8218 8905)",
    "DET PERSONNEL: LCP SAMUEL LIM",
    "(9838 7704)",
])


def test_render_golden_byte_exact():
    doc = manning.render_manning(START, END, slots=SAMPLE_SLOTS)
    assert doc.unfilled == []
    assert doc.text == GOLDEN


def test_render_unkeyed_phone_and_unfilled_hq():
    doc = manning.render_manning(
        START, END,
        slots=[slot_row(ManningSlotType.TU_COMD, None, "CPT WONG LI XUAN", None)],
    )
    # No phone keyed -> a fill-in-WhatsApp placeholder line (decision q);
    # missing HQ slots are reported, never silently absent.
    assert "TU COMD: CPT WONG LI XUAN\n( )" in doc.text
    assert doc.unfilled == ["TU PLANNER"]
    assert "TU PLANNER" not in doc.text


def test_render_groups_dets_and_orders_comd_first():
    doc = manning.render_manning(
        START, END,
        slots=[
            slot_row(ManningSlotType.TU_COMD, None, "CPT A", "1"),
            slot_row(ManningSlotType.TU_PLANNER, None, "LTA B", "2"),
            # Keyed out of order: personnel before their det comd, det 2 first.
            slot_row(ManningSlotType.DET_PERSONNEL, 2, "CPL D2P", "3"),
            slot_row(ManningSlotType.TU_DET_COMD, 2, "2SG D2C", "4"),
            slot_row(ManningSlotType.DET_PERSONNEL, 1, "CPL D1P", "5"),
            slot_row(ManningSlotType.TU_DET_COMD, 1, "3WO D1C", "6"),
        ],
    )
    text = doc.text
    assert text.index("TU 1") < text.index("TU 2")
    assert text.index("DET COMD: 3WO D1C") < text.index("DET PERSONNEL: CPL D1P")
    assert text.index("DET COMD: 2SG D2C") < text.index("DET PERSONNEL: CPL D2P")


# --- the fixed-structure generator (P6.7b) ------------------------------------------

def full_pools():
    """Fresh pools every call — determinism is asserted over equal inputs, not
    over a shared mutable fixture."""
    return {
        ManningSlotType.TU_COMD: [1, 2],
        ManningSlotType.TU_PLANNER: [3, 4],
        ManningSlotType.TU_DET_COMD: [5, 6, 7],
        ManningSlotType.DET_PERSONNEL: [10, 11, 12, 13, 14, 15, 16],
    }


def picked(result, slot, det_number):
    return [p.person_id for p in result if p.slot is slot and p.det_number == det_number]


def test_full_pools_fill_the_fixed_structure_in_order():
    result = manning.generate(pools=full_pools(), existing=[])
    assert result == [
        manning.GeneratedPick(ManningSlotType.TU_COMD, None, 1),
        manning.GeneratedPick(ManningSlotType.TU_PLANNER, None, 3),
        manning.GeneratedPick(ManningSlotType.TU_DET_COMD, 1, 5),
        manning.GeneratedPick(ManningSlotType.TU_DET_COMD, 2, 6),
        manning.GeneratedPick(ManningSlotType.DET_PERSONNEL, 1, 10),
        manning.GeneratedPick(ManningSlotType.DET_PERSONNEL, 1, 11),
        manning.GeneratedPick(ManningSlotType.DET_PERSONNEL, 1, 12),
        manning.GeneratedPick(ManningSlotType.DET_PERSONNEL, 2, 13),
        manning.GeneratedPick(ManningSlotType.DET_PERSONNEL, 2, 14),
        manning.GeneratedPick(ManningSlotType.DET_PERSONNEL, 2, 15),
    ]
    assert len(result) == 2 + len(manning.GENERATED_DETS) * (1 + manning.DET_PERSONNEL_PER_DET)


def test_generation_is_deterministic():
    # No randomness and no fairness history: equal inputs, identical output.
    assert manning.generate(pools=full_pools(), existing=[]) == manning.generate(
        pools=full_pools(), existing=[]
    )


def test_existing_rows_count_against_their_slot():
    result = manning.generate(
        pools=full_pools(),
        existing=[
            (ManningSlotType.TU_COMD, None, 90),
            (ManningSlotType.DET_PERSONNEL, 1, 91),
        ],
    )
    assert picked(result, ManningSlotType.TU_COMD, None) == []
    # Det 1 needs two more; det 2 is untouched and still gets its three.
    assert picked(result, ManningSlotType.DET_PERSONNEL, 1) == [10, 11]
    assert picked(result, ManningSlotType.DET_PERSONNEL, 2) == [12, 13, 14]
    assert picked(result, ManningSlotType.TU_PLANNER, None) == [3]


def test_existing_person_is_never_picked_again():
    # Kept manually in one slot, still sitting in the pools for others.
    result = manning.generate(
        pools=full_pools(),
        existing=[(ManningSlotType.TU_DET_COMD, 1, 5)],
    )
    assert all(p.person_id != 5 for p in result)
    assert picked(result, ManningSlotType.TU_DET_COMD, 2) == [6]


def test_exhausted_pool_leaves_vacancies_and_fills_the_rest():
    pools = full_pools()
    pools[ManningSlotType.DET_PERSONNEL] = [10, 11, 12, 13]
    result = manning.generate(pools=pools, existing=[])
    assert picked(result, ManningSlotType.DET_PERSONNEL, 1) == [10, 11, 12]
    assert picked(result, ManningSlotType.DET_PERSONNEL, 2) == [13]
    # HQ is filled regardless — a thin det never starves the slots above it.
    assert picked(result, ManningSlotType.TU_COMD, None) == [1]
    assert picked(result, ManningSlotType.TU_PLANNER, None) == [3]


def test_missing_pool_key_is_an_empty_pool():
    result = manning.generate(
        pools={ManningSlotType.TU_COMD: [1]}, existing=[],
    )
    assert result == [manning.GeneratedPick(ManningSlotType.TU_COMD, None, 1)]


def test_manual_row_outside_the_generated_dets_satisfies_nothing():
    # Det 3 is not part of the fixed structure: the row only takes its man
    # off the table, dets 1 and 2 still generate their full complement.
    result = manning.generate(
        pools=full_pools(),
        existing=[(ManningSlotType.DET_PERSONNEL, 3, 10)],
    )
    assert picked(result, ManningSlotType.DET_PERSONNEL, 1) == [11, 12, 13]
    assert picked(result, ManningSlotType.DET_PERSONNEL, 2) == [14, 15, 16]


def test_generate_arguments_are_keyword_only_with_no_defaults():
    # A silent default would let a stale caller run the OLD behaviour; both
    # arguments must be named, and neither may be omitted.
    with pytest.raises(TypeError):
        manning.generate({}, [])
    with pytest.raises(TypeError):
        manning.generate(pools={})


def test_over_filled_pair_generates_nothing_for_it_and_does_not_raise():
    # Four manual det-1 personnel is more than the structure asks for: that
    # pair simply generates nothing, and det 2 is untouched.
    result = manning.generate(
        pools=full_pools(),
        existing=[
            (ManningSlotType.DET_PERSONNEL, 1, person_id)
            for person_id in (90, 91, 92, 93)
        ],
    )
    assert picked(result, ManningSlotType.DET_PERSONNEL, 1) == []
    assert picked(result, ManningSlotType.DET_PERSONNEL, 2) == [10, 11, 12]


def test_fully_empty_pools_generate_nothing():
    assert manning.generate(pools={}, existing=[]) == []


def test_person_in_two_pools_is_picked_once():
    pools = full_pools()
    pools[ManningSlotType.TU_DET_COMD] = [5, 6]
    pools[ManningSlotType.DET_PERSONNEL] = [6, 10, 11, 12, 13, 14, 15]
    result = manning.generate(pools=pools, existing=[])
    ids = [p.person_id for p in result]
    assert ids.count(6) == 1
    assert picked(result, ManningSlotType.TU_DET_COMD, 2) == [6]
    assert picked(result, ManningSlotType.DET_PERSONNEL, 1) == [10, 11, 12]
