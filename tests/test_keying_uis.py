"""P3a.5: status keying UI and rights.

PS/S3/admin key statuses (MC/other). Rights (policy.can_key_parade), the 3-way
in-camp resolution, end-today, and optional remarks are all pinned here against
the morning parade state so a keyed row's effect is asserted through the SAME
derivation the rest of the app reads (never a second check — presence_service is
the only thing that decides "away").

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
    ParadeVariant,
    Rank,
    Service,
    StatusType,
)
from app.extensions import db
from app.models import Person, StatusEntry
from app.services import parade_service
from tests.conftest import login

TODAY = today_sgt()
TOMORROW = TODAY + timedelta(days=1)
YESTERDAY = TODAY - timedelta(days=1)


def pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def key_status(client, person_id, type_="MC", start=None, end=None, day_part="FULL",
                in_camp="DEFAULT", remarks="flu"):
    start = start or TODAY
    end = end or start
    data = {
        "person_id": str(person_id),
        "type": type_,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "day_part": day_part,
        "in_camp": in_camp,
    }
    if remarks is not None:
        data["remarks"] = remarks
    return client.post("/parade/statuses/new", data=data, follow_redirects=True)


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
    # the duty-granted path is pinned in test_duty_rights.py.
    assert policy.can_key_parade(_person(Appointment.PS), is_cos_of_day=False)
    assert policy.can_key_parade(
        _person(Appointment.OPR, company_role=CompanyRole.S3), is_cos_of_day=False
    )
    assert policy.can_key_parade(_person(Appointment.OPR, is_admin=True), is_cos_of_day=False)
    assert not policy.can_key_parade(_person(Appointment.OPR), is_cos_of_day=False)
    assert not policy.can_key_parade(_person(Appointment.OC), is_cos_of_day=False)


# --- criterion 1: PS keys an MC -> list + morning parade (derivation, not a second write) --

def test_ps_keys_mc_appears_in_list_and_morning_parade(app, client, make_person):
    make_person(username="c1_ps", appointment=Appointment.PS)
    make_person(username="c1_opr", display_name="Mc Target")
    login(client, "c1_ps")

    key_status(client, pid(app, "c1_opr"), type_="MC", remarks="fever")

    list_resp = client.get("/parade/statuses")
    assert list_resp.status_code == 200
    assert b"PTE Mc Target" in list_resp.data
    assert b"MC" in list_resp.data

    morning = client.get("/parade/morning").data
    absent = morning.split(b"NOT PRESENT IN CAMP")[1]
    assert b"PTE MC TARGET" in absent  # in the MC category, uppercased
    assert b"MC (1):" in morning
    with app.app_context():
        assert db.session.query(StatusEntry).count() == 1


def test_statuses_list_is_parade_ordered_not_date_or_alphabetical(app, client, make_person):
    # UI-22: person-major parade order (appointment, then rank), so a keyer finds
    # a person's rows together. The Opr's row starts earlier AND alphabetizes
    # first — under the old start_date order (or any alphabetical one) it would
    # lead; on parade the PS does.
    make_person(username="ord_keyer", appointment=Appointment.PS)
    make_person(username="ord_zps", display_name="Zed Ps", rank=Rank.TWO_SG,
                appointment=Appointment.PS, platoon=2)
    make_person(username="ord_aopr", display_name="Ann Opr", rank=Rank.PTE,
                appointment=Appointment.OPR, platoon=1)
    plant_status(app, "ord_aopr", start=YESTERDAY, end=TOMORROW)
    plant_status(app, "ord_zps", start=TODAY, end=TOMORROW)
    login(client, "ord_keyer")

    body = client.get("/parade/statuses").get_data(as_text=True)
    assert body.index("2SG Zed Ps") < body.index("PTE Ann Opr")


def test_status_form_offers_no_course_option(app, client, make_person):
    # P9.5: ON COURSE has exactly one source — a TP calendar event labelled
    # "Course". The keying form's choices are an enum comprehension over
    # StatusType, so a regrown COURSE member would show up here immediately.
    make_person(username="c1b_ps", appointment=Appointment.PS)
    login(client, "c1b_ps")

    form = client.get("/parade/statuses/new").data
    assert b'value="MC"' in form
    assert b'value="OTHER"' in form
    assert b'value="COURSE"' not in form
    assert b"On course" not in form


# --- criterion 2: Opr 403s on every status URL ------------------------------

def test_opr_403_on_every_status_url(app, client, make_person):
    make_person(username="c2_opr")
    entry_id = plant_status(app, "c2_opr")
    login(client, "c2_opr")

    for method, url in [
        ("get", "/parade/statuses"),
        ("get", "/parade/statuses/new"),
        ("post", "/parade/statuses/new"),
        ("get", f"/parade/statuses/{entry_id}/edit"),
        ("post", f"/parade/statuses/{entry_id}/edit"),
        ("post", f"/parade/statuses/{entry_id}/end-today"),
    ]:
        resp = getattr(client, method)(url)
        assert resp.status_code == 403, f"{method} {url} -> {resp.status_code}"


# --- criterion 3: a keyed status moves a REGULAR off current strength -------

def test_s3_keys_status_for_oc_shows_absent_on_morning(app, client, make_person):
    # Regulars have no in-app leave (P9.3 — ARCTIC FOE owns that); a keyed
    # out-of-camp status is the only thing that takes one off the parade, and it
    # is asserted through the same derivation as everyone else.
    make_person(username="c3_s3", company_role="S3")
    make_person(username="c3_oc", display_name="The Boss", rank=Rank.CPT,
                appointment=Appointment.OC, platoon=None, service=Service.REGULAR)
    login(client, "c3_s3")

    key_status(client, pid(app, "c3_oc"), type_="OTHER", in_camp="OUT", remarks="away")

    morning = client.get("/parade/morning").data
    absent = morning.split(b"NOT PRESENT IN CAMP")[1]
    assert b"CPT THE BOSS" in absent  # an out-of-camp OTHER lands in OTHERS
    assert b"OTHERS (1):" in morning
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


# --- criterion 4: 3-way in-camp resolution --------------------------------

def test_in_camp_default_resolves_per_type_and_morning_respects_it(app, client, make_person):
    make_person(username="c4_ps", appointment=Appointment.PS)
    make_person(username="c4_brief_default", display_name="Brief Default")
    make_person(username="c4_brief_out", display_name="Brief Out")
    make_person(username="c4_mc_default", display_name="Mc Default")
    login(client, "c4_ps")

    key_status(client, pid(app, "c4_brief_default"), type_="OTHER", in_camp="IN")
    key_status(client, pid(app, "c4_brief_out"), type_="OTHER", in_camp="OUT")
    key_status(client, pid(app, "c4_mc_default"), type_="MC", in_camp="DEFAULT")

    with app.app_context():
        rows = {
            r.person.username: r.in_camp
            for r in db.session.query(StatusEntry).join(Person, StatusEntry.person_id == Person.id)
        }
        assert rows["c4_brief_default"] is True
        assert rows["c4_brief_out"] is False
        assert rows["c4_mc_default"] is False

    morning = client.get("/parade/morning").data
    # Split the parade DOCUMENT (the <pre>), not the whole page: page chrome
    # outside the document can echo the same names, so a present-in-camp person
    # would otherwise leak into the "absent" half.
    doc_text = morning.split(b'id="paradetext"')[1].split(b">", 1)[1].split(b"</pre>")[0]
    present, absent = (
        doc_text.split(b"NOT PRESENT IN CAMP")[0],
        doc_text.split(b"NOT PRESENT IN CAMP")[1],
    )
    # OTHER+IN (an in-camp briefing, keyed explicitly since UI-21 removed the
    # BRIEFING type) -> OTHERS IN CAMP, under PRESENT IN CAMP, never absent.
    # (reason is the keyer's remark "flu", uppercased by _in_camp_reason.)
    assert b"OTHERS IN CAMP (1):" in morning
    assert b"PTE BRIEF DEFAULT (FLU)" in present
    assert b"PTE BRIEF DEFAULT" not in absent
    # OTHER+OUT and MC+DEFAULT -> out of camp -> the NOT PRESENT IN CAMP half.
    assert b"PTE BRIEF OUT" in absent
    assert b"PTE MC DEFAULT" in absent


# --- criterion 5: end-today ------------------------------------------------

def test_end_today_ends_ongoing_mc_stays_today_gone_tomorrow(app, client, make_person):
    make_person(username="c5_ps", appointment=Appointment.PS)
    make_person(username="c5_mc", display_name="Ongoing Mc")
    entry_id = plant_status(app, "c5_mc", type_=StatusType.MC, start=YESTERDAY,
                             end=TODAY + timedelta(days=5), in_camp=False)
    login(client, "c5_ps")

    resp = client.post(f"/parade/statuses/{entry_id}/end-today", follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        row = db.session.get(StatusEntry, entry_id)
        assert row.end_date == TODAY

    today_absent = client.get("/parade/morning").data.split(b"NOT PRESENT IN CAMP")[1]
    assert b"PTE ONGOING MC" in today_absent  # still absent (MC) today

    # The live page is today-only now, so tomorrow's derivation is asserted
    # through the same build_doc pipeline the page renders (page↔pipeline
    # equality is pinned by test_doc_builder). Gone tomorrow — back present.
    with app.app_context():
        tomorrow_absent = parade_service.build_doc(
            TOMORROW, ParadeVariant.MORNING
        ).text.split("NOT PRESENT IN CAMP")[1]
    assert "PTE ONGOING MC" not in tomorrow_absent


def test_end_today_on_future_entry_errors_and_leaves_unchanged(app, client, make_person):
    make_person(username="c5b_ps", appointment=Appointment.PS)
    make_person(username="c5b_future")
    future_start, future_end = TOMORROW, TOMORROW + timedelta(days=3)
    entry_id = plant_status(app, "c5b_future", type_=StatusType.OTHER, start=future_start,
                             end=future_end, in_camp=False)
    login(client, "c5b_ps")

    resp = client.post(f"/parade/statuses/{entry_id}/end-today", follow_redirects=True)
    assert resp.status_code == 200
    assert b"only entries covering today" in resp.data.lower()

    with app.app_context():
        row = db.session.get(StatusEntry, entry_id)
        assert row.start_date == future_start
        assert row.end_date == future_end


# --- criterion 6: remarks are optional for a status ------------------------

def test_remarks_optional_for_status(app, client, make_person):
    make_person(username="c6_ps", appointment=Appointment.PS)
    make_person(username="c6_target")

    login(client, "c6_ps")
    resp = key_status(client, pid(app, "c6_target"), type_="MC", remarks="")
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.query(StatusEntry).filter_by(remarks=None).count() == 1


# --- edit prefill: in_camp shows the explicit stored value, never DEFAULT --

def test_edit_status_prefill_in_camp_is_explicit_not_default(app, client, make_person):
    make_person(username="c7_ps", appointment=Appointment.PS)
    make_person(username="c7_target")
    entry_id = plant_status(app, "c7_target", type_=StatusType.OTHER, in_camp=True)
    login(client, "c7_ps")

    resp = client.get(f"/parade/statuses/{entry_id}/edit")
    assert resp.status_code == 200
    # WTForms' Select widget renders selected options as `<option selected value="...">`
    # (attrs sorted alphabetically) — pin the actual order rather than guess it.
    assert b'<option selected value="IN">' in resp.data
    assert b'<option selected value="DEFAULT">' not in resp.data


# --- nav gating --------------------------------------------------------------

def test_nav_gates_the_statuses_link(app, client, make_person):
    make_person(username="c8_ps", appointment=Appointment.PS)
    make_person(username="c8_s3", company_role="S3")
    make_person(username="c8_opr")

    login(client, "c8_ps")
    assert b'href="/parade/statuses"' in client.get("/").data
    client.post("/logout")

    login(client, "c8_s3")
    assert b'href="/parade/statuses"' in client.get("/").data
    client.post("/logout")

    login(client, "c8_opr")
    assert b'href="/parade/statuses"' not in client.get("/").data
