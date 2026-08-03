"""P7.1 — person_audit trail + /admin/audit page.

Append-only, one row per changed field per save, written in the same
transaction as the person edit. The Done criterion (an appointment change
appears in the view) is asserted on the /admin/audit response bytes.
"""
from app.domain.types import Appointment, Rank
from app.extensions import db
from app.models import Person, PersonAudit
from tests.conftest import login


def make_s3(make_person):
    return make_person(
        username="s3_admin",
        rank=Rank.TWO_SG,
        appointment=Appointment.DET_COMD,
        company_role="S3",
    )


def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def _edit_payload(**overrides):
    data = {
        "username": "target",
        "display_name": "Target",
        "phone": "",
        "rank": "PTE",
        "appointment": "OPR",
        "company_role": "",
        "platoon": "1",
        "service": "NSF",
    }
    data.update(overrides)
    return data


def test_person_audit_persists_with_defaults(app, make_person):
    make_person(username="p_a")
    make_person(username="actor_a", platoon=2)
    with app.app_context():
        pid = db.session.query(Person.id).filter_by(username="p_a").scalar()
        aid = db.session.query(Person.id).filter_by(username="actor_a").scalar()
        row = PersonAudit(person_id=pid, field="appointment", old="OPR", new="PC", actor_id=aid)
        db.session.add(row)
        db.session.commit()
        assert row.id is not None
        assert row.at is not None
        assert row.person.username == "p_a"
        assert row.actor.username == "actor_a"


def test_appointment_edit_writes_one_row_and_shows_in_view(app, client, make_person):
    make_person(username="target")
    login(client, make_s3(make_person))
    target_id = _pid(app, "target")
    resp = client.post(
        f"/admin/people/{target_id}",
        data=_edit_payload(appointment="PC"),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        rows = db.session.query(PersonAudit).filter_by(person_id=target_id).all()
        assert len(rows) == 1
        assert (rows[0].field, rows[0].old, rows[0].new) == ("appointment", "OPR", "PC")
        actor_id = db.session.query(Person.id).filter_by(username="s3_admin").scalar()
        assert rows[0].actor_id == actor_id
    # Done criterion: the change renders on the standalone audit page.
    page = client.get("/admin/audit")
    assert page.status_code == 200
    assert b"appointment" in page.data
    assert b"OPR" in page.data and b"PC" in page.data


def test_meals_opt_in_edit_writes_one_row(app, client, make_person):
    make_person(username="target")
    login(client, make_s3(make_person))
    target_id = _pid(app, "target")
    resp = client.post(
        f"/admin/people/{target_id}",
        data=_edit_payload(meals_opt_in="y"),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        person = db.session.get(Person, target_id)
        assert person.meals_opt_in is True
        rows = db.session.query(PersonAudit).filter_by(person_id=target_id).all()
        assert len(rows) == 1
        assert (rows[0].field, rows[0].old, rows[0].new) == ("meals_opt_in", "no", "yes")


def test_noop_save_writes_zero_rows(app, client, make_person):
    make_person(username="target")
    login(client, make_s3(make_person))
    target_id = _pid(app, "target")
    resp = client.post(
        f"/admin/people/{target_id}",
        data=_edit_payload(),  # identical to current values
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.query(PersonAudit).filter_by(person_id=target_id).count() == 0


def test_multi_field_edit_writes_one_row_per_field(app, client, make_person):
    make_person(username="target")
    login(client, make_s3(make_person))
    target_id = _pid(app, "target")
    client.post(
        f"/admin/people/{target_id}",
        data=_edit_payload(display_name="Renamed", rank="CPL", platoon="2"),
        follow_redirects=True,
    )
    with app.app_context():
        rows = db.session.query(PersonAudit).filter_by(person_id=target_id).all()
        changed = {r.field: (r.old, r.new) for r in rows}
        assert changed == {
            "display_name": ("Target", "Renamed"),
            "rank": ("PTE", "CPL"),
            "platoon": ("1", "2"),
        }


def test_audit_page_forbidden_for_non_s3(client, make_person):
    login(client, make_person(username="opr_x"))
    assert client.get("/admin/audit").status_code == 403


def test_audit_person_id_filter(app, client, make_person):
    make_person(username="target")
    make_person(username="other", platoon=2)
    login(client, make_s3(make_person))
    target_id = _pid(app, "target")
    other_id = _pid(app, "other")
    client.post(
        f"/admin/people/{target_id}",
        data=_edit_payload(appointment="PC"),
        follow_redirects=True,
    )
    client.post(
        f"/admin/people/{other_id}",
        data=_edit_payload(username="other", display_name="Other", platoon="2", rank="CPL"),
        follow_redirects=True,
    )
    filtered = client.get(f"/admin/audit?person_id={target_id}")
    assert filtered.status_code == 200
    assert b"appointment" in filtered.data
    # The other person's rank change (PTE -> CPL) must not leak into the
    # filtered-by-target view.
    assert b"CPL" not in filtered.data
    with app.app_context():
        assert db.session.query(PersonAudit).filter_by(person_id=other_id).count() == 1
