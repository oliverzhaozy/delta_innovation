"""Parade display order, line format, and morning-parade compute (Phase 3a).
Pure: stdlib + sibling app.domain modules only, so the ordering, category
mapping, and byte-exact rendering are all testable without an app or a DB.

The renderer is deliberately pure Python, NOT a Jinja text template (the
TECH_PLAN "Jinja text templates" line): hand-built strings dodge
template-whitespace landmines so the golden tests can pin the output to
docs/PARADE_FORMATS.md byte-for-byte.
"""
from dataclasses import dataclass
from datetime import date

from app.domain.dates import format_ddmmyy
from app.domain.presence import PresenceState
from app.domain.types import (
    Appointment,
    CourseAbsenceType,
    LeaveType,
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

# CosDoc's category fields: the six night/absent categories only (ParadeDoc
# carries these plus the two present-in-camp ones, named inline in categorize).
_COS_CATEGORIES = ("stay_out", "leave", "off_oil", "on_course", "mc", "others")


# --- morning parade compute (P3a.6) --------------------------------------
#
# The category compute turns presence resolutions into the exact category
# lists the WhatsApp document shows, and the renderer prints them byte-exact.


class ParadeImbalance(Exception):
    """A parade document whose category math cannot balance — a double-counted
    person, a drifted total, or a state that must never reach a parade
    (DEACTIVATED). We raise instead of rendering: a document the app knows is
    wrong is worse than none (the single-source-of-truth promise).
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
    and PRESENT IN CAMP persons and their NSF sub-set. Renderers ignore them, so
    every existing golden stays byte-identical. `total` is the input headcount;
    every balance check compares category lengths back to it.

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


def categorize(day, pairs, variant: str) -> ParadeDoc:
    """Bucket parade-sorted `(person, resolution)` pairs into a ParadeDoc for
    `variant` ∈ {"morning", "roll_call"}. Order within a category follows the
    input (already parade-sorted upstream).

    Each person lands in exactly one category: ABSENT by the winning row's kind;
    otherwise CURRENT STRENGTH — except on morning an in-camp annotation
    promotes them to OTHERS IN CAMP, and on roll call a STAY_OUT person goes to
    STAY OUT (in-camp annotations are dropped there — morning-only). A
    DEACTIVATED resolution must never reach a parade (presence_inputs is
    active-only) — we raise rather than silently drop the person.
    """
    if variant not in ("morning", "roll_call"):
        raise ValueError(f"unknown parade variant: {variant!r}")
    names = (
        "current_strength", "others_in_camp", "leave", "off_oil",
        "on_course", "mc", "others", "stay_out",
    )
    lines: dict[str, list] = {name: [] for name in names}
    people: dict[str, list] = {name: [] for name in names}
    for person, resolution in pairs:
        state = resolution.state
        if state is PresenceState.DEACTIVATED:
            raise ParadeImbalance(f"deactivated person on the parade: {person!r}")
        if state is PresenceState.ABSENT:
            bucket = _absent_category(resolution.row)
            line = parade_line(person)
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

    doc = ParadeDoc(
        day=day,
        variant=variant,
        total=len(pairs),
        **{name: tuple(lines[name]) for name in names},
        **{f"{name}_people": tuple(people[name]) for name in names},
    )
    return doc.validate()


def _category_block(title: str, lines: tuple) -> str:
    # Header count is len() of the same tuple that renders below it, so the two
    # cannot disagree. An empty category is the header alone (no numbered line).
    header = f"{title} ({len(lines)}):"
    if not lines:
        return header
    numbered = [f"{n}. {line}" for n, line in enumerate(lines, 1)]
    return "\n".join([header, *numbered])


def render_morning(doc: ParadeDoc) -> str:
    """Render the Message 3 morning parade state byte-exact to PARADE_FORMATS.md.

    Sections are joined by a single blank line (the skeleton's rhythm); the
    title+date pair is one section (no blank between them). Validated first —
    the app refuses to emit a document it knows is unbalanced.
    """
    doc.validate()
    if doc.variant != "morning":
        raise ValueError(f"render_morning expects a morning doc, got {doc.variant!r}")

    a = len(doc.current_strength)
    k = len(doc.others_in_camp)
    c = a + k
    d = len(doc.leave) + len(doc.off_oil) + len(doc.on_course) + len(doc.mc) + len(doc.others)
    # B (absent strength) == D by definition on the morning state; deriving it
    # here keeps the header pair from ever drifting apart.
    sections = [
        f"DELTA MORNING PARADE STATE:\n{format_ddmmyy(doc.day)}",
        f"TOTAL STRENGTH: {doc.total}",
        f"CURRENT STRENGTH: {a}",
        f"ABSENT STRENGTH: {d}",
        "——",
        f"PRESENT IN CAMP ({c}):",
        _category_block(CATEGORY_TITLES["current_strength"], doc.current_strength),
        _category_block(CATEGORY_TITLES["others_in_camp"], doc.others_in_camp),
        "——",
        f"NOT PRESENT IN CAMP ({d}):",
        _category_block(CATEGORY_TITLES["leave"], doc.leave),
        _category_block(CATEGORY_TITLES["off_oil"], doc.off_oil),
        _category_block(CATEGORY_TITLES["on_course"], doc.on_course),
        _category_block(CATEGORY_TITLES["mc"], doc.mc),
        _category_block(CATEGORY_TITLES["others"], doc.others),
    ]
    return "\n\n".join(sections)


def render_roll_call(doc: ParadeDoc) -> str:
    """Render the Message 2 roll call state byte-exact to PARADE_FORMATS.md.

    Same section rhythm as morning (single blank line between sections; title +
    date are one section), but the NIGHT document: STAY OUT is a real NOT-PRESENT
    category (regulars/stay-outs are away tonight) and OTHERS IN CAMP is ALWAYS
    header-only with a literal 0 — in-camp promotion is a morning-only rule, and
    validate() guarantees `others_in_camp` is empty here. Validated first: the
    app refuses to emit a document it knows is unbalanced.
    """
    doc.validate()
    if doc.variant != "roll_call":
        raise ValueError(f"render_roll_call expects a roll_call doc, got {doc.variant!r}")

    a = len(doc.current_strength)
    # PRESENT IN CAMP is exactly CURRENT STRENGTH: OTHERS IN CAMP is always 0.
    c = a
    d = (
        len(doc.stay_out) + len(doc.leave) + len(doc.off_oil)
        + len(doc.on_course) + len(doc.mc) + len(doc.others)
    )
    # B (absent strength) == D by definition; deriving it here keeps the header
    # pair from ever drifting apart.
    sections = [
        f"DELTA ROLL CALL STATE:\n{format_ddmmyy(doc.day)}",
        f"TOTAL STRENGTH: {doc.total}",
        f"CURRENT STRENGTH: {a}",
        f"ABSENT STRENGTH: {d}",
        "——",
        f"PRESENT IN CAMP ({c}):",
        _category_block(CATEGORY_TITLES["current_strength"], doc.current_strength),
        # Literal 0, header-only, by rule — not a _category_block on the (empty)
        # tuple, to make the "roll call has no others-in-camp" invariant explicit.
        f"{CATEGORY_TITLES['others_in_camp']} (0):",
        "——",
        f"NOT PRESENT IN CAMP ({d}):",
        _category_block(CATEGORY_TITLES["stay_out"], doc.stay_out),
        _category_block(CATEGORY_TITLES["leave"], doc.leave),
        _category_block(CATEGORY_TITLES["off_oil"], doc.off_oil),
        _category_block(CATEGORY_TITLES["on_course"], doc.on_course),
        _category_block(CATEGORY_TITLES["mc"], doc.mc),
        _category_block(CATEGORY_TITLES["others"], doc.others),
    ]
    return "\n\n".join(sections)


# --- COS message compute (P3b.1) -----------------------------------------
#
# Message 1 is a REQUEST, not a parade: it asks NSFs to report a status, so
# clean (PRESENT/DUTY) people are omitted and there is no total-strength
# invariant to balance — only the at-most-once guarantee. It reuses the exact
# row-kind mapping (_absent_category) and block renderer (_category_block) the
# morning document uses, so a category can never mean two different things.


@dataclass(frozen=True)
class CosDoc:
    """Message 1 (COS request) category lists, as already-rendered line bodies.

    Like ParadeDoc, it holds rendered `RANK NAME` bodies so a header count is
    the `len()` of the very tuple it labels — count and list can never disagree.
    Unlike ParadeDoc there is NO total/balance check: the message omits present
    NSFs, so it legitimately covers only a subset of the company. `cos_person`
    rides along for the greeting line; the six category order is the skeleton's.
    """

    day: date
    cos_person: object
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


def compute_cos_message(day, cos_person, pairs) -> CosDoc:
    """Build the Message 1 (COS request) doc from parade-sorted `(person,
    resolution)` pairs for `day` (D, the NEXT duty day — the route owns picking
    tomorrow, not this pure module). Order within a category follows the input.

    Inclusion (a request, not a parade): ABSENT → its category by the SAME kind
    mapping as `categorize` (`_absent_category`); STAY_OUT → STAY OUT (where
    every regular lands by engine default unless an absence overrode it); a
    ranged absence inherits purely by date coverage upstream in `resolve`.
    PRESENT / DUTY are omitted entirely (clean NSFs aren't in this message).
    `in_camp_rows` are ignored — Message 1 has no OTHERS IN CAMP, and single-day
    in-camp artifacts on D-1 don't cover D anyway. DEACTIVATED must never reach
    a parade document (presence_inputs is active-only) — we raise, not drop.
    """
    lines: dict[str, list] = {name: [] for name in _COS_CATEGORIES}
    people: dict[str, list] = {name: [] for name in _COS_CATEGORIES}
    for person, resolution in pairs:
        state = resolution.state
        if state is PresenceState.DEACTIVATED:
            raise ParadeImbalance(f"deactivated person on the parade: {person!r}")
        if state is PresenceState.ABSENT:
            bucket = _absent_category(resolution.row)
        elif state is PresenceState.STAY_OUT:
            bucket = "stay_out"
        else:
            # PRESENT / DUTY: omitted — this text requests statuses, not attendance.
            continue
        lines[bucket].append(parade_line(person))
        people[bucket].append(person)

    doc = CosDoc(
        day=day,
        cos_person=cos_person,
        **{name: tuple(lines[name]) for name in _COS_CATEGORIES},
        **{f"{name}_people": tuple(people[name]) for name in _COS_CATEGORIES},
    )
    return doc.validate()


def render_cos(doc: CosDoc) -> str:
    """Render the Message 1 COS request byte-exact to PARADE_FORMATS.md.

    Greeting line, then the six categories STAY OUT / LEAVE / OFF/OIL / ON
    COURSE / MC / OTHERS, each a `_category_block` (the same helper morning
    uses), joined by a single blank line — empty categories are header-only.
    This message has NO "——" separators (only Messages 2 and 3 do). Validated
    first: the app refuses to emit a document it knows lists someone twice.
    """
    doc.validate()
    greeting = (
        f"Hello all, {parade_line(doc.cos_person)} is the COS for "
        f"{format_ddmmyy(doc.day)}. "
        "Please indicate if you are on course/off/ma etc:"
    )
    sections = [
        greeting,
        _category_block(CATEGORY_TITLES["stay_out"], doc.stay_out),
        _category_block(CATEGORY_TITLES["leave"], doc.leave),
        _category_block(CATEGORY_TITLES["off_oil"], doc.off_oil),
        _category_block(CATEGORY_TITLES["on_course"], doc.on_course),
        _category_block(CATEGORY_TITLES["mc"], doc.mc),
        _category_block(CATEGORY_TITLES["others"], doc.others),
    ]
    return "\n\n".join(sections)

