# PLAN-duty-flags-and-e2e — P4.9 + P4.10: post-approval clash flags, phase-4 E2E, rollout step

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Authority:** `docs/TECH_PLAN.md` tasks **P4.9** and **P4.10**, amended by addendum **A8, B1** and contracts **C/P4.9, C/P4.10**. **Prerequisites: all four earlier plans committed** (P4.4–P4.8; B3 puts P4.9 after P4.8). Verify `duty_service.month_view`, `duty_service.confirmed_on`, and `can_key_parade_today` all exist before starting.

**Goal:** Warn-only, derived-at-render clash surfaces on both sides of a leave-vs-duty conflict: the leave detail page shows the requester's CONFIRMED duties in the requested range (to requester, PC, and OC — fulfilling the core-transaction step-2 promise "duty assignments (Phase 4+)"); the roster page flags CONFIRMED holders who are absent; the roll-call page names an absent duty holder in chrome. Then the Phase-4 E2E walk and the ROLLOUT.md duty cutover step close the phase.

**Architecture:** Nothing is stored and nothing is blocked (contract: no `approval_service` change — warn-only means read-side only; the app never auto-reassigns; the PS resolves via manual replace or swap). The flag predicate is **presence-derived** (A8): a holder is flagged iff `presence.resolve(holder, night)` returns ABSENT from the shared fetch — an MC (StatusEntry) or a regular's direct absence flags exactly like leave; a leave-table-only join would miss the most common real conflict.

## Global constraints

- Suite green, count strictly up; goldens byte-identical; page==snapshot invariant green (phase gate 7).
- `flask routes` unchanged (no new endpoints).
- **B1 is a hard rule:** the new leave-detail panel is a NEW include file plus exactly ONE `{% include %}` line inserted after the "Conducts & presence" card; **touching any other line of `leave/detail.html` is out of contract** (the file has 8 cards and 127 lines; zero-payoff refactors are rejected).
- Phase gates at the end (D/7-9): page==snapshot invariant all three variants; `rg "policy\.can_key_parade" app/blueprints app/templates` empty; `git status`/`git diff --stat` reviewed against the union of all P4 Produces lists — any orphan file is reverted, not explained.
- Commit per task (`P4.9:` / `P4.10:` prefixes); push.

## Files

