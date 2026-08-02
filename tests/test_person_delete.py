"""Post-out hard-delete cascade (owner decision (dd) 2026-07-30).

`person_service.delete_person` removes the person AND every row referencing
them — including records they actioned on other people, which is the part that
changes other people's balances. These tests pin that blast radius deliberately:
if a future change narrows it, the balance assertion in
`test_deleting_an_approver_destroys_the_leave_they_approved` is the tripwire.
"""
import datetime

import pytest

from app.domain.types import (
    Appointment,
    BalanceKind,
    Calendar,
    DayPart,
    DeclarationStatus,
    Duty,
    LeaveType,
    LedgerSource,
    ManningSlotType,
    ManningStatus,
    OverrideCategory,
    ParadeVariant,
    ParticipantCategory,
    RequestStatus,
    StatusType,
)
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
    OverseasDeclaration,
    ParadeOverride,
    Person,
    PersonAudit,
    StatusEntry,
)
from app.services import ledger_service, person_service
from tests.conftest import login

DAY = datetime.date(2026, 8, 5)  # a Wednesday


def _pid(username):
    return db.session.query(Person.id).filter_by(username=username).scalar()


def _person(username):
    return db.session.query(Person).filter_by(username=username).one()


def make_s3(make_person):
    return make_person(
        username="s3_admin", display_name="S3 Admin", appointment=Appointment.PS,
        company_role="S3", is_admin=True,
    )


# --- (a) the subject's own rows, across every table ---------------------------

def test_delete_removes_the_subjects_own_rows_across_tables(app, make_person):
    make_person(username="leaver")
    make_person(username="keeper", platoon=2)
    with app.app_context():
        leaver_id, keeper_id = _pid("leaver"), _pid("keeper")
        leave = LeaveRequest(
            person_id=leaver_id, type=LeaveType.OFF, start_date=DAY, end_date=DAY,
            day_part=DayPart.FULL, status=RequestStatus.APPROVED,
        )
        db.session.add(leave)
        db.session.flush()
        db.session.add_all([
            LedgerEntry(
                person_id=leaver_id, kind=BalanceKind.OFF, delta_half_days=-2,
                reason="Leave", source=LedgerSource.LEAVE_APPROVAL,
                leave_request_id=leave.id, created_by_id=keeper_id,
            ),
            StatusEntry(
                person_id=leaver_id, type=StatusType.MC, start_date=DAY, end_date=DAY,
                day_part=DayPart.FULL, in_camp=False, created_by_id=keeper_id,
            ),
            DutyAssignment(
                date=DAY, duty=Duty.COS, person_id=leaver_id, created_by_id=keeper_id,
            ),
            OverseasDeclaration(
                person_id=leaver_id, start_date=DAY, end_date=DAY, destination="Malaysia",
                status=DeclarationStatus.APPROVED,
            ),
            ParadeOverride(
                date=DAY, variant=ParadeVariant.MORNING, person_id=leaver_id,
                target_category=OverrideCategory.MC, created_by_id=keeper_id,
            ),
            PersonAudit(
                person_id=leaver_id, field="stay_out", old="no", new="yes",
                actor_id=keeper_id,
            ),
        ])
        db.session.commit()

        counts = person_service.delete_person(_person("leaver"), actor=_person("keeper"))

    with app.app_context():
        assert db.session.get(Person, leaver_id) is None
        for model in (
            LeaveRequest, LedgerEntry, StatusEntry, DutyAssignment,
            OverseasDeclaration, ParadeOverride, PersonAudit,
        ):
            assert db.session.query(model).count() == 0, model.__name__
        # The other person is untouched.
        assert db.session.get(Person, keeper_id) is not None
    # The summary names every table it emptied, so the flash can be concrete.
    assert counts["person"] == 1
    assert counts["leave_request"] == 1
    assert counts["ledger_entry"] == 1
    assert counts["status_entry"] == 1
    assert counts["duty_assignment"] == 1
    assert counts["overseas_declaration"] == 1
    assert counts["parade_override"] == 1
    assert counts["person_audit"] == 1


