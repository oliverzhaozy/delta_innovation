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
