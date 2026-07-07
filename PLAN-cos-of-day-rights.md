# PLAN-cos-of-day-rights — P4.8: rotating COS keying rights + COS autofill

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Authority:** `docs/TECH_PLAN.md` task **P4.8**, amended by addendum **A5** and contract **C/P4.8**. **Prerequisites: PLAN-duty-service (P4.4) AND PLAN-duty-feeds-documents (P4.7) committed** (addendum B3 strict sequence P4.4 → P4.7 → P4.8 — this plan edits `parade/routes.py`, which P4.7 also touched). Verify both before starting.

**Goal:** The CONFIRMED COS of today-or-tomorrow gains parade keying rights (statuses, quick-add, finalize) and is pre-selected in the COS-message greeting; the rights disappear when the assignment does. `policy.can_edit_ro` + `duty_service.cdos_of_day` land now, tested but unrouted, as P5's consumer.

**Architecture:** `domain/policy.py` stays pure — the duty fact is **passed in** as a keyword-only, no-default parameter (A5: a defaulted parameter lets any of the 14 call sites a sub-agent misses degrade *silently* to fallback-only rights; keyword-only-no-default makes a stale caller TypeError in the suite). The DB-aware wrapper `duty_service.can_key_parade_today` is what routes and templates actually call; templates switch in one place via the `inject_policy` context processor (`app/__init__.py:48`).

## Global constraints

