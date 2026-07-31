# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Implementation is **in progress** (started 2026-07-05 at Phase 0). `SPEC.md` is the product spec; `docs/TECH_PLAN.md` is the approved technical plan and the authoritative reference for the data model, architecture, permission layers, build phases, and the P0/P1 task breakdown — work through its tasks in order and check git log to see where the build stands. Read TECH_PLAN.md before doing anything substantive; do not re-plan what it already decides. P0.8 (deploy) is DONE (2026-07-27): live at coyadmin.duckdns.org on the GCP always-free e2-micro with the sanitized demo roster — `DEPLOY.md` is the runbook, and its whitelist-tarball build is the rule that keeps real data off the host; the P0.7 OC gate remains deferred per TECH_PLAN decision (k).

## Executor cognitive profile

Every model executing tasks in this repo follows the cognitive profile below (pre-computation rhythm, risk-aversion checklist, anti-rush rules, halt conditions). Where it conflicts with this file or `docs/TECH_PLAN.md`, those win.

@docs/fable-behavior.md

## Model roles (owner directive, 2026-07-09; executor updated to Opus 5 on 2026-07-25)

**Fable 5 is the planner; Opus 5 is the orchestrator/executor.** Apply this every session and every prompt:

- **Planning** — brainstorming, design decisions, specs, and plan files are Fable 5's job. If the session (main-loop) model is not Fable 5, delegate planning to a subagent with `model: "fable"` (Plan/Explore agents) and review its output before proceeding.
- **Orchestration & execution** — implementation, multi-step builds, and agent fan-outs run on Opus 5. If the session model is not Opus 5, delegate execution to subagents with `model: "opus"`; the main loop stays in the role of planner/reviewer.
- Trivial one-liners (typo fixes, single obvious edits) may be done inline by whichever model is in the main loop — don't spawn an agent to change one word.
- This is a standing directive: do not ask for re-confirmation each session.

## Parallel agents (owner directive, 2026-07-28)

Default to fanning out subagents whenever a task has independent parts — separate files, separate research questions, separate P-tasks, review dimensions. Launch them concurrently (one message, multiple Agent calls), don't work the parts sequentially in the main loop.

- **Workflow tool is pre-authorized.** Treat this directive as the owner's standing "use a workflow" opt-in: for substantive multi-part tasks (audits, reviews, migrations, broad research), reach for Workflow orchestration without asking first. Respect the session's workflow size guideline unless the prompt raises it.
- Decompose first, then dispatch: a quick inline scout to build the work-list is fine; the fan-out itself runs on subagents per the model roles above (execution on Opus 5, planning on Fable 5).
- **Use the superpowers skills to structure the fan-out**: invoke `superpowers:dispatching-parallel-agents` when 2+ independent tasks are in hand, and `superpowers:subagent-driven-development` when executing a written plan's tasks via subagents.
- Do NOT parallelize what is genuinely sequential (dependent edits, migration chains) or trivial (one-file fixes) — more agents on dependent work is waste, not speed.
- This is a standing directive: do not ask for re-confirmation each session.

## UI changes (owner directive, 2026-07-31)

Any task that adds or modifies UI (Jinja templates, `styles.css`, `app.js` presentation code) MUST invoke the `frontend-design:frontend-design` skill before writing markup or styles. Standing directive: do not ask for re-confirmation each session.

## What this is

A Flask web app replacing TimeTree as the single source of truth for a ~36-person Singapore army company's manpower admin (leave, parade states, duty rosters, RO, TU manning, meal counts). The two governing ideas:

1. **Single source of truth**: final (OC) approval of a leave request is ONE transaction that sets status APPROVED and writes the ledger deduction. There is no stored time-off calendar — absences are always derived by querying APPROVED requests. Never add a separate "plot" step or a denormalized absence/balance column.
2. **The app proposes, a human decides**: clash checks, roster generation, and manning flags warn and suggest; they never auto-reject leave or silently (re)assign anyone. Hard-block only rule violations that would corrupt data (double-deduction, ineligible duty assignment).

## Hard constraints from the owner

- Stack fixed: Python + Flask + SQLite + server-rendered Jinja/HTML/CSS. No JS framework; vanilla JS sprinkles only (e.g. copy buttons).
- ~40 users; scale is a non-issue. Do NOT add caching, queues, background workers, Postgres, or Docker.
- Security is a sane baseline (hashed passwords, HTTPS, httpOnly sessions, CSRF, deny-by-default authz with object-level checks). Flag genuine negligence; do not gold-plate (no 2FA, WAF, SSO).
- Partly a learning project: significant decisions get a one-line "why" (decision level, not line level).
- Generated documents (3 parade-state variants, RO, roster, manning) are plain-text Jinja templates matching the unit's exact WhatsApp formats — the owner supplies real samples when Phases 3/5/6 start; templates are blocked until then.

## Git workflow

