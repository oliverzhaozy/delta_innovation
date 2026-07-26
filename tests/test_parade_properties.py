"""P3b.4 — invariant property test: the parade balance guarantee must hold for
EVERY day the COS will ever compile, not just the three pinned goldens
(test_morning_parade / test_roll_call / test_cos_message). A seeded generator
(`random.Random(seed)`) builds a random roster of fake people with random
leave/status rows and drives it through the REAL pipeline
(presence.resolve -> categorize/compute_cos_message -> render_*).

Every check here is re-derived independently — from the RENDERED text, not
from ParadeDoc's own fields — because the whole point is to catch a drift
between the compute layer and the renderer that both sides could otherwise
agree on by construction (the same bug baked into both the producer and the
"trusted" checker would slip past a test that reused ParadeDoc's own len()).
"""
import random
import re
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.domain import parade
from app.domain.presence import PresenceState, resolve
from app.domain.types import (
    Appointment, DayPart, LeaveType, Rank, Service, StatusType,
)

D = date(2026, 7, 6)  # D, the day the parade docs are compiled for.

_APPOINTMENTS = list(Appointment)
_RANKS = list(Rank)
_PLATOONS = (None, 1, 2, 3)
_SERVICES = list(Service)
_LEAVE_TYPES = list(LeaveType)
_STATUS_TYPES = list(StatusType)
_DAY_PARTS = list(DayPart)

# Every rendered "TITLE (N):" header — the same shape _category_block emits —
# parsed independently of the ParadeDoc/CosDoc fields that produced it.
_HEADER_RE = re.compile(r"^(.+?) \((\d+)\):$")


# --- generator (roster x absences x statuses x day-parts) ------------------

def _random_range(rng, day_part):
    # Half-day rows are single-day (decision (i) only defines AM/PM within one
    # day); FULL rows get a range that can precede, straddle, or follow D.
    if day_part in (DayPart.AM, DayPart.PM):
        d = D + timedelta(days=rng.randint(-3, 3))
        return d, d
    start = D + timedelta(days=rng.randint(-5, 3))
    end = start + timedelta(days=rng.randint(0, 6))
    return start, end


def _make_person(rng, idx):
    rank = rng.choice(_RANKS)
    return SimpleNamespace(
        id=idx,
        # Plain name (rank is its own enum column since ee20005; parade_line pairs
        # them). Fixed 3-digit width keeps one person's rendered line from ever
        # being a startswith-prefix of another's.
        display_name=f"Fake{idx:03d}",
        appointment=rng.choice(_APPOINTMENTS),
        rank=rank,
        platoon=rng.choice(_PLATOONS),
        service=rng.choice(_SERVICES),
        stay_out=rng.choice((True, False)),
        is_active=True,  # presence_inputs is active-only; deactivated never reaches a parade
    )


def _leave_rows(rng):
    rows = []
    for _ in range(rng.randint(0, 2)):
        day_part = rng.choice(_DAY_PARTS)
        start, end = _random_range(rng, day_part)
        rows.append(SimpleNamespace(
            type=rng.choice(_LEAVE_TYPES), start_date=start, end_date=end, day_part=day_part,
        ))
    return rows


def _status_rows(rng):
    rows = []
    for _ in range(rng.randint(0, 2)):
        day_part = rng.choice(_DAY_PARTS)
        start, end = _random_range(rng, day_part)
        rows.append(SimpleNamespace(
            type=rng.choice(_STATUS_TYPES), start_date=start, end_date=end, day_part=day_part,
            in_camp=rng.choice((True, False)), remarks=None,
        ))
    return rows


def _build_roster(rng):
    people = [_make_person(rng, i) for i in range(rng.randint(3, 40))]
    people.sort(key=parade.parade_sort_key)  # feed categorize already parade-sorted
    pairs = []
    for p in people:
        res = resolve(
            p, D,
            leaves=_leave_rows(rng),
            statuses=_status_rows(rng),
        )
        pairs.append((p, res))
    return pairs


# --- independent rendered-text parsing (never touches ParadeDoc fields) ----

def _parse_blocks(rendered):
    """{HEADER TITLE: (declared_count, [numbered body lines])} read straight
    off the rendered text — parsing the text, not trusting ParadeDoc's own
    len() mechanism, is the entire point of this check."""
    lines = rendered.split("\n")
    blocks = {}
    i = 0
    while i < len(lines):
        m = _HEADER_RE.match(lines[i])
        if m:
            title, count = m.group(1), int(m.group(2))
            body = []
            j = i + 1
            while j < len(lines) and lines[j] and not _HEADER_RE.match(lines[j]):
                body.append(lines[j])
                j += 1
            blocks[title] = (count, body)
            i = j
        else:
            i += 1
    return blocks


def _parse_strength(rendered, label):
    # Strength summary lines ("TOTAL STRENGTH: 7") use "LABEL: N", distinct
    # from the "(N):" category-header shape _HEADER_RE parses.
    m = re.search(rf"^{label}: (\d+)$", rendered, re.MULTILINE)
    assert m, f"{label} line missing from rendered text"
    return int(m.group(1))


# PRESENT IN CAMP / NOT PRESENT IN CAMP are aggregate summary lines, not list
# headers: nothing is numbered directly under them (the next line is a blank,
# then a DIFFERENT category header) — their correctness is exactly assertion
# 3's aggregate-sum check below, so they're excluded here rather than failing
# a check that was never their shape.
_AGGREGATE_HEADERS = frozenset({"PRESENT IN CAMP", "NOT PRESENT IN CAMP"})