- Create: `app/templates/leave/_duty_panel.html`
- Modify: `app/templates/leave/detail.html` (ONE include line, after line 65's `</section>`)
- Modify: `app/blueprints/leave/routes.py` (`detail()` — add duty query to context)
- Modify: `app/services/duty_service.py` (`month_view` gains `absent_flags`; small helper `absence_state_for`)
- Modify: `app/templates/duty/roster.html` (flag badge in flagged cells)
- Modify: `app/blueprints/parade/routes.py` + `app/templates/parade/roll_call.html` (absent-holder chrome)
- Modify: `docs/ROLLOUT.md` (duty cutover section)
- Create: `tests/test_duty_flags.py`, `tests/test_e2e_phase4.py`

---

### Task 1: Leave-detail duty panel (P4.9, B1)

- [ ] **Step 1: Failing tests** (create `tests/test_duty_flags.py`; login idiom from `tests/test_leave_requests.py`):

```python
def test_leave_detail_shows_confirmed_duties_in_range(...):
    # Requester holds CONFIRMED COS on a date inside the request range.
    # Requester, their PC, and the OC each GET the detail page -> panel lists
    # the date + duty. A PROPOSED assignment does NOT appear.

def test_leave_detail_no_duties_message(...):
    # No assignments -> panel renders its empty-state line (panel is always
    # present, mirroring the Conducts card's posture).
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement.**

`app/blueprints/leave/routes.py`, in `detail()` (after the `away_rows` loop, before `can_act_pc`): add imports `DutyAssignment` (models) and `DutyState` (types), then:

```python
    duty_rows = (
        db.session.query(DutyAssignment)
        .filter(
            DutyAssignment.person_id == request_row.person_id,
            DutyAssignment.state == DutyState.CONFIRMED,
            DutyAssignment.date >= request_row.start_date,
            DutyAssignment.date <= request_row.end_date,
        )
        .order_by(DutyAssignment.date)
        .all()
    )
```

and pass `duty_rows=duty_rows` to `render_template`.

`app/templates/leave/_duty_panel.html` (new file, complete):

```html
<section class="card">
  <h2>Confirmed duties on these dates</h2>
  {% if duty_rows %}
  <ul class="toollist">
    {% for d in duty_rows %}
    <li><span class="muted">{{ d.date.strftime("%a %d %b") }}</span>
        <span>{{ d.duty.label }} — confirmed</span></li>
    {% endfor %}
  </ul>
  <p class="muted">Approving does not reassign the duty — the PS resolves it on the
     <a href="{{ url_for('duty.roster', month=duty_rows[0].date.strftime('%Y-%m')) }}">duty roster</a>
     (manual replace or swap).</p>
  {% else %}
  <p class="muted">No confirmed duties on these dates.</p>
  {% endif %}
</section>
```

`app/templates/leave/detail.html`: insert exactly one line after the "Conducts &amp; presence on these dates" card's closing `</section>` (line 65):

```html
{% include "leave/_duty_panel.html" %}
```

- [ ] **Step 4: Run → PASS. Step 5: Commit** `P4.9: leave detail duty panel (include-only per B1)`, push.

---

### Task 2: Roster-page absence flags + roll-call chrome (P4.9, A8)

- [ ] **Step 1: Failing tests:**

```python
def test_roster_flags_absent_confirmed_holder_mc(...):
    # CONFIRMED holder gets an MC StatusEntry covering the duty date ->
    # month_view(...).absent_flags contains the assignment id; page shows the
    # flag. THE A8 PIN: a StatusEntry (not leave!) must flag.

def test_roster_flags_direct_absence_and_leave_too(...):
def test_pm_half_day_does_not_flag(...):
    # PM off = present for the night documents -> not flagged (absent_for_day).

def test_cancelling_leave_clears_flag(...):
    # cancel_approved -> month_view no longer flags (derived, never stored).

def test_roll_call_chrome_names_absent_holder(...):
    # CONFIRMED COS dated D on MC covering D+1: GET /parade/roll-call?date=D+1
    # -> chrome contains holder name + "MC"; the <pre> text is unchanged.

def test_approval_not_blocked_by_confirmed_duty(...):
    # WARN-ONLY PIN: OC approves leave covering a CONFIRMED duty -> approval
    # succeeds, ledger debits once, assignment row untouched (same person).
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement.**

`duty_service.py` — flag derivation over the shared fetch (A8: flagged ⇔ resolve returns absent):

```python
def _absent_assignment_ids(rows, first, last):
    """Assignment ids whose CONFIRMED holder resolves ABSENT on the duty date,
    derived from the shared fetch (A8): an MC, a direct absence, and approved
    leave all flag the same way, because the predicate IS presence, not a
    leave-table join. Never stored — recomputed at render."""
    confirmed = [r for r in rows if r.state is DutyState.CONFIRMED]
    if not confirmed:
        return frozenset()
    leaves, directs, statuses = presence_service.fetch_absence_rows(first, last)
    by_person = defaultdict(lambda: ([], [], []))
    for row in leaves:
        by_person[row.person_id][0].append(row)
    for row in directs:
        by_person[row.person_id][1].append(row)
    for row in statuses:
        by_person[row.person_id][2].append(row)
    flagged = set()
    for r in confirmed:
        p_leaves, p_directs, p_statuses = by_person.get(r.person_id, ((), (), ()))
        resolution = presence.resolve(
            r.person, r.date,
            leaves=p_leaves, direct_absences=p_directs, statuses=p_statuses,
        )
        if resolution.state is presence.PresenceState.ABSENT:
            flagged.add(r.id)
    return frozenset(flagged)
```

(import `from app.domain import presence` alongside the existing domain imports). Extend `MonthView` with an `absent_flags` field: add `"absent_flags"` to the namedtuple fields and `absent_flags=_absent_assignment_ids(rows, first, last)` in `month_view` — **update the namedtuple definition and the constructor call together**; the suite catches a missed one.

`templates/duty/roster.html`: in the grid cell, after the state badge:

```html
{% if row.id in view.absent_flags %}
  <span class="badge rejected">⚠ holder absent</span>
{% endif %}
```

Roll-call chrome (`parade/routes.py`, `roll_call()`): the night's duty rows are `duty_service.confirmed_on(day - timedelta(days=1))` (already fetched for the missing-duty notice from P4.7 — reuse, don't refetch); an absent holder is derivable from `built.pairs` with **zero extra queries**:

```python
    night_rows = duty_service.confirmed_on(day - timedelta(days=1))
    holders = {row.person_id: row for row in night_rows}
    absent_holders = [
        {"row": holders[person.id], "person": person, "label": _row_label(resolution.row)}
        for person, resolution in built.pairs
        if person.id in holders and resolution.state is presence.PresenceState.ABSENT
    ]
```

(import `presence` from `app.domain`). Template, above the `<pre>`, next to the missing-duty notice:

```html
{% for a in absent_holders %}
  <p class="flash flash-error">CONFIRMED {{ a.row.duty.label }}
     {{ a.person.rank.value }} {{ a.person.display_name }} is absent
     ({{ a.label }}) tonight — resolve on the duty roster.</p>
{% endfor %}
```

- [ ] **Step 4: Run → PASS. Step 5: Commit** `P4.9: presence-derived duty absence flags — roster page and roll-call chrome`, push.

---

### Task 3: Phase-4 E2E walk + ROLLOUT.md (P4.10)

- [ ] **Step 1: Read `tests/test_e2e_phase3.py` and `docs/ROLLOUT.md` in full first** — the E2E file is the structural template (one test client walking the whole story with real POSTs), and ROLLOUT.md's existing cutover sections are the format to mirror.

- [ ] **Step 2: Write the walk** (`tests/test_e2e_phase4.py`) — one story, exactly P4.10's task text, in this order:

1. Seed: PS (CDOS-eligible: 2SG+), OC, an Opr COS pool (2+ people), one stay-out CDOS-eligible person, a month string.
2. PS logs in → POST `/duty/roster/generate` → GET page shows pools panel and PROPOSED badges.
3. Force a blank day (e.g. every COS candidate has APPROVED leave that day before generating) → page flags the blank.
4. Manual assign over a warning: assign a leave-covered person with `confirm=1` → row exists.
5. POST confirm with the page's fingerprint (parse it from the HTML: `name="fingerprint" value="..."`) → badges CONFIRMED.
6. Swap two CONFIRMED assignments → exactly one `DutySwapLog` row.
7. Requester submits leave covering a confirmed duty → PC endorses → OC GETs detail (duty panel visible) → OC approves → approval succeeded (warn-only), roster page now flags the holder, assignment row untouched.
8. Roll call for the night after a confirmed duty: stay-out holder in CURRENT STRENGTH; meals overnight counter counts him once.
9. COS selector: GET `/parade/cos-message` pre-fills the confirmed COS of that date.
10. Deposed COS: clear the assignment → that person's `/parade/statuses` GET → 403.

Each numbered step asserts on response HTML or DB state — no step is a bare status-code check where content proves more.

- [ ] **Step 3: Run → green.**

- [ ] **Step 4: ROLLOUT.md** — append a "Duty roster cutover" section mirroring the existing sections' structure: one month generated in parallel with the PS's manual roster; the three PSs eyeball the pools panel against reality (the 3SG-PS gap is expected — if the CDO/S pool is near-empty, the rule, not the app, is the problem); manual assigns/swaps exercised during the parallel month; hard cutover the following month, after which the app's CONFIRMED roster drives roll-call counts, meals, and COS keying rights.

- [ ] **Step 5: Phase gates (D/7-9) — run and paste all outputs:**
  1. Full suite: `.venv/Scripts/python -m pytest -q` → green, count recorded.
  2. Page==snapshot invariant test green for all three variants.
  3. `rg "policy\.can_key_parade" app/blueprints app/templates` → empty.
  4. `rg -l "flask|app\.models|app\.extensions|app\.services" app/domain/` → empty.
  5. `.venv/Scripts/python -m flask routes` → exactly the P4.5/P4.6 six beyond pre-P4; nothing else new.
  6. `git status` + `git diff --stat` against the pre-P4.4 commit, reviewed file-by-file against the five plans' Files lists — orphans reverted.
  7. WAL checkpoint before committing the DB if it changed: `.venv/Scripts/python -c "import sqlite3; sqlite3.connect('instance/delta.db').execute('PRAGMA wal_checkpoint(TRUNCATE)')"`

- [ ] **Step 6: Commit** `P4.10: Phase 4 E2E walk and duty cutover rollout step`, push.

## Edge cases a weaker model would miss

1. **The flag predicate is presence, not leave (A8).** The most common real conflict is a duty holder going on **MC** — a StatusEntry — or a regular's direct absence. Test the MC case FIRST; if your implementation joins only `leave_request`, that test catches it.
2. **PM off does not flag.** `presence.resolve` treats PM as present (partial) — a PM-off holder still does duty that night. Don't re-implement day-part logic; the engine already owns it.
3. **In-camp statuses never flag** — resolve puts them in `in_camp_rows`, state stays non-ABSENT. Passing ALL statuses to resolve (not pre-filtering) is correct; the engine sorts it out.
4. **Flags are derived at render, never stored** (contract: "storing flags" is Forbidden). Cancelling the leave clears the flag with zero writes — that's the test proving it's derived.
5. **B1's one-line rule is literal.** Any "while I'm here" tidy of detail.html's other 126 lines is a contract violation (H-6) — revert it.
6. **The duty panel shows for requester AND PC AND OC** — it sits outside the `can_act_*` blocks. The viewer gate is the route's existing `_may_view`; add nothing.
7. **Roll-call chrome derives from `built.pairs`** — the resolutions are already computed with the right duty_day; re-resolving in the route with a fresh fetch risks disagreeing with the document below it.
8. **The E2E fingerprint must be scraped from the rendered page**, not recomputed via the service — the walk proves the FORM carries it (A4's actual mechanism).
9. **The warn-only test must assert three things**: approval succeeded, ledger debited exactly once, and the assignment still names the same person (nothing auto-reassigned).
10. **`_row_label`** (parade routes helper) already formats MC/leave labels — reuse it for the chrome; a hand-rolled label diverges from every other surface.
11. **ROLLOUT.md gets a section, not a rewrite** — append, mirroring the existing sections' voice and structure.

## Acceptance criteria

- [ ] Approving leave over a confirmed duty: OC saw the panel pre-approval; roster flags post-approval; approval was NOT blocked; nothing reassigned (P4.9's Done line).
- [ ] MC flags; direct absence flags; PM does not; cancel clears.
- [ ] Roll-call chrome names the absent holder; `<pre>` text and snapshots unchanged.
- [ ] E2E walk green covering all ten story beats; ROLLOUT.md gains the duty cutover step.
- [ ] All phase gates (D/1-9) pass with outputs pasted; count > previous plan's.
- [ ] `leave/detail.html` diff is exactly one added line; committed per task and pushed.
