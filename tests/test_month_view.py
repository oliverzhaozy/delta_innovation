import re
from datetime import date

from app.domain.dates import today_sgt
from app.domain.types import Appointment, DayPart, LeaveType, Rank, RequestStatus
from app.extensions import db
from app.models import Event, LeaveRequest, Person
from app.services import presence_service
from tests.conftest import login


def make_pc(username="mv_pc"):
    return dict(username=username, rank=Rank.TWO_LT, appointment=Appointment.PC)


def create_event(client, calendar, title, start, end):
    return client.post(
        "/calendar/new",
        data={"calendar": calendar, "title": title, "start_dt": start, "end_dt": end, "notes": ""},
        follow_redirects=True,
    )


def event_id_for(app, title):
    with app.app_context():
        return db.session.query(Event.id).filter_by(title=title).scalar()


def plant_leave(app, username, day, status=RequestStatus.APPROVED, end=None):
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(
            LeaveRequest(
                person_id=pid, type=LeaveType.OFF, start_date=day, end_date=end or day,
                day_part=DayPart.FULL, status=status,
            )
        )
        db.session.commit()


# ---------- Criterion 1: a 3-day TP event is ONE bar spanning its 3 cells ----------

def test_three_day_event_is_one_spanning_bar_and_links_to_detail(app, client, make_person):
    # UI-23: Mon 6 - Wed 8 Jul 2026 all sit on the same week row, so the event
    # is a single bar spanning 3 columns — not one chip per day.
    login(client, make_person(**make_pc()))
    create_event(client, "TP", "Field camp", "2026-07-06T08:00", "2026-07-08T17:00")
    event_id = event_id_for(app, "Field camp")

    resp = client.get("/calendar/month?ym=2026-07")
    assert resp.status_code == 200
    link = f'href="/calendar/{event_id}"'.encode()
    assert resp.data.count(link) == 1
    assert b"grid-column: 1 / span 3" in resp.data


def test_event_crossing_a_week_boundary_gets_one_bar_per_week(app, client, make_person):
    # Mon 6 - Wed 15 Jul 2026 covers the 6-12 and 13-19 week rows: two bars, and
    # each carries a continuation cue on the side that runs off its row.
    login(client, make_person(**make_pc("mv_pc_span")))
    create_event(client, "TP", "Long ops", "2026-07-06T08:00", "2026-07-15T17:00")
    event_id = event_id_for(app, "Long ops")

    resp = client.get("/calendar/month?ym=2026-07")
    assert resp.status_code == 200
    assert resp.data.count(f'href="/calendar/{event_id}"'.encode()) == 2
    assert b"clip-r" in resp.data and b"clip-l" in resp.data


# ---------- Criterion 2: ARCTIC chips gated by can_view_arctic ----------

def test_arctic_chip_hidden_from_opr_but_visible_to_command_team(app, client, make_person):
    login(client, make_person(**make_pc("mv_pc2")))
    create_event(client, "ARCTIC", "Arctic drill", "2026-07-06T08:00", "2026-07-06T17:00")
    client.post("/logout")

    login(client, make_person(username="mv_opr"))
    resp = client.get("/calendar/month?ym=2026-07")
    assert resp.status_code == 200
    assert b"Arctic drill" not in resp.data
    client.post("/logout")

    login(client, make_person(**make_pc("mv_pc3")))
    resp = client.get("/calendar/month?ym=2026-07")
    assert b"Arctic drill" in resp.data


# ---------- Criterion 3: NSF OFF/LEAVE name chips from the derivation ----------

def test_day_with_approved_leave_shows_an_nsf_off_leave_name_chip(app, client, make_person):
    make_person(username="mv_leave_guy", platoon=1)  # NSF by default
    login(client, make_person(username="mv_viewer"))
    plant_leave(app, "mv_leave_guy", date(2026, 7, 8))

    resp = client.get("/calendar/month?ym=2026-07")
    assert resp.status_code == 200
    # A violet OFF/LEAVE chip naming the person, not a generic away count.
    assert resp.data.count(b"chip cal-off") == 1
    assert b"PTE Mv Leave Guy OFF" in resp.data


