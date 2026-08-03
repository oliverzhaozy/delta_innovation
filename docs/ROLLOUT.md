# Phase 1 rollout checklist

The MVP replaces S3's OFF/OIL tracking and the "remember to plot it" step. It
earns trust in the first two weeks or never — hence the parallel run.

## Before go-live

1. **Real roster.** Done, and the instructions moved: `seed/people.csv` IS the
   real 36-person roster, and the live host is seeded from a copy of the dev
   DB rather than from CSV (decision (gg), 2026-08-02), so it carries the
   movement data with the people. DEPLOY.md's "Replicate the dev DB onto the
   host" is the current procedure; `flask seed-people seed/people.csv` stays
   the CSV path and skips already-seeded usernames. No `is_admin=1` is needed
   for the command team — `policy.is_admin` grants admin by appointment (owner
   2026-08-02), and the stored flag is only the manual grant for a Det
   Comd/Opr such as the S3 or the developer.
2. **Opening balances.** Export S3's current OFF/OIL tracking into a CSV
   (`username,off_days,oil_days`, halves allowed), then:
   `flask seed-balances seed/opening_balances.csv --by <s3_username>`.
   The command refuses to touch anyone who already has ledger entries.
3. **Verify with S3.** S3 opens the Ledger page and confirms every balance
   against the old tracking *before* anyone requests leave. Fix discrepancies
   with manual adjustments (each needs a reason — "rollout correction" is fine).
4. **Holidays.** Confirm `seed/holidays_sg.csv` covers the current year;
   key next year's once MOM gazettes it.
5. **Issue accounts.** Everyone gets their username + the default password
   in person or via the platoon WhatsApp; first login forces a change.
   (Remind people: 12+ characters.)

## Parallel run (1–2 weeks)

- All new OFF/OIL requests go through the app; PCs and OC approve in-app.
- S3 keeps the old tracking updated alongside and compares balances weekly.
- TimeTree stays authoritative for TP/conducts (calendars arrive in Phase 2).

## Cutover

- Announce a hard date: from that day, the app's ledger is the record and the
  old tracking stops. Any dispute is settled by the per-person ledger history.
- Keep TimeTree read-only until Phase 3 replaces the parade-state workflow.

## Phase 2 cutover — TP/ARCTIC

Once Phase 2 is deployed and PCs/OC are keying TP and ARCTIC FOE conducts
into the calendar, the same parallel-run-then-cutover shape applies to
conducts as Phase 1 applied to OFF/OIL:

- Before the cutover date, key every conduct already on TimeTree (TP and
  ARCTIC) into the app so the clash panel isn't missing anything — it can
  only warn about what's actually been entered.
- Announce a hard date: from that day, the app is authoritative for TP and
  ARCTIC — the event, its participants, and the leave clash panel are the
  record.
- TimeTree goes **read-only** for conducts from that date on; nobody enters
  a new conduct there. It's kept only as the historical archive of anything
  predating the cutover.
- ARCTIC visibility doesn't change — command team only, same as it was on
  TimeTree; this cutover is about which tool is authoritative, not who sees what.

## Phase 3 cutover — parade states & meal indents

Phase 3 replaces the COS's nightly hand-assembly of the three WhatsApp
documents. The stakes are byte-level: a parade state with a wrong count is
worse than none, so this cutover is judged on exact output, not vibes.

- **Before the parallel run:** PS/S3 key every live status into the app — the
  documents can only be right about what's been keyed. Two things are not
  statuses (2026-07-26 revision): **ON COURSE** derives from a TP calendar
  event labelled "Course", so key the course as an event, and BRIEFING /
  SITE_TESTING are gone as types — MC and OTHER are the only ones left, with a
  briefing keyed as an in-camp OTHER. The **regulars' off/leave is not keyed
  here at all**; it lives in the external ARCTIC FOE system, so a regular with
  nothing keyed is SUPPOSED to appear in CURRENT STRENGTH — that is not a
  missing status. Stay-out flags checked person by person (People admin).
- **Parallel-run nights (1–2 weeks):** each evening the COS compiles the COS
  message and roll call the old way AND opens the app's pages for the same
  dates; each morning likewise for the morning parade. The owner (or the COS)
  eyeballs the app's text against the real sent message **character by
  character** — categories, order, counts, headers. Every mismatch is either
  un-keyed data (key it) or a renderer bug (report it; the golden tests pin the
  format, so a mismatch is a real finding).
- **The sent message is the record (2026-07-26 revision):** there is no
  "Finalize & copy" button and no snapshot archive — a parade document is
  re-derived from live data on every request, so Copy is a plain copy. What
  settles "what did we actually send that night" is the WhatsApp message
  itself; re-opening an old date shows today's answer for it, not the text
  that was sent.
- **S4 counter:** S4 compares the month grid's expected number — the day count
  behind it, from each day's morning parade — against their own count for the
  same days (every NSF plus the regulars ticked as counted for meal indents in
  People admin, decisions (j)/(bb)/(cc)).
