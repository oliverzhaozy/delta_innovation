"""Service-level tests for the month context (UI-24).

`build_month_context` decides the unified lane cap, the per-day "+N" breakdown,
the today flag and the day-detail panel's entries entirely on its own, so these
call it directly instead of going through HTTP and parsing markup.
"""
from datetime import date, datetime

from app.domain.dates import today_sgt
from app.domain.events import all_day_bounds
from app.domain.types import Appointment, Calendar, DayPart, LeaveType, Rank, RequestStatus
from app.extensions import db
from app.models import Event, LeaveRequest, Person
from app.services.calendar_month import FIRST_LANE_ROW, TOTAL_LANE_LIMIT, build_month_context

# Mon 6 Jul 2026 opens a week row; Wed 8 Jul is its column 3.
MONDAY = date(2026, 7, 6)
WEDNESDAY = date(2026, 7, 8)


def person_id(username):
    return db.session.query(Person.id).filter_by(username=username).scalar()


def add_event(creator, title, start, end, calendar=Calendar.TP):
    db.session.add(
        Event(
            calendar=calendar,
            title=title,
            start_dt=start,
            end_dt=end,
            created_by_id=creator,
        )
    )
    db.session.commit()


def add_leave(username, day, end=None):
    db.session.add(
        LeaveRequest(
            person_id=person_id(username),
            type=LeaveType.OFF,
            start_date=day,
            end_date=end or day,
            day_part=DayPart.FULL,
            status=RequestStatus.APPROVED,
        )
    )
    db.session.commit()


def viewer(make_person, username):
    """A PC — the month grid's ARCTIC bars need `can_view_arctic`."""
    return make_person(username=username, rank=Rank.TWO_LT, appointment=Appointment.PC)


def week_from(context, monday):
    return next(w for w in context["weeks"] if w["cells"][0]["date"] == monday)


def of_kind(week, kind):
    return [seg for seg in week["segments"] if seg["kind"] == kind]


# ---------- the unified cap ----------

def test_events_alone_overflow_the_cap_into_one_badge(app, make_person):
    # Seven single-day events stack to lanes 0-6; the cap shows five and folds
    # the rest into that day's badge — the events band used to be uncapped.
    viewer(make_person, "cms_cap_pc")
    with app.app_context():
        creator = person_id("cms_cap_pc")
        for hour in range(8, 15):
            add_event(
                creator,
                f"Thing {hour}",
                datetime(2026, 7, 8, hour, 0),
                datetime(2026, 7, 8, 17, 0),
            )
        user = db.session.query(Person).filter_by(username="cms_cap_pc").one()
        week = week_from(build_month_context(user, "2026-07"), MONDAY)

    assert len(of_kind(week, "event")) == TOTAL_LANE_LIMIT
    badges = of_kind(week, "more")
    assert len(badges) == 1
    assert (badges[0]["col"], badges[0]["span"]) == (3, 1)
    assert badges[0]["count"] == 2
    assert badges[0]["counts"] == {"tp": 2}
    # Flush under the last SHOWN bar, so the week is one row taller than the cap.
    assert badges[0]["row"] == FIRST_LANE_ROW + TOTAL_LANE_LIMIT
    assert week["lane_count"] == TOTAL_LANE_LIMIT + 1


def test_the_cap_counts_both_bands_and_splits_the_badge_by_toggle_key(app, make_person):
    # Six TP + one ARCTIC event fill lanes 0-6 and the two OFF runs floor under
    # them, so the ONE cap drops the last event of each calendar plus both OFF
    # runs — and the badge says which layer each hidden bar came from.
    viewer(make_person, "cms_mix_pc")
    make_person(username="cms_mix_a", platoon=1)
    make_person(username="cms_mix_b", platoon=1)
    with app.app_context():
        creator = person_id("cms_mix_pc")
        for hour in range(8, 14):
            add_event(
                creator,
                f"TP thing {hour}",
                datetime(2026, 7, 8, hour, 0),
                datetime(2026, 7, 8, 17, 0),
            )
        add_event(
            creator,
            "Arctic thing",
            datetime(2026, 7, 8, 14, 0),
            datetime(2026, 7, 8, 17, 0),
            calendar=Calendar.ARCTIC,
        )
        add_leave("cms_mix_a", WEDNESDAY)
        add_leave("cms_mix_b", WEDNESDAY)
        user = db.session.query(Person).filter_by(username="cms_mix_pc").one()
        week = week_from(build_month_context(user, "2026-07"), MONDAY)

    shown = of_kind(week, "event") + of_kind(week, "off")
    assert len(shown) == TOTAL_LANE_LIMIT
    assert all(seg["row"] < FIRST_LANE_ROW + TOTAL_LANE_LIMIT for seg in shown)
    badges = of_kind(week, "more")
    assert len(badges) == 1
    assert badges[0]["counts"] == {"tp": 1, "arctic": 1, "off": 2}
    assert badges[0]["count"] == 4


