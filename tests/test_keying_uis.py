"""P3a.5, repurposed 2026-07-31: the Declare MC page and its rights.

MC is self-declared (owner decision 2026-07-31): everyone logged in reads the
whole list and writes only their own row, so the page carries no keying gate —
just an object-level own-row check on the two mutating routes. The declaration's
effect is pinned against the morning parade state so a declared row is asserted
through the SAME derivation the rest of the app reads (never a second check —
presence_service is the only thing that decides "away").

The morning document renders names uppercased (parade_line) and splits into a
PRESENT IN CAMP half and a NOT PRESENT IN CAMP half; an out-of-camp absence
lands in the latter, an in-camp status in OTHERS IN CAMP under the former.
"""
from datetime import timedelta
from types import SimpleNamespace

from app.domain import policy
from app.domain.dates import today_sgt
from app.domain.types import (
    Appointment,
    CompanyRole,
    DayPart,
    Rank,
    Service,
    StatusType,
)
from app.extensions import db
from app.models import Person, StatusEntry
from tests.conftest import login

TODAY = today_sgt()
TOMORROW = TODAY + timedelta(days=1)
YESTERDAY = TODAY - timedelta(days=1)


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def declare_mc(client, start=None, end=None, remarks="flu", **extra):
    """POST the declaration form. `extra` exists so a test can smuggle fields the
    form no longer has (person_id/type/...) and prove they are ignored."""
    start = start or TODAY
    end = end or start
    data = {"start_date": start.isoformat(), "end_date": end.isoformat()}
    if remarks is not None:
        data["remarks"] = remarks
    data.update(extra)
    return client.post("/parade/mc/new", data=data, follow_redirects=True)


def plant_status(app, username, type_=StatusType.MC, start=TODAY, end=TODAY,
                  day_part="FULL", in_camp=False, remarks=None):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        row = StatusEntry(person_id=person_id, type=type_, start_date=start, end_date=end,
                           day_part=day_part, in_camp=in_camp, remarks=remarks,
                           created_by_id=person_id)
        db.session.add(row)
        db.session.commit()
        return row.id


# --- policy predicates ------------------------------------------------------

def _person(appointment=Appointment.OPR, company_role=None, is_admin=False):
    return SimpleNamespace(appointment=appointment, company_role=company_role, is_admin=is_admin)


def test_can_key_parade_is_ps_s3_or_admin():
    # is_cos_of_day=False is the honest spelling of "no duty today" (P4.8);
    # the duty-granted path is pinned in test_duty_rights.py. This predicate no
    # longer gates the MC page, nor the drag overrides (open to every logged-in
    # user, 2026-07-31) — it still gates morning keying and the FP quick-add.
    assert policy.can_key_parade(_person(Appointment.PS), is_cos_of_day=False)
    assert policy.can_key_parade(
        _person(Appointment.OPR, company_role=CompanyRole.S3), is_cos_of_day=False
    )
    assert policy.can_key_parade(_person(Appointment.OPR, is_admin=True), is_cos_of_day=False)
    # Command team is admin by appointment (owner 2026-08-02), which deliberately
    # gives the OC the keying fallback it used to be denied.
    assert policy.can_key_parade(_person(Appointment.OC), is_cos_of_day=False)
    assert not policy.can_key_parade(_person(Appointment.OPR), is_cos_of_day=False)
    assert not policy.can_key_parade(_person(Appointment.DET_COMD), is_cos_of_day=False)


# --- criterion 1: an Opr declares their own MC -> list + morning parade ------

def test_declaring_mc_appears_in_list_and_morning_parade(app, client, make_person):
    make_person(username="c1_opr", display_name="Mc Target")
    login(client, "c1_opr")

    declare_mc(client, remarks="fever")

    list_resp = client.get("/parade/mc")
    assert list_resp.status_code == 200
    assert b"PTE Mc Target" in list_resp.data
    assert b"fever" in list_resp.data

    morning = client.get("/parade/morning").data
    absent = morning.split(b"NOT PRESENT IN CAMP")[1]
    assert b"PTE MC TARGET" in absent  # in the MC category, uppercased
    assert b"MC (1):" in morning
    with app.app_context():
        assert db.session.query(StatusEntry).count() == 1


