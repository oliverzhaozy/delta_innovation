# Delta Innovation — Technical Implementation Plan

> Approved 2026-07-05. Build has not started; work begins at task P0.1 on explicit go-ahead.

## Context

Delta (a ~36-person Singapore military company) runs manpower admin on TimeTree plus hand-assembled text documents. The core failure: leave approval, calendar plotting, and balance deduction are three separate manual steps, so S3's OFF/OIL tracking drifts. This app **replaces TimeTree as the single source of truth**: final approval of a leave request is the one action that both plots the absence and decrements the balance. Parade states, duty rosters, RO, manning, and meal counts are all generated from the same data; anything manpower-critical is decision-support — the app proposes, a human confirms. Stack fixed: Python + Flask + SQLite + server-rendered Jinja. ~40 users, internet-reachable, deliberately baseline security. Partly a learning project — significant decisions carry a one-line "why".

This plan was pressure-tested by a 5-critic review panel (ambiguity, edge cases, design red-team, MVP scope, security); its confirmed findings are folded in below.

## Decisions confirmed by the owner

- **(a) Balances:** OFF and OIL only. LL/OL are recorded as absences (parade, clash checks, manning) but hold no in-app balance.
- **(b) Routing:** only **PS and below** (PS, Det Comd, Opr) route PC → OC. A **PC's own request goes straight to the OC**. Regulars (OC/SM/2IC/P2IC) don't use the request flow at all — their absences are keyed directly by S3/admin (no approval, no ledger) so parade states stay correct.
- **(c) PM off:** counts **present at night roll call** (expected back); stay-out personnel simply don't return that night and are counted under the normal stay-out rule.
- **(d) Half-day vs duty:** anyone with any off/leave that day is **skipped by the roster auto-pick**, but the PS can assign manually with a warning.
- **(e) Statuses:** MC/course/briefing/site-testing are **date-ranged records that auto-fill** every parade state they cover; the COS adds/ends/overrides, never re-keys.
- **Hosting:** undecided — plan targets a small Linux VPS + Caddy; decide before task P0.8.
- **Formats:** real sanitized samples of the 3 parade states, RO, and manning list will be pasted when Phases 3/5/6 need them.

## Assumptions that would change the design

1. **No TimeTree import** — app starts fresh; S3 keys opening OFF/OIL balances at rollout.
2. **Ledger deduction counts working days only** — weekends/PHs inside an approved range plot as away but deduct zero. Approver sees the breakdown ("Fri–Mon = 2 OFF deducted").
3. **Balances in integer half-day units** (full day = 2); half-day requests are single-day only; AM+PM same day merges to a full-day deduction.
4. **Parade-state reference times** (pinned finally by the format samples): evening COS message compiled on D−1 forecasts day D; roll call covers the night; morning parade covers first parade of day D.
5. **No per-soldier self-declaration flow** — the COS keys exceptions (self-declaration is a v2 candidate).
6. **No notifications** — WhatsApp remains the unit's channel; approvers get dashboard queue badges. Telegram bot is the v2 answer if latency bites.
7. **No approval delegation in v1** — the app is reachable anywhere, so an OC on leave can still approve from a phone; if that proves unrealistic, add a "2IC acts for OC" toggle later.
8. **Accounts admin-provisioned** (S3 + developer as `is_admin`); no self-signup; admin-driven password reset.
9. **Single company, single timezone (Asia/Singapore, naive datetimes), trusted-insider threat model, mobile-first usage.**
10. **Hosting this data on a commercial VPS is acceptable to the chain of command** — gated by an explicit task (P0.7) to get the OC's written OK *before* deployment. If refused: same app behind Tailscale/WireGuard, not a rebuild.
11. **"Even duties" means max−min spread ≤ 1 per duty type within the month**; consecutive means adjacent *duty* days (so Fri+Mon counts); cross-month carry-over is a tie-breaker only.

## Spec pressure-test