Commit and push to GitHub **regularly as you work** so status and work are never lost — do not batch a whole session into one commit. The plan's task breakdown gives the natural boundaries: at minimum, commit and push after every completed task (P0.1, P0.2, …), and mid-task whenever a coherent piece works. Use clean, imperative commit messages that name the task (e.g. `P1.3: add public_holiday table and working-days helper`). The repo is not yet initialized — `git init` and the GitHub remote are part of P0.1.

Owner's decision (2026-07-05): seed CSVs (including real personnel data), `.env`/secrets, and the SQLite database MAY be committed — this repo doubles as the backup of record. Because of that, the GitHub repo MUST stay private; never change its visibility or mirror its contents elsewhere.

## Commands

Python lives in the repo venv — use `.venv/Scripts/python` (Windows) directly:

- Dev server: `.venv/Scripts/python -m flask run` (FLASK_APP set by `.flaskenv`)
- Tests: `.venv/Scripts/python -m pytest -q`; single test: `.venv/Scripts/python -m pytest tests/test_x.py::test_name`
- Migrations: `.venv/Scripts/python -m flask db migrate -m "..."` then `... -m flask db upgrade`
- Seed people: `.venv/Scripts/python -m flask seed-people seed/people.csv` (skips existing usernames; default password `ChangeMe123!` with forced change at first login)
- Before committing `instance/delta.db`, checkpoint the WAL so the file is current: `.venv/Scripts/python -c "import sqlite3; sqlite3.connect('instance/delta.db').execute('PRAGMA wal_checkpoint(TRUNCATE)')"`

## Architecture (see TECH_PLAN.md for full detail)

- `create_app()` factory; one blueprint per domain (auth, admin, leave, ledger, calendar, parade, duty, ro, manning, meals) — each maps to one build phase.
- `app/domain/` holds PURE modules (no Flask imports): `policy.py` (RBAC), `eligibility.py`, `presence.py`, `parade.py`, `roster.py`, `meals.py`. All date/status arithmetic lives here so pytest hits it without HTTP. Keep view functions thin.
- Ledger is append-only integer half-days; balance = `SUM(delta)`. Corrections are compensating REVERSAL rows, never edits.
- SQLite in WAL mode; per-connection pragmas `foreign_keys=ON`, `busy_timeout`; all dates/times naive Asia/Singapore.

## Domain traps (easy to get wrong)

