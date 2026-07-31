"""P10.5 — the in-message drag sheet.

There is no JS runner in this suite, so the boundary is deliberate: these tests
pin the SERVER's half of the contract — which lines are draggable, which blocks
are drop targets, which people carry a conflict note, and that the hidden <pre>
the Copy button reads is still byte-exact build_doc text. Real dragging (the
dragstart/drop/modal choreography in app.js) is browser smoke, not pytest.

The load-bearing invariant is that the interactive sheet and the copyable text
come from ONE source (`sheet_sections`), so the sheet's own lines are asserted to
reassemble into that very text.
"""
import html as htmlmod
import re
from datetime import timedelta

from app.domain import parade as parade_domain
from app.domain.dates import today_sgt
from app.domain.types import (
    ALLOWED_OVERRIDE_TARGETS,
    DayPart,
    LeaveType,
    OverrideCategory,
    ParadeVariant,
    Rank,
    RequestStatus,
    Service,
    StatusType,
)
from app.extensions import db
from app.models import LeaveRequest, Person, StatusEntry
from app.services import parade_service
from tests.conftest import login

TODAY = today_sgt()
TOMORROW = TODAY + timedelta(days=1)


def _pid(app, username):
    with app.app_context():
        return db.session.query(Person.id).filter_by(username=username).scalar()


def _plant_status(app, username, *, type_, in_camp, start=TODAY, end=TODAY, remarks=None):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        keyer_id = db.session.query(Person.id).filter_by(username="sh_keyer").scalar()
        db.session.add(
            StatusEntry(
                person_id=person_id, type=type_, start_date=start, end_date=end,
                day_part=DayPart.FULL, in_camp=in_camp, remarks=remarks,
                created_by_id=keyer_id,
            )
        )
        db.session.commit()


def _plant_leave(app, username, *, type_=LeaveType.LL, day_part=DayPart.FULL,
                 start=TODAY, end=TODAY):
    with app.app_context():
        person_id = db.session.query(Person.id).filter_by(username=username).scalar()
        db.session.add(
            LeaveRequest(
                person_id=person_id, type=type_, start_date=start, end_date=end,
                day_part=day_part, status=RequestStatus.APPROVED,
            )
        )
        db.session.commit()


def _pre_text(html, pre_id):
    body = re.search(rf'<pre id="{pre_id}"[^>]*>(.*?)</pre>', html, re.S).group(1)
    return htmlmod.unescape(body)


def _drop_categories(html):
    return re.findall(r'data-drop-category="([^"]+)"', html)


def _dragged_ids(html):
    return [int(m) for m in re.findall(r'data-drag-person="(\d+)"', html)]


def _conflict_ids(html):
    """{person_id: note} for every draggable line that carries a conflict."""
    found = {}
    for row in re.finditer(
        r'data-drag-person="(\d+)"(?: data-conflict="([^"]*)")?', html
    ):
        if row.group(2) is not None:
            found[int(row.group(1))] = htmlmod.unescape(row.group(2))
    return found


def _sheet_text(html):
    """Reassemble the interactive sheet back into plain document text: one line
    per .sheet-line, one blank line between .sheet-sections."""
    live = re.search(r'<div class="sheet-live" id="sheet-live">(.*?)\n  </div>', html, re.S)
    sections = re.findall(
        r'<div class="sheet-section[^"]*"[^>]*>(.*?)\n    </div>', live.group(1), re.S
    )
    blocks = []
    for section in sections:
        lines = re.findall(r'<div class="sheet-line[^"]*"[^>]*>(.*?)</div>', section, re.S)
        blocks.append("\n".join(htmlmod.unescape(line) for line in lines))
    return "\n\n".join(blocks)


def _cast(make_person):
    make_person(username="sh_keyer", is_admin=True, display_name="Key Er",
                rank=Rank.THREE_SG)
    make_person(username="sh_clean", display_name="Clean One")
    make_person(username="sh_mc", display_name="Mc One")
    make_person(username="sh_leave", display_name="Leave One")
    make_person(username="sh_pm", display_name="Pm One")
    make_person(username="sh_camp", display_name="Camp One")
    make_person(username="sh_reg", display_name="Reg One", service=Service.REGULAR)


def _plant_all(app):
    _plant_status(app, "sh_mc", type_=StatusType.MC, in_camp=False,
                  end=TOMORROW + timedelta(days=1))
    _plant_leave(app, "sh_leave", type_=LeaveType.LL, end=TOMORROW)
    _plant_leave(app, "sh_pm", type_=LeaveType.OFF, day_part=DayPart.PM)
    _plant_status(app, "sh_camp", type_=StatusType.OTHER, in_camp=True, remarks="BDO")


# --- the copy source is untouched -------------------------------------------

def test_hidden_pre_is_byte_equal_to_build_doc_text(app, client, make_person):
    _cast(make_person)
    _plant_all(app)
    login(client, "sh_keyer")
    html = client.get("/parade/morning").get_data(as_text=True)
    with app.app_context():
        built = parade_service.build_doc(TODAY, ParadeVariant.MORNING)
    assert 'id="paradetext" hidden' in html
    assert _pre_text(html, "paradetext") == built.text


