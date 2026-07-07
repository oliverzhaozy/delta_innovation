# PLAN-duty-service — P4.4: duty_service (availability + generation + confirm)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Authority:** `docs/TECH_PLAN.md` task **P4.4**, amended by pre-flight addendum items **A4** and **A7** and contract **C/P4.4**. Where this plan and TECH_PLAN conflict, TECH_PLAN + addendum win. Executor behavior: `docs/fable-behavior.md`.

**Goal:** Build `app/services/duty_service.py` — the DB-aware layer that shapes one absence fetch + overnight-TP resolution + existing assignments into the pure P4.2/P4.3 inputs, writes PROPOSED rosters, and confirms a month behind a content fingerprint.

**Architecture:** Pure modules already exist and are FROZEN (`domain/eligibility.py` per addendum B4, `domain/roster.py` as committed in P4.3 — do not change either). This task is glue only: fetch → shape → call pure code → write rows in one transaction. It also promotes `presence_service._fetch_rows` to public `fetch_absence_rows` so duty availability reads the same single derivation as everything else — a third absence-fetch path is the drift bug this app exists to kill.

**Tech stack:** Flask + SQLAlchemy + SQLite (WAL). Tests via pytest with the existing `conftest.py` app/db fixtures.

## Global constraints (apply to every task below)

- Python: `.venv/Scripts/python` (Windows venv). Full suite: `.venv/Scripts/python -m pytest -q`.
- Baseline test count **435**. After this plan the count must be **strictly greater**; record the actual number.
- Parade goldens must stay **byte-identical** (no task here touches documents, so any golden change is a bug).
- `flask routes` output must be **unchanged** by this plan (no routes in contract).
- Exactly **one** alembic head; **no migration** in this plan (models landed in P4.1).
- Domain purity gate: `rg -l "flask|app\.models|app\.extensions|app\.services" app/domain/` returns nothing.
- Contract (addendum C/P4.4) — **Forbidden:** routes, templates, changing `presence_inputs`'s signature (that is P4.7), touching CONFIRMED rows in regeneration. If it isn't in a Produces list below, do not build it.
- Commit after each task: imperative message naming the task (e.g. `P4.4: promote fetch_absence_rows shared fetch`), then push.
- No placeholders, no TODOs, no `except:` — see `docs/fable-behavior.md` §3.

## Files

- Modify: `app/services/presence_service.py` (rename `_fetch_rows` → `fetch_absence_rows`, lines 48, 110, 199)
- Create: `app/services/duty_service.py`
- Create: `tests/test_duty_service.py`

## Interfaces produced (frozen for later plans)

```python
# app/services/duty_service.py
class RosterChanged(Exception): ...          # confirm-time fingerprint mismatch (A4)
month_bounds(month: str) -> (date, date)    # "YYYY-MM" -> (first, last); ValueError on junk
availability_for_month(month: str) -> (pools, availability, confirmed_rows)
generate_month(month: str, actor) -> None   # writes PROPOSED rows, one commit
roster_fingerprint(month: str) -> str       # sha256 over the month's PROPOSED content
confirm_month(month: str, actor, fingerprint: str) -> None  # raises RosterChanged
# presence_service
fetch_absence_rows(start_date, end_date) -> (leaves, directs, statuses)  # was _fetch_rows
```

---

### Task 1: Promote `_fetch_rows` to public `fetch_absence_rows`

**Files:** Modify `app/services/presence_service.py`. No new test file (existing suite is the regression net).

- [ ] **Step 1: Rename with both callers.** In `app/services/presence_service.py`:
  - Line 48: `def _fetch_rows(start_date, end_date):` → `def fetch_absence_rows(start_date, end_date):`
  - Line 110 (in `absences_between`): `leaves, directs, statuses = _fetch_rows(start_date, end_date)` → `fetch_absence_rows(...)`
  - Line 199 (in `presence_inputs`): same rename.
  - Update the docstring's first line to say it is now the shared public fetch that `absences_between`, `presence_inputs`, **and duty availability (P4.4)** all read — keep the rest verbatim.

- [ ] **Step 2: Grep for stale references — must be zero.**

