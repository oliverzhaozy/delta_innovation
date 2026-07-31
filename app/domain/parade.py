"""Parade display order, line format, and morning-parade compute (Phase 3a).
Pure: stdlib + sibling app.domain modules only, so the ordering, category
mapping, and byte-exact rendering are all testable without an app or a DB.

The renderer is deliberately pure Python, NOT a Jinja text template (the
TECH_PLAN "Jinja text templates" line): hand-built strings dodge
template-whitespace landmines so the golden tests can pin the output to
docs/PARADE_FORMATS.md byte-for-byte.
"""
import bisect
import dataclasses
from collections import namedtuple
from dataclasses import dataclass
from datetime import date
from typing import Mapping

from app.domain.dates import format_ddmmyy, format_ddmmyy_range
from app.domain.presence import PresenceState
from app.domain.types import (
    ALLOWED_OVERRIDE_TARGETS,
    Appointment,
    CourseAbsenceType,
    LeaveType,
    OverrideCategory,
    ParadeVariant,
    Rank,
    StatusType,
)

# Decision (g): parade display order, NOT the SPEC.md chain of command (which
# lists SM above 2IC) — the owner's sample governs how the roster is printed.
# Decision (h): OC DES / CSM DES are not enum members yet; their slots are
# documented here as comments so the tuple below is correct on the day the
# unit actually creates those appointments.
_PARADE_APPOINTMENT_SEQUENCE = (
    Appointment.OC,
    # OC DES slots here (decision h) — not an enum member until Delta has one.
    Appointment.TWO_IC,
    Appointment.SM,
    # CSM DES slots here (decision h) — not an enum member until Delta has one.
    Appointment.PC,
    Appointment.P2IC,
    Appointment.PS,
    Appointment.DET_COMD,
    Appointment.OPR,
)
PARADE_APPOINTMENT_ORDER: dict = {
    appointment: idx for idx, appointment in enumerate(_PARADE_APPOINTMENT_SEQUENCE)
}

# Decision (g): 3WO is hoisted above LTA per the unit's own convention — this
# is display-only and deliberately diverges from the legal `RANK_ORDER` used
# for duty eligibility (see tests/test_parade_order.py). MSG and 1SG were
# unlisted in the original spec's rank line; they slot at their legal-order
# positions either side of SSG per the owner's decision.
_PARADE_RANK_SEQUENCE = (
    Rank.CPT,
    Rank.THREE_WO,
    Rank.LTA,
    Rank.TWO_LT,
    Rank.MSG,
    Rank.SSG,
    Rank.ONE_SG,
    Rank.TWO_SG,
    Rank.THREE_SG,
    Rank.CFC,
    Rank.CPL,
    Rank.LCP,
    Rank.PTE,
)
PARADE_RANK_ORDER: dict = {rank: idx for idx, rank in enumerate(_PARADE_RANK_SEQUENCE)}


def parade_sort_key(person) -> tuple:
    """Sort key for parade display: appointment, then rank, then platoon, then
    keyed (id) order — never alphabetical (owner's explicit "do not
    alphabetize" rule), so two same-rank people keep roster/creation order.
    """
    platoon_key = person.platoon or 0  # None (HQ/command team) sorts first.
    return (
        PARADE_APPOINTMENT_ORDER[person.appointment],
        PARADE_RANK_ORDER[person.rank],
        platoon_key,
        person.id,
    )


def parade_line(person) -> str:
    # display_name holds the plain name only; rank is a separate enum column
    # (since ee20005). This is the SINGLE place the "RANK NAME" pairing happens —
    # every renderer, the COS greeting, and the OTHERS-IN-CAMP lines go through it.
    return f"{person.rank.value} {person.display_name}".upper()


# Category field name -> the printed block title. The renderers read titles from
# here rather than repeating literals, so a title lives in exactly one place.
# Values are byte-identical to the strings the goldens pin — this dict is a
# lookup, not a wording change.
CATEGORY_TITLES = {
    "current_strength": "CURRENT STRENGTH",
    "others_in_camp": "OTHERS IN CAMP",
    "stay_out": "STAY OUT",
    "leave": "LEAVE",
    "off_oil": "OFF/OIL",
    "on_course": "ON COURSE",
    "mc": "MC",
    "others": "OTHERS",
}

