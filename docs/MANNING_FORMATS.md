# TU manning format — verbatim authority (P6.1)

Owner-supplied sample received 2026-07-07. Byte-level authority for
`domain/manning.py`'s renderer and its goldens (same posture as
PARADE_FORMATS.md and RO_FORMATS.md). Reproduced EXACTLY as sent; the owner
decisions below say what is format and what is hand-typing artifact.

## The sample (period 5–13 Jul 2026)

```
TASK UNIT (TU) MANNING FOR 
050726 - 130726

TU COMD: CPT WONG LI XUAN 
(9190 9702) 
TU PLANNER: LTA QUEK JING YU
(9736 3276)

TU 1
DET COMD: 3WO WONG JINGHENG
(9798 3466) 
DET PERSONNEL: 2SG JEYMUS TAN
(8518 3687) 
DET PERSONNEL: 3SG WONG WEI XUAN
(9683 9858) 
DET PERSONNEL: CPL ANG CHENG ZE
(8435 8990) 

TU 2
DET COMD: 2SG RAYBRIEL WONG
(9382 3212)
DET PERSONNEL: 3SG LOY QIYUAN 
(9673 7123)
DET PERSONNEL: 3SG XU XIANGRUI
(8218 8905) 
DET PERSONNEL: LCP SAMUEL LIM
(9838 7704)
```

## Observed structure (renderer-facing facts)

1. **Header:** `TASK UNIT (TU) MANNING FOR` then `DDMMYY - DDMMYY` on the
   next line. The period is date-ranged, not named; owner: ranges usually
   span 4–7 days (the sample spans 9 — advisory, never validated).
2. **HQ block:** `TU COMD: <RANK> <NAME IN CAPS>` and
   `TU PLANNER: <RANK> <NAME IN CAPS>`, each followed by a phone line.
3. **Detachments:** `TU <n>` heading, then one `DET COMD:` line and N
   `DET PERSONNEL:` lines (3 each in the sample; headcount is data, not a
   rule — per-det headcount rules are deliberately cut from P6). Since
   decision (aa) that splits in two: auto-generation SIZES to a fixed
   structure (2 dets × (1 Det Comd + 3 personnel), plus 1 TU Comd and 1 TU
   Planner), but RENDERING still enforces no headcount rule — a period built
   or edited by hand into any shape, with a fourth man or a det 3, renders
   exactly as keyed.
4. **THE TRAP, in the document itself:** the rendered label `DET COMD:` is
   the manning slot `TU_DET_COMD`, filled by appointment **P2IC/PS** — never
   by a company-appointment Det Comd, who fills `DET PERSONNEL`. The UI label
   stays "TU Det Comd (P2IC/PS)"; only the DOCUMENT prints `DET COMD`.
5. **Phone lines:** every person carries `(#### ####)` on the following
   line — see decision (q).
6. Blank line between the header and HQ block, between HQ and TU 1, and
   between detachments; trailing spaces on several lines (hand-typing).

## Owner decisions

- **(l-bis) Normalization applies (precedent RO decision (l)):** the renderer
  emits no trailing spaces; irregular spacing in the sample is hand-typing
  artifact, not format.
- **(q) Phone numbers ARE stored (owner decision 2026-07-07, revising the
  data-minimization rule):** `Person.phone` is an optional S3-keyed field
  ("9190 9702" free text); the document renders `(<phone>)` under each name,
  and `( )` as the fill-in-WhatsApp placeholder when no phone is keyed.
  CLAUDE.md's data-sensitivity rule is amended accordingly: the number stays
  OPTIONAL, S3-keyed, and used by this document alone — nothing else reads it.
  `[REVISED 2026-08-02 by decision (gg)]` This decision originally added that
  the sanitized demo roster never carried real numbers; that roster is gone
  (`seed/demo_people.csv` deleted) — the public instance runs the real roster
  from `seed/people.csv`, so real numbers do reach the host, and the
  optional-and-single-purpose rule above is what keeps the field minimal.
- **(r) Period naming:** periods are date-ranged in the document; the model
  keeps an OPTIONAL name for the S3's period list only — it never renders.
  `[SUPERSEDED 2026-07-28 by TECH_PLAN decision (aa): periods are date-ranged
  and nothing else — the name column is dropped, so the second clause no
  longer describes the model.]`