Run: `rg "_fetch_rows" app tests`
Expected: no output. (If tests reference the old name, update them to the new name — do not keep an alias; a compatibility alias IS a second fetch path.)

- [ ] **Step 3: Full suite.**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `435 passed` (rename only — count unchanged is correct **for this task only**).

- [ ] **Step 4: Commit.**

```bash
git add app/services/presence_service.py tests
git commit -m "P4.4: promote fetch_absence_rows as the shared absence fetch"
git push
```

---

### Task 2: `duty_service.py` — month bounds + availability shaping

**Files:** Create `app/services/duty_service.py`; create `tests/test_duty_service.py`.

- [ ] **Step 1: Write failing tests** in `tests/test_duty_service.py`. Use the existing conftest fixtures the way `tests/test_eligibility.py` and `tests/test_presence_service_v2.py` do (read both first for the fixture idiom — people are created via the Person model with rank/appointment enums). Cover:

```python
import pytest
from datetime import date, datetime

from app.domain.types import (
    Appointment, Calendar, DayPart, Duty, DutyState, LeaveType, Rank,
    RequestStatus, Service, StatusType,
)
from app.models import DutyAssignment, Event, EventParticipant, LeaveRequest, StatusEntry
from app.services import duty_service


def test_month_bounds():
    assert duty_service.month_bounds("2026-07") == (date(2026, 7, 1), date(2026, 7, 31))
    assert duty_service.month_bounds("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    with pytest.raises(ValueError):
        duty_service.month_bounds("garbage")


def test_availability_pm_half_day_blocks(app, ...):
    # person: Opr, 3SG, NSF (eligible COS); APPROVED PM leave on 2026-07-15
    # availability(person, date(2026,7,15)) is False (decision d — ANY day_part blocks)


def test_availability_in_camp_status_does_not_block(...):
    # person with an in_camp=True BRIEFING status covering the day -> True
    # (in camp is not away; only out-of-camp statuses block)


def test_availability_overnight_tp_event_blocks_day_event_does_not(...):
    # overnight TP event (end_dt.date() > start_dt.date()) tagging the person
    # via a category row -> False on every covered day; a same-day 0800-1700
    # event -> True. An overnight ARCTIC event -> True (only TP blocks).


def test_availability_confirmed_assignment_blocks_same_date(...):
    # person holds a CONFIRMED assignment on the day -> False


def test_pools_shape(...):
    # pools maps both Duty members; a 3SG PS is in NEITHER pool (the known gap)
```

- [ ] **Step 2: Run tests to verify they fail.**

Run: `.venv/Scripts/python -m pytest tests/test_duty_service.py -q`
Expected: FAIL with `ModuleNotFoundError`/`AttributeError` (duty_service does not exist).

- [ ] **Step 3: Implement.** Create `app/services/duty_service.py`:

```python
"""Duty roster orchestration (P4.4): shape DB rows into the pure P4.2/P4.3
inputs, write PROPOSED rosters, confirm behind a content fingerprint.

The pure modules are the law (eligibility.py is frozen per addendum B4;
roster.py is deterministic and solver-free); this module only fetches and
shapes. Availability reads the SAME shared absence fetch as the away board and
every parade document (presence_service.fetch_absence_rows) — a third fetch
path is the drift bug this app exists to kill.
"""
import hashlib
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import update

from app.domain import eligibility, roster
from app.domain.dates import iter_days, now_sgt
from app.domain.types import Calendar, Duty, DutyState
from app.extensions import db
from app.models import DutyAssignment, Event
from app.services import event_service, presence_service


class RosterChanged(Exception):
    """The month's PROPOSED roster changed between page load and confirm (A4);
    message is user-facing."""


def month_bounds(month: str):
    """'YYYY-MM' -> (first day, last day). ValueError on anything else."""
    year_s, mon_s = month.split("-")
    year, mon = int(year_s), int(mon_s)
    return date(year, mon, 1), date(year, mon, monthrange(year, mon)[1])


def _assignments_between(first, last, *, state=None):
    query = db.session.query(DutyAssignment).filter(
        DutyAssignment.date >= first, DutyAssignment.date <= last
    )
    if state is not None:
        query = query.filter(DutyAssignment.state == state)
    return query.order_by(DutyAssignment.date, DutyAssignment.duty).all()


def availability_for_month(month: str):
    """(pools, availability, confirmed_rows) for the month — the shaped inputs
    the generator and the manual-assign checks (P4.6) both consume.

    One shared absence fetch for the whole month; in-camp statuses do NOT
    block (in camp is not away — a briefing eats meals and can hold a duty).
    Only OVERNIGHT TP events block (P4.2's stated v1 definition); ARCTIC rows
    are contingency plans, not scheduled conducts, and never block.
    """
    first, last = month_bounds(month)
    people = event_service.active_roster()
    pools = {duty: eligibility.pool(duty, people) for duty in Duty}

    leaves, directs, statuses = presence_service.fetch_absence_rows(first, last)
    absence_rows = defaultdict(list)
    for row in leaves:
        absence_rows[row.person_id].append(row)
    for row in directs:
        absence_rows[row.person_id].append(row)
    for row in statuses:
        if not row.in_camp:
            absence_rows[row.person_id].append(row)

    overnight = defaultdict(list)
    window_start = datetime.combine(first, time.min)
    window_end = datetime.combine(last + timedelta(days=1), time.min)
    events = (
        db.session.query(Event)
        .filter(
            Event.calendar == Calendar.TP,
            Event.start_dt < window_end,
            Event.end_dt > window_start,
        )
        .all()
    )
    for ev in events:
        if ev.end_dt.date() > ev.start_dt.date():
            for p in event_service.resolve_participants(ev):
                overnight[p.id].append(ev)

    confirmed = _assignments_between(first, last, state=DutyState.CONFIRMED)
    held_dates = defaultdict(set)
    for row in confirmed:
        held_dates[row.person_id].add(row.date)

    def availability(person, day):
        return eligibility.available(
            person,
            day,
            absence_rows=absence_rows.get(person.id, ()),
            overnight_events=overnight.get(person.id, ()),
            other_duty_dates=held_dates.get(person.id, frozenset()),
        )

    return pools, availability, confirmed
```

- [ ] **Step 4: Run tests.**

Run: `.venv/Scripts/python -m pytest tests/test_duty_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add app/services/duty_service.py tests/test_duty_service.py
git commit -m "P4.4: duty_service availability shaping over the shared fetch"
git push
```

---

### Task 3: `generate_month` — PROPOSED rows, CONFIRMED untouched

- [ ] **Step 1: Write failing tests** (append to `tests/test_duty_service.py`):

```python
def test_generate_writes_proposed_and_matches_pure_module(...):
    # Fixture month with 2 COS-eligible + 2 CDOS-eligible people, no absences.
    # generate_month("2026-08", actor) then rebuild the same inputs by hand and
    # call roster.generate directly per duty; DB rows == pure output, all PROPOSED.


def test_regenerate_preserves_confirmed_and_replans_rest(...):
    # Seed one CONFIRMED row (2026-08-10, COS, person X) + generate_month.
    # Assert: the CONFIRMED row is byte-identical after (same id/person/state);
    # no PROPOSED row exists for (2026-08-10, COS); other slots regenerated.


def test_generate_blank_days_have_no_row(...):
    # Empty CDOS pool -> zero CDOS rows written (blanks are absence of a row).


def test_generate_replaces_only_proposed(...):
    # Run generate_month twice; second run leaves exactly one PROPOSED row per
    # open slot (no duplicates — UNIQUE(date, duty) would also catch this).
```

- [ ] **Step 2: Run to verify failure.** Expected: `AttributeError: generate_month`.

- [ ] **Step 3: Implement** (append to `duty_service.py`):

