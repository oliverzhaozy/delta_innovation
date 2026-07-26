"""P4.5 + P4.6 — /duty/roster page and manual assignment.

Routes are thin wires over duty_service; these tests hit the real app so the
wiring, rights (view-for-all vs manage-for-PS), and the hard-block-vs-warn
split are pinned through actual responses, mirroring the parade page suites.
"""
import re
from datetime import date

from app.domain.types import (
    Appointment, DayPart, Duty, DutyState, LeaveType, Rank, RequestStatus,
)
from app.extensions import db
from app.models import DutyAssignment, LeaveRequest, Person
from app.services import duty_service
from tests.conftest import login

AUG = "2026-08"


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def get_person(username):
    """Live Person row — call inside an app context."""
    return db.session.query(Person).filter_by(username=username).one()


def make_cos_pair(make_person):
    make_person(username="det1", rank=Rank.THREE_SG, appointment=Appointment.DET_COMD)
    make_person(username="opr1", rank=Rank.CPL, appointment=Appointment.OPR)


# --- month_view ------------------------------------------------------------------

def test_month_view_blanks_derived_from_missing_rows(app, make_person):
    make_cos_pair(make_person)

    with app.app_context():
        duty_service.generate_month(AUG, get_person("det1"))
        hole = date(2026, 8, 15)
        (
            db.session.query(DutyAssignment)
            .filter_by(date=hole, duty=Duty.COS, state=DutyState.PROPOSED)
            .delete()
        )
        db.session.commit()

        view = duty_service.month_view(AUG)
        # Blanks are the ABSENCE of a row — month_view must fill the missing
        # (day, duty) slots with None before asking violations() to flag them.
        assert (hole, Duty.COS) in view.violations.blanks
        assert (hole, Duty.COS) not in view.by_slot
        assert view.first == date(2026, 8, 1)
        assert view.last == date(2026, 8, 31)
        assert len(view.days) == 31


def test_month_view_empty_pool_all_blank(app, make_person):
    make_cos_pair(make_person)  # nobody is CDOS-eligible

    with app.app_context():
        duty_service.generate_month(AUG, get_person("det1"))
        view = duty_service.month_view(AUG)
        assert view.pools[Duty.CDOS] == []
        for d in view.days:
            assert (d, Duty.CDOS) in view.violations.blanks


# --- page + generate/confirm routes ----------------------------------------------

def make_full_cast(make_person):
    """COS pair + a roster-managing PS (2SG PS: CDOS-eligible) + a viewer Opr."""
    make_cos_pair(make_person)
    make_person(username="ps2", rank=Rank.TWO_SG, appointment=Appointment.PS, platoon=2)


def rendered_fingerprint(html):
    match = re.search(r'name="fingerprint" value="([0-9a-f]{64})"', html)
    assert match, "confirm form must render the fingerprint"
    return match.group(1)


def test_roster_page_viewable_by_opr_without_buttons(app, client, make_person):
    make_full_cast(make_person)
    login(client, "opr1")

    page = client.get(f"/duty/roster?month={AUG}")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "COS pool" in html and "CDO/S pool" in html
    assert 'name="fingerprint"' not in html
    assert "/duty/roster/generate" not in html
    assert "/duty/roster/confirm" not in html


def test_manual_assign_select_is_parade_ordered(app, client, make_person):
    # UI-22: the assign dropdown was the last alphabetical people list. Parade
    # order now: PC, P2IC (3WO above LTA — the parade hoist, not the legal
    # RANK_ORDER), PS, Det Comd, Opr. The names alphabetize in a different order
    # entirely, so a regression to display_name fails here.
    make_person(username="ord_pc", display_name="Yankee Pc", rank=Rank.LTA,
                appointment=Appointment.PC, platoon=1)
    make_person(username="ord_p2ic_wo", display_name="Bravo P2ic", rank=Rank.THREE_WO,
                appointment=Appointment.P2IC, platoon=2)
    make_person(username="ord_p2ic_lta", display_name="Alpha P2ic", rank=Rank.LTA,
                appointment=Appointment.P2IC, platoon=3)
    make_person(username="ord_det", display_name="Zulu Det", rank=Rank.THREE_SG,
                appointment=Appointment.DET_COMD, platoon=1)
    make_person(username="ord_opr", display_name="Charlie Opr", rank=Rank.PTE,
                appointment=Appointment.OPR, platoon=1)
    make_person(username="ord_ps", display_name="Delta Ps", rank=Rank.TWO_SG,
                appointment=Appointment.PS, platoon=2)
    login(client, "ord_ps")

    html = client.get(f"/duty/roster?month={AUG}").get_data(as_text=True)
    select = re.search(r'<select name="person_id">.*?</select>', html, re.S).group(0)
    assert re.findall(r'<option value="\d+">([^<]+)</option>', select) == [
        "LTA Yankee Pc",
        "3WO Bravo P2ic",
        "LTA Alpha P2ic",
        "2SG Delta Ps",
        "3SG Zulu Det",
        "PTE Charlie Opr",
    ]


