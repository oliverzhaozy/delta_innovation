"""Person post-out (owner decision (dd) 2026-07-30).

When someone ORDs or posts out they are HARD-deleted along with every row that
references them — not just their own leave/status/duty history, but the records
they actioned on other people (leave they approved, statuses they keyed, duty
they assigned). The owner chose this knowingly: those other people's rows
disappear too, so balances and past documents change. It is the deliberate
reversal of the repo's "rows are never deleted" stance, and the reason there is
no longer an `is_active` flag to soft-delete with.

The delete order below is CHILD-FIRST, which is the whole design constraint:
`foreign_keys=ON` is set per connection, so a parent removed before its children
raises IntegrityError. So the ledger goes before leave (a ledger row FKs both
person and leave_request), participants before events, slots before periods, and
the person row goes last.

Every delete is a bulk `query.delete()` whose rowcount feeds the summary — no
ORM-object deletes, so no reliance on `all, delete-orphan` cascades (which bulk
deletes do NOT fire): the children this cascade would drop are named explicitly
above their parents instead. That keeps the returned counts exact.
"""
from app.extensions import db
from app.models import (
    DutyAssignment,
    DutyBlockedDay,
    Event,
    EventParticipant,
    LeaveRequest,
    LedgerEntry,
    ManningPeriod,
    ManningSlot,
    MealAdjustment,
    OverseasDeclaration,
    ParadeOverride,
    PersonAudit,
    StatusEntry,
)


def delete_person(person, *, actor):
    """Hard-delete `person` and everything referencing them, in one transaction.

    Returns `{table_name: rows_deleted}` for every table that lost rows (tables
    that lost none are omitted), so the caller can report something concrete.

    `actor` (keyword-only, no default) is the signed-in person performing the
    delete. Deleting yourself would destroy the row backing the live session
    mid-request, so it raises `ValueError` — a structural backstop beneath the
    admin route's user-facing guard, not a second copy of it.
    """
    if actor.id == person.id:
        raise ValueError("a person cannot delete their own account")

    person_id = person.id
    counts = {}

    def _delete(label, model, condition):
        removed = db.session.query(model).filter(condition).delete(synchronize_session=False)
        if removed:
            counts[label] = removed

    # Sub-selects for the two parent tables whose children must go first. Both
    # are evaluated inside the child DELETE, before the parent rows are removed.
    events_created = db.session.query(Event.id).filter(Event.created_by_id == person_id)
    periods_created = db.session.query(ManningPeriod.id).filter(
        ManningPeriod.created_by_id == person_id
    )

    # 1. Ledger — their own rows, rows they posted for others, and rows hanging
    #    off any leave request about to go in step 2. That last set is OTHER
    #    people's balances changing; the owner accepted it explicitly.
    doomed_leave = db.session.query(LeaveRequest.id).filter(
        db.or_(
            LeaveRequest.person_id == person_id,
            LeaveRequest.pc_actor_id == person_id,
            LeaveRequest.oc_actor_id == person_id,
        )
    )
    _delete(
        "ledger_entry",
        LedgerEntry,
        db.or_(
            LedgerEntry.person_id == person_id,
            LedgerEntry.created_by_id == person_id,
            LedgerEntry.leave_request_id.in_(doomed_leave),
        ),
    )

    # 2. Leave requests: theirs, plus everyone's that they decided on.
    _delete(
        "leave_request",
        LeaveRequest,
        db.or_(
            LeaveRequest.person_id == person_id,
            LeaveRequest.pc_actor_id == person_id,
            LeaveRequest.oc_actor_id == person_id,
        ),
    )

    # 3. Statuses they hold or keyed.
    _delete(
        "status_entry",
        StatusEntry,
        db.or_(StatusEntry.person_id == person_id, StatusEntry.created_by_id == person_id),
    )

    # 4. Duty. Dropping a blocked day they created makes that date a duty day
    #    again — accepted as part of the blanket cascade.
    _delete(
        "duty_assignment",
        DutyAssignment,
        db.or_(
            DutyAssignment.person_id == person_id,
            DutyAssignment.created_by_id == person_id,
        ),
    )
    _delete("duty_blocked_day", DutyBlockedDay, DutyBlockedDay.created_by_id == person_id)

    # 5. Dormant meal adjustments they keyed.
    _delete("meal_adjustment", MealAdjustment, MealAdjustment.created_by_id == person_id)

    # 6. Events: their participation in anyone's event, plus every participant of
    #    the events they created, then those events.
    _delete(
        "event_participant",
        EventParticipant,
        db.or_(
            EventParticipant.person_id == person_id,
            EventParticipant.event_id.in_(events_created),
        ),
    )
    _delete("event", Event, Event.created_by_id == person_id)

    # 7. Manning: same child-then-parent shape as events.
    _delete(
        "manning_slot",
        ManningSlot,
        db.or_(
            ManningSlot.person_id == person_id,
            ManningSlot.period_id.in_(periods_created),
        ),
    )
    _delete("manning_period", ManningPeriod, ManningPeriod.created_by_id == person_id)

    # 8. Overseas declarations they made or decided.
    _delete(
        "overseas_declaration",
        OverseasDeclaration,
        db.or_(
            OverseasDeclaration.person_id == person_id,
            OverseasDeclaration.pc_actor_id == person_id,
        ),
    )

    # 9. Parade overrides about them or dragged by them.
    _delete(
        "parade_override",
        ParadeOverride,
        db.or_(
            ParadeOverride.person_id == person_id,
            ParadeOverride.created_by_id == person_id,
        ),
    )

    # 10. Audit trail about them and by them — including the rows recording their
    #     edits to others, which is why no trace of them survives.
    _delete(
        "person_audit",
        PersonAudit,
        db.or_(PersonAudit.person_id == person_id, PersonAudit.actor_id == person_id),
    )

    # 11. Finally the person themselves, now unreferenced.
    db.session.delete(person)
    counts["person"] = 1

    db.session.commit()
    return counts
