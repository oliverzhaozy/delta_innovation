"""The S4 meals page after owner decision (j) (2026-07-07): two NSF presence
counters per day — NSFs in camp by day, NSFs staying tonight — and nothing
more. Meal indents are NSF-only, so the per-meal counts and the manual ±
(P3b.5/P3b.6 as originally built) were removed by the same decision; the
/meals/adjust route must be GONE, not just hidden.
"""
from datetime import date

from app.domain.types import CompanyRole, Service
from tests.conftest import login

DAY = date(2026, 7, 8)  # Wednesday — same convention as the other parade tests


def _s4(make_person):
    # A regular S4: keeps the fixture numbers purely about the NSFs below.
    return make_person(
        username="s4_guy", company_role=CompanyRole.S4, service=Service.REGULAR,
        display_name="1SG Siti Rahim",
    )


def test_meals_page_403s_for_opr(app, client, make_person):
    make_person(username="opr1")
    login(client, "opr1")
    assert client.get(f"/meals?date={DAY.isoformat()}").status_code == 403


def test_adjust_route_is_gone(app, client, make_person):
    _s4(make_person)
    login(client, "s4_guy")
    assert client.post("/meals/adjust", data={"date": DAY.isoformat()}).status_code == 404


def test_counters_render_engine_derived_numbers(app, client, make_person):
    _s4(make_person)
    make_person(username="stay_in", display_name="CFC Daniel Lim")
    make_person(username="stay_out_guy", display_name="CPL Marcus Tan", stay_out=True)
    login(client, "s4_guy")

    page = client.get(f"/meals?date={DAY.isoformat()}")
    assert page.status_code == 200
    # Day: both NSFs are in camp by day (stay-out dissolves at morning parade);
    # the regular S4 is present but never counted.
    assert b'id="nsf-day">2<' in page.data
    # Overnight: only the stay-in NSF remains for the night D -> D+1.
    assert b'id="nsf-overnight">1<' in page.data


def test_adjustment_ui_is_gone(app, client, make_person):
    _s4(make_person)
    login(client, "s4_guy")
    page = client.get(f"/meals?date={DAY.isoformat()}")
    assert b"Adjustment" not in page.data
    assert b"adjust" not in page.data.lower()
