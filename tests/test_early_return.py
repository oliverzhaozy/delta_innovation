"""P2.10 early return: S3/OC shorten an APPROVED full-day multi-day request and
credit the balance for the working days no longer taken — one transaction, one
compensating REVERSAL row, ledger never edited.

The credit is net-from-ledger (mirrors P2.9 cancel): outstanding still deducted
minus the recomputed cost of the shortened range, clamped at zero. So it composes
with a later amendment and a later cancel without ever drifting the balance.
"""
from datetime import date

import pytest
from sqlalchemy import update

from app.domain.types import (
    Appointment,
    BalanceKind,
    DayPart,
    LeaveType,
    LedgerSource,
    Rank,
    RequestStatus,
)
from app.extensions import db
from app.models import LeaveRequest, LedgerEntry, Person
from app.services import ledger_service
from app.services.approval_service import TransitionError, cancel_approved, early_return
from tests.conftest import login

# Thu 13 – Mon 17 Aug 2026: 3 working days (Thu, Fri, Mon) = 6 half-days.
THU = date(2026, 8, 13)
FRI = date(2026, 8, 14)
SUN = date(2026, 8, 16)  # non-working; Sat 15 + Sun 16 both fall inside Thu–Sun
MON = date(2026, 8, 17)
WED = date(2026, 8, 12)  # before start
TUE_NEXT = date(2026, 8, 18)  # after end


def _pid(username):
    return db.session.query(Person.id).filter_by(username=username).scalar()


def _approved(person_id, type=LeaveType.OFF, start=THU, end=MON, day_part=DayPart.FULL):
    req = LeaveRequest(
        person_id=person_id,
        type=type,
        start_date=start,
        end_date=end,
        day_part=day_part,
        status=RequestStatus.APPROVED,
    )
    db.session.add(req)
    db.session.flush()
    return req


def _debit(person_id, req_id, actor_id, delta, kind=BalanceKind.OFF):
    ledger_service.post_entry(
        person_id=person_id,
        kind=kind,
        delta_half_days=delta,
        reason="OFF 13 Aug – 17 Aug",
        source=LedgerSource.LEAVE_APPROVAL,
        created_by_id=actor_id,
        leave_request_id=req_id,
    )


def _reversals(req_id):
    return (
        db.session.query(LedgerEntry)
        .filter_by(leave_request_id=req_id, source=LedgerSource.REVERSAL)
        .all()
    )


# --- Criterion 1: Thu–Mon returned after Thu credits exactly 2 days -----------

def test_returned_after_thu_credits_two_days(app, make_person):
    make_person(username="er_p1")
    make_person(username="er_s3_1", company_role="S3")
    with app.app_context():
        pid, actor_id = _pid("er_p1"), _pid("er_s3_1")
        req = _approved(pid)
        _debit(pid, req.id, actor_id, -6)
        db.session.commit()
        assert ledger_service.balance(pid, BalanceKind.OFF) == -6

        early_return(req, db.session.get(Person, actor_id), THU)

        # end_date amended; only Thu (1 working day = 2 half-days) still deducted.
        assert db.session.get(LeaveRequest, req.id).end_date == THU
        assert ledger_service.balance(pid, BalanceKind.OFF) == -2
        rows = db.session.query(LedgerEntry).filter_by(leave_request_id=req.id).all()
        assert len(rows) == 2  # append-only: original debit + one reversal
        rev = _reversals(req.id)
        assert len(rev) == 1 and rev[0].delta_half_days == 4  # 2 days credited
        assert "OFF" in rev[0].reason  # reason records the amendment
        # Fix 1: the amendment ALSO leaves an audit trace on the request row.
        req_after = db.session.get(LeaveRequest, req.id)
        assert "Early return by" in req_after.remarks
        assert "end 17 Aug -> 13 Aug" in req_after.remarks


# --- Criterion 2: composability — amend, amend, cancel; balance stays whole ---

def test_two_amendments_then_cancel_leave_balance_whole(app, make_person):
    make_person(username="er_comp")
    make_person(username="er_comp_s3", company_role="S3")
    with app.app_context():
        pid, actor_id = _pid("er_comp"), _pid("er_comp_s3")
        actor = db.session.get(Person, actor_id)
        req = _approved(pid)
        _debit(pid, req.id, actor_id, -6)
        db.session.commit()

        early_return(req, actor, FRI)  # Thu–Fri costs 4; credit max(0, 6-4) = 2
        assert ledger_service.balance(pid, BalanceKind.OFF) == -4

        early_return(req, actor, THU)  # Thu costs 2; credit off NET: max(0, 4-2) = 2
        assert ledger_service.balance(pid, BalanceKind.OFF) == -2

        cancel_approved(req, actor)  # net -2 remaining -> credit +2
        assert ledger_service.balance(pid, BalanceKind.OFF) == 0
        assert db.session.get(LeaveRequest, req.id).status is RequestStatus.CANCELLED

        rows = (
            db.session.query(LedgerEntry)
            .filter_by(leave_request_id=req.id)
            .order_by(LedgerEntry.id)
            .all()
        )
        assert len(rows) == 4  # debit, +2, +2, +2 — every step a NEW row
        assert rows[0].source is LedgerSource.LEAVE_APPROVAL and rows[0].delta_half_days == -6
        assert [r.delta_half_days for r in rows[1:]] == [2, 2, 2]
        assert all(r.source is LedgerSource.REVERSAL for r in rows[1:])


