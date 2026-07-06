from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.dates import today_sgt
from app.extensions import db
from app.models import OverseasDeclaration, Person
from tests.conftest import login

TODAY = today_sgt()
NEXT_WEEK = TODAY + timedelta(days=7)
LAST_WEEK = TODAY - timedelta(days=7)
YESTERDAY = TODAY - timedelta(days=1)


def declare(client, start=None, end=None, destination="Malaysia"):
    start = start or NEXT_WEEK
    end = end or NEXT_WEEK
    return client.post(
        "/overseas/declare",
        data={"start_date": start.isoformat(), "end_date": end.isoformat(), "destination": destination},
        follow_redirects=True,
    )


def declaration_id_for(app, username):
    with app.app_context():
        return (
            db.session.query(OverseasDeclaration.id)
            .join(Person, OverseasDeclaration.person_id == Person.id)
            .filter(Person.username == username)
            .scalar()
        )


def test_date_order_check_constraint_enforced_in_db(app, make_person):
    make_person(username="ovs_dbcheck")
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username="ovs_dbcheck").scalar()
        row = OverseasDeclaration(
            person_id=pid, start_date=TODAY + timedelta(days=2), end_date=TODAY + timedelta(days=1),
            destination="Nowhere",
        )
        db.session.add(row)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_opr_declares_and_it_appears_in_mine_and_s3_upcoming(app, client, make_person):
    make_person(username="s3_person", company_role="S3")
    login(client, make_person(username="ovs_opr", display_name="PTE Ovs Opr"))
    resp = declare(client, destination="Japan")
    assert b"Declared" in resp.data

    mine_resp = client.get("/overseas/mine")
    assert b"Japan" in mine_resp.data
    client.post("/logout")

    login(client, "s3_person")
    upcoming_resp = client.get("/overseas/upcoming")
    assert upcoming_resp.status_code == 200
    assert b"Japan" in upcoming_resp.data
    assert b"Ovs Opr" in upcoming_resp.data


def test_retract_sets_cancelled_at_stays_in_mine_and_leaves_upcoming(app, client, make_person):
    make_person(username="s3_person2", company_role="S3")
    login(client, make_person(username="ovs_retract"))
    declare(client, destination="Thailand")
    decl_id = declaration_id_for(app, "ovs_retract")

    resp = client.post(f"/overseas/{decl_id}/retract", follow_redirects=True)
    assert b"Retracted" in resp.data

    with app.app_context():
        row = db.session.get(OverseasDeclaration, decl_id)
        assert row.cancelled_at is not None

    mine_resp = client.get("/overseas/mine")
    assert b"Thailand" in mine_resp.data  # row stays visible
    assert b"Retracted" in mine_resp.data  # badge

    client.post("/logout")
    login(client, "s3_person2")
    upcoming_resp = client.get("/overseas/upcoming")
    assert b"Thailand" not in upcoming_resp.data


def test_cannot_retract_someone_elses_declaration(app, client, make_person):
    login(client, make_person(username="ovs_victim"))
    declare(client, destination="Vietnam")
    decl_id = declaration_id_for(app, "ovs_victim")
    client.post("/logout")

    login(client, make_person(username="ovs_attacker"))
    resp = client.post(f"/overseas/{decl_id}/retract")
    assert resp.status_code == 403


def test_non_s3_forbidden_on_upcoming(client, make_person):
    login(client, make_person(username="ovs_plain"))
    assert client.get("/overseas/upcoming").status_code == 403


def test_past_declaration_excluded_from_upcoming(app, client, make_person):
    make_person(username="s3_person3", company_role="S3")
    login(client, make_person(username="ovs_past"))
    declare(client, start=LAST_WEEK, end=YESTERDAY, destination="Indonesia")
    client.post("/logout")

    login(client, "s3_person3")
    resp = client.get("/overseas/upcoming")
    assert b"Indonesia" not in resp.data


def test_end_before_start_rejected_by_form(client, make_person):
    login(client, make_person(username="ovs_rev"))
    resp = declare(client, start=NEXT_WEEK, end=NEXT_WEEK - timedelta(days=1))
    assert b"before start date" in resp.data