# The full set of ParadeDoc category fields (categorize() populates all eight);
# CosDoc carries the six night/absent categories only.
_PARADE_CATEGORIES = (
    "current_strength", "others_in_camp", "leave", "off_oil",
    "on_course", "mc", "others", "stay_out",
)
_COS_CATEGORIES = ("stay_out", "leave", "off_oil", "on_course", "mc", "others")


# --- morning parade compute (P3a.6) --------------------------------------
#
# The category compute turns presence resolutions into the exact category
# lists the WhatsApp document shows, and the renderer prints them byte-exact.


class ParadeImbalance(Exception):
    """A parade document whose category math cannot balance — a double-counted
    person or a drifted total. We raise instead of rendering: a document the app
    knows is wrong is worse than none (the single-source-of-truth promise).
    """


@dataclass(frozen=True)
class ParadeDoc:
    """One parade document's finished category lists, as already-rendered line
    bodies (the `RANK NAME`, plus `(REASON)` for OTHERS IN CAMP) AND the parallel
    tuple of source PERSON objects for each category (`*_people`).

    Holding rendered bodies is what the renderers read, so the header counts are
    `len()` of the very tuple that renders and a count can never disagree with
    the list beneath it. The parallel person tuples ride alongside for consumers
    that need the people, not the strings — meals (P3b.5) counts CURRENT STRENGTH
    and PRESENT IN CAMP persons and their NSF sub-set. A second parallel tuple set
    (`*_notes`) carries the AbsenceNote each absent line's suffix was rendered
    from (None on a bare line), so the drag sheet can show it as a chip without
    re-parsing the line. Renderers ignore both, so every existing golden stays
    byte-identical. `total` is the input headcount; every balance check compares
    category lengths back to it.

    `stay_out` is populated for the roll_call variant only; on morning it is
    always empty (STAY OUT dissolves into CURRENT STRENGTH — Message 3 rule).
    """

    day: date
    variant: str
    total: int
    current_strength: tuple = ()
    others_in_camp: tuple = ()
    leave: tuple = ()
    off_oil: tuple = ()
    on_course: tuple = ()
    mc: tuple = ()
    others: tuple = ()
    stay_out: tuple = ()
    # Parallel person tuples (default empty so hand-built line-only docs still
    # construct and validate). categorize() always populates them in lockstep
    # with the line tuples above.
    current_strength_people: tuple = ()
    others_in_camp_people: tuple = ()
    leave_people: tuple = ()
    off_oil_people: tuple = ()
    on_course_people: tuple = ()
    mc_people: tuple = ()
    others_people: tuple = ()
    stay_out_people: tuple = ()
    # Parallel AbsenceNote tuples (None per bare line), same default reasoning as
    # the person tuples above. Never read by the renderers — only by the sheet.
    current_strength_notes: tuple = ()
    others_in_camp_notes: tuple = ()
    leave_notes: tuple = ()
    off_oil_notes: tuple = ()
    on_course_notes: tuple = ()
    mc_notes: tuple = ()
    others_notes: tuple = ()
    stay_out_notes: tuple = ()

    def _not_present(self) -> tuple:
        # Morning has no STAY OUT category; roll call counts it under D.
        base = (self.leave, self.off_oil, self.on_course, self.mc, self.others)
        return base if self.variant == "morning" else (self.stay_out, *base)

    def _people_buckets(self) -> tuple:
        # Same variant-aware structure as the line buckets, over the person
        # tuples — used for the person-identity dedup in validate().
        present = (self.current_strength_people, self.others_in_camp_people)
        base = (
            self.leave_people, self.off_oil_people, self.on_course_people,
            self.mc_people, self.others_people,
        )
        not_present = base if self.variant == "morning" else (self.stay_out_people, *base)
        return (*present, *not_present)

    def validate(self) -> "ParadeDoc":
        """Raise ParadeImbalance unless the document balances, else return self.

        Two failure modes, both fatal: counts that don't sum to the total
        (T = C + D), or the same rendered line in two categories (a person
        placed twice). Exposed so a hand-built corrupted doc can be checked
        directly, and called by both categorize and render_morning.
        """
        present = (self.current_strength, self.others_in_camp)
        if self.variant == "morning" and self.stay_out:
            raise ParadeImbalance("morning parade has no STAY OUT category")
        # Symmetric to the above: in-camp promotion is morning-only, so roll call
        # never has OTHERS IN CAMP people (its header is a literal 0). A doc that
        # populates it is corrupt — refuse it, keeping the "(0)" header honest.
        if self.variant == "roll_call" and self.others_in_camp:
            raise ParadeImbalance("roll call has no OTHERS IN CAMP category")
        buckets = (*present, *self._not_present())
        covered = sum(len(b) for b in buckets)
        if covered != self.total:
            raise ParadeImbalance(
                f"category headcount {covered} != total strength {self.total}"
            )
        # Exactly-once dedup keys on person identity (id), not the rendered line:
        # two DISTINCT people who share rank+name render identical lines and must
        # BOTH be allowed to stand (closes a P3a.6 minor). Falls back to line
        # dedup for hand-built line-only docs, which carry no person tuples.
        people = [p for bucket in self._people_buckets() for p in bucket]
        if people:
            ids = [p.id for p in people]
            if len(set(ids)) != len(ids):
                raise ParadeImbalance("a person appears in more than one category")
        else:
            lines = [line for bucket in buckets for line in bucket]
            if len(set(lines)) != len(lines):
                raise ParadeImbalance("a person appears in more than one category")
        return self