# --- Criterion 3: max(0, .) — already fully reversed posts nothing ------------

def test_no_credit_when_outstanding_already_zero(app, make_person):
    make_person(username="er_zero")
    make_person(username="er_zero_s3", company_role="S3")
    with app.app_context():
        pid, actor_id = _pid("er_zero"), _pid("er_zero_s3")
        actor = db.session.get(Person, actor_id)
        req = _approved(pid)
        _debit(pid, req.id, actor_id, -6)
        # A prior full reversal already zeroed the outstanding debit.
        ledger_service.post_entry(
            person_id=pid, kind=BalanceKind.OFF, delta_half_days=6,
            reason="prior full reversal", source=LedgerSource.REVERSAL,
            created_by_id=actor_id, leave_request_id=req.id,
        )
        db.session.commit()
        assert ledger_service.balance(pid, BalanceKind.OFF) == 0

        early_return(req, actor, THU)  # outstanding 0, cost 2 -> max(0, 0-2) = 0

        assert db.session.get(LeaveRequest, req.id).end_date == THU  # still shortened
        rows = db.session.query(LedgerEntry).filter_by(leave_request_id=req.id).all()
        assert len(rows) == 2  # nothing new posted, no negative credit, no crash
        assert ledger_service.balance(pid, BalanceKind.OFF) == 0


# --- Criterion 4: guards each raise TransitionError, nothing saved ------------

def test_guard_non_approved_status(app, make_person):
    make_person(username="er_g1")
    make_person(username="er_g1_s3", company_role="S3")
    with app.app_context():
        pid, actor_id = _pid("er_g1"), _pid("er_g1_s3")
        req = _approved(pid)
        req.status = RequestStatus.PENDING_OC  # not APPROVED
        db.session.commit()
        with pytest.raises(TransitionError):
            early_return(req, db.session.get(Person, actor_id), THU)
        assert db.session.get(LeaveRequest, req.id).end_date == MON
        assert _reversals(req.id) == []


def test_guard_half_day_request(app, make_person):
    make_person(username="er_g2")
    make_person(username="er_g2_s3", company_role="S3")
    with app.app_context():
        pid, actor_id = _pid("er_g2"), _pid("er_g2_s3")
        req = _approved(pid, start=THU, end=THU, day_part=DayPart.AM)  # half-day
        db.session.commit()
        with pytest.raises(TransitionError):
            early_return(req, db.session.get(Person, actor_id), THU)
        assert db.session.get(LeaveRequest, req.id).end_date == THU
        assert _reversals(req.id) == []


def test_guard_single_day_request(app, make_person):
    make_person(username="er_g3")
    make_person(username="er_g3_s3", company_role="S3")
    with app.app_context():
        pid, actor_id = _pid("er_g3"), _pid("er_g3_s3")
        req = _approved(pid, start=THU, end=THU)  # single-day FULL
        _debit(pid, req.id, actor_id, -2)
        db.session.commit()
        with pytest.raises(TransitionError):
            early_return(req, db.session.get(Person, actor_id), THU)
        assert _reversals(req.id) == []
        assert ledger_service.balance(pid, BalanceKind.OFF) == -2


def test_guard_new_end_not_before_current_end(app, make_person):
    make_person(username="er_g4")
    make_person(username="er_g4_s3", company_role="S3")
    with app.app_context():
        pid, actor_id = _pid("er_g4"), _pid("er_g4_s3")
        req = _approved(pid)
        _debit(pid, req.id, actor_id, -6)
        db.session.commit()
        actor = db.session.get(Person, actor_id)
        with pytest.raises(TransitionError):
            early_return(req, actor, MON)  # == current end
        with pytest.raises(TransitionError):
            early_return(req, actor, TUE_NEXT)  # after current end
        assert db.session.get(LeaveRequest, req.id).end_date == MON
        assert _reversals(req.id) == []


