# PLAN-duty-roster-page — P4.5 + P4.6: roster page, manual assignment, validated swaps

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Authority:** `docs/TECH_PLAN.md` tasks **P4.5** and **P4.6**, amended by addendum **A6** and contracts **C/P4.5, C/P4.6**. **Prerequisite: PLAN-duty-service.md (P4.4) is committed** — verify `app/services/duty_service.py` exists with `month_bounds`, `availability_for_month`, `generate_month`, `roster_fingerprint`, `confirm_month`, `RosterChanged` before starting (CR-1: open the file, don't assume).

**Goal:** The `/duty/roster` page: month grid with state badges, always-rendered pools panel, soft-violation highlights and blank flags, Generate/Confirm buttons (P4.5); manual assign/replace/clear with hard-block-vs-warn semantics, and validated CONFIRMED-only 1-for-1 swaps with an append-only log (P4.6).

**Architecture:** New `duty` blueprint mirroring the existing blueprint shape (`app/blueprints/parade/` is the reference). Views stay thin: a `duty_service.month_view(month)` helper assembles everything the page renders; `assign`/`clear`/`swap` service functions own the transactions and raise typed exceptions the routes translate to 4xx/flash.

## Global constraints

- Suite: `.venv/Scripts/python -m pytest -q`; count strictly greater than the P4.4 close-out count; goldens byte-identical; one alembic head (no migration here).
- `flask routes` after this plan gains **exactly** these six endpoints and nothing else:
  `GET /duty/roster` · `POST /duty/roster/generate` · `POST /duty/roster/confirm` · `POST /duty/roster/assign` · `POST /duty/roster/clear` · `POST /duty/roster/swap`
- Contract Forbidden: any other route; parade files; presence files; `approval_service`; auto-reassignment of anything. `DutySwapLog` gets **no update or delete path, ever**.
- Mutations `@require(policy.can_manage_roster)` (exists in `app/domain/policy.py:58` — all three PSs + admin). **Viewing: any logged-in user** (who's on duty is broadcast information).
- Domain purity grep clean; commit per task with `P4.5:` / `P4.6:` prefixes; push.
- **One deliberate contract addition (decision recorded here so the executor doesn't improvise):** a single nav line in `app/templates/base.html` — the P2.4/P3a.5 precedent (every page task added its nav link); an unreachable page fails the "independently runnable" phase rule. Touch no other line of base.html.

## Files

- Create: `app/blueprints/duty/__init__.py`, `app/blueprints/duty/routes.py`
- Create: `app/templates/duty/roster.html`
- Modify: `app/services/duty_service.py` (add `month_view`, `assign`, `clear`, `swap` + exceptions)
- Modify: `app/__init__.py` (register blueprint — two lines, alphabetical with the others)
- Modify: `app/templates/base.html` (one `<a>` line)
- Create: `tests/test_duty_roster_page.py`

## Interfaces produced (Plan 5 consumes `month_view`)

```python
MonthView = namedtuple("MonthView", "first last days rows by_slot pools violations fingerprint")
month_view(month: str) -> MonthView
class IneligibleAssignment(Exception): ...       # hard block -> 400
class NeedsAvailabilityConfirm(Exception): ...   # .reasons list -> warn, re-submit with confirm
class SwapError(Exception): ...                  # -> 400
assign(day, duty, person, *, actor, override_availability) -> DutyAssignment
clear(day, duty) -> bool
swap(assignment_a_id, assignment_b_id, *, actor, override_availability) -> DutySwapLog
```

---

### Task 1: `duty_service.month_view`

- [ ] **Step 1: Failing tests** (create `tests/test_duty_roster_page.py`):

```python
def test_month_view_blanks_derived_from_missing_rows(...):
    # 2 pool people, generate a month, delete one PROPOSED row directly ->
    # month_view reports that (day, duty) in violations.blanks.

def test_month_view_empty_pool_all_blank(...):
    # No CDOS-eligible people -> every (day, CDOS) is in violations.blanks and
    # pools[Duty.CDOS] == [].
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement** (append to `duty_service.py`; add `from collections import namedtuple` alongside existing imports):

```python
MonthView = namedtuple("MonthView", "first last days rows by_slot pools violations fingerprint")


def month_view(month: str) -> MonthView:
    """Everything the roster page renders, assembled once. `violations` is
    re-derived from the CURRENT rows on every call (the pure module's contract:
    re-flag after manual edits and swaps, not only after generation). Blanks
    are slots with NO row — the DB never stores a None assignment."""
    first, last = month_bounds(month)
    days = list(iter_days(first, last))
    rows = _assignments_between(first, last)
    by_slot = {(r.date, r.duty): r for r in rows}
    people = event_service.active_roster()
    pools = {duty: eligibility.pool(duty, people) for duty in Duty}
    assignments = {
        (d, duty): (by_slot[(d, duty)].person_id if (d, duty) in by_slot else None)
        for d in days
        for duty in Duty
    }
    _counts, prior_tail = _prior_month_inputs(first)
    return MonthView(
        first=first, last=last, days=days, rows=rows, by_slot=by_slot,
        pools=pools,
        violations=roster.violations(assignments, pools, prior_tail=prior_tail),
        fingerprint=roster_fingerprint(month),
    )
```

- [ ] **Step 4: Run → PASS. Step 5: Commit** `P4.5: month_view assembles the roster page data`, push.

---

### Task 2: Blueprint, page route, Generate/Confirm, template, nav

- [ ] **Step 1: Failing route tests** (append; copy the login/client idiom from `tests/test_morning_parade_page.py`):

```python
def test_roster_page_viewable_by_opr_without_buttons(...):
    # logged-in Opr GETs /duty/roster -> 200; page contains the grid and the
    # pools panel but NOT 'name="fingerprint"' and NOT url_for generate/confirm.

def test_roster_mutations_403_for_opr(...):
    # Opr POSTs generate/confirm/assign/clear/swap -> 403 each.

def test_empty_pool_warning_card(...):
    # No CDOS-eligible fixture -> page shows the empty-pool warning text.

def test_generate_then_confirm_flips_badges(...):
    # PS: POST generate -> page shows PROPOSED badges; POST confirm with the
    # rendered fingerprint -> CONFIRMED badges.

def test_confirm_stale_fingerprint_flashes_rereview(...):
    # PS A loads page (capture fingerprint), PS regenerates, confirm with the
    # old print -> redirect + flash containing "re-review", rows still PROPOSED.
```

- [ ] **Step 2: Run → FAIL (404s).** **Step 3: Implement.**

`app/blueprints/duty/__init__.py` (mirror `app/blueprints/parade/__init__.py` exactly, name `"duty"`, url_prefix `"/duty"`).

`app/blueprints/duty/routes.py`:

```python
from datetime import date

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.authz import require
from app.blueprints.duty import bp
from app.domain import policy
from app.domain.dates import today_sgt
from app.domain.types import Duty
from app.extensions import db
from app.models import DutySwapLog, Person
from app.services import duty_service


def _parse_month(raw: str) -> str:
    # Same posture as parade's _parse_day: a bad ?month= falls back to the
    # current month rather than 400ing — the page must always render something.
    try:
        duty_service.month_bounds(raw)
        return raw
    except (ValueError, AttributeError):
        return today_sgt().strftime("%Y-%m")


@bp.route("/roster")
@login_required
def roster():
    month = _parse_month(request.args.get("month", ""))
    view = duty_service.month_view(month)
    swap_log = (
        db.session.query(DutySwapLog).order_by(DutySwapLog.at.desc(), DutySwapLog.id.desc()).all()
    )
    return render_template(
        "duty/roster.html",
        month=month, view=view, Duty=Duty, swap_log=swap_log,
        roster_people=sorted(
            {p.id: p for duty in Duty for p in view.pools[duty]}.values(),
            key=lambda p: p.display_name,
        ),
    )


@bp.route("/roster/generate", methods=["POST"])
@require(policy.can_manage_roster)
def generate():
    month = _parse_month(request.form.get("month", ""))
    duty_service.generate_month(month, current_user)
    flash("Draft roster generated — review, then confirm.", "success")
    return redirect(url_for("duty.roster", month=month))


@bp.route("/roster/confirm", methods=["POST"])
@require(policy.can_manage_roster)
def confirm():
    month = _parse_month(request.form.get("month", ""))
    try:
        duty_service.confirm_month(month, current_user, request.form.get("fingerprint", ""))
    except duty_service.RosterChanged as exc:
        flash(str(exc), "error")
    else:
        flash("Month confirmed — parades and meals now read these duties.", "success")
    return redirect(url_for("duty.roster", month=month))
```

`app/templates/duty/roster.html` — extends base; sections in order (write real markup matching the classes used in `parade/away.html` / `leave/detail.html` — `card`, `table-wrap`, `list`, `badge`, `muted`, `flash`):

1. Page head: `Duty roster — {{ month }}` + prev/next month links (compute prev/next month strings in the route if easier; a `{{ month }}`-typed GET form is also fine).
2. **Pools panel — ALWAYS rendered, before the grid** (the plan's day-one reality check). Per duty: heading `{{ duty.label }} pool ({{ view.pools[duty]|length }})`, each member as `RANK NAME (Appointment)`; if `|length <= 2` render a warning card: `⚠ {{ duty.label }} pool is empty or tiny — the eligibility rule, not the app, may be the problem.`
3. Grid: table, rows = `view.days`, columns = COS/CDOS. Cell for `view.by_slot.get((d, duty))`: person name + `<span class="badge {{ 'approved' if row.state.value == 'CONFIRMED' else 'pending' }}">{{ row.state.value }}</span>`; missing row → `— <strong>blank</strong> ⚠`. Highlight adjacency: precompute in the route a set of `(person_id, date)` from `view.violations.adjacency` pairs and mark matching cells with `⚠ adjacent`.
4. Violations card: spread breaches (`{{ duty.label }}: min {{ lo }}, max {{ hi }}`) and adjacency pairs (person name + the two dates). Person names: build `{id: person}` from the pools in the route.
5. `{% if policy.can_manage_roster(current_user) %}` block: Generate form (POST, hidden `month`, CSRF, button "Generate (replaces draft)"), Confirm form (POST, hidden `month`, hidden `fingerprint` = `{{ view.fingerprint }}`, CSRF, button "Confirm month"). Manual-assignment and swap forms come in Task 3 — leave them out now.
6. Swap log table (visible to all viewers): who↔whom, dates, duty, actor, at; empty-state line.

Register in `app/__init__.py`: add `from app.blueprints.duty import bp as duty_bp` (alphabetical, after `calendar`) and `app.register_blueprint(duty_bp)` in the matching position.

Nav in `base.html`: after the Snapshots link (line 22) add exactly one line:
```html
        <a href="{{ url_for('duty.roster') }}">Duty roster</a>
```
CSRF hidden input pattern: `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` (same as every existing form).

- [ ] **Step 4: Run → PASS.** Also run `.venv/Scripts/python -m flask routes` and diff: exactly `duty.roster`, `duty.generate`, `duty.confirm` added so far.
- [ ] **Step 5: Commit** `P4.5: duty roster page — grid, pools panel, generate/confirm`, push.

---

### Task 3: Manual assign / clear (P4.6 part 1)

- [ ] **Step 1: Failing tests:**

```python
def test_assign_ineligible_is_400(...):
    # PS posts assign of a PC to COS -> response.status_code == 400; no row.

def test_assign_unavailable_requires_confirm(...):
    # Person on APPROVED leave that day: POST without confirm -> no row, flash
    # warning; POST again with confirm=1 -> row written, state PROPOSED.

def test_assign_replaces_confirmed_keeping_confirmed(...):
    # Existing CONFIRMED row; assign a different eligible person with confirm=1
    # -> same row id, new person_id, state still CONFIRMED, confirmed_by re-stamped.

def test_clear_removes_row(...):
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement.** Service (append to `duty_service.py`):

```python
class IneligibleAssignment(Exception):
    """Rule violation (a PC can never hold COS) — hard block, 4xx, never a warning."""


class NeedsAvailabilityConfirm(Exception):
    """Soft problems (decision d: the PS may assign over them with an explicit
    confirm). `reasons` is the user-facing list."""

    def __init__(self, reasons):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _availability_reasons(person, day, duty):
    """Soft-warning reasons for putting `person` on (day, duty): covering
    absence/overnight event, adjacency (incl. cross-month tail), spread breach."""
    month = day.strftime("%Y-%m")
    pools, availability, _confirmed = availability_for_month(month)
    reasons = []
    if not availability(person, day):
        reasons.append("covering absence, overnight TP event, or duty that day")
    first, last = month_bounds(day.replace(day=1).strftime("%Y-%m"))
    rows = _assignments_between(first, last)
    _counts, tail = _prior_month_inputs(first)
    held = {r.date for r in rows if r.person_id == person.id and r.date != day}
    held.update(d for d, _duty, pid in tail if pid == person.id)
    if any(roster.adjacent_duty_days(day, other) for other in held):
        reasons.append("adjacent duty day (incl. Fri→Mon)")
    counts = {p.id: 0 for p in pools[duty]}
    for r in rows:
        if r.duty is duty and r.person_id in counts and not (r.date == day):
            counts[r.person_id] += 1
    if person.id in counts:
        counts[person.id] += 1
        if counts and max(counts.values()) - min(counts.values()) > 1:
            reasons.append(f"would breach {duty.label} spread (max−min > 1)")
    return reasons


def assign(day, duty, person, *, actor, override_availability):
    """Assign/replace one (date, duty). Eligibility is LAW (hard block);
    availability/adjacency/spread are judgment (warn-then-confirm). Replacing a
    CONFIRMED row keeps it CONFIRMED with a fresh confirm stamp — manual replace
    is exactly how the PS resolves a post-approval clash; a new row on an empty
    slot is PROPOSED (it becomes real only when the month is confirmed)."""
    rule = eligibility.eligible_cos if duty is Duty.COS else eligibility.eligible_cdos
    if not (person.is_active and rule(person)):
        raise IneligibleAssignment(
            f"{person.display_name} can never hold {duty.label} — rank/appointment rule."
        )
    reasons = _availability_reasons(person, day, duty)
    if reasons and not override_availability:
        raise NeedsAvailabilityConfirm(reasons)
    row = (
        db.session.query(DutyAssignment)
        .filter(DutyAssignment.date == day, DutyAssignment.duty == duty)
        .first()
    )
    if row is None:
        row = DutyAssignment(
            date=day, duty=duty, person_id=person.id,
            state=DutyState.PROPOSED, created_by_id=actor.id,
        )
        db.session.add(row)
    else:
        row.person_id = person.id
        if row.state is DutyState.CONFIRMED:
            row.confirmed_by_id = actor.id
            row.confirmed_at = now_sgt()
    db.session.commit()
    return row


def clear(day, duty) -> bool:
    row = (
        db.session.query(DutyAssignment)
        .filter(DutyAssignment.date == day, DutyAssignment.duty == duty)
        .first()
    )
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True
```

Routes (append to `duty/routes.py`):

```python
@bp.route("/roster/assign", methods=["POST"])
@require(policy.can_manage_roster)
def assign():
    month = _parse_month(request.form.get("month", ""))
    try:
        day = date.fromisoformat(request.form.get("date", ""))
        duty = Duty(request.form.get("duty", ""))
        person = db.session.get(Person, int(request.form.get("person_id", "")))
    except (ValueError, TypeError):
        abort(400)
    if person is None:
        abort(400)
    try:
        duty_service.assign(
            day, duty, person, actor=current_user,
            override_availability=request.form.get("confirm") == "1",
        )
    except duty_service.IneligibleAssignment as exc:
        abort(400, description=str(exc))
    except duty_service.NeedsAvailabilityConfirm as exc:
        flash(f"Not assigned — {exc}. Tick “assign anyway” to override.", "error")
        return redirect(url_for("duty.roster", month=month))
    flash("Assigned.", "success")
    return redirect(url_for("duty.roster", month=month))


@bp.route("/roster/clear", methods=["POST"])
@require(policy.can_manage_roster)
def clear():
    month = _parse_month(request.form.get("month", ""))
    try:
        day = date.fromisoformat(request.form.get("date", ""))
        duty = Duty(request.form.get("duty", ""))
    except ValueError:
        abort(400)
    flash("Cleared." if duty_service.clear(day, duty) else "Nothing to clear.", "success")
    return redirect(url_for("duty.roster", month=month))
```

Template: add a "Manual assignment" card inside the `can_manage_roster` block — date input (`type="date"`), duty select (COS/CDO/S), person select over `roster_people`, checkbox `name="confirm" value="1"` labelled "assign anyway (override availability warning)", hidden `month`, CSRF, Assign button; plus a Clear form (date + duty + button).

- [ ] **Step 4: Run → PASS. Step 5: Commit** `P4.6: manual assign/clear — eligibility hard-blocked, availability warn-then-confirm`, push.

---

### Task 4: Validated swaps (P4.6 part 2, A6)

- [ ] **Step 1: Failing tests:**

```python
def test_swap_writes_one_log_row_and_swaps_people(...):
def test_swap_proposed_row_is_400(...):        # A6: CONFIRMED-only
def test_swap_different_duties_is_400(...):    # cannot occur via UI; pinned anyway
def test_swap_midway_failure_leaves_both_rows_unswapped(...):
    # monkeypatch db.session.commit to raise once; assert both person_ids
    # unchanged after rollback and no DutySwapLog row exists.
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement.** Service:

```python
class SwapError(Exception):
    """Structurally invalid swap — 4xx, user-facing message."""


def swap(assignment_a_id, assignment_b_id, *, actor, override_availability):
    """Validated 1-for-1 swap: both rows CONFIRMED (A6 — a PROPOSED draft is
    regenerate/manual-assign territory, and a logged swap of a draft would be
    semantically orphaned by the next regenerate), same duty (the disjoint
    pools guarantee it; a mismatch means hand-crafted input), both people
    re-validated for the other's date. Both rows + ONE log row, one commit."""
    a = db.session.get(DutyAssignment, assignment_a_id)
    b = db.session.get(DutyAssignment, assignment_b_id)
    if a is None or b is None or a.id == b.id:
        raise SwapError("Pick two existing, different assignments.")
    if a.state is not DutyState.CONFIRMED or b.state is not DutyState.CONFIRMED:
        raise SwapError("Swaps are for CONFIRMED duties — regenerate or manual-assign covers drafts.")
    if a.duty is not b.duty:
        raise SwapError("Swaps are same-duty only.")
    rule = eligibility.eligible_cos if a.duty is Duty.COS else eligibility.eligible_cdos
    for row in (a, b):
        if not (row.person.is_active and rule(row.person)):
            raise IneligibleAssignment(f"{row.person.display_name} can no longer hold {row.duty.label}.")
    reasons = _availability_reasons(a.person, b.date, a.duty) + _availability_reasons(
        b.person, a.date, b.duty
    )
    if reasons and not override_availability:
        raise NeedsAvailabilityConfirm(reasons)
    person_a_id, person_b_id = a.person_id, b.person_id
    a.person_id, b.person_id = person_b_id, person_a_id
    stamp = now_sgt()
    for row in (a, b):
        row.confirmed_by_id = actor.id
        row.confirmed_at = stamp
    log = DutySwapLog(
        person_a_id=person_a_id, person_b_id=person_b_id,
        date_a=a.date, date_b=b.date, duty=a.duty, actor_id=actor.id,
    )
    db.session.add(log)
    db.session.commit()
    return log
```

Caveat for `_availability_reasons` during a swap: it sees the pre-swap rows, so each person's *own* old date shows up as "held". Exclude the two swapped dates from `held` for the swap path by computing reasons AFTER the in-memory `person_id` flip but BEFORE commit — or simpler and correct: pass `day != other_swapped_date` — implement it by moving the two `_availability_reasons` calls to after the flip (the session is not yet committed; the query in `_availability_reasons` reads the flushed session state — call `db.session.flush()` after the flip, and `db.session.rollback()` in every raise path after the flip). Pin with a test: swapping two people who are each available on the other's date raises nothing spurious.

Route:

```python
@bp.route("/roster/swap", methods=["POST"])
@require(policy.can_manage_roster)
def swap():
    month = _parse_month(request.form.get("month", ""))
    try:
        a_id = int(request.form.get("assignment_a", ""))
        b_id = int(request.form.get("assignment_b", ""))
    except ValueError:
        abort(400)
    try:
        duty_service.swap(
            a_id, b_id, actor=current_user,
            override_availability=request.form.get("confirm") == "1",
        )
    except (duty_service.SwapError, duty_service.IneligibleAssignment) as exc:
        abort(400, description=str(exc))
    except duty_service.NeedsAvailabilityConfirm as exc:
        flash(f"Not swapped — {exc}. Tick “swap anyway” to override.", "error")
        return redirect(url_for("duty.roster", month=month))
    flash("Swapped — logged.", "success")
    return redirect(url_for("duty.roster", month=month))
```

Template: "Swap" card in the manager block — two selects over the month's CONFIRMED rows only (`{{ r.date }} — {{ r.duty.label }} — {{ r.person.display_name }}`, value `r.id`), the same override checkbox, hidden `month`, CSRF.

- [ ] **Step 4: Run tests → PASS.**
- [ ] **Step 5: Gates:** full suite (count up, record); `flask routes` diff shows exactly the six contracted endpoints; goldens byte-identical; domain purity grep clean; `git diff --stat` only the files in this plan's Files list.
- [ ] **Step 6: Commit** `P4.6: validated CONFIRMED-only swaps with append-only log`, push.

## Edge cases a weaker model would miss

1. **Blanks are the absence of a row.** The grid and `violations()` need an assignments map covering every `(day, duty)` with `None` filled in — iterating DB rows alone reports zero blanks forever.
2. **The fingerprint goes through the form.** GET renders `view.fingerprint` into a hidden field; confirm POSTs it back. Recomputing it at POST time and comparing to itself would always pass — that's the A4 TOCTOU verbatim.
3. **4xx means 4xx.** A redirect-with-flash is 302 and fails the "hard-blocked with 4xx" Done. Eligibility violations → `abort(400)`; availability warnings → flash + redirect (they're not errors, they're judgment).
4. **Replace-on-CONFIRMED stays CONFIRMED** (with a fresh stamp). Downgrading to PROPOSED would silently remove a real duty from tonight's roll call and meals.
5. **New row on an empty slot is PROPOSED**, not CONFIRMED — becoming the roster of record requires the explicit confirm step; a manual fill of a blank in an already-confirmed month must go through Confirm again (fingerprint covers only PROPOSED rows, so confirm picks up exactly the new drafts).
6. **A PROPOSED↔PROPOSED swap is 400, not a log row** (A6): the next regenerate deletes the rows and orphans the log entry.
7. **Same-duty is guaranteed by pool disjointness but validated anyway** — the check defends against hand-crafted POSTs, not the UI.
8. **Swap availability must ignore the two dates being vacated**, or every legitimate swap warns about "already on duty" — see the flush-then-check note in Task 4.
9. **The Opr test must assert BOTH invisibility and 403** — hiding the buttons without the `@require` decorator is IDOR-adjacent; the decorator without hiding is bad UX. Both.
10. **`_parse_month` never 400s the GET page** — same posture as parade's `_parse_day`.
11. **Swap-log list is read-only for everyone; no delete/edit route exists** — do not add a "remove wrong entry" affordance; swapping back is a second row.

## Acceptance criteria

- [ ] `flask routes` gains exactly the six contracted endpoints.
- [ ] Opr: sees grid + pools + swap log; no forms; all five POSTs → 403.
- [ ] Empty-pool fixture shows the warning card; violations and blanks render.
- [ ] Confirm flips badges; stale fingerprint → "re-review" flash, nothing confirmed.
- [ ] PC-as-COS assign → 400; leave-covered assign needs `confirm=1`; CONFIRMED replace keeps CONFIRMED.
- [ ] Swap writes exactly one log row; PROPOSED swap → 400; induced mid-swap failure leaves both rows unswapped.
- [ ] Full suite green, count > previous plan's; goldens byte-identical; committed per task and pushed.