def test_a_dropped_multi_day_run_is_counted_on_every_day_it_covered(app, make_person):
    # Five people off Mon-Fri fill the cap; the sixth run is dropped and each of
    # its five days says it is hiding one.
    viewer(make_person, "cms_span_pc")
    for n in range(6):
        make_person(username=f"cms_span_{n}", platoon=1)
    with app.app_context():
        for n in range(6):
            add_leave(f"cms_span_{n}", MONDAY, end=date(2026, 7, 10))
        user = db.session.query(Person).filter_by(username="cms_span_pc").one()
        week = week_from(build_month_context(user, "2026-07"), MONDAY)

    assert len(of_kind(week, "off")) == TOTAL_LANE_LIMIT
    badges = of_kind(week, "more")
    assert [b["col"] for b in badges] == [1, 2, 3, 4, 5]
    assert all(b["counts"] == {"off": 1} and b["count"] == 1 for b in badges)


def test_a_week_inside_the_cap_grows_no_badge(app, make_person):
    viewer(make_person, "cms_quiet_pc")
    with app.app_context():
        creator = person_id("cms_quiet_pc")
        for hour in (8, 10):
            add_event(
                creator,
                f"Quiet {hour}",
                datetime(2026, 7, 8, hour, 0),
                datetime(2026, 7, 8, 17, 0),
            )
        user = db.session.query(Person).filter_by(username="cms_quiet_pc").one()
        week = week_from(build_month_context(user, "2026-07"), MONDAY)

    assert of_kind(week, "more") == []
    assert week["lane_count"] == 2


# ---------- today ----------

def test_only_the_current_months_own_cell_is_flagged_today(app, make_person):
    viewer(make_person, "cms_today_pc")
    today = today_sgt()
    with app.app_context():
        user = db.session.query(Person).filter_by(username="cms_today_pc").one()
        context = build_month_context(user, "")
        flagged = [
            cell for week in context["weeks"] for cell in week["cells"] if cell["is_today"]
        ]
        assert [cell["date"] for cell in flagged] == [today]

        # The next month's grid pads with days of THIS month — today may be one
        # of them, and a padding cell must not claim the ring.
        next_month = build_month_context(user, context["next_ym"])
        assert not any(
            cell["is_today"] for week in next_month["weeks"] for cell in week["cells"]
        )


# ---------- day_entries ----------

def test_every_day_of_the_month_has_an_entry_list(app, make_person):
    viewer(make_person, "cms_days_pc")
    with app.app_context():
        user = db.session.query(Person).filter_by(username="cms_days_pc").one()
        entries = build_month_context(user, "2026-07")["day_entries"]

    assert min(entries) == date(2026, 7, 1)
    assert max(entries) == date(2026, 7, 31)
    assert len(entries) == 31
    assert entries[date(2026, 7, 15)] == []  # a quiet day still opens the panel


def test_entry_days_match_the_bar_rule_including_the_month_clip(app, make_person):
    viewer(make_person, "cms_range_pc")
    with app.app_context():
        creator = person_id("cms_range_pc")
        add_event(creator, "Field camp", datetime(2026, 7, 6, 8, 0), datetime(2026, 7, 8, 17, 0))
        add_event(creator, "Boundary op", datetime(2026, 6, 30, 8, 0), datetime(2026, 7, 2, 17, 0))
        user = db.session.query(Person).filter_by(username="cms_range_pc").one()
        entries = build_month_context(user, "2026-07")["day_entries"]
        titles = {day: [e["obj"].title for e in rows] for day, rows in entries.items()}

    assert titles[date(2026, 7, 5)] == []
    assert titles[date(2026, 7, 6)] == ["Field camp"]
    assert titles[date(2026, 7, 7)] == ["Field camp"]
    assert titles[date(2026, 7, 8)] == ["Field camp"]
    assert titles[date(2026, 7, 9)] == []
    # Clipped at the month edge exactly like the bar: 30 Jun is July's business
    # only from the 1st onward.
    assert titles[date(2026, 7, 1)] == ["Boundary op"]
    assert titles[date(2026, 7, 2)] == ["Boundary op"]
    assert titles[date(2026, 7, 3)] == []