def test_two_overlapping_requests_for_same_person_show_one_chip(app, client, make_person):
    # Overlaps are soft-warned, never blocked — the same person can hold two
    # APPROVED requests covering one day. The cell shows people, not rows:
    # the NSF OFF/LEAVE layer dedupes on person_id.
    make_person(username="mv_double_guy", platoon=1)
    login(client, make_person(username="mv_double_viewer"))
    plant_leave(app, "mv_double_guy", date(2026, 7, 8))
    plant_leave(app, "mv_double_guy", date(2026, 7, 8))

    resp = client.get("/calendar/month?ym=2026-07")
    assert resp.status_code == 200
    assert resp.data.count(b"chip cal-off") == 1


def test_four_contiguous_off_days_are_one_spanning_bar(app, client, make_person):
    # UI-23: consecutive days with the same person + label + day-part merge into
    # ONE run, so Mon 6 - Thu 9 Jul 2026 draws a single 4-column bar.
    make_person(username="mv_run_guy", platoon=1)
    login(client, make_person(username="mv_run_viewer"))
    plant_leave(app, "mv_run_guy", date(2026, 7, 6), end=date(2026, 7, 9))

    resp = client.get("/calendar/month?ym=2026-07")
    assert resp.status_code == 200
    assert resp.data.count(b"chip cal-off") == 1
    assert b"grid-column: 1 / span 4" in resp.data


def test_the_run_past_the_lane_cap_collapses_into_a_per_day_more_chip(app, client, make_person):
    # UI-24: one cap of TOTAL_LANE_LIMIT lanes covers the whole week stack, so
    # with no events in the week the sixth concurrent OFF run is the one dropped
    # from the bars and counted into that day's "+N more" chip instead.
    for n in range(6):
        make_person(username=f"mv_cap_{n}", platoon=1)
        plant_leave(app, f"mv_cap_{n}", date(2026, 7, 8))
    login(client, make_person(username="mv_cap_viewer"))

    resp = client.get("/calendar/month?ym=2026-07")
    assert resp.status_code == 200
    assert b"+1 more" in resp.data
    # 5 name bars + the "+1 more" chip, which carries the same cal-off class.
    assert resp.data.count(b"chip cal-off") == 6


def test_off_chip_sits_flush_under_its_own_days_events(app, client, make_person):
    # Wed 8 Jul stacks three events (rows 2-4) but Thu 9 has only one (row 2):
    # Thu's OFF chip floors under ITS day's events (row 3), not under the
    # week's tallest stack — no phantom gap rows in the quiet cell.
    make_person(username="mv_flush_guy", platoon=1)
    login(client, make_person(**make_pc("mv_flush_pc")))
    for n in range(3):
        create_event(client, "TP", f"Wed thing {n}", "2026-07-08T08:00", "2026-07-08T17:00")
    create_event(client, "TP", "Thu thing", "2026-07-09T08:00", "2026-07-09T17:00")
    plant_leave(app, "mv_flush_guy", date(2026, 7, 9))

    resp = client.get("/calendar/month?ym=2026-07")
    assert resp.status_code == 200
    assert b'cal-off" style="grid-column: 4 / span 1; grid-row: 3"' in resp.data


def placements_by_text(html):
    """Every bar's `grid-column …; grid-row …` string, keyed by its visible text.

    A title crossing week rows draws one bar per row, so the values are lists.
    """
    found = {}
    for style, text in re.findall(r'style="(grid-[^"]+)"[^>]*>([^<]*)</(?:a|span)>', html):
        found.setdefault(text.strip(), []).append(style)
    return found


def test_single_day_bars_stack_flush_under_a_full_week_bar(app, client, make_person):
    # Regression pin for the gap the owner screenshotted (Mon 10 - Sun 16 Aug
    # 2026): a full-week bar, a Tue-Sun bar, two Mon-only events and one Mon-only
    # OFF run. Monday's lane 1 is free — the Tue-Sun bar starts in column 2 — so
    # the Mon-only entries take rows 3, 4 and 5 with no empty row above them.
    make_person(username="mv_hole_guy", platoon=1)
    login(client, make_person(**make_pc("mv_hole_pc")))
    create_event(client, "TP", "LX - CTC", "2026-08-06T08:00", "2026-08-17T17:00")
    create_event(client, "TP", "BRONCO COURSE", "2026-08-11T08:00", "2026-08-21T17:00")
    create_event(client, "TP", "CSM Technet", "2026-08-15T08:00", "2026-08-16T17:00")
    create_event(client, "TP", "CDSO", "2026-08-15T08:00", "2026-08-15T17:00")
    create_event(client, "TP", "National Day", "2026-08-10T00:00", "2026-08-10T23:59")
    create_event(client, "TP", "Wolf PT", "2026-08-10T08:00", "2026-08-10T17:00")
    plant_leave(app, "mv_hole_guy", date(2026, 8, 10))

    resp = client.get("/calendar/month?ym=2026-08")
    assert resp.status_code == 200
    placements = placements_by_text(resp.data.decode())
    assert "grid-column: 1 / span 7; grid-row: 2" in placements["LX - CTC"]
    assert "grid-column: 2 / span 6; grid-row: 3" in placements["BRONCO COURSE"]
    assert placements["National Day"] == ["grid-column: 1 / span 1; grid-row: 3"]
    assert placements["Wolf PT"] == ["grid-column: 1 / span 1; grid-row: 4"]
    assert placements["PTE Mv Hole Guy OFF"] == ["grid-column: 1 / span 1; grid-row: 5"]


