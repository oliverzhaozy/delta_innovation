"""Who is away on a given date — the single derivation that parade states,
meal counts, duty availability, and manning flags will all read. Phase 1 scope:
APPROVED leave only; statuses (MC/course) and regulars' direct absences join
this in Phase 3.
"""
from app.domain.types import DayPart, RequestStatus
from app.extensions import db
from app.models import LeaveRequest, Person


def absences_on(day):
    """APPROVED requests covering `day` for active people, platoon-ordered."""
    return (
        db.session.query(LeaveRequest)
        .join(Person, LeaveRequest.person_id == Person.id)
        .filter(
            LeaveRequest.status == RequestStatus.APPROVED,
            LeaveRequest.start_date <= day,
            LeaveRequest.end_date >= day,
            Person.is_active.is_(True),
        )
        .order_by(Person.platoon.nulls_first(), Person.display_name)
        .all()
    )


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