def test_delete_removes_rows_the_person_created_for_others(app, make_person):
    # The blanket half of the cascade: rows whose SUBJECT is someone else but
    # whose creator was the leaver. A blocked duty day going means that date
    # carries duty again — the owner accepted that.
    make_person(username="keyer")
    make_person(username="subject", platoon=2)
    with app.app_context():
        keyer_id, subject_id = _pid("keyer"), _pid("subject")
        db.session.add_all([
            StatusEntry(
                person_id=subject_id, type=StatusType.MC, start_date=DAY, end_date=DAY,
                day_part=DayPart.FULL, in_camp=False, created_by_id=keyer_id,
            ),
            DutyBlockedDay(date=DAY, created_by_id=keyer_id),
        ])
        db.session.commit()

        counts = person_service.delete_person(_person("keyer"), actor=_person("subject"))

    with app.app_context():
        assert db.session.query(StatusEntry).count() == 0
        assert db.session.query(DutyBlockedDay).count() == 0
        assert db.session.get(Person, subject_id) is not None
    assert counts["status_entry"] == 1
    assert counts["duty_blocked_day"] == 1


# --- (b) deleting an approver takes other people's leave AND ledger with it ----

def test_deleting_an_approver_destroys_the_leave_they_approved(app, make_person):
    # THE consequence the owner was warned about: the requester keeps existing,
    # but their approved leave and its deduction vanish, so their balance moves.
    make_person(username="requester")
    make_person(username="approver", appointment=Appointment.PC, platoon=2)
    make_person(username="bystander", platoon=3)
    with app.app_context():
        requester_id = _pid("requester")
        approver_id = _pid("approver")
        bystander_id = _pid("bystander")
        # Opening balance posted by someone who survives, so only the leave
        # deduction is at risk.
        ledger_service.post_entry(
            person_id=requester_id, kind=BalanceKind.OFF, delta_half_days=14,
            reason="Opening", source=LedgerSource.MANUAL, created_by_id=bystander_id,
        )
        leave = LeaveRequest(
            person_id=requester_id, type=LeaveType.OFF, start_date=DAY, end_date=DAY,
            day_part=DayPart.FULL, status=RequestStatus.APPROVED,
            pc_actor_id=approver_id, oc_actor_id=bystander_id,
        )
        db.session.add(leave)
        db.session.flush()
        ledger_service.post_entry(
            person_id=requester_id, kind=BalanceKind.OFF, delta_half_days=-2,
            reason="Leave", source=LedgerSource.LEAVE_APPROVAL,
            created_by_id=approver_id, leave_request_id=leave.id,
        )
        db.session.commit()
        assert ledger_service.balance(requester_id, BalanceKind.OFF) == 12

        counts = person_service.delete_person(_person("approver"), actor=_person("bystander"))

    with app.app_context():
        assert db.session.get(Person, approver_id) is None
        # The requester survives; their leave and its deduction do not.
        assert db.session.get(Person, requester_id) is not None
        assert db.session.query(LeaveRequest).count() == 0
        # Balance moved back up by the destroyed deduction — the accepted cost.
        assert ledger_service.balance(requester_id, BalanceKind.OFF) == 14
    assert counts["leave_request"] == 1
    assert counts["ledger_entry"] == 1  # only the deduction; the opening row stays


def test_ledger_rows_of_a_doomed_leave_go_even_when_posted_by_a_survivor(app, make_person):
    # The subtle FK edge: the ledger row belongs to the requester and was posted
    # by a survivor, but it hangs off leave the deleted person decided — so it
    # must go, or the leave delete would trip foreign_keys=ON.
    make_person(username="req")
    make_person(username="oc_actor", appointment=Appointment.PC, platoon=2)
    make_person(username="poster", platoon=3)
    with app.app_context():
        req_id, oc_id, poster_id = _pid("req"), _pid("oc_actor"), _pid("poster")
        leave = LeaveRequest(
            person_id=req_id, type=LeaveType.OFF, start_date=DAY, end_date=DAY,
            day_part=DayPart.FULL, status=RequestStatus.APPROVED, oc_actor_id=oc_id,
        )
        db.session.add(leave)
        db.session.flush()
        ledger_service.post_entry(
            person_id=req_id, kind=BalanceKind.OFF, delta_half_days=-2,
            reason="Leave", source=LedgerSource.LEAVE_APPROVAL,
            created_by_id=poster_id, leave_request_id=leave.id,
        )
        db.session.commit()

        person_service.delete_person(_person("oc_actor"), actor=_person("poster"))

    with app.app_context():
        assert db.session.query(LeaveRequest).count() == 0
        assert db.session.query(LedgerEntry).count() == 0
        assert db.session.get(Person, req_id) is not None