def test_regular_leave_is_not_in_the_nsf_off_leave_layer(app, client, make_person):
    from app.domain.types import Service

    make_person(username="mv_reg_guy", platoon=1, service=Service.REGULAR)
    login(client, make_person(username="mv_reg_viewer"))
    plant_leave(app, "mv_reg_guy", date(2026, 7, 8))

    resp = client.get("/calendar/month?ym=2026-07")
    assert resp.status_code == 200
    assert b"chip cal-off" not in resp.data  # NSF-only layer


# ---------- Criterion 4: absences_on still delegates correctly ----------

def test_absences_on_matches_absences_between_single_day(app, make_person):
    make_person(username="mv_delegate_guy", platoon=2)
    day = date(2026, 7, 9)
    plant_leave(app, "mv_delegate_guy", day)
    with app.app_context():
        on_result = presence_service.absences_on(day)
        between_result = presence_service.absences_between(day, day)[day]
        assert [r.id for r in on_result] == [r.id for r in between_result]
        assert len(on_result) == 1


# ---------- Criterion 5: event spanning a month boundary ----------

def test_event_spanning_month_boundary_appears_in_both_months(app, client, make_person):
    login(client, make_person(**make_pc("mv_pc4")))
    create_event(client, "TP", "Boundary op", "2026-07-30T08:00", "2026-08-02T17:00")
    event_id = event_id_for(app, "Boundary op")
    link = f'href="/calendar/{event_id}"'.encode()

    # Each month draws its own bar, clipped at the month edge: July shows one
    # spanning Thu 30 - Fri 31, August one spanning Sat 1 - Sun 2 (same week row).
    july_resp = client.get("/calendar/month?ym=2026-07")
    assert july_resp.data.count(link) == 1

    august_resp = client.get("/calendar/month?ym=2026-08")
    assert august_resp.data.count(link) == 1


# ---------- Criterion 6: default month, ?ym= nav, malformed ?ym=, prev/next/Today ----------

def test_default_month_is_current_month(client, make_person):
    login(client, make_person(username="mv_default_viewer"))
    resp = client.get("/calendar/month")
    assert resp.status_code == 200
    assert today_sgt().strftime("%B %Y").encode() in resp.data


def test_ym_param_navigates_to_requested_month(client, make_person):
    login(client, make_person(username="mv_nav_viewer"))
    resp = client.get("/calendar/month?ym=2026-07")
    assert resp.status_code == 200
    assert b"July 2026" in resp.data


def test_malformed_ym_falls_back_to_today(client, make_person):
    # The parade morning page's ?date= convention falls back to today rather
    # than 404ing; this route mirrors that (the brief's default guess of 404
    # doesn't match the sibling route it told us to check against).
    login(client, make_person(username="mv_bad_ym_viewer"))
    resp = client.get("/calendar/month?ym=garbage")
    assert resp.status_code == 200
    assert today_sgt().strftime("%B %Y").encode() in resp.data


def test_prev_next_today_links_present(client, make_person):
    login(client, make_person(username="mv_links_viewer"))
    resp = client.get("/calendar/month?ym=2026-07")
    assert b"ym=2026-06" in resp.data
    assert b"ym=2026-08" in resp.data
    assert b"Today" in resp.data


def test_day_number_is_plain_text_with_no_parade_destination(client, make_person):
    # P9.2: the archive is gone and the parade pages are today-fixed, so no past
    # date has a parade destination — the day number is plain text, not a link.
    login(client, make_person(username="mv_dayno_viewer"))
    resp = client.get("/calendar/month?ym=2026-07")
    assert b'<span class="day-num">8</span>' in resp.data
    assert b"/parade/history" not in resp.data
    assert b"/parade/morning?date=" not in resp.data
