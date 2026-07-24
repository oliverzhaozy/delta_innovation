"""The parade-document build pipeline. `build_doc` is the ONE owner of the
presence_inputs -> categorize/compute -> render flow: every parade page and the
meals compute render documents through here, so a convention added to the
pipeline can never reach one surface but miss another. Parade documents are
copy-only — there is no stored/frozen archive; an absence is always re-derived
from the live APPROVED requests + statuses + direct absences.
"""
from collections import namedtuple
from datetime import timedelta

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import joinedload

from app.domain import parade as parade_domain
from app.domain.dates import now_sgt
from app.domain.types import ParadeVariant
from app.extensions import db
from app.models import ParadeOverride, ParadeSnapshot
from app.services import presence_service

# pairs: the presence_inputs PersonPresence list (routes read conflicts off it);
# doc/text: the categorized document and its rendered WhatsApp text, or None
# when the engine refused the document — then `imbalance` carries the reason.
# has_overrides: whether any stored drag-and-drop override exists for this
# (date, variant) — drives the page's "overrides active" indicator + Reset.
BuiltDoc = namedtuple("BuiltDoc", "pairs doc text imbalance has_overrides")


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
    # Stored drags are applied INSIDE this try, between categorize and render,
    # so a pathological override still surfaces as `imbalance` (never a raise)
    # and the meal counters — which read this same doc — inherit every drag
    # (owner decision 6). has_overrides reflects that rows exist, so a drag that
    # only re-sorts (or a stale one that no-ops) still lights the Reset control.
    overrides = _overrides_for(day, variant)
    try:
        if variant is ParadeVariant.MORNING:
            doc = parade_domain.categorize(day, pairs, "morning")
            doc = parade_domain.apply_overrides(doc, overrides)
            text = parade_domain.render_morning(doc)
        elif variant is ParadeVariant.ROLL_CALL:
            doc = parade_domain.categorize(day, pairs, "roll_call")
            doc = parade_domain.apply_overrides(doc, overrides)
            text = parade_domain.render_roll_call(doc)
        elif variant is ParadeVariant.COS_MESSAGE:
            doc = parade_domain.compute_cos_message(day, cos_person, pairs)
            doc = parade_domain.apply_overrides(doc, overrides)
            text = parade_domain.render_cos(doc)
        else:  # pragma: no cover — ParadeVariant is closed; a new member must land here deliberately
            raise ValueError(f"unknown parade variant: {variant!r}")
    except parade_domain.ParadeImbalance as exc:
        return BuiltDoc(
            pairs=pairs, doc=None, text=None, imbalance=str(exc),
            has_overrides=bool(overrides),
        )
    return BuiltDoc(
        pairs=pairs, doc=doc, text=text, imbalance=None,
        has_overrides=bool(overrides),
    )


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


# --- drag-and-drop overrides (P8.2) -----------------------------------------

def _overrides_for(day, variant) -> dict:
    """{person_id: OverrideCategory} for one document. build_doc reads this and
    hands it to apply_overrides; a stale entry (person no longer in the doc) is
    harmlessly skipped there, so no cleanup is needed on roster changes."""
    rows = (
        db.session.query(ParadeOverride)
        .filter(ParadeOverride.date == day, ParadeOverride.variant == variant)
        .all()
    )
    return {row.person_id: row.target_category for row in rows}


def set_override(day, variant, person_id, target, *, created_by_id):
    """Persist (or overwrite) one person's drag on one document — latest wins.

    A single-statement SQLite upsert on `uq_parade_override_slot`: a second drag
    of the same person on the same (date, variant) updates the target in place
    rather than a check-then-act SELECT-then-INSERT/UPDATE (no TOCTOU race). The
    caller commits; this only stages the statement.
    """
    stmt = sqlite_insert(ParadeOverride).values(
        date=day,
        variant=variant,
        person_id=person_id,
        target_category=target,
        created_by_id=created_by_id,
        created_at=now_sgt(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["date", "variant", "person_id"],
        set_={
            "target_category": target,
            "created_by_id": created_by_id,
            "created_at": now_sgt(),
        },
    )
    db.session.execute(stmt)


def clear_overrides(day, variant) -> int:
    """Delete every stored override for one document, returning how many rows
    went — the derivation is then back to the raw presence engine. The caller
    commits."""
    deleted = (
        db.session.query(ParadeOverride)
        .filter(ParadeOverride.date == day, ParadeOverride.variant == variant)
        .delete(synchronize_session=False)
    )
    return deleted
