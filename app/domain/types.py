"""Pure domain vocabulary: ranks, appointments, roles. No Flask or DB imports —
everything in app/domain must stay importable and testable without an app.
"""
import enum


class Rank(str, enum.Enum):
    # Declared highest to lowest, matching SPEC.md.
    CPT = "CPT"
    LTA = "LTA"
    TWO_LT = "2LT"
    THREE_WO = "3WO"
    MSG = "MSG"
    SSG = "SSG"
    ONE_SG = "1SG"
    TWO_SG = "2SG"
    THREE_SG = "3SG"
    CFC = "CFC"
    CPL = "CPL"
    LCP = "LCP"
    PTE = "PTE"


# Explicit integer seniority (higher = more senior). Duty eligibility compares
# against 2SG from both directions, so ordering must be exact, not implied.
RANK_ORDER = {rank: seniority for seniority, rank in enumerate(reversed(list(Rank)), start=1)}


def rank_at_most(rank: Rank, ceiling: Rank) -> bool:
    """True if `rank` is `ceiling` or more junior (e.g. "2SG or below")."""
    return RANK_ORDER[rank] <= RANK_ORDER[ceiling]


def rank_at_least(rank: Rank, floor: Rank) -> bool:
    """True if `rank` is `floor` or more senior (e.g. "2SG or above")."""
    return RANK_ORDER[rank] >= RANK_ORDER[floor]


class Appointment(str, enum.Enum):
    OC = "OC"
    SM = "SM"
    TWO_IC = "2IC"
    PC = "PC"
    P2IC = "P2IC"
    PS = "PS"
    # Company appointment — NOT the manning slot "TU Det Comd" (see eligibility.py).
    DET_COMD = "DET_COMD"
    OPR = "OPR"

    @property
    def label(self) -> str:
        return {"DET_COMD": "Det Comd", "OPR": "Opr"}.get(self.value, self.value)


# Roster/list display order (most senior appointment first), mirroring the
# declaration order above. Parallels RANK_ORDER so the People page can sort by
# appointment then rank without re-deriving seniority anywhere else.
APPOINTMENT_ORDER = {appt: order for order, appt in enumerate(Appointment)}


COMMAND_TEAM = frozenset({
    Appointment.OC,
    Appointment.SM,
    Appointment.TWO_IC,
    Appointment.PC,
    Appointment.P2IC,
    Appointment.PS,
})


class PlatoonCategory(str, enum.Enum):
    """The unit's seniority grouping of its platoons (owner decision (ee)
    2026-07-30). Declaration order IS the seniority/display order — the same
    trick APPOINTMENT_ORDER uses, so one authoritative order serves the People
    page sections and every other list. Four categories over three platoons, so
    exactly one of STC/Baby is always empty; the mapping is keyed data
    (`platoon_category` rows), never hard-coded here."""

    STC = "STC"
    SENIOR = "Senior"
    JUNIOR = "Junior"
    BABY = "Baby"


class CompanyRole(str, enum.Enum):
    S3 = "S3"  # manpower
    S4 = "S4"  # logistics


class LeaveType(str, enum.Enum):
    OFF = "OFF"
    OIL = "OIL"
    LL = "LL"  # local leave
    OL = "OL"  # overseas leave


# Only OFF and OIL carry an in-app balance; LL/OL are recorded as absences only
# (owner decision (a) in TECH_PLAN).
BALANCE_TRACKED = frozenset({LeaveType.OFF, LeaveType.OIL})


class DayPart(str, enum.Enum):
    FULL = "FULL"
    AM = "AM"
    PM = "PM"


class RequestStatus(str, enum.Enum):
    PENDING_PC = "PENDING_PC"
    PENDING_OC = "PENDING_OC"
    APPROVED = "APPROVED"
    REJECTED_PC = "REJECTED_PC"
    REJECTED_OC = "REJECTED_OC"
    CANCELLED = "CANCELLED"

    @property
    def label(self) -> str:
        return {
            "PENDING_PC": "Pending PC",
            "PENDING_OC": "Pending OC",
            "APPROVED": "Approved",
            "REJECTED_PC": "Rejected (PC)",
            "REJECTED_OC": "Rejected (OC)",
            "CANCELLED": "Cancelled",
        }[self.value]

    @property
    def badge(self) -> str:
        if self in (RequestStatus.PENDING_PC, RequestStatus.PENDING_OC):
            return "pending"
        if self is RequestStatus.APPROVED:
            return "approved"
        if self is RequestStatus.CANCELLED:
            return "cancelled"
        return "rejected"


PENDING_STATUSES = frozenset({RequestStatus.PENDING_PC, RequestStatus.PENDING_OC})
# Statuses that occupy calendar days (for overlap checks and derived absence).
OCCUPYING_STATUSES = frozenset(
    {RequestStatus.PENDING_PC, RequestStatus.PENDING_OC, RequestStatus.APPROVED}
)


