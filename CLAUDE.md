# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Planning is complete; **no code exists yet**. `SPEC.md` is the product spec; `docs/TECH_PLAN.md` is the approved technical plan (2026-07-05) and the authoritative reference for the data model, architecture, permission layers, build phases, and the P0/P1 task breakdown. Implementation starts at task P0.1 **only on the owner's explicit go-ahead** — do not scaffold or code without it. Read TECH_PLAN.md before doing anything substantive; do not re-plan what it already decides.

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

## Planned commands (valid once P0.1–P0.2 land)

- Run dev server: `flask run`
- Migrations: `flask db upgrade` (Alembic via Flask-Migrate)
- Tests: `pytest` (single test: `pytest tests/test_x.py::test_name`)
- Seed people: CSV seed script under `seed/` (created in P0.3)

## Architecture (see TECH_PLAN.md for full detail)

- `create_app()` factory; one blueprint per domain (auth, admin, leave, ledger, calendar, parade, duty, ro, manning, meals) — each maps to one build phase.
- `app/domain/` holds PURE modules (no Flask imports): `policy.py` (RBAC), `eligibility.py`, `presence.py`, `parade.py`, `roster.py`, `meals.py`. All date/status arithmetic lives here so pytest hits it without HTTP. Keep view functions thin.
- Ledger is append-only integer half-days; balance = `SUM(delta)`. Corrections are compensating REVERSAL rows, never edits.
- SQLite in WAL mode; per-connection pragmas `foreign_keys=ON`, `busy_timeout`; all dates/times naive Asia/Singapore.

## Domain traps (easy to get wrong)

- **Two distinct permission concepts**: app access (RBAC from appointment/company_role, in `policy.py`) vs assignment eligibility (rank+appointment predicates, in `eligibility.py`). Don't mix them.
- **TU Det Comd ≠ Det Comd**: the manning slot "TU Det Comd" is filled by appointment P2IC/PS; company-appointment Det Comds fill "Det Personnel". Keep enum identifiers distinct; there's a regression test for this.
- **Leave routing**: PS/Det Comd/Opr → own-platoon PC → OC; a PC's own request goes straight to OC; regulars (OC/SM/2IC/P2IC) never use the request flow — S3 keys their absences as `direct_absence` (no ledger). Self-approval is structurally forbidden.
- **Deduction counts working days only** (public_holiday table is a Phase 1 dependency); half-day requests are single-day only; AM+PM same day = one full day.
- **Parade precedence**: one line per person per parade — deactivated > approved leave > status > duty > stay-out > present; duty overrides stay-out at night; conflicts surface to the COS, never silently resolved.
- COS/CDO-S duty rules: COS = rank ≤ 2SG AND appointment Det Comd/Opr; CDO/S = rank ≥ 2SG AND appointment PC/P2IC/PS. The appointment sets are disjoint (a person can never be eligible for both).

## Data sensitivity

Personnel movements and activation-standby manning for a real military unit. Data minimization is a rule: rank + name + appointment + platoon only — no NRIC, phone numbers, or medical detail beyond the literal string "MC". No unit name/crest on pre-login pages. Deployment is gated on the OC's written OK (task P0.7).
