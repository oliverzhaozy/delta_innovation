"""P3a.4: presence_service v2 — the single derivation.

Statuses (MC/other) join APPROVED leave in ONE fetch layer. `absences_between`
normalises it to away-only `AbsenceRow`s (in-camp statuses dropped — in camp is
not away); `presence_inputs` resolves every active person through the pure engine
(in-camp statuses kept as annotations). These tests pin: the merge, the label
mapping, the in-camp exclusion, the away consumers, and the parade-sorted
resolution list.
"""
import dataclasses
from datetime import date

from app.domain.presence import PresenceState
from app.domain.types import (
    Appointment,
    DayPart,
    LeaveType,
    Rank,
    RequestStatus,
    Service,
    StatusType,
)
from app.extensions import db
from app.models import LeaveRequest, Person, StatusEntry
from app.services import presence_service
from tests.conftest import login

DAY = date(2026, 7, 8)
NEXT = date(2026, 7, 9)


# --- planting helpers ----------------------------------------------------

def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def plant_leave(app, username, start=DAY, end=DAY, day_part=DayPart.FULL,
                status=RequestStatus.APPROVED, type_=LeaveType.OFF):
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username=username).scalar()
        row = LeaveRequest(person_id=pid, type=type_, start_date=start, end_date=end,
                           day_part=day_part, status=status)
        db.session.add(row)
        db.session.commit()
        return row.id


def plant_status(app, username, type_=StatusType.MC, start=DAY, end=DAY,
                 day_part=DayPart.FULL, in_camp=False, remarks=None):
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username=username).scalar()
        row = StatusEntry(person_id=pid, type=type_, start_date=start, end_date=end,
                          day_part=day_part, in_camp=in_camp, remarks=remarks, created_by_id=pid)
        db.session.add(row)
        db.session.commit()
        return row.id


def rows_on(app, day=DAY):
    with app.app_context():
        return presence_service.absences_on(day)


# --- AbsenceRow shape (decision: frozen dataclass) -----------------------

def test_absence_row_is_frozen_with_the_agreed_fields(app, make_person):
    make_person(username="ar_leave", platoon=1)
    plant_leave(app, "ar_leave")
    (row,) = rows_on(app)
    assert dataclasses.is_dataclass(row)
    # Convenience keys + normalised tag + provenance.
    assert row.person_id == _pid(app, "ar_leave")
    assert row.source == "leave"
    assert row.label == "OFF"
    assert row.in_camp is False
    assert row.day_part is DayPart.FULL
    assert row.person.display_name  # the Person model rides along
    # Frozen: attempting to mutate raises.
    try:
        row.label = "changed"
    except Exception as exc:
        assert exc.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("AbsenceRow should be immutable")


# --- the merge: both sources, out-of-camp only ---------------------------

def test_absences_between_merges_leave_and_out_of_camp_status(app, make_person):
    make_person(username="m_leave", platoon=1)
    make_person(username="m_mc", platoon=2)
    plant_leave(app, "m_leave")
    plant_status(app, "m_mc", type_=StatusType.MC, in_camp=False)

    rows = rows_on(app)
    by_source = {r.source: r for r in rows}
    assert set(by_source) == {"leave", "status"}
    assert by_source["leave"].label == "OFF"
    assert by_source["status"].label == "MC"
    assert all(r.in_camp is False for r in rows)


def test_absences_between_excludes_in_camp_status(app, make_person):
    make_person(username="ic_brief", platoon=1)
    make_person(username="oc_mc", platoon=1)
    plant_status(app, "ic_brief", type_=StatusType.OTHER, in_camp=True)
    plant_status(app, "oc_mc", type_=StatusType.MC, in_camp=False)

    people = {r.person.username for r in rows_on(app)}
    assert "oc_mc" in people          # out of camp → away
    assert "ic_brief" not in people   # in camp ≠ away


def test_absences_between_label_mapping_per_source(app, make_person):
    make_person(username="lab_oil", platoon=1)
    make_person(username="lab_mc", platoon=1)
    plant_leave(app, "lab_oil", type_=LeaveType.OIL)
    plant_status(app, "lab_mc", type_=StatusType.MC, in_camp=False)

    labels = {r.person.username: r.label for r in rows_on(app)}
    assert labels["lab_oil"] == "OIL"   # leave → type.value
    assert labels["lab_mc"] == "MC"     # status → type.label