def test_roster_mutations_403_for_opr(app, client, make_person):
    make_full_cast(make_person)
    login(client, "opr1")

    for endpoint in ("generate", "confirm", "assign", "clear"):
        resp = client.post(f"/duty/roster/{endpoint}", data={"month": AUG})
        assert resp.status_code == 403, endpoint


def test_empty_pool_warning_card(app, client, make_person):
    # COS people exist; the CDOS pool is empty -> warning card renders.
    make_cos_pair(make_person)
    login(client, "opr1")

    html = client.get(f"/duty/roster?month={AUG}").get_data(as_text=True)
    assert "CDO/S pool is empty or tiny" in html


def test_bad_month_query_falls_back_to_current_month(app, client, make_person):
    make_full_cast(make_person)
    login(client, "opr1")
    # Same posture as parade's _parse_day: junk never 400s the page.
    assert client.get("/duty/roster?month=garbage").status_code == 200


def test_generate_then_confirm_flips_badges(app, client, make_person):
    make_full_cast(make_person)
    login(client, "ps2")

    proposed_badge = '<span class="badge pending">PROPOSED</span>'
    confirmed_badge = '<span class="badge approved">CONFIRMED</span>'

    resp = client.post("/duty/roster/generate", data={"month": AUG}, follow_redirects=True)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert proposed_badge in html and confirmed_badge not in html

    resp = client.post(
        "/duty/roster/confirm",
        data={"month": AUG, "fingerprint": rendered_fingerprint(html)},
        follow_redirects=True,
    )
    html = resp.get_data(as_text=True)
    assert confirmed_badge in html and proposed_badge not in html


# --- manual assign / clear (P4.6 part 1) ------------------------------------------

def plant_leave(app, username, day, *, day_part=DayPart.FULL):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(
            LeaveRequest(
                person_id=person_id, type=LeaveType.OFF, start_date=day,
                end_date=day, day_part=day_part, status=RequestStatus.APPROVED,
            )
        )
        db.session.commit()


def plant_assignment(app, username, day, duty, *, state=DutyState.CONFIRMED):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        row = DutyAssignment(
            date=day, duty=duty, person_id=person_id, state=state,
            created_by_id=person_id,
        )
        db.session.add(row)
        db.session.commit()
        return row.id


def assign_form(username_key, app, day, duty=Duty.COS, **extra):
    data = {
        "month": AUG, "date": day.isoformat(), "duty": duty.value,
        "person_id": str(pid(app, username_key)),
    }
    data.update(extra)
    return data


def test_assign_ineligible_is_400(app, client, make_person):
    make_full_cast(make_person)
    make_person(username="pc2", rank=Rank.LTA, appointment=Appointment.PC, platoon=2)
    login(client, "ps2")

    resp = client.post(
        "/duty/roster/assign", data=assign_form("pc2", app, date(2026, 8, 5))
    )
    assert resp.status_code == 400
    with app.app_context():
        assert db.session.query(DutyAssignment).count() == 0


def test_duty_exempt_person_out_of_pool_and_assign_is_400(app, client, make_person):
    # Owner 2026-07-24: duty_exempt carves a person out of the pools AND out
    # of manual assignment — still rank/appointment-eligible, so this pins the
    # flag, not the law.
    make_full_cast(make_person)
    make_person(username="p2ic_x", rank=Rank.THREE_WO, appointment=Appointment.P2IC,
                platoon=None, duty_exempt=True, display_name="Exempt Ptwoic")
    login(client, "ps2")

    html = client.get(f"/duty/roster?month={AUG}").get_data(as_text=True)
    assert "CDO/S pool (1)" in html  # ps2 alone — the exempt P2IC is carved out
    assert "Exempt Ptwoic" not in html

    resp = client.post(
        "/duty/roster/assign",
        data=assign_form("p2ic_x", app, date(2026, 8, 5), duty=Duty.CDOS),
    )
    assert resp.status_code == 400
    with app.app_context():
        assert db.session.query(DutyAssignment).count() == 0


