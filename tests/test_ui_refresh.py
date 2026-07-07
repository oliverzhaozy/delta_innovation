"""UI refresh (owner-approved 2026-07-07) — the unified parade page's pill
row, the grouped nav's rights-gating, and dashboard link integrity."""
import re
from datetime import date

from app.domain.types import Appointment, Rank
from tests.conftest import login

DAY = date(2026, 7, 8)


def make_viewer(make_person, **kw):
    return make_person(username=kw.pop("username", "opr1"), **kw)


def pill_row(html):
    match = re.search(r'<nav class="pills".*?</nav>', html, re.S)
    assert match, "the parade pill row must render"
    return match.group(0)


def active_pill(html):
    match = re.search(r'<a[^>]*class="active"[^>]*>([^<]+)</a>', pill_row(html))
    return match.group(1).strip() if match else None


def test_parade_pills_and_active_states(app, client, make_person):
    make_viewer(make_person)
    login(client, "opr1")

    for path, label in (
        (f"/parade/morning?date={DAY.isoformat()}", "Morning"),
        (f"/parade/cos-message?date={DAY.isoformat()}", "COS message"),
        (f"/parade/roll-call?date={DAY.isoformat()}", "Roll call"),
        (f"/parade/away?date={DAY.isoformat()}", "Away board"),
        ("/parade/snapshots", "Snapshots"),
    ):
        html = client.get(path).get_data(as_text=True)
        assert active_pill(html) == label, path


def test_pills_carry_the_page_date(app, client, make_person):
    make_viewer(make_person)
    login(client, "opr1")
    html = client.get(f"/parade/morning?date={DAY.isoformat()}").get_data(as_text=True)
    # Switching document tabs stays on the same day.
    assert f"/parade/roll-call?date={DAY.isoformat()}" in html.replace("&amp;", "&")


def test_nav_groups_are_rights_gated(app, client, make_person):
    make_viewer(make_person)  # a plain Opr
    login(client, "opr1")
    html = client.get("/").get_data(as_text=True)
    for summary in ("Parade", "Duty", "Leave", "Calendar", "Account"):
        assert f"<summary>{summary}" in html, summary
    # Staff-only entries stay invisible to an Opr.
    for hidden in ("Manning", "OFF/OIL ledger", ">People<", "NSF meals",
                   "Statuses", "Direct absences", "ARCTIC FOE"):
        assert hidden not in html, hidden

    client.post("/logout")
    make_person(username="s3_admin", company_role="S3", is_admin=True)
    login(client, "s3_admin")
    html = client.get("/").get_data(as_text=True)
    for visible in ("Manning", "OFF/OIL ledger", ">People<", "NSF meals"):
        assert visible in html, visible


def test_nav_highlights_the_current_section(app, client, make_person):
    make_viewer(make_person)
    login(client, "opr1")
    html = client.get("/duty/roster").get_data(as_text=True)
    match = re.search(r'<details class="navgroup" data-here>\s*<summary>(\w+)', html)
    assert match and match.group(1) == "Duty"


def test_dashboard_links_resolve_for_every_role(app, client, make_person):
    # Rendering IS the test: a broken url_for throws at render. Cover the
    # widest role (admin sees every card) and the narrowest (a plain Opr).
    make_person(username="admin", company_role="S3", is_admin=True)
    make_viewer(make_person, username="opr_only")

    for username in ("admin", "opr_only"):
        client.post("/logout")
        login(client, username)
        html = client.get("/").get_data(as_text=True)
        assert html.count("</section>") >= 3  # grouped cards, not one flat list
        # The stale placeholder the refresh removed must never come back.
        assert "Phase 4" not in html
        assert 'class="tag"' not in html  # no "Live"/"Phase N" tags anymore

    # The admin's dashboard reaches the staff-only surfaces.
    client.post("/logout")
    login(client, "admin")
    html = client.get("/").get_data(as_text=True)
    assert "People admin" in html
    assert "NSF meal counter" in html
    assert "TU manning" in html

    # ...which a plain Opr never sees.
    client.post("/logout")
    login(client, "opr_only")
    opr_html = client.get("/").get_data(as_text=True)
    for hidden in ("People admin", "NSF meal counter", "TU manning", "OFF/OIL ledger"):
        assert hidden not in opr_html, hidden
