"""TU manning orchestration (P6.4): shape live rows into domain/manning's
pure rules, own the slot transactions, and build the document.

One shared absence fetch per period (A8) feeds every candidate's conflict
check — leave, direct absences, and OUT-OF-CAMP statuses all flag the same
way, plus non-cancelled overseas declarations. Conflicted people are FLAGGED
and sorted last, never hidden: the pick list IS the eligible-and-available
replacement list, and the S3 decides from one screen.
"""
from collections import defaultdict, namedtuple

from sqlalchemy.exc import IntegrityError

from app.domain import manning
from app.domain.types import ManningSlotType
from app.extensions import db
from app.models import ManningPeriod, ManningSlot, OverseasDeclaration
from app.services import event_service, presence_service


class IneligibleSlot(Exception):
    """Rule violation (the trap: a company Det Comd can never hold the slot
    the document labels DET COMD) — hard block, 4xx, never a warning."""


class DuplicatePerson(Exception):
    """One slot per person per period (UNIQUE backstop) — friendly error."""


Candidate = namedtuple("Candidate", "person status reasons")

_AbsenceLike = namedtuple("AbsenceLike", "label start_date end_date")
_SlotRow = namedtuple("SlotRow", "slot det_number name phone")


def _absence_rows_by_person(start_date, end_date):
    """The period's absence rows per person, shaped for the pure conflict
    check from the ONE shared fetch (A8): leave and course covers always; statuses
    only when out of camp (in camp is not away)."""
    leaves, statuses, courses = presence_service.fetch_absence_rows(start_date, end_date)
    rows = defaultdict(list)
    for row in leaves:
        rows[row.person_id].append(
            _AbsenceLike(row.type.value, row.start_date, row.end_date)
        )
    for row in statuses:
        if not row.in_camp:
            rows[row.person_id].append(
                _AbsenceLike(row.type.label, row.start_date, row.end_date)
            )
    for row in courses:
        rows[row.person_id].append(
            _AbsenceLike(row.type.label, row.start_date, row.end_date)
        )
    return rows


def _declarations_by_person(start_date, end_date):
    rows = defaultdict(list)
    query = (
        db.session.query(OverseasDeclaration)
        .filter(
            OverseasDeclaration.start_date <= end_date,
            OverseasDeclaration.end_date >= start_date,
        )
        .all()
    )
    for row in query:
        rows[row.person_id].append(row)
    return rows


def conflict_map(period):
    """{person_id: (status, reasons)} for every active person over the
    period — the builder's pick lists and the flag surfaces (P6.6) read the
    SAME map, so the two can never disagree."""
    absences = _absence_rows_by_person(period.start_date, period.end_date)
    declarations = _declarations_by_person(period.start_date, period.end_date)
    return {
        person.id: manning.conflict_check(
            period.start_date,
            period.end_date,
            absence_rows=absences.get(person.id, ()),
            overseas_rows=declarations.get(person.id, ()),
        )
        for person in event_service.active_roster()
    }


def candidates(period):
    """{slot_type: [Candidate]} — eligible people only (the trap lives in
    domain/manning.slot_eligible), no-known-conflict first, then roster
    order. Conflicted candidates are flagged, never hidden."""
    people = event_service.active_roster()
    checks = conflict_map(period)
    result = {}
    for slot in ManningSlotType:
        eligible = [p for p in people if manning.slot_eligible(slot, p)]
        rows = [Candidate(p, checks[p.id][0], checks[p.id][1]) for p in eligible]
        rows.sort(key=lambda c: c.status is manning.ManningConflict.CONFLICT)
        result[slot] = rows
    return result


