"""P8.6 — override routes.

Route tests assert through the RENDERED text only (the server re-render is the
one truth; the client does no count math): a keyer's move rebalances the <pre>,
a non-keyer is refused, disallowed/off-roster targets flash and write nothing,
and the COS override is stored against tomorrow's date. P8.7 extends this file
with the drag-grid UI assertions.
"""
from datetime import timedelta

from app.domain.dates import today_sgt
from app.domain.types import OverrideCategory, ParadeVariant, Service
from app.extensions import db
from app.models import ParadeOverride, Person
from app.services import parade_service
from tests.conftest import login

TODAY = today_sgt()
TOMORROW = TODAY + timedelta(days=1)


def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def test_keyer_move_reflected_in_rendered_text(app, client, make_person):
    make_person(username="ov_keyer", is_admin=True, display_name="Key Er")
    make_person(username="ov_target", display_name="Move Me")
    login(client, "ov_keyer")
    tpid = _pid(app, "ov_target")

    resp = client.post(
        "/parade/override",
        data={"variant": "morning", "person_id": str(tpid), "target": "mc"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # The moved person now stands under MC, and the header counts rebalanced —
    # asserted only through the server-rendered <pre>.
    assert b"MC (1):" in resp.data
    assert b"PTE MOVE ME" in resp.data
    assert b"CURRENT STRENGTH: 1" in resp.data
    with app.app_context():
        row = db.session.query(ParadeOverride).one()
        assert row.date == TODAY
        assert row.variant is ParadeVariant.MORNING
        assert row.target_category is OverrideCategory.MC


def test_non_keyer_gets_403_and_writes_nothing(app, client, make_person):
    make_person(username="ov_plain")  # OPR NSF, not a keyer
    make_person(username="ov_t2")
    login(client, "ov_plain")
    tpid = _pid(app, "ov_t2")

    resp = client.post(
        "/parade/override",
        data={"variant": "morning", "person_id": str(tpid), "target": "mc"},
    )
    assert resp.status_code == 403
    with app.app_context():
        assert db.session.query(ParadeOverride).count() == 0


def test_morning_stay_out_target_rejected(app, client, make_person):
    make_person(username="ov_k2", is_admin=True)
    make_person(username="ov_t3")
    login(client, "ov_k2")
    tpid = _pid(app, "ov_t3")

    resp = client.post(
        "/parade/override",
        data={"variant": "morning", "person_id": str(tpid), "target": "stay_out"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Could not move" in resp.data
    with app.app_context():
        assert db.session.query(ParadeOverride).count() == 0


def test_off_roster_person_rejected(app, client, make_person):
    make_person(username="ov_k3", is_admin=True)
    login(client, "ov_k3")

    resp = client.post(
        "/parade/override",
        data={"variant": "morning", "person_id": "999999", "target": "mc"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Could not move" in resp.data
    with app.app_context():
        assert db.session.query(ParadeOverride).count() == 0


def test_unknown_variant_is_400(app, client, make_person):
    make_person(username="ov_k4", is_admin=True)
    login(client, "ov_k4")
    resp = client.post(
        "/parade/override",
        data={"variant": "garbage", "person_id": "1", "target": "mc"},
    )
    assert resp.status_code == 400


def test_reset_restores_untouched_render(app, client, make_person):
    make_person(username="ov_k5", is_admin=True, display_name="Reset Keyer")
    make_person(username="ov_t5", display_name="Reset Target")
    login(client, "ov_k5")
    tpid = _pid(app, "ov_t5")
    with app.app_context():
        baseline = parade_service.build_doc(TODAY, ParadeVariant.MORNING).text

    client.post(
        "/parade/override",
        data={"variant": "morning", "person_id": str(tpid), "target": "mc"},
    )
    with app.app_context():
        assert db.session.query(ParadeOverride).count() == 1

    resp = client.post(
        "/parade/override/reset", data={"variant": "morning"}, follow_redirects=True
    )
    assert resp.status_code == 200
    assert b"Reset 1 override" in resp.data
    with app.app_context():
        assert db.session.query(ParadeOverride).count() == 0
        assert parade_service.build_doc(TODAY, ParadeVariant.MORNING).text == baseline


def test_cos_override_writes_tomorrows_date(app, client, make_person):
    make_person(username="ov_kcos", is_admin=True)
    make_person(username="ov_tcos", service=Service.REGULAR)
    login(client, "ov_kcos")
    tpid = _pid(app, "ov_tcos")

    resp = client.post(
        "/parade/override",
        data={"variant": "cos", "person_id": str(tpid), "target": "leave", "cos": str(tpid)},
    )
    assert resp.status_code == 302
    with app.app_context():
        row = db.session.query(ParadeOverride).filter_by(
            variant=ParadeVariant.COS_MESSAGE
        ).one()
        assert row.date == TOMORROW
        assert row.target_category is OverrideCategory.LEAVE
