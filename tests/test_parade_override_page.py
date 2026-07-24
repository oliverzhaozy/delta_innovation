"""P8.6 — override routes.

Route tests assert through the RENDERED text only (the server re-render is the
one truth; the client does no count math): a keyer's move rebalances the <pre>,
a non-keyer is refused, disallowed/off-roster targets flash and write nothing,
and the COS override is stored against tomorrow's date. P8.7 extends this file
with the drag-grid UI assertions.
"""
import re
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


# --- T9: drag grid mirrors the doc; keyer-gating; indicator ------------------

def _grid_by_category(html):
    """Parse the drag grid into {data-drop-category: [person_id, ...]} using the
    same data attributes the page renders — the testable seam for a doc↔grid
    equality check with no JS runner."""
    grid = {}
    for zone in re.finditer(
        r'data-drop-category="([^"]+)"(.*?)(?=data-drop-category="|$)', html, re.S
    ):
        key = zone.group(1)
        ids = [int(m) for m in re.findall(r'data-drag-person="(\d+)"', zone.group(2))]
        grid[key] = ids
    return grid


def _person(app, pid):
    with app.app_context():
        return db.session.get(Person, pid)


def _expected_grid(app, day, variant, **kw):
    with app.app_context():
        from app.domain import parade as parade_domain

        built = parade_service.build_doc(day, variant, **kw)
        return {
            view.key: [pid for pid, _line in view.entries]
            for view in parade_domain.category_views(built.doc)
        }


def test_grid_matches_doc_tuples_for_all_variants(app, client, make_person):
    make_person(username="grid_keyer", is_admin=True, display_name="Grid Keyer")
    make_person(username="grid_p1", display_name="Grid One")
    make_person(username="grid_reg", display_name="Grid Reg", service=Service.REGULAR)
    login(client, "grid_keyer")

    for path, day, variant in (
        ("/parade/morning", TODAY, ParadeVariant.MORNING),
        ("/parade/roll-call", TODAY, ParadeVariant.ROLL_CALL),
    ):
        resp = client.get(path)
        assert resp.status_code == 200
        assert _grid_by_category(resp.data.decode()) == _expected_grid(app, day, variant)

    # The COS page fixes the doc to tomorrow; its grid must mirror THAT doc.
    keyer_id = _pid(app, "grid_keyer")
    cos = client.get(f"/parade/cos-message?cos={keyer_id}")
    assert cos.status_code == 200
    assert _grid_by_category(cos.data.decode()) == _expected_grid(
        app, TOMORROW, ParadeVariant.COS_MESSAGE, cos_person=_person(app, keyer_id)
    )


def test_grid_and_pre_are_two_projections_of_one_doc(app, client, make_person):
    make_person(username="proj_keyer", is_admin=True)
    make_person(username="proj_p1", display_name="Proj One")
    login(client, "proj_keyer")
    resp = client.get("/parade/morning")
    html = resp.data.decode()
    with app.app_context():
        built = parade_service.build_doc(TODAY, ParadeVariant.MORNING)
    # The same response carries the grid AND the <pre>; the <pre> is byte-equal
    # to build_doc's text (one doc, two projections, one request).
    import html as htmlmod

    pre = re.search(r'<pre id="paradetext"[^>]*>(.*?)</pre>', html, re.S).group(1)
    assert htmlmod.unescape(pre) == built.text


def test_non_keyer_sees_no_drag_ui(app, client, make_person):
    make_person(username="noadjust", display_name="No Adjust")
    login(client, "noadjust")
    resp = client.get("/parade/morning")
    assert resp.status_code == 200
    assert b"data-drop-category" not in resp.data
    assert b'id="override-form"' not in resp.data


def test_indicator_and_reset_only_when_overridden(app, client, make_person):
    make_person(username="ind_keyer", is_admin=True)
    make_person(username="ind_target", display_name="Ind Target")
    login(client, "ind_keyer")
    tpid = _pid(app, "ind_target")

    before = client.get("/parade/morning").data
    assert b"overrides-active" not in before
    assert b"/parade/override/reset" not in before

    client.post(
        "/parade/override",
        data={"variant": "morning", "person_id": str(tpid), "target": "mc"},
    )
    after = client.get("/parade/morning").data
    assert b"overrides-active" in after
    assert b"/parade/override/reset" in after
