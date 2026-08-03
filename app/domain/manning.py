"""TU manning rules (P6.3). Pure: stdlib + sibling app.domain only.

Slot eligibility reads the FROZEN P4.2 mapping (`TU_SLOT_APPOINTMENTS`, B4)
— this module never restates who fills what, so the TU-Det-Comd trap has one
owner. The conflict check is a deliberate TRI-STATE with no AVAILABLE member:
absence of data is not presence of availability (declarations only exist if
someone declared), so the best the app can honestly say is NO_KNOWN_CONFLICT.
Per A8 the caller shapes ALL absence kinds (approved leave incl. LL/OL,
direct absences, out-of-camp statuses) from the shared fetch into
`absence_rows`; a leave-table-only join would miss the most common real
conflict (an MC or a course from the TP calendar).
"""
import enum
from collections import defaultdict, namedtuple

from app.domain.dates import range_label
from app.domain.eligibility import TU_SLOT_APPOINTMENTS
from app.domain.types import DeclarationStatus, ManningSlotType


class ManningConflict(str, enum.Enum):
    CONFLICT = "CONFLICT"
    NO_KNOWN_CONFLICT = "NO_KNOWN_CONFLICT"
    # Deliberately no AVAILABLE member — pinned in tests.


def slot_eligible(slot, person) -> bool:
    """May `person` legally hold `slot`? Appointment from the frozen mapping —
    assignment eligibility, not app access (the two permission concepts never
    mix)."""
    return person.appointment in TU_SLOT_APPOINTMENTS[slot.value]


def conflict_check(start_date, end_date, *, absence_rows=(), overseas_rows=()):
    """(ManningConflict, reasons) for one person over [start_date, end_date].

    `absence_rows`: pre-shaped rows with .label/.start_date/.end_date — any
    overlap is a reason (warn-only; even a half-day inside an activation
    window is worth a flag, and the S3 decides). `overseas_rows`: declarations
    with .destination/.status — rejected ones never flag, pending ones DO
    (owner 2026-07-28: declared travel is a risk until a PC says otherwise);
    that pin lives HERE so no caller can forget the filter.
    """
    reasons = []
    for row in absence_rows:
        if row.start_date <= end_date and row.end_date >= start_date:
            reasons.append(f"{row.label} {range_label(row.start_date, row.end_date)}")
    for row in overseas_rows:
        if (
            row.status is not DeclarationStatus.REJECTED
            and row.start_date <= end_date
            and row.end_date >= start_date
        ):
            reasons.append(
                f"Overseas ({row.destination}) {range_label(row.start_date, row.end_date)}"
            )
    status = ManningConflict.CONFLICT if reasons else ManningConflict.NO_KNOWN_CONFLICT
    return status, tuple(reasons)


ManningDoc = namedtuple("ManningDoc", "text unfilled")

_HQ_SLOTS = (ManningSlotType.TU_COMD, ManningSlotType.TU_PLANNER)


def _person_lines(row):
    """Two lines per person: the slot line and the phone line. No phone keyed
    renders the fill-in-WhatsApp placeholder '( )' (decision q)."""
    phone = f"({row.phone})" if row.phone else "( )"
    return [f"{row.slot.label}: {row.name}", phone]


def render_manning(start_date, end_date, *, slots) -> ManningDoc:
    """The document text + unfilled-HQ report (docs/MANNING_FORMATS.md).

    `slots`: shaped rows with .slot/.det_number/.name/.phone (the service
    formats names). Status is not an input and never will be: a period's
    DRAFT/PENDING/APPROVED state (decision (ff)) is chrome around this text,
    so whatever is assigned renders identically at every status. Grouping is
    derived here: HQ block
    (TU COMD then TU PLANNER), then dets ascending by det_number, DET COMD
    line first within each det, personnel in given order. Unfilled HQ slots
    are REPORTED, never silently absent; det completeness is the S3's
    judgment (per-det headcount rules are deliberately cut).
    """
    header = [
        "TASK UNIT (TU) MANNING FOR",
        f"{start_date.strftime('%d%m%y')} - {end_date.strftime('%d%m%y')}",
    ]

    hq_lines = []
    unfilled = []
    for hq_slot in _HQ_SLOTS:
        row = next((r for r in slots if r.slot is hq_slot), None)
        if row is None:
            unfilled.append(hq_slot.label)
        else:
            hq_lines += _person_lines(row)

    blocks = ["\n".join(header)]
    if hq_lines:
        blocks.append("\n".join(hq_lines))

    det_numbers = sorted({r.det_number for r in slots if r.det_number is not None})
    for det in det_numbers:
        det_rows = [r for r in slots if r.det_number == det]
        ordered = [r for r in det_rows if r.slot is ManningSlotType.TU_DET_COMD]
        ordered += [r for r in det_rows if r.slot is ManningSlotType.DET_PERSONNEL]
        lines = [f"TU {det}"]
        for row in ordered:
            lines += _person_lines(row)
        blocks.append("\n".join(lines))

    return ManningDoc(text="\n\n".join(blocks), unfilled=unfilled)


# The generated structure is FIXED by the owner (2026-07-28): HQ plus dets 1
# and 2 at three personnel each. Sizing is not a per-period choice.
GENERATED_DETS = (1, 2)
DET_PERSONNEL_PER_DET = 3

GeneratedPick = namedtuple("GeneratedPick", "slot det_number person_id")

# (slot, det_number, how many that pair needs) in fill order.
_STRUCTURE = (
    (ManningSlotType.TU_COMD, None, 1),
    (ManningSlotType.TU_PLANNER, None, 1),
    *((ManningSlotType.TU_DET_COMD, det, 1) for det in GENERATED_DETS),
    *((ManningSlotType.DET_PERSONNEL, det, DET_PERSONNEL_PER_DET) for det in GENERATED_DETS),
)


def generate(*, pools, existing):
    """[GeneratedPick] filling the fixed structure around the rows that stay.

    `pools` = {ManningSlotType: [person_id, ...]}, pre-filtered by the caller
    to eligible AND no-known-conflict, in roster order; a missing key is an
    empty pool. `existing` = (slot, det_number, person_id) rows surviving
    regeneration (the manual ones): each person is barred from every pick, and
    each row counts against the need for ITS (slot, det_number) pair — so a
    manual det-3 row satisfies nothing, it only takes its man off the table.

    An exhausted pool leaves that vacancy unpicked and moves on; later slots
    still fill, and the builder's `doc.unfilled` banner is where a thin HQ
    surfaces. Deliberate deviation from `roster.generate`: no randomness and
    no fairness history. Activation periods are sporadic, not a monthly
    rotation, so spreading them evenly would be arithmetic about nothing —
    the S3 reshuffles by hand. Identical inputs give identical output.
    """
    used = set()
    filled = defaultdict(int)
    for slot, det_number, person_id in existing:
        used.add(person_id)
        filled[(slot, det_number)] += 1

    picks = []
    for slot, det_number, needed in _STRUCTURE:
        pool = pools.get(slot, ())
        for _ in range(needed - filled[(slot, det_number)]):
            person_id = next((p for p in pool if p not in used), None)
            if person_id is None:
                break
            used.add(person_id)
            picks.append(GeneratedPick(slot, det_number, person_id))
    return picks
