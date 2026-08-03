"""The Home to-do dashboard: everything the signed-in person still has to do,
assembled once per request.

Derived-only, like every other surface in this app: nothing here is stored — no
conflict table, no "seen"/dismissed flag, no snapshot — so an item leaves the
dashboard only when the underlying data is fixed. There is deliberately nothing
to acknowledge.

This module is fetch/assemble GLUE. Every rule it shows already has an owning
function (leave_service, overseas_service, manning_service, duty_service,
parade_service) and is reused verbatim; no rule is re-derived here. The only
new logic is `>= today` filtering over structures those owners already built,
which is why this is a service and not a domain module — there is no pure rule
to test in isolation.

Heavy branches are role-gated: an Opr's render is the two cheap "today" queries
and their own duty rows, while the per-period manning sweep and the month-view
pass only run for the S3 and the PS who actually see those cards.
"""
from collections import namedtuple
from datetime import timedelta

from app.domain import policy, routing
from app.domain.dates import adjacent_ym, today_sgt
from app.domain.manning import ManningConflict
from app.domain.types import Duty, PENDING_STATUSES, ParadeVariant, RequestStatus
from app.services import (
    duty_service,
    leave_service,
    manning_service,
    overseas_service,
    parade_service,
    presence_service,
)

# Empty collections, never None, for the cards a viewer's roles don't unlock —
# the template iterates unconditionally and shows a card only when it has rows.
Dashboard = namedtuple(
    "Dashboard",
    "my_cos_dates my_cdos_dates my_rejected_leave my_rejected_travel "
    "pc_leave pc_travel travel_on_manning pc_manning "
    "oc_leave "
    "s3_sent_back s3_conflicts s3_unfilled "
    "ps_blanks ps_absent_duty "
    "parade_imbalance "
    "today",
)

# The state-of-the-company strip everyone gets. `away` rows are
# presence_service.AbsenceRow objects (person, label, source, day_part);
# `my_next_duty` is a DutyAssignment or None.
Today = namedtuple("Today", "date cos cdos away my_leave my_pending my_next_duty")


def _my_requests(user):
    """(approved, pending) of this person's live requests from ONE fetch.

    Empty for regulars: their off/leave lives in the external ARCTIC FOE system
    (owner directive 2026-07-26), so `routing.can_request` is the same gate the
    leave pages use rather than a second rule.
    """
    if not routing.can_request(user):
        return [], []
    rows = leave_service.live_requests(user.id)
    approved = [r for r in rows if r.status is RequestStatus.APPROVED]
    pending = [r for r in rows if r.status in PENDING_STATUSES]
    return approved, pending


def _month_todos(month, today, *, require_rows):
    """(blanks, absent_rows) for one month's roster, from `today` onwards.

    `require_rows` is how an ungenerated month stays silent: every duty day of
    it is a blank, so a month nobody has touched would bury the real work under
    ~42 noise lines. One assignment row means planning has started.

    Spread violations are never included — they are computed but deliberately
    not displayed (the reason is written at duty/roster.html:128-131: a max−min
    gap over a 21-day month is the normal state of a small pool, so the line
    fired constantly and taught the reader to ignore the card).
    """
    view = duty_service.month_view(month)
    if require_rows and not view.rows:
        return [], []
    # Blanks stay the owner's raw (day, duty) tuples: the template compares day
    # against `dash.today.date` for the "affects the RO" emphasis, which is one
    # comparison in one place instead of a precomputed flag on every row.
    blanks = [(day, duty) for day, duty in view.violations.blanks if day >= today]
    absent = [
        row for row in view.rows if row.id in view.absent_flags and row.date >= today
    ]
    return blanks, absent