def test_sheet_lines_reassemble_into_the_document_text(app, client, make_person):
    _cast(make_person)
    _plant_all(app)
    login(client, "sh_keyer")
    html = client.get("/parade/morning").get_data(as_text=True)
    # The sheet and the <pre> are two projections of ONE section list — the
    # markup must fold back to exactly the text the Copy button hands over.
    assert _sheet_text(html) == _pre_text(html, "paradetext")


# --- what is draggable, and where it can go ---------------------------------

def test_every_person_appears_exactly_once_as_a_draggable_line(app, client, make_person):
    _cast(make_person)
    _plant_all(app)
    login(client, "sh_keyer")
    html = client.get("/parade/morning").get_data(as_text=True)
    ids = _dragged_ids(html)
    with app.app_context():
        roster_ids = {pid for (pid,) in db.session.query(Person.id)}
    assert sorted(ids) == sorted(roster_ids)
    assert len(ids) == len(set(ids))


def test_drop_zones_are_exactly_the_variants_allowed_targets(app, client, make_person):
    _cast(make_person)
    login(client, "sh_keyer")
    for path, variant in (
        ("/parade/morning", ParadeVariant.MORNING),
        ("/parade/roll-call", ParadeVariant.ROLL_CALL),
        ("/parade/cos-message", ParadeVariant.COS_MESSAGE),
    ):
        html = client.get(path).get_data(as_text=True)
        zones = _drop_categories(html)
        assert len(zones) == len(set(zones)), path
        assert {OverrideCategory(z) for z in zones} == ALLOWED_OVERRIDE_TARGETS[variant], path


def test_cos_remove_strip_only_on_the_cos_message(app, client, make_person):
    _cast(make_person)
    login(client, "sh_keyer")
    cos = client.get("/parade/cos-message").get_data(as_text=True)
    assert "drop-zone--remove" in cos
    # It is the D4 "present" target, and the only current_strength zone there.
    assert cos.count('data-drop-category="current_strength"') == 1
    for path in ("/parade/morning", "/parade/roll-call"):
        assert "drop-zone--remove" not in client.get(path).get_data(as_text=True)


# --- conflict notes (D7) -----------------------------------------------------

def test_conflict_attribute_marks_people_resting_on_keyed_data(app, client, make_person):
    _cast(make_person)
    _plant_all(app)
    login(client, "sh_keyer")
    html = client.get("/parade/morning").get_data(as_text=True)
    notes = _conflict_ids(html)

    assert "MC" in notes[_pid(app, "sh_mc")]
    assert "LL" in notes[_pid(app, "sh_leave")]
    assert "OFF" in notes[_pid(app, "sh_pm")]      # PM partial — present, but keyed
    assert "Other" in notes[_pid(app, "sh_camp")]  # in-camp annotation
    # A clean present NSF and a plain stay-out regular drag without a prompt.
    assert _pid(app, "sh_clean") not in notes
    assert _pid(app, "sh_reg") not in notes


# --- keyer gating ------------------------------------------------------------

def test_keyer_sees_the_sheet_form_and_modal(app, client, make_person):
    _cast(make_person)
    login(client, "sh_keyer")
    html = client.get("/parade/morning").get_data(as_text=True)
    assert 'id="sheet-live"' in html
    assert 'id="override-form"' in html
    assert 'id="drag-confirm"' in html
    assert 'role="dialog"' in html


def test_plain_user_sees_sheet_but_no_fp_form(app, client, make_person):
    # Owner decision 2026-07-31: the drag sheet is open to every logged-in user.
    # The FP quick-add beneath it is the keyer-gated part, and stays hidden.
    _cast(make_person)
    make_person(username="sh_plain", display_name="Plain One")  # OPR NSF, no keying
    login(client, "sh_plain")
    html = client.get("/parade/morning").get_data(as_text=True)
    assert 'id="sheet-live"' in html
    assert 'id="override-form"' in html
    assert "Not joining FP" not in html
    with app.app_context():
        built = parade_service.build_doc(TODAY, ParadeVariant.MORNING)
    assert _pre_text(html, "paradetext") == built.text


# --- the Moves-active badge and Reset ---------------------------------------

def test_badge_and_reset_only_once_a_move_is_stored(app, client, make_person):
    _cast(make_person)
    login(client, "sh_keyer")
    before = client.get("/parade/morning").get_data(as_text=True)
    assert "moves-active" not in before
    assert "/parade/override/reset" not in before

    client.post(
        "/parade/override",
        data={
            "variant": "morning", "person_id": str(_pid(app, "sh_clean")),
            "target": "mc",
        },
    )
    after = client.get("/parade/morning").get_data(as_text=True)
    assert "moves-active" in after
    assert "/parade/override/reset" in after


def test_reset_still_renders_when_the_document_is_out_of_balance(
    app, client, make_person, monkeypatch
):
    # D6: a stored move that unbalances the document must not brick the page —
    # the imbalance card carries its own Reset so one click gets back out.
    _cast(make_person)
    login(client, "sh_keyer")
    client.post(
        "/parade/override",
        data={
            "variant": "morning", "person_id": str(_pid(app, "sh_clean")),
            "target": "mc",
        },
    )

    def _boom(day, pairs, variant):
        raise parade_domain.ParadeImbalance("induced for test")

    monkeypatch.setattr(parade_domain, "categorize", _boom)
    html = client.get("/parade/morning").get_data(as_text=True)
    assert "out of balance" in html
    assert 'id="sheet-live"' not in html
    assert "/parade/override/reset" in html