def _absent_category(row) -> str:
    """The category a winning ABSENT row belongs to, by the PARADE_FORMATS
    mapping. Discriminated on the enum class of `row.type` — the one attribute
    every source row shares — so no source-specific attribute sniffing:
    LeaveType → OFF/OIL or LEAVE, CourseAbsenceType → ON COURSE, StatusType →
    MC or OTHERS (an out-of-camp status; in-camp ones are never absent-making,
    so they never reach here). ON COURSE has exactly one source since P9.5 —
    the TP calendar — so no status can land there.
    """
    kind = row.type
    if isinstance(kind, LeaveType):
        return "off_oil" if kind in (LeaveType.OFF, LeaveType.OIL) else "leave"
    if isinstance(kind, CourseAbsenceType):
        return "on_course"
    if isinstance(kind, StatusType):
        return "mc" if kind is StatusType.MC else "others"  # out-of-camp OTHER
    raise ParadeImbalance(f"unclassifiable absence row: {row!r}")


def _in_camp_reason(row) -> str:
    # Reason for an OTHERS IN CAMP line: the keyer's remark ("BDO"), else the
    # status type's label. Uppercased to sit with the all-caps line.
    return (row.remarks or row.type.label).upper()


# The suffix every ABSENT line carries (owner 2026-07-27), as DATA rather than a
# baked-in string: `reason` is None when the category already names it. Held on
# the document beside the rendered line so the drag sheet can show it as a chip
# — and so a keyer's typed note (owner revision 2026-07-30) is the same shape as
# a derived one and renders through the same one formatter.
AbsenceNote = namedtuple("AbsenceNote", "reason start end")


def absence_note(row) -> AbsenceNote:
    """The AbsenceNote a winning ABSENT row dictates.

    Discriminated on the row's kind exactly as `_absent_category` is: LEAVE /
    OFF-OIL / MC carry no reason, because the category itself already names it;
    ON COURSE and OTHERS lead with one ("SIG COURSE", "HL") since the category
    alone does not say which course or which excuse. The reason falls back to the
    type's label the same way `_in_camp_reason` does — a course cover always
    carries the TP event title as its remarks — and is uppercased HERE, once, so
    every consumer holds a print-ready string.
    """
    kind = row.type
    if isinstance(kind, LeaveType) or kind is StatusType.MC:
        reason = None
    else:
        reason = (row.remarks or kind.label).upper()
    return AbsenceNote(reason=reason, start=row.start_date, end=row.end_date)


