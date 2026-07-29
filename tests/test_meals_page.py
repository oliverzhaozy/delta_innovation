"""The S4 meal-indent pages after owner decisions (j) (2026-07-07) and (bb)
(2026-07-29): a month grid of one expected number per day, and a day view with
the two presence counters behind it — nothing more. The per-meal counts and the
manual ± (P3b.5/P3b.6 as originally built) were removed by decision (j); the
/meals/adjust route must be GONE, not just hidden.
"""
from datetime import date

from app.domain.types import CompanyRole, Rank, Service
from tests.conftest import login

DAY = date(2026, 7, 8)  # Wednesday — same convention as the other parade tests
YM = "2026-07"


def _s4(make_person):
    # A regular S4: keeps the fixture numbers purely about the NSFs below.
    return make_person(
        username="s4_guy", company_role=CompanyRole.S4, service=Service.REGULAR,
        display_name="Siti Rahim", rank=Rank.ONE_SG,
    )


def _two_nsfs(make_person):
    make_person(username="stay_in", display_name="Daniel Lim", rank=Rank.CFC)
    make_person(username="stay_out_guy", display_name="Marcus Tan", rank=Rank.CPL,
                stay_out=True)


def test_meals_pages_403_for_opr(app, client, make_person):
    make_person(username="opr1")
    login(client, "opr1")
    assert client.get(f"/meals?ym={YM}").status_code == 403
    assert client.get(f"/meals/day?date={DAY.isoformat()}").status_code == 403


def test_adjust_route_is_gone(app, client, make_person):
    _s4(make_person)
    login(client, "s4_guy")
    assert client.post("/meals/adjust", data={"date": DAY.isoformat()}).status_code == 404


def test_counters_render_engine_derived_numbers(app, client, make_person):
    _s4(make_person)
    _two_nsfs(make_person)
    login(client, "s4_guy")

    page = client.get(f"/meals/day?date={DAY.isoformat()}")
    assert page.status_code == 200
    # Day: both NSFs are in camp by day (stay-out dissolves at morning parade);
    # the regular S4 has not opted in, so he is never counted.
    assert b'id="meal-day">2<' in page.data
    # Overnight: only the stay-in NSF remains for the night D -> D+1.
    assert b'id="meal-overnight">1<' in page.data
    # The one number S4 indents for: the larger of the two.
    assert b'id="meal-expected">2<' in page.data


def test_month_grid_links_each_day_to_its_breakdown(app, client, make_person):
    _s4(make_person)
    _two_nsfs(make_person)
    login(client, "s4_guy")

    page = client.get(f"/meals?ym={YM}")
    assert page.status_code == 200
    assert b"July 2026" in page.data
    assert f'href="/meals/day?date={DAY.isoformat()}"'.encode() in page.data
    # The grid carries the expected number itself, not just a link.
    assert b">2</a>" in page.data


def test_month_grid_marks_an_out_of_balance_day(app, client, make_person, monkeypatch):
    from app.services import meal_service

    _s4(make_person)
    _two_nsfs(make_person)
    login(client, "s4_guy")

    real_compute_for = meal_service.compute_for

    def fake(day):
        if day == DAY:
            return None, "out of balance"
        return real_compute_for(day)

    monkeypatch.setattr(meal_service, "compute_for", fake)
    page = client.get(f"/meals?ym={YM}").get_data(as_text=True)
    assert "A parade document for these dates is out of balance" in page
    # The rest of the month still renders its numbers.
    assert "meal-num meal-warn" in page and page.count("meal-num") > 1


def test_adjustment_ui_is_gone(app, client, make_person):
    _s4(make_person)
    login(client, "s4_guy")
    for url in (f"/meals?ym={YM}", f"/meals/day?date={DAY.isoformat()}"):
        page = client.get(url)
        assert b"Adjustment" not in page.data
        assert b"adjust" not in page.data.lower()
