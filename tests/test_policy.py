from types import SimpleNamespace

from app.domain import policy
from app.domain.types import Appointment, CompanyRole, Rank


def person(appointment, rank=Rank.PTE, company_role=None, platoon=1, is_admin=False):
    return SimpleNamespace(
        appointment=appointment,
        rank=rank,
        company_role=company_role,
        platoon=platoon,
        is_admin=is_admin,
    )


def test_command_team_is_oc_through_ps():
    in_team = [Appointment.OC, Appointment.SM, Appointment.TWO_IC,
               Appointment.PC, Appointment.P2IC, Appointment.PS]
    for appt in Appointment:
        assert policy.is_command_team(person(appt)) == (appt in in_team)


def test_any_pc_may_approve_regardless_of_platoon():
    # Owner decision 2026-07-09 revised decision (b): platoon no longer scopes
    # approval — any PC may approve any PENDING_PC request.
    assert policy.can_approve_as_pc(person(Appointment.PC, platoon=1))
    assert policy.can_approve_as_pc(person(Appointment.PC, platoon=2))
    assert policy.can_approve_as_pc(person(Appointment.PC, platoon=None))
    # Approval is still PC-only: OC and non-PC appointments cannot.
    assert not policy.can_approve_as_pc(person(Appointment.OC, platoon=1))
    assert not policy.can_approve_as_pc(person(Appointment.OPR, platoon=1))


def test_only_oc_finally_approves():
    for appt in Appointment:
        assert policy.can_final_approve(person(appt)) == (appt is Appointment.OC)


def test_s3_powers():
    s3 = person(Appointment.DET_COMD, company_role=CompanyRole.S3)
    s4 = person(Appointment.DET_COMD, company_role=CompanyRole.S4)
    opr = person(Appointment.OPR)
    for p, expected in ((s3, True), (s4, False), (opr, False)):
        assert policy.can_manage_ledger(p) == expected
        assert policy.can_manage_people(p) == expected
        assert policy.can_manage_manning(p) == expected
    assert policy.can_manage_meals(s4)
    assert not policy.can_manage_meals(s3)


def test_roster_is_ps_territory():
    assert policy.can_manage_roster(person(Appointment.PS))
    assert not policy.can_manage_roster(person(Appointment.PC))


def test_admin_flag_unlocks_admin_and_s3_pages_but_not_approval():
    admin = person(Appointment.OPR, is_admin=True)
    assert policy.can_admin_accounts(admin)
    assert policy.can_manage_ledger(admin)
    # Approval authority comes from appointment, never from the admin flag.
    assert not policy.can_final_approve(admin)
    assert not policy.can_approve_as_pc(admin)
