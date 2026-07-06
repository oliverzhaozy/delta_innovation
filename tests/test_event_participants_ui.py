import re

from app.domain.types import Appointment, ParticipantCategory, Rank, Service
from app.extensions import db
from app.models import Event, EventParticipant, Person
from tests.conftest import login

START = "2026-08-01T08:00"
END = "2026-08-01T17:00"


def make_pc(username="epu_pc"):
    return dict(username=username, rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=1)


def create_event(client, categories=None, include_people=None, except_people=None,
                  title="Range clearance", start=START, end=END, notes="", calendar="TP"):
    data = {
        "calendar": calendar,
        "title": title,
        "start_dt": start,
        "end_dt": end,
        "notes": notes,
    }
    if categories:
        data["categories"] = categories
    if include_people:
        data["include_people"] = include_people
    if except_people:
        data["except_people"] = except_people
    return client.post("/calendar/new", data=data, follow_redirects=True)


def event_id_for(app, title):
    with app.app_context():
        return db.session.query(Event.id).filter_by(title=title).scalar()


def participant_count(app, event_id):
    with app.app_context():
        return db.session.query(EventParticipant).filter_by(event_id=event_id).count()


def resolved_row(rank, name):
    # The resolved-list markup (<li><span>RANK Name</span></li>) is distinct
    # from the chips markup, so this pins the assertion to "is this person in
    # the *resolved* list" rather than "does this string appear anywhere on
    # the page" — an excepted/except-chip name legitimately still appears in
    # the chips row (as a "- Name" tag) even though it's not resolved.
    return f"<li><span>{rank} {name}</span></li>"


# ---------- Criterion 1: category + except + also-include resolves exactly ----------

def test_creates_event_with_category_except_and_include_shows_resolved_names(app, client, make_person):
    login(client, make_person(**make_pc()))
    make_person(username="p2_a", display_name="Alice P2", rank=Rank.CPL, platoon=2, service=Service.NSF)
    make_person(username="p2_b", display_name="Bob P2", rank=Rank.PTE, platoon=2, service=Service.NSF)
    make_person(username="p1_y", display_name="Yusuf P1", rank=Rank.PTE, platoon=1, service=Service.NSF)

    with app.app_context():
        x_id = db.session.query(Person.id).filter_by(username="p2_a").scalar()
        y_id = db.session.query(Person.id).filter_by(username="p1_y").scalar()

    resp = create_event(
        client,
        title="Platoon 2 briefing",
        categories=[ParticipantCategory.PLATOON_2.value],
        except_people=[str(x_id)],
        include_people=[str(y_id)],
    )
    assert resp.status_code == 200
    body = resp.data.decode()

    assert resolved_row("PTE", "Bob P2") in body  # remaining platoon-2 member
    assert resolved_row("CPL", "Alice P2") not in body  # excepted out of the resolved list
    assert "&minus; Alice P2" in body  # ...but still shown as an "except" chip
    assert resolved_row("PTE", "Yusuf P1") in body  # carved in from another platoon
    assert "2 people" in body  # Bob + Yusuf


# ---------- Criterion 2: person in both include and except -> form error, nothing saved ----------

def test_person_in_both_include_and_except_rerenders_with_error(app, client, make_person):
    login(client, make_person(**make_pc()))
    make_person(username="p2_dup", display_name="Dup Person", rank=Rank.PTE, platoon=2)
    with app.app_context():
        dup_id = db.session.query(Person.id).filter_by(username="p2_dup").scalar()

    resp = create_event(
        client,
        title="Should not save",
        include_people=[str(dup_id)],
        except_people=[str(dup_id)],
    )
    assert resp.status_code == 200
    assert b"both" in resp.data.lower()

    with app.app_context():
        assert db.session.query(Event).filter_by(title="Should not save").count() == 0


# ---------- Criterion 3: editing replaces rows, no duplicates across two edits ----------

