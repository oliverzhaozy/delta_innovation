# Parade State Formats — Authoritative Spec

> Supplied verbatim by the owner on 2026-07-06 (with owner decisions (g)/(h)/(i) captured the same day, see bottom).
> This file is the format authority for Phase 3's three parade documents. TECH_PLAN.md references it; golden tests
> in `tests/` pin renderers to it byte-for-byte. Change nothing here without the owner.

## Universal Rules (Applies to All Messages)

- **Total Strength:** must always account for all personnel in the company across the categories.
- **Formatting:** all names in CAPITAL LETTERS. All dates in DDMMYY format.
- **Header Counts:** the number in parentheses next to a category header — e.g. `LEAVE (X):` — must exactly match the
  number of personnel listed under it. Empty categories show the header only with no numbered placeholders.
- **Sorting Hierarchy:**
  - *Internal logic:* sort by Appointment (OC > OC DES > 2IC > SM > CSM DES > PCs > P2ICs) then by Rank
    (CPT > 3WO > LTA > 2LT > SSG > 2SG > 3SG > CFC > CPL > LCP > PTE). Do not alphabetize within the same rank.
  - *Display output:* strictly `RANK NAME` (e.g. `3WO ANDY LEOW`). Do not include appointment indicators in the
    final output lists.
- **Date range on every absent line (owner decision, 2026-07-27):** in all three messages, every line under LEAVE,
  OFF/OIL, ON COURSE, MC, and OTHERS ends with the dates the person is away, in parentheses:
  - LEAVE / OFF/OIL / MC — `RANK NAME (DDMMYY - DDMMYY)`, collapsing to `RANK NAME (DDMMYY)` on a one-day range.
    The category already names the reason, so the dates stand alone.
  - ON COURSE — `RANK NAME (COURSE TITLE: DDMMYY - DDMMYY)`; the category alone does not say which course.
  - OTHERS — `RANK NAME (REASON: DDMMYY - DDMMYY)`, e.g. `1. CPL JO-WAYNE (HL: 270726 - 280726)`.

  OTHERS IN CAMP is unchanged (reason only, never dates); STAY OUT and CURRENT STRENGTH lines stay bare. A line a
  keyer DRAGS into a category is also bare: a dragged person has no backing row whose dates could honestly be quoted.

## Message 1: COS Message

**Purpose:** request status updates for the NEXT DAY.

Key rules:
- Does **not** include all personnel. NSFs without pre-reported statuses are omitted from the initial text.
- All Regulars are automatically populated into the STAY OUT category as a default unless they have an active,
  overriding status. **(Owner decision, 2026-07-31: the `stay_out` flag is now the sole source of this category.
  Regulars ship with the flag ticked, so the default is unchanged in practice — but a regular whose flag is
  unticked is omitted from this message like any present NSF, rather than forced into STAY OUT by service.)**
- Inherit ongoing statuses (LEAVE, OFF, OIL, ON COURSE, MC) from the previous state only if their date range covers
  the next duty day.
- Temporary statuses like OTHERS IN CAMP from the previous day are dropped and not copied over.

Format:

```
Hello all, [RANK NAME] is the COS for [DDMMYY]. Please indicate if you are on course/off/ma etc:

STAY OUT (X):
1.

LEAVE (X):
1.

OFF/OIL (X):
1.

ON COURSE (X):
1.

MC (X):
1.

OTHERS (X):
1.
```

## Message 2: Roll Call State

**Purpose:** consolidated accounting record for the NEXT DAY.

Key rules:
- All personnel in the company must appear exactly once.
- Personnel from the finalized COS Message are transferred directly into their corresponding NOT PRESENT IN CAMP
  categories.
- Everyone else not explicitly captured with an absent status is placed into CURRENT STRENGTH.
- **Math validation:** Total Strength = Current Strength + Absent Strength. All tracking formulas must balance
  perfectly back to the total company headcount.

Format:

```
DELTA ROLL CALL STATE:
[DDMMYY]

TOTAL STRENGTH: [TOTAL_STRENGTH]

CURRENT STRENGTH: [A]

ABSENT STRENGTH: [B]

——

PRESENT IN CAMP ([C]):

CURRENT STRENGTH ([A]):
1.

OTHERS IN CAMP (0):

——

NOT PRESENT IN CAMP ([D]):

STAY OUT ([E]):
1.

LEAVE ([F]):
1.

OFF/OIL ([G]):
1.

ON COURSE ([H]):
1.

MC ([I]):
1.

OTHERS ([J]):
1.
```