def test_guard_new_end_before_start(app, make_person):
    make_person(username="er_g5")
    make_person(username="er_g5_s3", company_role="S3")
    with app.app_context():
        pid, actor_id = _pid("er_g5"), _pid("er_g5_s3")
        req = _approved(pid)
        _debit(pid, req.id, actor_id, -6)
        db.session.commit()
        with pytest.raises(TransitionError):
            early_return(req, db.session.get(Person, actor_id), WED)  # before start
        assert db.session.get(LeaveRequest, req.id).end_date == MON
        assert _reversals(req.id) == []


# --- Criterion 5 (mechanism): concurrent amendment loses at the claim ---------

def test_concurrent_amendment_loses_at_claim(app, make_person):
    """The claim's end_date predicate: if the row was already amended out from
    under our (stale) object, the conditional UPDATE matches 0 rows and we abort
    with no credit — no double-crediting under a double-submit/concurrency."""
    make_person(username="er_cc")
    make_person(username="er_cc_s3", company_role="S3")
    with app.app_context():
        pid, actor_id = _pid("er_cc"), _pid("er_cc_s3")
        req = _approved(pid)
        _debit(pid, req.id, actor_id, -6)
        db.session.commit()
        # Simulate another actor amending first: move end_date WITHOUT syncing our
        # in-memory object, so req.end_date stays MON (stale) while the row is THU.
        db.session.execute(
            update(LeaveRequest).where(LeaveRequest.id == req.id).values(end_date=THU),
            execution_options={"synchronize_session": False},
        )
        assert req.end_date == MON  # our view is stale; guards will still pass
        with pytest.raises(TransitionError):
            early_return(req, db.session.get(Person, actor_id), FRI)
        db.session.rollback()
        assert ledger_service.balance(pid, BalanceKind.OFF) == -6  # untouched
        assert _reversals(req.id) == []


# --- Criterion 7: LL request (multi-day, no ledger) — shortens, no ledger row -

def test_ll_amendment_posts_no_ledger_row(app, make_person):
    make_person(username="er_ll")
    make_person(username="er_ll_s3", company_role="S3")
    with app.app_context():
        pid, actor_id = _pid("er_ll"), _pid("er_ll_s3")
        req = _approved(pid, type=LeaveType.LL)  # LL: absence only, no ledger
        req.remarks = "Prior note"  # a pre-existing remark must be preserved
        db.session.commit()
        early_return(req, db.session.get(Person, actor_id), THU)  # must not crash
        req_after = db.session.get(LeaveRequest, req.id)
        assert req_after.end_date == THU
        assert db.session.query(LedgerEntry).filter_by(leave_request_id=req.id).all() == []
        # Fix 1: LL credits nothing, but the amendment still records who/what.
        assert req_after.remarks.startswith("Prior note; Early return by")
        assert "end 17 Aug -> 13 Aug" in req_after.remarks


# --- Fix 1: zero prorated credit (dropped days non-working) still traces -------

def test_zero_credit_off_still_records_trace(app, make_person):
    """Approve Thu–Sun (Sat/Sun non-working), return to Fri: the only days dropped
    are the weekend, so the prorated credit is 0 — no REVERSAL row. The amendment
    must still shorten the absence AND leave an audit trace on the request row."""
    make_person(username="er_zc")
    make_person(username="er_zc_s3", company_role="S3")
    with app.app_context():
        pid, actor_id = _pid("er_zc"), _pid("er_zc_s3")
        actor = db.session.get(Person, actor_id)
        req = _approved(pid, start=THU, end=SUN)  # Thu–Sun; only Thu+Fri are working
        _debit(pid, req.id, actor_id, -4)  # 2 working days = 4 half-days
        db.session.commit()

        early_return(req, actor, FRI)  # drop Sat+Sun only -> credit max(0, 4-4) = 0

        req_after = db.session.get(LeaveRequest, req.id)
        assert req_after.end_date == FRI  # absence shortened
        assert _reversals(req.id) == []  # zero credit -> no REVERSAL row
        assert ledger_service.balance(pid, BalanceKind.OFF) == -4  # balance untouched
        assert "Early return by" in req_after.remarks
        assert "end 16 Aug -> 14 Aug" in req_after.remarks


# --- Criterion 6: route authz + the away board shortens end-to-end -----------

def _people(make_person):
    make_person(username="er_opr", display_name="PTE Away Board", platoon=1)
    make_person(username="er_pc", rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=1)
    make_person(username="er_oc", rank=Rank.CPT, appointment=Appointment.OC, platoon=None)
    make_person(
        username="er_s3", rank=Rank.TWO_SG, appointment=Appointment.DET_COMD,
        company_role="S3", platoon=1,
    )