# The generated structure's per-pair sizes, rebuilt from domain/manning's
# public constants. Used ONLY to count open slots for the S3's flash — the pure
# generator stays the one owner of what actually gets filled, so a mismatch here
# could misreport a message, never misfill a slot.
_STRUCTURE_NEEDS = {
    (ManningSlotType.TU_COMD, None): 1,
    (ManningSlotType.TU_PLANNER, None): 1,
    **{(ManningSlotType.TU_DET_COMD, det): 1 for det in manning.GENERATED_DETS},
    **{
        (ManningSlotType.DET_PERSONNEL, det): manning.DET_PERSONNEL_PER_DET
        for det in manning.GENERATED_DETS
    },
}


def _open_slots(existing) -> int:
    """Structure vacancies before generation: the fixed shape's size minus the
    surviving rows that already satisfy part of it. A row outside the generated
    structure (a det-3 pick, a fourth man in det 1) satisfies nothing, exactly
    as the pure generator treats it."""
    filled = defaultdict(int)
    for slot, det_number, _person_id in existing:
        filled[(slot, det_number)] += 1
    return sum(
        max(0, needed - filled[pair]) for pair, needed in _STRUCTURE_NEEDS.items()
    )


def generate_period(period):
    """Fill the period's fixed structure in ONE transaction, replacing only the
    generator's own rows — a manual pick is never re-planned.

    The `is_manual` split IS the regeneration contract: `True` rows survive and
    constrain the plan (their people are off the table, their slots count as
    satisfied), `False` rows are deleted and re-planned. The pools handed to the
    pure generator are pre-filtered HERE to no-known-conflict candidates — the
    generator re-checks nothing, so this filter is the only thing keeping a man
    on approved leave out of an activation det.

    Returns (filled, open_before): picks written, and the vacancies that existed
    before the run. Det-level shortfalls surface nowhere else (`doc.unfilled`
    reports HQ only), so those two numbers are the S3's signal that a thin pool
    left the structure incomplete.
    """
    db.session.query(ManningSlot).filter(
        ManningSlot.period_id == period.id,
        ManningSlot.is_manual.is_(False),
    ).delete()

    pools = {
        slot: [
            c.person.id
            for c in rows
            if c.status is manning.ManningConflict.NO_KNOWN_CONFLICT
        ]
        for slot, rows in candidates(period).items()
    }
    existing = [
        (row.slot, row.det_number, row.person_id)
        for row in db.session.query(ManningSlot)
        .filter(ManningSlot.period_id == period.id)
        .all()
    ]

    picks = manning.generate(pools=pools, existing=existing)
    for pick in picks:
        db.session.add(
            ManningSlot(
                period_id=period.id, slot=pick.slot, person_id=pick.person_id,
                det_number=pick.det_number, is_manual=False,
            )
        )
    db.session.commit()
    return len(picks), _open_slots(existing)


def assign_slot(period, slot, person, *, det_number):
    """Fill one slot. Eligibility is LAW (hard block); conflicts are judgment
    (the flag rides the pick list — no confirm step, the S3 saw it). The
    UNIQUE(period, person) constraint is the duplicate guard: no pre-check
    SELECT, the commit decides."""
    if not manning.slot_eligible(slot, person):
        raise IneligibleSlot(
            f"{person.display_name} can never hold {slot.ui_label} — appointment rule."
        )
    row = ManningSlot(
        period_id=period.id, slot=slot, person_id=person.id, det_number=det_number,
        is_manual=True,
    )
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise DuplicatePerson(
            f"{person.display_name} is already in this period — one slot per person."
        )
    return row


def remove_slot(slot_id) -> bool:
    row = db.session.get(ManningSlot, slot_id)
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def build_document(period) -> manning.ManningDoc:
    """Shape the period's slots into the pure render: 'RANK FULL NAME' caps
    (same convention as the RO), the keyed phone or None."""
    shaped = [
        _SlotRow(
            row.slot,
            row.det_number,
            f"{row.person.rank.value} {row.person.display_name.upper()}",
            row.person.phone,
        )
        for row in period.slots
    ]
    return manning.render_manning(period.start_date, period.end_date, slots=shaped)
