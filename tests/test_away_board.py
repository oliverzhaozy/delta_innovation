from datetime import date

from app.domain.types import Appointment, DayPart, LeaveType, Rank, RequestStatus
from app.extensions import db
from app.models import LeaveRequest, Person
from tests.conftest import login

WED = date(2026, 7, 8)


def plant_request(app, username, status, day_part=DayPart.FULL, day=WED):
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(
            LeaveRequest(
                person_id=pid, type=LeaveType.OFF, start_date=day, end_date=day,
                day_part=day_part, status=status,
            )
        )
        db.session.commit()


def test_board_shows_approved_absences_only(app, client, make_person):
    make_person(username="away_guy", display_name="PTE Away Guy", platoon=1)
    make_person(username="pending_guy", display_name="PTE Pending Guy", platoon=1)
    viewer = make_person(username="viewer", platoon=2)
    plant_request(app, "away_guy", RequestStatus.APPROVED)
    plant_request(app, "pending_guy", RequestStatus.PENDING_PC)

    login(client, viewer)
    resp = client.get(f"/parade/away?date={WED.isoformat()}")
    assert resp.status_code == 200
    assert b"PTE Away Guy" in resp.data
    assert b"Pending Guy" not in resp.data


def test_board_tags_half_days_and_counts(app, client, make_person):
    make_person(username="am_guy", display_name="PTE Am Guy", platoon=3)
    viewer = make_person(username="viewer2", platoon=1)
    plant_request(app, "am_guy", RequestStatus.APPROVED, day_part=DayPart.AM)
    login(client, viewer)
    resp = client.get(f"/parade/away?date={WED.isoformat()}")
    assert b"AM" in resp.data
    assert b"1 half-day" in resp.data


def test_deactivated_person_disappears_from_board(app, client, make_person):
    make_person(username="gone_guy", display_name="PTE Gone Guy", platoon=1, is_active=False)
    viewer = make_person(username="viewer3", platoon=1)
    plant_request(app, "gone_guy", RequestStatus.APPROVED)
    login(client, viewer)
    resp = client.get(f"/parade/away?date={WED.isoformat()}")
    assert b"Gone Guy" not in resp.data


def test_bad_date_falls_back_to_today(client, make_person):
    login(client, make_person(username="viewer4"))
    assert client.get("/parade/away?date=garbage").status_code == 200
