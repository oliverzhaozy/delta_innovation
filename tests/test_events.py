from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.types import Calendar, ParticipantCategory
from app.extensions import db
from app.models import Event, EventParticipant, Person

START = datetime(2026, 8, 1, 8, 0)
END = datetime(2026, 8, 1, 17, 0)


def person_id_of(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def make_event(pid, calendar=Calendar.TP, start=START, end=END, title="TP exercise"):
    return Event(
        calendar=calendar, title=title, start_dt=start, end_dt=end, created_by_id=pid,
    )


def test_calendar_enum_members_and_labels():
    assert [c.value for c in Calendar] == ["TP", "ARCTIC"]
    assert Calendar.TP.label == "TP"
    assert Calendar.ARCTIC.label == "ARCTIC FOE"


def test_participant_category_enum_members_and_labels():
    assert [c.value for c in ParticipantCategory] == [
        "NSF", "REGULAR", "COMMAND_TEAM", "PLATOON_1", "PLATOON_2", "PLATOON_3",
    ]
    assert ParticipantCategory.NSF.label == "NSF"
    assert ParticipantCategory.REGULAR.label == "Regulars"
    assert ParticipantCategory.COMMAND_TEAM.label == "Command team"
    assert ParticipantCategory.PLATOON_1.label == "Platoon 1"
    assert ParticipantCategory.PLATOON_2.label == "Platoon 2"
    assert ParticipantCategory.PLATOON_3.label == "Platoon 3"


def test_end_dt_must_be_after_start_dt(app, make_person):
    make_person(username="ev_owner1")
    with app.app_context():
        pid = person_id_of(app, "ev_owner1")
        event = make_event(pid, start=END, end=START)  # end before start
        db.session.add(event)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_end_dt_equal_start_dt_rejected(app, make_person):
    make_person(username="ev_owner2")
    with app.app_context():
        pid = person_id_of(app, "ev_owner2")
        event = make_event(pid, start=START, end=START)  # zero-length
        db.session.add(event)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_participant_xor_rejects_both_person_and_category(app, make_person):
    make_person(username="ev_owner3")
    make_person(username="ev_p3")
    with app.app_context():
        pid = person_id_of(app, "ev_owner3")
        other_pid = person_id_of(app, "ev_p3")
        event = make_event(pid)
        db.session.add(event)
        db.session.flush()
        participant = EventParticipant(
            event_id=event.id, person_id=other_pid, category=ParticipantCategory.NSF,
        )
        db.session.add(participant)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_participant_xor_rejects_neither_person_nor_category(app, make_person):
    make_person(username="ev_owner4")
    with app.app_context():
        pid = person_id_of(app, "ev_owner4")
        event = make_event(pid)
        db.session.add(event)
        db.session.flush()
        participant = EventParticipant(event_id=event.id)
        db.session.add(participant)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_duplicate_person_on_same_event_rejected(app, make_person):
    make_person(username="ev_owner5")
    make_person(username="ev_p5")
    with app.app_context():
        pid = person_id_of(app, "ev_owner5")
        other_pid = person_id_of(app, "ev_p5")
        event = make_event(pid)
        db.session.add(event)
        db.session.flush()
        db.session.add(EventParticipant(event_id=event.id, person_id=other_pid))
        db.session.add(EventParticipant(event_id=event.id, person_id=other_pid))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_duplicate_category_on_same_event_rejected(app, make_person):
    make_person(username="ev_owner6")
    with app.app_context():
        pid = person_id_of(app, "ev_owner6")
        event = make_event(pid)
        db.session.add(event)
        db.session.flush()
        db.session.add(EventParticipant(event_id=event.id, category=ParticipantCategory.NSF))
        db.session.add(EventParticipant(event_id=event.id, category=ParticipantCategory.NSF))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_many_distinct_categories_and_people_allowed_on_one_event(app, make_person):
    make_person(username="ev_owner7")
    make_person(username="ev_p7a")
    make_person(username="ev_p7b")
    with app.app_context():
        pid = person_id_of(app, "ev_owner7")
        pid_a = person_id_of(app, "ev_p7a")
        pid_b = person_id_of(app, "ev_p7b")
        event = make_event(pid)
        db.session.add(event)
        db.session.flush()
        db.session.add_all([
            EventParticipant(event_id=event.id, category=ParticipantCategory.NSF),
            EventParticipant(event_id=event.id, category=ParticipantCategory.REGULAR),
            EventParticipant(event_id=event.id, person_id=pid_a),
            EventParticipant(event_id=event.id, person_id=pid_b),
        ])
        db.session.commit()  # should not raise
        assert len(event.participants) == 4


def test_deleting_event_cascades_to_participants(app, make_person):
    make_person(username="ev_owner8")
    with app.app_context():
        pid = person_id_of(app, "ev_owner8")
        event = make_event(pid)
        db.session.add(event)
        db.session.flush()
        db.session.add(EventParticipant(event_id=event.id, category=ParticipantCategory.NSF))
        db.session.commit()
        event_id = event.id

        event = db.session.get(Event, event_id)
        db.session.delete(event)
        db.session.commit()

        remaining = (
            db.session.query(EventParticipant).filter_by(event_id=event_id).count()
        )
        assert remaining == 0