### Weakest links / hidden complexity
- **Parade-state semantics** are the app's real complexity: 3 variants × AM/PM × stay-out × date-ranged statuses × duty personnel. Resolution: one pure engine with a fixed **precedence rule** (deactivated > approved leave > status > duty > stay-out > present), exactly one line per person per parade, **duty overrides stay-out at night**, conflicts surfaced to the COS instead of silently resolved, and a per-line COS override with reason. Heavily unit-tested; the highest-risk phase (3) is split in two.
- **Eligibility pool gaps**: a 3SG PS satisfies *neither* duty rule (COS needs rank ≤ 2SG + Det Comd/Opr; CDO/S needs rank ≥ 2SG + PC/P2IC/PS) — and Delta's PSs are NSF. The rules are applied exactly as written, but the roster page **shows the computed pools** so an accidentally tiny/empty pool is visible immediately.
- **The TU Det Comd trap**: manning slot "TU Det Comd" = appointment P2IC/PS, disjoint from company appointment Det Comd (whose holders fill Det Personnel). Distinct enum identifiers, an explicit slot→appointments mapping table, UI label "TU Det Comd (P2IC/PS)", and a regression test asserting the trap.
- **Leave lifecycle after approval** (spec-silent, all handled): full cancellation with compensating ledger credit (Phase 1); early return / partial amendment with prorated credit (Phase 2); leave approved after a roster/manning is confirmed → flag the conflict, never auto-reassign; edits to a pending request reset it to the start of its route.
- **Retroactive drift in generated documents**: live-recomputed documents change when history changes. Cheap fix: parade states get a **finalize snapshot** (rendered text + who/when) at copy time from Phase 3a.