class DeclarationStatus(str, enum.Enum):
    """Overseas-declaration approval state (owner directive 2026-07-28). One
    approval step only — any PC decides and the OC is never involved — so this
    is deliberately NOT a subset of RequestStatus."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

    @property
    def label(self) -> str:
        return {
            "PENDING": "Pending",
            "APPROVED": "Approved",
            "REJECTED": "Rejected",
        }[self.value]

    @property
    def badge(self) -> str:
        if self is DeclarationStatus.PENDING:
            return "pending"
        if self is DeclarationStatus.APPROVED:
            return "approved"
        return "rejected"


# Removal history — each removed value has a migration remapping stored rows to
# OTHER, so the enum must never regrow one without a matching data plan:
#   BRIEFING, SITE_TESTING  removed 2026-07-11 (owner directive, f31c09a7d5e2)
#   COURSE                  removed 2026-07-26 (owner directive, b4d70e3f1a29) —
#     ON COURSE now derives solely from TP calendar events labelled
#     TpLabel.ON_COURSE; there is no keyed course status.
class StatusType(str, enum.Enum):
    MC = "MC"
    OTHER = "OTHER"

    @property
    def label(self) -> str:
        return {
            "MC": "MC",
            "OTHER": "Other",
        }[self.value]


class CourseAbsenceType(str, enum.Enum):
    """The kind marker on a synthesized course-cover row (P9.4). A course absence
    has no table of its own — it is derived from TP calendar events labelled
    `TpLabel.ON_COURSE` — so this enum exists purely so `_absent_category` can
    discriminate the row by the class of its `.type`, exactly as it does for
    LeaveType and StatusType. One member: there is one course category."""

    COURSE = "COURSE"

    @property
    def label(self) -> str:
        return {"COURSE": "On course"}[self.value]


class ParadeVariant(str, enum.Enum):
    """Which of the 3 WhatsApp parade documents the build pipeline renders.
    Distinct from the lowercase "morning"/"roll_call" strings domain.parade's
    compute pipeline takes — that's an internal compute-shape switch; this is
    the human-labelled kind of document `build_doc` is asked to produce."""

    COS_MESSAGE = "COS_MESSAGE"
    ROLL_CALL = "ROLL_CALL"
    MORNING = "MORNING"

    @property
    def label(self) -> str:
        return {
            "COS_MESSAGE": "COS message",
            "ROLL_CALL": "Roll call state",
            "MORNING": "Morning parade state",
        }[self.value]


class OverrideCategory(str, enum.Enum):
    """A drag-and-drop parade recategorization target (P8, reinstated in P10).
    Each VALUE is EXACTLY a ParadeDoc/CosDoc category field name, so `.value`
    indexes the doc tuple directly — there is no second field→category mapping
    that could drift out of step with the renderer's tuples."""

    CURRENT_STRENGTH = "current_strength"
    OTHERS_IN_CAMP = "others_in_camp"
    STAY_OUT = "stay_out"
    LEAVE = "leave"
    OFF_OIL = "off_oil"
    ON_COURSE = "on_course"
    MC = "mc"
    OTHERS = "others"


# Which categories a drag may target on each document, mirroring the categories
# that variant actually renders: morning has no STAY OUT (it dissolves into
# CURRENT STRENGTH); roll call has no OTHERS IN CAMP (always a literal 0). The
# COS request has no OTHERS IN CAMP either, but CURRENT_STRENGTH IS legal there
# and means "present, so drop the line" (decision D4 2026-07-26): Message 1 lists
# only people with something to report, so "back to present" is removal from the
# message, not a bucket. A route validates the posted target against this set
# before writing an override; apply_overrides treats a disallowed target as a
# wiring bug and raises.
ALLOWED_OVERRIDE_TARGETS: dict = {
    ParadeVariant.MORNING: frozenset(OverrideCategory) - {OverrideCategory.STAY_OUT},
    ParadeVariant.ROLL_CALL: frozenset(OverrideCategory) - {OverrideCategory.OTHERS_IN_CAMP},
    ParadeVariant.COS_MESSAGE: frozenset(OverrideCategory) - {OverrideCategory.OTHERS_IN_CAMP},
}


class RoSection(str, enum.Enum):
    """The six standing 'Matters' sections of the RO, in document order
    (docs/RO_FORMATS.md decision (o)). The format fixes the order, so member
    declaration order IS the render order — no position column anywhere."""

    SAFETY = "SAFETY"
    ADMIN = "ADMIN"
    LOGISTIC = "LOGISTIC"
    SECURITY = "SECURITY"
    RND = "RND"
    INSTRUCTIONS = "INSTRUCTIONS"

    @property
    def label(self) -> str:
        return {
            "SAFETY": "Safety Matters",
            "ADMIN": "Administrative Matters",
            "LOGISTIC": "Logistic Matters",
            "SECURITY": "Security Matters",
            "RND": "R&D Matters",
            "INSTRUCTIONS": "Instructions",
        }[self.value]


class Meal(str, enum.Enum):
    """The three daily meals a manpower food order accounts for (P3b.5)."""

    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"
    DINNER = "DINNER"

    @property
    def label(self) -> str:
        return {"BREAKFAST": "Breakfast", "LUNCH": "Lunch", "DINNER": "Dinner"}[self.value]


