# PLAN-duty-feeds-documents — P4.7: CONFIRMED duties feed presence, parades, and meals

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Authority:** `docs/TECH_PLAN.md` task **P4.7**, amended by addendum **A1, A2, A3, A7** and contract **C/P4.7**. **Prerequisite: PLAN-duty-service.md (P4.4) committed.** Addendum B3: this plan and PLAN-duty-roster-page both edit `duty_service.py` — never run them in parallel; either order after P4.4 is fine, but run them sequentially.

**Goal:** CONFIRMED duty assignments reach every parade document and the meal counters through exactly one function (`parade_service.build_doc`), with the roll-call labeling convention (roll call labeled D covers night D−1→D, so it reads the duty of **D−1**; morning and COS message read the duty of **D**) owned in one place.

**Architecture:** The hooks have waited since P3a.2: `presence.resolve` already has a `duties=` parameter and a `PresenceState.DUTY` branch (`app/domain/presence.py:128,141`), and `parade.categorize` already buckets DUTY into current strength (`app/domain/parade.py:252`). Decision (j)'s meals rewrite means meals consume `build_doc` outputs (`app/services/meal_service.py:17-18`), so a duty convention added inside `build_doc` reaches parades, snapshots, AND meals with zero meals-code changes. This task is: one keyword-only parameter on `presence_inputs`, one offset decision inside `build_doc`, page-chrome notices, and pin tests.

**Contract (C/P4.7) — Forbidden:** any change to `presence.resolve`, `covers`, or `parade.categorize`; **any change to golden bytes**. The engine and the pure parade module are DONE — if you think they need a change, STOP and ask (fable-behavior H-2).

## Global constraints

- Suite green, count strictly up from the previous plan's; **all parade goldens byte-identical** (duty-free fixture days must render exactly as before — the strongest gate in this plan).
- The page==snapshot invariant test (from P3b.6) must keep passing for all three variants.
- `flask routes` unchanged (no new endpoints — notices ride on existing pages).
- Domain purity grep clean; one alembic head; commit per task (`P4.7:` prefix); push.

## Files

- Modify: `app/services/presence_service.py` (`presence_inputs` gains `*, duty_day=None`; ~lines 187-222)
- Modify: `app/services/parade_service.py` (`build_doc` passes the offset; ~line 32)
- Modify: `app/services/duty_service.py` (add `confirmed_on(day)` — 6 lines)
- Modify: `app/blueprints/parade/routes.py` (roll-call route: missing-duty notice), `app/templates/parade/roll_call.html` (chrome outside `<pre>`)
- Modify: `app/blueprints/meals/routes.py` + its template (same notice for night D→D+1)
- Create: `tests/test_duty_presence.py`

## Interfaces produced

```python
presence_service.presence_inputs(day, *, duty_day=None)  # keyword-only, default None = fetch duty of `day`
duty_service.confirmed_on(day) -> list[DutyAssignment]   # CONFIRMED rows dated `day`
# build_doc: unchanged signature; roll_call now internally passes duty_day=day-1
```

---

### Task 1: `presence_inputs(day, *, duty_day=None)` + the A3 adapter

- [ ] **Step 1: Failing tests** (create `tests/test_duty_presence.py`; fixture idiom from `tests/test_presence_service_v2.py`):

```python
def test_confirmed_duty_reaches_resolution(...):
    # Stay-out NSF Opr (eligible COS), CONFIRMED COS dated 2026-08-10.
    # presence_inputs(date(2026,8,10)) -> his resolution.state is DUTY
    # (duty overrides stay-out).

def test_duty_day_offset_fetches_other_date(...):
    # Same fixture. presence_inputs(date(2026,8,11), duty_day=date(2026,8,10))
    # -> DUTY on the 11th (the adapter row covers the RESOLUTION day — this is
    # addendum A3's exact trap: keying the adapter to the assignment's own
    # .date makes covers() always False whenever duty_day != day).

def test_proposed_changes_nothing(...):
    # Same but state PROPOSED -> STAY_OUT (drafts never move real counts).

def test_leave_beats_duty(...):
    # CONFIRMED duty holder with APPROVED FULL leave covering the day ->
    # resolution.state is ABSENT (precedence: leave > duty), never DUTY.
```

- [ ] **Step 2: Run → FAIL** (`TypeError: unexpected keyword` / wrong states).