def build_dashboard(user) -> Dashboard:
    """Every open item for `user`, re-derived now. Role-gated section by section."""
    today = today_sgt()
    rows = duty_service.assignments_for_person(user.id, start=today)
    # Two-day window, mirroring duty_service.can_key_parade_today and
    # ro_service.can_edit_ro_for: these banners announce the viewer's OWN rows
    # (and so the keying they imply), they do not re-derive the rights.
    window = (today, today + timedelta(days=1))
    my_cos_dates = [r.date for r in rows if r.duty is Duty.COS and r.date in window]
    my_cdos_dates = [r.date for r in rows if r.duty is Duty.CDOS and r.date in window]

    my_leave, my_pending = _my_requests(user)
    # Same gate as _my_requests, for the same reason: a regular is outside the
    # request flow, so a planted row of theirs is not "your request was refused".
    my_rejected_leave = (
        leave_service.rejected_live_requests(user.id) if routing.can_request(user) else []
    )
    # Deliberately ungated: only a PS/Det Comd/Opr declaration is ever PENDING
    # long enough to be rejected (routing.overseas_initial_status auto-approves
    # everyone else's), so the query is naturally empty for the rest — a gate
    # here would re-derive routing inside glue.
    my_rejected_travel = overseas_service.rejected_declarations_for(user.id)

    today_panel = Today(
        date=today,
        cos=duty_service.cos_of_day(today),
        cdos=duty_service.cdos_of_day(today),
        away=presence_service.dedupe_by_person(presence_service.absences_on(today)),
        my_leave=my_leave,
        my_pending=my_pending,
        my_next_duty=rows[0] if rows else None,
    )

    pc_leave, pc_travel, pc_manning = [], [], []
    travel_on_manning = set()
    if policy.is_pc(user):
        # Home now reads overseas declarations, so it purges elapsed ones like
        # every other overseas page: there are no background workers here
        # (CLAUDE.md), so the GET is what enforces "the trip is over, it's gone".
        overseas_service.purge_expired()
        pc_leave = leave_service.pending_requests(RequestStatus.PENDING_PC)
        pc_travel = overseas_service.pending_declarations()
        travel_on_manning = overseas_service.on_manning_ids(pc_travel)
        pc_manning = manning_service.pending_periods()

    oc_leave = []
    if policy.can_final_approve(user):
        oc_leave = leave_service.pending_requests(RequestStatus.PENDING_OC)

    s3_sent_back, s3_conflicts, s3_unfilled = [], [], []
    if policy.can_manage_manning(user):
        s3_sent_back = manning_service.sent_back_periods()
        for period in manning_service.periods_from(today):
            checks = manning_service.conflict_map(period)
            conflicted = [
                (slot, checks[slot.person_id][1])
                for slot in period.slots
                if checks[slot.person_id][0] is ManningConflict.CONFLICT
            ]
            if conflicted:
                s3_conflicts.append((period, conflicted))
            unfilled = manning_service.build_document(period).unfilled
            if unfilled:
                s3_unfilled.append((period, unfilled))

    ps_blanks, ps_absent_duty = [], []
    if policy.can_manage_roster(user):
        ps_blanks, ps_absent_duty = _month_todos(
            today.strftime("%Y-%m"), today, require_rows=False
        )
        year, month = adjacent_ym(today.year, today.month, 1)
        next_blanks, next_absent = _month_todos(
            f"{year:04d}-{month:02d}", today, require_rows=True
        )
        ps_blanks += next_blanks
        ps_absent_duty += next_absent

    parade_imbalance = None
    if duty_service.can_key_parade_today(user):
        # One variant only: build_doc is by far the heaviest call on this page,
        # and an imbalance is an engine-level refusal (the categorized totals do
        # not add up), so any variant senses the same fault. MORNING is the one
        # that needs no cos_display.
        parade_imbalance = parade_service.build_doc(today, ParadeVariant.MORNING).imbalance

    return Dashboard(
        my_cos_dates=my_cos_dates,
        my_cdos_dates=my_cdos_dates,
        my_rejected_leave=my_rejected_leave,
        my_rejected_travel=my_rejected_travel,
        pc_leave=pc_leave,
        pc_travel=pc_travel,
        travel_on_manning=travel_on_manning,
        pc_manning=pc_manning,
        oc_leave=oc_leave,
        s3_sent_back=s3_sent_back,
        s3_conflicts=s3_conflicts,
        s3_unfilled=s3_unfilled,
        ps_blanks=ps_blanks,
        ps_absent_duty=ps_absent_duty,
        parade_imbalance=parade_imbalance,
        today=today_panel,
    )
