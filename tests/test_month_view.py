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


def plant_leave(app, username, day, status=RequestStatus.APPROVED):
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(
            LeaveRequest(
                person_id=pid, type=LeaveType.OFF, start_date=day, end_date=day,
                day_part=DayPart.FULL, status=status,
            )
        )
        db.session.commit()


# ---------- Criterion 1: a 3-day TP event appears in exactly its 3 cells ----------

def test_three_day_event_appears_in_exactly_three_cells_and_links_to_detail(app, client, make_person):
    login(client, make_person(**make_pc()))
    create_event(client, "TP", "Field camp", "2026-07-06T08:00", "2026-07-08T17:00")
    event_id = event_id_for(app, "Field camp")

    resp = client.get("/calendar/month?ym=2026-07")
    assert resp.status_code == 200
    link = f'href="/calendar/{event_id}"'.encode()
    assert resp.data.count(link) == 3


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

    july_resp = client.get("/calendar/month?ym=2026-07")
    assert july_resp.data.count(link) == 2  # Jul 30, 31

    august_resp = client.get("/calendar/month?ym=2026-08")
    assert august_resp.data.count(link) == 2  # Aug 1, 2


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


def test_day_number_links_to_morning_parade(client, make_person):
    login(client, make_person(username="mv_dayno_viewer"))
    resp = client.get("/calendar/month?ym=2026-07")
    assert b"/parade/morning?date=2026-07-08" in resp.data
