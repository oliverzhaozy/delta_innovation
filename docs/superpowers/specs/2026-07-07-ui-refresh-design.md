# UI refresh — grouped nav, unified parade page, ops-room visual pass

Owner-approved 2026-07-07 (three decisions: dropdown nav groups; parade
documents unified behind URL-backed tabs; full visual refresh). Constraints:
server-rendered Jinja + vanilla JS sprinkles only; document bytes untouched
(parade/RO/manning goldens stay byte-identical — this is ALL page chrome);
every existing route and test keeps working.

## 1. Navigation

The ~18 flat topnav links become one plain link + five rights-gated dropdown
groups (`<details class="navgroup">`, with a ~10-line JS sprinkle so opening
one closes the others and an outside tap closes all):

- **Home**
- **Parade ▾** — Parade state (unified page), Away board, Snapshots,
  Statuses†, Direct absences†
- **Duty ▾** — Duty roster, Routine Orders, Manning†
- **Leave ▾** — My leave†, Approvals (pending badge)†, Overseas declarations,
  Upcoming travel†, Ledger†
- **Calendar ▾** — TP month, ARCTIC FOE†
- **Account ▾** — People†, Meals†, Password, Sign out

† only for roles that may use it (same predicates the routes enforce); a
group whose every item is hidden does not render. The group containing the
current page carries an active style (endpoint-prefix match).

## 2. Unified parade page

`parade/morning.html`, `cos_message.html`, and `roll_call.html` merge into
ONE template, `parade/state.html`: a pill row (Morning · COS message · Roll
call · Away board · Snapshots) + one date switcher + the active document's
chrome. Each pill keeps its own URL (`/parade/morning`, `/parade/cos-message`,
`/parade/roll-call`) — finalize redirects, bookmarks, and the existing suites
keep working; the "tabs" are URL-backed, so no client-side state. Per-doc
chrome renders conditionally: FP quick-add (morning), COS selector (cos),
missing-duty/absent-holder notices (roll call); conflicts panel is shared.
The three routes pass `doc="morning"|"cos"|"roll_call"` to the shared
template. Away board and Snapshots stay their own pages but gain the same
pill row for one-tap flow. *Why URL-backed: the app's whole posture is
server-rendered; a JS tab switcher would be the first stateful UI element.*

## 3. Dashboard

`main/dashboard.html`'s single stale "Your tools" card becomes four
rights-gated cards — Documents & parades, Duty & orders, Leave & travel,
Staff tools — every link live (fixes: Duty roster still tagged "Phase 4";
RO, Manning, Snapshots, Parade state missing).

## 4. Visual refresh — "ops room"

Grounded in the subject (an army company's ops tool, compiled at night on a
phone), keeping SAF green as the identity anchor — a deliberate choice, not a
template default. Tokens only, no font files, no external assets:

- **Type:** condensed uppercase display stack for h1/brand/nav groups
  (`"Avenir Next Condensed", "Arial Narrow", "Roboto Condensed",
  sans-serif-condensed, sans-serif` — evokes stencilled document headers);
  `ui-monospace` with tabular numerals for document `<pre>`s, dates, counts.
- **Surface:** paper shifts to a green-grey (#F1F3F0); cards get thinner
  shadow + 10px radius + crisper 1px line; h2 small-caps kept.
- **Active states:** solid green-800 pill with white text (nav group + pill
  row + date "Today"); no new accent colour — amber/red stay semantic.
- **Signature element — the message sheet:** every document `<pre>`
  (3 parades, RO, manning) renders inside `.sheet`: a bordered white sheet
  with a top rule carrying the doc label + date and the Copy button anchored
  right — visually the WhatsApp artifact being produced. `<pre>` CONTENT is
  untouched.

## Testing

- All 553 existing tests stay green (the template merge preserves every
  probed string: `<pre>` ids/content, form actions, notice text).
- New: pill row present with correct active pill on all three parade URLs;
  nav groups rights-gated (Opr sees no Staff-only entries; group hidden when
  empty); dashboard link integrity (every `url_for` resolves — rendering the
  page IS the test).

## Cut (deliberately)

Time-aware default tab; JS tab switching; restyling the login page beyond
tokens; dark mode; per-section pill rows outside Parade.
