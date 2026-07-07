"""P4.5 + P4.6 — /duty/roster page, manual assignment, validated swaps.

Routes are thin wires over duty_service; these tests hit the real app so the
wiring, rights (view-for-all vs manage-for-PS), and the hard-block-vs-warn
split are pinned through actual responses, mirroring the parade page suites.
"""
import re
from datetime import date

from app.domain.types import Appointment, Duty, DutyState, Rank
from app.extensions import db
from app.models import DutyAssignment, Person
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


def test_roster_mutations_403_for_opr(app, client, make_person):
    make_full_cast(make_person)
    login(client, "opr1")

    for endpoint in ("generate", "confirm"):
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

    resp = client.post("/duty/roster/generate", data={"month": AUG}, follow_redirects=True)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "PROPOSED" in html and "CONFIRMED" not in html

    resp = client.post(
        "/duty/roster/confirm",
        data={"month": AUG, "fingerprint": rendered_fingerprint(html)},
        follow_redirects=True,
    )
    html = resp.get_data(as_text=True)
    assert "CONFIRMED" in html and "PROPOSED" not in html


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
