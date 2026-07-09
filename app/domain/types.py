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


COMMAND_TEAM = frozenset({
    Appointment.OC,
    Appointment.SM,
    Appointment.TWO_IC,
    Appointment.PC,
    Appointment.P2IC,
    Appointment.PS,
})


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


class StatusType(str, enum.Enum):
    MC = "MC"
    COURSE = "COURSE"
    BRIEFING = "BRIEFING"
    SITE_TESTING = "SITE_TESTING"
    OTHER = "OTHER"

    @property
    def label(self) -> str:
        return {
            "MC": "MC",
            "COURSE": "On course",
            "BRIEFING": "Briefing",
            "SITE_TESTING": "Site testing",
            "OTHER": "Other",
        }[self.value]


# Convenience default for the P3a.5 keying form, not a rule: BRIEFING is
# usually in-camp and the rest usually aren't, but any row can override it
# (e.g. an out-of-camp briefing, or an in-camp "not joining FP" OTHER).
STATUS_IN_CAMP_DEFAULT: dict[StatusType, bool] = {
    StatusType.MC: False,
    StatusType.COURSE: False,
    StatusType.BRIEFING: True,
    StatusType.SITE_TESTING: False,
    StatusType.OTHER: False,
}


class DirectAbsenceType(str, enum.Enum):
    LEAVE = "LEAVE"
    OTHER = "OTHER"

    @property
    def label(self) -> str:
        return {"LEAVE": "Leave", "OTHER": "Other"}[self.value]


class ParadeVariant(str, enum.Enum):
    """Which of the 3 WhatsApp parade documents a ParadeSnapshot freezes.
    Distinct from the lowercase "morning"/"roll_call" strings domain.parade's
    compute pipeline takes — that's an internal compute-shape switch; this is
    the persisted, human-labelled kind of document that was finalized."""

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


class RoRecurrence(str, enum.Enum):
    """When a standing timeline item appears (decision (n)): every day, or
    only the last WORKING day of the week (Friday, or earlier when Friday is
    a public holiday)."""

    DAILY = "DAILY"
    LAST_WORKING_DAY = "LAST_WORKING_DAY"


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


class DutyState(str, enum.Enum):
    """PROPOSED = generator/PS draft, invisible to parades and meals;
    CONFIRMED = the roster of record (drafts must never move real counts)."""

    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"


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