```python
def _prior_month_inputs(first):
    """CONFIRMED-only history for the generator (A7): counts = the whole
    previous month; tail = its last 3 calendar days (Fri->Mon adjacency can
    reach 3 days back). Both empty when no previous month exists — an empty
    tail means no adjacency constraint from the past, defined, not crashed."""
    prev_last = first - timedelta(days=1)
    prev_first = prev_last.replace(day=1)
    rows = _assignments_between(prev_first, prev_last, state=DutyState.CONFIRMED)
    prior_counts = {duty: defaultdict(int) for duty in Duty}
    for row in rows:
        prior_counts[row.duty][row.person_id] += 1
    tail_start = prev_last - timedelta(days=2)
    prior_tail = [(r.date, r.duty, r.person_id) for r in rows if r.date >= tail_start]
    return prior_counts, prior_tail


def generate_month(month: str, actor):
    """Generate the month's PROPOSED roster in one transaction, replacing only
    PROPOSED rows — CONFIRMED rows are never touched by regeneration.

    One generate() call PER DUTY over that duty's open (non-CONFIRMED) days:
    the appointment pools are disjoint, so per-duty runs cannot double-book a
    person, and skipping confirmed slots this way keeps the pure module's
    internal counts honest (no discarded picks). In-month CONFIRMED rows join
    the tail (adjacency must see them) and the prior counts (evenness bias).
    """
    first, last = month_bounds(month)
    pools, availability, confirmed = availability_for_month(month)
    prior_counts, prior_tail = _prior_month_inputs(first)

    confirmed_slots = {(r.date, r.duty) for r in confirmed}
    tail = list(prior_tail) + [(r.date, r.duty, r.person_id) for r in confirmed]
    counts = {duty: dict(prior_counts[duty]) for duty in Duty}
    for r in confirmed:
        counts[r.duty][r.person_id] = counts[r.duty].get(r.person_id, 0) + 1

    all_days = list(iter_days(first, last))
    picks = {}
    for duty in Duty:
        open_days = [d for d in all_days if (d, duty) not in confirmed_slots]
        picks.update(
            roster.generate(
                open_days, {duty: pools[duty]}, availability,
                prior_counts=counts, prior_tail=tail,
            )
        )

    db.session.query(DutyAssignment).filter(
        DutyAssignment.date >= first,
        DutyAssignment.date <= last,
        DutyAssignment.state == DutyState.PROPOSED,
    ).delete()
    for (day, duty), person_id in picks.items():
        if person_id is None:
            continue  # blank day: no row — the page derives blanks (P4.5)
        db.session.add(
            DutyAssignment(
                date=day, duty=duty, person_id=person_id,
                state=DutyState.PROPOSED, created_by_id=actor.id,
            )
        )
    db.session.commit()
```

- [ ] **Step 4: Run tests → PASS. Step 5: Commit** (`P4.4: generate_month — PROPOSED rosters, CONFIRMED preserved`), push.

---

### Task 4: `roster_fingerprint` + `confirm_month` (A4)

- [ ] **Step 1: Write failing tests:**

```python
def test_confirm_flips_proposed_and_stamps(...):
    # generate -> confirm with the current fingerprint -> all rows CONFIRMED,
    # confirmed_by_id == actor.id, confirmed_at set.


def test_confirm_stale_fingerprint_aborts(...):
    # generate -> capture fingerprint -> manually change ONE row's person_id
    # (simulating PS B's edit) -> confirm with the stale print raises
    # RosterChanged; every row still PROPOSED, no confirmed_by stamped.


def test_double_confirm_second_loses_cleanly(...):
    # confirm once; a second confirm with the SAME (now stale) fingerprint
    # raises RosterChanged and does not re-stamp confirmed_at.


def test_confirm_does_not_touch_other_months(...):
    # PROPOSED rows in 2026-09 stay PROPOSED when 2026-08 is confirmed.
```

- [ ] **Step 2: Run to verify failure.** **Step 3: Implement:**

