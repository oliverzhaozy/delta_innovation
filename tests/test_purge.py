"""P7.2 — annual retention purge (service + CLI).

Cutoff BEFORE = 2026-06-01: rows that fully ended before it go; rows on/after
or spanning it stay. The ledger collapses (never bare-deletes) so balances are
preserved and verified identical (A10).
"""
from datetime import date, datetime

from app.domain.types import (
    Appointment,
    BalanceKind,
    Calendar,
    DeclarationStatus,
    Duty,
    LeaveType,
    LedgerSource,
    ManningSlotType,
    Meal,
    ParticipantCategory,
    Rank,
    RequestStatus,
    StatusType,
)
from app.extensions import db
from app.models import (
    DutyAssignment,
    Event,
    EventParticipant,
    LeaveRequest,
    LedgerEntry,
    ManningPeriod,
    ManningSlot,
    MealAdjustment,
    OverseasDeclaration,
    Person,
    PersonAudit,
    RoDocument,
    RoExtraItem,
    StatusEntry,
)
from app.services import ledger_service, purge_service

BEFORE = date(2026, 6, 1)
OLD = datetime(2026, 1, 15, 9, 0)  # created_at well before the cutoff
NEW = datetime(2026, 6, 15, 9, 0)  # created_at on/after the cutoff


def _s3(make_person):
    return make_person(
        username="s3_admin",
        rank=Rank.TWO_SG,
        appointment=Appointment.DET_COMD,
        company_role="S3",
    )


def _pid(username):
    return db.session.query(Person.id).filter_by(username=username).scalar()


def _ledger(person_id, kind, delta, created_at, actor_id, leave_request_id=None, source=None):
    if source is None:
        source = LedgerSource.LEAVE_APPROVAL if leave_request_id else LedgerSource.MANUAL
    db.session.add(
        LedgerEntry(
            person_id=person_id,
            kind=kind,
            delta_half_days=delta,
            reason="seed",
            source=source,
            leave_request_id=leave_request_id,
            created_by_id=actor_id,
            created_at=created_at,
        )
    )


# --- balance identity + carry-forward collapse ---------------------------------


def test_balance_identity_and_carry_forward(app, make_person):
    make_person(username="pa")
    _s3(make_person)
    with app.app_context():
        pa, actor = _pid("pa"), _pid("s3_admin")
        # OFF: old +4, old -2 (sum +2 -> one carry-forward), new +6 survives.
        _ledger(pa, BalanceKind.OFF, 4, OLD, actor)
        _ledger(pa, BalanceKind.OFF, -2, OLD, actor)
        _ledger(pa, BalanceKind.OFF, 6, NEW, actor)
        # OIL: old +2, old -2 (sum 0 -> NO carry-forward row).
        _ledger(pa, BalanceKind.OIL, 2, OLD, actor)
        _ledger(pa, BalanceKind.OIL, -2, OLD, actor)
        db.session.commit()

        before = ledger_service.balances_for_everyone()
        result = purge_service.execute(BEFORE, actor=db.session.get(Person, actor))
        after = ledger_service.balances_for_everyone()

        assert after == before
        assert dict(result.counts)["ledger_entry"] == 4  # the four old rows collapsed (the +6 is new)

        carry = db.session.query(LedgerEntry).filter(LedgerEntry.reason.like("Carry-forward%")).all()
        assert len(carry) == 1
        row = carry[0]
        assert row.kind is BalanceKind.OFF
        assert row.delta_half_days == 2
        assert row.source is LedgerSource.MANUAL
        assert row.leave_request_id is None
        assert row.created_by_id == actor
        # The one surviving original new row + the carry-forward = two OFF rows.
        assert db.session.query(LedgerEntry).filter_by(person_id=pa, kind=BalanceKind.OFF).count() == 2
        assert db.session.query(LedgerEntry).filter_by(person_id=pa, kind=BalanceKind.OIL).count() == 0


# --- A10 FK edge: a new ledger row keeps its old leave request alive -----------


