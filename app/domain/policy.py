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


def can_approve_as_pc(person, platoon) -> bool:
    # Object-level scope: a PC only ever acts on their own platoon's requests.
    return is_pc(person) and person.platoon is not None and person.platoon == platoon


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
