# Phase 1 rollout checklist

The MVP replaces S3's OFF/OIL tracking and the "remember to plot it" step. It
earns trust in the first two weeks or never — hence the parallel run.

## Before go-live

1. **Real roster.** Replace `seed/people.csv` with the actual 36 people
   (same columns; set `is_admin=1` for S3 and the developer). On the server:
   `flask seed-people seed/people.csv` — skips already-seeded usernames.
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

## Phase 3 cutover — parade states & NSF meal counter

Phase 3 replaces the COS's nightly hand-assembly of the three WhatsApp
documents. The stakes are byte-level: a parade state with a wrong count is
worse than none, so this cutover is judged on exact output, not vibes.

- **Before the parallel run:** PS/S3 key every live status (MC, courses,
  briefings) and the regulars' absences into the app — the documents can only
  be right about what's been keyed. Stay-out flags checked person by person
  (People admin).
- **Parallel-run nights (1–2 weeks):** each evening the COS compiles the COS
  message and roll call the old way AND opens the app's pages for the same
  dates; each morning likewise for the morning parade. The owner (or the COS)
  eyeballs the app's text against the real sent message **character by
  character** — categories, order, counts, headers. Every mismatch is either
  un-keyed data (key it) or a renderer bug (report it; the golden tests pin the
  format, so a mismatch is a real finding).
- **Finalize is the record:** from day one of the parallel run, whoever copies
  a document presses "Finalize & copy" — the snapshot archive is what settles
  "what did we actually send that night".
- **S4 counter:** S4 compares the NSF day/overnight counters against their own
  count for the same nights (indents are NSF-only, decision (j)).
- **Hard cutover:** announce a date; from that night the app's text IS the
  message (paste, don't retype). Manual assembly stops. Anything still keyed
  wrong surfaces as a conflict line or a wrong count the next morning and gets
  fixed in the app, never patched in WhatsApp.
- Requires the app deployed and reachable from phones (P0.8) — the COS
  compiles from home.

## Phase 4 cutover — duty roster

Phase 4 replaces the PS's hand-built COS/CDO-S roster. The app proposes and a
human decides: the generator drafts, the PS confirms, and only CONFIRMED
duties reach parades, meals, and keying rights — so the cutover risk is a
wrong draft nobody reviewed, not a silent reassignment.

- **Parallel month:** the PSs generate one month alongside the manual roster.
  First thing to check is the **pools panel** against reality: the eligibility
  rules are strict (COS = ≤2SG Det Comd/Opr; CDO/S = ≥2SG PC/P2IC/PS), and a
  3SG PS legitimately appears in NEITHER pool. If a pool is near-empty, the
  rule — not the app — is the problem; raise it before trusting a roster.
- **During the parallel month:** exercise manual assigns (including one over
  an availability warning), so the confirm/fingerprint and warning flows have
  all been driven with real names. Blanks and ⚠ flags on the page are
  findings, not bugs: a blank means no one eligible was available; a "holder
  absent" flag means leave/MC landed after confirmation and the PS resolves
  it by manual replace.
- **Confirm is the record:** a month's roster only counts once a PS presses
  Confirm — drafts move nothing. Regenerate freely before confirming; after
  confirming, changes go through manual replace.
- **Hard cutover:** the following month, the manual roster stops. From day
  one of that month the app's CONFIRMED roster drives roll-call CURRENT
  STRENGTH, the NSF overnight meal counter, the COS-message pre-fill, and the
  rotating COS's parade-keying rights (today's and tomorrow's confirmed COS
  can key statuses; the rights disappear with the assignment).

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
  match the confirmed roster; a `[NO CONFIRMED DUTY]` placeholder means the
  month wasn't confirmed, not a bug. Mismatches are un-keyed data (key it)
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
- **Hard cutover:** from the next period on, the app's text IS the list
  (paste, don't retype). There is no manning snapshot by design — the pasted
  WhatsApp message remains the archival record.

## Ongoing habits

- Someone ORDs/posts out → S3 deactivates the account the same week
  (People → edit → untick Active). Deactivation lists any open leave to
  resolve first.
- Nightly backups restore-drill once a month (see DEPLOY.md, Phase 0.8).
