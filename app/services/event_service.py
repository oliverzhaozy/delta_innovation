"""DB-aware glue joining the roster onto the pure P2.3 resolver."""
from app.domain import participants
from app.domain.types import RANK_ORDER
from app.extensions import db
from app.models import Person


def active_roster():
    """Active people, ordered platoon -> rank (seniority) -> name — the
    deterministic ordering TECH_PLAN specifies for every roster-derived list.
    Rank seniority isn't expressible as a plain column ORDER BY (the stored
    enum value doesn't sort in seniority order), so the rank/name tiebreak
    happens in Python via a stable sort over the already platoon+name
    ordered query; at ~40 rows this costs nothing.
    """
    people = (
        db.session.query(Person)
        .filter_by(is_active=True)
        .order_by(Person.platoon.nulls_first(), Person.display_name)
        .all()
    )
    return sorted(
        people,
        key=lambda p: (p.platoon if p.platoon is not None else -1, -RANK_ORDER[p.rank]),
    )


def resolve_participants(event) -> list:
    """Resolve `event`'s category/person rows against who's active right now
    — categories are never stored membership, they resolve at query time.
    """
    return participants.resolve(event.participants, active_roster())