def test_route_authz_and_success(app, client, make_person):
    _people(make_person)
    with app.app_context():
        opr_id, s3_id = _pid("er_opr"), _pid("er_s3")
        req_a = _approved(opr_id)
        _debit(opr_id, req_a.id, s3_id, -6)
        req_b = _approved(opr_id)
        _debit(opr_id, req_b.id, s3_id, -6)
        db.session.commit()
        rid_a, rid_b = req_a.id, req_b.id

    # Opr and PC are denied; the guard aborts before any mutation.
    for who in ("er_opr", "er_pc"):
        login(client, who)
        resp = client.post(f"/leave/{rid_a}/early-return", data={"new_end_date": THU.isoformat()})
        assert resp.status_code == 403
        client.post("/logout")
    with app.app_context():
        assert db.session.get(LeaveRequest, rid_a).end_date == MON
        assert ledger_service.balance(_pid("er_opr"), BalanceKind.OFF) == -12

    # S3 succeeds on request A.
    login(client, "er_s3")
    resp = client.post(
        f"/leave/{rid_a}/early-return", data={"new_end_date": THU.isoformat()},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    client.post("/logout")

    # OC succeeds on request B.
    login(client, "er_oc")
    resp = client.post(
        f"/leave/{rid_b}/early-return", data={"new_end_date": THU.isoformat()},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    client.post("/logout")

    with app.app_context():
        assert db.session.get(LeaveRequest, rid_a).end_date == THU
        assert db.session.get(LeaveRequest, rid_b).end_date == THU
        # -12 debit, +4 credited on each request -> -4 remaining.
        assert ledger_service.balance(_pid("er_opr"), BalanceKind.OFF) == -4


def test_route_early_return_shortens_away_board(app, client, make_person):
    make_person(username="ab_opr", display_name="PTE Away Board", platoon=1)
    make_person(username="ab_s3", company_role="S3")
    with app.app_context():
        opr_id, s3_id = _pid("ab_opr"), _pid("ab_s3")
        req = _approved(opr_id)
        _debit(opr_id, req.id, s3_id, -6)
        db.session.commit()
        rid = req.id

    login(client, "ab_s3")
    # Before: Fri inside the range shows the person away.
    assert b"PTE Away Board" in client.get(f"/parade/away?date={FRI.isoformat()}").data
    resp = client.post(
        f"/leave/{rid}/early-return", data={"new_end_date": THU.isoformat()},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # After: Thu still away, Fri no longer (absence derived from the shortened range).
    assert b"PTE Away Board" in client.get(f"/parade/away?date={THU.isoformat()}").data
    assert b"PTE Away Board" not in client.get(f"/parade/away?date={FRI.isoformat()}").data
    with app.app_context():
        assert ledger_service.balance(_pid("ab_opr"), BalanceKind.OFF) == -2


def test_route_double_submit_no_second_credit(app, client, make_person):
    make_person(username="ds_opr", platoon=1)
    make_person(username="ds_s3", company_role="S3")
    with app.app_context():
        opr_id, s3_id = _pid("ds_opr"), _pid("ds_s3")
        req = _approved(opr_id)
        _debit(opr_id, req.id, s3_id, -6)
        db.session.commit()
        rid = req.id

    login(client, "ds_s3")
    client.post(f"/leave/{rid}/early-return", data={"new_end_date": THU.isoformat()}, follow_redirects=True)
    # Second identical submit: the request is now THU–THU (single-day), so the
    # multi-day guard (end_date <= start_date) rejects it before the range check
    # or the conditional claim ever run. (The claim-predicate path — a stale
    # in-memory end_date while the row moved — is covered by
    # test_concurrent_amendment_loses_at_claim.)
    client.post(f"/leave/{rid}/early-return", data={"new_end_date": THU.isoformat()}, follow_redirects=True)
    with app.app_context():
        assert ledger_service.balance(_pid("ds_opr"), BalanceKind.OFF) == -2
        assert len(_reversals(rid)) == 1  # exactly one credit, never doubled


# --- Criterion 6 (template): form shown only for eligible requests + viewers --

def test_detail_form_visibility(app, client, make_person):
    make_person(username="v_opr", platoon=1)
    make_person(username="v_s3", company_role="S3")
    with app.app_context():
        opr_id = _pid("v_opr")
        multi = _approved(opr_id)  # APPROVED, FULL, multi-day -> eligible
        single = _approved(opr_id, start=THU, end=THU)  # single-day -> not eligible
        pending = _approved(opr_id)
        pending.status = RequestStatus.PENDING_OC  # not approved -> not eligible
        db.session.commit()
        multi_id, single_id, pending_id = multi.id, single.id, pending.id

    login(client, "v_s3")
    assert b"/early-return" in client.get(f"/leave/{multi_id}").data
    assert b"/early-return" not in client.get(f"/leave/{single_id}").data
    assert b"/early-return" not in client.get(f"/leave/{pending_id}").data
    client.post("/logout")

    # Requester may view the eligible request but the form is hidden (not S3/OC).
    login(client, "v_opr")
    assert b"/early-return" not in client.get(f"/leave/{multi_id}").data
