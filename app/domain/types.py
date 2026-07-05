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


class Service(str, enum.Enum):
    NSF = "NSF"
    REGULAR = "REGULAR"
