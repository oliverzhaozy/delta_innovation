import re
from datetime import datetime

from app.domain.types import Appointment, Calendar, ParticipantCategory, Rank, Service
from app.extensions import db
from app.models import Event, EventParticipant, Person
from app.services import event_service
from tests.conftest import login

START = "2026-08-01T08:00"
END = "2026-08-01T17:00"


def make_pc(username="epu_pc"):
    return dict(username=username, rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=1)


def create_event(client, categories=None, people=None,
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
    if people:
        data["people"] = people
    return client.post("/calendar/new", data=data, follow_redirects=True)


def event_id_for(app, title):
    with app.app_context():
        return db.session.query(Event.id).filter_by(title=title).scalar()


def participant_count(app, event_id):
    with app.app_context():
        return db.session.query(EventParticipant).filter_by(event_id=event_id).count()


def category_values(app, event_id):
    with app.app_context():
        rows = db.session.query(EventParticipant).filter_by(event_id=event_id).all()
        return {r.category.value for r in rows if r.category is not None}


def person_ids(app, event_id):
    with app.app_context():
        rows = db.session.query(EventParticipant).filter_by(event_id=event_id).all()
        return {r.person_id for r in rows if r.person_id is not None}


def resolved_row(rank, name):
    # The resolved-list markup (<li><span>RANK Name</span></li>) is distinct
    # from the chips markup, so this pins the assertion to "is this person in
    # the *resolved* list" rather than "does this string appear anywhere on
    # the page" — a legacy-except name legitimately still appears as a "- Name"
    # chip even though it's not resolved.
    return f"<li><span>{rank} {name}</span></li>"


def tag_is_checked(body, value):
    # WTForms/html_params ordering isn't guaranteed, and we hand-render the
    # inputs, so match the whole <input> tag by its value= and look for
    # "checked" inside it rather than assuming attribute order.
    match = re.search(rf'<input[^>]*value="{value}"[^>]*>', body)
    assert match, f"no input tag with value={value!r} found"
    return "checked" in match.group(0)


def group_block(body, category_value):
    # The slice of a single group's <details> block, from its category
    # checkbox to the block's close — used to assert intra-group order and
    # that a person shows up under more than one group.
    start = body.index(f'value="{category_value}"')
    end = body.index("</details>", start)
    return body[start:end]


# ---------- Category + person-include resolves exactly, with an "N people" count ----------

def test_creates_event_with_category_and_include_shows_resolved_names(app, client, make_person):
    login(client, make_person(**make_pc()))
    make_person(username="p2_a", display_name="Alice P2", rank=Rank.CPL, platoon=2, service=Service.NSF)
    make_person(username="p2_b", display_name="Bob P2", rank=Rank.PTE, platoon=2, service=Service.NSF)
    make_person(username="p1_y", display_name="Yusuf P1", rank=Rank.PTE, platoon=1, service=Service.NSF)

    with app.app_context():
        y_id = db.session.query(Person.id).filter_by(username="p1_y").scalar()

    resp = create_event(
        client,
        title="Platoon 2 briefing",
        categories=[ParticipantCategory.PLATOON_2.value],
        people=[str(y_id)],
    )
    assert resp.status_code == 200
    body = resp.data.decode()

    assert resolved_row("CPL", "Alice P2") in body  # platoon-2 member
    assert resolved_row("PTE", "Bob P2") in body  # platoon-2 member
    assert resolved_row("PTE", "Yusuf P1") in body  # carved in from another platoon
    assert "3 people" in body  # Alice + Bob + Yusuf


# ---------- Crafted duplicate person id -> one row, no 500 ----------

def test_duplicate_person_id_is_deduped_to_one_row(app, client, make_person):
    """The picker renders a person in both their service and platoon group, so a
    no-JS user can legitimately tick them twice; a hand-built POST can too. Two
    identical ids must dedupe to one row rather than 500 on
    uq_participant_event_person."""
    login(client, make_person(**make_pc()))
    make_person(username="p2_dupinc", display_name="Dup Include", rank=Rank.PTE, platoon=2)
    with app.app_context():
        dup_id = db.session.query(Person.id).filter_by(username="p2_dupinc").scalar()

    resp = create_event(
        client,
        title="Dup include event",
        people=[str(dup_id), str(dup_id)],  # crafted duplicate
    )
    assert resp.status_code == 200  # saved, no IntegrityError 500
    event_id = event_id_for(app, "Dup include event")
    assert event_id is not None
    assert participant_count(app, event_id) == 1  # one row, not two


# ---------- Editing replaces rows wholesale, no duplicates across two edits ----------

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
            "people": [str(w_id)],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert participant_count(app, event_id) == 2  # 1 category + 1 person, not accumulated
    body = resp.data.decode()
    assert resolved_row("PTE", "Zed P2") in body
    assert resolved_row("PTE", "Wren P3") in body

    # Second edit: drop everything down to a single person include.
    resp = client.post(
        f"/calendar/{event_id}/edit",
        data={
            "calendar": "TP",
            "title": "Edit target",
            "start_dt": START,
            "end_dt": END,
            "notes": "",
            "people": [str(z_id)],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert participant_count(app, event_id) == 1
    body = resp.data.decode()
    assert resolved_row("PTE", "Zed P2") in body  # the only person now
    assert "Wren P3" not in body  # no row references them at all (detail has no picker)
    assert "1 person" in body


# ---------- New form: ALL choice, five group dropdowns, people inputs, no legacy fields ----------

def test_new_form_renders_category_checkboxes_with_no_exclude_control(client, make_person):
    login(client, make_person(**make_pc()))
    resp = client.get("/calendar/new")
    assert resp.status_code == 200
    body = resp.data.decode()

    assert 'value="ALL"' in body  # the "All (everyone)" pseudo-choice
    for category in ParticipantCategory:
        assert f'value="{category.value}"' in body
    assert body.count('<details class="picker"') == 5  # NSF, REGULAR, PLATOON_1..3
    assert 'name="people"' in body
    assert 'type="checkbox"' in body

    # The old "Also include"/"Except" person fields are gone: the only input
    # name ending in "people" is the unified "people" field.
    people_fields = {n for n in re.findall(r'name="([a-z_]+)"', body) if n.endswith("people")}
    assert people_fields == {"people"}
    assert "exclude" not in body.lower()


# ---------- Edit form prepopulates category + person selections (checked state) ----------

def test_edit_form_prepopulates_existing_participant_selections(app, client, make_person):
    login(client, make_person(**make_pc()))
    make_person(username="p1_pre", display_name="Preset Person", rank=Rank.PTE, platoon=1)
    with app.app_context():
        pre_id = db.session.query(Person.id).filter_by(username="p1_pre").scalar()

    create_event(
        client,
        title="Prepop test",
        categories=[ParticipantCategory.REGULAR.value],
        people=[str(pre_id)],
    )
    event_id = event_id_for(app, "Prepop test")

    resp = client.get(f"/calendar/{event_id}/edit")
    assert resp.status_code == 200
    body = resp.data.decode()

    assert tag_is_checked(body, ParticipantCategory.REGULAR.value)
    assert tag_is_checked(body, pre_id)


# ---------- "All (everyone)" saves NSF + REGULAR category rows ----------

def test_all_checkbox_saves_nsf_and_regular_rows(app, client, make_person):
    login(client, make_person(**make_pc()))
    resp = create_event(client, title="Whole company", categories=["ALL"])
    assert resp.status_code == 200
    event_id = event_id_for(app, "Whole company")
    assert category_values(app, event_id) == {
        ParticipantCategory.NSF.value,
        ParticipantCategory.REGULAR.value,
    }
    assert person_ids(app, event_id) == set()


# ---------- ALL + overlapping category/person selections dedupe (no 500) ----------

def test_all_plus_overlapping_selections_deduped(app, client, make_person):
    login(client, make_person(**make_pc()))
    make_person(username="p1_cov", display_name="Covered P1", rank=Rank.PTE, platoon=1, service=Service.NSF)
    with app.app_context():
        cov_id = db.session.query(Person.id).filter_by(username="p1_cov").scalar()

    resp = create_event(
        client,
        title="All plus overlap",
        categories=["ALL", ParticipantCategory.NSF.value, ParticipantCategory.PLATOON_1.value],
        people=[str(cov_id)],
    )
    assert resp.status_code == 200  # ALL+NSF would 500 on uq_participant_event_category without the set()
    event_id = event_id_for(app, "All plus overlap")
    assert category_values(app, event_id) == {
        ParticipantCategory.NSF.value,
        ParticipantCategory.REGULAR.value,
        ParticipantCategory.PLATOON_1.value,
    }
    assert person_ids(app, event_id) == {cov_id}
    assert participant_count(app, event_id) == 4  # 3 categories + 1 person


# ---------- Crafted duplicate category value -> one row, no 500 ----------

def test_duplicate_category_value_deduped_to_one_row(app, client, make_person):
    login(client, make_person(**make_pc()))
    resp = create_event(
        client,
        title="Dup category event",
        categories=[ParticipantCategory.NSF.value, ParticipantCategory.NSF.value],
    )
    assert resp.status_code == 200  # no IntegrityError 500 on uq_participant_event_category
    event_id = event_id_for(app, "Dup category event")
    assert category_values(app, event_id) == {ParticipantCategory.NSF.value}
    assert participant_count(app, event_id) == 1


# ---------- Edit collapses stored NSF+REGULAR back to "ALL" and round-trips ----------

def test_edit_collapses_nsf_regular_to_all_and_round_trips(app, client, make_person):
    login(client, make_person(**make_pc()))
    create_event(
        client,
        title="Collapse test",
        categories=[ParticipantCategory.NSF.value, ParticipantCategory.REGULAR.value],
    )
    event_id = event_id_for(app, "Collapse test")

    # Edit GET: NSF+REGULAR collapses to a checked ALL, with NSF/REGULAR shown unchecked.
    body = client.get(f"/calendar/{event_id}/edit").data.decode()
    assert tag_is_checked(body, "ALL")
    assert not tag_is_checked(body, ParticipantCategory.NSF.value)
    assert not tag_is_checked(body, ParticipantCategory.REGULAR.value)

    # Save the collapsed form (ALL only) -> the stored rows stay NSF+REGULAR.
    resp = client.post(
        f"/calendar/{event_id}/edit",
        data={
            "calendar": "TP",
            "title": "Collapse test",
            "start_dt": START,
            "end_dt": END,
            "notes": "",
            "categories": ["ALL"],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert category_values(app, event_id) == {
        ParticipantCategory.NSF.value,
        ParticipantCategory.REGULAR.value,
    }

    # Round-trip stable: a second edit GET still collapses to a checked ALL.
    body = client.get(f"/calendar/{event_id}/edit").data.decode()
    assert tag_is_checked(body, "ALL")


# ---------- The roster fetch every people list inherits is parade-ordered ----------

def test_active_roster_is_parade_ordered_not_platoon_or_alphabetical(app, make_person):
    # UI-22: `active_roster` is THE order for every roster-derived list (picker,
    # duty pools, manning candidates, dropdowns). The cast breaks all three of
    # the orderings it replaced: 2IC displays above SM on parade but below it in
    # the declaration APPOINTMENT_ORDER, 3WO is hoisted above LTA on parade but
    # not in the legal RANK_ORDER, and the names alphabetize in reverse.
    make_person(username="ar_2ic", display_name="Zed Two", rank=Rank.LTA,
                appointment=Appointment.TWO_IC, platoon=None, service=Service.REGULAR)
    make_person(username="ar_sm", display_name="Yan Sm", rank=Rank.THREE_WO,
                appointment=Appointment.SM, platoon=None, service=Service.REGULAR)
    make_person(username="ar_p2ic_wo", display_name="Bee P2ic", rank=Rank.THREE_WO,
                appointment=Appointment.P2IC, platoon=1)
    make_person(username="ar_p2ic_lta", display_name="Ace P2ic", rank=Rank.LTA,
                appointment=Appointment.P2IC, platoon=2)
    # The OC also pins that the roster is unfiltered since decision (dd): every
    # person row is serving, and the OC's appointment sorts them to the top.
    make_person(username="ar_oc", display_name="Aaa Oc", rank=Rank.CPT,
                appointment=Appointment.OC, platoon=None)

    with app.app_context():
        assert [p.username for p in event_service.active_roster()] == [
            "ar_oc", "ar_2ic", "ar_sm", "ar_p2ic_wo", "ar_p2ic_lta",
        ]


# ---------- Group members ordered by appointment then rank, never alphabetical ----------

def test_group_members_ordered_by_appointment_then_rank(app, client, make_person):
    login(client, make_person(**make_pc()))
    # Names deliberately alphabetize opposite to the appointment order
    # (PC < PS < OPR per the parade sequence).
    make_person(username="p2_opr", display_name="Aaa Opr", rank=Rank.PTE,
                appointment=Appointment.OPR, platoon=2)
    make_person(username="p2_pc", display_name="Mmm Pc", rank=Rank.LTA,
                appointment=Appointment.PC, platoon=2)
    make_person(username="p2_ps", display_name="Zzz Ps", rank=Rank.TWO_SG,
                appointment=Appointment.PS, platoon=2)
    with app.app_context():
        opr_id = db.session.query(Person.id).filter_by(username="p2_opr").scalar()
        pc_id = db.session.query(Person.id).filter_by(username="p2_pc").scalar()
        ps_id = db.session.query(Person.id).filter_by(username="p2_ps").scalar()

    body = client.get("/calendar/new").data.decode()
    block = group_block(body, ParticipantCategory.PLATOON_2.value)
    pc_at = block.index(f'value="{pc_id}"')
    ps_at = block.index(f'value="{ps_id}"')
    opr_at = block.index(f'value="{opr_id}"')
    assert pc_at < ps_at < opr_at  # appointment order, not alphabetical (Aaa/Mmm/Zzz)


# ---------- A person appears in both service and platoon group; double-check saves one row ----------

def test_person_appears_in_service_and_platoon_group_and_double_check_saves_one_row(app, client, make_person):
    login(client, make_person(**make_pc()))
    make_person(username="p1_dual", display_name="Dora Dual", rank=Rank.PTE, platoon=1, service=Service.NSF)
    with app.app_context():
        dual_id = db.session.query(Person.id).filter_by(username="p1_dual").scalar()

    body = client.get("/calendar/new").data.decode()
    # Rendered under both NSF (service) and PLATOON_1 (platoon).
    assert f'value="{dual_id}"' in group_block(body, ParticipantCategory.NSF.value)
    assert f'value="{dual_id}"' in group_block(body, ParticipantCategory.PLATOON_1.value)

    # A no-JS user ticking both boxes posts the id twice -> one row.
    resp = create_event(client, title="Double check", people=[str(dual_id), str(dual_id)])
    assert resp.status_code == 200
    event_id = event_id_for(app, "Double check")
    assert participant_count(app, event_id) == 1
    assert person_ids(app, event_id) == {dual_id}


# ---------- An id outside the roster is a clean form error, nothing saved ----------

def test_invalid_people_id_rejected_as_form_error(app, client, make_person):
    login(client, make_person(**make_pc()))
    make_person(username="p2_real", display_name="Real P2", rank=Rank.PTE, platoon=2)
    with app.app_context():
        # No deactivated people exist any more (decision (dd)), so "outside the
        # roster" means an id belonging to nobody at all.
        ghost_id = db.session.query(db.func.max(Person.id)).scalar() + 999

    resp = create_event(client, title="Ghost event", people=[str(ghost_id)])
    assert resp.status_code == 200
    assert b"People:" in resp.data  # the field's error line rendered, no 500
    with app.app_context():
        assert db.session.query(Event).filter_by(title="Ghost event").count() == 0


# ---------- Legacy person-except rows warn on edit and are dropped on save ----------

def test_legacy_except_rows_drop_on_save(app, client, make_person):
    login(client, make_person(**make_pc()))
    make_person(username="p2_leg", display_name="Legacy Ex", rank=Rank.PTE, platoon=2)
    with app.app_context():
        pc_id = db.session.query(Person.id).filter_by(username="epu_pc").scalar()
        ex_id = db.session.query(Person.id).filter_by(username="p2_leg").scalar()
        event = Event(
            calendar=Calendar.TP,
            title="Legacy except event",
            start_dt=datetime(2026, 8, 1, 8, 0),
            end_dt=datetime(2026, 8, 1, 17, 0),
            all_day=False,
            created_by_id=pc_id,
        )
        event.participants = [
            EventParticipant(category=ParticipantCategory.PLATOON_2, include=True),
            EventParticipant(person_id=ex_id, include=False),  # legacy exclude row
        ]
        db.session.add(event)
        db.session.commit()
        event_id = event.id

    # Edit GET renders without a legacy-exclusions warning (owner 2026-08-02:
    # the note was removed; the drop-on-save behavior below is unchanged).
    body = client.get(f"/calendar/{event_id}/edit").data.decode()
    assert "saving will drop them" not in body

    # Detail before save still shows the "- Legacy Ex" chip and excludes them.
    body = client.get(f"/calendar/{event_id}").data.decode()
    assert "&minus; Legacy Ex" in body
    assert resolved_row("PTE", "Legacy Ex") not in body

    # Save (unchanged category, no people): the exclude row is dropped.
    resp = client.post(
        f"/calendar/{event_id}/edit",
        data={
            "calendar": "TP",
            "title": "Legacy except event",
            "start_dt": START,
            "end_dt": END,
            "notes": "",
            "categories": [ParticipantCategory.PLATOON_2.value],
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "&minus; Legacy Ex" not in body  # chip gone
    assert resolved_row("PTE", "Legacy Ex") in body  # now resolved via the category
    assert person_ids(app, event_id) == set()  # no person rows remain
    assert category_values(app, event_id) == {ParticipantCategory.PLATOON_2.value}
