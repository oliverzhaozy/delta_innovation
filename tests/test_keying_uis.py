"""P3a.5: status + direct-absence keying UIs and rights.

PS/S3/admin key statuses (MC/course/briefing/...); S3/admin key direct
absences for regulars. Rights (policy.can_key_parade / can_key_direct_absence),
the 3-way in-camp resolution, end-today, and remarks-required-for-direct-
absence are all pinned here against the morning parade state so a keyed row's
effect is asserted through the SAME derivation the rest of the app reads (never
a second check — presence_service is the only thing that decides "away").

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
    DirectAbsenceType,
    Service,
    StatusType,
)
from app.extensions import db
from app.models import DirectAbsence, Person, StatusEntry
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


def key_direct(client, person_id, type_="LEAVE", start=None, end=None, day_part="FULL",
               remarks="posting"):
    start = start or TODAY
    end = end or start
    data = {
        "person_id": str(person_id),
        "type": type_,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "day_part": day_part,
    }
    if remarks is not None:
        data["remarks"] = remarks
    return client.post("/parade/direct-absences/new", data=data, follow_redirects=True)


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


def plant_direct(app, username, type_=DirectAbsenceType.LEAVE, start=TODAY, end=TODAY,
                  remarks="posting"):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        row = DirectAbsence(person_id=person_id, type=type_, start_date=start, end_date=end,
                             remarks=remarks, created_by_id=person_id)
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


def test_can_key_direct_absence_is_s3_or_admin_only():
    assert policy.can_key_direct_absence(_person(Appointment.OPR, company_role=CompanyRole.S3))
    assert policy.can_key_direct_absence(_person(Appointment.OPR, is_admin=True))
    assert not policy.can_key_direct_absence(_person(Appointment.PS))  # PS keys parade, not direct absences
    assert not policy.can_key_direct_absence(_person(Appointment.OPR))


# --- criterion 1: PS keys an MC -> list + morning parade (derivation, not a second write) --

def test_ps_keys_mc_appears_in_list_and_morning_parade(app, client, make_person):
    make_person(username="c1_ps", appointment=Appointment.PS)
    make_person(username="c1_opr", display_name="PTE Mc Target")
    login(client, "c1_ps")

    key_status(client, pid(app, "c1_opr"), type_="MC", remarks="fever")

    list_resp = client.get("/parade/statuses")
    assert list_resp.status_code == 200
    assert b"PTE Mc Target" in list_resp.data
    assert b"MC" in list_resp.data

    morning = client.get(f"/parade/morning?date={TODAY.isoformat()}").data
    absent = morning.split(b"NOT PRESENT IN CAMP")[1]
    assert b"PTE MC TARGET" in absent  # in the MC category, uppercased
    assert b"MC (1):" in morning
    with app.app_context():
        assert db.session.query(StatusEntry).count() == 1


# --- criterion 2: Opr 403s everywhere; PS 403s on every direct-absence URL --

def test_opr_403_on_every_status_and_direct_absence_url(app, client, make_person):
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
        ("get", "/parade/direct-absences"),
        ("get", "/parade/direct-absences/new"),
        ("post", "/parade/direct-absences/new"),
        ("get", f"/parade/direct-absences/{entry_id}/edit"),
        ("post", f"/parade/direct-absences/{entry_id}/edit"),
        ("post", f"/parade/direct-absences/{entry_id}/end-today"),
    ]:
        resp = getattr(client, method)(url)
        assert resp.status_code == 403, f"{method} {url} -> {resp.status_code}"


def test_ps_403_on_all_direct_absence_urls(app, client, make_person):
    make_person(username="c2_ps", appointment=Appointment.PS)
    make_person(username="c2_da_target", appointment=Appointment.OC, platoon=None,
                service=Service.REGULAR)
    entry_id = plant_direct(app, "c2_da_target")
    login(client, "c2_ps")

    for method, url in [
        ("get", "/parade/direct-absences"),
        ("get", "/parade/direct-absences/new"),
        ("post", "/parade/direct-absences/new"),
        ("get", f"/parade/direct-absences/{entry_id}/edit"),
        ("post", f"/parade/direct-absences/{entry_id}/edit"),
        ("post", f"/parade/direct-absences/{entry_id}/end-today"),
    ]:
        resp = getattr(client, method)(url)
        assert resp.status_code == 403, f"{method} {url} -> {resp.status_code}"


# --- criterion 3: S3 keys the OC's absence; NSF rejected with a form error --

def test_s3_keys_direct_absence_for_oc_shows_leave_on_morning(app, client, make_person):
    make_person(username="c3_s3", company_role="S3")
    make_person(username="c3_oc", display_name="CPT The Boss", appointment=Appointment.OC,
                platoon=None, service=Service.REGULAR)
    login(client, "c3_s3")

    key_direct(client, pid(app, "c3_oc"), type_="LEAVE", remarks="on leave")

    morning = client.get(f"/parade/morning?date={TODAY.isoformat()}").data
    absent = morning.split(b"NOT PRESENT IN CAMP")[1]
    assert b"CPT THE BOSS" in absent  # a direct LEAVE lands in the LEAVE category
    assert b"LEAVE (1):" in morning
    with app.app_context():
        assert db.session.query(DirectAbsence).count() == 1


def test_s3_direct_absence_for_nsf_rejected_form_error_nothing_saved(app, client, make_person):
    make_person(username="c3_s3b", company_role="S3")
    make_person(username="c3_nsf", service=Service.NSF)
    login(client, "c3_s3b")

    resp = key_direct(client, pid(app, "c3_nsf"), remarks="attempt")
    assert resp.status_code == 200  # re-rendered form, not a redirect
    assert b"Not a valid choice" in resp.data
    with app.app_context():
        assert db.session.query(DirectAbsence).count() == 0


# --- criterion 4: 3-way in-camp resolution --------------------------------

def test_in_camp_default_resolves_per_type_and_morning_respects_it(app, client, make_person):
    make_person(username="c4_ps", appointment=Appointment.PS)
    make_person(username="c4_brief_default", display_name="PTE Brief Default")
    make_person(username="c4_brief_out", display_name="PTE Brief Out")
    make_person(username="c4_mc_default", display_name="PTE Mc Default")
    login(client, "c4_ps")

    key_status(client, pid(app, "c4_brief_default"), type_="BRIEFING", in_camp="DEFAULT")
    key_status(client, pid(app, "c4_brief_out"), type_="BRIEFING", in_camp="OUT")
    key_status(client, pid(app, "c4_mc_default"), type_="MC", in_camp="DEFAULT")

    with app.app_context():
        rows = {
            r.person.username: r.in_camp
            for r in db.session.query(StatusEntry).join(Person, StatusEntry.person_id == Person.id)
        }
        assert rows["c4_brief_default"] is True
        assert rows["c4_brief_out"] is False
        assert rows["c4_mc_default"] is False

    morning = client.get(f"/parade/morning?date={TODAY.isoformat()}").data
    present, absent = (
        morning.split(b"NOT PRESENT IN CAMP")[0],
        morning.split(b"NOT PRESENT IN CAMP")[1],
    )
    # BRIEFING+DEFAULT -> in camp -> OTHERS IN CAMP, under PRESENT IN CAMP, never absent.
    # (reason is the keyer's remark "flu", uppercased by _in_camp_reason.)
    assert b"OTHERS IN CAMP (1):" in morning
    assert b"PTE BRIEF DEFAULT (FLU)" in present
    assert b"PTE BRIEF DEFAULT" not in absent
    # BRIEFING+OUT and MC+DEFAULT -> out of camp -> the NOT PRESENT IN CAMP half.
    assert b"PTE BRIEF OUT" in absent
    assert b"PTE MC DEFAULT" in absent


# --- criterion 5: end-today ------------------------------------------------

def test_end_today_ends_ongoing_mc_stays_today_gone_tomorrow(app, client, make_person):
    make_person(username="c5_ps", appointment=Appointment.PS)
    make_person(username="c5_mc", display_name="PTE Ongoing Mc")
    entry_id = plant_status(app, "c5_mc", type_=StatusType.MC, start=YESTERDAY,
                             end=TODAY + timedelta(days=5), in_camp=False)
    login(client, "c5_ps")

    resp = client.post(f"/parade/statuses/{entry_id}/end-today", follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        row = db.session.get(StatusEntry, entry_id)
        assert row.end_date == TODAY

    today_absent = client.get(
        f"/parade/morning?date={TODAY.isoformat()}"
    ).data.split(b"NOT PRESENT IN CAMP")[1]
    assert b"PTE ONGOING MC" in today_absent  # still absent (MC) today

    tomorrow_absent = client.get(
        f"/parade/morning?date={TOMORROW.isoformat()}"
    ).data.split(b"NOT PRESENT IN CAMP")[1]
    # Gone from tomorrow's derivation — back present, no longer in the absent half.
    assert b"PTE ONGOING MC" not in tomorrow_absent


def test_end_today_on_future_entry_errors_and_leaves_unchanged(app, client, make_person):
    make_person(username="c5b_ps", appointment=Appointment.PS)
    make_person(username="c5b_future")
    future_start, future_end = TOMORROW, TOMORROW + timedelta(days=3)
    entry_id = plant_status(app, "c5b_future", type_=StatusType.COURSE, start=future_start,
                             end=future_end, in_camp=False)
    login(client, "c5b_ps")

    resp = client.post(f"/parade/statuses/{entry_id}/end-today", follow_redirects=True)
    assert resp.status_code == 200
    assert b"only entries covering today" in resp.data.lower()

    with app.app_context():
        row = db.session.get(StatusEntry, entry_id)
        assert row.start_date == future_start
        assert row.end_date == future_end


def test_end_today_symmetry_on_direct_absence(app, client, make_person):
    make_person(username="c5c_s3", company_role="S3")
    make_person(username="c5c_reg", display_name="2IC Ongoing", appointment=Appointment.TWO_IC,
                platoon=None, service=Service.REGULAR)
    entry_id = plant_direct(app, "c5c_reg", start=YESTERDAY, end=TODAY + timedelta(days=2))
    login(client, "c5c_s3")

    resp = client.post(f"/parade/direct-absences/{entry_id}/end-today", follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        row = db.session.get(DirectAbsence, entry_id)
        assert row.end_date == TODAY


# --- criterion 6: remarks required for direct absences, optional for statuses --

def test_remarks_optional_for_status_but_required_for_direct_absence(app, client, make_person):
    make_person(username="c6_ps", appointment=Appointment.PS)
    make_person(username="c6_s3", company_role="S3")
    make_person(username="c6_target")
    make_person(username="c6_reg", appointment=Appointment.OC, platoon=None,
                service=Service.REGULAR)

    login(client, "c6_ps")
    resp = key_status(client, pid(app, "c6_target"), type_="MC", remarks="")
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.query(StatusEntry).filter_by(remarks=None).count() == 1
    client.post("/logout")

    login(client, "c6_s3")
    resp2 = key_direct(client, pid(app, "c6_reg"), remarks="")
    assert resp2.status_code == 200
    with app.app_context():
        assert db.session.query(DirectAbsence).count() == 0


# --- edit prefill: in_camp shows the explicit stored value, never DEFAULT --

def test_edit_status_prefill_in_camp_is_explicit_not_default(app, client, make_person):
    make_person(username="c7_ps", appointment=Appointment.PS)
    make_person(username="c7_target")
    entry_id = plant_status(app, "c7_target", type_=StatusType.BRIEFING, in_camp=True)
    login(client, "c7_ps")

    resp = client.get(f"/parade/statuses/{entry_id}/edit")
    assert resp.status_code == 200
    # WTForms' Select widget renders selected options as `<option selected value="...">`
    # (attrs sorted alphabetically) — pin the actual order rather than guess it.
    assert b'<option selected value="IN">' in resp.data
    assert b'<option selected value="DEFAULT">' not in resp.data


# --- nav gating --------------------------------------------------------------

def test_nav_gates_statuses_and_direct_absence_links(app, client, make_person):
    make_person(username="c8_ps", appointment=Appointment.PS)
    make_person(username="c8_s3", company_role="S3")
    make_person(username="c8_opr")

    login(client, "c8_ps")
    ps_home = client.get("/").data
    assert b'href="/parade/statuses"' in ps_home
    assert b'href="/parade/direct-absences"' not in ps_home
    client.post("/logout")

    login(client, "c8_s3")
    s3_home = client.get("/").data
    assert b'href="/parade/direct-absences"' in s3_home
    client.post("/logout")

    login(client, "c8_opr")
    opr_home = client.get("/").data
    assert b'href="/parade/statuses"' not in opr_home
    assert b'href="/parade/direct-absences"' not in opr_home