def note_display(note: AbsenceNote) -> str:
    """The ONE owner of the note's printed form: "DDMMYY - DDMMYY", or
    "REASON: DDMMYY - DDMMYY" when the note names a reason (a one-day range
    collapses inside format_ddmmyy_range). Every rendering of a note — the
    parade line's parenthesized suffix and the drag sheet's chip — is this
    string, so the two can never describe one note differently.
    """
    dates = format_ddmmyy_range(note.start, note.end)
    if note.reason is None:
        return dates
    return f"{note.reason}: {dates}"


def note_suffix(note: AbsenceNote) -> str:
    return f"({note_display(note)})"


def categorize(day, pairs, variant: str) -> ParadeDoc:
    """Bucket parade-sorted `(person, resolution)` pairs into a ParadeDoc for
    `variant` ∈ {"morning", "roll_call"}. Order within a category follows the
    input (already parade-sorted upstream).

    Each person lands in exactly one category: ABSENT by the winning row's kind;
    otherwise CURRENT STRENGTH — except on morning an in-camp annotation
    promotes them to OTHERS IN CAMP, and on roll call a STAY_OUT person goes to
    STAY OUT (in-camp annotations are dropped there — morning-only).
    """
    if variant not in ("morning", "roll_call"):
        raise ValueError(f"unknown parade variant: {variant!r}")
    names = (
        "current_strength", "others_in_camp", "leave", "off_oil",
        "on_course", "mc", "others", "stay_out",
    )
    lines: dict[str, list] = {name: [] for name in names}
    people: dict[str, list] = {name: [] for name in names}
    notes: dict[str, list] = {name: [] for name in names}
    for person, resolution in pairs:
        state = resolution.state
        # The note is built FIRST and the line rendered from it, so the stored
        # note and the printed suffix cannot say different things.
        note = None
        if state is PresenceState.ABSENT:
            bucket = _absent_category(resolution.row)
            note = absence_note(resolution.row)
            line = f"{parade_line(person)} {note_suffix(note)}"
        elif variant == "morning" and resolution.in_camp_rows:
            reason = _in_camp_reason(resolution.in_camp_rows[0])
            bucket = "others_in_camp"
            line = f"{parade_line(person)} ({reason})"
        elif variant == "roll_call" and state is PresenceState.STAY_OUT:
            bucket = "stay_out"
            line = parade_line(person)
        else:  # PRESENT / DUTY, and morning STAY_OUT → current strength
            bucket = "current_strength"
            line = parade_line(person)
        lines[bucket].append(line)
        people[bucket].append(person)
        notes[bucket].append(note)

    doc = ParadeDoc(
        day=day,
        variant=variant,
        total=len(pairs),
        **{name: tuple(lines[name]) for name in names},
        **{f"{name}_people": tuple(people[name]) for name in names},
        **{f"{name}_notes": tuple(notes[name]) for name in names},
    )
    return doc.validate()


# --- structured sections (P10.2) -----------------------------------------
#
# One document renders in two places: the copyable WhatsApp text and (for a
# keyer) the interactive drag sheet. sheet_sections is the SINGLE source both
# read, so the two can never drift — the renderers are literally a join over it.

# person_id is None only for a hand-built line-only doc (no `*_people` tuples);
# such an entry still renders but carries nothing to drag. `text` is the whole
# numbered line and is what the copyable document is joined from. `body`/`note`
# are the SAME line split at its suffix — filled only for a noted line — so an
# interactive surface can print the note as a chip; `f"{body} ({note})" == text`
# by construction, which is what keeps the two projections identical.
SheetEntry = namedtuple("SheetEntry", "person_id text body note", defaults=(None, None))

# key/title None marks inert chrome (title+date, strength lines, the "——" rules,
# umbrella headers, the greeting, roll call's literal OTHERS IN CAMP line); a set
# key names the ParadeDoc/CosDoc field the section prints, i.e. a drop target.
SheetSection = namedtuple("SheetSection", "key title text entries")


def _plain(text: str) -> SheetSection:
    return SheetSection(key=None, title=None, text=text, entries=())


