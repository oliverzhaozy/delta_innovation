"""Parade snapshot writes/reads — append-only. No update or delete function
exists in this module (nor a route anywhere for one): re-finalizing before
sending is a legitimate correction, and the resulting extra row IS the audit
trail (ledger posture — history, never edits), never a stored calendar the
app could let drift against the live recompute.
"""
from app.extensions import db
from app.models import ParadeSnapshot


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
