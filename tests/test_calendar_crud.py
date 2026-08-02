from datetime import datetime

from app.domain.types import Appointment, ParticipantCategory, Rank
from app.extensions import db
from app.models import Event, EventParticipant
from tests.conftest import login

START = "2026-08-01T08:00"
END = "2026-08-01T17:00"


def make_pc(username="cal_pc"):
    return dict(username=username, rank=Rank.TWO_LT, appointment=Appointment.PC)


def create_event(client, calendar, title="Range clearance", start=START, end=END, notes="",
                 all_day=False, label=None):
    data = {"calendar": calendar, "title": title, "start_dt": start, "end_dt": end, "notes": notes}
    if all_day:
        data["all_day"] = "y"  # checkbox present => True; omitted => False
    if label is not None:
        data["label"] = label
    return client.post("/calendar/new", data=data, follow_redirects=True)


def event_id_for(app, title):
    with app.app_context():
        return db.session.query(Event.id).filter_by(title=title).scalar()


# ---------- Criterion 1: Opr sees TP only, 403 everywhere else ----------

def test_opr_lists_tp_but_forbidden_on_arctic_and_all_mutating_urls(app, client, make_person):
    login(client, make_person(**make_pc("cal_pc1")))
    create_event(client, "ARCTIC", title="Arctic secret drill")
    arctic_id = event_id_for(app, "Arctic secret drill")
    client.post("/logout")

    login(client, make_person(username="cal_opr"))
    assert client.get("/calendar/tp").status_code == 200
    assert client.get("/calendar/arctic").status_code == 403
    assert client.get(f"/calendar/{arctic_id}").status_code == 403
    assert client.get("/calendar/new").status_code == 403
    assert create_event(client, "TP", title="Opr sneaky create").status_code == 403
    assert client.get(f"/calendar/{arctic_id}/edit").status_code == 403
    assert client.post(
        f"/calendar/{arctic_id}/edit",
        data={"calendar": "ARCTIC", "title": "hacked", "start_dt": START, "end_dt": END, "notes": ""},
    ).status_code == 403
    assert client.post(f"/calendar/{arctic_id}/delete").status_code == 403


# ---------- Criterion 5: anonymous redirected to login everywhere ----------

def test_anonymous_redirected_to_login_on_every_calendar_url(app, client, make_person):
    login(client, make_person(**make_pc("cal_pc2")))
    create_event(client, "TP", title="Anon target")
    event_id = event_id_for(app, "Anon target")
    client.post("/logout")

    for url, method in [
        ("/calendar/tp", "get"),
        ("/calendar/arctic", "get"),
        (f"/calendar/{event_id}", "get"),
        ("/calendar/new", "get"),
        (f"/calendar/{event_id}/edit", "get"),
        (f"/calendar/{event_id}/delete", "post"),
    ]:
        resp = getattr(client, method)(url, follow_redirects=False)
        assert resp.status_code == 302, url
        assert "/login" in resp.headers["Location"], url


# ---------- Criterion 2: command team creates TP and ARCTIC, each in its own list ----------

def test_pc_creates_tp_and_arctic_events_each_in_their_own_list(client, make_person):
    login(client, make_person(**make_pc()))
    resp = create_event(client, "TP", title="TP Field Exercise")
    assert resp.status_code == 200
    assert b"Event created" in resp.data

    resp = create_event(client, "ARCTIC", title="Arctic Foe Op")
    assert resp.status_code == 200
    assert b"Event created" in resp.data

    tp_body = client.get("/calendar/tp").data
    assert b"TP Field Exercise" in tp_body
    assert b"Arctic Foe Op" not in tp_body

    arctic_body = client.get("/calendar/arctic").data
    assert b"Arctic Foe Op" in arctic_body
    assert b"TP Field Exercise" not in arctic_body


# ---------- Criterion 3: edit persists; delete removes event + participants ----------

