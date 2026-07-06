"""Pure participant resolution for calendar events (Phase 2).

An event's involved people are never stored — they're computed from
`event_participant` rows against the current roster, so a category (e.g.
"Platoon 2") always reflects who's in that platoon *today*, not who was in
it when the event was created.

Resolution order:
  1. Only active people are ever eligible (deactivated people drop out even
     if a person row names them directly).
  2. The base set is every included category's members, minus every
     excluded category's members (e.g. NSF + REGULAR - COMMAND_TEAM).
  3. Person rows then override the base set per person: include adds them,
     exclude removes them — this is how S3 carves out "except X plus Y"
     from a category. The schema forbids a person appearing on both a
     person row and being ambiguous (unique per event+person), so include
     and exclude can't collide for the same person.
  4. No rows at all means nobody is involved — there is no implicit "whole
     company" default; that's expressed explicitly by tagging NSF+REGULAR.
"""
from app.domain.types import COMMAND_TEAM, ParticipantCategory, Service

_PLATOON_CATEGORIES = {
    ParticipantCategory.PLATOON_1: 1,
    ParticipantCategory.PLATOON_2: 2,
    ParticipantCategory.PLATOON_3: 3,
}


def in_category(person, category: ParticipantCategory) -> bool:
    """Membership predicate for a single category, evaluated against the
    roster at query time (never cached/stored)."""
    if category is ParticipantCategory.NSF:
        return person.service is Service.NSF
    if category is ParticipantCategory.REGULAR:
        return person.service is Service.REGULAR
    if category is ParticipantCategory.COMMAND_TEAM:
        return person.appointment in COMMAND_TEAM
    # Platoon categories: `person.platoon` is None for people without a
    # platoon (command team) — None must never equal a platoon number.
    return person.platoon == _PLATOON_CATEGORIES[category]


def resolve(rows, people) -> list:
    """Resolve `rows` (participant-shaped: .person_id, .category, .include)
    against `people` (the active-or-not roster) into the list of people
    actually involved, in `people`'s order.
    """
    if not rows:
        return []

    included_categories = [r.category for r in rows if r.category is not None and r.include]
    excluded_categories = [r.category for r in rows if r.category is not None and not r.include]
    included_person_ids = {r.person_id for r in rows if r.person_id is not None and r.include}
    excluded_person_ids = {r.person_id for r in rows if r.person_id is not None and not r.include}

    result = []
    for candidate in people:
        if not candidate.is_active:
            continue
        if candidate.id in excluded_person_ids:
            included = False
        elif candidate.id in included_person_ids:
            included = True
        else:
            in_base = any(in_category(candidate, c) for c in included_categories) and not any(
                in_category(candidate, c) for c in excluded_categories
            )
            included = in_base
        if included:
            result.append(candidate)
    return result
