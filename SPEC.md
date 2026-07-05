## Context

- A Singapore military company (here, **Delta**) is made up of NSFs (conscripts) and regulars.
- **Chain of command** (highest to lowest): OC → SM → 2IC → PC → P2IC → PS → Det Comd → Opr.
    - OC, SM, 2IC, P2IC are regulars. PC, PS, Det Comd can be NSF or regular (all NSF in Delta). Opr are all NSF.
    - The **command team** is everyone from OC down to PS.
- **Rank** (highest to lowest): CPT → LTA → 2LT → 3WO → MSG → SSG → 1SG → 2SG → 3SG → CFC → CPL → LCP → PTE.
- **Being away from camp:** OFF and LL (local leave) mean you don't report to camp but stay in Singapore; OIL (off-in-lieu) and OL (overseas leave) also let you travel overseas.
- **Daily duties:**
    - **COS** (Company Orderly Soldier) — anyone ranked 2SG or below whose appointment is Det Comd or Opr.
    - **CDO/S** (Company Duty Officer/Sergeant) — anyone ranked 2SG or above whose appointment is between PS and PC.
- **Guard duty** (GC / SIGC / RG) runs monthly but is **out of scope** for this app.
- **Company roles:** among the 2SG/3SG Det Comds, S3 handles manpower and S4 handles logistics.
- **Platoons** 1, 2, 3 — each has its own PC, P2IC, and PS.
- **Total strength** is simply the number of active people (currently 36); it shifts as people ORD, post in, or command changes.

## Current situation (the problems this solves)

- Delta currently uses **TimeTree** with three calendars: NSF OFF/Leave, Training Programme (TP), and ARCTIC FOE.
    - **NSF OFF/Leave** tracks time off. Flow today: PC approves → OC approves → S3 deducts the balance. Problem: people forget to plot it in TimeTree once approved, so S3's tracking drifts out of sync.
    - **TP** is trainings/conducts, visible to everyone.
    - **ARCTIC FOE** is key trainings/conducts, command team only.
    - PCs manually cross-check TimeTree to see whether someone's requested time off clashes with a conduct or leaves a day short-manned. This is slow and easy to get wrong.
- Delta also regenerates several lists by hand:
    - **Parade state** — accountability of everyone, run by the COS. Three versions a day: the evening **COS message** (people declare their status), the night **roll call state**, and the next **morning parade state**.
    - **Manning list** — who's on standby for activation (S3's job); those people must stay in Singapore. Problem: people decide to go overseas (often Malaysia) late, forcing constant edits.
    - **RO (Routine Orders)** — next day's key events, done by the CDO/S; also lists the next day's duty personnel and the week's key events (set once on Friday).
    - **Monthly COS & CDO/S list** — who's on each duty for the coming month (done by the PS), excluding weekends and public holidays. Tedious to cross-check against TimeTree, so oversights happen and duties get swapped.
- **Meals** — S4 indents breakfast/lunch/dinner based on how many are in camp, but the headcount is often unclear, so meals get under-ordered.

## Ideas

- One web app to do all of the above, **replacing TimeTree** — the app holds the calendars and data itself, so nothing needs to be read out of TimeTree.
- Two ideas guide everything:
    - **The app is the single source of truth.** Approving time off is what plots it on the calendar and adjusts the balance — there's no separate "remember to plot it" step. This is what fixes the tracking-drift problem.
    - **The app helps, the human decides.** It flags clashes and short-manned days and proposes rosters, but a person still makes the final call. It shouldn't silently auto-reject leave or lock in a roster on its own.

## Features

**Accounts & access**

- Everyone has a login. What you can see and do depends on your appointment/role — e.g. only the command team sees ARCTIC FOE, only PCs and the OC approve leave, only S3 edits the OFF/OIL records, only S4 sees the meal counts.

**Calendars & events**

- The app's own version of the three calendars, with access set by appointment.
- For TP and ARCTIC FOE events: the event name, the dates/times it runs, and who's involved. "Who's involved" can be chosen by category (NSFs, Regulars, Command team, Platoon 1/2/3) or by individual names.
- For time-off entries: the person, whether it's AM / PM / full-day, and the type (OFF / OIL / LL / OL).

**Leave requests & approval**

- Anyone can request OFF/OIL/Leave in the app.
- The request goes to the person's PC, then — once the PC approves — to the OC.
- On final approval the app automatically plots it on the calendar, deducts the OFF/OIL balance, and the person then shows as away in the parade states.
- When a PC or OC reviews a request, the app shows that person's current balance and any conduct they're already tagged in on those dates, so the clash check is instant instead of manual.

**OFF/OIL tracking (S3)**

- A page where S3 sees everyone's OFF and OIL balance.
- S3 can add OFF/OIL (with a reason) or deduct them.
- Approved requests feed this automatically, so balances stay in sync without manual entry.

**Parade state generation**

- The app builds all three daily versions (COS message, roll call state, morning parade state) in the exact text format currently used.
- Most of it fills in automatically:
    - People on OFF/OIL/Leave come from approved requests.
    - "Stay out" is a per-person setting — those people count as **away at night roll call** (booked out) but **present at morning parade** (reported in).
    - The COS only keys the genuine exceptions (MC, on course, briefing, site testing, etc.) with a short reason.
- Counting: total strength = active people; current strength = those accounted for at that parade; absent = everyone else (which includes "others in camp", e.g. people at a briefing).
- Half-day off (*to confirm*): an **AM off** shows as away in the morning parade but present again that evening; a **PM off** shows as present in the morning but is expected back for roll call.

**Duty roster generation (monthly COS & CDO/S)**

- Auto-builds the month's COS and CDO/S roster, skipping weekends and public holidays, and only picking people who are eligible (the COS/CDO/S rules in Context) and available that day.
- Fairness: an even number of duties per person per month, and avoid putting the same person on consecutive days.
- Swaps are a straight 1-for-1 swap, keeping the counts balanced.

**RO generation**

- Fixed sections (Safety, Admin, Logistic, Security, R&D, Instructions) are stored once and reused.
- Duty personnel come from the monthly roster.
- The timed schedule is pulled from that day's TP events, with the option to key in extra items not in TP.
- Messages and the Quote of the Day (issued by Bn) are pasted in each day.
- "Key events of the week" is set once on Friday and stays fixed for the week.

**Manning list (S3)**

- Builds the Task Unit (TU) manning for the period. Who can fill each slot:
    - **TU Comd** — OC or 2IC.
    - **TU Planner** — PCs.
    - **TU Det Comd** — appointment P2IC or PS. *(Note: this is not the same as the company appointment "Det Comd".)*
    - **Det Personnel** — appointment Det Comd or Opr.
- The detachment line-up is re-decided each period, not fixed.
- The app flags anyone who's on OFF/OIL/Leave or has declared they're going overseas that weekend, and suggests swaps — S3 confirms.
- To make the overseas problem trackable, there's a feature for people to declare weekend overseas travel in the app.

**Meal counts (S4)**

- For each day, the app shows how many people (and how many NSFs) are in camp, so S4 can indent meals accurately.

## Architecture notes

- **Stack:** Python · Flask · SQLite · HTML/CSS.
- **Hosting:** needs to work from home, not just in camp.