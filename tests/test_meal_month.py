"""The meal-indent month grid (owner decision (bb) 2026-07-29, revised by (cc)
2026-07-30): one expected number per day = the morning(D) day count, derived
through the same compute_for the day view uses — never a second derivation.

A day whose parade document is out of balance carries `None` (rendered "—")
so one refused day cannot hide the whole month.
"""
from datetime import date

from app.domain.types import CompanyRole, Rank, Service
from app.services import meal_service

DAY = date(2026, 7, 8)  # Wednesday — same convention as the other parade tests
YM = "2026-07"


def _cell(context, day):
    for week in context["weeks"]:
        for cell in week:
            if cell["date"] == day:
                return cell
    raise AssertionError(f"{day} is not in the grid")


def _seed(make_person):
    make_person(
        username="s4_guy", company_role=CompanyRole.S4, service=Service.REGULAR,
        display_name="Siti Rahim", rank=Rank.ONE_SG,
    )
    make_person(username="stay_in", display_name="Daniel Lim", rank=Rank.CFC)
    make_person(username="stay_out_guy", display_name="Marcus Tan", rank=Rank.CPL,
                stay_out=True)


def test_month_grid_cell_carries_the_day_count(app, make_person):
    _seed(make_person)
    with app.app_context():
        expected, imbalance = meal_service.compute_for(DAY)
        assert imbalance is None
        cell = _cell(meal_service.month_context(YM), DAY)
    assert cell["in_month"] is True
    # Both NSFs are in camp by day; the opted-out regular S4 never counts.
    assert cell["expected"] == expected == 2


def test_padding_cells_carry_no_number(app, make_person):
    _seed(make_person)
    with app.app_context():
        context = meal_service.month_context(YM)
    padding = [cell for week in context["weeks"] for cell in week if not cell["in_month"]]
    assert padding, "July 2026 starts mid-week, so the grid has padding cells"
    assert all(cell["expected"] is None for cell in padding)


def test_one_out_of_balance_day_does_not_hide_the_month(app, make_person, monkeypatch):
    _seed(make_person)
    real_compute_for = meal_service.compute_for

    def fake(day):
        if day == DAY:
            return None, "out of balance"
        return real_compute_for(day)

    monkeypatch.setattr(meal_service, "compute_for", fake)
    with app.app_context():
        context = meal_service.month_context(YM)
    assert _cell(context, DAY)["expected"] is None
    for neighbour in (date(2026, 7, 7), date(2026, 7, 9)):
        assert isinstance(_cell(context, neighbour)["expected"], int)


def test_month_context_navigation_wraps_the_year(app, make_person):
    _seed(make_person)
    with app.app_context():
        context = meal_service.month_context("2026-12")
    assert context["month_start"] == date(2026, 12, 1)
    assert (context["prev_ym"], context["next_ym"]) == ("2026-11", "2027-01")
