# Calendar — consolidated all-calendars home, colour-coded layers, TimeTree-style events

Owner-approved 2026-07-09. One calendar feature, built and committed in four passes:
the consolidated all-calendars home view (UI-7, `72057cb`), a wider month grid (UI-8,
`95b1bd1`), TimeTree-style event creation with all-day and per-calendar labels (UI-9,
`c93978c`), and day-cell click-to-create (UI-10, `e42e6a1`). This document consolidates
the two written design specs into the feature's final state. Constraints unchanged
throughout: server-rendered Jinja + vanilla-JS sprinkles only; no new stored calendar;
every existing route and test keeps working.

The home page becomes a single **consolidated "All Calendars" view** — one month grid
overlaying every schedule, with **visual toggle filters** to switch each calendar on or
off so the owner can see how the schedules intersect (the TimeTree behaviour this app
replaces) — and event creation is made to feel like TimeTree: a clean month switcher, a
prominent create button, an all-day toggle, and per-calendar labels that colour the chips.

## 1. Calendar-as-home

`GET /` renders `calendar/month.html`. The endpoint name stays `main.dashboard`, so every
auth redirect that targets `url_for("main.dashboard")` — `login_view`, post-login,
post-password-change — is untouched. `GET /calendar/month` renders the **same** template
through the **same** context builder, `calendar_month.build_month_context(user, ym_raw)` —
one code path, so the two entry points can never drift.

The old `main/dashboard.html` function-tile page is deleted. Role-gated access to staff
surfaces now lives entirely in the nav (present on every page, already rights-gated by the
UI-refresh work); the home page carries no separate tile list.

*Why one builder in a service, not the route:* the away board, leave panel, and parade
documents already share their derivation through `presence_service`; the month grid follows
the same posture — routes stay thin, the assembly is unit-testable without HTTP.

## 2. Three colour-coded layers over one month grid

| Layer | Source | Colour token | Visibility |
|---|---|---|---|
| TP | `Event.calendar == TP` | `--cal-tp` (indigo) | all users |
| ARCTIC FOE | `Event.calendar == ARCTIC` | `--cal-arctic` (teal) | **command team only** |
| NSF OFF/LEAVE | **derived** from APPROVED NSF leave | `--cal-off` (violet) | all users |

**Decision — the third layer is derived, not stored.** There is no new `Calendar` enum
value and no migration. The violet layer comes from
`presence_service.nsf_leave_between(start, end)`, a *filtered view* of the single
`absences_between` derivation — never a second query. This honours the project's core rule:
absences are always derived from APPROVED leave, never plotted into a stored time-off
calendar.

**Decision — the OFF/LEAVE layer is APPROVED leave only.** `nsf_leave_between` keeps rows
where `source == "leave"` AND `person.service is Service.NSF` (leave types OFF/OIL/LL/OL).
MC, course, and briefing statuses are away sources that stay on the away board
(`/parade/away`), not on the home grid — the label "OFF/LEAVE" says exactly what the layer
is. The full away picture (leave + direct absence + out-of-camp status) is unchanged on the
away board and leave panel.

**ARCTIC visibility is a server boundary, not a toggle.** `build_month_context` omits ARCTIC
event chips for anyone failing `policy.can_view_arctic`, exactly as the list/detail routes
do. The client toggle is cosmetic only; it is never what protects ARCTIC.

Each layer renders as coloured chips with a leading dot, so the calendar is legible without
relying on colour alone. The OFF/LEAVE layer shows up to 3 name chips per day, then a
"+N more" link to that day's away board. One chip per PERSON (overlapping approved requests
dedupe on `person_id`), matching the away board's own per-person rule. Chips stay in the
parent derivation's platoon → name order.

## 3. Toggle filters (TimeTree-style)

A pill row (`.cal-filters`) sits below the toolbar, one `<button>` per visible layer, each
with `aria-pressed`, a coloured dot, and a text label. Clicking a pill toggles a
`hide-cal-<key>` class on `.month-grid`; pure CSS then hides that layer's chips. The set of
hidden layers is persisted in `localStorage` under `delta.calFilters`, so the choice
survives month navigation and return visits.

**No-JS fallback:** with scripting off, no pills are wired and every layer shows — the grid
is fully usable, the toggles are progressive enhancement. The ARCTIC pill only renders for
command users (its chips are already absent server-side for everyone else, so a stale toggle
can reveal nothing).

## 4. Toolbar and event creation

`can_edit_events` and `can_view_arctic` are the same predicate (`is_command_team`), so every
event editor may pick either calendar — no extra gating needed.

**Decisions locked with the owner:**

1. **Prominent "+ New event" button** in the toolbar (editors only).
2. **A clear calendar picker** (TP vs ARCTIC FOE) on the create/edit form — already present,
   made prominent.

`month.html` carries one clean `.cal-toolbar`: the month title, a `Today` button (the literal
word is kept — a test pins it), `‹`/`›` chevrons (prev/next `?ym=`), and a right-aligned
"+ New event" button (editors only). The toggle pills stay below.

**Day-cell click-to-create (UI-10).** Each in-month day cell gains a subtle "+" (editors
only) linking to `/calendar/new?date=YYYY-MM-DD`; the day *number* keeps its away-board link.
The `new` route pre-fills start/end to that day (08:00–09:00) on GET; a bad or missing date
falls through to a blank form, following `parade.away`'s forgiving `?date=` convention.

## 5. All-day events

**Decision — an all-day toggle**, stored as an explicit column rather than inferred from the
times.

