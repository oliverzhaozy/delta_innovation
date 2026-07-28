"""Approval routing — owner decision (b) in TECH_PLAN:
PS and below (PS, Det Comd, Opr) route PC -> OC; a PC's own request goes
straight to the OC; regulars (OC/SM/2IC/P2IC) never use the request flow —
S3 records their absences directly.
"""
from app.domain.types import Appointment, DeclarationStatus, RequestStatus

REQUESTER_APPOINTMENTS = frozenset(
    {Appointment.PC, Appointment.PS, Appointment.DET_COMD, Appointment.OPR}
)


def can_request(person) -> bool:
    return person.appointment in REQUESTER_APPOINTMENTS


def initial_status(appointment: Appointment) -> RequestStatus:
    if appointment is Appointment.PC:
        return RequestStatus.PENDING_OC  # no self-approval: skip the PC step
    if appointment in (Appointment.PS, Appointment.DET_COMD, Appointment.OPR):
        return RequestStatus.PENDING_PC
    raise ValueError(f"{appointment.value} does not request leave through the app")


def overseas_initial_status(appointment: Appointment) -> DeclarationStatus:
    """Owner directive 2026-07-28: only troopers' travel needs a PC's eyes — a
    PC's own declaration and a regular's are approved on submission.

    Unlike `initial_status` this never raises: EVERYONE declares overseas
    (TECH_PLAN RBAC line), so every appointment must map to a status.
    """
    if appointment in (Appointment.PS, Appointment.DET_COMD, Appointment.OPR):
        return DeclarationStatus.PENDING
    return DeclarationStatus.APPROVED
