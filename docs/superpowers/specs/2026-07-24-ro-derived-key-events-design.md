# RO: remove standing timeline items, derive key events from TP — design

Date: 2026-07-24. Approved by owner in conversation. Partially supersedes
RO_FORMATS.md decisions (n) and (o).

## What changes

1. **Standing timeline items are removed entirely.** The `ro_standing_item`
   table, `RoStandingItem` model, `RoRecurrence` enum, the `/ro/standing`
   pages, and the standing lines themselves (0600H Roll call & Breakfast,
   TBC LP, TBC SBA) all go. The RO timeline becomes: TP events starting on
   the day (timed, ascending) + hand-keyed extras (timed merged in; TBC
   block last). `last_working_day_of_week` goes too — its only consumer was
   the standing-SBA filter, and with it `timeline_items` loses its
   `holidays` parameter.
2. **Weekly key events are no longer keyed by hand.** The
   `weekly_key_events` table, `WeeklyKeyEvents` model, `/ro/key-events`
   page, and `ro_service.set_week` are removed. The Mon–Fri block is
   derived at render time from the TP calendar.

## Key-events derivation rule (owner decisions, 2026-07-24)

For each weekday D (Mon–Fri) of the RO date's week:

- Titles of TP-calendar events **overlapping** D (`start_dt.date() <= D <=
  end_dt.date()`), comma-joined (`", "`) — a multi-day exercise appears on
  every day it spans. Order within a line: events starting ON the day
  first, time-ascending, then continuing multi-day events by their start —
  the owner's sample lists the week-long backdrop ("Site Testing") last on
  every line.
- If no TP event overlaps D and D is a public holiday: the holiday's
  **name** (e.g. `Wed - National Day`).
- Otherwise: `Garage Maintenance`.
- A holiday that does have TP events shows just the events, not the name.

## Where it lives

- New pure builder `domain/ro.weekly_key_events(monday, *, tp_events,
  holiday_names)` → 5-tuple of strings; `holiday_names` is a
  `{date: name}` mapping. `render`'s `key_events` is now always a real
  5-tuple (the `None` fallback path is deleted).
- `ro_service.build` fetches TP events overlapping the Mon–Fri span and the
  week's holiday names via a new `PublicHoliday.names_between(start, end)`
  → `{date: name}` classmethod (`dates_between` stays for other callers).
- One migration drops `ro_standing_item` and `weekly_key_events`. Data in
  both tables is destroyed — owner explicitly approved; key events are now
  derivable and standing lines are deliberately gone.
- `purge_service` loses its `weekly_key_events` retention purge.
- `templates/ro/standing.html` and `key_events.html` are deleted; the two
  admin links in `ro/view.html` go; `/ro/boilerplate` stays.

## Why (decision level)

- Deriving key events from TP kills a second manual keying of the same
  facts — the single-source-of-truth rule this app exists for.
- Removal is full (models + tables + pages), not soft: dormant admin pages
  that no longer affect the document are a trap for the S3.
- The builder is pure and lives in `domain/` so pytest pins the
  overlap/default/holiday logic without HTTP.

## Test impact

- `test_ro_domain`: standing + last-working-day tests removed; new unit
  tests for `weekly_key_events` (multi-day overlap, join order, Garage
  Maintenance default, holiday name, holiday-with-events) and the slimmer
  `timeline_items`.
- `test_ro_service` goldens: timeline loses the three standing lines; the
  key-events block is derived.
- `test_ro_models`, `test_ro_page`, `test_e2e_phase5`, `test_purge`: the
  removed surfaces' tests go or are updated.
