# FABLE-BEHAVIOR — Executor Cognitive Profile

**Binding for any model executing tasks in this repository.** Precedence: `CLAUDE.md` > `docs/TECH_PLAN.md` (incl. its pre-flight addendum's task contracts and Stop & Validate gates) > this file. This file governs *how* to think and check work; those govern *what* to build.

---

## 1. THE COGNITIVE RHYTHM (pre-computation before any output)

Execute this loop silently and completely BEFORE generating any code. Skipping a step because the task "looks simple" is the primary failure mode this file exists to prevent.

**CR-1. Enumerate inputs.** The task text, its contract (Requires/Produces/Forbidden if one exists), and every file the change touches. Verify every Requires artifact actually exists (open it, don't assume) before writing anything.

**CR-2. State-mutation sketch.** List every row INSERT/UPDATE/DELETE the change performs, grouped by transaction. One user action mapping to more than one transaction is a design defect: redesign to one, or write the one-line justification for accepted partial failure.

**CR-3. Symbol map.** For each function to be written or modified: signature, input domain (what values CAN arrive, not what values SHOULD), output shape, and every raise/error path — written down before the body. A function whose error path you cannot name is not designed yet.

**CR-4. Coupling scan.** Grep ALL call sites of every symbol you change — routes, services, templates, tests. Enumerate them with counts. Changing a signature, return shape, or enum without the consumer walk is forbidden. Template call sites count double: they fail at render time, not import time.

**CR-5. Dry run.** Trace one concrete example end-to-end through the *planned* code on paper: real dates, a named fixture person, actual expected values at each step. If the trace requires a value you cannot produce, the design is incomplete — return to CR-2, or halt per §4.

**CR-6. Generate in dependency order.** Types/constants → pure domain function → tests pinning it (goldens/invariants where the repo convention uses them) → service/transaction → route → template. Never write a route before its domain function has a green test.

---

## 2. RISK-AVERSION POSTURE (failure classes + interception checklist)

### Failure classes that ship silently

- **Check-then-act TOCTOU.** A pre-check SELECT followed by a write is a race, not a validation. Intercept: conditional-claim `UPDATE … WHERE <precondition>` with rowcount check (see `approval_service._claim`), or DB constraint + caught `IntegrityError`. Never pre-check uniqueness with a SELECT.
- **Silent default degradation.** Adding a defaulted parameter for new behavior lets every missed call site compile and quietly run the OLD behavior. Behavioral parameters are **keyword-only with no default** so stale callers TypeError in the suite.
- **Derived-state drift.** Never store what is computable from existing rows; never add a second fetch path for data that already has one. A convenience copy IS the bug.
- **Date-offset ambiguity.** Every offset convention (e.g., a document labeled D covering the night D−1→D) lives in exactly ONE owning function; consumers call it, never re-derive it. Day-part boundaries, naive-vs-aware, and month/year rollovers are boundary-test targets, not assumptions.
- **Two renderings of one artifact.** Any content produced in two places (page and snapshot, list and export) must come from one builder function, with an invariant test asserting the outputs are identical.
- **Role check without object check (IDOR).** `@require(role)` proves who they are, not that THIS object is theirs. Every mutating route on an owned object re-verifies the object relationship.
- **N+1 in templates.** A relationship iterated inside Jinja is a query-per-row invisible in review. Eager-load everything a template loops over.
- **Float arithmetic on counted quantities.** Integers in the smallest unit, always.

### Self-QA checklist — run ALL items before claiming any task done

1. Full test suite run; paste the actual count; count ≥ the previous task's count.
2. Diff review: every hunk maps to a sentence of the task text. Orphan hunks are reverted, not explained.
3. Grep for stale references to every renamed/re-signatured/deleted symbol: result must be zero.
4. Re-trace the CR-5 dry-run example through the ACTUAL committed code, not the planned code.
5. Name what the user sees when this code path errors. "An exception" is not an answer.
6. Golden/pinned outputs byte-identical, unless the task text itself quotes the new expected output.
7. State plainly what was verified and how. Never claim "should work" — claim "ran X, observed Y."

---

## 3. CONTEXT EXTENSION RULES (anti-rush operational law)

- **No placeholder artifacts, ever.** No `# TODO`, `# FIXME`, `pass` stubs, `raise NotImplementedError` scaffolds, commented-out code, or "implement later" notes. If a piece cannot be finished within the task, HALT per §4 and ask — a placeholder is a silent scope cut.
- **No shortcut syntax.** No bare `except:`, no mutable default arguments, no `import *`, no exception-swallowing to reach green, no clever one-liner where the surrounding code uses four clear lines. Match the file's existing idiom exactly — the diff should read as if the original author continued typing.
- **Comments state constraints the code cannot show** (invariants, offset conventions, deliberate deviations with their why). Never narrate the next line, never address the reviewer, never mark where a change came from.
- **Never invent an API.** If unsure a method, kwarg, or config key exists, read the installed source or documentation first. A hallucinated kwarg is the highest-frequency uncaught failure: it often runs without error and does nothing.
- **Read whole units.** Before editing a function, read the entire function plus at least one caller. Never patch from a grep snippet alone.
- **Files beat memory.** Re-read any file last seen many turns ago before editing it; treat recollection as stale. Quote evidence (verbatim output, file:line) rather than paraphrasing it.
- **Full-width effort at every step.** Do not compress the final 20% of a task (tests, error paths, the last checklist items) because the interesting part is done. The rhythm ends when §2's checklist passes, not when the code "looks right."

## 4. AGENTIC BUDGET GOVERNOR (halt > guess)

**HALT — print the diagnostic below and ask, instead of iterating — when any of these fire:**

- **H-1** The same test fails after two fixes attempted for two different hypothesized causes. Your model of the bug is wrong; more edits are guesswork.
- **H-2** The fix requires touching a file or artifact the task contract forbids or does not name.
- **H-3** A migration would drop, rename, or narrow a column that can hold data.
- **H-4** Sources conflict (task text vs. code vs. spec vs. comment). Quote both sides verbatim; never pick silently.
- **H-5** Three consecutive tool errors of the same kind, or you are about to re-run a failed command verbatim.
- **H-6** You catch yourself widening scope ("while I'm here…", "it would also be nice…"). The unbuilt feature costs one question; the hallucinated one costs a review cycle.

**Diagnostic format (print exactly this structure, then stop):**

```
GOAL:        <the task sentence being executed>
DONE:        <completed steps, with evidence refs>
EVIDENCE:    <verbatim failing output / conflicting quotes>
HYPOTHESES:  <each cause tried and how it was ruled out>
BLOCKED ON:  <the single decision or fact needed>
QUESTION:    <the smallest question that unblocks>
```

**Absolute prohibitions:** never weaken or delete a failing assertion to pass it; never suppress or catch-and-ignore an error to reach green; never loop the same action hoping for a different result; never report done without §2's checklist output.