def test_whole_day_entries_lead_and_timed_events_follow_by_start_time(app, make_person):
    viewer(make_person, "cms_order_pc")
    make_person(username="cms_order_guy", platoon=1)
    with app.app_context():
        creator = person_id("cms_order_pc")
        add_event(creator, "Late thing", datetime(2026, 7, 8, 14, 0), datetime(2026, 7, 8, 17, 0))
        add_event(creator, "Early thing", datetime(2026, 7, 8, 9, 0), datetime(2026, 7, 8, 12, 0))
        add_event(creator, "Holiday", *all_day_bounds(WEDNESDAY, WEDNESDAY))
        add_leave("cms_order_guy", WEDNESDAY)
        user = db.session.query(Person).filter_by(username="cms_order_pc").one()
        entries = build_month_context(user, "2026-07")["day_entries"][WEDNESDAY]
        listed = [(e["kind"], e["cal_key"], e["time_display"]) for e in entries]
        names = [e["obj"].title if e["kind"] == "event" else e["obj"].person.display_name
                 for e in entries]

    assert listed == [
        ("event", "tp", "All-day"),
        ("off", "off", "All-day"),
        ("event", "tp", "9:00 AM – 12:00 PM"),
        ("event", "tp", "2:00 PM – 5:00 PM"),
    ]
    assert names == ["Holiday", "Cms Order Guy", "Early thing", "Late thing"]


def test_a_multi_day_timed_event_shows_its_ends_and_all_day_in_between(app, make_person):
    viewer(make_person, "cms_multi_pc")
    with app.app_context():
        creator = person_id("cms_multi_pc")
        add_event(creator, "Long ops", datetime(2026, 7, 6, 7, 0), datetime(2026, 7, 8, 15, 0))
        user = db.session.query(Person).filter_by(username="cms_multi_pc").one()
        entries = build_month_context(user, "2026-07")["day_entries"]
        shown = {
            day: [e["time_display"] for e in entries[day]]
            for day in (date(2026, 7, 6), date(2026, 7, 7), date(2026, 7, 8))
        }

    assert shown == {
        date(2026, 7, 6): ["7:00 AM"],
        date(2026, 7, 7): ["All-day"],
        date(2026, 7, 8): ["3:00 PM"],
    }


def test_arctic_entries_are_absent_for_a_user_who_may_not_see_them(app, make_person):
    viewer(make_person, "cms_arctic_pc")
    make_person(username="cms_arctic_opr")
    with app.app_context():
        creator = person_id("cms_arctic_pc")
        add_event(
            creator,
            "Arctic drill",
            datetime(2026, 7, 8, 8, 0),
            datetime(2026, 7, 8, 17, 0),
            calendar=Calendar.ARCTIC,
        )
        pc = db.session.query(Person).filter_by(username="cms_arctic_pc").one()
        opr = db.session.query(Person).filter_by(username="cms_arctic_opr").one()
        pc_entries = build_month_context(pc, "2026-07")["day_entries"][WEDNESDAY]
        opr_entries = build_month_context(opr, "2026-07")["day_entries"][WEDNESDAY]

    # The panel is filtered by the same server-side rule as the bars — the
    # toggle is cosmetic, never the boundary.
    assert [e["cal_key"] for e in pc_entries] == ["arctic"]
    assert opr_entries == []


def test_a_person_with_two_approved_requests_lists_once(app, make_person):
    viewer(make_person, "cms_dedupe_pc")
    make_person(username="cms_dedupe_guy", platoon=1)
    with app.app_context():
        add_leave("cms_dedupe_guy", WEDNESDAY)
        add_leave("cms_dedupe_guy", WEDNESDAY)
        user = db.session.query(Person).filter_by(username="cms_dedupe_pc").one()
        entries = build_month_context(user, "2026-07")["day_entries"][WEDNESDAY]

    # Same dedupe as the bars: the panel shows people, not rows.
    assert len(entries) == 1