def test_declaration_writes_mc_full_out_of_camp_for_the_declarer(app, client, make_person):
    # The three fields the form dropped are fixed server-side, not defaulted in
    # a widget — this pins the values the presence engine actually reads.
    make_person(username="c1b_opr")
    login(client, "c1b_opr")

    declare_mc(client, start=TODAY, end=TOMORROW, remarks="flu")

    with app.app_context():
        row = db.session.query(StatusEntry).one()
        assert row.person_id == pid(app, "c1b_opr")
        assert row.created_by_id == row.person_id
        assert row.type is StatusType.MC
        assert row.day_part is DayPart.FULL
        assert row.in_camp is False
        assert (row.start_date, row.end_date) == (TODAY, TOMORROW)


def test_posted_person_id_and_type_are_ignored(app, client, make_person):
    # Self-only is STRUCTURAL, not validated: there is no person field to reject,
    # so a smuggled person_id/type simply has nowhere to land.
    make_person(username="c1c_declarer")
    make_person(username="c1c_victim")
    login(client, "c1c_declarer")

    declare_mc(client, person_id=str(pid(app, "c1c_victim")), type="OTHER", in_camp="IN")

    with app.app_context():
        row = db.session.query(StatusEntry).one()
        assert row.person_id == pid(app, "c1c_declarer")
        assert row.type is StatusType.MC
        assert row.in_camp is False


def test_mc_list_is_parade_ordered_not_date_or_alphabetical(app, client, make_person):
    # UI-22: person-major parade order (appointment, then rank), so a reader finds
    # a person's rows together. The Opr's row starts earlier AND alphabetizes
    # first — under the old start_date order (or any alphabetical one) it would
    # lead; on parade the PS does.
    make_person(username="ord_reader", appointment=Appointment.PS)
    make_person(username="ord_zps", display_name="Zed Ps", rank=Rank.TWO_SG,
                appointment=Appointment.PS, platoon=2)
    make_person(username="ord_aopr", display_name="Ann Opr", rank=Rank.PTE,
                appointment=Appointment.OPR, platoon=1)
    plant_status(app, "ord_aopr", start=YESTERDAY, end=TOMORROW)
    plant_status(app, "ord_zps", start=TODAY, end=TOMORROW)
    login(client, "ord_reader")

    body = client.get("/parade/mc").get_data(as_text=True)
    assert body.index("2SG Zed Ps") < body.index("PTE Ann Opr")


def test_mc_form_asks_only_for_dates_and_remarks(app, client, make_person):
    # The type/day-part/in-camp/person selects are gone, which is also how P9.5's
    # rule ("ON COURSE has exactly one source — a TP event labelled Course")
    # is now structurally true here: there is no type choice left to regrow into.
    make_person(username="c1d_opr")
    login(client, "c1d_opr")

    form = client.get("/parade/mc/new").data
    assert b'name="start_date"' in form
    assert b'name="end_date"' in form
    assert b'name="remarks"' in form
    for absent_field in (b'name="person_id"', b'name="type"', b'name="day_part"',
                         b'name="in_camp"'):
        assert absent_field not in form, absent_field
    assert b'value="COURSE"' not in form
    assert b"On course" not in form


# --- criterion 2: everyone reads the page; only the owner writes their row ----

def test_opr_can_reach_every_mc_url(app, client, make_person):
    # The page carries no keying gate now — a plain Opr gets the list, the form,
    # and their own row's edit page.
    make_person(username="c2_opr")
    entry_id = plant_status(app, "c2_opr")
    login(client, "c2_opr")

    for url in ("/parade/mc", "/parade/mc/new", f"/parade/mc/{entry_id}/edit"):
        assert client.get(url).status_code == 200, url


def test_editing_someone_elses_mc_is_403(app, client, make_person):
    # FABLE-BEHAVIOR's object-level rule: being logged in proves who they are,
    # never that THIS row is theirs.
    make_person(username="c2b_owner", display_name="Row Owner")
    make_person(username="c2b_other")
    entry_id = plant_status(app, "c2b_owner", start=YESTERDAY, end=TOMORROW)
    login(client, "c2b_other")

    assert client.get(f"/parade/mc/{entry_id}/edit").status_code == 403
    assert client.post(f"/parade/mc/{entry_id}/edit", data={
        "start_date": TODAY.isoformat(), "end_date": TODAY.isoformat(), "remarks": "",
    }).status_code == 403

    with app.app_context():
        row = db.session.get(StatusEntry, entry_id)
        assert (row.start_date, row.end_date) == (YESTERDAY, TOMORROW)


