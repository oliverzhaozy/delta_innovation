"""Parade snapshot writes/reads — append-only. No update or delete function
exists in this module (nor a route anywhere for one): re-finalizing before
sending is a legitimate correction, and the resulting extra row IS the audit
trail (ledger posture — history, never edits), never a stored calendar the
app could let drift against the live recompute.
"""
from collections import namedtuple
from datetime import timedelta

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
    pipeline (pre-flight addendum A2). Every page and finalize route — and the
    meals compute — builds documents through here, so a convention added to
    the pipeline (P4.7's duty_day offset lives here and nowhere else) can never
    reach the screen but miss the archival snapshot. ParadeImbalance becomes
    the `imbalance` field rather than a raise: the conflicts panel needs
    `pairs` even when the document itself is refused.
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


def finalize(day, variant, rendered_text, actor) -> ParadeSnapshot:
    """Freeze one document at copy time (add + commit). No unique(date,
    variant) — a second finalize for the same day/variant appends a new row
    rather than overwriting the first."""
    snap = ParadeSnapshot(
        date=day,
        variant=variant,
        rendered_text=rendered_text,
        finalized_by_id=actor.id,
    )
    db.session.add(snap)
    db.session.commit()
    return snap


def snapshots(limit=None):
    """Newest-first (finalized_at desc; id desc breaks ties within the same
    second, e.g. two finalizes fired back to back)."""
    query = (
        db.session.query(ParadeSnapshot)
        .order_by(ParadeSnapshot.finalized_at.desc(), ParadeSnapshot.id.desc())
    )
    return query.limit(limit).all() if limit is not None else query.all()