def test_editing_event_replaces_participant_rows_without_duplicates(app, client, make_person):
    login(client, make_person(**make_pc()))
    make_person(username="p2_z", display_name="Zed P2", rank=Rank.PTE, platoon=2)
    make_person(username="p3_w", display_name="Wren P3", rank=Rank.PTE, platoon=3)
    with app.app_context():
        z_id = db.session.query(Person.id).filter_by(username="p2_z").scalar()
        w_id = db.session.query(Person.id).filter_by(username="p3_w").scalar()

    create_event(client, title="Edit target", categories=[ParticipantCategory.NSF.value])
    event_id = event_id_for(app, "Edit target")
    assert participant_count(app, event_id) == 1

    # First edit: swap to a category + a person include.
    resp = client.post(
        f"/calendar/{event_id}/edit",
        data={
            "calendar": "TP",
            "title": "Edit target",
            "start_dt": START,
            "end_dt": END,
            "notes": "",
            "categories": [ParticipantCategory.PLATOON_2.value],
            "include_people": [str(w_id)],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert participant_count(app, event_id) == 2  # 1 category + 1 person, not accumulated
    body = resp.data.decode()
    assert resolved_row("PTE", "Zed P2") in body
    assert resolved_row("PTE", "Wren P3") in body

    # Second edit: drop everything down to a single except-person row.
    resp = client.post(
        f"/calendar/{event_id}/edit",
        data={
            "calendar": "TP",
            "title": "Edit target",
            "start_dt": START,
            "end_dt": END,
            "notes": "",
            "except_people": [str(z_id)],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert participant_count(app, event_id) == 1
    body = resp.data.decode()
    # Zed is now only an "except" row with no category to except from, so the
    # resolved list is empty — but the chip still names them (that's correct;
    # it's the resolved *list* that must drop them).
    assert resolved_row("PTE", "Zed P2") not in body
    assert "&minus; Zed P2" in body
    assert "Wren P3" not in body  # no row references them at all anymore
    assert "0 people" in body


# ---------- Criterion 4: inactive person in a tagged category is dropped ----------

def test_inactive_person_in_category_not_resolved(app, client, make_person):
    login(client, make_person(**make_pc()))
    make_person(username="p2_active", display_name="Active P2", rank=Rank.PTE, platoon=2)
    make_person(username="p2_gone", display_name="Gone P2", rank=Rank.PTE, platoon=2, is_active=False)

    resp = create_event(client, title="Roll call", categories=[ParticipantCategory.PLATOON_2.value])
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Active P2" in body
    assert "Gone P2" not in body


# ---------- Criterion 5: categories are checkboxes; no category-exclude control ----------

def test_new_form_renders_category_checkboxes_with_no_exclude_control(client, make_person):
    login(client, make_person(**make_pc()))
    resp = client.get("/calendar/new")
    assert resp.status_code == 200
    body = resp.data.decode()

    for category in ParticipantCategory:
        assert f'value="{category.value}"' in body

    assert 'type="checkbox"' in body
    assert "exclude" not in body.lower()


def test_edit_form_prepopulates_existing_participant_selections(app, client, make_person):
    login(client, make_person(**make_pc()))
    make_person(username="p1_pre", display_name="Preset Person", rank=Rank.PTE, platoon=1)
    with app.app_context():
        pre_id = db.session.query(Person.id).filter_by(username="p1_pre").scalar()

    create_event(
        client,
        title="Prepop test",
        categories=[ParticipantCategory.REGULAR.value],
        include_people=[str(pre_id)],
    )
    event_id = event_id_for(app, "Prepop test")

    resp = client.get(f"/calendar/{event_id}/edit")
    assert resp.status_code == 200
    body = resp.data.decode()

    def tag_is_checked(value):
        # WTForms' html_params sorts attributes alphabetically, so "checked"
        # can land anywhere in the tag relative to "value" — match the whole
        # <input> tag and look inside it instead of assuming an order.
        match = re.search(rf'<input[^>]*value="{value}"[^>]*>', body)
        assert match, f"no input tag with value={value!r} found"
        return "checked" in match.group(0)

    assert tag_is_checked(ParticipantCategory.REGULAR.value)
    assert tag_is_checked(pre_id)
