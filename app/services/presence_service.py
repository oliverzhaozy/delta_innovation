"""Who is away on a given date — the single derivation that parade states,
meal counts, duty availability, and manning flags will all read. Phase 1 scope:
APPROVED leave only; statuses (MC/course) and regulars' direct absences join
this in Phase 3.
"""
from app.domain.dates import iter_days
from app.domain.types import DayPart, RequestStatus
from app.extensions import db
from app.models import LeaveRequest, Person


def absences_between(start_date, end_date):
    """APPROVED requests overlapping [start_date, end_date] for active people,
    bucketed per day. One range query (for month view) instead of one query
    per day; `absences_on` delegates here so there is a single derivation.
    """
    rows = (
        db.session.query(LeaveRequest)
        .join(Person, LeaveRequest.person_id == Person.id)
        .filter(
            LeaveRequest.status == RequestStatus.APPROVED,
            LeaveRequest.start_date <= end_date,
            LeaveRequest.end_date >= start_date,
            Person.is_active.is_(True),
        )
        .order_by(Person.platoon.nulls_first(), Person.display_name)
        .all()
    )
    by_day = {d: [] for d in iter_days(start_date, end_date)}
    for row in rows:
        # Clip the request's range to the queried window before bucketing.
        first = max(row.start_date, start_date)
        last = min(row.end_date, end_date)
        for d in iter_days(first, last):
            by_day[d].append(row)
    return by_day


def absences_on(day):
    """APPROVED requests covering `day` for active people, platoon-ordered."""
    return absences_between(day, day)[day]


def away_summary(day):
    """Board data: total strength, rows grouped by platoon, and counts."""
    total = db.session.query(Person.id).filter_by(is_active=True).count()
    rows = absences_on(day)
    full_ids = {r.person_id for r in rows if r.day_part is DayPart.FULL}
    partial_ids = {r.person_id for r in rows if r.day_part is not DayPart.FULL} - full_ids
    groups: dict = {}
    for row in rows:
        key = f"Platoon {row.person.platoon}" if row.person.platoon else "HQ"
        groups.setdefault(key, []).append(row)
    return {
        "total": total,
        "away_full": len(full_ids),
        "away_partial": len(partial_ids),
        "groups": groups,
    }


def away_text(day, summary) -> str:
    """Plain-text rendition for pasting into WhatsApp."""
    lines = [
        f"AWAY — {day.strftime('%a %d %b %Y')}",
        f"Total strength: {summary['total']}",
        f"Away: {summary['away_full']} full-day, {summary['away_partial']} half-day",
    ]
    for group, rows in summary["groups"].items():
        lines.append("")
        lines.append(f"{group}:")
        for r in rows:
            part = "" if r.day_part is DayPart.FULL else f" ({r.day_part.value})"
            lines.append(f"- {r.person.display_name} — {r.type.value}{part}")
    if not summary["groups"]:
        lines.append("")
        lines.append("Nobody away.")
    return "\n".join(lines)