- [ ] **Step 3: Implement.** In `presence_service.py`, add imports `from collections import namedtuple` piece (already has defaultdict; add what's missing), `DutyAssignment` to the models import, `DutyState` to the types import. Then:

```python
_DutyCover = namedtuple("DutyCover", "start_date end_date")


def presence_inputs(day, *, duty_day=None):
    """... (keep the existing docstring, then append:)

    `duty_day` (keyword-only): which date's CONFIRMED duty_assignment rows feed
    the DUTY state — the fetch key ONLY. The adapter row handed to the engine
    covers start=end=`day` (the resolution day), because `covers()` compares
    against the day being resolved (A3): roll call labeled D covers the night
    D−1→D, so its build passes duty_day=D−1 but the duty must count ON day D.
    Default None means the duty of `day` itself (morning parade, COS message).
    """
    ...existing body...
    duty_rows = (
        db.session.query(DutyAssignment)
        .filter(
            DutyAssignment.date == (duty_day if duty_day is not None else day),
            DutyAssignment.state == DutyState.CONFIRMED,
        )
        .all()
    )
    by_duty = defaultdict(list)
    for row in duty_rows:
        by_duty[row.person_id].append(_DutyCover(start_date=day, end_date=day))
```

and pass `duties=by_duty.get(person.id, ())` into the existing `presence.resolve(...)` call.

- [ ] **Step 4: Run new tests → PASS. Run FULL suite** — every golden must still pass (duty-free days: `duties=()` → behavior identical).
- [ ] **Step 5: Commit** `P4.7: presence_inputs takes duty_day — CONFIRMED duties enter the derivation`, push.

---

### Task 2: `build_doc` owns the offset convention (A2)

- [ ] **Step 1: Failing tests:**

```python
def test_roll_call_reads_duty_of_previous_day(...):
    # CONFIRMED COS dated D. build_doc(D+1, ParadeVariant.ROLL_CALL): the
    # stay-out holder appears in CURRENT STRENGTH (counted present that night).
    # build_doc(D, ParadeVariant.ROLL_CALL): he does NOT (his duty is the night
    # D→D+1, not D−1→D).

def test_morning_and_cos_read_duty_of_own_day(...):
    # build_doc(D, MORNING): holder in CURRENT STRENGTH.
    # build_doc(D, COS_MESSAGE, cos_person=...): holder OMITTED (DUTY is
    # omitted like PRESENT — this document requests statuses).

def test_meals_counters_follow_the_same_pipe(...):
    # A1's two pins, through meal_service.compute_for:
    # (a) stay-out NSF CDOS with CONFIRMED duty dated D -> overnight(D) counts
    #     him EXACTLY once (roll_call(D+1) reads duty of D);
    # (b) the same holder with APPROVED leave covering D and D+1 -> overnight(D)
    #     does NOT count him (leave > duty; nobody re-adds him downstream).
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement.** In `parade_service.build_doc`, replace line 32 (`pairs = presence_service.presence_inputs(day)`) with:

```python
    # The duty_day convention lives HERE and nowhere else (A2): the roll call
    # labeled `day` covers the night day−1 → day, so it reads the duty of
    # day−1; morning parade and the COS message read the duty of their own day.
    duty_day = day - timedelta(days=1) if variant is ParadeVariant.ROLL_CALL else None
    pairs = presence_service.presence_inputs(day, duty_day=duty_day)
```

(add `from datetime import timedelta` to the imports). **No meals change is needed** — `meal_service.compute_for` already builds morning(D) and roll_call(D+1) through `build_doc` (decision (j) landed A1's posture: the meals duty term is permanently presence-derived). Verify `app/domain/meals.py` contains no stale "P4 hook" comment promising a duty term (it currently doesn't — decision (j) rewrote it); if you find one anywhere, rewrite it to state the A1 rule.

- [ ] **Step 4: Run → PASS; full suite; goldens; page==snapshot invariant still green.**
- [ ] **Step 5: Commit** `P4.7: build_doc owns the roll-call duty_day offset; meals inherit via the one pipeline`, push.

---

### Task 3: "No confirmed duty for this night" page chrome (A7)

- [ ] **Step 1: Failing tests:**

```python
def test_roll_call_page_notice_when_no_confirmed_duty(...):
    # No assignments: GET /parade/roll-call -> page contains the notice text;
    # the <pre> document text is byte-identical to before (chrome only).
    # With a CONFIRMED COS for day-1 but no CDOS -> notice names CDO/S only.

def test_meals_page_notice(...):
    # GET /meals?date=D with no CONFIRMED rows dated D -> notice present.

def test_snapshot_text_never_contains_notice(...):
    # Finalize roll call with no confirmed duty: stored rendered_text does NOT
    # contain the notice string (chrome lives outside the document).
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement.**

`duty_service.confirmed_on`:

```python
def confirmed_on(day):
    """CONFIRMED assignments dated `day` — the consumers' notice helper (A7):
    when a night has no confirmed duty (rollout ramp, month boundary), pages
    say so in chrome; the document text never changes."""
    return (
        db.session.query(DutyAssignment)
        .filter(DutyAssignment.date == day, DutyAssignment.state == DutyState.CONFIRMED)
        .order_by(DutyAssignment.duty)
        .all()
    )
```

Roll-call route (`parade/routes.py`, in `roll_call()` before `render_template`): the night covered is `day−1 → day`, so:

```python
    night_duties = {row.duty for row in duty_service.confirmed_on(day - timedelta(days=1))}
    missing_duties = [duty for duty in Duty if duty not in night_duties]
```

pass `missing_duties=missing_duties` to the template; import `Duty` into the existing `app.domain.types` import block and `duty_service` into the services import. Template (`roll_call.html`), **above the `<pre>` block, never inside it**:

```html
{% if missing_duties %}
  <p class="flash flash-error">No confirmed duty for this night:
    {% for d in missing_duties %}{{ d.label }}{% if not loop.last %}, {% endif %}{% endfor %}
    — this document counts nobody as on duty.</p>
{% endif %}
```

Meals route: read `app/blueprints/meals/routes.py` first (whole file — CR: read whole units). The day-D counters cover night D→D+1, so compute `missing_duties` from `duty_service.confirmed_on(day)` and render the same chrome in the meals template above the counters.

- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Full gates:** suite green (count up, record); goldens byte-identical; `flask routes` unchanged; purity grep clean; `git diff --stat` only this plan's files.
- [ ] **Step 6: Commit** `P4.7: missing-duty page chrome on roll call and meals`, push.

## Edge cases a weaker model would miss

1. **A3 is the whole task.** The adapter row must carry `start_date = end_date = the resolution day`; the assignment's `.date` is only the fetch key. Keyed the "natural" way, duty silently never appears at roll call — the one place it matters — and every test that only checks morning parade stays green.
2. **The offset belongs to `build_doc`, not the routes.** All six parade route sites and the meals service already flow through `build_doc` (P3b.6/A2). Adding `duty_day=` at any route is a second convention owner — the drift A2 exists to prevent.
3. **Meals need zero code.** Decision (j) made the meal counters read `build_doc` docs. Resist "adding duty to breakfast" — re-adding duty people by hand re-introduces A1's bug (counting a duty holder who is on approved leave, because leave outranks duty in presence and they were deliberately excluded).
4. **PROPOSED must change nothing** — filter `state == CONFIRMED` in the fetch. A draft moving food orders or parade counts is the exact failure DutyState exists to prevent.
5. **COS message omits DUTY people** by design (`parade.py:434` — it requests statuses; clean people aren't listed). Don't "fix" the holder's absence from Message 1.
6. **Morning STAY_OUT already lands in current strength** (`parade.py:252`), so a stay-out holder's morning line doesn't change when duty wins — assert roll call, where the behavior actually differs.
7. **The notice is chrome, not document.** It must never enter `built.text` or a snapshot — the P3 goldens and the page==snapshot invariant both enforce this; test it explicitly anyway (snapshot text must not contain the notice string).
8. **Roll call's night is D−1→D but meals' night for day D is D→D+1** — the two notices read different duty dates. Copying the roll-call expression into the meals route unchanged is wrong by one day.
9. **`duty_day` is keyword-only.** A positional call must TypeError (same A5 posture as P4.8) — the default `None` is correct here because "duty of the resolved day" is right for every caller except roll call, which build_doc handles.

## Acceptance criteria

- [ ] Stay-out holder with CONFIRMED duty dated D: in roll_call(D+1) CURRENT STRENGTH; absent from roll_call(D); in morning(D) current strength; omitted from cos(D).
- [ ] Duty holder on approved leave: ABSENT everywhere; overnight meal counter excludes him (A1 pin).
- [ ] Stay-out CDOS: overnight counter counts him exactly once (A1 pin).
- [ ] PROPOSED rows change no document and no counter.
- [ ] All parade goldens byte-identical; page==snapshot invariant green; snapshot text never contains the notice.
- [ ] Suite green, count up; routes unchanged; committed per task and pushed.