def test_assign_unavailable_requires_confirm(app, client, make_person):
    make_full_cast(make_person)
    plant_leave(app, "det1", date(2026, 8, 5))
    login(client, "ps2")

    resp = client.post(
        "/duty/roster/assign",
        data=assign_form("det1", app, date(2026, 8, 5)),
        follow_redirects=True,
    )
    assert "Not assigned" in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.query(DutyAssignment).count() == 0

    resp = client.post(
        "/duty/roster/assign",
        data=assign_form("det1", app, date(2026, 8, 5), confirm="1"),
        follow_redirects=True,
    )
    assert "Assigned." in resp.get_data(as_text=True)
    with app.app_context():
        row = db.session.query(DutyAssignment).one()
        assert row.person_id == pid(app, "det1")
        assert row.state is DutyState.PROPOSED


def test_assign_replaces_confirmed_keeping_confirmed(app, client, make_person):
    make_full_cast(make_person)
    row_id = plant_assignment(app, "det1", date(2026, 8, 5), Duty.COS)
    login(client, "ps2")

    resp = client.post(
        "/duty/roster/assign",
        data=assign_form("opr1", app, date(2026, 8, 5), confirm="1"),
        follow_redirects=True,
    )
    assert "Assigned." in resp.get_data(as_text=True)
    with app.app_context():
        row = db.session.get(DutyAssignment, row_id)
        # Manual replace is how the PS resolves a post-approval clash: the slot
        # stays CONFIRMED (tonight's roll call must not lose its duty) with a
        # fresh stamp saying who changed it.
        assert row.person_id == pid(app, "opr1")
        assert row.state is DutyState.CONFIRMED
        assert row.confirmed_by_id == pid(app, "ps2")
        assert db.session.query(DutyAssignment).count() == 1


def test_new_row_on_empty_slot_is_proposed_not_confirmed(app, client, make_person):
    make_full_cast(make_person)
    login(client, "ps2")

    client.post(
        "/duty/roster/assign",
        data=assign_form("det1", app, date(2026, 8, 5)),
        follow_redirects=True,
    )
    with app.app_context():
        row = db.session.query(DutyAssignment).one()
        assert row.state is DutyState.PROPOSED
        assert row.confirmed_by_id is None


def test_clear_removes_row(app, client, make_person):
    make_full_cast(make_person)
    plant_assignment(app, "det1", date(2026, 8, 5), Duty.COS)
    login(client, "ps2")

    data = {"month": AUG, "date": "2026-08-05", "duty": Duty.COS.value}
    resp = client.post("/duty/roster/clear", data=data, follow_redirects=True)
    assert "Cleared." in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.query(DutyAssignment).count() == 0

    resp = client.post("/duty/roster/clear", data=data, follow_redirects=True)
    assert "Nothing to clear." in resp.get_data(as_text=True)


def test_confirm_stale_fingerprint_flashes_rereview(app, client, make_person):
    make_full_cast(make_person)
    login(client, "ps2")

    html = client.post(
        "/duty/roster/generate", data={"month": AUG}, follow_redirects=True
    ).get_data(as_text=True)
    stale = rendered_fingerprint(html)

    # Another PS edits one slot after this page was loaded.
    with app.app_context():
        row = db.session.query(DutyAssignment).filter_by(duty=Duty.COS).first()
        other = get_person("det1" if row.person_id == pid(app, "opr1") else "opr1")
        row.person_id = other.id
        db.session.commit()

    resp = client.post(
        "/duty/roster/confirm",
        data={"month": AUG, "fingerprint": stale},
        follow_redirects=True,
    )
    html = resp.get_data(as_text=True)
    assert "re-review" in html
    with app.app_context():
        rows = db.session.query(DutyAssignment).all()
        assert rows and all(r.state is DutyState.PROPOSED for r in rows)
