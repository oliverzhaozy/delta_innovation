"""App-access predicates (RBAC): what a logged-in person may SEE and DO.

Pure functions over person-shaped objects (rank/appointment/company_role/... attrs);
no Flask or DB imports. Permissions are a computed property of appointment — an
editable permission matrix would be config with no configurer at 40 users.

Assignment *eligibility* (who can be PICKED for a duty or manning slot) is a
different concept and lives in eligibility.py — keep the two separate.
"""
from app.domain.types import COMMAND_TEAM, Appointment, CompanyRole


def is_admin(person) -> bool:
    return bool(person.is_admin)


def is_command_team(person) -> bool:
    return person.appointment in COMMAND_TEAM


def is_pc(person) -> bool:
    return person.appointment is Appointment.PC


def can_approve_as_pc(person) -> bool:
    # Owner decision 2026-07-09 revised decision (b): any PC may approve any
    # PENDING_PC request; platoon no longer scopes approval. Self-approval stays
    # impossible structurally — a PC's own request enters PENDING_OC (routing).
    return is_pc(person)


def can_final_approve(person) -> bool:
    return person.appointment is Appointment.OC


def can_view_arctic(person) -> bool:
    return is_command_team(person)


def can_edit_events(person) -> bool:
    return is_command_team(person)


def can_manage_ledger(person) -> bool:
    return person.company_role is CompanyRole.S3 or is_admin(person)


def can_manage_people(person) -> bool:
    return person.company_role is CompanyRole.S3 or is_admin(person)


def can_manage_manning(person) -> bool:
    return person.company_role is CompanyRole.S3 or is_admin(person)


def can_manage_meals(person) -> bool:
    return person.company_role is CompanyRole.S4 or is_admin(person)


def can_manage_roster(person) -> bool:
    # All three PSs share the company roster (TECH_PLAN open decision, default yes).
    return person.appointment is Appointment.PS or is_admin(person)


def can_admin_accounts(person) -> bool:
    return is_admin(person)


def can_cancel_approved_leave(person) -> bool:
    # Reversing the ledger is S3's or the OC's call, never the requester's.
    return can_manage_ledger(person) or can_final_approve(person)


def can_key_parade(person, *, is_cos_of_day) -> bool:
    # Keyword-only, NO default (addendum A5): a stale caller that forgets the
    # duty fact TypeErrors in the suite instead of silently degrading to
    # fallback-only rights. The DB-aware fact comes from
    # duty_service.can_key_parade_today — policy.py never queries.
    return (
        is_cos_of_day
        or person.appointment is Appointment.PS
        or person.company_role is CompanyRole.S3
        or is_admin(person)
    )


def can_edit_ro(person, *, is_cdos_of_day) -> bool:
    # P5's consumer, landed unrouted (P4.8): the rotating CDO/S edits the RO;
    # command team is the fallback (addendum A9).
    return is_cdos_of_day or is_command_team(person)


def can_manage_ro_standing(person) -> bool:
    # Standing RO text (boilerplate, standing timeline items, weekly key
    # events) is staff work, not the rotating duty's (P5.4).
    return person.company_role is CompanyRole.S3 or is_admin(person)


def can_key_direct_absence(person) -> bool:
    # S3 keys regulars' absences (decision b) — not PS, who has no business
    # keying the command team's exceptions.
    return person.company_role is CompanyRole.S3 or is_admin(person)