def test_fp_quick_add_rows_are_not_addressable_as_mc(app, client, make_person):
    # An in-camp OTHER row belongs to the morning page's quick-add; the MC routes
    # 404 on it even for the person it names, so this page can never edit one.
    make_person(username="c2c_opr")
    entry_id = plant_status(app, "c2c_opr", type_=StatusType.OTHER, in_camp=True,
                             remarks="BDO")
    login(client, "c2c_opr")

    assert client.get(f"/parade/mc/{entry_id}/edit").status_code == 404


def test_list_shows_everyones_mcs_but_no_fp_other_rows(app, client, make_person):
    make_person(username="c2d_viewer", display_name="Just Viewer")
    make_person(username="c2d_sick", display_name="Sick Guy")
    make_person(username="c2d_fp", display_name="Fp Guy")
    plant_status(app, "c2d_sick", type_=StatusType.MC, remarks="fever")
    plant_status(app, "c2d_fp", type_=StatusType.OTHER, in_camp=True, remarks="BDO")
    login(client, "c2d_viewer")

    body = client.get("/parade/mc").get_data(as_text=True)
    assert "Sick Guy" in body          # someone else's MC is visible
    assert "Fp Guy" not in body        # an FP quick-add row is not an MC
    # The viewer owns neither row, so neither carries an edit link — the
    # template offers only what the routes would allow.
    assert "/edit" not in body


# --- criterion 3: a REGULAR's own MC takes them off current strength ---------

def test_regular_declares_own_mc_and_shows_absent_on_morning(app, client, make_person):
    # Regulars have no in-app leave (P9.3 — ARCTIC FOE owns that); a declared MC
    # is what takes one off the parade, asserted through the same derivation as
    # everyone else's.
    make_person(username="c3_oc", display_name="The Boss", rank=Rank.CPT,
                appointment=Appointment.OC, platoon=None, service=Service.REGULAR)
    login(client, "c3_oc")

    declare_mc(client, remarks="fever")

    morning = client.get("/parade/morning").data
    absent = morning.split(b"NOT PRESENT IN CAMP")[1]
    assert b"CPT THE BOSS" in absent
    assert b"MC (1):" in morning
    with app.app_context():
        assert db.session.query(StatusEntry).count() == 1


def test_regular_with_nothing_keyed_stays_in_current_strength(app, client, make_person):
    # The other half of the same rule: absent an in-app row, a regular is NOT
    # tracked as away — they appear on the morning parade like anyone else.
    make_person(username="c3_ps", appointment=Appointment.PS)
    make_person(username="c3_oc2", display_name="Present Boss", rank=Rank.CPT,
                appointment=Appointment.OC, platoon=None, service=Service.REGULAR)
    login(client, "c3_ps")

    morning = client.get("/parade/morning").data
    present = morning.split(b"NOT PRESENT IN CAMP")[0]
    assert b"CPT PRESENT BOSS" in present


# --- criterion 4: editing one's own declaration ------------------------------

def test_owner_edits_own_mc_dates(app, client, make_person):
    make_person(username="c4_opr", display_name="Edit Mine")
    entry_id = plant_status(app, "c4_opr", start=TODAY, end=TODAY, remarks="flu")
    login(client, "c4_opr")

    resp = client.post(f"/parade/mc/{entry_id}/edit", data={
        "start_date": TODAY.isoformat(), "end_date": TOMORROW.isoformat(),
        "remarks": "still flu",
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        row = db.session.get(StatusEntry, entry_id)
        assert row.end_date == TOMORROW
        assert row.remarks == "still flu"
        # The fixed shape survives an edit — there is no field that could move it.
        assert row.type is StatusType.MC
        assert row.day_part is DayPart.FULL
        assert row.in_camp is False


# --- criterion 6: remarks are optional --------------------------------------

def test_remarks_optional_for_mc(app, client, make_person):
    make_person(username="c6_target")

    login(client, "c6_target")
    resp = declare_mc(client, remarks="")
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.query(StatusEntry).filter_by(remarks=None).count() == 1


# --- nav ---------------------------------------------------------------------

def test_nav_shows_declare_mc_to_everyone(app, client, make_person):
    make_person(username="c8_ps", appointment=Appointment.PS)
    make_person(username="c8_opr")

    login(client, "c8_ps")
    assert b'href="/parade/mc"' in client.get("/").data
    client.post("/logout")

    # The whole point of the repurpose: an ordinary Opr, who can key nothing on
    # the parade pages, still gets the link.
    login(client, "c8_opr")
    assert b'href="/parade/mc"' in client.get("/").data