# --- (c) events created by the person, with their participant rows ------------

def test_events_created_by_the_person_go_with_their_participants(app, make_person):
    make_person(username="organiser")
    make_person(username="attendee", platoon=2)
    with app.app_context():
        organiser_id, attendee_id = _pid("organiser"), _pid("attendee")
        mine = Event(
            calendar=Calendar.TP, title="Mine", start_dt=datetime.datetime(2026, 8, 5, 9),
            end_dt=datetime.datetime(2026, 8, 5, 17), created_by_id=organiser_id,
        )
        theirs = Event(
            calendar=Calendar.TP, title="Theirs", start_dt=datetime.datetime(2026, 8, 6, 9),
            end_dt=datetime.datetime(2026, 8, 6, 17), created_by_id=attendee_id,
        )
        db.session.add_all([mine, theirs])
        db.session.flush()
        db.session.add_all([
            # Two participants on the doomed event: a person row and a category row.
            EventParticipant(event_id=mine.id, person_id=attendee_id, include=True),
            EventParticipant(
                event_id=mine.id, category=ParticipantCategory.NSF, include=True
            ),
            # The leaver's own participation in an event that SURVIVES.
            EventParticipant(event_id=theirs.id, person_id=organiser_id, include=True),
            EventParticipant(
                event_id=theirs.id, category=ParticipantCategory.NSF, include=True
            ),
        ])
        db.session.commit()
        theirs_id = theirs.id

        counts = person_service.delete_person(_person("organiser"), actor=_person("attendee"))

    with app.app_context():
        # The event they created is gone, participant rows and all.
        assert db.session.query(Event).filter_by(title="Mine").count() == 0
        # The other person's event survives, minus the leaver's participant row.
        assert db.session.get(Event, theirs_id) is not None
        remaining = db.session.query(EventParticipant).all()
        assert len(remaining) == 1
        assert remaining[0].event_id == theirs_id
        assert remaining[0].category is ParticipantCategory.NSF
    assert counts["event"] == 1
    assert counts["event_participant"] == 3  # 2 on the doomed event + 1 elsewhere


# --- (d) manning slots leave surviving periods --------------------------------

def test_manning_slots_are_removed_from_surviving_periods(app, make_person):
    make_person(username="det_opr")
    make_person(username="planner", appointment=Appointment.PS, platoon=2)
    with app.app_context():
        opr_id, planner_id = _pid("det_opr"), _pid("planner")
        # A period built by the SURVIVOR that the leaver holds a slot in.
        survives = ManningPeriod(start_date=DAY, end_date=DAY, created_by_id=planner_id)
        # A period the leaver built themselves — it goes wholesale.
        doomed = ManningPeriod(start_date=DAY, end_date=DAY, created_by_id=opr_id)
        db.session.add_all([survives, doomed])
        db.session.flush()
        db.session.add_all([
            ManningSlot(
                period_id=survives.id, slot=ManningSlotType.DET_PERSONNEL,
                person_id=opr_id, det_number=1,
            ),
            ManningSlot(
                period_id=survives.id, slot=ManningSlotType.TU_PLANNER,
                person_id=planner_id,
            ),
            ManningSlot(
                period_id=doomed.id, slot=ManningSlotType.DET_PERSONNEL,
                person_id=planner_id, det_number=1,
            ),
        ])
        db.session.commit()
        survives_id, doomed_id = survives.id, doomed.id

        counts = person_service.delete_person(_person("det_opr"), actor=_person("planner"))

    with app.app_context():
        assert db.session.get(ManningPeriod, doomed_id) is None
        period = db.session.get(ManningPeriod, survives_id)
        assert period is not None
        # Only the planner's own slot is left in the surviving period.
        assert [s.slot for s in period.slots] == [ManningSlotType.TU_PLANNER]
    assert counts["manning_period"] == 1
    assert counts["manning_slot"] == 2  # the leaver's slot + the doomed period's


