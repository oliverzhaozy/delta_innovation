"""Platoon seniority categories, pure (owner decision (ee) 2026-07-30).

Two jobs, both over duck-typed `platoon_category` rows (.category, .platoon,
.in_cos_pool) so pytest needs no DB — the same posture eligibility.py takes with
bare person objects:

- which platoons are carved out of the COS auto-pick pool, and
- how the People page's one flat roster splits into command + category sections.

`PlatoonCategory`'s declaration order IS the section order; nothing here sorts,
because `people` arrives in parade order and every partition preserves it.
"""
from collections import defaultdict, namedtuple

from app.domain.types import Appointment, PlatoonCategory

# The appointments that sit IN a platoon and therefore group by one. Mirrors the
# inline tuple in routing.py:20 (leave routing has its own small, self-documenting
# vocabulary — a shared constant there would couple two unrelated rules).
PS_AND_BELOW = frozenset({Appointment.PS, Appointment.DET_COMD, Appointment.OPR})

CategorySection = namedtuple("CategorySection", "category platoon people")
PlatoonGroup = namedtuple("PlatoonGroup", "platoon people")
Grouping = namedtuple("Grouping", "command sections uncategorised no_platoon")


def cos_exclusions(rows) -> dict:
    """Excluded platoon -> the category that excluded it. THE rule, one place: a
    category carves its platoon out of the COS pool only when it HAS a platoon
    and its flag is off. `platoon is not None` is load-bearing — a category with
    no platoon must never read as an exclusion of "platoon None"."""
    return {
        row.platoon: row.category
        for row in rows
        if row.platoon is not None and not row.in_cos_pool
    }


def cos_excluded_platoons(rows) -> frozenset:
    """Just the platoon numbers — what a pool filter needs."""
    return frozenset(cos_exclusions(rows))


def group_people(people, rows) -> Grouping:
    """Partition an already parade-ordered roster into the People page's shape,
    order preserved inside every group:

    - `command`: everyone whose appointment is NOT PS-and-below (OC, 2IC, SM,
      PC, P2IC), regardless of whether they carry a platoon number.
    - `sections`: one per PlatoonCategory in enum order, ALWAYS all four — an
      unmapped or empty category still renders, so its state stays visible.
    - `uncategorised`: PS-and-below whose platoon maps to no category, one group
      per platoon (ascending), so a renumbering never hides anyone.
    - `no_platoon`: PS-and-below with no platoon at all (the column is nullable).
    """
    by_category = {row.category: row for row in rows}
    mapped = frozenset(row.platoon for row in rows if row.platoon is not None)
    command, no_platoon = [], []
    per_platoon = defaultdict(list)
    for person in people:
        if person.appointment not in PS_AND_BELOW:
            command.append(person)
        elif person.platoon is None:
            no_platoon.append(person)
        else:
            per_platoon[person.platoon].append(person)
    sections = []
    for category in PlatoonCategory:
        row = by_category.get(category)
        platoon = row.platoon if row is not None else None
        sections.append(
            CategorySection(
                category=category,
                platoon=platoon,
                people=list(per_platoon.get(platoon, ())) if platoon is not None else [],
            )
        )
    return Grouping(
        command=command,
        sections=sections,
        uncategorised=[
            PlatoonGroup(platoon=platoon, people=members)
            for platoon, members in sorted(per_platoon.items())
            if platoon not in mapped
        ],
        no_platoon=no_platoon,
    )
