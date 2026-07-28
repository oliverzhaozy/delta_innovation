from datetime import timedelta

import pytest

from app.domain.dates import now_sgt, today_sgt
from app.domain.types import Appointment, Rank, RequestStatus
from app.extensions import db
from app.models import LeaveRequest, Person
from tests.conftest import login


@pytest.fixture()
def cast(app, make_person):
    """opr (P1), pc1, oc — the minimum cast for the history split and the queues."""
    make_person(username="opr", platoon=1)
    make_person(username="pc1", rank=Rank.TWO_LT, appointment=Appointment.PC, platoon=1)
    make_person(username="oc", rank=Rank.CPT, appointment=Appointment.OC, platoon=None)
    with app.app_context():
        ids = dict(db.session.query(Person.username, Person.id).all())
    return ids


def add_request(app, person_id, status, start, end=None, created_at=None, type_="OFF"):
    """Insert one request and return its when_label (the marker asserted on)."""
    with app.app_context():
        row = LeaveRequest(
            person_id=person_id,
            type=type_,
            start_date=start,
            end_date=end or start,
            status=status,
        )
        if created_at is not None:
            row.created_at = created_at
        db.session.add(row)
        db.session.commit()
        return row.when_label


def days_from_today(offset):
    return today_sgt() + timedelta(days=offset)


@pytest.fixture()
def split_rows(app, cast):
    """One row of every kind, keyed by name; all dates distinct so when_label is
    a unique marker per row."""
    opr = cast["opr"]
    return {
        "pending": add_request(app, opr, RequestStatus.PENDING_PC, days_from_today(3)),
        "upcoming": add_request(app, opr, RequestStatus.APPROVED, days_from_today(10)),
        "elapsed": add_request(app, opr, RequestStatus.APPROVED, days_from_today(-20)),
        "rejected": add_request(app, opr, RequestStatus.REJECTED_PC, days_from_today(-25)),
        "cancelled": add_request(app, opr, RequestStatus.CANCELLED, days_from_today(-30)),
    }


def test_index_shows_only_live_requests(client, cast, split_rows):
    login(client, "opr")
    html = client.get("/leave/").data.decode()
    assert split_rows["pending"] in html
    assert split_rows["upcoming"] in html
    assert split_rows["elapsed"] not in html
    assert split_rows["rejected"] not in html
    assert split_rows["cancelled"] not in html


def test_history_shows_only_concluded_requests(client, cast, split_rows):
    login(client, "opr")
    html = client.get("/leave/history").data.decode()
    assert split_rows["elapsed"] in html
    assert split_rows["rejected"] in html
    assert split_rows["cancelled"] in html
    assert split_rows["pending"] not in html
    assert split_rows["upcoming"] not in html


def test_history_empty_state(client, cast):
    login(client, "opr")
    assert b"No past requests." in client.get("/leave/history").data


def test_history_forbidden_for_regulars(client, cast):
    # Regulars are outside the request flow entirely (owner directive 2026-07-26).
    login(client, "oc")
    assert client.get("/leave/history").status_code == 403


def test_pc_queue_puts_the_soonest_leave_first(app, client, cast):
    later = add_request(
        app, cast["opr"], RequestStatus.PENDING_PC, days_from_today(30),
        created_at=now_sgt() - timedelta(hours=2),
    )
    sooner = add_request(
        app, cast["opr"], RequestStatus.PENDING_PC, days_from_today(2),
        created_at=now_sgt(),
    )
    login(client, "pc1")
    html = client.get("/leave/queue/pc").data.decode()
    # Submitted second, but starts first — most upcoming leads the queue.
    assert html.index(sooner) < html.index(later)


def test_oc_queue_puts_the_soonest_leave_first(app, client, cast):
    later = add_request(
        app, cast["opr"], RequestStatus.PENDING_OC, days_from_today(30),
        created_at=now_sgt() - timedelta(hours=2),
    )
    sooner = add_request(
        app, cast["opr"], RequestStatus.PENDING_OC, days_from_today(2),
        created_at=now_sgt(),
    )
    login(client, "oc")
    html = client.get("/leave/queue/oc").data.decode()
    assert html.index(sooner) < html.index(later)