def _sheet_entry(n: int, line: str, person, note) -> SheetEntry:
    """One numbered line as a SheetEntry. `body`/`note` are filled only when the
    line HAS a note and the person behind it is known (a hand-built line-only doc
    has neither) — everything else carries `text` alone, and the numbering is the
    same `n` in both, so the two forms stay one line.
    """
    text = f"{n}. {line}"
    if person is None:
        return SheetEntry(person_id=None, text=text)
    if note is None:
        return SheetEntry(person_id=person.id, text=text)
    return SheetEntry(
        person_id=person.id,
        text=text,
        body=f"{n}. {parade_line(person)}",
        note=note_display(note),
    )


def _category_section(doc, name: str) -> SheetSection:
    """One printed category as a section: the header, then one SheetEntry per
    line. The "N. " numbering happens HERE and nowhere else, and the section's
    text is assembled from those very entries — so a numbered line on the drag
    sheet and the same line in the copied text are the same string by
    construction. Header count is len() of the tuple that renders below it, so
    the two cannot disagree; an empty category is the header alone.
    """
    lines = getattr(doc, name)
    people = getattr(doc, f"{name}_people") or (None,) * len(lines)
    notes = getattr(doc, f"{name}_notes") or (None,) * len(lines)
    entries = tuple(
        _sheet_entry(n, line, person, note)
        for n, (line, person, note) in enumerate(zip(lines, people, notes), 1)
    )
    title = CATEGORY_TITLES[name]
    header = f"{title} ({len(lines)}):"
    return SheetSection(
        key=name,
        title=title,
        text="\n".join([header, *(entry.text for entry in entries)]),
        entries=entries,
    )


def _morning_sections(doc: ParadeDoc) -> tuple:
    a = len(doc.current_strength)
    k = len(doc.others_in_camp)
    c = a + k
    d = len(doc.leave) + len(doc.off_oil) + len(doc.on_course) + len(doc.mc) + len(doc.others)
    # B (absent strength) == D by definition on the morning state; deriving it
    # here keeps the header pair from ever drifting apart.
    return (
        _plain(f"DELTA MORNING PARADE STATE:\n{format_ddmmyy(doc.day)}"),
        _plain(f"TOTAL STRENGTH: {doc.total}"),
        _plain(f"CURRENT STRENGTH: {a}"),
        _plain(f"ABSENT STRENGTH: {d}"),
        _plain("——"),
        _plain(f"PRESENT IN CAMP ({c}):"),
        _category_section(doc, "current_strength"),
        _category_section(doc, "others_in_camp"),
        _plain("——"),
        _plain(f"NOT PRESENT IN CAMP ({d}):"),
        _category_section(doc, "leave"),
        _category_section(doc, "off_oil"),
        _category_section(doc, "on_course"),
        _category_section(doc, "mc"),
        _category_section(doc, "others"),
    )


def _roll_call_sections(doc: ParadeDoc) -> tuple:
    a = len(doc.current_strength)
    # PRESENT IN CAMP is exactly CURRENT STRENGTH: OTHERS IN CAMP is always 0.
    c = a
    d = (
        len(doc.stay_out) + len(doc.leave) + len(doc.off_oil)
        + len(doc.on_course) + len(doc.mc) + len(doc.others)
    )
    # B (absent strength) == D by definition; deriving it here keeps the header
    # pair from ever drifting apart.
    return (
        _plain(f"DELTA ROLL CALL STATE:\n{format_ddmmyy(doc.day)}"),
        _plain(f"TOTAL STRENGTH: {doc.total}"),
        _plain(f"CURRENT STRENGTH: {a}"),
        _plain(f"ABSENT STRENGTH: {d}"),
        _plain("——"),
        _plain(f"PRESENT IN CAMP ({c}):"),
        _category_section(doc, "current_strength"),
        # Literal 0, and INERT, by rule — not a category section on the (empty)
        # tuple, so nothing can be dropped into a bucket roll call does not have.
        _plain(f"{CATEGORY_TITLES['others_in_camp']} (0):"),
        _plain("——"),
        _plain(f"NOT PRESENT IN CAMP ({d}):"),
        _category_section(doc, "stay_out"),
        _category_section(doc, "leave"),
        _category_section(doc, "off_oil"),
        _category_section(doc, "on_course"),
        _category_section(doc, "mc"),
        _category_section(doc, "others"),
    )


