"""P4.10 — the Phase 4 end-to-end walk, via the test client only.

One PS runs a real month: generate over a forced blank -> manual assign over a
warning -> confirm behind the scraped fingerprint -> a requester's leave over
a confirmed duty is endorsed and approved (the OC saw the duty panel; nothing
was blocked, nothing reassigned, the roster flags it) -> the stay-out duty
holder lands in the night's CURRENT STRENGTH and the meal counter counts him
-> the COS selector pre-fills the confirmed COS -> and a deposed COS loses
keying rights with the assignment.
"""
import re
from datetime import timedelta

from app.domain.dates import iter_days, today_sgt
from app.domain.types import (
    Appointment, BalanceKind, DayPart, Duty, DutyState, LeaveType, LedgerSource,
    Rank, RequestStatus, Service,
)
from app.extensions import db
from app.models import DutyAssignment, LeaveRequest, Person
from app.services import duty_service, ledger_service, meal_service
from tests.conftest import login


def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def _fingerprint(html):
    match = re.search(r'name="fingerprint" value="([0-9a-f]{64})"', html)
    assert match, "the confirm form must carry the fingerprint (A4's mechanism)"
    return match.group(1)


def _switch(client, username):
    # /login short-circuits for an authenticated session — log out first.
    client.post("/logout")
    login(client, username)


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
    blank_day = first + timedelta(days=2)

    # Every COS candidate is on APPROVED leave on blank_day BEFORE generating:
    # the generator must leave that slot empty (decision d — never rule-broken).
    with app.app_context():
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

    # --- 2./3. PS generates: pools panel, PROPOSED badges, the blank flagged --
    login(client, "ps_boss")
    resp = client.post("/duty/roster/generate", data={"month": month},
                       follow_redirects=True)
    html = resp.get_data(as_text=True)
    # CDO/S pool = the PS + the PC (an LTA PC satisfies rank>=2SG + PC).
    assert "COS pool (2)" in html and "CDO/S pool (2)" in html
    assert '<span class="badge pending">PROPOSED</span>' in html
    assert "blank" in html  # the forced hole is flagged, not silently filled

    # --- 4. Manual assign over the availability warning ----------------------
    assign_data = {
        "month": month, "date": blank_day.isoformat(), "duty": Duty.COS.value,
        "person_id": str(_pid(app, "opr_a")),
    }
    resp = client.post("/duty/roster/assign", data=assign_data, follow_redirects=True)
    assert "Not assigned" in resp.get_data(as_text=True)  # warn first...
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

    # --- 5. Confirm with the fingerprint scraped from the rendered page ------
    html = client.get(f"/duty/roster?month={month}").get_data(as_text=True)
    resp = client.post(
        "/duty/roster/confirm",
        data={"month": month, "fingerprint": _fingerprint(html)},
        follow_redirects=True,
    )
    html = resp.get_data(as_text=True)
    assert '<span class="badge approved">CONFIRMED</span>' in html
    assert '<span class="badge pending">PROPOSED</span>' not in html

    # --- 6. Leave over a confirmed duty: endorsed, panel seen, approved, warned
    with app.app_context():
        opr_a_id = _pid(app, "opr_a")
        clash_row = next(
            r for r in db.session.query(DutyAssignment)
            .filter_by(duty=Duty.COS, state=DutyState.CONFIRMED, person_id=opr_a_id)
            .order_by(DutyAssignment.date)
            if r.date.weekday() < 5 and r.date != blank_day
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
        assert row.state is DutyState.CONFIRMED
        assert clash_id in duty_service.month_view(month).absent_flags

    # --- 7. The stay-out CDO/S holder is counted present for his night -------
    with app.app_context():
        excluded = {blank_day, clash_day}
        ps_nights = {
            r.date for r in db.session.query(DutyAssignment).filter_by(
                duty=Duty.CDOS, state=DutyState.CONFIRMED,
                person_id=_pid(app, "ps_boss"),
            )
        }
        pd = next(
            d for d in iter_days(first, last - timedelta(days=1))
            if d in ps_nights and d not in excluded
            and (d + timedelta(days=1)) not in excluded
        )
        counts, imbalance = meal_service.compute_for(pd)
        assert imbalance is None
        # NSFs that night: the two stay-in oprs + the stay-out PS on CDO/S duty
        # (DUTY overrides stay-out) — without the duty pipe this would be 2.
        assert counts.overnight == 3

    # --- 8. The COS selector pre-fills the confirmed COS of the page date ----
    _switch(client, "ps_boss")
    with app.app_context():
        cos_holder_id = (
            db.session.query(DutyAssignment.person_id)
            .filter_by(date=pd, duty=Duty.COS, state=DutyState.CONFIRMED)
            .scalar()
        )
    html = client.get(f"/parade/cos-message?date={pd.isoformat()}").get_data(as_text=True)
    assert f'value="{cos_holder_id}" selected' in html

    # --- 9. Deposed COS: the rights disappear with the assignment ------------
    with app.app_context():
        holder_today = (
            db.session.query(Person)
            .join(DutyAssignment, DutyAssignment.person_id == Person.id)
            .filter(
                DutyAssignment.date == today,
                DutyAssignment.duty == Duty.COS,
                DutyAssignment.state == DutyState.CONFIRMED,
            )
            .one()
        )
        holder_username = holder_today.username
    _switch(client, holder_username)
    assert client.get("/parade/statuses").status_code == 200

    _switch(client, "ps_boss")
    for day in (today, today + timedelta(days=1)):  # the whole two-day window
        client.post("/duty/roster/clear", data={
            "month": month, "date": day.isoformat(), "duty": Duty.COS.value,
        }, follow_redirects=True)
    _switch(client, holder_username)
    assert client.get("/parade/statuses").status_code == 403
