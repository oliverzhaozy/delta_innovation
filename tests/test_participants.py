from types import SimpleNamespace

from app.domain import participants
from app.domain.types import Appointment, ParticipantCategory, Service


def person(id, service=Service.NSF, appointment=Appointment.OPR, platoon=1, is_active=True):
    return SimpleNamespace(
        id=id, service=service, appointment=appointment, platoon=platoon, is_active=is_active
    )


def category_row(category, include=True):
    return SimpleNamespace(person_id=None, category=category, include=include)


def person_row(person_id, include=True):
    return SimpleNamespace(person_id=person_id, category=None, include=include)


# --- in_category -------------------------------------------------------

def test_in_category_service_categories():
    nsf = person(1, service=Service.NSF)
    reg = person(2, service=Service.REGULAR)
    assert participants.in_category(nsf, ParticipantCategory.NSF)
    assert not participants.in_category(nsf, ParticipantCategory.REGULAR)
    assert participants.in_category(reg, ParticipantCategory.REGULAR)
    assert not participants.in_category(reg, ParticipantCategory.NSF)


def test_in_category_command_team():
    oc = person(1, appointment=Appointment.OC)
    opr = person(2, appointment=Appointment.OPR)
    assert participants.in_category(oc, ParticipantCategory.COMMAND_TEAM)
    assert not participants.in_category(opr, ParticipantCategory.COMMAND_TEAM)


def test_in_category_platoons():
    p1 = person(1, platoon=1)
    p2 = person(2, platoon=2)
    p3 = person(3, platoon=3)
    assert participants.in_category(p1, ParticipantCategory.PLATOON_1)
    assert not participants.in_category(p1, ParticipantCategory.PLATOON_2)
    assert not participants.in_category(p1, ParticipantCategory.PLATOON_3)
    assert participants.in_category(p2, ParticipantCategory.PLATOON_2)
    assert participants.in_category(p3, ParticipantCategory.PLATOON_3)


def test_in_category_platoon_none_never_matches():
    # Command team members (OC/SM/2IC) may have no platoon; None must not
    # accidentally satisfy a platoon category.
    no_platoon = person(1, platoon=None)
    for cat in (ParticipantCategory.PLATOON_1, ParticipantCategory.PLATOON_2, ParticipantCategory.PLATOON_3):
        assert not participants.in_category(no_platoon, cat)


# --- resolve -------------------------------------------------------------

def test_resolve_no_rows_means_nobody_involved():
    people = [person(1), person(2)]
    assert participants.resolve([], people) == []


def test_resolve_platoon_except_x_plus_y():
    plat2_a = person(1, platoon=2)
    plat2_b = person(2, platoon=2)  # X: excluded by person row
    plat2_c = person(3, platoon=2)
    plat1_y = person(4, platoon=1)  # Y: included by person row, not in platoon 2
    people = [plat2_a, plat2_b, plat2_c, plat1_y]
    rows = [
        category_row(ParticipantCategory.PLATOON_2, include=True),
        person_row(2, include=False),  # except X
        person_row(4, include=True),  # plus Y
    ]
    result = participants.resolve(rows, people)
    assert result == [plat2_a, plat2_c, plat1_y]


def test_resolve_person_exclude_beats_category_include():
    in_category = person(1, service=Service.REGULAR)
    excluded_person = person(2, service=Service.REGULAR)
    people = [in_category, excluded_person]
    rows = [
        category_row(ParticipantCategory.REGULAR, include=True),
        person_row(2, include=False),
    ]
    assert participants.resolve(rows, people) == [in_category]


def test_resolve_person_include_beats_category_exclude():
    command_team_member = person(1, appointment=Appointment.PC, service=Service.REGULAR)
    other_regular = person(2, appointment=Appointment.OPR, service=Service.REGULAR)
    people = [command_team_member, other_regular]
    rows = [
        category_row(ParticipantCategory.REGULAR, include=True),
        category_row(ParticipantCategory.COMMAND_TEAM, include=False),
        person_row(1, include=True),  # person-include overrides the category-exclude
    ]
    assert participants.resolve(rows, people) == [command_team_member, other_regular]


def test_resolve_inactive_dropped_even_when_category_member():
    active_reg = person(1, service=Service.REGULAR, is_active=True)
    inactive_reg = person(2, service=Service.REGULAR, is_active=False)
    people = [active_reg, inactive_reg]
    rows = [category_row(ParticipantCategory.REGULAR, include=True)]
    assert participants.resolve(rows, people) == [active_reg]


def test_resolve_inactive_dropped_even_when_person_included():
    inactive_but_named = person(1, is_active=False)
    people = [inactive_but_named]
    rows = [person_row(1, include=True)]
    assert participants.resolve(rows, people) == []


def test_resolve_excluded_category_subtracts_from_included_categories():
    # "Whole company" is expressed as NSF + REGULAR; subtracting COMMAND_TEAM
    # should drop command-team members even though they're NSF or REGULAR too.
    nsf_soldier = person(1, service=Service.NSF, appointment=Appointment.OPR)
    regular_pc = person(2, service=Service.REGULAR, appointment=Appointment.PC)
    regular_ps = person(3, service=Service.REGULAR, appointment=Appointment.PS)
    people = [nsf_soldier, regular_pc, regular_ps]
    rows = [
        category_row(ParticipantCategory.NSF, include=True),
        category_row(ParticipantCategory.REGULAR, include=True),
        category_row(ParticipantCategory.COMMAND_TEAM, include=False),
    ]
    assert participants.resolve(rows, people) == [nsf_soldier]


def test_resolve_unknown_person_id_ignored():
    only_person = person(1, service=Service.REGULAR)
    people = [only_person]
    rows = [
        category_row(ParticipantCategory.REGULAR, include=True),
        person_row(999, include=True),  # matches nobody in the roster
    ]
    assert participants.resolve(rows, people) == [only_person]


def test_resolve_preserves_people_order():
    p3 = person(3, service=Service.REGULAR)
    p1 = person(1, service=Service.REGULAR)
    p2 = person(2, service=Service.REGULAR)
    # people list order is 3, 1, 2 — result must follow this, not id order.
    people = [p3, p1, p2]
    rows = [category_row(ParticipantCategory.REGULAR, include=True)]
    assert participants.resolve(rows, people) == [p3, p1, p2]