def sheet_sections(doc) -> tuple:
    """The section list behind BOTH renderings of `doc` — the plain WhatsApp
    text (a join over `.text`) and the keyer's interactive sheet (which iterates
    the same objects). Section order mirrors the document skeletons exactly.

    Validated first: the app refuses to describe a document it knows is wrong.
    """
    doc.validate()
    if isinstance(doc, CosDoc):
        return _cos_sections(doc)
    if doc.variant == "morning":
        return _morning_sections(doc)
    if doc.variant == "roll_call":
        return _roll_call_sections(doc)
    raise ValueError(f"unknown parade variant: {doc.variant!r}")


def render_morning(doc: ParadeDoc) -> str:
    """Render the Message 3 morning parade state byte-exact to PARADE_FORMATS.md.

    Sections are joined by a single blank line (the skeleton's rhythm); the
    title+date pair is one section (no blank between them). Validated first —
    the app refuses to emit a document it knows is unbalanced.
    """
    doc.validate()
    if doc.variant != "morning":
        raise ValueError(f"render_morning expects a morning doc, got {doc.variant!r}")
    return "\n\n".join(section.text for section in _morning_sections(doc))


def render_roll_call(doc: ParadeDoc) -> str:
    """Render the Message 2 roll call state byte-exact to PARADE_FORMATS.md.

    Same section rhythm as morning (single blank line between sections; title +
    date are one section), but the NIGHT document: STAY OUT is a real NOT-PRESENT
    category (flagged stay-outs are away tonight) and OTHERS IN CAMP is ALWAYS
    header-only with a literal 0 — in-camp promotion is a morning-only rule, and
    validate() guarantees `others_in_camp` is empty here. Validated first: the
    app refuses to emit a document it knows is unbalanced.
    """
    doc.validate()
    if doc.variant != "roll_call":
        raise ValueError(f"render_roll_call expects a roll_call doc, got {doc.variant!r}")
    return "\n\n".join(section.text for section in _roll_call_sections(doc))


# --- COS message compute (P3b.1) -----------------------------------------
#
# Message 1 is a REQUEST, not a parade: it asks NSFs to report a status, so
# clean (PRESENT/DUTY) people are omitted and there is no total-strength
# invariant to balance — only the at-most-once guarantee. It reuses the exact
# row-kind mapping (_absent_category) and section builder (_category_section)
# the morning document uses, so a category can never mean two different things.


@dataclass(frozen=True)
class CosDoc:
    """Message 1 (COS request) category lists, as already-rendered line bodies.

    Like ParadeDoc, it holds rendered `RANK NAME` bodies so a header count is
    the `len()` of the very tuple it labels — count and list can never disagree.
    Unlike ParadeDoc there is NO total/balance check: the message omits present
    NSFs, so it legitimately covers only a subset of the company. `cos_display`
    is the already-uppercased "RANK NAME" the greeting prints — a string, not a
    Person, because the COS may be typed as free text and need not be on this
    app's roster at all; the six category order is the skeleton's.
    """

    day: date
    cos_display: str
    stay_out: tuple = ()
    leave: tuple = ()
    off_oil: tuple = ()
    on_course: tuple = ()
    mc: tuple = ()
    others: tuple = ()
    # Parallel person tuples (ParadeDoc precedent) — default empty so a
    # hand-built line-only CosDoc still constructs and validates. compute
    # populates them in lockstep with the line tuples above; the identity dedup
    # in validate() reads them.
    stay_out_people: tuple = ()
    leave_people: tuple = ()
    off_oil_people: tuple = ()
    on_course_people: tuple = ()
    mc_people: tuple = ()
    others_people: tuple = ()
    # Parallel AbsenceNote tuples, ParadeDoc precedent — the note each absent
    # line's suffix was rendered from, None on a bare STAY OUT line.
    stay_out_notes: tuple = ()
    leave_notes: tuple = ()
    off_oil_notes: tuple = ()
    on_course_notes: tuple = ()
    mc_notes: tuple = ()
    others_notes: tuple = ()

    def validate(self) -> "CosDoc":
        """Raise ParadeImbalance if anyone is listed twice, else return self.

        The single-state resolution already puts each person in one category, so
        compute can't produce a duplicate — but the invariant is enforced anyway
        (a hand-built or future-miswired doc must never render two lines for one
        person). No headcount check: Message 1 does not account for everyone.

        Dedup keys on person identity (id) when the person tuples are present —
        two distinct people who share rank+name render identical lines and must
        both stand — and falls back to line dedup for hand-built line-only docs.
        """
        people = [p for bucket in self._people_buckets() for p in bucket]
        if people:
            ids = [p.id for p in people]
            if len(set(ids)) != len(ids):
                raise ParadeImbalance("a person appears in more than one category")
            return self
        buckets = (
            self.stay_out, self.leave, self.off_oil,
            self.on_course, self.mc, self.others,
        )
        lines = [line for bucket in buckets for line in bucket]
        if len(set(lines)) != len(lines):
            raise ParadeImbalance("a person appears in more than one category")
        return self

    def _people_buckets(self) -> tuple:
        return (
            self.stay_out_people, self.leave_people, self.off_oil_people,
            self.on_course_people, self.mc_people, self.others_people,
        )