- **Two distinct permission concepts**: app access (RBAC from appointment/company_role, in `policy.py`) vs assignment eligibility (rank+appointment predicates, in `eligibility.py`). Don't mix them.
- **TU Det Comd ≠ Det Comd**: the manning slot "TU Det Comd" is filled by appointment P2IC/PS; company-appointment Det Comds fill "Det Personnel". Keep enum identifiers distinct; there's a regression test for this.
- **Leave routing**: PS/Det Comd/Opr → any PC → OC; a PC's own request goes straight to OC; regulars (OC/SM/2IC/P2IC) never use the request flow at all — their off/leave lives in the external ARCTIC FOE system (owner directive 2026-07-26), so this app tracks them only via MC/other statuses and TP course events; a regular with nothing keyed appears in CURRENT STRENGTH. There is no `direct_absence` table. Self-approval is structurally forbidden.
- **Deduction counts working days only** (public_holiday table is a Phase 1 dependency); half-day requests are single-day only; AM+PM same day = one full day.
- **Parade precedence**: one line per person per parade — approved leave > out-of-camp status > course > duty > stay-out > present; duty overrides stay-out at night; conflicts surface to the COS, never silently resolved. The derivation is never edited: a keyer's drag is a separate per-(date, variant, person) `parade_override` row, latest-wins, applied INSIDE `build_doc` between categorize and render (so meals inherit it) and undone wholesale by Reset. Nothing is ever written back into leave/status data, and there is still no snapshot archive — the document is re-derived on every request. `[REVISED 2026-07-31 (owner)]` A dragged line carries NO note of its own — keyer-typed override notes were built and then scrapped the next day; an override row is exactly (date, variant, person, target), and only DERIVED absences print a dated suffix. The drag itself (the sheet, `/parade/override` and its Reset) is open to EVERY logged-in user (owner decision 2026-07-31) — the "Not joining FP" quick-add and every other parade write stay gated on `duty_service.can_key_parade_today`.
- **One document, one line source**: `domain/parade.sheet_sections(doc)` is the only place a parade document's lines and numbering exist. The plain-text renderers are a join over it and the keyer's in-message drag sheet iterates the same objects, so the copied WhatsApp text and the interactive markup cannot drift. Never format a parade line anywhere else. The parenthesized suffix has its own single owner inside that: `parade.note_display(AbsenceNote)` — every absent line's `(…)` is that one string (`SheetEntry.body`/`.note` are the same line split at it, and `f"{body} ({note})" == text` is pinned by test).
- **ON COURSE has one source**: a TP calendar event labelled `TpLabel.ON_COURSE` (value `"Course"` — `ArcticLabel.ON_COURSE` owns `"On Course"`, and label values must stay distinct across the two enums). Every resolved participant is out of camp for every DATE the event covers, clock times ignored (`domain/events.event_days` owns that rule). There is no course *status*.
- COS/CDO-S duty rules: COS = rank ≤ 2SG AND appointment Det Comd/Opr; CDO/S = rank ≥ 2SG AND appointment PC/P2IC/PS. The appointment sets are disjoint (a person can never be eligible for both).
- **Overseas declarations are PC-approved and disposable** (owner 2026-07-28, decision (y)): PS/Det Comd/Opr declarations start PENDING and any PC decides; PCs' own and regulars' auto-approve on submission (the OC is never in this chain — unlike leave). Retract and an elapsed end_date hard-DELETE the row (`overseas_service.purge_expired` runs on overseas page loads; no history is kept) — one of two deliberate exceptions to "rows are never deleted" (the other, larger one is the post-out cascade, decision (dd) below). Rejected rows stay visible to the owner (with the PC's remark) until retracted/elapsed; manning flags every non-REJECTED declaration, pending included. Leave requests are the opposite: never deleted — "history" is a display split (`leave_service.live_requests`/`concluded_requests`).
- **Duty rosters are weekday-only and live on write** (owner 2026-07-27, decision (x)): there is no PROPOSED/CONFIRMED step — a generated or assigned row feeds parades, meals, RO, and COS keying rights immediately. `duty_service.duty_days` is the ONE owner of "which dates carry a duty" (Mon–Fri, minus `public_holiday`, minus `duty_blocked_day`); generation, the grid, and manual assignment all call it and never re-derive it. Regeneration replaces only `is_manual=False` rows. Emptying a day = block it (which deletes that date's assignments); changing a holder = assign over the slot. TP events never block generation or availability (decision (z), 2026-07-28) — only covering absences (leave/OFF/OIL, MC/status, course) and already holding the other duty that date skip a person.
- **TU manning generates a FIXED structure** (owner 2026-07-28, decision (aa)): 1 TU Comd, 1 TU Planner, and dets 1–2 ("TU 1"/"TU 2") each 1 TU Det Comd + 3 Det Personnel — auto-generation sizes to exactly that, while rendering still enforces no headcount rule (a hand-built period of any shape renders). Only slot-eligible people with NO_KNOWN_CONFLICT are picked, in roster order with no fairness carry-over; conflicted people are never auto-picked but stay manually assignable. `is_manual` mirrors the duty roster — manual assigns write `True`, regeneration replaces only `False` rows. There is no period name: periods are date-ranged only.
- **Post-out HARD-deletes the person and everything referencing them** (owner 2026-07-30, decision (dd)): ORD/post-out calls `person_service.delete_person` — one transaction, child-first, covering not just the person's own leave/ledger/statuses/duties/manning/overseas/overrides/audit but the records they actioned on OTHERS (leave they approved, statuses they keyed, duty and blocked days they created, events and manning periods they built). Other people's ledger rows attached to that leave go too, so **other people's balances change**; the owner accepted this after being warned. `is_active` no longer exists — every `person` row is a serving member, so nothing filters on it, `active_roster()` is unfiltered (the name is kept: it owns THE roster order), and there is no `DEACTIVATED` presence state or parade tier. *Why: a soft-delete flag left ORD'd members interleaved through every roster, pool, and picker forever; the unit wants them gone, and accepts losing the history that hangs off them.*
- **Platoon categories are keyed data, and their COS carve-out is a WARNING** (owner 2026-07-30, decision (ee)): the three platoons group into seniority categories `PlatoonCategory` STC → Senior → Junior → Baby (declaration order = display order), one platoon per category (`platoon_category.platoon` is UNIQUE and nullable — with 4 categories over 3 platoons one is always empty), each with an `in_cos_pool` toggle. Default shipped mapping: 1=Junior, 2=STC (excused COS), 3=Senior. The carve-out is applied ONLY in `duty_service._pools` — `eligibility.py`'s API is frozen (B4) and this is convention, not law — which is why that helper returns BOTH pools: `auto` (COS minus excused platoons: generation, pools panel, spread violations) and `assignable` (raw eligibility: the manual-assign dropdown). Manual assignment of an excused platoon's person is soft-warned through the existing confirm/`override_availability` flow, never hard-blocked like `duty_exempt`. CDO/S is never filtered — a platoon's PS does CDO/S regardless. *Why: the unit excuses its most senior platoon from COS by convention, and a convention that silently deleted people from the picker would be indistinguishable from a bug.*

## Data sensitivity

Personnel movements and activation-standby manning for a real military unit. Data minimization is a rule: rank + name + appointment + platoon, plus an OPTIONAL S3-keyed phone number (owner decision (q) 2026-07-07, for the manning document only — `docs/MANNING_FORMATS.md`; the sanitized demo roster never carries real numbers) — no NRIC or medical detail beyond the literal string "MC". No unit name/crest on pre-login pages. Per TECH_PLAN decision (k) (2026-07-07): the public instance runs a **sanitized demo roster** (`seed/demo_people.csv`) until the organisation approves the project and takes over security — real personnel data never goes on the public host before that.
