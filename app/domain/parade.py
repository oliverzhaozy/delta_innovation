"""Parade display order, line format, and morning-parade compute (Phase 3a).
Pure: stdlib + sibling app.domain modules only, so the ordering, category
mapping, and byte-exact rendering are all testable without an app or a DB.

The renderer is deliberately pure Python, NOT a Jinja text template (the
TECH_PLAN "Jinja text templates" line): following the away_text precedent,
hand-built strings dodge template-whitespace landmines so the golden tests can
pin the output to docs/PARADE_FORMATS.md byte-for-byte.
"""
from dataclasses import dataclass
from datetime import date

from app.domain.dates import format_ddmmyy
from app.domain.presence import PresenceState
from app.domain.types import Appointment, DirectAbsenceType, LeaveType, Rank, StatusType

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
    # display_name already embeds the rank prefix ("CPT Chan Wei Liang"), so
    # uppercasing it alone yields the required "RANK NAME" format.
    return person.display_name.upper()


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
    bodies (the `RANK NAME`, plus `(REASON)` for OTHERS IN CAMP).

    Holding rendered bodies — not people — is deliberate: the header counts are
    then `len()` of the very tuple that renders, so a count can never disagree
    with the list beneath it. `total` is the input headcount; every balance
    check compares category lengths back to it.

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

    def _not_present(self) -> tuple:
        # Morning has no STAY OUT category; roll call counts it under D.
        base = (self.leave, self.off_oil, self.on_course, self.mc, self.others)
        return base if self.variant == "morning" else (self.stay_out, *base)

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
        buckets = (*present, *self._not_present())
        covered = sum(len(b) for b in buckets)
        if covered != self.total:
            raise ParadeImbalance(
                f"category headcount {covered} != total strength {self.total}"
            )
        lines = [line for bucket in buckets for line in bucket]
        if len(set(lines)) != len(lines):
            raise ParadeImbalance("a person appears in more than one category")
        return self


def _absent_category(row) -> str:
    """The category a winning ABSENT row belongs to, by the PARADE_FORMATS
    mapping. Discriminated on the enum class of `row.type` — the one attribute
    all three source rows share — so no source-specific attribute sniffing:
    LeaveType → OFF/OIL or LEAVE, DirectAbsenceType → LEAVE or OTHERS,
    StatusType → MC / ON COURSE / OTHERS (an out-of-camp status; in-camp ones
    are never absent-making, so they never reach here).
    """
    kind = row.type
    if isinstance(kind, LeaveType):
        return "off_oil" if kind in (LeaveType.OFF, LeaveType.OIL) else "leave"
    if isinstance(kind, DirectAbsenceType):
        return "leave" if kind is DirectAbsenceType.LEAVE else "others"
    if isinstance(kind, StatusType):
        if kind is StatusType.MC:
            return "mc"
        if kind is StatusType.COURSE:
            return "on_course"
        return "others"  # out-of-camp BRIEFING / SITE_TESTING / OTHER
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
    buckets: dict[str, list] = {
        name: []
        for name in (
            "current_strength", "others_in_camp", "leave", "off_oil",
            "on_course", "mc", "others", "stay_out",
        )
    }
    for person, resolution in pairs:
        state = resolution.state
        if state is PresenceState.DEACTIVATED:
            raise ParadeImbalance(f"deactivated person on the parade: {person!r}")
        if state is PresenceState.ABSENT:
            buckets[_absent_category(resolution.row)].append(parade_line(person))
        elif variant == "morning" and resolution.in_camp_rows:
            reason = _in_camp_reason(resolution.in_camp_rows[0])
            buckets["others_in_camp"].append(f"{parade_line(person)} ({reason})")
        elif variant == "roll_call" and state is PresenceState.STAY_OUT:
            buckets["stay_out"].append(parade_line(person))
        else:  # PRESENT / DUTY, and morning STAY_OUT → current strength
            buckets["current_strength"].append(parade_line(person))

    doc = ParadeDoc(
        day=day,
        variant=variant,
        total=len(pairs),
        **{name: tuple(lines) for name, lines in buckets.items()},
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
        _category_block("CURRENT STRENGTH", doc.current_strength),
        _category_block("OTHERS IN CAMP", doc.others_in_camp),
        "——",
        f"NOT PRESENT IN CAMP ({d}):",
        _category_block("LEAVE", doc.leave),
        _category_block("OFF/OIL", doc.off_oil),
        _category_block("ON COURSE", doc.on_course),
        _category_block("MC", doc.mc),
        _category_block("OTHERS", doc.others),
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

    def validate(self) -> "CosDoc":
        """Raise ParadeImbalance if anyone is listed twice, else return self.

        The single-state resolution already puts each person in one category, so
        compute can't produce a duplicate — but the invariant is enforced anyway
        (a hand-built or future-miswired doc must never render two lines for one
        person). No headcount check: Message 1 does not account for everyone.
        """
        buckets = (
            self.stay_out, self.leave, self.off_oil,
            self.on_course, self.mc, self.others,
        )
        lines = [line for bucket in buckets for line in bucket]
        if len(set(lines)) != len(lines):
            raise ParadeImbalance("a person appears in more than one category")
        return self


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
    buckets: dict[str, list] = {
        name: []
        for name in ("stay_out", "leave", "off_oil", "on_course", "mc", "others")
    }
    for person, resolution in pairs:
        state = resolution.state
        if state is PresenceState.DEACTIVATED:
            raise ParadeImbalance(f"deactivated person on the parade: {person!r}")
        if state is PresenceState.ABSENT:
            buckets[_absent_category(resolution.row)].append(parade_line(person))
        elif state is PresenceState.STAY_OUT:
            buckets["stay_out"].append(parade_line(person))
        # PRESENT / DUTY: omitted — this text requests statuses, not attendance.

    doc = CosDoc(
        day=day,
        cos_person=cos_person,
        **{name: tuple(lines) for name, lines in buckets.items()},
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
        _category_block("STAY OUT", doc.stay_out),
        _category_block("LEAVE", doc.leave),
        _category_block("OFF/OIL", doc.off_oil),
        _category_block("ON COURSE", doc.on_course),
        _category_block("MC", doc.mc),
        _category_block("OTHERS", doc.others),
    ]
    return "\n\n".join(sections)
