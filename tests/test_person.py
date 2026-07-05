from app.domain.types import (
    RANK_ORDER,
    Appointment,
    Rank,
    Service,
    rank_at_least,
    rank_at_most,
)
from app.extensions import db
from app.models import Person


def test_rank_order_matches_spec_hierarchy():
    assert (
        RANK_ORDER[Rank.CPT]
        > RANK_ORDER[Rank.THREE_WO]
        > RANK_ORDER[Rank.TWO_SG]
        > RANK_ORDER[Rank.THREE_SG]
        > RANK_ORDER[Rank.PTE]
    )


def test_rank_boundary_helpers_are_inclusive():
    # "2SG or below" and "2SG or above" both include 2SG itself.
    assert rank_at_most(Rank.TWO_SG, Rank.TWO_SG)
    assert rank_at_most(Rank.THREE_SG, Rank.TWO_SG)
    assert not rank_at_most(Rank.ONE_SG, Rank.TWO_SG)
    assert rank_at_least(Rank.TWO_SG, Rank.TWO_SG)
    assert rank_at_least(Rank.ONE_SG, Rank.TWO_SG)
    assert not rank_at_least(Rank.THREE_SG, Rank.TWO_SG)


def test_person_roundtrip_and_password(app):
    with app.app_context():
        db.create_all()
        person = Person(
            username="test_opr",
            display_name="PTE Test",
            rank=Rank.PTE,
            appointment=Appointment.OPR,
            platoon=1,
            service=Service.NSF,
        )
        person.set_password("some-password-123")
        db.session.add(person)
        db.session.commit()

        got = db.session.query(Person).filter_by(username="test_opr").one()
        assert got.rank is Rank.PTE
        assert got.appointment is Appointment.OPR
        assert got.company_role is None
        assert got.check_password("some-password-123")
        assert not got.check_password("wrong")
        assert got.must_change_pw  # default: forced change at first login