def test_a10_leave_kept_when_new_ledger_references_it(app, make_person):
    make_person(username="pb")
    _s3(make_person)
    with app.app_context():
        pb, actor = _pid("pb"), _pid("s3_admin")
        # L1 ended before cutoff but has a REVERSAL-era new ledger row -> kept.
        l1 = LeaveRequest(
            person_id=pb, type=LeaveType.OFF, start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 10), status=RequestStatus.APPROVED,
        )
        # L2 ended before cutoff, only old ledger rows -> gone.
        l2 = LeaveRequest(
            person_id=pb, type=LeaveType.OFF, start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 10), status=RequestStatus.APPROVED,
        )
        db.session.add_all([l1, l2])
        db.session.flush()
        _ledger(pb, BalanceKind.OFF, -4, OLD, actor, leave_request_id=l1.id)
        # A REVERSAL dated after the cutoff — survives and keeps l1 alive.
        _ledger(pb, BalanceKind.OFF, 4, NEW, actor, leave_request_id=l1.id, source=LedgerSource.REVERSAL)
        _ledger(pb, BalanceKind.OFF, -2, OLD, actor, leave_request_id=l2.id)
        db.session.commit()
        l1_id, l2_id = l1.id, l2.id

        before = ledger_service.balances_for_everyone()
        result = purge_service.execute(BEFORE, actor=db.session.get(Person, actor))
        after = ledger_service.balances_for_everyone()

        assert after == before
        assert db.session.get(LeaveRequest, l1_id) is not None  # kept: new row references it
        assert db.session.get(LeaveRequest, l2_id) is None  # gone: only old refs
        assert dict(result.counts)["leave_request"] == 1


# --- boundaries ----------------------------------------------------------------


def test_date_boundaries(app, make_person):
    make_person(username="pc")
    _s3(make_person)
    with app.app_context():
        pc, actor = _pid("pc"), _pid("s3_admin")

        def status(start, end):
            row = StatusEntry(
                person_id=pc, type=StatusType.MC, start_date=start, end_date=end,
                in_camp=False, created_by_id=actor,
            )
            db.session.add(row)
            return row

        purged = status(date(2026, 5, 31), date(2026, 5, 31))  # ended day before -> gone
        on_cutoff = status(date(2026, 6, 1), date(2026, 6, 1))  # ends on cutoff -> kept
        spanning = status(date(2026, 5, 30), date(2026, 6, 5))  # spans cutoff -> kept
        db.session.commit()
        ids = (purged.id, on_cutoff.id, spanning.id)

        purge_service.execute(BEFORE, actor=db.session.get(Person, actor))

        p_id, oc_id, sp_id = ids
        assert db.session.get(StatusEntry, p_id) is None
        assert db.session.get(StatusEntry, oc_id) is not None
        assert db.session.get(StatusEntry, sp_id) is not None


# --- cascades: delete-orphan children go with their purged parents -------------


def test_cascades_children_removed_with_parents(app, make_person):
    make_person(username="pd")
    _s3(make_person)
    with app.app_context():
        pd, actor = _pid("pd"), _pid("s3_admin")

        old_event = Event(
            calendar=Calendar.TP, title="old", start_dt=datetime(2026, 1, 1, 8, 0),
            end_dt=datetime(2026, 1, 1, 17, 0), created_by_id=actor,
        )
        old_event.participants.append(EventParticipant(category=ParticipantCategory.PLATOON_1))
        new_event = Event(
            calendar=Calendar.TP, title="new", start_dt=datetime(2026, 6, 10, 8, 0),
            end_dt=datetime(2026, 6, 10, 17, 0), created_by_id=actor,
        )
        new_event.participants.append(EventParticipant(person_id=pd))

        old_ro = RoDocument(date=date(2026, 1, 20), messages="x")
        old_ro.extra_items.append(RoExtraItem(text="old item"))
        new_ro = RoDocument(date=date(2026, 6, 20), messages="y")
        new_ro.extra_items.append(RoExtraItem(text="new item"))

        old_period = ManningPeriod(start_date=date(2026, 1, 1), end_date=date(2026, 1, 7), created_by_id=actor)
        old_period.slots.append(ManningSlot(slot=ManningSlotType.TU_COMD, person_id=pd, det_number=None))
        new_period = ManningPeriod(start_date=date(2026, 6, 2), end_date=date(2026, 6, 8), created_by_id=actor)
        new_period.slots.append(ManningSlot(slot=ManningSlotType.TU_COMD, person_id=pd, det_number=None))

        db.session.add_all([old_event, new_event, old_ro, new_ro, old_period, new_period])
        db.session.commit()
        keep_event, keep_ro, keep_period = new_event.id, new_ro.id, new_period.id

        purge_service.execute(BEFORE, actor=db.session.get(Person, actor))

        # Old parents and their children gone; new siblings and children survive.
        assert db.session.query(Event).count() == 1
        assert db.session.get(Event, keep_event) is not None
        assert db.session.query(EventParticipant).count() == 1
        assert db.session.query(RoDocument).count() == 1
        assert db.session.get(RoDocument, keep_ro) is not None
        assert db.session.query(RoExtraItem).count() == 1
        assert db.session.query(ManningPeriod).count() == 1
        assert db.session.get(ManningPeriod, keep_period) is not None
        assert db.session.query(ManningSlot).count() == 1


# --- dry-run writes nothing ----------------------------------------------------