class BalanceKind(str, enum.Enum):
    OFF = "OFF"
    OIL = "OIL"


class LedgerSource(str, enum.Enum):
    LEAVE_APPROVAL = "LEAVE_APPROVAL"
    MANUAL = "MANUAL"
    REVERSAL = "REVERSAL"


class Service(str, enum.Enum):
    NSF = "NSF"
    REGULAR = "REGULAR"


class Calendar(str, enum.Enum):
    TP = "TP"
    ARCTIC = "ARCTIC"

    @property
    def label(self) -> str:
        return {"TP": "TP", "ARCTIC": "ARCTIC FOE"}[self.value]


class ParticipantCategory(str, enum.Enum):
    NSF = "NSF"
    REGULAR = "REGULAR"
    COMMAND_TEAM = "COMMAND_TEAM"
    PLATOON_1 = "PLATOON_1"
    PLATOON_2 = "PLATOON_2"
    PLATOON_3 = "PLATOON_3"

    @property
    def label(self) -> str:
        return {
            "NSF": "NSF",
            "REGULAR": "Regulars",
            "COMMAND_TEAM": "Command team",
            "PLATOON_1": "Platoon 1",
            "PLATOON_2": "Platoon 2",
            "PLATOON_3": "Platoon 3",
        }[self.value]


# Per-calendar event labels (UI-9). The member VALUE is the display string
# (it can carry slashes/spaces); `.slug` is the css-safe, calendar-prefixed
# token that keys the label colour class (.ev-<slug>) in styles.css. Values are
# distinct across the two enums, so a stored label value maps to one calendar.
class TpLabel(str, enum.Enum):
    PT = "PT"
    VOC = "VOC"
    MPT_PMCS_EAS = "MPT/PMCS/EAS"
    FFP = "FFP"
    HRC = "HRC"
    IPPT = "IPPT"
    OPS = "Ops"
    HOLIDAYS = "Holidays"
    # The ON COURSE source for every parade document (P9.4): every participant of
    # a TP event carrying this label is out of camp for every date it covers. The
    # value is deliberately "Course", NOT "On Course" — ArcticLabel.ON_COURSE owns
    # that string, and label values must stay distinct across the two enums (the
    # comment above; the event form's single label <select> and its value→calendar
    # map both depend on it). The parade block still prints "ON COURSE".
    ON_COURSE = "Course"
    OTHERS = "Others"

    @property
    def slug(self) -> str:
        return "tp-" + self.name.lower().replace("_", "-")


class ArcticLabel(str, enum.Enum):
    CONDUCTS = "Conducts"
    ADMIN_OTHERS = "Admin/Others"
    LEAVE_OFF_MC_ORD = "Leave/OFF/MC/ORD"
    DUTIES_NEUTRAL = "Duties/Neutral"
    ON_COURSE = "On Course"
    ICT = "ICT"
    EXERCISES = "Exercises"
    OPS_OPS_RELATED = "Ops/Ops related"
    FFP_HRC_TRAINING = "FFP/HRC training"
    COY_COMMITMENTS = "Coy commitments"

    @property
    def slug(self) -> str:
        return "arctic-" + self.name.lower().replace("_", "-")


class Duty(str, enum.Enum):
    """The two rotating company duties (P4). Eligibility rules live in
    eligibility.py; the appointment pools are disjoint by design."""

    COS = "COS"
    CDOS = "CDOS"

    @property
    def label(self) -> str:
        return {"COS": "COS", "CDOS": "CDO/S"}[self.value]


class ManningSlotType(str, enum.Enum):
    """TU manning slots (P6.2). THE TRAP, enum-level: TU_DET_COMD is filled
    by appointment P2IC/PS and is DELIBERATELY distinct from
    Appointment.DET_COMD — company Det Comds fill DET_PERSONNEL. The document
    itself prints "DET COMD" for this slot (docs/MANNING_FORMATS.md), which
    is exactly why the identifier must never be renamed to match the label.
    `label` is the DOCUMENT line label; `ui_label` is the builder's
    disambiguated wording."""

    TU_COMD = "TU_COMD"
    TU_PLANNER = "TU_PLANNER"
    TU_DET_COMD = "TU_DET_COMD"
    DET_PERSONNEL = "DET_PERSONNEL"

    @property
    def label(self) -> str:
        return {
            "TU_COMD": "TU COMD",
            "TU_PLANNER": "TU PLANNER",
            "TU_DET_COMD": "DET COMD",
            "DET_PERSONNEL": "DET PERSONNEL",
        }[self.value]

    @property
    def ui_label(self) -> str:
        return {
            "TU_COMD": "TU Comd (OC/2IC)",
            "TU_PLANNER": "TU Planner (PC)",
            "TU_DET_COMD": "TU Det Comd (P2IC/PS)",
            "DET_PERSONNEL": "Det Personnel (Det Comd/Opr)",
        }[self.value]
