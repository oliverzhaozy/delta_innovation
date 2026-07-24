"""RO assembly + render (P5.3). Pure: stdlib + sibling app.domain only.

docs/RO_FORMATS.md is the byte-level authority; owner decisions (l)–(o) and
the 2026-07-24 revision govern everything here: uniform 12-➖ separator and
every emitted line rstripped (l); the CDO/CDS label exists in THIS document
only (m); the timeline is TP events STARTING on the day + hand-keyed extras,
timed blocks ascending then one TBC block last (n as revised — standing items
are gone); the six Matters sections render '-' when empty, the messages blob
is free text, and key events cover the RO date's own week with the
Mon/Tues/Wed/Thurs/Fri spellings, derived from the TP calendar (o as
revised). A missing duty renders an explicit placeholder AND is reported — a
silently blank duty line is how a wrong document gets sent.
"""
from collections import namedtuple
from datetime import timedelta

from app.domain.types import RoSection

SEPARATOR = "➖" * 12
MISSING_DUTY = "[NO CONFIRMED DUTY]"
DEFAULT_KEY_EVENT = "Garage Maintenance"
_DAY_LABELS = ("Mon", "Tues", "Wed", "Thurs", "Fri")

RoDoc = namedtuple("RoDoc", "text missing_duties")


def timeline_items(day, *, tp_events=(), extra_items=()):
    """[(time | None, text)] for `day`, ordered per (n′): timed ascending
    (stable, so ties keep TP-start → keyed order), then one TBC block of
    extras in keyed order.

    Only TP events STARTING on `day` insert — a continuing multi-day event
    has no meaningful time on its later days, and the key-events block
    already carries the week's conducts. Callers pass TP-calendar events
    only; this module does not know calendars exist.
    """
    items = [
        (ev.start_dt.time(), ev.title)
        for ev in sorted(tp_events, key=lambda e: e.start_dt)
        if ev.start_dt.date() == day
    ]
    items += [(x.time, x.text) for x in extra_items]
    timed = sorted((i for i in items if i[0] is not None), key=lambda i: i[0])
    tbc = [i for i in items if i[0] is None]
    return timed + tbc


def weekly_key_events(monday, *, tp_events=(), holiday_names=None):
    """The Mon–Fri key-events 5-tuple, derived from the TP calendar
    (2026-07-24 decision, superseding hand-keyed weeks). Each day lists the
    titles of TP events overlapping it (start date <= day <= end date):
    events starting ON the day first, time-ascending, then continuing
    multi-day events by their start — the owner's sample lists the
    week-long backdrop last on every line. An empty day falls back to the
    public holiday's name (`holiday_names` maps date -> name) or, failing
    that, DEFAULT_KEY_EVENT.
    """
    names = holiday_names or {}
    week = []
    for offset in range(5):
        day = monday + timedelta(days=offset)
        overlapping = sorted(
            (ev for ev in tp_events if ev.start_dt.date() <= day <= ev.end_dt.date()),
            key=lambda e: (e.start_dt.date() != day, e.start_dt),
        )
        titles = ", ".join(ev.title for ev in overlapping)
        week.append(titles or names.get(day, DEFAULT_KEY_EVENT))
    return tuple(week)


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
    (mon..fri) 5-tuple from weekly_key_events."""
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
    parts += ["", "Key events of the week"]
    parts += [f"{label} - {value}".rstrip() for label, value in zip(_DAY_LABELS, key_events)]
    return RoDoc(text="\n".join(parts), missing_duties=missing)
