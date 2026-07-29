"""UI refresh (owner-approved 2026-07-07) — the unified parade page's pill
row, the grouped nav's rights-gating, and dashboard link integrity."""
import re

from app.domain.types import Appointment, Rank
from tests.conftest import login


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
        ("/parade/morning", "Morning parade state"),
        ("/parade/cos-message", "COS message"),
        ("/parade/roll-call", "Roll call"),
    ):
        html = client.get(path).get_data(as_text=True)
        assert active_pill(html) == label, path


def test_pills_have_no_date_param(app, client, make_person):
    make_viewer(make_person)
    login(client, "opr1")
    html = client.get("/parade/morning").get_data(as_text=True)
    # Each page is fixed to its operational date, so the tab links are plain —
    # no ?date= carries a day across tabs.
    assert "?date=" not in pill_row(html)


def test_nav_groups_are_rights_gated(app, client, make_person):
    make_viewer(make_person)  # a plain Opr
    login(client, "opr1")
    html = client.get("/").get_data(as_text=True)
    for summary in ("Parade", "Duty", "Leave", "Calendar", "Account"):
        assert f"<summary>{summary}" in html, summary
    # Staff-only entries stay invisible to an Opr.
    for hidden in ("TU manning", "OFF/OIL ledger", ">People<", "Meal indents",
                   "Statuses", "Direct absences", "ARCTIC FOE"):
        assert hidden not in html, hidden

    client.post("/logout")
    make_person(username="s3_admin", company_role="S3", is_admin=True)
    login(client, "s3_admin")
    html = client.get("/").get_data(as_text=True)
    for visible in ("TU manning", "OFF/OIL ledger", ">People<", "Meal indents"):
        assert visible in html, visible


def test_nav_highlights_the_current_section(app, client, make_person):
    make_viewer(make_person)
    login(client, "opr1")
    html = client.get("/duty/roster").get_data(as_text=True)
    match = re.search(r'<details class="navgroup" data-here>\s*<summary>(\w+)', html)
    assert match and match.group(1) == "Duty"


def test_home_calendar_renders_for_every_role(app, client, make_person):
    # Home is the calendar. Rendering IS the test: a broken url_for throws at
    # render. Cover the widest role (admin) and the narrowest (a plain Opr).
    make_person(username="admin", company_role="S3", is_admin=True)
    make_viewer(make_person, username="opr_only")

    for username in ("admin", "opr_only"):
        client.post("/logout")
        login(client, username)
        html = client.get("/").get_data(as_text=True)
        assert "month-grid" in html  # the calendar overlay, not the old tiles
        assert "Phase 4" not in html

    # Staff-only nav surfaces reach the admin (nav is on every page)...
    client.post("/logout")
    login(client, "admin")
    html = client.get("/").get_data(as_text=True)
    for visible in (">People<", "Meal indents", "TU manning"):
        assert visible in html, visible

    # ...which a plain Opr never sees.
    client.post("/logout")
    login(client, "opr_only")
    opr_html = client.get("/").get_data(as_text=True)
    for hidden in (">People<", "Meal indents", "TU manning", "OFF/OIL ledger"):
        assert hidden not in opr_html, hidden
