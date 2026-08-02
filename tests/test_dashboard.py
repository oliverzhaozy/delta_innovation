"""Task A — the Home to-do dashboard's backend: the queue queries that moved
into their owning services, and dashboard_service's per-role assembly.

Everything here is service-level (no HTTP): `build_dashboard` takes a Person and
returns the namedtuple the template will consume. Dates are relative to
`today_sgt()` because the dashboard's whole contract is "from today onwards" —
the same idiom as tests/test_duty_rights.py.
"""
from contextlib import contextmanager
from datetime import date, timedelta

import pytest

from app.domain.dates import adjacent_ym, today_sgt
from app.domain.types import (
    Appointment,
    CompanyRole,
    DayPart,
    DeclarationStatus,
    Duty,
    LeaveType,
    ManningSlotType,
    ManningStatus,
    Rank,
    RequestStatus,
    Service,
    StatusType,
)
from app.extensions import db
from app.models import (
    DutyAssignment,
    LeaveRequest,
    ManningPeriod,
    ManningSlot,
    OverseasDeclaration,
    Person,
    StatusEntry,
)
from app.services import (
    dashboard_service,
    duty_service,
    leave_service,
    manning_service,
    overseas_service,
)
from tests.conftest import login

TODAY = today_sgt()
TOMORROW = TODAY + timedelta(days=1)
YESTERDAY = TODAY - timedelta(days=1)


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def get_person(username):
    """Live Person row — call inside an app context."""
    return db.session.query(Person).filter_by(username=username).one()


def make_cast(make_person):
    make_person(username="oc", rank=Rank.CPT, appointment=Appointment.OC,
                platoon=None, service=Service.REGULAR, display_name="Wong Li Xuan")
    make_person(username="pc1", rank=Rank.LTA, appointment=Appointment.PC,
                display_name="Quek Jing Yu")
    make_person(username="ps2", rank=Rank.THREE_SG, appointment=Appointment.PS,
                platoon=2, display_name="Lim Wei Han")
    # The S3 is an Opr with the company role: appointment stays outside the
    # command team, so this fixture unlocks the manning cards ALONE.
    make_person(username="s3", rank=Rank.CPL, appointment=Appointment.OPR,
                company_role=CompanyRole.S3, display_name="Tan Boon Keat")
    make_person(username="opr1", rank=Rank.CPL, appointment=Appointment.OPR,
                display_name="Ang Cheng Ze")


def plant_leave(app, person_id, start, end, *, status=RequestStatus.APPROVED,
                type_=LeaveType.OFF, remarks=None, pc_actor=None, oc_actor=None):
    with app.app_context():
        row = LeaveRequest(
            person_id=person_id, type=type_, start_date=start, end_date=end,
            day_part=DayPart.FULL, status=status, remarks=remarks,
        )
        if pc_actor is not None:
            row.pc_actor_id = pid(app, pc_actor)
        if oc_actor is not None:
            row.oc_actor_id = pid(app, oc_actor)
        db.session.add(row)
        db.session.commit()
        return row.id


def plant_status(app, person_id, start, end, *, type_=StatusType.MC, in_camp=False):
    with app.app_context():
        db.session.add(StatusEntry(
            person_id=person_id, type=type_, start_date=start, end_date=end,
            day_part=DayPart.FULL, in_camp=in_camp, created_by_id=person_id,
        ))
        db.session.commit()