def test_absences_between_clips_range_and_buckets_each_day(app, make_person):
    make_person(username="span_mc", platoon=1)
    plant_status(app, "span_mc", type_=StatusType.MC, start=DAY, end=NEXT, in_camp=False)
    with app.app_context():
        by_day = presence_service.absences_between(DAY, NEXT)
        assert {r.person.username for r in by_day[DAY]} == {"span_mc"}
        assert {r.person.username for r in by_day[NEXT]} == {"span_mc"}


def test_absences_on_delegates_to_absences_between(app, make_person):
    make_person(username="del_mc", platoon=1)
    plant_status(app, "del_mc", type_=StatusType.MC, in_camp=False)
    with app.app_context():
        on_ids = [r.id for r in presence_service.absences_on(DAY)]
        between_ids = [r.id for r in presence_service.absences_between(DAY, DAY)[DAY]]
        assert on_ids == between_ids
        assert len(on_ids) == 1


# --- consumer: month view NSF OFF/LEAVE chip (HTTP) ----------------------

def test_month_view_shows_no_off_leave_chip_for_mc_or_briefing(app, client, make_person):
    # The violet layer is APPROVED leave ONLY; MC and briefing are away sources
    # that live on the away board, never the home grid. Neither shows a chip.
    make_person(username="mv_brief", platoon=1)
    make_person(username="mv_mc", platoon=2)
    plant_status(app, "mv_brief", type_=StatusType.OTHER, start=DAY, end=DAY, in_camp=True)
    plant_status(app, "mv_mc", type_=StatusType.MC, start=NEXT, end=NEXT, in_camp=False)

    login(client, make_person(username="mv_v"))
    resp = client.get("/calendar/month?ym=2026-07")
    assert resp.status_code == 200
    assert b"chip cal-off" not in resp.data


def test_month_view_leave_and_mc_same_person_shows_one_chip(app, client, make_person):
    # A person on BOTH leave and MC the same day: the leave-only filter drops the
    # MC row, so the person's single OFF chip is the only one — never two.
    make_person(username="mv_both", platoon=1)
    plant_leave(app, "mv_both", start=DAY, end=DAY)
    plant_status(app, "mv_both", type_=StatusType.MC, start=DAY, end=DAY, in_camp=False)

    login(client, make_person(username="mv_both_v"))
    resp = client.get("/calendar/month?ym=2026-07")
    assert resp.status_code == 200
    assert resp.data.count(b"chip cal-off") == 1


# --- consumer: leave-detail projected-away panel (HTTP) ------------------

def test_leave_panel_projected_away_includes_status_absent_person(app, client, make_person):
    make_person(username="lp_req", appointment=Appointment.OPR, platoon=1, service=Service.NSF)
    req_id = plant_leave(app, "lp_req", start=DAY, end=DAY, status=RequestStatus.PENDING_PC)
    # Another person is on MC that day — the panel must now see them.
    make_person(username="lp_mc", platoon=2)
    plant_status(app, "lp_mc", type_=StatusType.MC, start=DAY, end=DAY, in_camp=False)
    # ...and an in-camp briefing person who must NOT be counted.
    make_person(username="lp_brief", platoon=2)
    plant_status(app, "lp_brief", type_=StatusType.OTHER, start=DAY, end=DAY, in_camp=True)

    login(client, make_person(username="lp_oc", rank=Rank.CPT, appointment=Appointment.OC,
                              platoon=None))
    resp = client.get(f"/leave/{req_id}")
    assert resp.status_code == 200
    assert b"1 away" in resp.data          # the MC'd person (briefing excluded)
    assert b"2 if approved" in resp.data   # MC'd person + the requester