- **Hard cutover:** announce a date; from that night the app's text IS the
  message (paste, don't retype). Manual assembly stops. Anything still keyed
  wrong surfaces as a conflict line or a wrong count the next morning and gets
  fixed in the app, never patched in WhatsApp.
- Requires the app deployed and reachable from phones (P0.8) — the COS
  compiles from home.

## Phase 4 cutover — duty roster

Phase 4 replaces the PS's hand-built COS/CDO-S roster. The app proposes and a
human decides: the generator plans working days only and the PS edits what it
got wrong — every row is live the moment it is written (owner 2026-07-27), so
the cutover risk is a roster nobody reviewed, not a silent reassignment.

- **Parallel month:** the PSs generate one month alongside the manual roster.
  First thing to check is the **pools panel** against reality: the eligibility
  rules are strict (COS = ≤2SG Det Comd/Opr; CDO/S = ≥2SG PC/P2IC/PS), and a
  3SG PS legitimately appears in NEITHER pool. If a pool is near-empty, the
  rule — not the app — is the problem; raise it before trusting a roster.
- **During the parallel month:** exercise manual assigns (including one over
  an availability warning, which asks to confirm on the page that names the
  clash) and block one day, so both flows have been driven with real names.
  Blanks and ⚠ flags on the page are findings, not bugs: a blank means no one
  eligible was available; a "holder absent" flag means leave/MC landed after
  the assignment and the PS resolves it by assigning over the slot.
- **Generation is safe to repeat:** regenerating replaces the generator's own
  picks and leaves every manual assignment alone. To empty a day, block it
  (that also removes any holders on it); to change a person, assign over the
  slot.
- **Hard cutover:** the following month, the manual roster stops. From day
  one of that month the app's roster drives roll-call CURRENT STRENGTH, the
  RO's duty lines, and the rotating COS's parade-keying rights (today's and
  tomorrow's COS can key statuses; the rights disappear with the assignment).

## Phase 5 cutover — Routine Orders

Phase 5 replaces the CDO/CDS's nightly hand-assembly of the RO. Like the
parade states, this is judged on exact output — but the RO has more keyed
content, so the pre-run setup matters most.

- **Before the parallel run (S3, one-time):** key the six Matters sections
  into RO boilerplate exactly as the current RO carries them. TP conducts
  already in the calendar auto-insert into the timeline — key any that are
  missing.
- **Weekly habit (2026-07-24 revision):** none for key events — the Mon–Fri
  block derives from the TP calendar (a weekday with no conduct shows the
  public holiday's name or "Garage Maintenance"). Keeping the TP calendar
  current IS the keying. Recurring daily lines (0600 Roll call, TBC LP/SBA)
  are keyed per-day as timeline items by the CDO/CDS.
- **Parallel-run evenings (1–2 weeks):** each evening the CDO/CDS opens
  `/ro` (it defaults to tomorrow), pastes the day's messages/QOTD blob, keys
  the day's timeline items, and compares the app's text against the real RO
  they assemble the old way — character by character. Duty Personnel must
  match the duty roster, whose rows are live the moment they are written
  (owner 2026-07-27); the `[NO CONFIRMED DUTY]` placeholder means no duty row
  exists for that date — an unfilled slot or a blocked day — not a missing
  confirmation step. Mismatches are un-keyed data (key it)
  or a renderer bug (report it — the golden pins the format).
- **Known normalizations (owner decisions, not bugs):** uniform 12-➖
  separators, no trailing spaces, and the TBC block always renders last.
- **Hard cutover:** announce a date; from that evening the app's text IS the
  RO (paste, don't retype). There is no RO snapshot by design — the pasted
  WhatsApp message remains the archival record.

## Phase 6 cutover — TU manning

Phase 6 replaces the hand-typed TU manning list. Lower tempo than the nightly
documents (a period every week or two), so the cutover is one real period
built in parallel.

- **Before the first period (S3, one-time):** key phone numbers on the
  People admin page (decision (q) — phones exist for this document only; an
  unkeyed phone renders "( )" to fill in WhatsApp). Remind everyone the
  overseas-declaration form exists — the conflict flags can only know what
  was declared or keyed.
- **The trap, on purpose:** the document line "DET COMD" is the slot the app
  calls "TU Det Comd (P2IC/PS)". The pick list will not offer a
  company-appointment Det Comd for it — that is the eligibility rule working,
  not a bug; company Det Comds go under DET PERSONNEL.
- **Parallel period:** build the next real activation window in the app
  alongside the usual hand-typed list; compare the rendered text character by
  character (known normalization: no trailing spaces). Check every ⚠ flag —
  each is an approved absence, an out-of-camp status, or a live overseas
  declaration overlapping the period. "No known conflict" means exactly that
  and no more: the app cannot see undeclared travel.
- **Second pair of eyes before it is pasted (decision (ff), 2026-08-02):** the
  S3 builds the period as a DRAFT, presses **Confirm** (→ PENDING), and any PC
  opens `/manning/queue` and **Approves** it, or sends it back with a required
  remark — which returns the period to DRAFT for rework and re-confirm.
  Whoever confirmed cannot also decide. Approval gates **nothing**: the
  document, Copy, the leave-detail manning panel and the RO all work at every
  status, and editing a period never changes its status. It is the agreed flow
  all the same — the text goes to WhatsApp after a PC has approved it, not
  before.
- **Hard cutover:** from the next period on, the app's text IS the list
  (paste, don't retype). There is no manning snapshot by design — the pasted
  WhatsApp message remains the archival record.

## Ongoing habits

- Someone ORDs/posts out → S3 deletes the account the same week
  (People → edit → Delete person). This is permanent and cascades: their
  leave, ledger, statuses, duties and manning slots go, as do records they
  actioned on others (leave they approved, and its ledger deductions — so
  other people's balances can move). The edit page lists any open leave
  first; resolve anything that still matters before deleting.
- Nightly backups restore-drill once a month (see DEPLOY.md, Phase 0.8).