### Over-scoped — cut from v1
- Manning **swap suggestions** → conflict flags + a filtered eligible-and-available candidate list. S3 decides by looking at one screen.
- Roster **fairness optimization** → greedy generator, soft constraints (evenness, no consecutive) violated-and-highlighted rather than solved; unfillable days left blank and flagged. No solver, ever, at 36 people.
- **Notifications, RO snapshots, audit UI** → later phases; the pasted WhatsApp message remains the archival record for RO.
- **Formatted parade text in Phase 1** → replaced by an "absence board" (who's away on date D). A parade state without statuses/stay-out would mark people on MC as present — a wrong document is worse than none. The exact-format documents land in Phase 3 against the real samples. *(Deviation from the stated MVP shape, deliberately: the core loop still ends with the person visibly away in the app.)*

## Data model

SQLite via SQLAlchemy + Alembic. Dates ISO, times naive SGT. People are never hard-deleted.

- **person** — username (unique), display_name, rank (enum CPT..PTE + explicit integer order), appointment (OC/SM/2IC/PC/P2IC/PS/DET_COMD/OPR), company_role (S3/S4/null), platoon (1–3/null), service (NSF/REGULAR), stay_out, is_active, is_admin, password_hash, must_change_pw.
  *Why one table for person+user: strict 1:1 at this scale; a separate accounts table is indirection with no payoff.*
- **leave_request** — person_id, type (OFF/OIL/LL/OL), start_date, end_date, day_part (FULL/AM/PM; half-day ⇒ single day), reason, status (PENDING_PC → PENDING_OC → APPROVED | REJECTED_PC | REJECTED_OC | CANCELLED), created_at, pc_actor/pc_at, oc_actor/oc_at, remarks. PC-requester rows start at PENDING_OC. Edits while pending reset to the start of the route.
  *Why a date range, not per-day rows: overlap predicates are trivial at this scale; the ledger keeps balance-like state out of date rows.*
- **ledger_entry** — person_id, kind (OFF/OIL), delta_half_days (int ±), reason, source (LEAVE_APPROVAL/MANUAL/REVERSAL), leave_request_id?, created_by, created_at. **Append-only; balance = SUM(delta); no balance column exists anywhere.** Unique(leave_request_id, source, kind) as a double-deduction backstop.
  *Why a ledger: a derived balance cannot drift — the drift problem fixed in schema form — and every half-day is explainable to the soldier disputing it.*
- **direct_absence** — person_id, type (LEAVE/OTHER), dates, day_part, remarks, created_by. S3/admin-keyed absences for regulars (who are outside the request flow). No ledger effect.
- **event** — calendar (TP/ARCTIC), title, start_dt, end_dt, notes, created_by. **event_participant** — event_id + (person_id XOR category NSF/REGULAR/COMMAND_TEAM/PLATOON_1/2/3) + include/exclude flag for per-person exceptions; unique per (event, person) and (event, category).
  *Categories resolve at query time against the current roster — right for future clash checks; past-event reinterpretation after postings is an accepted limitation (parade snapshots protect the documents that matter).*
- **status_entry** — person_id, type (MC/COURSE/BRIEFING/SITE_TESTING/OTHER), start_date, end_date, day_part, **in_camp** (defaulted per type, overridable), remarks, created_by. Date-ranged, auto-fills parades (per answer e). *in_camp separates "absent from parade but in camp" (briefing → eats meals) from "out of camp" (MC).*
- **duty_assignment** — date, duty (COS/CDOS), person_id, state (PROPOSED/CONFIRMED), UNIQUE(date, duty); **duty_swap_log** (who↔whom, dates, actor, at).
- **manning_period** + **manning_slot** — slot (TU_COMD/TU_PLANNER/TU_DET_COMD/DET_PERSONNEL), person_id, det_number (groups a TU Det Comd with their personnel), UNIQUE(period_id, person_id). Slot eligibility driven by an explicit slot→appointments mapping.
- **overseas_declaration** — person_id, dates, destination, created_at, cancelled_at (retractable with a trace — late plan changes are the very thing being tracked).
- **ro_boilerplate** (section, content) · **ro_document** (date unique, messages, qotd) · **ro_extra_item** (time, text) · **weekly_key_events** (week_start unique, content).
- **parade_snapshot** — date, variant, rendered_text, finalized_by/at. Append-only freeze at copy time.
- **public_holiday** — date, name; seeded for current+next year, admin-editable. *(Phase 1 dependency: working-day deduction needs it.)*

**No stored time-off calendar.** Live absence = query over APPROVED leave_requests (+ direct_absence). Calendar, parade, duty availability, manning flags, and meals all read this one derivation. *Why: the "remember to plot it" step cannot be forgotten because it does not exist.*

## Architecture

### Why SQLite
One file, zero administration, real transactions. 40 users producing a few writes a minute is orders of magnitude under its limits; WAL lets reads proceed during writes; backup = one `.backup` command. A client-server DB here is pure ops burden.

### Layout
```
app/
  __init__.py        # create_app() factory — per-test app instances, clean config split
  extensions.py      # db, login_manager, csrf, limiter
  models/
  domain/            # PURE modules, no Flask imports — the testable core
    policy.py        #   RBAC predicates (appointment/company_role/is_admin + duty-of-day)
    eligibility.py   #   COS/CDOS/TU-slot predicates + availability
    presence.py      #   who is where on date D (absences × statuses × stay_out × duty)
    parade.py        #   compute(date, variant) -> one line per person + counts
    roster.py        #   greedy monthly generator (hard/soft constraints)
    meals.py         #   per-meal in-camp counts
  blueprints/        # auth, admin, leave, ledger, calendar, parade, duty, ro, manning, meals
  templates/  static/
migrations/  tests/  seed/  config.py  wsgi.py
```
*Why blueprint-per-domain: each maps to one user-facing job and one build phase; routes, templates, and permissions stay cohesive. Why pure domain modules: the hard part is date/status arithmetic — keep it out of view functions so pytest hits it without HTTP.*

### Auth & sessions
Flask-Login cookie sessions (httpOnly, Secure, SameSite=Lax) · werkzeug password hashing · Flask-WTF CSRF on every form · Flask-Limiter on login (in-memory is fine; per-worker counters accepted) · **session cleared and rotated at login and logout** (fixation) · forced password change on first login (min length 12, no complexity theatre, no rotation) · remember-me for phones · admin reset. **Deny-by-default authorization**: a `@require(policy)` decorator on every route plus **object-level checks** (a PC passes `is_pc` but must also match the request's platoon; leave/ledger lookups verify the viewer is the requester, their approver, or S3 — the realistic breach here is IDOR, not crypto). Rotating-duty rights (COS keys parade, CDO/S edits RO) resolve via `duty_assignment` for that date, with PS/S3 fallback. No 2FA/SSO/WAF — gold-plating for this threat model.
*Why Flask-Login + werkzeug + Flask-WTF: boring, maintained, zero extra services; CSRF is baseline (not gold-plating) for a cookie-auth form app on the internet.*

### The core transaction (approval auto-plots + auto-decrements)
1. Requester (NSF) submits → PENDING_PC (PS and below) or PENDING_OC (PCs). Form shows their own balance; overlaps with their existing requests warn at submission.
2. PC (matching platoon only) reviews: panel shows current balance, deduction breakdown, conducts they're tagged in on those dates (Phase 2+), duty assignments (Phase 4+), manning membership (Phase 6+), overlapping absences, projected away-count per requested day. Approve → PENDING_OC; reject with remark.
3. OC approves → **one DB transaction**: conditional `UPDATE … WHERE status='PENDING_OC'` (rowcount 1 or abort — beats double-click/concurrent approvals), balance and overlap **re-checked inside the transaction**, status → APPROVED + ledger debit rows (OFF/OIL only; working days only). Commit or nothing.
4. Every downstream view derives from APPROVED requests — away immediately, no second step. *This transaction IS the product.*
5. Insufficient balance: loud warning with projected negative; OC may still approve (human decides); negatives flagged on S3's page. Hard-block only a same-day-part double-deduction (data corruption, not judgment).
6. Cancellation (Phase 1): requester cancels pending freely; approved leave is cancelled by S3/OC → status CANCELLED + compensating REVERSAL credit in one transaction. Early return (Phase 2): amend end_date + prorated credit. Ledger stays append-only.

### Document generation
All documents (3 parade variants, RO, roster, manning) are **Jinja text templates** over query results rendered into `<pre>` with a copy button (small vanilla JS — no framework case exists in this app). Deterministic ordering: platoon → rank order → name. Parade states freeze to `parade_snapshot` on copy. *Why text: these are WhatsApp messages today; matching the exact current format is the requirement.*

### Deployment (VPS shape; final host TBD before P0.8)
Small Linux VPS (SG region if possible) · gunicorn `-w 2 -k gthread --threads 4` bound to **127.0.0.1** (SQLite is single-writer; 8 concurrent requests is ample) · **ProxyFix** (x_for/x_proto/x_host=1 — Secure cookies and rate-limit keying are wrong without it) · Caddy reverse-proxy with auto-HTTPS, `reverse_proxy` only (no file_server near the app tree) · systemd (Restart=on-failure, EnvironmentFile 600 with a real SECRET_KEY — app refuses to start on a missing/placeholder key or debug=True, TZ=Asia/Singapore) · DB in `/var/lib/<app>` chmod 600/dir 700 (WAL needs directory write) · pragmas per connection: foreign_keys=ON, busy_timeout=5000, synchronous=NORMAL; journal_mode=WAL once · nightly `sqlite3 .backup` (never cp a live WAL DB), **encrypted with age before leaving the box**, monthly restore drill · ufw default-deny (22/80/443), key-only SSH, unattended-upgrades, non-root service user.

**Data sensitivity (proportionate, not gold-plated):** the dataset is who's in camp each night and who's on activation standby — OPSEC-relevant even if unclassified. Bar: no worse than today's TimeTree posture, and better. Measures: OC's written OK before hosting (task P0.7); data minimization (rank+name+appointment+platoon only — no NRIC, no phone numbers, no medical detail beyond "MC"); bland domain and pre-login page (no unit name/crest); robots.txt deny + X-Robots-Tag noindex; no third-party assets/analytics; deactivate accounts the week someone ORDs.

## Permission layers (two distinct concepts)

**1. App access (RBAC)** — *what you can see and do.* Pure predicates in `domain/policy.py` from appointment + company_role + is_admin (+ duty-of-day), enforced by route decorators and object-level checks. Everyone: request leave, own history, view TP, declare overseas. Command team (OC..PS): ARCTIC, event CRUD. PC: first-step approval, own platoon only. OC: final approval. S3: ledger, direct absences, manning, people data. S4: meals. PS (all three): duty roster. COS-of-day: parade keying. CDO/S-of-day: RO. Admin: accounts, holidays.
*Why code, not DB tables: permissions are a pure function of appointment; an editable permission matrix is config with no configurer at 40 users.*

**2. Assignment eligibility** — *who can be picked.* Pure predicates in `domain/eligibility.py` over rank + appointment:
- `eligible_cos`: rank ≤ 2SG **and** appointment ∈ {Det Comd, Opr}
- `eligible_cdos`: rank ≥ 2SG **and** appointment ∈ {PC, P2IC, PS} (2SG legally sits in both rules; the appointment sets are disjoint, so nobody is dual-eligible)
- TU slots via mapping table: TU Comd {OC, 2IC} · TU Planner {PC} · **TU Det Comd {P2IC, PS} — not company Det Comd** · Det Personnel {Det Comd, Opr}
- `available(p, date)`: no approved absence or blocking status touching the date (incl. half-days, per answer d), not tagged in an overnight/outstation TP event, not already on the other duty.

Eligibility ∧ availability feeds auto-pick; humans always confirm; manual assignment over a warning is allowed; hard-block only rule violations (a PC can never hold COS). Never auto-reject, never silently reassign.

## Build phases (each independently runnable and testable)

- **P0 — Hardened walking skeleton, deployed.** Factory, DB, person+seed, auth, layout, policy, OPSEC gate, VPS+HTTPS+backups. Test: log in from a phone at home.
- **P1 — MVP core loop.** Requests (full/half-day), routing per answer (b), PC/OC queues, the approval transaction, cancellation, PH table, S3 balances + per-person ledger history + manual adjust, absence board. **Kills balance drift.** Test: E2E via test client + parallel run.
- **P2 — Calendars & clash panel.** TP/ARCTIC CRUD, category+exception participants, month view, clash panel (time-window intersection, not date match — AM off vs afternoon conduct is no clash), early-return amendment, **overseas-declaration form** (data starts accumulating long before manning needs it). **Kills manual clash-checking.**
- **P3a — Statuses + morning parade.** Date-ranged statuses (in_camp, day_part), presence engine with precedence, regulars' direct absences, morning parade in exact format (from sample), finalize snapshots, COS-of-day rights.
- **P3b — Remaining parade variants + meals.** COS message + roll call (stay-out/half-day rules per answers c/d), per-meal counts (breakfast = overnight stayers + duty; lunch; dinner) with NSF sub-counts and S4 manual ±, mapping confirmed with S4. **Kills the COS's nightly assembly.**
- **P4 — Duty roster.** Pools displayed, greedy generation (hard: eligibility/availability; soft: spread ≤ 1, no adjacent duty days incl. Fri→Mon — violations highlighted, blanks flagged), PROPOSED→CONFIRMED, validated 1-for-1 swaps + swap log, post-approval clash flags on confirmed duties. **Kills the PS's monthly cross-check.**
- **P5 — RO builder.** Boilerplate sections, daily assembly (roster duty personnel + TP schedule + extra items + pasted messages/QOTD), weekly key events set Friday. (Needs roster + TP: order is forced.)
- **P6 — Manning.** Periods, det-grouped slots with mapping-table eligibility, conflict flags vs leave/OL/declarations (UNKNOWN where data doesn't exist yet, not "available"), eligible-and-available replacement lists. Two-way flags: approving leave for a slot-holder warns both sides.
- **P7 — Polish.** Audit/person-change views, annual retention purge, optional Telegram notifications.

## Phase 0 + Phase 1 task breakdown (one task at a time)

**P0.1** Scaffold: venv, requirements (Flask, Flask-SQLAlchemy, Flask-Migrate, Flask-Login, Flask-WTF, Flask-Limiter, pytest), app factory, config classes (prod refuses placeholder SECRET_KEY/debug), wsgi.py, git init. *Done:* hello page serves; a trivial test passes.
**P0.2** DB wiring: extensions, Alembic init, per-connection pragmas (foreign_keys, busy_timeout, synchronous=NORMAL), WAL. *Done:* `flask db upgrade` creates the DB.
**P0.3** Person model + rank/appointment/role enums with explicit rank ordering + migration + CSV seed (36 people). *Done:* seeded, queryable in `flask shell`.
**P0.4** Auth: login/logout with session clear+rotate, hashing, rate limit, first-login password change, cookie flags. *Done:* login/logout works; fixation test passes.
**P0.5** Mobile-first base layout, role-aware nav, flash messages, minimal CSS. *Done:* sane at phone width.
**P0.6** `domain/policy.py` + `@require` decorator + tests incl. platoon scoping and an Opr-vs-S3-page denial test. *Done:* deny-by-default proven.
**P0.7** OPSEC gate: OC's written OK to host; data-minimization rules in README (no NRIC/phones/diagnoses); bland branding. *Done:* recorded before any deploy.
**P0.8** Deploy: VPS (or chosen host), gunicorn(127.0.0.1, gthread), ProxyFix, Caddy HTTPS + noindex headers, systemd + EnvironmentFile, ufw/key-only SSH/unattended-upgrades, nightly encrypted backup + restore drill, DEPLOY.md. *Done:* login page reachable from a phone at home over HTTPS.

**P1.1** Admin people pages: list/create/edit/deactivate (deactivation lists the person's future leave/pending requests for S3 to void), stay-out toggle, password reset. *Done:* onboard + offboard end-to-end.
**P1.2** LeaveRequest + LedgerEntry models, migrations, constraints (half-day ⇒ single day; ledger uniqueness backstop) and indexes. *Done:* migration applies; constraints tested.
**P1.3** public_holiday table + seed (current+next year SG) + `working_days(range)` helper + tests. *Done:* Fri–Mon OFF computes 2 days.
**P1.4** Balance service (`balance(person, kind)` = ledger SUM) + tests incl. negative balances.
**P1.5** Request form (type, dates, day_part, reason; own balance shown; overlap warning) + "My requests" with cancel-while-pending. *Done:* submit → correct initial status by appointment.
**P1.6** Routing + self-approval guard: PS-and-below → PENDING_PC; PC → PENDING_OC; regulars excluded from the flow; actor ≠ requester enforced. *Done:* unit tests per appointment.
**P1.7** PC queue + detail (balance panel, deduction breakdown), approve/reject with remark, platoon-scoped at the object level. *Done:* PC1 cannot open a P2 request by URL.
**P1.8** OC queue + the approval transaction: conditional status UPDATE, in-transaction balance+overlap re-check, ledger debit, warn-allow negative with explicit confirm. *Done:* induced mid-transaction failure leaves no partial state; double-submit deducts once.
**P1.9** Cancellation of approved leave (S3/OC) → CANCELLED + compensating REVERSAL credit in one transaction. *Done:* balance restored; absence disappears from derivations.
**P1.10** S3 ledger pages: all-balances table (negatives flagged), per-person history (every delta with reason/actor — this is what retires the shadow spreadsheet), manual ± with mandatory reason. *Done:* adjustment visible in history and balance.
**P1.11** Presence service v1 + absence board: `absences_on(date)` with day-part tags (requests + direct absences), simple copyable list. *Done:* approved leave appears for the right dates; cancelled leave doesn't.
**P1.12** E2E test: request → PC → OC → ledger → absence board via the Flask test client.
**P1.13** Rollout: S3 keys opening balances (UI or CSV command), 1–2 week parallel run against TimeTree, hard cutover date, rollout checklist.

## Risks & open decisions

- **Format fidelity** — parade/RO/manning templates blocked on real samples; Phases 3/5/6 each begin with them. The samples also pin the parade compile-time semantics (assumption 4).
- **OPSEC** — P0.7 gate; fallback is VPN overlay, not a rebuild.
- **Approval latency** — no notifications; badges only. Watch during parallel run; Telegram bot is the escape hatch.
- **Adoption** — the ledger only earns trust if every delta is explainable; that's why per-person history ships in Phase 1 and manual S3 adjustments require reasons.
- **Eligible-pool reality check** — if Delta's actual ranks leave the CDO/S pool near-empty, the rule (not the app) is the problem; pools are displayed so this surfaces on day one of Phase 4.
- Open: meal-category→meal mapping (confirm with S4 in P3b); whether all three PSs share roster rights (default yes); OC-away delegation (default none, revisit); event-participant materialization for history (skipped — snapshots cover documents); retention cadence (default annual manual purge).

## Verification

- Unit: policy (incl. platoon/object scoping), eligibility (incl. TU Det Comd trap), working-day math, ledger/balance, presence precedence, parade variants, roster constraints.
- E2E: test-client walk of the core loop incl. cancellation; double-submit idempotency test.
- Manual: each role on a phone-width viewport; Opr account probing S3/ARCTIC/other-platoon URLs (IDOR check) before launch.
- Ops: HTTPS reachable from outside; backup restore drill executed once before real data exists.
