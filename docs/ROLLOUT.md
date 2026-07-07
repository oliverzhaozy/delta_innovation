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

## Ongoing habits

- Someone ORDs/posts out → S3 deactivates the account the same week
  (People → edit → untick Active). Deactivation lists any open leave to
  resolve first.
- Nightly backups restore-drill once a month (see DEPLOY.md, Phase 0.8).
