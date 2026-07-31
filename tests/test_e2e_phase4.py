"""P4.10 — the Phase 4 end-to-end walk, via the test client only.

One PS runs a real month: generate over a forced blank -> manual assign over a
warning, confirmed on the page that names it -> a requester's leave over a
live duty is endorsed and approved (the OC saw the duty panel; nothing was
blocked, nothing reassigned, the roster flags it) -> cos_of_day resolves the
holder -> and blocking a day takes the duty, and its keying rights, away with
it.
"""
from datetime import timedelta

from app.domain.dates import iter_days, today_sgt
from app.domain.types import (
    Appointment, BalanceKind, DayPart, Duty, LeaveType, LedgerSource,
    Rank, RequestStatus, Service,
)
from app.extensions import db
from app.models import DutyAssignment, LeaveRequest, Person
from app.services import duty_service, ledger_service
from tests.conftest import login


def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def _switch(client, username):
    # /login short-circuits for an authenticated session — log out first.
    client.post("/logout")
    login(client, username)


def _keying_status(client):
    # A routed probe of the COS's parade-keying rights: the empty "Not joining
    # FP" bulk remove on today's morning page (302 when granted, removing
    # nothing; 403 when refused). The MC page (self-service) and the override
    # routes (open to every logged-in user, 2026-07-31) are no longer gated, so
    # neither can serve as the probe.
    return client.post("/parade/morning/fp/remove").status_code


