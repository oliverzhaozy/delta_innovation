# TimeTree-style calendar: create events, all-day, per-calendar labels (UI-9)

Owner-approved 2026-07-09. Builds on the consolidated all-calendars home (UI-7) to make event
creation and display feel like TimeTree — the app this replaces. Constraints unchanged:
server-rendered Jinja + vanilla-JS sprinkles only; no new stored calendar; every existing route and
test keeps working.

## Goals

1. A cleaner prev/next/today month switcher.
2. A prominent create-event entry point on the calendar page.
3. A clear calendar picker (TP vs ARCTIC FOE) when creating — already present, made prominent.
4. An **all-day** toggle.
5. **Per-calendar label tagging** with fixed label lists, and events **coloured by their label**.

`can_edit_events` and `can_view_arctic` are the same predicate (`is_command_team`), so every event
editor may pick either calendar — no extra gating needed.

**Decisions locked with the owner:**
1. **Colour each event by its label** (~19 label colours; unlabeled events fall back to the calendar
   colour). Chips keep their `cal-tp`/`cal-arctic`/`cal-off` class so the existing on/off toggle
   filters still work — only the *colour* now comes from the label.
2. **Prominent "+ New event" button** in the toolbar (editors only). No day-cell click; day numbers
   keep linking to the away board.
3. **Labels are optional** ("— none —" allowed; each calendar has an "Others"/"Admin/Others" catch-all).

## Data model

Two columns added to `event`:
- `all_day` — `Boolean`, `nullable=False`, model default `False`; migration adds it with
  `server_default sa.false()` (SQLite batch requires a server default for NOT NULL on an existing table).
- `label` — `String(40)`, nullable; stores the label's value string (e.g. `"MPT/PMCS/EAS"`).

`Event.label_enum` resolves `self.label` to its `TpLabel`/`ArcticLabel` member (or `None`) via
`label_class_for(self.calendar)`, so month/detail/list templates read display text and colour slug
from one place. The `end_dt > start_dt` check constraint and `ix_event_range` index are unchanged —
all-day normalization keeps `end > start` true even for a single day.

Migration off head `cc534ff0410d`, `batch_alter_table('event')` add/drop, matching `downgrade()`.

## Domain

Label enums in `app/domain/types.py` (the file's `str, enum.Enum` + `.label` idiom), each with a
css-safe, calendar-prefixed `.slug`:
- **TpLabel**: PT, VOC, MPT/PMCS/EAS, FFP, HRC, IPPT, Ops, Holidays, Others.
- **ArcticLabel**: Conducts, Admin/Others, Leave/OFF/MC/ORD, Duties/Neutral, On Course, ICT,
  Exercises, Ops/Ops related, FFP/HRC training, Coy commitments.

All label value strings are distinct across the two enums, so value → calendar is unambiguous.

Pure module `app/domain/events.py` (no Flask/DB), unit-tested without HTTP:
- `label_class_for(calendar)` → `TpLabel | ArcticLabel`.
- `is_valid_label(calendar, value)` → bool (empty/None allowed — labels are optional).
- `all_day_bounds(start_date, end_date)` → `(datetime@00:00, datetime@time.max)` so a single-day
  all-day event still satisfies `end_dt > start_dt` and the month grid buckets it onto exactly its
  days (bucketing uses `.date()`).

## Form and routes

`EventForm` gains `all_day` (BooleanField) and `label` (SelectField, `validators=[Optional()]`,
`validate_choice=False` so an absent/empty label passes — keeps existing no-label POSTs green;
choices set at request time). `validate_end_dt` becomes all-day-aware (same-day allowed when
all-day). `validate_label` rejects a label outside the selected calendar's set.

Routes `new`/`edit` set `all_day` and `label`; when all-day, start/end are replaced via
`events.all_day_bounds(...)`. A `label_calendars` map (`{value: "tp"|"arctic"}`) is passed to the
form template for the JS filter.

## Templates, CSS, JS

- **month.html** — one clean `.cal-toolbar`: month title, a `Today` button (literal word kept — a
  test pins it), `‹`/`›` chevrons (prev/next `?ym=`), and a right-aligned "+ New event" button
  (editors only). Toggle pills stay below. Event chips gain the label colour class and show
  `label · title`.
- **form.html** — all-day toggle, label select, the visible calendar picker; a note that all-day
  ignores the time.
- **detail.html** — the label chip and "All day"/times (date-only when all-day).
- **styles.css** — `.cal-toolbar` + buttons; ~19 `.ev-<slug>` colour classes (solid bar bg + paired
  accessible foreground, via the accessible categorical-palette method), placed after the `.chip.cal-*`
  rules so label colour wins for labeled chips; unlabeled chips keep the calendar tint. Toggle-hide
  rules unchanged (keyed on `cal-*`).
- **app.js** — two progressive-enhancement sprinkles: filter the label `<select>` to the selected
  calendar (embedded `label_calendars` map), and de-emphasise the time when all-day is on. No-JS: all
  options show and the server validates the pairing.

## Testing

- Pure domain (`tests/test_event_labels.py`): `all_day_bounds` (single/multi-day, boundaries);
  `is_valid_label` (right calendar ok, wrong rejected, empty ok, unknown rejected); unique `.slug` per member.
- CRUD (extend `tests/test_calendar_crud.py`): all-day storage (00:00 → end-of-day); valid label
  stored + chip carries `ev-<slug>`; cross-calendar label rejected with a field error (nothing
  persisted); no-label create still works; edit persists all-day/label.
- Nav: toolbar renders `Today`, `‹`/`›`, and (editor) "+ New event"; `month-grid` and `chip cal-off`
  assertions unchanged. Full suite green, count ≥ 559.

## Out of scope (deliberate cuts)

- No day-cell click-to-create (owner chose the toolbar button).
- No repeat/reminder/to-do/location/URL fields from the screenshot — the participant model already
  covers "members".
- No change to the derived OFF/LEAVE layer, the away board, or parade/leave semantics.
- No weekly view (month grid only, as today).
