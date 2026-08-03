"""decision (ee) — domain/platoons.py: the COS carve-out rule and the People
page's grouping, both pure over duck-typed rows.

The module never sorts: `people` arrives in parade order (event_service's one
canonical order) and every partition must preserve it, so these tests pin order
as well as membership.
"""
from types import SimpleNamespace

from app.domain.platoons import (
    PS_AND_BELOW,
    cos_exclusions,
    cos_excluded_platoons,
    group_people,
)
from app.domain.types import Appointment, PlatoonCategory


def row(category, platoon, in_cos_pool=True):
    return SimpleNamespace(category=category, platoon=platoon, in_cos_pool=in_cos_pool)


def person(username, appointment, platoon):
    return SimpleNamespace(id=hash(username) & 0xFFFF, username=username,
                           appointment=appointment, platoon=platoon)


DEFAULT_ROWS = [
    row(PlatoonCategory.STC, 2, in_cos_pool=False),
    row(PlatoonCategory.SENIOR, 3),
    row(PlatoonCategory.JUNIOR, 1),
    row(PlatoonCategory.BABY, None),
]


# --- the COS carve-out ----------------------------------------------------------

def test_only_a_mapped_platoon_with_the_flag_off_is_excluded():
    assert cos_excluded_platoons(DEFAULT_ROWS) == frozenset({2})


def test_a_category_with_no_platoon_never_excludes_anything():
    # The None trap: an excused category holding NO platoon must not put None in
    # the excluded set, or `person.platoon not in excluded` would carve out every
    # platoon-less person.
    rows = [row(PlatoonCategory.BABY, None, in_cos_pool=False)]
    assert cos_excluded_platoons(rows) == frozenset()
    assert cos_exclusions(rows) == {}


def test_every_category_in_the_pool_excludes_nobody():
    assert cos_excluded_platoons([row(c, n) for c, n in
                                  zip(PlatoonCategory, (2, 3, 1, None))]) == frozenset()


def test_cos_exclusions_names_the_excluding_category():
    # The manual-assign warning quotes the category, so the mapping (not just the
    # platoon set) is part of the rule's one owner.
    assert cos_exclusions(DEFAULT_ROWS) == {2: PlatoonCategory.STC}


def test_no_rows_at_all_excludes_nobody():
    assert cos_excluded_platoons([]) == frozenset()


# --- group_people ---------------------------------------------------------------

OC = person("oc", Appointment.OC, None)
PC1 = person("pc1", Appointment.PC, 1)          # command team, but carries a platoon
P2IC2 = person("p2ic2", Appointment.P2IC, 2)
PS2 = person("ps2", Appointment.PS, 2)
DET2 = person("det2", Appointment.DET_COMD, 2)
OPR3 = person("opr3", Appointment.OPR, 3)
OPR1 = person("opr1", Appointment.OPR, 1)
OPR_NONE = person("opr_none", Appointment.OPR, None)

ROSTER = [OC, PC1, P2IC2, PS2, DET2, OPR3, OPR1, OPR_NONE]


def usernames(people):
    return [p.username for p in people]


def test_ps_and_below_is_exactly_the_platoon_appointments():
    assert PS_AND_BELOW == frozenset(
        {Appointment.PS, Appointment.DET_COMD, Appointment.OPR}
    )


def test_command_holds_everyone_above_ps_even_with_a_platoon():
    groups = group_people(ROSTER, DEFAULT_ROWS)
    # A PC or P2IC has a platoon number but is command — the section split is by
    # APPOINTMENT, never by whether the platoon column is filled.
    assert usernames(groups.command) == ["oc", "pc1", "p2ic2"]


def test_sections_are_all_four_categories_in_enum_order():
    groups = group_people(ROSTER, DEFAULT_ROWS)
    assert [s.category for s in groups.sections] == list(PlatoonCategory)
    assert [s.platoon for s in groups.sections] == [2, 3, 1, None]
    assert [usernames(s.people) for s in groups.sections] == [
        ["ps2", "det2"],   # STC = platoon 2, minus the P2IC (command)
        ["opr3"],          # Senior = platoon 3
        ["opr1"],          # Junior = platoon 1
        [],                # Baby holds no platoon
    ]


def test_an_unmapped_category_renders_empty_rather_than_vanishing():
    groups = group_people(ROSTER, DEFAULT_ROWS)
    baby = groups.sections[-1]
    assert baby.category is PlatoonCategory.BABY
    assert baby.platoon is None and baby.people == []


def test_a_mapped_but_unpopulated_category_is_empty_too():
    rows = [row(PlatoonCategory.STC, 2), row(PlatoonCategory.SENIOR, 3),
            row(PlatoonCategory.JUNIOR, 1), row(PlatoonCategory.BABY, None)]
    groups = group_people([OPR1], rows)
    stc = groups.sections[0]
    assert stc.platoon == 2 and stc.people == []


def test_a_platoon_mapped_to_no_category_gets_its_own_group():
    # Nobody may be hidden by an incomplete mapping: platoon 3 has no category
    # here, so its people surface in `uncategorised`, ascending by platoon.
    rows = [row(PlatoonCategory.JUNIOR, 1), row(PlatoonCategory.STC, 2, in_cos_pool=False)]
    groups = group_people(ROSTER, rows)
    assert [(g.platoon, usernames(g.people)) for g in groups.uncategorised] == [
        (3, ["opr3"]),
    ]
    assert [usernames(s.people) for s in groups.sections] == [
        ["ps2", "det2"], [], ["opr1"], [],
    ]


def test_ps_and_below_without_a_platoon_lands_in_no_platoon():
    groups = group_people(ROSTER, DEFAULT_ROWS)
    assert usernames(groups.no_platoon) == ["opr_none"]
    # ...and never in a category section or an uncategorised group.
    assert "opr_none" not in usernames(
        [p for s in groups.sections for p in s.people]
        + [p for g in groups.uncategorised for p in g.people]
    )


def test_every_person_lands_in_exactly_one_group():
    groups = group_people(ROSTER, DEFAULT_ROWS)
    placed = (
        usernames(groups.command)
        + [p.username for s in groups.sections for p in s.people]
        + [p.username for g in groups.uncategorised for p in g.people]
        + usernames(groups.no_platoon)
    )
    assert sorted(placed) == sorted(usernames(ROSTER))
    assert len(placed) == len(set(placed))


def test_input_order_is_preserved_inside_every_group():
    reversed_roster = list(reversed(ROSTER))
    groups = group_people(reversed_roster, DEFAULT_ROWS)
    assert usernames(groups.command) == ["p2ic2", "pc1", "oc"]
    assert usernames(groups.sections[0].people) == ["det2", "ps2"]