```python
def roster_fingerprint(month: str) -> str:
    """sha256 over the sorted (date, duty, person_id) CONTENT of the month's
    PROPOSED rows (A4). Content-based on purpose: an UPDATE-in-place regenerate
    and a single manual edit both change it; count+max(id) would not."""
    first, last = month_bounds(month)
    rows = _assignments_between(first, last, state=DutyState.PROPOSED)
    canon = "|".join(
        f"{r.date.isoformat()},{r.duty.value},{r.person_id}"
        for r in sorted(rows, key=lambda r: (r.date, r.duty.value, r.person_id))
    )
    return hashlib.sha256(canon.encode()).hexdigest()


def confirm_month(month: str, actor, fingerprint: str):
    """Confirm the month's PROPOSED rows — but only the roster the actor
    actually reviewed: the posted fingerprint is recomputed inside this
    transaction and a mismatch aborts (A4 — the plain WHERE state='PROPOSED'
    claim would confirm whatever PS B regenerated after PS A loaded the page).
    """
    first, last = month_bounds(month)
    if roster_fingerprint(month) != fingerprint:
        db.session.rollback()
        raise RosterChanged(
            "Roster changed since you loaded this page — re-review before confirming."
        )
    db.session.execute(
        update(DutyAssignment)
        .where(
            DutyAssignment.date >= first,
            DutyAssignment.date <= last,
            DutyAssignment.state == DutyState.PROPOSED,
        )
        .values(
            state=DutyState.CONFIRMED,
            confirmed_by_id=actor.id,
            confirmed_at=now_sgt(),
        )
    )
    db.session.commit()
```

- [ ] **Step 4: Run tests → PASS.**

- [ ] **Step 5: Full gates.**

Run each, in order:
1. `.venv/Scripts/python -m pytest -q` → all green, count > 435 (record it).
2. `rg "_fetch_rows" app tests` → nothing.
3. `rg -l "flask|app\.models|app\.extensions|app\.services" app/domain/` → nothing.
4. `.venv/Scripts/python -m flask routes` → identical to before this plan.
5. `git diff --stat main@{1}` (or against the pre-plan commit) → only the three files in this plan's Files list.

- [ ] **Step 6: Commit** (`P4.4: confirm_month behind content fingerprint`), push.

## Edge cases a weaker model would miss (all encoded above — re-verify at the end)

1. **In-camp statuses must NOT block availability.** `fetch_absence_rows` returns ALL statuses; `absences_between` filters in-camp ones, but you are not calling `absences_between` — filter `row.in_camp` yourself or an in-camp briefing wrongly blocks a duty.
2. **PM half-day DOES block** (decision d) even though the presence engine treats PM as present-for-parade. Availability and parade presence deliberately disagree here; do not "unify" them.
3. **Only TP events block; ARCTIC never does.** TECH_PLAN §permission-layers says "overnight/outstation TP event". Filter `Event.calendar == Calendar.TP`.
4. **Overnight ≠ long.** The rule is `end_dt.date() > start_dt.date()` — a 2300→0100 event blocks both days; a 0800→2300 same-day event never blocks.
5. **Per-duty generate() calls are safe only because pools are disjoint** (COS = Det Comd/Opr; CDOS = PC/P2IC/PS). Do not merge into one call with post-filtering — that leaves discarded picks in the generator's internal counts.
6. **Blank days have no row.** Do not write rows with `person_id=None` (column is NOT NULL); absence of a row IS the blank, and `roster.violations` flags it from the assignments map the page builds.
7. **Fingerprint must be content-based** — not `count+max(id)`: regenerate may reuse ids and a single manual edit must invalidate (A4's exact words).
8. **`prior_tail`/`prior_counts` are CONFIRMED-only** (a draft never constrains the future) and both empty on the first-ever month — no special-casing, the pure module already handles empty.
9. **Delete-then-insert of PROPOSED must filter `state == PROPOSED`** in the delete — a bare month-range delete would destroy CONFIRMED rows (contract-forbidden and data loss).
10. **`monthrange` handles Feb/leap years** — do not hand-roll month length.

## Acceptance criteria

- [ ] Full suite green; count > 435 (state the number).
- [ ] `rg "_fetch_rows" app tests` → empty.
- [ ] `flask routes` unchanged; one alembic head; goldens byte-identical.
- [ ] `regenerate preserves CONFIRMED` test passes (P4.4's Done line).
- [ ] Stale-fingerprint confirm raises `RosterChanged` with no partial state.
- [ ] Generation over a fixture month equals the pure module's output (P4.4's Done line).
- [ ] Diff touches only: `presence_service.py`, `duty_service.py`, `tests/test_duty_service.py`.
- [ ] Committed per task and pushed.