## Message 3: Morning Parade State

**Purpose:** finalized record of actual morning attendance for the CURRENT DAY.

Key rules:
- All personnel in the company must appear exactly once.
- Starts from the Roll Call State baseline, but automatically shifts all STAY OUT personnel into CURRENT STRENGTH
  (signifying they have returned to camp for the day).
- **"Not Joining FP" processing:** if a list of personnel missing Field Parade is provided, automatically move them
  from CURRENT STRENGTH to OTHERS IN CAMP and append their specific reason in parentheses — e.g.
  `3SG OLIVER ZHAO (BDO)`.
- **Math validation:** the tracking formulas must perfectly balance back to the total company strength.

Format:

```
DELTA MORNING PARADE STATE:
[DDMMYY]

TOTAL STRENGTH: [TOTAL_STRENGTH]

CURRENT STRENGTH: [A]

ABSENT STRENGTH: [B]

——

PRESENT IN CAMP ([C]):

CURRENT STRENGTH ([A]):
1.

OTHERS IN CAMP ([K]):
1.

——

NOT PRESENT IN CAMP ([D]):

LEAVE ([F]):
1.

OFF/OIL ([G]):
1.

ON COURSE ([H]):
1.

MC ([I]):
1.

OTHERS ([J]):
1.
```

## Owner decisions resolving the spec's open points (2026-07-06)

- **(g) Full parade display order.** Appointment: OC > [OC DES] > 2IC > SM > [CSM DES] > PC > P2IC > PS > Det Comd >
  Opr. Rank: **CPT > 3WO > LTA > 2LT > MSG > SSG > 1SG > 2SG > 3SG > CFC > CPL > LCP > PTE** (3WO hoisted above LTA
  per the unit convention; MSG and 1SG — unlisted in the original rules — slot at their legal-order positions around
  SSG). No alphabetizing within rank; ties break by platoon then keyed order. Display-only: the app's legal
  `RANK_ORDER` (eligibility rules) is unaffected.
- **(h) OC DES / CSM DES deferred.** Their sort slots are documented (bracketed above and as comments in the code
  constant); the appointments are added to the app only when Delta actually has a DES posting.
- **(i) AM-off at night roll call = absent.** One rule for both roll call and morning parade of day D: absences with
  day part FULL or **AM** count as absent; **PM**-off counts as present (expected back at night — owner decision (c);
  away in the afternoon only).

## Derived mappings (how app data feeds the categories)

- **STAY OUT** = the `stay_out` flag alone (owner decision, 2026-07-31: service = REGULAR no longer forces it —
  regulars ship flagged in the seed data, and a regular whose box is unticked parades PRESENT like anyone else).
- **LEAVE** = approved leave of type LL/OL. **OFF/OIL** = approved OFF/OIL leave. (The direct-absence contribution
  went with the `direct_absence` table on 2026-07-26 — regulars' off/leave lives in ARCTIC FOE, not in this app.)
- **ON COURSE** = a TP calendar event labelled `Course` covering the date (owner decision, 2026-07-26: `StatusType`
  has no COURSE member — the event is the sole source, and every DATE it covers counts, clock times ignored).
  **MC** = status MC.
- **OTHERS** (not present) = out-of-camp statuses, i.e. a status of type OTHER keyed out of camp (2026-07-26:
  StatusType is MC/OTHER only — BRIEFING and SITE_TESTING were folded into OTHER, and direct absences are gone).
- **OTHERS IN CAMP** = in-camp statuses (e.g. a briefing, "not joining FP" entries) — morning parade only; roll call
  shows `(0)`.
- **Absent-line dates** = the winning absence row's own `start_date`/`end_date`, so the line reports when the person
  is back — never the date of the document they appear on.
- **ON COURSE course title** = the title of the TP calendar event that put the person on course, uppercased.
- **OTHERS reason** = the status row's remark, falling back to the status type's label when there is none — the same
  fallback OTHERS IN CAMP uses.