def compute_cos_message(day, cos_display, pairs) -> CosDoc:
    """Build the Message 1 (COS request) doc from parade-sorted `(person,
    resolution)` pairs for `day` (D, the NEXT duty day — the route owns picking
    tomorrow, not this pure module). Order within a category follows the input.

    Inclusion (a request, not a parade): ABSENT → its category by the SAME kind
    mapping as `categorize` (`_absent_category`); STAY_OUT → STAY OUT (where
    every regular lands by engine default unless an absence overrode it); a
    ranged absence inherits purely by date coverage upstream in `resolve`.
    PRESENT / DUTY are omitted entirely (clean NSFs aren't in this message).
    `in_camp_rows` are ignored — Message 1 has no OTHERS IN CAMP, and single-day
    in-camp artifacts on D-1 don't cover D anyway.
    """
    lines: dict[str, list] = {name: [] for name in _COS_CATEGORIES}
    people: dict[str, list] = {name: [] for name in _COS_CATEGORIES}
    notes: dict[str, list] = {name: [] for name in _COS_CATEGORIES}
    for person, resolution in pairs:
        state = resolution.state
        note = None
        if state is PresenceState.ABSENT:
            bucket = _absent_category(resolution.row)
            note = absence_note(resolution.row)
            line = f"{parade_line(person)} {note_suffix(note)}"
        elif state is PresenceState.STAY_OUT:
            # STAY OUT is not an absence: there is no backing row, so no suffix.
            bucket = "stay_out"
            line = parade_line(person)
        else:
            # PRESENT / DUTY: omitted — this text requests statuses, not attendance.
            continue
        lines[bucket].append(line)
        people[bucket].append(person)
        notes[bucket].append(note)

    doc = CosDoc(
        day=day,
        cos_display=cos_display,
        **{name: tuple(lines[name]) for name in _COS_CATEGORIES},
        **{f"{name}_people": tuple(people[name]) for name in _COS_CATEGORIES},
        **{f"{name}_notes": tuple(notes[name]) for name in _COS_CATEGORIES},
    )
    return doc.validate()


def _cos_sections(doc: CosDoc) -> tuple:
    greeting = (
        f"Hello all, {doc.cos_display} is the COS for "
        f"{format_ddmmyy(doc.day)}. "
        "Please indicate if you are on course/off/ma etc:"
    )
    return (
        _plain(greeting),
        *(_category_section(doc, name) for name in _COS_CATEGORIES),
    )


def render_cos(doc: CosDoc) -> str:
    """Render the Message 1 COS request byte-exact to PARADE_FORMATS.md.

    Greeting line, then the six categories STAY OUT / LEAVE / OFF/OIL / ON
    COURSE / MC / OTHERS, each a `_category_section` (the same helper morning
    uses), joined by a single blank line — empty categories are header-only.
    This message has NO "——" separators (only Messages 2 and 3 do). Validated
    first: the app refuses to emit a document it knows lists someone twice.
    """
    doc.validate()
    return "\n\n".join(section.text for section in _cos_sections(doc))