def plant_assignment(app, person_id, day, duty, *, is_manual=True):
    with app.app_context():
        row = DutyAssignment(
            date=day, duty=duty, person_id=person_id, is_manual=is_manual,
            created_by_id=person_id,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def plant_period(app, start, end, *, creator="s3", status=ManningStatus.DRAFT,
                 remarks=None, confirmed_by=None):
    with app.app_context():
        period = ManningPeriod(
            start_date=start, end_date=end, created_by_id=pid(app, creator),
            status=status, remarks=remarks,
        )
        if confirmed_by is not None:
            period.confirmed_by_id = pid(app, confirmed_by)
        db.session.add(period)
        db.session.commit()
        return period.id


def plant_slot(app, period_id, person_id, slot, *, det_number=None):
    with app.app_context():
        db.session.add(ManningSlot(
            period_id=period_id, person_id=person_id, slot=slot,
            det_number=det_number, is_manual=True,
        ))
        db.session.commit()


def plant_declaration(app, person_id, start, end, *, status=DeclarationStatus.PENDING,
                      destination="Johor", remarks=None, pc_actor=None):
    with app.app_context():
        row = OverseasDeclaration(
            person_id=person_id, start_date=start, end_date=end,
            destination=destination, status=status, remarks=remarks,
        )
        if pc_actor is not None:
            row.pc_actor_id = pid(app, pc_actor)
        db.session.add(row)
        db.session.commit()
        return row.id


@contextmanager
def dashboard_for(app, username):
    """Build AND assert inside one app context: the Dashboard carries live ORM
    rows, which detach the moment the context closes."""
    with app.app_context():
        yield dashboard_service.build_dashboard(get_person(username))


# --- the queue queries that moved into their owning services -------------------

def test_sent_back_periods_is_draft_with_remarks_only(app, make_person):
    make_cast(make_person)
    later = plant_period(app, TODAY + timedelta(days=20), TODAY + timedelta(days=24),
                         remarks="Det 2 is thin")
    earlier = plant_period(app, TODAY + timedelta(days=3), TODAY + timedelta(days=6),
                           remarks="Swap the planner")
    plant_period(app, TODAY, TODAY + timedelta(days=2))  # DRAFT, never decided
    plant_period(app, TODAY, TODAY + timedelta(days=2), status=ManningStatus.PENDING,
                 remarks="stale remark on a re-confirmed period")

    with app.app_context():
        rows = manning_service.sent_back_periods()
        assert [r.id for r in rows] == [earlier, later]  # soonest first
        assert rows[0].remarks == "Swap the planner"


def test_periods_from_excludes_elapsed_and_orders_soonest_first(app, make_person):
    make_cast(make_person)
    plant_period(app, TODAY - timedelta(days=10), YESTERDAY)
    running = plant_period(app, YESTERDAY, TODAY)
    future = plant_period(app, TODAY + timedelta(days=30), TODAY + timedelta(days=33))

    with app.app_context():
        assert [p.id for p in manning_service.periods_from(TODAY)] == [running, future]


def test_assignments_for_person_windows_from_start_and_is_keyword_only(app, make_person):
    make_cast(make_person)
    person_id = pid(app, "opr1")
    plant_assignment(app, person_id, YESTERDAY, Duty.COS)
    plant_assignment(app, person_id, TODAY + timedelta(days=4), Duty.CDOS)
    plant_assignment(app, person_id, TODAY, Duty.COS)
    plant_assignment(app, pid(app, "ps2"), TODAY, Duty.CDOS)

    with app.app_context():
        rows = duty_service.assignments_for_person(person_id, start=TODAY)
        assert [r.date for r in rows] == [TODAY, TODAY + timedelta(days=4)]
        # Keyword-only with no default: a stale positional caller must break
        # loudly rather than silently fetch every duty ever held.
        with pytest.raises(TypeError):
            duty_service.assignments_for_person(person_id, TODAY)


def test_pending_requests_filters_status_and_orders_by_start_then_created(app, make_person):
    make_cast(make_person)
    person_id = pid(app, "opr1")
    late = plant_leave(app, person_id, TODAY + timedelta(days=5), TODAY + timedelta(days=5),
                       status=RequestStatus.PENDING_PC)
    overdue = plant_leave(app, person_id, YESTERDAY, YESTERDAY,
                          status=RequestStatus.PENDING_PC)
    plant_leave(app, person_id, TODAY, TODAY, status=RequestStatus.PENDING_OC)
    with app.app_context():
        # Same start_date as `late`: created_at breaks the tie, so force the order.
        row = db.session.get(LeaveRequest, late)
        row.created_at = row.created_at + timedelta(hours=1)
        db.session.commit()
    tie = plant_leave(app, person_id, TODAY + timedelta(days=5), TODAY + timedelta(days=5),
                      status=RequestStatus.PENDING_PC)

    with app.app_context():
        rows = leave_service.pending_requests(RequestStatus.PENDING_PC)
        assert [r.id for r in rows] == [overdue, tie, late]
        oc_rows = leave_service.pending_requests(RequestStatus.PENDING_OC)
        assert [r.status for r in oc_rows] == [RequestStatus.PENDING_OC]


def test_rejected_live_requests_keeps_only_the_current_rejections(app, make_person):
    make_cast(make_person)
    opr_id = pid(app, "opr1")
    by_oc = plant_leave(app, opr_id, TODAY + timedelta(days=6), TODAY + timedelta(days=6),
                        status=RequestStatus.REJECTED_OC)
    by_pc = plant_leave(app, opr_id, TODAY, TOMORROW, status=RequestStatus.REJECTED_PC)
    elapsed = plant_leave(app, opr_id, TODAY - timedelta(days=3), YESTERDAY,
                          status=RequestStatus.REJECTED_PC)
    plant_leave(app, opr_id, TODAY, TODAY, status=RequestStatus.CANCELLED)
    plant_leave(app, opr_id, TODAY, TODAY, status=RequestStatus.APPROVED)
    plant_leave(app, pid(app, "ps2"), TODAY, TODAY, status=RequestStatus.REJECTED_PC)

    with app.app_context():
        assert [r.id for r in leave_service.rejected_live_requests(opr_id)] == [by_pc, by_oc]
        # A second READ, not a move: every one of them is still in history, the
        # elapsed one included (that row's only home from now on).
        concluded = {r.id for r in leave_service.concluded_requests(opr_id)}
        assert {by_pc, by_oc, elapsed} <= concluded


def test_rejected_by_names_the_step_that_turned_it_down(app, make_person):
    make_cast(make_person)
    opr_id = pid(app, "opr1")
    at_pc = plant_leave(app, opr_id, TODAY, TODAY, status=RequestStatus.REJECTED_PC,
                        pc_actor="pc1")
    # Past the PC before the OC refused it, so both actors are stamped.
    at_oc = plant_leave(app, opr_id, TOMORROW, TOMORROW, status=RequestStatus.REJECTED_OC,
                        pc_actor="pc1", oc_actor="oc")

    with app.app_context():
        assert db.session.get(LeaveRequest, at_pc).rejected_by.username == "pc1"
        assert db.session.get(LeaveRequest, at_oc).rejected_by.username == "oc"


def test_rejected_declarations_for_scopes_person_status_and_date(app, make_person):
    make_cast(make_person)
    opr_id = pid(app, "opr1")
    mine = plant_declaration(app, opr_id, TOMORROW, TODAY + timedelta(days=4),
                             status=DeclarationStatus.REJECTED)
    elapsed = plant_declaration(app, opr_id, TODAY - timedelta(days=5), YESTERDAY,
                                status=DeclarationStatus.REJECTED)
    plant_declaration(app, opr_id, TOMORROW, TOMORROW)  # still PENDING
    plant_declaration(app, pid(app, "ps2"), TOMORROW, TOMORROW,
                      status=DeclarationStatus.REJECTED)

    with app.app_context():
        assert [d.id for d in overseas_service.rejected_declarations_for(opr_id)] == [mine]
        # Filter, not purge: the declarant's own pages are read-only, so the
        # elapsed row is skipped here and left for purge_expired to delete.
        assert db.session.get(OverseasDeclaration, elapsed) is not None


# --- build_dashboard: the always-on today panel --------------------------------

def test_opr_gets_only_the_today_panel(app, make_person):
    make_cast(make_person)
    plant_leave(app, pid(app, "ps2"), TODAY, TODAY, status=RequestStatus.PENDING_PC)
    plant_period(app, TODAY, TODAY + timedelta(days=3), status=ManningStatus.PENDING)
    plant_declaration(app, pid(app, "ps2"), TODAY, TODAY + timedelta(days=2))

    with dashboard_for(app, "opr1") as dash:
        assert dash.my_cos_dates == []
        assert dash.my_cdos_dates == []
        assert dash.my_rejected_leave == [] and dash.my_rejected_travel == []
        assert dash.pc_leave == [] and dash.pc_travel == [] and dash.pc_manning == []
        assert dash.travel_on_manning == set()
        assert dash.oc_leave == []
        assert dash.s3_sent_back == [] and dash.s3_conflicts == [] and dash.s3_unfilled == []
        assert dash.ps_blanks == [] and dash.ps_absent_duty == []
        assert dash.parade_imbalance is None
        assert dash.today.date == TODAY
        assert dash.today.my_next_duty is None


def test_own_cos_and_cdos_rows_land_in_the_two_day_banners(app, make_person):
    make_cast(make_person)
    person_id = pid(app, "opr1")
    plant_assignment(app, person_id, TOMORROW, Duty.COS)
    plant_assignment(app, person_id, TODAY + timedelta(days=2), Duty.COS)
    plant_assignment(app, person_id, TODAY, Duty.CDOS)

    with dashboard_for(app, "opr1") as dash:
        assert dash.my_cos_dates == [TOMORROW]  # day+2 is outside the window
        assert dash.my_cdos_dates == [TODAY]
        assert dash.today.my_next_duty.date == TODAY


def test_today_panel_reports_holders_away_people_and_own_requests(app, make_person):
    make_cast(make_person)
    opr_id, ps_id = pid(app, "opr1"), pid(app, "ps2")
    plant_assignment(app, ps_id, TODAY, Duty.COS)
    plant_assignment(app, opr_id, TODAY, Duty.CDOS)
    plant_status(app, opr_id, TODAY, TODAY)  # MC
    # Same person away twice today: the strip counts PEOPLE, not rows.
    plant_leave(app, opr_id, TODAY, TODAY)
    plant_leave(app, ps_id, TOMORROW, TOMORROW, status=RequestStatus.PENDING_PC)
    plant_leave(app, ps_id, TODAY + timedelta(days=3), TODAY + timedelta(days=3))
    rejected = plant_leave(app, ps_id, TODAY + timedelta(days=4), TODAY + timedelta(days=4),
                           status=RequestStatus.REJECTED_PC)

    with dashboard_for(app, "ps2") as dash:
        assert dash.today.cos.username == "ps2"
        assert dash.today.cdos.username == "opr1"
        assert [row.person_id for row in dash.today.away] == [opr_id]
        assert [r.start_date for r in dash.today.my_pending] == [TOMORROW]
        assert [r.start_date for r in dash.today.my_leave] == [TODAY + timedelta(days=3)]
        # The rejected row is neither pending nor approved, so it stays out of
        # the panel — it surfaces as its own to-do card instead.
        assert all(r.status is not RequestStatus.REJECTED_PC
                   for r in dash.today.my_leave + dash.today.my_pending)
        assert [r.id for r in dash.my_rejected_leave] == [rejected]


def test_regular_never_gets_a_personal_leave_panel(app, make_person):
    make_cast(make_person)
    # An OC is outside the request flow (ARCTIC FOE), so even a planted row —
    # which routing would never create — must not surface as "your leave".
    plant_leave(app, pid(app, "oc"), TODAY, TODAY)
    with dashboard_for(app, "oc") as dash:
        assert dash.today.my_leave == []
        assert dash.today.my_pending == []


def test_requester_gets_their_own_rejected_leave_and_travel(app, make_person):
    make_cast(make_person)
    ps_id = pid(app, "ps2")
    refused = plant_leave(app, ps_id, TOMORROW, TOMORROW, status=RequestStatus.REJECTED_PC,
                          remarks="Det 2 is thin that week", pc_actor="pc1")
    trip = plant_declaration(app, ps_id, TOMORROW, TODAY + timedelta(days=3),
                             status=DeclarationStatus.REJECTED, pc_actor="pc1")

    with dashboard_for(app, "ps2") as dash:
        assert [r.id for r in dash.my_rejected_leave] == [refused]
        assert dash.my_rejected_leave[0].remarks == "Det 2 is thin that week"
        assert [d.id for d in dash.my_rejected_travel] == [trip]
        # A requester is nobody's approver — the queue fields stay empty.
        assert dash.pc_leave == [] and dash.pc_travel == [] and dash.oc_leave == []


def test_regular_never_gets_a_rejected_leave_card(app, make_person):
    make_cast(make_person)
    # The can_request gate again: a regular's off/leave lives in ARCTIC FOE, so
    # a planted rejection — which routing would never create — is not their work.
    plant_leave(app, pid(app, "oc"), TOMORROW, TOMORROW, status=RequestStatus.REJECTED_OC)
    with dashboard_for(app, "oc") as dash:
        assert dash.my_rejected_leave == []


# --- build_dashboard: the approver roles ---------------------------------------

def test_pc_gets_leave_travel_and_manning_queues(app, make_person):
    make_cast(make_person)
    opr_id = pid(app, "opr1")
    mine = plant_leave(app, opr_id, TOMORROW, TOMORROW, status=RequestStatus.PENDING_PC)
    plant_leave(app, opr_id, TODAY + timedelta(days=8), TODAY + timedelta(days=8),
                status=RequestStatus.PENDING_OC)
    travelling = plant_declaration(app, opr_id, TOMORROW, TODAY + timedelta(days=4))
    quiet = plant_declaration(app, pid(app, "ps2"), TODAY + timedelta(days=20),
                              TODAY + timedelta(days=22))
    period_id = plant_period(app, TODAY, TODAY + timedelta(days=6),
                             status=ManningStatus.PENDING, confirmed_by="s3")
    plant_slot(app, period_id, opr_id, ManningSlotType.TU_PLANNER)

    with dashboard_for(app, "pc1") as dash:
        assert [r.id for r in dash.pc_leave] == [mine]
        assert {d.id for d in dash.pc_travel} == {travelling, quiet}
        # opr1 holds a slot in a period overlapping their trip; ps2 holds nothing.
        assert dash.travel_on_manning == {travelling}
        assert [p.id for p in dash.pc_manning] == [period_id]


def test_pc_purges_elapsed_declarations_on_the_way_in(app, make_person):
    make_cast(make_person)
    stale = plant_declaration(app, pid(app, "opr1"), TODAY - timedelta(days=5), YESTERDAY)
    with dashboard_for(app, "pc1"):
        pass
    with app.app_context():
        assert db.session.get(OverseasDeclaration, stale) is None


def test_oc_sees_only_the_final_approval_queue(app, make_person):
    make_cast(make_person)
    opr_id = pid(app, "opr1")
    final = plant_leave(app, opr_id, TOMORROW, TOMORROW, status=RequestStatus.PENDING_OC)
    plant_leave(app, opr_id, TODAY + timedelta(days=2), TODAY + timedelta(days=2),
                status=RequestStatus.PENDING_PC)

    with dashboard_for(app, "oc") as dash:
        assert [r.id for r in dash.oc_leave] == [final]
        assert dash.pc_leave == []  # an OC is not a PC


# --- build_dashboard: the S3's manning checks ----------------------------------

def test_s3_sees_sent_back_periods_with_their_remark(app, make_person):
    make_cast(make_person)
    period_id = plant_period(app, TODAY + timedelta(days=2), TODAY + timedelta(days=5),
                             remarks="TU Comd is on leave", confirmed_by="s3")
    with dashboard_for(app, "s3") as dash:
        assert [p.id for p in dash.s3_sent_back] == [period_id]
        assert dash.s3_sent_back[0].remarks == "TU Comd is on leave"


def test_s3_conflicts_name_the_holder_and_the_reason(app, make_person):
    make_cast(make_person)
    opr_id = pid(app, "opr1")
    period_id = plant_period(app, TODAY, TODAY + timedelta(days=4))
    plant_slot(app, period_id, opr_id, ManningSlotType.TU_COMD)
    plant_slot(app, period_id, pid(app, "ps2"), ManningSlotType.TU_PLANNER)
    plant_leave(app, opr_id, TODAY + timedelta(days=1), TODAY + timedelta(days=2))

    with dashboard_for(app, "s3") as dash:
        assert len(dash.s3_conflicts) == 1
        period, conflicted = dash.s3_conflicts[0]
        assert period.id == period_id
        assert len(conflicted) == 1
        slot, reasons = conflicted[0]
        assert slot.person_id == opr_id
        assert "OFF" in reasons[0]
        # Both HQ slots are filled, so nothing is reported unfilled.
        assert dash.s3_unfilled == []


def test_s3_checks_skip_elapsed_periods(app, make_person):
    make_cast(make_person)
    opr_id = pid(app, "opr1")
    period_id = plant_period(app, TODAY - timedelta(days=6), YESTERDAY)
    plant_slot(app, period_id, opr_id, ManningSlotType.TU_PLANNER)
    plant_leave(app, opr_id, TODAY - timedelta(days=5), TODAY - timedelta(days=4))

    with dashboard_for(app, "s3") as dash:
        assert dash.s3_conflicts == []
        assert dash.s3_unfilled == []


def test_s3_unfilled_reports_the_missing_hq_slot(app, make_person):
    make_cast(make_person)
    period_id = plant_period(app, TODAY + timedelta(days=1), TODAY + timedelta(days=4))
    plant_slot(app, period_id, pid(app, "opr1"), ManningSlotType.TU_PLANNER)

    with dashboard_for(app, "s3") as dash:
        assert len(dash.s3_unfilled) == 1
        period, unfilled = dash.s3_unfilled[0]
        assert period.id == period_id
        assert unfilled == [ManningSlotType.TU_COMD.label]


# --- build_dashboard: the PS's roster gaps -------------------------------------

def current_month_active(app):
    with app.app_context():
        first, last = duty_service.month_bounds(TODAY.strftime("%Y-%m"))
        return duty_service.duty_days(first, last).active


def next_month_active(app):
    year, month = adjacent_ym(TODAY.year, TODAY.month, 1)
    with app.app_context():
        first, last = duty_service.month_bounds(f"{year:04d}-{month:02d}")
        return duty_service.duty_days(first, last).active


def test_ps_blanks_start_at_today_and_ignore_the_past(app, make_person):
    make_cast(make_person)
    active = current_month_active(app)
    with dashboard_for(app, "ps2") as dash:
        expected = {(day, duty) for day in active if day >= TODAY for duty in Duty}
        assert set(dash.ps_blanks) == expected
        assert all(day >= TODAY for day, _duty in dash.ps_blanks)
        # Yesterday's unfilled slot is not work anyone can still do.
        assert not any(day < TODAY for day, _duty in dash.ps_blanks)


def test_ps_blanks_drop_the_days_already_gone(app, make_person, monkeypatch):
    """The `>= today` filter pinned on a fixed mid-month Wednesday: run against
    the real date this assertion goes vacuous whenever no duty day precedes
    today in the current month (the 1st, or a weekend start)."""
    make_cast(make_person)
    frozen = date(2026, 9, 16)
    monkeypatch.setattr("app.services.dashboard_service.today_sgt", lambda: frozen)

    with dashboard_for(app, "ps2") as dash:
        assert (frozen, Duty.COS) in dash.ps_blanks
        assert (date(2026, 9, 15), Duty.COS) not in dash.ps_blanks
        assert (date(2026, 9, 15), Duty.CDOS) not in dash.ps_blanks


def test_ungenerated_next_month_is_silent_until_one_row_exists(app, make_person):
    make_cast(make_person)
    active = next_month_active(app)
    with dashboard_for(app, "ps2") as dash:
        assert not any(day in active for day, _duty in dash.ps_blanks)

    # One row means planning started, so the month's remaining gaps are work.
    plant_assignment(app, pid(app, "opr1"), active[0], Duty.COS)
    with dashboard_for(app, "ps2") as dash:
        assert (active[1], Duty.COS) in dash.ps_blanks
        assert (active[0], Duty.CDOS) in dash.ps_blanks
        assert (active[0], Duty.COS) not in dash.ps_blanks  # that one is filled


def test_ps_absent_duty_flags_a_holder_away_on_their_own_duty_date(app, make_person):
    make_cast(make_person)
    opr_id = pid(app, "opr1")
    flagged = plant_assignment(app, opr_id, TODAY, Duty.COS)
    plant_leave(app, opr_id, TODAY, TODAY)
    past = plant_assignment(app, opr_id, YESTERDAY, Duty.CDOS)
    plant_leave(app, opr_id, YESTERDAY, YESTERDAY)

    with dashboard_for(app, "ps2") as dash:
        assert [row.id for row in dash.ps_absent_duty] == [flagged]
        assert past not in [row.id for row in dash.ps_absent_duty]


# --- Task B: the page itself ("/") ---------------------------------------------
# Same planting helpers as above, driven through HTTP: these pin what the
# dashboard TEMPLATE puts on the screen for a role, not what the service returns.


def test_pc_page_names_the_requester_and_flags_a_travelling_slot_holder(app, client, make_person):
    make_cast(make_person)
    opr_id = pid(app, "opr1")
    plant_leave(app, opr_id, TOMORROW, TOMORROW, status=RequestStatus.PENDING_PC)
    plant_declaration(app, opr_id, TOMORROW, TODAY + timedelta(days=4))
    period_id = plant_period(app, TODAY, TODAY + timedelta(days=6),
                             status=ManningStatus.PENDING, confirmed_by="s3")
    plant_slot(app, period_id, opr_id, ManningSlotType.TU_PLANNER)

    login(client, "pc1")
    body = client.get("/").data
    # Card headings, not bare labels: base.html renders the SAME strings (with
    # the same counts) in the PC's nav, so an unscoped match proves nothing.
    assert b"<h2>OFF/OIL/Leave approvals (1)</h2>" in body
    assert b"Ang Cheng Ze" in body
    assert b"<h2>Travel approvals (1)</h2>" in body
    assert b"On TU manning" in body
    assert b"<h2>Manning approvals (1)</h2>" in body
    # The manning card's own row — the nav link carries no dates.
    period_row = (f"TU manning &mdash; {TODAY.strftime('%d %b')} &ndash; "
                  f"{(TODAY + timedelta(days=6)).strftime('%d %b %Y')}")
    assert period_row.encode() in body


def test_requester_page_carries_both_rejections_and_is_not_all_clear(app, client, make_person):
    make_cast(make_person)
    opr_id = pid(app, "opr1")
    refused = plant_leave(app, opr_id, TOMORROW, TOMORROW, status=RequestStatus.REJECTED_PC,
                          remarks="Det 2 is thin that week", pc_actor="pc1")
    plant_declaration(app, opr_id, TOMORROW, TODAY + timedelta(days=3),
                      status=DeclarationStatus.REJECTED, destination="Bangkok",
                      pc_actor="pc1")

    login(client, "opr1")
    body = client.get("/").data
    assert b"<h2>OFF/OIL/Leave rejected (1)</h2>" in body
    assert f'href="/leave/{refused}"'.encode() in body
    assert b"Det 2 is thin that week" in body
    assert b"rejected by LTA Quek Jing Yu" in body
    # Which step refused it is the whole point of the badge.
    assert b"Rejected (PC)" in body
    assert b"<h2>Travel rejected (1)</h2>" in body
    assert b"Bangkok" in body
    assert b'href="/overseas/mine"' in body
    # An Opr with nothing else open is the all-clear case (see the test below),
    # so this pins that both cards are counted in has_todo.
    assert b"Nothing needs your action." not in body


def test_opr_page_shows_no_approval_cards(app, client, make_person):
    make_cast(make_person)
    opr_id = pid(app, "opr1")
    plant_leave(app, pid(app, "ps2"), TOMORROW, TOMORROW, status=RequestStatus.PENDING_PC)
    plant_declaration(app, opr_id, TOMORROW, TODAY + timedelta(days=4))
    period_id = plant_period(app, TODAY, TODAY + timedelta(days=6),
                             status=ManningStatus.PENDING, confirmed_by="s3")
    plant_slot(app, period_id, opr_id, ManningSlotType.TU_PLANNER)

    login(client, "opr1")
    body = client.get("/").data
    assert b"OFF/OIL/Leave approvals" not in body
    assert b"Travel approvals" not in body
    assert b"On TU manning" not in body
    assert b"Manning approvals" not in body


def test_s3_page_carries_the_send_back_remark_the_conflicts_and_the_gaps(app, client,
                                                                        make_person):
    make_cast(make_person)
    plant_period(app, TODAY + timedelta(days=2), TODAY + timedelta(days=5),
                 remarks="TU Comd is on leave", confirmed_by="s3")
    # A second period with one conflicted holder and one unfilled HQ slot: the
    # three S3 cards are separate template branches, so each needs a render.
    opr_id = pid(app, "opr1")
    period_id = plant_period(app, TODAY, TODAY + timedelta(days=4))
    plant_slot(app, period_id, opr_id, ManningSlotType.TU_COMD)
    plant_leave(app, opr_id, TODAY + timedelta(days=1), TODAY + timedelta(days=2))

    login(client, "s3")
    body = client.get("/").data
    assert b"Manning sent back (1)" in body
    assert b"TU Comd is on leave" in body
    assert b"TU manning conflicts" in body
    assert b"Ang Cheng Ze" in body
    assert b"Unfilled TU slots" in body
    assert ManningSlotType.TU_PLANNER.label.encode() in body


def test_blank_duty_days_within_a_day_are_marked_as_affecting_the_ro(app, client, make_person,
                                                                    monkeypatch):
    """Pinned to a fixed mid-week Wednesday: against the real date the badge
    count depends on where in the week the suite happens to run."""
    make_cast(make_person)
    frozen = date(2026, 9, 16)
    monkeypatch.setattr("app.services.dashboard_service.today_sgt", lambda: frozen)

    login(client, "ps2")
    body = client.get("/").data
    assert b"Duty days without a holder" in body
    # Wed 16th and Thu 17th, both duties each — the 18th onwards is planning.
    assert body.count(b"affects the RO") == 4


def test_nav_links_the_month_view_and_home_never_renders_the_grid(app, client, make_person):
    make_cast(make_person)
    login(client, "opr1")
    body = client.get("/").data
    assert b'href="/calendar/month"' in body
    assert b"month-grid" not in body
    # ...and the grid is still there, one click away.
    assert b"month-grid" in client.get("/calendar/month").data


def test_all_clear_card_renders_when_nothing_is_open(app, client, make_person):
    make_cast(make_person)
    login(client, "opr1")
    body = client.get("/").data
    assert b"Nothing needs your action." in body
    # The Today panel is not a to-do, so it renders regardless.
    assert b"<h2>Today</h2>" in body


def test_today_panel_lists_the_away_and_the_viewers_own_pending_request(app, client, make_person):
    make_cast(make_person)
    ps_id = pid(app, "ps2")
    plant_status(app, pid(app, "opr1"), TODAY, TODAY)  # MC
    plant_leave(app, ps_id, TOMORROW, TOMORROW, status=RequestStatus.PENDING_PC)
    # The viewer's own duty rows: the two banners above the cards.
    plant_assignment(app, ps_id, TODAY, Duty.COS)
    plant_assignment(app, ps_id, TOMORROW, Duty.CDOS)

    login(client, "ps2")
    body = client.get("/").data
    assert b"key the parade" in body
    assert b"compile the RO" in body
    assert b"Away today (1)" in body
    # The whole rendered line: a bare "MC" matches the nav's "Declare MC".
    assert b"CPL Ang Cheng Ze &mdash; MC" in body
    assert b"Pending PC" in body
    # The panel's next-duty line, not the banner above it — the banner reads
    # "You are COS on ...", so only the wrapped <p> isolates the panel.
    assert f"<p>COS on {TODAY.strftime('%a %d %b')}</p>".encode() in body


def test_spread_violations_never_reach_the_page(app, client, make_person):
    """Deliberately omitted (dashboard_service._month_todos): a max−min gap over
    a 21-day month is the normal state of a small pool, so the line would fire
    constantly and teach the reader to ignore the card."""
    make_cast(make_person)
    opr_id = pid(app, "opr1")
    active = current_month_active(app)
    for day in active[:4]:
        plant_assignment(app, opr_id, day, Duty.COS)

    login(client, "ps2")
    body = client.get("/").data.lower()
    assert b"spread" not in body
