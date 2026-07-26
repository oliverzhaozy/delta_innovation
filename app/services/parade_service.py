"""The parade-document build pipeline. `build_doc` is the ONE owner of the
presence_inputs -> categorize/compute -> render flow: every parade page and the
meals compute render documents through here, so a convention added to the
pipeline can never reach one surface but miss another. Parade documents are
copy-only — there is no stored/frozen archive; an absence is always re-derived
from the live APPROVED requests + statuses + direct absences.
"""
from collections import namedtuple
from datetime import timedelta

from sqlalchemy.orm import joinedload

from app.domain import parade as parade_domain
from app.domain.types import ParadeVariant
from app.extensions import db
from app.models import ParadeSnapshot
from app.services import presence_service

# pairs: the presence_inputs PersonPresence list (routes read conflicts off it);
# doc/text: the categorized document and its rendered WhatsApp text, or None
# when the engine refused the document — then `imbalance` carries the reason.
BuiltDoc = namedtuple("BuiltDoc", "pairs doc text imbalance")


def build_doc(day, variant, *, cos_person=None) -> BuiltDoc:
    """The ONE owner of the presence_inputs -> categorize/compute -> render
    pipeline (pre-flight addendum A2). Every parade page — and the meals
    compute — builds documents through here, so a convention added to the
    pipeline (P4.7's duty_day offset lives here and nowhere else) can never
    reach one surface but miss another. ParadeImbalance becomes the `imbalance`
    field rather than a raise: the conflicts panel needs `pairs` even when the
    document itself is refused.
    """
    if variant is ParadeVariant.COS_MESSAGE and cos_person is None:
        raise ValueError("COS_MESSAGE needs a cos_person for its greeting")
    # The duty_day convention lives HERE and nowhere else (A2): the roll call
    # labeled `day` covers the night day−1 → day, so it reads the duty of
    # day−1; morning parade and the COS message read the duty of their own day.
    duty_day = day - timedelta(days=1) if variant is ParadeVariant.ROLL_CALL else None
    pairs = presence_service.presence_inputs(day, duty_day=duty_day)
    try:
        if variant is ParadeVariant.MORNING:
            doc = parade_domain.categorize(day, pairs, "morning")
            text = parade_domain.render_morning(doc)
        elif variant is ParadeVariant.ROLL_CALL:
            doc = parade_domain.categorize(day, pairs, "roll_call")
            text = parade_domain.render_roll_call(doc)
        elif variant is ParadeVariant.COS_MESSAGE:
            doc = parade_domain.compute_cos_message(day, cos_person, pairs)
            text = parade_domain.render_cos(doc)
        else:  # pragma: no cover — ParadeVariant is closed; a new member must land here deliberately
            raise ValueError(f"unknown parade variant: {variant!r}")
    except parade_domain.ParadeImbalance as exc:
        return BuiltDoc(pairs=pairs, doc=None, text=None, imbalance=str(exc))
    return BuiltDoc(pairs=pairs, doc=doc, text=text, imbalance=None)


def save_snapshot(day, variant, text, *, created_by_id) -> "ParadeSnapshot | None":
    """Append `text` as the archive of `variant` for `day`, unless the newest
    existing row for that (date, variant) already holds byte-identical text —
    hitting Copy twice on an unchanged document must not grow the archive
    (append-only, dedup-on-identical; owner default 2026-07-24). The caller
    commits; this only stages the row. Returns the new row, or None when the
    identical-text guard skipped the insert.
    """
    newest = (
        db.session.query(ParadeSnapshot)
        .filter(ParadeSnapshot.date == day, ParadeSnapshot.variant == variant)
        .order_by(ParadeSnapshot.created_at.desc(), ParadeSnapshot.id.desc())
        .first()
    )
    if newest is not None and newest.rendered_text == text:
        return None
    snap = ParadeSnapshot(
        date=day, variant=variant, rendered_text=text, created_by_id=created_by_id
    )
    db.session.add(snap)
    return snap


def snapshots_for(day=None):
    """Archived snapshots newest-first, optionally narrowed to one date. The
    copier is eager-loaded because the history page prints their name per row
    (N+1 rule: a relationship looped in a template is a query per row).
    """
    query = (
        db.session.query(ParadeSnapshot)
        .options(joinedload(ParadeSnapshot.created_by))
        .order_by(
            ParadeSnapshot.date.desc(),
            ParadeSnapshot.created_at.desc(),
            ParadeSnapshot.id.desc(),
        )
    )
    if day is not None:
        query = query.filter(ParadeSnapshot.date == day)
    return query.all()


def snapshots_by_date(day=None):
    """`snapshots_for` folded into (date, rows) pairs, dates newest-first — the
    shape the history page's day cards iterate. Rows arrive already sorted
    date-desc, so same-date rows are contiguous and group in one pass.
    """
    groups = []
    for snap in snapshots_for(day):
        if not groups or groups[-1][0] != snap.date:
            groups.append((snap.date, []))
        groups[-1][1].append(snap)
    return groups