def _assert_headers_match_bodies(blocks):
    for title, (count, body) in blocks.items():
        if title in _AGGREGATE_HEADERS:
            continue
        assert count == len(body), f"{title}: header says {count}, {len(body)} lines follow"


def _all_doc_lines(doc):
    return (
        doc.current_strength + doc.others_in_camp + doc.leave + doc.off_oil
        + doc.on_course + doc.mc + doc.others + doc.stay_out
    )


def _occurrences(doc, person):
    # OTHERS IN CAMP appends " (REASON)" to the plain parade_line, so match by
    # equality or by that specific suffix — never a bare substring search,
    # which could false-positive on one person's name being another's prefix.
    line = parade.parade_line(person)
    return sum(
        1 for candidate in _all_doc_lines(doc)
        if candidate == line or candidate.startswith(line + " (")
    )


# --- the property test -------------------------------------------------------

@pytest.mark.parametrize("seed", range(5))
def test_parade_invariants_hold_for_a_random_roster(seed):
    rng = random.Random(seed)
    pairs = _build_roster(rng)
    roster_size = len(pairs)

    morning_doc = parade.categorize(D, pairs, "morning")
    roll_doc = parade.categorize(D, pairs, "roll_call")
    cos_person = _make_person(rng, -1)  # COS is the greeting subject only, not a roster member
    cos_doc = parade.compute_cos_message(D, cos_person, pairs)

    morning_text = parade.render_morning(morning_doc)
    roll_text = parade.render_roll_call(roll_doc)
    cos_text = parade.render_cos(cos_doc)

    # 1. Exactly-once: every roster person appears in exactly one category of
    # the morning doc and the roll-call doc (COS legitimately omits people).
    for person, _res in pairs:
        assert _occurrences(morning_doc, person) == 1
        assert _occurrences(roll_doc, person) == 1

    # 2. Header == list, parsed from rendered text — independent verification
    # for all three documents, not just morning/roll_call.
    morning_blocks = _parse_blocks(morning_text)
    roll_blocks = _parse_blocks(roll_text)
    cos_blocks = _parse_blocks(cos_text)
    _assert_headers_match_bodies(morning_blocks)
    _assert_headers_match_bodies(roll_blocks)
    _assert_headers_match_bodies(cos_blocks)

    # 3. Totals balance, parsed from rendered text (never doc.total).
    m_total = _parse_strength(morning_text, "TOTAL STRENGTH")
    m_current = _parse_strength(morning_text, "CURRENT STRENGTH")
    m_absent = _parse_strength(morning_text, "ABSENT STRENGTH")
    assert m_total == roster_size
    c = morning_blocks["PRESENT IN CAMP"][0]
    k = morning_blocks["OTHERS IN CAMP"][0]
    assert morning_blocks["CURRENT STRENGTH"][0] == m_current
    assert c == m_current + k  # C = A + K
    d_categories = ("LEAVE", "OFF/OIL", "ON COURSE", "MC", "OTHERS")
    assert sum(morning_blocks[name][0] for name in d_categories) == m_absent
    assert morning_blocks["NOT PRESENT IN CAMP"][0] == m_absent
    assert m_total == c + m_absent  # T = C + D

    r_total = _parse_strength(roll_text, "TOTAL STRENGTH")
    r_current = _parse_strength(roll_text, "CURRENT STRENGTH")
    r_absent = _parse_strength(roll_text, "ABSENT STRENGTH")
    assert r_total == roster_size
    assert roll_blocks["OTHERS IN CAMP"][0] == 0  # roll call: always the literal 0
    r_c = roll_blocks["PRESENT IN CAMP"][0]
    assert r_c == r_current  # C = A (+0)
    assert roll_blocks["CURRENT STRENGTH"][0] == r_current
    b_categories = ("STAY OUT", "LEAVE", "OFF/OIL", "ON COURSE", "MC", "OTHERS")
    assert sum(roll_blocks[name][0] for name in b_categories) == r_absent
    assert roll_blocks["NOT PRESENT IN CAMP"][0] == r_absent
    assert r_total == r_c + r_absent  # T = C + D

    # 4. COS message: every listed person is a roster member in a reportable
    # state; no PRESENT-state person appears; counts already checked above.
    reportable = {
        parade.parade_line(p) for p, res in pairs
        if res.state in (PresenceState.ABSENT, PresenceState.STAY_OUT)
    }
    present_lines = {
        parade.parade_line(p) for p, res in pairs if res.state is PresenceState.PRESENT
    }
    listed = set()
    for _title, (_count, body) in cos_blocks.items():
        for line in body:
            listed.add(line.split(". ", 1)[1])
    assert listed <= reportable
    assert not (listed & present_lines)


# --- 5. totality: an unmapped absence-row kind must raise, never land in OTHERS

class _BogusKind:
    """A `row.type` value that is none of LeaveType/StatusType
    — `_absent_category` has no branch for it, so it must raise rather than
    silently bucket the row into OTHERS (the "unmapped source raises"
    done-criterion this task adds test coverage for)."""


@pytest.mark.parametrize("via", ["leaves", "statuses"])
def test_unmapped_absence_kind_raises_instead_of_falling_into_others(via):
    person = _make_person(random.Random(0), 0)
    bogus_row = SimpleNamespace(
        type=_BogusKind(), start_date=D, end_date=D, day_part=DayPart.FULL, in_camp=False,
    )
    res = resolve(person, D, **{via: [bogus_row]})
    assert res.state is PresenceState.ABSENT  # resolve() never inspects `.type`
    with pytest.raises(parade.ParadeImbalance):
        parade.categorize(D, [(person, res)], "morning")
    with pytest.raises(parade.ParadeImbalance):
        parade.compute_cos_message(D, person, [(person, res)])