def test_periods_the_person_confirmed_or_approved_go_too(app, make_person):
    # Decision (ff) meeting decision (dd): the approval trail is a record they
    # actioned on someone else's period, so the period goes with them — the same
    # blast radius as leave they approved.
    make_person(username="confirmer")
    make_person(username="builder_ps", appointment=Appointment.PS, platoon=2)
    make_person(username="slot_holder", platoon=3)
    with app.app_context():
        confirmer_id = _pid("confirmer")
        builder_id = _pid("builder_ps")
        holder_id = _pid("slot_holder")
        confirmed = ManningPeriod(
            start_date=DAY, end_date=DAY, created_by_id=builder_id,
            status=ManningStatus.PENDING, confirmed_by_id=confirmer_id,
        )
        approved = ManningPeriod(
            start_date=DAY, end_date=DAY, created_by_id=builder_id,
            status=ManningStatus.APPROVED, confirmed_by_id=builder_id,
            pc_actor_id=confirmer_id,
        )
        untouched = ManningPeriod(
            start_date=DAY, end_date=DAY, created_by_id=builder_id,
        )
        db.session.add_all([confirmed, approved, untouched])
        db.session.flush()
        # A slot belonging to a SURVIVOR, on a period that is doomed anyway.
        db.session.add(ManningSlot(
            period_id=confirmed.id, slot=ManningSlotType.TU_PLANNER,
            person_id=holder_id,
        ))
        db.session.commit()
        untouched_id = untouched.id
        assert untouched.status is ManningStatus.DRAFT

        counts = person_service.delete_person(
            _person("confirmer"), actor=_person("builder_ps")
        )

    with app.app_context():
        assert [p.id for p in db.session.query(ManningPeriod).all()] == [untouched_id]
        assert db.session.query(ManningSlot).count() == 0
    assert counts["manning_period"] == 2
    assert counts["manning_slot"] == 1


# --- the self-delete backstop -------------------------------------------------

def test_service_refuses_to_delete_the_actor(app, make_person):
    make_person(username="solo")
    with app.app_context():
        solo = _person("solo")
        with pytest.raises(ValueError, match="own account"):
            person_service.delete_person(solo, actor=solo)
        # Nothing was committed.
        assert db.session.query(Person).count() == 1


# --- (e) the route ------------------------------------------------------------

def test_route_deletes_and_flashes_what_went(app, client, make_person):
    make_person(username="posted_out")
    login(client, make_s3(make_person))
    with app.app_context():
        target_id = _pid("posted_out")
        db.session.add(
            StatusEntry(
                person_id=target_id, type=StatusType.MC, start_date=DAY, end_date=DAY,
                day_part=DayPart.FULL, in_camp=False, created_by_id=target_id,
            )
        )
        db.session.commit()

    resp = client.post(f"/admin/people/{target_id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Deleted Posted Out" in body
    assert "status_entry (1)" in body
    assert "person (1)" in body
    with app.app_context():
        assert db.session.get(Person, target_id) is None
        assert db.session.query(StatusEntry).count() == 0


def test_route_blocks_self_delete(app, client, make_person):
    make_s3(make_person)
    login(client, "s3_admin")
    with app.app_context():
        own_id = _pid("s3_admin")
    resp = client.post(f"/admin/people/{own_id}/delete", follow_redirects=True)
    assert b"can&#39;t delete your own account" in resp.data
    with app.app_context():
        assert db.session.get(Person, own_id) is not None


def test_route_forbidden_for_non_admin(app, client, make_person):
    make_person(username="plain_opr")
    make_person(username="victim", platoon=2)
    login(client, "plain_opr")
    with app.app_context():
        victim_id = _pid("victim")
    assert client.post(f"/admin/people/{victim_id}/delete").status_code == 403
    with app.app_context():
        assert db.session.get(Person, victim_id) is not None


def test_route_unknown_person_is_404(app, client, make_person):
    login(client, make_s3(make_person))
    assert client.post("/admin/people/99999/delete").status_code == 404
