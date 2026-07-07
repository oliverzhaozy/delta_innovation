"""RO assembly + render (P5.3). Pure: stdlib + sibling app.domain only.

docs/RO_FORMATS.md is the byte-level authority; owner decisions (l)–(o)
govern everything here: uniform 12-➖ separator and every emitted line
rstripped (l); the CDO/CDS label exists in THIS document only (m); the
timeline is standing items filtered by recurrence + TP events STARTING on the
day + hand-keyed extras, timed blocks ascending then one TBC block last
(n/n′); the six Matters sections render '-' when empty, the messages blob is
free text, and key events cover the RO date's own week with the
Mon/Tues/Wed/Thurs/Fri spellings (o). A missing duty renders an explicit
placeholder AND is reported — a silently blank duty line is how a wrong
document gets sent.
"""
from collections import namedtuple
from datetime import timedelta

from app.domain.dates import is_working_day
from app.domain.types import RoRecurrence, RoSection

SEPARATOR = "➖" * 12
MISSING_DUTY = "[NO CONFIRMED DUTY]"
_DAY_LABELS = ("Mon", "Tues", "Wed", "Thurs", "Fri")

RoDoc = namedtuple("RoDoc", "text missing_duties")


def last_working_day_of_week(day, holidays=frozenset()):
    """The last working day of `day`'s Mon–Sun week (decision n): Friday,
    stepping back over public holidays. A degenerate all-holiday week returns
    the Monday — defined, not crashed."""
    monday = day - timedelta(days=day.weekday())
    candidate = monday + timedelta(days=4)
    while candidate > monday and not is_working_day(candidate, holidays):
        candidate -= timedelta(days=1)
    return candidate


def timeline_items(day, *, standing_items=(), tp_events=(), extra_items=(),
                   holidays=frozenset()):
    """[(time | None, text)] for `day`, ordered per (n′): timed ascending
    (stable, so ties keep standing-position → TP-start → keyed order), then
    one TBC block (standing by position, then extras as keyed).

    Only TP events STARTING on `day` insert — a continuing multi-day event
    has no meaningful time on its later days, and the key-events block
    already carries the week's conducts. Callers pass TP-calendar events
    only; this module does not know calendars exist.
    """
    lwd = last_working_day_of_week(day, holidays)
    standing = sorted(
        (
            s for s in standing_items
            if s.recurrence is RoRecurrence.DAILY or day == lwd
        ),
        key=lambda s: s.position,
    )
    items = [(s.time, s.text) for s in standing]
    items += [
        (ev.start_dt.time(), ev.title)
        for ev in sorted(tp_events, key=lambda e: e.start_dt)
        if ev.start_dt.date() == day
    ]
    items += [(x.time, x.text) for x in extra_items]
    timed = sorted((i for i in items if i[0] is not None), key=lambda i: i[0])
    tbc = [i for i in items if i[0] is None]
    return timed + tbc


def _clean_block(content):
    """Keyed free text, normalized per (l): every line rstripped, leading and
    trailing blank lines dropped; nothing at all renders the explicit '-'."""
    lines = [line.rstrip() for line in (content or "").splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) if lines else "-"


def _timeline_text(items):
    """Blocks of 'HHMMH' / 'TBC' + one '- item' line each, blank line between
    blocks. Consecutive items sharing a slot merge into one block (the sorted
    input puts equal times and all TBC items adjacent)."""
    if not items:
        return "-"
    blocks = []
    for t, text in items:
        slot = "TBC" if t is None else f"{t.strftime('%H%M')}H"
        if not blocks or blocks[-1][0] != slot:
            blocks.append((slot, []))
        blocks[-1][1].append(text.rstrip())
    return "\n\n".join(
        slot + "\n" + "\n".join(f"- {text}" for text in texts)
        for slot, texts in blocks
    )


def render(day, *, cos, cdos, items, boilerplate, messages, key_events) -> RoDoc:
    """The whole document. `cos`/`cdos` are pre-formatted 'RANK NAME' strings
    or None (the SERVICE owns rank formatting and the CONFIRMED-rows-only rule
    — A9); `items` comes from timeline_items; `boilerplate` maps RoSection →
    keyed content; `messages` is the daily pasted blob; `key_events` is the
    (mon..fri) 5-tuple or None."""
    missing = [
        label for label, name in (("CDO/CDS", cdos), ("COS", cos)) if not name
    ]
    parts = [
        f"Routine Orders for {day.strftime('%d%m%y')}",
        day.strftime("%A"),
        SEPARATOR,
        "Duty Personnel",
        f"CDO/CDS: {cdos or MISSING_DUTY}",
        f"COS: {cos or MISSING_DUTY}",
        SEPARATOR,
        "",
        _timeline_text(items),
    ]
    for section in RoSection:
        parts += ["", SEPARATOR, section.label, _clean_block(boilerplate.get(section, ""))]
    parts += ["", SEPARATOR, "Messages and QOTD", _clean_block(messages)]
    week = key_events or ("", "", "", "", "")
    parts += ["", "Key events of the week"]
    parts += [f"{label} - {value}".rstrip() for label, value in zip(_DAY_LABELS, week)]
    return RoDoc(text="\n".join(parts), missing_duties=missing)