def test_leave_panel_distinct_rule_holds_with_overlapping_status(app, client, make_person):
    make_person(username="lp2_req", appointment=Appointment.OPR, platoon=1, service=Service.NSF)
    req_id = plant_leave(app, "lp2_req", start=DAY, end=DAY, status=RequestStatus.PENDING_PC)
    # Another person has BOTH leave and an MC that day — must count once.
    make_person(username="lp2_both", platoon=2)
    plant_leave(app, "lp2_both", start=DAY, end=DAY)
    plant_status(app, "lp2_both", type_=StatusType.MC, start=DAY, end=DAY, in_camp=False)

    login(client, make_person(username="lp2_oc", rank=Rank.CPT, appointment=Appointment.OC,
                              platoon=None))
    resp = client.get(f"/leave/{req_id}")
    assert resp.status_code == 200
    assert b"1 away" in resp.data          # lp2_both counted once
    assert b"2 away" not in resp.data
    assert b"2 if approved" in resp.data   # lp2_both + requester


# --- presence_inputs: the parade-document entry point --------------------

def test_presence_inputs_resolves_each_active_person_parade_sorted(app, make_person):
    # Parade order: OC (0) < PC (idx) < OPR (last). Each entry carries its
    # person, so identity AND ordering are asserted directly — P3a.6 must never
    # have to zip a resolution back to a person by index.
    make_person(username="pi_oc", rank=Rank.CPT, appointment=Appointment.OC, platoon=None,
                service=Service.REGULAR)  # regular, nothing → STAY_OUT
    make_person(username="pi_pc", rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=1,
                service=Service.NSF)
    make_person(username="pi_opr", rank=Rank.PTE, appointment=Appointment.OPR, platoon=1,
                service=Service.NSF)
    plant_leave(app, "pi_pc", start=DAY, end=DAY)  # approved leave → ABSENT
    plant_status(app, "pi_opr", type_=StatusType.OTHER, start=DAY, end=DAY, in_camp=True)

    with app.app_context():
        entries = presence_service.presence_inputs(DAY)
        assert [e.person.username for e in entries] == ["pi_oc", "pi_pc", "pi_opr"]

        # [0] the OC regular with nothing keyed: (that person, STAY_OUT).
        oc_person, oc_res = entries[0]  # NamedTuple: unpacks as (person, resolution)
        assert oc_person.username == "pi_oc"
        assert oc_res.state is PresenceState.STAY_OUT
        assert oc_res.row is None
        assert oc_res.in_camp_rows == ()
        assert oc_res.conflicts == ()

        # [1] the PC on approved leave: ABSENT, leave is the winning row.
        assert entries[1].person.username == "pi_pc"
        assert entries[1].resolution.state is PresenceState.ABSENT
        assert entries[1].resolution.row.person_id == entries[1].person.id
        assert entries[1].resolution.row.type is LeaveType.OFF  # original model row

        # [2] the OPR with an in-camp briefing: present, briefing is an annotation.
        assert entries[2].person.username == "pi_opr"
        assert entries[2].resolution.state is PresenceState.PRESENT
        assert len(entries[2].resolution.in_camp_rows) == 1
        assert entries[2].resolution.in_camp_rows[0].person_id == entries[2].person.id


def test_presence_inputs_passes_all_sources_so_conflicts_surface(app, make_person):
    make_person(username="pi_conf", appointment=Appointment.OPR, platoon=1, service=Service.NSF)
    plant_leave(app, "pi_conf", start=DAY, end=DAY)
    plant_status(app, "pi_conf", type_=StatusType.MC, start=DAY, end=DAY, in_camp=False)
    with app.app_context():
        (entry,) = presence_service.presence_inputs(DAY)
        assert entry.person.username == "pi_conf"
        res = entry.resolution
        assert res.state is PresenceState.ABSENT
        assert res.row.type is LeaveType.OFF          # leave wins
        assert len(res.conflicts) == 1
        assert res.conflicts[0].type is StatusType.MC  # MC surfaced, never dropped


def test_presence_inputs_excludes_deactivated_people(app, make_person):
    make_person(username="pi_active", appointment=Appointment.OPR, platoon=1)
    make_person(username="pi_gone", appointment=Appointment.OPR, platoon=1, is_active=False)
    plant_leave(app, "pi_gone", start=DAY, end=DAY)  # even with leave, off the roster
    with app.app_context():
        entries = presence_service.presence_inputs(DAY)
        assert [e.person.username for e in entries] == ["pi_active"]  # only the active person