# --- drag-and-drop recategorization overrides (P8, reinstated P10.3) ------
#
# A stored override moves one person from the category the presence engine put
# them in to a keyer-chosen one, WITHOUT touching any leave/status data. The
# move happens on the built doc, inside the one build pipeline, so the meal
# counters (which read the same doc) inherit every drag (owner decision 6).


def _doc_variant(doc) -> ParadeVariant:
    """The ParadeVariant a built doc belongs to. CosDoc has no `variant`
    string, so its type is the discriminator; ParadeDoc carries the compute
    variant string the categorize/render pair use."""
    if isinstance(doc, CosDoc):
        return ParadeVariant.COS_MESSAGE
    return ParadeVariant.MORNING if doc.variant == "morning" else ParadeVariant.ROLL_CALL


def _doc_categories(doc) -> tuple:
    return _COS_CATEGORIES if isinstance(doc, CosDoc) else _PARADE_CATEGORIES


def apply_overrides(doc, overrides: Mapping[int, OverrideCategory]):
    """Return a copy of `doc` with each `{person_id: target}` override applied,
    or `doc` itself when `overrides` is empty (identity — no rebuild).

    A disallowed target for the doc's variant is a wiring bug (the route
    validates the target against ALLOWED_OVERRIDE_TARGETS before it ever stores
    one) — raise ValueError. A person no longer in the doc is a stale override
    that self-heals — silently skipped. A person already in the target bucket is
    a no-op. The moved line is the BARE parade_line (any parenthesized suffix —
    an OTHERS IN CAMP reason or an absence date range — is dropped, and never
    added on the way in: a dragged person has no truthful backing row to quote),
    inserted at its parade_sort_key position so the category stays in parade
    order. The result
    is validated: a move that unbalanced the doc is refused like any other.

    CURRENT_STRENGTH on a CosDoc REMOVES the person (decision D4): Message 1 has
    no present-in-camp block, so "back to present" there means the line leaves
    the message. Legal only because a CosDoc has no headcount invariant.
    """
    if not overrides:
        return doc
    variant = _doc_variant(doc)
    allowed = ALLOWED_OVERRIDE_TARGETS[variant]
    categories = _doc_categories(doc)
    lines = {c: list(getattr(doc, c)) for c in categories}
    people = {c: list(getattr(doc, c + "_people")) for c in categories}
    # Same empty-tuple fallback _category_section uses: a hand-built doc may carry
    # people without notes, and the three tuples must stay index-aligned.
    notes = {
        c: list(getattr(doc, c + "_notes")) or [None] * len(lines[c])
        for c in categories
    }
    location = {p.id: c for c in categories for p in people[c]}
    for person_id, target in overrides.items():
        if target not in allowed:
            raise ValueError(
                f"{target.value!r} is not a valid override target for {variant.value}"
            )
        current = location.get(person_id)
        if current is None or current == target.value:
            continue
        idx = next(i for i, p in enumerate(people[current]) if p.id == person_id)
        person = people[current].pop(idx)
        lines[current].pop(idx)
        notes[current].pop(idx)
        if (
            variant is ParadeVariant.COS_MESSAGE
            and target is OverrideCategory.CURRENT_STRENGTH
        ):
            # D4: dropped out of the message entirely; there is no bucket to
            # land in. Undo is Reset — the line is no longer there to drag back.
            location.pop(person_id)
            continue
        dest = target.value
        pos = bisect.bisect_right(people[dest], parade_sort_key(person), key=parade_sort_key)
        people[dest].insert(pos, person)
        lines[dest].insert(pos, parade_line(person))
        notes[dest].insert(pos, None)
        location[person_id] = dest
    replacements = {}
    for c in categories:
        replacements[c] = tuple(lines[c])
        replacements[c + "_people"] = tuple(people[c])
        replacements[c + "_notes"] = tuple(notes[c])
    return dataclasses.replace(doc, **replacements).validate()