def _seed_spread(actor, person_id):
    """One purgeable old row in every dated table (plus a ledger row)."""
    _ledger(person_id, BalanceKind.OFF, 4, OLD, actor)
    db.session.add_all([
        LeaveRequest(person_id=person_id, type=LeaveType.OFF, start_date=date(2026, 1, 1),
                     end_date=date(2026, 1, 2), status=RequestStatus.APPROVED),
        StatusEntry(person_id=person_id, type=StatusType.MC, start_date=date(2026, 1, 1),
                    end_date=date(2026, 1, 2), in_camp=False, created_by_id=actor),
        OverseasDeclaration(person_id=person_id, start_date=date(2026, 1, 1),
                            end_date=date(2026, 1, 2), destination="KL",
                            status=DeclarationStatus.APPROVED),
        DutyAssignment(date=date(2026, 1, 1), duty=Duty.COS, person_id=person_id,
                       created_by_id=actor),
        MealAdjustment(date=date(2026, 1, 1), meal=Meal.LUNCH, delta=1, reason="x", created_by_id=actor),
        PersonAudit(person_id=person_id, field="rank", old="PTE", new="CPL", actor_id=actor, at=OLD),
    ])
    event = Event(calendar=Calendar.TP, title="e", start_dt=datetime(2026, 1, 1, 8, 0),
                  end_dt=datetime(2026, 1, 1, 9, 0), created_by_id=actor)
    ro = RoDocument(date=date(2026, 1, 1), messages="m")
    period = ManningPeriod(start_date=date(2026, 1, 1), end_date=date(2026, 1, 7), created_by_id=actor)
    db.session.add_all([event, ro, period])


def _all_counts():
    return {
        "ledger_entry": db.session.query(LedgerEntry).count(),
        "leave_request": db.session.query(LeaveRequest).count(),
        "status_entry": db.session.query(StatusEntry).count(),
        "overseas_declaration": db.session.query(OverseasDeclaration).count(),
        "event": db.session.query(Event).count(),
        "duty_assignment": db.session.query(DutyAssignment).count(),
        "ro_document": db.session.query(RoDocument).count(),
        "manning_period": db.session.query(ManningPeriod).count(),
        "meal_adjustment": db.session.query(MealAdjustment).count(),
        "person_audit": db.session.query(PersonAudit).count(),
    }


def test_dry_run_changes_nothing(app, make_person):
    make_person(username="pe")
    _s3(make_person)
    with app.app_context():
        _seed_spread(_pid("s3_admin"), _pid("pe"))
        db.session.commit()
        before = _all_counts()

    result = app.test_cli_runner().invoke(
        args=["purge", "--before", "2026-06-01", "--by", "s3_admin"]
    )
    assert result.exit_code == 0, result.output
    assert "ledger_entry" in result.output
    assert "Dry run" in result.output

    with app.app_context():
        assert _all_counts() == before  # nothing written


def test_execute_via_cli_reports_identical_balances(app, make_person):
    make_person(username="pf")
    _s3(make_person)
    with app.app_context():
        pf, actor = _pid("pf"), _pid("s3_admin")
        _ledger(pf, BalanceKind.OFF, 4, OLD, actor)
        _ledger(pf, BalanceKind.OFF, 6, NEW, actor)
        db.session.commit()

    result = app.test_cli_runner().invoke(
        args=["purge", "--before", "2026-06-01", "--by", "s3_admin", "--execute"]
    )
    assert result.exit_code == 0, result.output
    assert "Balances verified identical." in result.output

    with app.app_context():
        pf = _pid("pf")
        assert ledger_service.balance(pf, BalanceKind.OFF) == 10  # 4 + 6 preserved


# --- CLI contract: bad input errors and deletes nothing ------------------------


def test_cli_unknown_username_errors(app, make_person):
    make_person(username="pg")
    _s3(make_person)
    with app.app_context():
        _ledger(_pid("s3_admin"), BalanceKind.OFF, 4, OLD, _pid("s3_admin"))
        db.session.commit()

    result = app.test_cli_runner().invoke(
        args=["purge", "--before", "2026-06-01", "--by", "nobody", "--execute"]
    )
    assert result.exit_code != 0
    assert "No such user" in result.output
    with app.app_context():
        assert db.session.query(LedgerEntry).count() == 1  # untouched


def test_cli_missing_by_errors(app, make_person):
    _s3(make_person)
    result = app.test_cli_runner().invoke(args=["purge", "--before", "2026-06-01"])
    assert result.exit_code != 0
    assert "Missing option" in result.output or "--by" in result.output


def test_cli_malformed_date_errors(app, make_person):
    _s3(make_person)
    result = app.test_cli_runner().invoke(
        args=["purge", "--before", "01-06-2026", "--by", "s3_admin"]
    )
    assert result.exit_code != 0