def test_edit_changes_persist(app, client, make_person):
    login(client, make_person(**make_pc()))
    create_event(client, "TP", title="Before edit")
    event_id = event_id_for(app, "Before edit")

    resp = client.post(
        f"/calendar/{event_id}/edit",
        data={
            "calendar": "TP",
            "title": "After edit",
            "start_dt": START,
            "end_dt": "2026-08-01T18:00",
            "notes": "updated notes",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"After edit" in resp.data

    with app.app_context():
        row = db.session.get(Event, event_id)
        assert row.title == "After edit"
        assert row.notes == "updated notes"
        assert row.end_dt == datetime(2026, 8, 1, 18, 0)


def test_delete_removes_event_and_its_participant_rows(app, client, make_person):
    login(client, make_person(**make_pc()))
    create_event(client, "TP", title="To be deleted")
    event_id = event_id_for(app, "To be deleted")

    with app.app_context():
        db.session.add(EventParticipant(event_id=event_id, category=ParticipantCategory.NSF))
        db.session.commit()
        assert db.session.query(EventParticipant).filter_by(event_id=event_id).count() == 1

    resp = client.post(f"/calendar/{event_id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert b"To be deleted" not in client.get("/calendar/tp").data

    with app.app_context():
        assert db.session.get(Event, event_id) is None
        assert db.session.query(EventParticipant).filter_by(event_id=event_id).count() == 0


# ---------- Criterion 4: end_dt <= start_dt rejected by the form ----------

def test_new_rejects_end_dt_before_start_dt(app, client, make_person):
    login(client, make_person(**make_pc()))
    resp = create_event(client, "TP", title="Bad range", start=END, end=START)
    assert resp.status_code == 200
    assert b"after" in resp.data.lower()
    with app.app_context():
        assert db.session.query(Event).filter_by(title="Bad range").count() == 0


def test_new_rejects_end_dt_equal_start_dt(app, client, make_person):
    login(client, make_person(**make_pc()))
    resp = create_event(client, "TP", title="Zero length", start=START, end=START)
    assert resp.status_code == 200
    assert b"after" in resp.data.lower()
    with app.app_context():
        assert db.session.query(Event).filter_by(title="Zero length").count() == 0


# ---------- Criterion 6: month-view ARCTIC link is live for command team ----------

def test_month_view_arctic_link_is_live_for_command_team(client, make_person):
    login(client, make_person(**make_pc()))
    body = client.get("/calendar/month").data
    assert b'href="/calendar/arctic"' in body
    assert b"ARCTIC FOE" in body


def test_month_view_hides_arctic_link_for_non_command_team(client, make_person):
    login(client, make_person(username="cal_opr2"))
    body = client.get("/calendar/month").data
    assert b"ARCTIC FOE" not in body


def test_month_view_layer_toggles_are_rights_gated(client, make_person):
    # The filter pills moved off Home with the grid (UI-25). TP and NSF
    # OFF/LEAVE are everyone's; the ARCTIC pill follows the chips it hides, so
    # only the command team gets it — the toggle is never the boundary itself.
    login(client, make_person(username="cal_opr_toggle"))
    body = client.get("/calendar/month").data
    assert b'data-cal-toggle="tp"' in body
    assert b'data-cal-toggle="off"' in body
    assert b'data-cal-toggle="arctic"' not in body
    client.post("/logout")

    login(client, make_person(**make_pc("cal_pc_toggle")))
    body = client.get("/calendar/month").data
    assert b'data-cal-toggle="tp"' in body
    assert b'data-cal-toggle="off"' in body
    assert b'data-cal-toggle="arctic"' in body


# ---------- UI-9: all-day, labels, toolbar ----------

def test_all_day_event_stored_from_midnight_to_end_of_day(app, client, make_person):
    login(client, make_person(**make_pc()))
    resp = create_event(
        client, "TP", title="All day drill",
        start="2026-08-05T09:30", end="2026-08-05T14:00", all_day=True,
    )
    assert resp.status_code == 200
    assert b"Event created" in resp.data
    with app.app_context():
        row = db.session.query(Event).filter_by(title="All day drill").one()
        assert row.all_day is True
        # Time normalized regardless of what the user typed: 00:00 -> end of day,
        # single day still satisfies end_dt > start_dt.
        assert row.start_dt == datetime(2026, 8, 5, 0, 0)
        assert row.end_dt == datetime(2026, 8, 5, 23, 59, 59, 999999)


def test_valid_label_is_stored_and_chip_carries_its_colour_class(app, client, make_person):
    login(client, make_person(**make_pc()))
    create_event(client, "TP", title="PT session", label="PT")
    with app.app_context():
        assert db.session.query(Event).filter_by(title="PT session").one().label == "PT"
    # The event is in Aug 2026 — navigate there, not the default current month.
    body = client.get("/calendar/month?ym=2026-08").data
    assert b"ev-tp-pt" in body       # label colour class on the chip
    assert b"PT session" in body


def test_cross_calendar_label_is_rejected_and_not_persisted(app, client, make_person):
    login(client, make_person(**make_pc()))
    resp = create_event(client, "TP", title="Bad label", label="Conducts")  # ARCTIC label on TP
    assert resp.status_code == 200
    assert b"available for this calendar" in resp.data
    with app.app_context():
        assert db.session.query(Event).filter_by(title="Bad label").count() == 0


def test_event_without_a_label_is_allowed(app, client, make_person):
    login(client, make_person(**make_pc()))
    resp = create_event(client, "TP", title="No label event", label="")
    assert resp.status_code == 200
    assert b"Event created" in resp.data
    with app.app_context():
        assert db.session.query(Event).filter_by(title="No label event").one().label is None


def test_edit_sets_all_day_and_label(app, client, make_person):
    login(client, make_person(**make_pc()))
    create_event(client, "ARCTIC", title="Edit me arctic")
    event_id = event_id_for(app, "Edit me arctic")

    resp = client.post(
        f"/calendar/{event_id}/edit",
        data={
            "calendar": "ARCTIC", "title": "Edit me arctic",
            "start_dt": "2026-08-02T10:00", "end_dt": "2026-08-02T12:00",
            "all_day": "y", "label": "Conducts", "notes": "",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        row = db.session.get(Event, event_id)
        assert row.all_day is True
        assert row.label == "Conducts"
        assert row.start_dt == datetime(2026, 8, 2, 0, 0)
        assert row.end_dt == datetime(2026, 8, 2, 23, 59, 59, 999999)


def test_new_event_form_renders_with_label_select_and_map(client, make_person):
    login(client, make_person(**make_pc()))
    resp = client.get("/calendar/new")
    assert resp.status_code == 200
    assert b'id="label"' in resp.data
    assert b'id="all_day"' in resp.data
    # The value->calendar map embeds cleanly in the single-quoted data attribute.
    assert b"data-label-calendars" in resp.data
    assert b"Conducts" in resp.data  # an ARCTIC label option is present


def test_toolbar_shows_nav_and_create_for_editor(client, make_person):
    login(client, make_person(**make_pc()))
    body = client.get("/calendar/month").data
    assert b"Today" in body
    assert b"cal-step" in body       # prev/next chevrons
    assert b"+ New event" in body


def test_toolbar_hides_create_for_non_editor(client, make_person):
    login(client, make_person(username="cal_opr_tb"))
    body = client.get("/calendar/month").data
    assert b"Today" in body
    assert b"+ New event" not in body


def test_new_event_form_prefills_the_clicked_date(client, make_person):
    login(client, make_person(**make_pc()))
    resp = client.get("/calendar/new?date=2026-08-15")
    assert resp.status_code == 200
    assert b'value="2026-08-15T08:00"' in resp.data  # start seeded to that day
    assert b'value="2026-08-15T09:00"' in resp.data  # end default (+1h)


def test_new_event_form_ignores_a_bad_date_param(client, make_person):
    login(client, make_person(**make_pc()))
    resp = client.get("/calendar/new?date=not-a-date")
    assert resp.status_code == 200  # falls through to a blank form, no crash
    assert b'value="not-a-date"' not in resp.data


def test_month_grid_shows_day_add_link_for_editor(client, make_person):
    login(client, make_person(**make_pc()))
    body = client.get("/calendar/month?ym=2026-08").data
    assert b"day-add" in body
    assert b"/calendar/new?date=2026-08-15" in body


def test_month_grid_hides_day_add_for_non_editor(client, make_person):
    login(client, make_person(username="cal_opr_dayadd"))
    body = client.get("/calendar/month?ym=2026-08").data
    assert b"day-add" not in body