- Suite green, count strictly up; goldens byte-identical; `flask routes` unchanged; one alembic head.
- **Purity gate (this is THE task that tempts a DB import into policy.py):** `rg -l "flask|app\.models|app\.extensions|app\.services" app/domain/` → nothing.
- **Phase gate 8, permanent from now on:** `rg "policy\.can_key_parade" app/blueprints app/templates` → nothing.
- Contract Forbidden: caching machinery ("one duty query per page render — accepted at 40 users; do not invent caching" — A5's exact words); per-date rights scoping (the two-day window decides WHO can key, not WHICH dates).
- Commit per task (`P4.8:` prefix); push.

## Files

- Modify: `app/domain/policy.py` (lines 72-74 `can_key_parade`; append `can_edit_ro`)
- Modify: `app/services/duty_service.py` (add `can_key_parade_today`, `cos_of_day`, `cdos_of_day`)
- Modify: `app/blueprints/parade/routes.py` (10 call sites + `_validate_cos_person`)
- Modify: `app/__init__.py` (context processor exposes the wrapper)
- Modify: `app/templates/base.html:23`, `app/templates/parade/morning.html:37`, `app/templates/parade/roll_call.html:37`, `app/templates/parade/cos_message.html:53` (one token each)
- Modify/Create: `tests/test_policy.py` (amend existing can_key_parade tests), `tests/test_duty_rights.py` (new)

## The 14 call sites (enumerated — CR-4 coupling scan, verified by grep on 2026-07-07)

Routes (`app/blueprints/parade/routes.py`): line 150 (inline `if policy.can_key_parade(current_user)`), decorators at lines 170, 195, 218, 259, 295, 338, 352, 375, 403. Templates: `base.html:23`, `morning.html:37`, `roll_call.html:37`, `cos_message.html:53`. **Re-run the grep yourself before editing** — line numbers shift if P4.7 touched the file:
`rg -n "policy\.can_key_parade" app`

---

### Task 1: Pure predicates — keyword-only, no default

- [ ] **Step 1: Failing tests.** In `tests/test_policy.py` (read it first; amend the existing `can_key_parade` tests) and new assertions:

```python
def test_can_key_parade_requires_duty_fact():
    # A5 pin: positional or missing -> TypeError, never a silent default.
    with pytest.raises(TypeError):
        policy.can_key_parade(ps_person)
    with pytest.raises(TypeError):
        policy.can_key_parade(ps_person, True)

def test_can_key_parade_matrix():
    # (PS, False) True; (S3, False) True; (admin, False) True;
    # (Opr, False) False; (Opr, True) True — the duty fact grants, never revokes.

def test_can_edit_ro():
    # (Opr, is_cdos_of_day=True) True; (Opr, False) False;
    # (any command-team appointment, False) True — A9's fallback.
    # Keyword-only pin: policy.can_edit_ro(opr, True) raises TypeError.
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement** in `app/domain/policy.py` (NO new imports — purity):

```python
def can_key_parade(person, *, is_cos_of_day) -> bool:
    # Keyword-only, NO default (addendum A5): a stale caller that forgets the
    # duty fact TypeErrors in the suite instead of silently degrading to
    # fallback-only rights. The DB-aware fact comes from
    # duty_service.can_key_parade_today — policy.py never queries.
    return (
        is_cos_of_day
        or person.appointment is Appointment.PS
        or person.company_role is CompanyRole.S3
        or is_admin(person)
    )


def can_edit_ro(person, *, is_cdos_of_day) -> bool:
    # P5's consumer, landed unrouted (P4.8): the rotating CDO/S edits the RO;
    # command team is the fallback (addendum A9).
    return is_cdos_of_day or is_command_team(person)
```

- [ ] **Step 4: Run the policy tests → PASS.** The FULL suite now FAILS loudly at every stale call site — that is A5 working; **do not commit until Task 2 restores green.** (Deviation from commit-per-task: Tasks 1+2 are one atomic change; a red commit would break the always-green invariant.)

---

### Task 2: DB-aware wrapper + all 14 call sites

- [ ] **Step 1: Failing tests** (create `tests/test_duty_rights.py`):

```python
def test_confirmed_cos_today_can_key(...):
    # Opr with CONFIRMED COS dated today_sgt(): can_key_parade_today -> True;
    # via test client he can GET /parade/statuses (200) and POST finalize.

def test_tomorrows_cos_can_key_today(...):
    # CONFIRMED COS dated today+1 -> True (compiles day-D's message on D−1).

def test_deposed_or_expired_cos_loses_rights(...):
    # Assignment dated today-1 -> False -> statuses GET is 403.
    # Assignment deleted (deposed) -> 403.

def test_proposed_cos_grants_nothing(...):
    # PROPOSED assignment for today -> 403 (drafts grant no rights).

def test_cos_selector_prefills_confirmed_cos(...):
    # CONFIRMED COS for tomorrow; another PS GETs /parade/cos-message ->
    # greeting names the confirmed COS, not current_user; explicit ?cos=
    # still overrides.
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement.**

`duty_service.py` (append; `timedelta`, `today_sgt` and `policy` imports — add `from app.domain import policy` and extend the dates import):

```python
def _confirmed_holder(day, duty):
    row = (
        db.session.query(DutyAssignment)
        .filter(
            DutyAssignment.date == day,
            DutyAssignment.duty == duty,
            DutyAssignment.state == DutyState.CONFIRMED,
        )
        .first()
    )
    return row.person if row is not None else None


def cos_of_day(day):
    """CONFIRMED COS holder for `day`, or None (autofills the greeting)."""
    return _confirmed_holder(day, Duty.COS)


def cdos_of_day(day):
    """CONFIRMED CDO/S holder for `day`, or None — P5's RO-rights input."""
    return _confirmed_holder(day, Duty.CDOS)


def can_key_parade_today(person) -> bool:
    """The DB-aware wrapper every route and template calls: PS/S3/admin
    fallback OR CONFIRMED COS for today or tomorrow (tomorrow's COS compiles
    day-D's message on the evening of D−1 — assumption 4 makes the two-day
    window the honest one). One duty query per page render — accepted at 40
    users (A5); do not add caching. Rights are date-independent: the window
    decides WHO can key, not WHICH dates they may key."""
    today = today_sgt()
    is_cos = (
        db.session.query(DutyAssignment.id)
        .filter(
            DutyAssignment.person_id == person.id,
            DutyAssignment.duty == Duty.COS,
            DutyAssignment.state == DutyState.CONFIRMED,
            DutyAssignment.date.in_((today, today + timedelta(days=1))),
        )
        .first()
        is not None
    )
    return policy.can_key_parade(person, is_cos_of_day=is_cos)
```

`app/blueprints/parade/routes.py`: add `duty_service` to the services import; replace all 10 sites — `@require(policy.can_key_parade)` → `@require(duty_service.can_key_parade_today)`; line 150's inline check → `if duty_service.can_key_parade_today(current_user):`.

`app/__init__.py` `inject_policy` (the one place all 4 templates switch through):

```python
    @app.context_processor
    def inject_policy():
        # Templates condition nav/content on the same predicates routes enforce.
        # can_key_parade is duty-aware (P4.8): templates get the DB-aware
        # wrapper, so the pure policy predicate (keyword-only) is never called
        # bare from Jinja.
        from app.services import duty_service

        return {
            "policy": policy,
            "routing": routing,
            "BalanceKind": BalanceKind,
            "can_key_parade_today": duty_service.can_key_parade_today,
        }
```

Templates — one token per file: `policy.can_key_parade(current_user)` → `can_key_parade_today(current_user)` at `base.html:23`, `morning.html:37`, `roll_call.html:37`, `cos_message.html:53`.

`_validate_cos_person` (routes.py:65) — new fallback order CONFIRMED-COS-of-page-date → current_user; signature gains `day` (positional, both callers updated: `cos_message()` and `cos_message_finalize()`):

```python
def _validate_cos_person(raw, day, roster=None):
    """Resolve a `cos=` id (query or posted) to an active Person; fallback
    order is CONFIRMED COS of the page date, then current_user (P4.8 closes
    the P3 hook this function's comment has named since P3b.3). Invalid or
    inactive ids never 400 — a keying mistake costs one reload."""
    roster = roster if roster is not None else event_service.active_roster()
    try:
        cos_id = int(raw)
    except (TypeError, ValueError):
        cos_id = None
    if cos_id is not None:
        person = next((p for p in roster if p.id == cos_id), None)
        if person is not None:
            return person
    return duty_service.cos_of_day(day) or current_user
```

Callers: `cos_message()` → `_validate_cos_person(request.args.get("cos", ""), day, roster)`; `cos_message_finalize()` → `_validate_cos_person(request.form.get("cos", ""), day)`.

- [ ] **Step 4: FULL suite → green** (this is where every stale caller surfaces; fix by switching the caller to the wrapper, NEVER by adding a default to the policy predicate).
- [ ] **Step 5: Gates:**
  1. `rg "policy\.can_key_parade" app/blueprints app/templates` → **nothing** (phase gate 8, forever).
  2. `rg -l "flask|app\.models|app\.extensions|app\.services" app/domain/` → nothing.
  3. `flask routes` unchanged; goldens byte-identical; count up (record).
- [ ] **Step 6: Commit** `P4.8: COS-of-day keying rights via duty-aware wrapper; can_edit_ro landed unrouted`, push.

## Edge cases a weaker model would miss

1. **No default on `is_cos_of_day` — this is the task's core discipline.** The moment a `=False` default appears "to make tests pass", every missed call site silently loses the feature with no error (A5's exact failure mode). Fix stale callers, never the signature.
2. **policy.py must not gain a DB import.** The purity gate exists because this task is exactly the one that tempts it. The duty query lives in `duty_service`; policy takes a bool.
3. **Two-day window is today AND tomorrow, CONFIRMED and COS only.** Yesterday's COS gets nothing; PROPOSED gets nothing; a CONFIRMED **CDOS** gets no parade-keying rights (CDO/S edits the RO — different duty, different surface, P5).
4. **`current_user` is a proxy, not a Person** — `duty_service.can_key_parade_today(person)` receives the proxy from `@require`; `person.id`/`.appointment` resolve fine through it. Don't add `._get_current_object()` gymnastics; the existing predicates already take the proxy.
5. **The `@require` decorator calls `predicate(current_user)` with one positional arg** (`app/authz.py:17`) — which is exactly why the wrapper (not the two-arg pure predicate) is what gets decorated.
6. **`_validate_cos_person`'s precedence is: explicit valid `?cos=` FIRST, then confirmed COS, then current_user.** Auto-fill must not override a deliberate hand-selection (the app proposes, a human decides) — and the finalize route re-runs the same resolution so a tampered hidden field still can't name someone off-roster.
7. **`cdos_of_day`/`can_edit_ro` stay unrouted.** Wiring them anywhere is out of contract (P5 does that); they ship with unit tests only.
8. **The nav check runs on every page render for every user** (base.html) — the wrapper adds one indexed query (`ix_duty_date`). Accepted; do not cache, do not conditionally skip.
9. **`today_sgt()`, never `date.today()`** — a user abroad on OL must not shift the rights window (existing `dates.py` rule).
10. **Tests that previously called `policy.can_key_parade(x)` directly** (grep `tests/` too) must migrate to `is_cos_of_day=False` explicitly — that's the honest spelling of "no duty today".

## Acceptance criteria

- [ ] Opr with CONFIRMED COS today or tomorrow: keys statuses, uses quick-add, finalizes; 403 on all of it the day after the assignment passes (P4.8's Done line).
- [ ] COS-message selector pre-selects the confirmed COS; `?cos=` hand-override still wins.
- [ ] `policy.can_key_parade(person)` and `(person, True)` raise TypeError (pinned).
- [ ] `can_edit_ro` unit-tested, unrouted; `cdos_of_day` returns holder/None.
- [ ] `rg "policy\.can_key_parade" app/blueprints app/templates` → empty, and stays empty forever.
- [ ] Purity grep clean; suite green with count up; goldens byte-identical; routes unchanged; committed and pushed.
