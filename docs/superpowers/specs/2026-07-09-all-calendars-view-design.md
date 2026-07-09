# Consolidated "All Calendars" home view with toggle filters (UI-7)

Owner-approved 2026-07-09. The home page becomes a single **consolidated "All Calendars" view** —
one month grid overlaying every schedule, with **visual toggle filters** to switch each calendar on
or off so the owner can see how the different schedules intersect (the TimeTree behaviour this app
replaces). Constraints unchanged: server-rendered Jinja + vanilla-JS sprinkles only; no new stored
calendar; every existing route and test keeps working.

This design was reconstructed from a prior session that built the feature directly into code with no
written spec (leaving it uncommitted with two stale tests and one open decision). Both decisions are
now locked, below.

## 1. Calendar-as-home

`GET /` renders `calendar/month.html`. The endpoint name stays `main.dashboard`, so every auth
redirect that targets `url_for("main.dashboard")` — `login_view`, post-login, post-password-change —
is untouched. `GET /calendar/month` renders the **same** template through the **same** context
builder, `calendar_month.build_month_context(user, ym_raw)` — one code path, so the two entry points
can never drift.

The old `main/dashboard.html` function-tile page is deleted. Role-gated access to staff surfaces now
lives entirely in the nav (present on every page, already rights-gated by the UI-refresh work); the
home page carries no separate tile list.

*Why one builder in a service, not the route:* the away board, leave panel, and parade documents
already share their derivation through `presence_service`; the month grid follows the same posture —
routes stay thin, the assembly is unit-testable without HTTP.

## 2. Three colour-coded layers over one month grid

| Layer | Source | Colour token | Visibility |
|---|---|---|---|
| TP | `Event.calendar == TP` | `--cal-tp` (indigo) | all users |
| ARCTIC FOE | `Event.calendar == ARCTIC` | `--cal-arctic` (teal) | **command team only** |
| NSF OFF/LEAVE | **derived** from APPROVED NSF leave | `--cal-off` (violet) | all users |

**Decision 1 — the third layer is derived, not stored.** There is no new `Calendar` enum value and
no migration. The violet layer comes from `presence_service.nsf_leave_between(start, end)`, a
*filtered view* of the single `absences_between` derivation — never a second query. This honours the
project's core rule: absences are always derived from APPROVED leave, never plotted into a stored
time-off calendar.

**Decision 2 — the OFF/LEAVE layer is APPROVED leave only.** `nsf_leave_between` keeps rows where
`source == "leave"` AND `person.service is Service.NSF` (leave types OFF/OIL/LL/OL). MC, course, and
briefing statuses are away sources that stay on the away board (`/parade/away`), not on the home
grid — the label "OFF/LEAVE" says exactly what the layer is. The full away picture (leave + direct
absence + out-of-camp status) is unchanged on the away board and leave panel.

**ARCTIC visibility is a server boundary, not a toggle.** `build_month_context` omits ARCTIC event
chips for anyone failing `policy.can_view_arctic`, exactly as the list/detail routes do. The client
toggle is cosmetic only; it is never what protects ARCTIC.

Each layer renders as coloured chips with a leading dot, so the calendar is legible without relying
on colour alone. The OFF/LEAVE layer shows up to 3 name chips per day, then a "+N more" link to that
day's away board. One chip per PERSON (overlapping approved requests dedupe on `person_id`), matching
the away board's own per-person rule. Chips stay in the parent derivation's platoon → name order.

## 3. Toggle filters (TimeTree-style)

A pill row (`.cal-filters`) sits above the grid, one `<button>` per visible layer, each with
`aria-pressed`, a coloured dot, and a text label. Clicking a pill toggles a `hide-cal-<key>` class on
`.month-grid`; pure CSS then hides that layer's chips. The set of hidden layers is persisted in
`localStorage` under `delta.calFilters`, so the choice survives month navigation and return visits.

**No-JS fallback:** with scripting off, no pills are wired and every layer shows — the grid is fully
usable, the toggles are progressive enhancement. The ARCTIC pill only renders for command users
(its chips are already absent server-side for everyone else, so a stale toggle can reveal nothing).

## Testing

- All existing tests stay green; suite grows from 553 (pre-WIP) to **559**.
- `test_main.py` / `test_ui_refresh.py`: `/` is the calendar for every role (`month-grid` present,
  no `Phase 4`/tag leftovers); TP + OFF toggles show for all; the ARCTIC toggle shows only for
  command; staff surfaces reachable via nav for admin and absent for a plain Opr.
- `test_month_view.py`: an approved NSF leave day shows one violet name chip; two overlapping
  requests for one person show one chip; a REGULAR's leave shows no chip (NSF-only layer).
- `test_presence_service_v2.py`: MC / in-camp briefing show **no** OFF/LEAVE chip (leave-only
  boundary); a person on both leave and MC the same day shows exactly one chip (the MC row is
  filtered out, not double-counted).

## Cut (deliberately)

- No new stored `Calendar` value or migration — the third layer stays derived.
- No server-side persistence of toggle state — `localStorage` is enough (scale is a non-issue).
- No change to `/parade/away`, the leave panel, or parade-document semantics — they still read the
  full `absences_between` (leave + direct + out-of-camp status).
- No new event-creation flow for a "third calendar" — TP/ARCTIC CRUD is unchanged.