def test_phase4_end_to_end(app, client, make_person):
    # --- 1. Seed: PS (CDOS pool of one, stay-out NSF), OC, PC, two-man COS pool
    make_person(username="ps_boss", rank=Rank.TWO_SG, appointment=Appointment.PS,
                platoon=2, stay_out=True, display_name="Benny Foo")
    make_person(username="oc_boss", rank=Rank.CPT, appointment=Appointment.OC,
                service=Service.REGULAR, platoon=None, display_name="Marcus Leong")
    make_person(username="pc1", rank=Rank.LTA, appointment=Appointment.PC,
                service=Service.REGULAR, platoon=1, display_name="Shawn Koh")
    make_person(username="opr_a", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD,
                platoon=1, display_name="Adam Tan")
    make_person(username="opr_b", rank=Rank.CPL, appointment=Appointment.OPR,
                platoon=1, display_name="Bryan Lim")

    today = today_sgt()
    month = today.strftime("%Y-%m")
    first, last = duty_service.month_bounds(month)

    # Every COS candidate is on APPROVED leave on blank_day BEFORE generating:
    # the generator must leave that slot empty (decision d — never rule-broken).
    with app.app_context():
        # The forced hole has to be a day the roster actually plans: weekends
        # and holidays are not slots at all since 2026-07-27.
        blank_day = next(
            d for d in duty_service.duty_days(first, last).active
            if d >= first + timedelta(days=2)
        )
        for username in ("opr_a", "opr_b"):
            person_id = db.session.query(Person.id).filter_by(username=username).scalar()
            db.session.add(
                LeaveRequest(
                    person_id=person_id, type=LeaveType.OFF, start_date=blank_day,
                    end_date=blank_day, day_part=DayPart.FULL,
                    status=RequestStatus.APPROVED,
                )
            )
        db.session.commit()

    # --- 2./3. PS generates: pools panel, live rows, the blank flagged -------
    login(client, "ps_boss")
    resp = client.post("/duty/roster/generate", data={"month": month},
                       follow_redirects=True)
    html = resp.get_data(as_text=True)
    # CDO/S pool = the PS + the PC (an LTA PC satisfies rank>=2SG + PC).
    assert "COS pool (2)" in html and "CDO/S pool (2)" in html
    assert "Roster generated." in html
    assert "blank" in html  # the forced hole is flagged, not silently filled

    # --- 4. Manual assign: the warning is answered ON the page ---------------
    assign_data = {
        "month": month, "date": blank_day.isoformat(), "duty": Duty.COS.value,
        "person_id": str(_pid(app, "opr_a")),
    }
    resp = client.post("/duty/roster/assign", data=assign_data)
    html = resp.get_data(as_text=True)
    assert "covering absence" in html                      # the reason, named...
    assert "Confirm and assign" in html                    # ...then the choice
    resp = client.post("/duty/roster/assign", data={**assign_data, "confirm": "1"},
                       follow_redirects=True)
    assert "Assigned." in resp.get_data(as_text=True)     # ...assign on confirm
    with app.app_context():
        row = (
            db.session.query(DutyAssignment)
            .filter_by(date=blank_day, duty=Duty.COS)
            .one()
        )
        assert row.person_id == _pid(app, "opr_a")
        assert row.is_manual is True  # regeneration must not undo the PS

    # --- 5. Leave over a live duty: endorsed, panel seen, approved, warned ---
    with app.app_context():
        opr_a_id = _pid(app, "opr_a")
        clash_row = next(
            r for r in db.session.query(DutyAssignment)
            .filter_by(duty=Duty.COS, person_id=opr_a_id)
            .order_by(DutyAssignment.date)
            if r.date != blank_day
        )
        clash_day, clash_id = clash_row.date, clash_row.id
        ledger_service.post_entry(
            person_id=opr_a_id, kind=BalanceKind.OFF, delta_half_days=4,
            reason="opening balance", source=LedgerSource.MANUAL,
            created_by_id=_pid(app, "oc_boss"),
        )
        db.session.commit()

    _switch(client, "opr_a")
    resp = client.post("/leave/new", data={
        "type": "OFF", "start_date": clash_day.isoformat(),
        "end_date": clash_day.isoformat(), "day_part": "FULL", "reason": "",
    }, follow_redirects=True)
    assert b"Request submitted." in resp.data
    with app.app_context():
        req_id = (
            db.session.query(LeaveRequest.id)
            .filter_by(person_id=_pid(app, "opr_a"), status=RequestStatus.PENDING_PC)
            .scalar()
        )

    _switch(client, "pc1")
    assert client.post(f"/leave/{req_id}/pc-approve", follow_redirects=True).status_code == 200

    _switch(client, "oc_boss")
    html = client.get(f"/leave/{req_id}").get_data(as_text=True)
    assert "Confirmed duties on these dates" in html  # the OC saw the clash...
    assert "COS — confirmed" in html
    client.post(f"/leave/{req_id}/oc-approve", follow_redirects=True)
    with app.app_context():
        assert db.session.get(LeaveRequest, req_id).status is RequestStatus.APPROVED
        row = db.session.get(DutyAssignment, clash_id)
        # ...and approving blocked nothing and reassigned nobody (warn-only).
        assert row.person_id == _pid(app, "opr_a")
        assert clash_id in duty_service.month_view(month).absent_flags

    # --- 6. cos_of_day resolves the COS of any date --------------------------
    _switch(client, "ps_boss")
    with app.app_context():
        # An arbitrary live duty date: one the PS holds CDO/S on, skipping the
        # blocked and clash days this walk already disturbed.
        excluded = {blank_day, clash_day}
        ps_nights = {
            r.date for r in db.session.query(DutyAssignment).filter_by(
                duty=Duty.CDOS, person_id=_pid(app, "ps_boss"),
            )
        }
        pd = next(
            d for d in iter_days(first, last - timedelta(days=1))
            if d in ps_nights and d not in excluded
        )
        cos_holder_id = (
            db.session.query(DutyAssignment.person_id)
            .filter_by(date=pd, duty=Duty.COS)
            .scalar()
        )
        # The COS page no longer autofills from the roster (P10.1: free text,
        # defaulting to the logged-in user), but cos_of_day itself still feeds
        # the RO's COS line — pinned here for an arbitrary phase date.
        assert duty_service.cos_of_day(pd).id == cos_holder_id

    # --- 7. Blocking a day removes its duty, and the keying rights with it ---
    # The rights window is today/tomorrow, and only a duty day inside THIS
    # month can carry a COS at all now that rosters are weekday-only — a
    # Saturday window has none, which is the same rule seen from the other side.
    tomorrow = today + timedelta(days=1)
    with app.app_context():
        active = set(duty_service.duty_days(first, last).active)
        window = [d for d in (today, tomorrow) if d in active]
        holders = {
            row.date: row.person.username
            for row in db.session.query(DutyAssignment).filter(
                DutyAssignment.date.in_((today, tomorrow)),
                DutyAssignment.duty == Duty.COS,
            )
        }
    assert set(holders) == set(window)

    if window:
        holder_username = holders[window[0]]
        _switch(client, holder_username)
        assert _keying_status(client) == 302

        _switch(client, "ps_boss")
        for day in window:  # the whole two-day window
            resp = client.post("/duty/roster/block", data={
                "month": month, "date": day.isoformat(),
            }, follow_redirects=True)
            assert "Blocked" in resp.get_data(as_text=True)
        _switch(client, holder_username)
        assert _keying_status(client) == 403

        # Unblocking gives the day back as an EMPTY slot — the removed holder
        # is gone for good, so the rights stay gone until someone is assigned.
        _switch(client, "ps_boss")
        html = client.post("/duty/roster/unblock", data={
            "month": month, "date": window[0].isoformat(),
        }, follow_redirects=True).get_data(as_text=True)
        assert "Unblocked" in html and "blank" in html
        _switch(client, holder_username)
        assert _keying_status(client) == 403
    else:
        # A weekend window: nobody holds a COS, so no NSF can key.
        _switch(client, "opr_a")
        assert _keying_status(client) == 403
