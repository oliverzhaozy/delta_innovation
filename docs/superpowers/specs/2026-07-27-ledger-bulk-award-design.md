# Ledger bulk award — design

**Date:** 2026-07-27 · **Status:** approved (owner, in-session)

## What

A "Bulk award" page that lets a ledger manager (S3 etc.) credit the same
OFF **or** OIL amount to many people in one submit, with one shared reason.
Owner decisions (this session):

- **One amount + kind selector** — a Kind field (OFF or OIL), one Days box,
  one Reason. Awarding both kinds = two submissions.
- **NSFs only** — the picker shows no Regulars group and no regular names;
  every category resolves against the NSF-only active roster (consistent
  with the NSF-only ledger index, commit `5c8271c`).
- **Add only** — no deduct direction. Deductions/corrections stay on the
  per-person adjust page.

## Route & permission

- `GET/POST /ledger/bulk-award` in `app/blueprints/ledger/routes.py`,
  gated `@require(policy.can_manage_ledger)` like the rest of the ledger.
- Entry point: a "Bulk award" button on `/ledger/` (ledger index page head).
- On success: flash `Awarded {days} {KIND} to {n} people.` and redirect to
  `ledger.index`.

## Form (`app/blueprints/ledger/forms.py`)

`BulkAwardForm`, following `FpBulkAddForm`'s picker wire format:

- `categories = SelectMultipleField(...)` — same choices pattern as
  `FpBulkAddForm` (`ParticipantCategory` values + `"ALL"` pseudo-choice).
- `people = SelectMultipleField(coerce=int)` — choices set in the route to
  the **NSF** active roster ids.
- `kind = SelectField` — OFF/OIL, from `BalanceKind` (same as
  `AdjustmentForm.kind`).
- `days = DecimalField` — same 0.5–30 range and whole/half-day validator as
  `AdjustmentForm.days` (ledger stores integer half-days).
- `reason = StringField` — required, ≤300 (same as `AdjustmentForm.reason`).

## Selection resolution (in the route, at submit time)

Copy the `morning_fp_new` expansion exactly, but against the NSF roster:

```
roster = [p for p in event_service.active_roster() if p.service is Service.NSF]
```

- `"ALL"` → every person in `roster` (i.e. every active NSF).
- Each other category → `participants.in_category(p, category)` over `roster`
  (so COMMAND_TEAM = NSF command appointments only; REGULAR, if ever POSTed
  stale, resolves to nobody).
- Union with explicitly ticked `people` ids **restricted to the NSF roster**
  (a POSTed regular/inactive id must never create an entry — the form's
  `people` choices already enforce this; the roster intersection in the
  route is the belt-and-braces object check).
- The union is a set: a person ticked via NSF + their platoon gets **one**
  entry, never two.
- Empty selection → flash error, re-render the form (no redirect loop).

## Write path

One submit = ONE transaction: for each resolved person,
`ledger_service.post_entry(person_id, kind, +days*2 half-days, reason,
source=LedgerSource.MANUAL, created_by_id=current_user.id)`, then a single
`db.session.commit()`. No new service function needed — `post_entry` is the
existing single-row primitive and the loop lives in the route like other
bulk writes. Entries are indistinguishable from single-person manual
adjustments on the person history page (shared reason, MANUAL source).

## Template (`app/templates/ledger/bulk_award.html`)

- `form method=post` with `data-people-picker` (the app.js hook that keeps
  group/member checkboxes in sync) — exactly one such form on the page.
- `{% include "_people_picker.html" %}` with `picker_groups` passed as the
  NSF-filtered groups: **NSF, Platoon 1–3** (build in the route with
  `participants.in_category` + `parade.parade_sort_key` over the NSF roster,
  mirroring `event_service.picker_groups`); `command_ids` filtered to NSFs.
- Below the picker: Kind, Days, Reason fields and an "Award" submit button.

## Tests (`tests/test_ledger_pages.py`)

1. Bulk award to two ticked people credits both balances and writes MANUAL
   entries with the shared reason.
2. Platoon category box expands to that platoon's NSFs.
3. Overlapping selection (NSF category + a member also ticked) → exactly one
   entry for that person.
4. A regular's id smuggled into the POST creates no entry; the bulk page
   never lists regular names.
5. Opr (no `can_manage_ledger`) → 403.
6. Quarter-day (e.g. 0.7) rejected by the whole/half validator.
7. Empty selection → error flash, nothing written.

## Out of scope

Bulk deduct; awarding both kinds in one submit; any change to the
per-person adjust flow or ledger history rendering.

## Amendment (owner, 2026-07-28)

Three picker/label tweaks scoped to the bulk-award page only — the
calendar/FP pickers render exactly as before:

- **No ALL / Command team rows.** `_people_picker.html` gains an optional
  `picker_hide_top` knob (undefined → today's behavior); the bulk page sets
  it truthy, so the two top checkboxes no longer render. "All NSFs" (the
  relabelled NSF group) is the everyone-selector, making an ALL box
  redundant. `BulkAwardForm.categories` choices are now exactly the four
  picker groups (`BULK_AWARD_CATEGORIES` = NSF + Platoon 1–3), defined once
  in `forms.py` and imported by the route (the old `"ALL"` pseudo-choice and
  its route-side expansion are gone). A stale `ALL`/`COMMAND_TEAM` POST now
  fails WTForms choice validation and re-renders with a field error.
- **"All NSFs" label.** The include gains an optional `picker_group_labels`
  ({category.value: label}) override; the bulk page passes
  `{"NSF": "All NSFs"}`. The `ParticipantCategory.NSF` enum label is
  unchanged, so other pages still read "NSF".
- **No reason placeholder.** The bulk template's reason field drops the
  `placeholder="e.g. Awarded for exercise support"` kwarg.

`command_ids` is passed to the include as an empty set from the bulk route:
the Command team row is hidden so no id needs a `data-command` marker, but
the include still evaluates `p.id in command_ids`, so an empty set keeps that
reference safe (app.js's `#cat_command` lookup is already null-guarded).