Two columns are added to `event`:
- `all_day` — `Boolean`, `nullable=False`, model default `False`; the migration adds it with
  `server_default sa.false()` (SQLite batch requires a server default for NOT NULL on an
  existing table).
- `label` — `String(40)`, nullable; stores the label's value string (e.g. `"MPT/PMCS/EAS"`).

The migration is off head `cc534ff0410d`, `batch_alter_table('event')` add/drop with a
matching `downgrade()`. The `end_dt > start_dt` check constraint and the `ix_event_range`
index are unchanged — all-day normalization keeps `end > start` true even for a single day.

Pure module `app/domain/events.py` (no Flask/DB, unit-tested without HTTP) owns the
convention: `all_day_bounds(start_date, end_date)` → `(datetime@00:00, datetime@time.max)`,
so a single-day all-day event still satisfies `end_dt > start_dt` and the month grid buckets
it onto exactly its days (bucketing uses `.date()`).

`EventForm` gains `all_day` (BooleanField); `validate_end_dt` becomes all-day-aware (same-day
allowed when all-day). The `new`/`edit` routes replace start/end via
`events.all_day_bounds(...)` when all-day is set. On the form, all-day de-emphasises the time
inputs; the detail page shows "All day" (date-only) instead of times.

## 6. Per-calendar labels, coloured chips

**Decisions locked with the owner:**

1. **Colour each event by its label** (~19 label colours; unlabeled events fall back to the
   calendar colour). Chips keep their `cal-tp`/`cal-arctic`/`cal-off` class so the existing
   on/off toggle filters still work — only the *colour* now comes from the label.
2. **Labels are optional** ("— none —" allowed; each calendar has an "Others"/"Admin/Others"
   catch-all).

Label enums live in `app/domain/types.py` (the file's `str, enum.Enum` + `.label` idiom),
each member with a css-safe, calendar-prefixed `.slug`:

- **TpLabel**: PT, VOC, MPT/PMCS/EAS, FFP, HRC, IPPT, Ops, Holidays, Others.
- **ArcticLabel**: Conducts, Admin/Others, Leave/OFF/MC/ORD, Duties/Neutral, On Course, ICT,
  Exercises, Ops/Ops related, FFP/HRC training, Coy commitments.

All label value strings are distinct across the two enums, so value → calendar is
unambiguous. `Event.label_enum` resolves `self.label` to its `TpLabel`/`ArcticLabel` member
(or `None`) via `label_class_for(self.calendar)`, so month/detail/list templates read display
text and colour slug from one place. `app/domain/events.py` also provides
`label_class_for(calendar)` → `TpLabel | ArcticLabel` and `is_valid_label(calendar, value)` →
bool (empty/None allowed — labels are optional).

`EventForm` gains `label` (SelectField, `validators=[Optional()]`, `validate_choice=False` so
an absent/empty label passes — keeps existing no-label POSTs green; choices are set at request
time). `validate_label` rejects a label outside the selected calendar's set. The routes pass a
`label_calendars` map (`{value: "tp"|"arctic"}`) to the form template for the JS filter.

**CSS/JS.** `styles.css` gains ~19 `.ev-<slug>` colour classes (solid bar bg + paired
accessible foreground, via the accessible categorical-palette method), placed after the
`.chip.cal-*` rules so label colour wins for labeled chips; unlabeled chips keep the calendar
tint. The toggle-hide rules are unchanged (keyed on `cal-*`). Event chips show `label · title`.
`app.js` carries two progressive-enhancement sprinkles: filter the label `<select>` to the
selected calendar (embedded `label_calendars` map), and de-emphasise the time when all-day is
on. With no JS, all options show and the server validates the pairing.

## Testing

The suite grew from 553 (pre-feature) to **580** across UI-7…UI-10, all existing tests still
green:

- **Calendar-as-home** — `/` is the calendar for every role (`month-grid` present, no
  `Phase 4`/tag leftovers); TP + OFF toggles show for all; the ARCTIC toggle shows only for
  command; staff surfaces reachable via nav for admin, absent for a plain Opr.
- **Derived OFF/LEAVE layer** — an approved NSF leave day shows one violet name chip; two
  overlapping requests for one person show one chip; a REGULAR's leave shows no chip (NSF-only
  layer); MC / in-camp briefing show **no** OFF/LEAVE chip (leave-only boundary); a person on
  both leave and MC the same day shows exactly one chip (the MC row is filtered out, not
  double-counted).
- **Pure domain** (`tests/test_event_labels.py`) — `all_day_bounds` (single/multi-day,
  boundaries); `is_valid_label` (right calendar ok, wrong rejected, empty ok, unknown
  rejected); unique `.slug` per member.
- **CRUD** (`tests/test_calendar_crud.py`) — all-day storage (00:00 → end-of-day); valid label
  stored + chip carries `ev-<slug>`; cross-calendar label rejected with a field error (nothing
  persisted); no-label create still works; edit persists all-day/label; day-cell `?date=`
  pre-fill (good date → 08:00–09:00, bad/missing → blank form).
- **Toolbar/nav** — toolbar renders `Today`, `‹`/`›`, and (editor) "+ New event";
  `month-grid` and `chip cal-off` assertions unchanged.

## Cut (deliberately)

- No new stored `Calendar` value or migration — the third layer stays derived.
- No server-side persistence of toggle state — `localStorage` is enough (scale is a
  non-issue).
- No change to `/parade/away`, the leave panel, or parade-document semantics — they still read
  the full `absences_between` (leave + direct + out-of-camp status).
- No repeat / reminder / to-do / location / URL fields from the TimeTree screenshot — the
  participant model already covers "members".
- No weekly view (month grid only, as today).
