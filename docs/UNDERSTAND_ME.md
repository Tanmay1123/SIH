# Understand Me — a complete walkthrough of CodeNova

This document assumes you can program but know nothing about this project, GST,
or fraud detection. Read it top to bottom and you will understand what was
built, why each piece exists, and where the weak points are.

> **Not a programmer, or short on time?** There is a companion document that
> explains every part of the backend with no maths and no jargon:
> [10-year-old explanation of all the backend that is happening.md](10-year-old%20explanation%20of%20all%20the%20backend%20that%20is%20happening.md).
> Same content, different register.

---

## 1. The problem, in plain language

When a business in India buys goods, it pays GST on that purchase. It can later
claim that amount back from the government — that refund is called **Input Tax
Credit (ITC)**. The system assumes the purchase was real.

Fraudsters exploit that assumption. They register a handful of shell companies
and have them invoice each other in a closed circle: company A bills B, B bills
C, and C bills A. No goods ever move. But on paper every company now has
"purchases" it can claim ITC against, so all of them apply for refunds on tax
that was never really paid.

The reason this is hard to catch is that **every single invoice looks
legitimate**. The GSTIN is valid, the amounts add up, the filing is on time.
Existing government checks compare a seller's declared sales (GSTR-1) against a
buyer's claimed purchases (GSTR-3B) and flag mismatches — but in a well-run ring
there is no mismatch, because both sides of every fake invoice are filed
consistently by people working together. The fraud is invisible in any single
record. It is only visible in the **shape of the network**: value that leaves a
company and comes back to it.

---

## 2. Why synthetic data

Real GSTN invoice data is confidential taxpayer information. It is not on any
public portal; access requires government data-sharing agreements. There is no
legitimate way for a hackathon team to obtain it, and fabricating a connection
to a real government API would be dishonest.

So this project generates its own trade network. That turns out to be a genuine
advantage rather than a compromise:

- **The ground truth is known.** We know exactly which companies are shells, so
  we can measure whether the detector finds them, rather than just asserting
  that it works.
- **Hard cases can be manufactured on purpose.** The generator injects benign
  loops specifically designed to fool a naive detector (see §5).
- **It is reproducible.** Same seed, same network — so a result can be checked.

### Two generators, because they have different jobs

`backend/fraud_engine/synthetic_network.py` is **training tooling**. Its
consumer is the XGBoost trainer and the test suite, so it optimises for one
thing: a clean fraud/not-fraud split with enough hard cases that the model
cannot cheat. It never touches the running application's database.

`backend/fraud_engine/dataset_lab.py` — the **Dataset Lab**, §5b — is for
**people**. Its consumers are demos, screenshots and end-to-end testing, and
what makes those useful is a *spread*: a dataset where every alert scores 95
tells you nothing about whether the queue is usable, and neither does one where
every alert scores 8. So the lab plants four explicit bands and then reports
back what the real detector made of each.

Both are fabricated; neither is ever used to seed the app behind an officer's
back. The application starts empty and only ever holds a dataset somebody
uploaded — and data from the lab goes in through `core.csv_import.load_dataset`,
exactly the same validated path an officer's upload takes. Nothing in the
pipeline is hardcoded to fabricated data, so a real (companies, invoices)
dataset runs through the same code unchanged.

---

## 3. Architecture and data flow

```
   ┌──────────────────────────────────────────────────────────────┐
   │  Officer logs in, uploads companies.csv + invoices.csv       │
   │  (core/csv_import.py validates it, stores it as a Dataset)   │
   │  Each upload is kept. One dataset is "active" at a time.     │
   └──────────────────────────┬───────────────────────────────────┘
                              │ writes
                              ▼
                    ┌────────────────────────────┐
                    │        PostgreSQL          │
                    │ Dataset, Company, Invoice  │
                    └─────────┬──────────────────┘
                              │ read (scoped to the active dataset)
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  pipeline.py — one pass = one named, dated DetectionRun      │
   └──────────────────────────┬───────────────────────────────────┘
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  graph_builder.py                                            │
   │  companies -> nodes, invoices -> directed edges               │
   │  (invoices between the same pair collapse into ONE edge)     │
   │  PLUS control edges: shared director / registered address    │
   └───────────────┬──────────────────────────┬───────────────────┘
                   ▼                          ▼
   ┌───────────────────────────────┐  ┌───────────────────────────┐
   │ cycle_detection.py            │  │ mill_detection.py         │
   │ Stage 1: Tarjan SCC           │  │ NON-LOOP fraud: a shell   │
   │ Stage 2: Johnson's            │  │ selling to many buyers    │
   │ Loops closed by an invoice OR │  │ and buying from nobody.   │
   │ by shared ownership           │  │ A star, not a cycle.      │
   └───────────────┬───────────────┘  └─────────────┬─────────────┘
                   ▼                                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  risk_scoring.py            │  rule-based mill scoring       │
   │  17 features -> XGBoost     │  6 named signals, each with    │
   │  SHAP -> plain-English      │  its own sentence              │
   └──────────────────────────┬───────────────────────────────────┘
                              ▼
                    ┌───────────────────┐
                    │ FlaggedRing rows  │◄──── officer reviews in the UI
                    │ RiskScore rows    │
                    └─────────┬─────────┘
                              │
              ┌───────────────┴────────────────┐
              │                                │
     "Confirm as fraudulent"            "Not fraud"
              │                          + reason code
              ▼                                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  ledger.py — SHA-256 hash chain                              │
   │  block N stores hash(content + hash of block N-1)            │
   │  Three record types: confirmations, dismissals, and issued   │
   │  case reports. Each carries the model version + threshold     │
   │  that produced the score the officer acted on.               │
   └──────────────────────────┬───────────────────────────────────┘
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  reporting.py + mailer.py                                    │
   │  One-page case report -> the officer and their supervisor    │
   │  Its content hash goes into the ledger too                   │
   └──────────────────────────┬───────────────────────────────────┘
                              ▼
                    Django REST Framework API
                              ▼
              React dashboard (Cytoscape + Tailwind)
```

The pipeline is **synchronous end to end**. There is no Celery, no Redis, no
worker process. Cycle detection on this network takes about 3 milliseconds and
scoring about two seconds, so an HTTP request can just do the work and return.
A test (`test_detection_is_fast_enough_to_run_synchronously`) asserts this stays
true; if it ever fails, that is the signal that the no-queue decision needs
revisiting.

---

## 4. Walking through the code

### `backend/core/` — the base data model

Three tables, because the whole problem only needs three.

- **`models.py`** — `Dataset` (one upload, kept permanently), `Company` (GSTIN,
  PAN, name, director, registered address, registration date, declared
  turnover) and `Invoice` (seller FK, buyer FK, amount, date, goods
  description, `has_eway_bill`). A company is a node; an invoice is a directed
  edge. `director_name` and `registered_address` are indexed because the
  feature pipeline groups on them to find shell factories — and the graph
  builder now turns them into edges outright (§6b). GSTIN is unique **per
  dataset**, not globally: the same taxpayer legitimately appears in two
  different uploads.
- **`serializers.py` / `views.py` / `urls.py`** — read-only REST endpoints for
  companies and invoices, dataset upload / list / activate / rename / delete,
  and auth (login/logout/whoami). Company detail also carries the latest risk
  score, its explanation, and which alerts it appears in.
- **`csv_import.py`** — parses and validates an officer-uploaded CSV pair and
  loads it as a new `Dataset` in one transaction, then makes it active. The
  only path by which data enters the application. It deletes nothing: previous
  datasets, their detection runs and the audit ledger all survive.
- **`management/commands/setup_accounts.py`** — creates the team's logins with
  their roles attached, idempotently. `createsuperuser` makes one account with
  no role; a department needs several, and a team needs to recreate them
  identically on another laptop. Existing accounts have name, email and role
  brought into line but keep their password unless `--reset-password` is
  given — silently changing a password is a lockout, not an update. It also
  refuses to demote a superuser to officer, because `roles.py` treats a
  superuser as a supervisor regardless and the two would then disagree.
- **`management/commands/reset_data.py`** — deletes every case record and keeps
  `auth_user`, which is what makes it useful before a demo and different from
  `flush`. Requires `--yes`.

### `backend/fraud_engine/` — everything detection-related

- **`pipeline.py`** — the orchestrator. One call produces one `DetectionRun`:
  build the graph, run both detectors, score, store, roll up the counters. The
  two-graph decision lives here (§6b), as does carrying officer decisions
  forward between runs so nobody re-reviews work they already did.
- **`graph_builder.py`** — reads the active dataset into two pandas DataFrames
  and builds a NetworkX `DiGraph`. All invoices between the same pair of
  companies collapse into a single edge carrying totals (value, invoice count,
  how many lacked an e-way bill, date range). Cycle-finding only cares
  *whether* a trade relationship exists, so collapsing thousands of invoices
  into a couple of thousand edges is free speed. It works on DataFrames rather
  than Django objects so the exact same code can run on
  generated-but-never-saved data during training. It also adds **control
  edges** — §6b.
- **`cycle_detection.py`** — the two-stage search. Explained in §6.
- **`mill_detection.py`** — fraud that is not a loop at all. §6c.
- **`risk_scoring.py`** — features, model training, inference, SHAP. §7 and §8.
- **`ledger.py`** — the hash chain. §9.
- **`reporting.py`** — the supervisor's one-page case report. §10.
- **`mailer.py`** — delivers it, and records a failure rather than raising, so
  a misconfigured mail server is something an officer can see and retry.
- **`settings_helpers.py`** — the risk threshold and the supervisor recipient
  list, read from settings rather than hardcoded in two files.
- **`models.py`** — `DetectionRun`, `FlaggedRing`, `RiskScore`, `LedgerBlock`,
  `CaseReport`.
- **`views.py` / `urls.py` / `serializers.py`** — the API.
- **`tests.py`** — 111 tests in thirteen classes, one per concern.
- **`models_artifacts/`** — the committed pretrained model (`risk_model.json`
  plus `feature_meta.json`). Committed on purpose so a fresh clone can score
  immediately. Stored as XGBoost's native JSON rather than a pickle, which
  keeps it small, inspectable and portable across library versions.
- **`synthetic_network.py`** — the trade-network generator that feeds the
  trainer, described in §2. Used only by `tests.py` and `train_risk_model.py`;
  never touches the running application's database.
- **`dataset_lab.py`** — the Dataset Lab generator (§5b). Builds a network with
  a controllable risk mix plus an answer key, and can run the real pipeline over
  its own output so the generator does not get to mark its own homework.
- **`lab_views.py`** — the lab's API. `presets`/`preview`/`download` are open
  (they read nothing and produce only fabricated CSV text); `load` writes rows
  and is authenticated.
- **`management/commands/train_risk_model.py`** — optional retraining.

### `frontend/src/`

- **`api.js`** — one Axios instance, an auth-token request interceptor, and
  every API call the app makes.
- **`App.jsx`** — the router. `/lab` is matched *before* the auth gate, so the
  Dataset Lab is reachable signed out; everything else falls through to `Gate`,
  which shows `Login` or the routed console. It also owns the shared
  status/alerts/graph triple, fetched once here rather than per page — three
  pages read from it, and refetching on navigation would rebuild the Cytoscape
  graph every time, which is both slow and visibly jarring. Owns the `useTheme`
  hook at the top of the tree so the chosen theme is already applied on the
  login screen, before there is a console to render at all.
- **`useTheme.js`** — dark/light mode as a small hook: reads/writes a
  `localStorage` key, toggles the `dark` class on `<html>`, and defaults to
  dark. Tailwind is configured with `@custom-variant dark
  (&:where(.dark, .dark *))` in `index.css` so `dark:` utilities key off that
  class instead of the OS-level `prefers-color-scheme` media query — the
  in-app toggle overrides the OS setting rather than fighting it.
- **`icons.jsx`** — small dependency-free inline SVG icons (sun, moon, menu,
  upload, trash, close, file), used instead of pulling in an icon package.
- **`Login.jsx`** — the officer sign-in page.
- **`lab/LabPage.jsx`, `lab/labApi.js`** — the Dataset Lab (§5b). Kept in its
  own directory with its **own** Axios client, deliberately: the console's
  client tears the session down on any 401, which is right for a case file and
  wrong here, where the only endpoint that can 401 is "load into the console"
  and the answer is a sentence for the user, not a logout.
- **`App.jsx`** — the router, plus the one piece of shared state. The
  status/alerts/graph triple is fetched here rather than per page, because
  three pages read from it and refetching on every navigation would rebuild the
  Cytoscape graph each time — slow, and visibly jarring given the graph has a
  deliberate reveal animation.
- **`useAuth.jsx`** — the signed-in account, its role, and a permissions map
  that comes *from the server* rather than being inferred in the browser, so
  there is exactly one definition of who can do what.
- **`layout/AppShell.jsx`** — the application frame: a collapsible navigation
  rail, a context bar carrying the active dataset and the account, and the
  routed page. Everything used to live on one screen behind three tabs, with
  the dataset switcher, nine counters, two buttons and the account competing
  for one header strip. Splitting it into routed pages is what makes it
  navigable rather than merely dense.
- **`layout/UserMenu.jsx`** — the account control: who you are, your role, what
  that role permits, links to your profile and settings, and sign out.
- **`pages/`** — Overview (where you land: counters and the top of your queue),
  Network (the three-pane investigation screen), Detections (run history,
  upload, run), Reports, Ledger, Team (supervisor-only) and Settings.
- **`components/ui.jsx`** — shared primitives. These exist so spacing, radius,
  weight and colour are decided once instead of being re-improvised on every
  screen, which is what makes an interface look assembled rather than designed.
- **`components/AlertsFeed.jsx`** — the ranked work queue on the left.
  Collapsible: a lines icon at its top toggles it down to a slim strip and
  back, for when the graph needs the screen space. Alerts carry a shape icon
  (loop vs star) so rings and mills are distinguishable at a glance, a badge
  when a ring closes through shared ownership, and filter chips for
  *to review / all / confirmed / cleared*. It opens on **to review**, because
  that is the officer's actual queue.
- **`components/DatasetPicker.jsx`** — the dataset switcher in the header.
  Lists every upload with its counts and run count; click to activate,
  double-click to rename.
- **`components/ReportsView.jsx`** — the **History & reports** tab. Detection
  runs on the left with a review-progress bar and their model provenance;
  issued case reports on the right with their content hash, ledger block and
  delivery status. A report can be previewed exactly as the supervisor
  receives it, rendered in a sandboxed iframe so its inline email styles cannot
  leak into the console.
- **`components/GraphView.jsx`** — the Cytoscape network view, deliberately
  built to match how Obsidian's graph view actually *works*, not just how it
  looks (researched from Obsidian's own graph-view documentation rather than
  guessed at). The mechanics, in order of how much they matter:
  - **Zoom-relative label fade.** Node labels start at `text-opacity: 0` and
    fade in only as you zoom past a threshold computed relative to the
    zoom-to-fit level, driven by a `zoom` event handler (`updateLabelFade()`).
    This is the part that actually solves the readability problem: with ~250
    companies on screen, showing every label simultaneously is unreadable no
    matter how small the dots are made. Zoomed out you see shape only; zoom
    into a cluster and its names become legible.
  - **Degree-based node size.** A node's size is driven by
    `node.degree(false)` — how many distinct companies it has traded with —
    the same "more links, bigger node" rule Obsidian applies to notes, with a
    modest extra multiplier for a confirmed high risk score.
  - **No arrowheads.** Plain thin straight edges only; direction is shown in
    the evidence panel's numbered loop list instead, where it is actually
    legible, rather than as tiny arrows lost in a dense graph.
  - **A calm staggered reveal**, not a visible physics simulation: the cose
    layout runs once, instantly (`animate: false`) with every element hidden,
    then nodes fade in in small batches ordered by a BFS traversal (so a
    cluster of trading partners ripples in together), with edges fading in
    once both endpoints are visible.
  - **A selected ring's labels are forced visible at any zoom level** —
    including fully zoomed out — via an inline `text-opacity` override, with
    a resync back to the zoom-driven value on deselection.
  - Spacing (`nodeRepulsion`, `idealEdgeLength`) scales with node count, so a
    20-node ring-only view and the full ~250-node network each get
    proportionate room to spread out.
- **`components/CompanyDetail.jsx`** — the evidence panel and **both** review
  actions. Confirming and clearing sit side by side deliberately (§8b);
  clearing opens a small form requiring a reason code. For a mill alert it
  shows the numbers behind the score — sales vs purchases, buyers vs
  suppliers — and says in plain words that this is not a loop and why cycle
  detection could not have found it.
- **`components/LedgerViewer.jsx`** — blocks and chain verification status.
  Each block is badged by record type (confirmed / cleared / report issued) and
  summarised accordingly, with the model version and threshold underneath.

---

## 5. How the synthetic network is built (and why its shape matters)

This is the most important design decision in the project, and the least
obvious.

**Legitimate trade is generated as a DAG.** Every honest company is assigned a
supply-chain tier — 0 raw material, 1 component maker, 2 distributor, 3 retailer
— and invoices only ever flow to a strictly higher tier. Because the tier always
increases, the honest sub-graph *mathematically cannot contain a cycle*. That
mirrors reality (supply chains flow one way) and it means cycle detection has
almost nothing to chew through.

**Value flows with margin, not randomly.** A tier-2 distributor's sales budget
is what it actually purchased, times a margin drawn between 0.98 and 1.45. This
matters more than it sounds. An earlier version drew each company's sales and
purchases independently, which made every honest mid-chain company look wildly
unbalanced and handed the model a free giveaway feature. Some margins land at or
below 1.0 on purpose: commission agents and consignment traders genuinely do
pass value straight through, and they are precisely the honest businesses most
easily mistaken for conduits.

**Honest turnover declarations are rewritten to match reality.** After invoices
are generated, each legitimate company's `declared_turnover` is set to what it
actually traded, times 0.85–1.2. Shell declarations are left alone — declaring a
few lakh while pushing crores through the books *is* the fraud.

**Benign loops are injected deliberately.** Three kinds:
1. A retailer selling returns and scrap back to its own distributor (2-cycles).
2. Two distributors genuinely trading both ways at comparable volume — the
   hardest honest case in the dataset, since the flow is balanced and the loop
   is tight, structurally almost identical to a shell pair.
3. Three to five retailers doing mutual stock transfers (3- to 5-cycles).

Without these, "is in a cycle" would perfectly predict fraud, the ML stage would
be a rubber stamp, and the system would flag every honest business that happens
to trade both ways. They exist to make the problem real.

**Fraud rings** are 3–6 shell companies with a closed loop of invoices, carrying
the fingerprints investigators actually look for: shared registered addresses
and directors, invoice value far above declared turnover, missing e-way bills,
near-identical amounts circling the loop, recent registration, round-figure
amounts. About 30% are generated as "hard" rings that hide several of these
tells, so the model cannot rely on any single one.

**Honest companies vary too**, on purpose: ~14% are genuinely new businesses,
~18% have poor e-way bill compliance, ~30% are seasonal and concentrate their
invoicing into one window. Each of these blunts a feature that would otherwise
separate the classes perfectly for the wrong reason.

The result: **every one of the 17 features has at least 24% overlap between
fraudulent and honest companies.** No single column decides the answer. The
model has to combine evidence, which is what makes the explanations meaningful.

---

## 5b. The Dataset Lab

*`backend/fraud_engine/dataset_lab.py`, `lab_views.py`,
`frontend/src/lab/`. Served at `/lab`.*

§5 describes the generator that trains the model. This is the other one, and it
exists because a training generator makes bad demo data.

### The four bands

The lab plants companies in four explicit bands, and the band is a statement
about *how it was built*, never a promise about the score it will receive:

| Band | Built as | Purpose |
|---|---|---|
| `high` | Textbook rings and textbook mills. Every tell present | should be caught |
| `medium` | Real loops and real lopsided sellers with one or two flags each | the queue's hard half |
| `low` | Genuine two-way traders, distributor pairs, retailer triangles | **must not** be caught |
| `clean` | Tiered supply-chain trade | background |

The `low` band carries the weight. A generator that only plants obvious fraud
produces a detector that looks excellent and is useless. The honest look-alikes
form real cycles, so cycle detection alone flags every one of them — which is
exactly the mistake the risk model exists to prevent, and the only way to know
whether it is actually preventing it.

The `medium` band is what makes the queue realistic. Grey rings are three to
five companies **two to six years old**, filing 45–78% of their e-way bills,
declaring 40–75% of what they invoiced, with hop amounts spread ±35% rather than
repeating to the rupee, and at most one shared director between two members —
never a shared address. Borderline sellers clear the mill detector's gates but
score either side of its reporting threshold on purpose: some of them are meant
to go unreported, because that is what the threshold costs, and being able to
watch it cost something is the point of planting them.

### `analyse()` — the generator does not mark its own homework

The interesting half of the module is not generation, it is
`dataset_lab.analyse()`. It runs the **real** pipeline over the generated data,
in memory, with nothing written to the database: the same `graph_builder`, the
same two-graph split from §6b, the same Tarjan/Johnson, the same
`mill_detection` rules and the same XGBoost model.

It then reports two different things side by side:

- **what was planted**, from the answer key
- **what was found**, from the pipeline — the score distribution, how many
  planted groups were surfaced, and how many `low`/`clean` companies were pushed
  over the risk threshold

Reporting only the first would be marking our own homework. The false-alarm
count is the number that keeps the lab honest, and it is displayed as
prominently as the recall.

One attribution detail matters: a mill alert lists the mill first and then every
company that bought from it. Those buyers are mostly honest businesses that were
sold a fake invoice, so crediting the alert to *their* planted group would be
wrong — the accusation is against the seller alone, and `_alert_row` uses
`mill_company_id` rather than the full member list for exactly that reason.

### A bug this design caught

The lab's `dataframes()` turns CSV-shaped rows into the frames the pipeline
reads. CSV carries `has_eway_bill` as the string `"true"`/`"false"`, and the
first version handed those to pandas as-is. `mill_detection` does
`~invoices["has_eway_bill"].astype(bool)` — and **every non-empty string is
truthy**, so `"false"` read as `True`, no invoice ever counted as missing an
e-way bill, and twenty of the mill score's hundred points were silently dead.
Textbook mills capped out around 57 instead of 90.

The preview was under-reporting relative to a real upload, which is precisely
the class of bug a preview must not have. It is now parsed with
`core.csv_import.TRUE_STRINGS` — the importer's own rule, so the preview
interprets the file exactly as the importer will — and
`test_eway_flags_survive_the_round_trip_to_dataframes` guards it.

A second bug came out of `test_no_invoice_predates_either_party`: trading
windows are derived from the group being planted, but counterparties are drawn
from the wider economy where ~14% of companies are brand new, so a mill happily
invoiced a company that would not exist for another three months. Clamped
centrally in `_Context.add_invoice` rather than at each call site.

### Why the endpoints are open

`presets`, `preview` and `download` are `AllowAny`. They read nothing from the
database — no company, invoice, alert or officer decision is reachable from
them — and produce only fabricated CSV text. Putting the tool that fills an
empty console behind that console's login is a circle.

`load` writes rows, so it is authenticated, and it goes through
`core.csv_import.load_dataset` rather than writing `Company` objects directly.
Generated data gets no shortcut past the importer: if the generator ever emitted
something an officer's upload would be rejected for, that call is where it
fails.

Size is clamped, not refused (`LabSpec.clamped()`): generation runs
synchronously inside a request and cycle enumeration is the expensive part, so
the ceiling is 1,200 companies and 25 groups of each kind.

### Why it looks different

The lab has no nav rail, no dataset picker, no officer and no case. It has a
graph-paper header, an amber accent instead of the console's institutional
green, and a "fabricated data" badge in its title bar. That separation is
functional, not decorative: every number on that page is invented, and nothing
on it should ever be capable of being screenshotted and mistaken for a finding
about a real business.

---

## 6. How cycle detection works, in words

We need every closed loop A → B → C → A in a graph of ~220 companies and ~1,200
trade relationships. Done naively — walking every path from every company and
checking whether it returns home — this is hopeless: the number of paths grows
factorially.

It is done in two stages.

**Stage 1: Tarjan's strongly connected components — the pre-filter.**

A *strongly connected component* (SCC) is a group of nodes where every node can
reach every other node. The key insight: **a cycle can only exist inside a
single SCC.** If A and B are both on one loop, then A can reach B (going
forward round the loop) and B can reach A (continuing round) — which is exactly
what it means to be in the same SCC.

Tarjan's algorithm finds every SCC in one linear pass, O(V + E). In a healthy
trade network almost every company sits in an SCC of size 1, because supply
chains flow one way and never come back. So this single cheap pass discards the
overwhelming majority of the graph before any expensive work begins. In our
network, ~220 companies collapse to a handful of small components, together
holding maybe 76 companies.

**Stage 2: Johnson's algorithm — the enumeration.**

Johnson's algorithm lists every *simple* cycle (one that never repeats a
company) in a directed graph. Its cost is O((V + E)(C + 1)) where C is the
number of cycles it actually finds. The important property is that it does no
work proportional to cycles that don't exist — it never explores a dead end
twice, because once a node is shown to lead nowhere useful it is "blocked" until
something changes. We run it **only inside each surviving SCC**, which are tiny.

**The length bound.** The number of simple cycles in a dense graph grows
factorially, so an unbounded search on a pathologically dense component could
run effectively forever. Real ITC rings are short — the entire point is to
return the credit to the originator quickly — so ring length is capped at 6 by
default (`settings.MAX_RING_SIZE`). Small components get the exact unbounded
search and are filtered afterwards; components above a size threshold get the
bound pushed down into the search itself, so it can never blow up.

**De-duplication.** `[A,B,C]`, `[B,C,A]` and `[C,A,B]` are the same ring seen
from different starting points. Each cycle is rotated so its lowest company ID
comes first, giving one canonical form per ring.

**The output is candidates, not verdicts.** This stage finds ~33 loops, of which
only 7 are fraud. It has narrowed 220 companies to 33 things worth looking at.
Deciding which of the 33 are real is the next stage's job.

---

## 6b. Rings that close through ownership, not through an invoice

An evaluator asked the sharpest question we have had: *what about companies
committing fraud without forming a loop?* The honest answer was that we would
miss them. This section and the next are what closes that gap.

**The pattern.** Consider A → B → C by invoice, where C and A share a
registered address, or a director. That **is** a circular-trade ring. The loop
closes through *control* rather than through a bill — and that is the smarter
way to run the fraud, precisely because it leaves no closing invoice for a
cycle detector to find. With invoice edges alone it looks like an innocent
supply chain.

**The fix is cheap because the data was already there.** We already computed
`shared_address_count` and `shared_director_count` as feature *numbers*. Now
`graph_builder._add_control_edges()` also puts them in the graph as **edges**,
marked `relation="control"` and bidirectional (control is not directional: if
two companies are run by the same person, value can move either way without an
invoice). Tarjan and Johnson then find these rings with no other change.

**Two rules keep it honest.** A reported cycle must contain:

- **at least one invoice hop** — otherwise a group of companies sharing an
  address would register as a "ring" purely for being co-located, which says
  nothing at all about trade;
- **at most one control hop** (`MAX_CONTROL_HOPS`) — the pattern we are hunting
  is a chain of real invoices that closes once through ownership. Several
  control hops means we are looking at an address cluster, not a trade cycle.

A third guard sits in `_add_control_edges` itself: a shared address or director
that links more than `MAX_SHARED_GROUP_SIZE` companies is skipped. A group that
large is almost always a data artefact — "Address not available", a filing
agent, a common-services provider — and linking every pair inside it would add
thousands of meaningless edges.

Finally, a real trade edge is **never downgraded** to a control edge. If A
already sells to B, that stays an invoice relationship; the shared detail is
recorded on it as extra evidence.

### The methodological catch, and how it is handled

The risk model's four cycle features (`in_cycle_count`, `min_cycle_length`,
`min_cycle_amount_cv`, `max_cycle_value_log`) were learned on a **pure invoice
graph**. Feeding it cycle counts inflated by control edges would be scoring
outside its training distribution: the numbers would move for a reason the
model has never seen, and the scores would stop meaning what they claim.

So `pipeline.py` builds **two graphs**. Features come from the invoice-only
graph, exactly as at training time. Reported alerts come from the
control-augmented one. The score stays honest and the extra rings still get
surfaced. This is the kind of detail that is easy to get silently wrong, so it
is called out in a comment at the point where it happens.

---

## 6c. Fake invoice mills — fraud with no loop at all

The bigger blind spot, and probably the most common form of real GST fraud in
India.

**The name**, since it trips people up: a flour mill churns out flour all day;
this churns out invoices all day. The product is paperwork. Nothing more
metaphorical than that is meant by it.

**The pattern.** A shell company exists only to issue invoices. It sells to
dozens of unrelated real businesses who want input credit to claim, and it buys
from almost nobody, because nothing it "sold" ever existed. Then it stops
filing and disappears.

That is a **star**, not a loop. There is no cycle. Tarjan and Johnson will
never see it, however well tuned they are. It needs its own detector, and
`mill_detection.py` is it.

**How it works.** Three gates decide what is even worth looking at — at least
`MIN_BUYERS` distinct buyers, sales at least `MIN_SALES_MULTIPLE` times
purchases, and sales above `MIN_SALES_VALUE` (a tiny lopsided company is a
small business, not a fraud operation worth an officer's time). Anything
passing the gates is scored on six weighted signals:

| Signal | Weight | What it means |
|---|---|---|
| `one_way_flow` | 30 | Sells a lot, buys nothing — it never acquired what it sold |
| `eway_missing` | 20 | Paper moved, goods did not |
| `buyer_spread` | 18 | Many unrelated customers, almost no suppliers |
| `young` | 12 | Registered recently but already invoicing at volume |
| `under_declared` | 12 | Declares a fraction of what it invoices |
| `round_amounts` | 8 | Figures written by hand rather than priced |

### Why this is rules and not a model — deliberately

The XGBoost model is trained on labelled shells that sit **inside generated
rings**. It has never seen a labelled mill. Asking it to score one would be
inference far outside its training distribution: a confident number with
nothing behind it.

So this detector is explicit on purpose. Named signals, stated weights, and one
plain-English sentence per signal, so every score reads back as the reasons
that produced it. It is honest about what it is, and it is a real baseline: once
officer decisions have accumulated enough confirmations and dismissals on mill
alerts — which is exactly what the review loop in §8b now collects — these
rules become the thing a learned model has to beat.

---

## 7. The risk features, and why each one signals fraud

The model scores **only companies that cycle detection surfaced**. A company in
no loop is not a circular-trade suspect and is reported at zero risk rather than
run through a model that never trained on such companies. (An earlier version
scored everyone and hit a perfect AUC — by simply relearning the graph stage's
output from the sentinel values non-loop companies carry. Impressive number,
zero information.)

**Registration and identity**

| Feature | Why it signals fraud |
|---|---|
| `days_since_registration` | Shells are young. They are created, used to churn credit for months, then abandoned before scrutiny arrives. |
| `shared_address_count` | How many *other* companies share this registered address. A dozen unrelated firms at one address is a shell factory. |
| `shared_director_count` | Same logic for directors. Rings reuse people because each new identity is friction. |
| `declared_turnover_log` | Shells declare small to stay under reporting thresholds. |

**Money flow**

| Feature | Why it signals fraud |
|---|---|
| `turnover_to_invoice_ratio` | Declared turnover ÷ total invoice value on the books. Honest businesses declare roughly what they trade; a shell declares lakhs while pushing crores. Uses *both* sales and purchases — dividing by sales alone would make every honest retailer look like a shell. |
| `itc_velocity` | Purchases per day since registration. A three-month-old company that has booked crores is accumulating credit faster than a real supply chain could generate it. |
| `pass_through_ratio` | \|sales − purchases\| ÷ total flow. Real firms add margin and hold stock, so the sides differ. A conduit has money in = money out, pushing this to zero. |
| `sales_value_log`, `purchase_value_log` | Raw scale, providing context for the ratios. |

**Invoice hygiene**

| Feature | Why it signals fraud |
|---|---|
| `eway_missing_ratio` | An e-way bill accompanies an actual goods movement. Invoices without one are the clearest sign that paper moved but goods did not. |
| `round_amount_ratio` | Fabricated invoices are written by a person picking a number, so they cluster on round figures far more than genuinely priced transactions. |
| `invoice_burst_ratio` | Largest share of a company's invoices inside any 30-day window. Rings churn their book fast then go quiet; honest trade spreads out. |
| `counterparty_count` | Distinct trading partners. Shells deal mostly with each other. |

**Loop geometry** (shared by fraudulent *and* benign loops, so these narrow the
field without giving the answer away)

| Feature | Why it signals fraud |
|---|---|
| `min_cycle_amount_cv` | Coefficient of variation of the amounts around the loop. **The most conceptually important feature.** Real trade adds margin at every step so amounts vary; fraudulent circular billing passes nearly the same figure around, driving this towards zero — value is circulating, not being created. |
| `min_cycle_length` | Shorter loops return credit to the originator faster. |
| `in_cycle_count` | How many loops the company sits in. |
| `max_cycle_value_log` | Value circulating in the largest loop it belongs to. |

**The model.** XGBoost gradient-boosted trees, weighted to compensate for shells
being a minority. Output probability × 100 becomes the 0–100 company risk score.
A **ring's** score is the *mean* of its members' scores, not the max: a ring is a
conspiracy, so what matters is that the whole loop looks wrong. One suspicious
company inside an otherwise ordinary loop is far more likely to be coincidence.

**Held-out performance:** ROC AUC 0.9999 on two entire networks the model never
saw. On the demo dataset, all 7 injected rings score 88–99.7 and rank above all
26 benign loops, the highest of which scores 12.5. Read §13 before quoting that
number as evidence of real-world accuracy.

---

## 8. How the explanations work

A risk score nobody can interrogate is not usable evidence. An officer about to
start recovery proceedings against a real business needs to know *why*.

After scoring, **SHAP** (SHapley Additive exPlanations) computes how much each
feature pushed each company's score up or down. SHAP comes from cooperative game
theory: it asks, across all possible orderings of the features, how much does
adding *this* feature change the prediction on average? That fairly attributes a
single prediction to its inputs, rather than reporting which features matter
in general.

`risk_scoring.py` then converts the top contributions into sentences. Not
`eway_missing_ratio = 0.56` but:

> ▲ 56% of its invoices moved with no e-way bill, so paper changed hands but
> there is no record of goods actually moving.

Both directions are reported, so exonerating evidence shows too:

> ▼ An established taxpayer, registered 3,496 days ago.

A ring's explanation aggregates SHAP impact across its members and quotes the
member sentence that best represents each of the strongest factors.

---

## 8b. The review loop — letting the system be told it is wrong

This is the change that matters most, and it is the smallest.

**What was missing.** The application had a "Confirm as fraudulent" button and
nothing else. An officer could tell the system it was **right**. There was no
way to say *"I looked at this and it is a normal business."* The consequences
compound:

- no negative examples were ever collected;
- precision could not be measured, only asserted;
- and the model could never improve, because nothing ever corrected it.

**What exists now.** Every alert has three states — `pending`, `confirmed`,
`dismissed` — and both actions sit side by side in the evidence panel.
Dismissing requires a **structured reason code**:

| Code | Meaning |
|---|---|
| `genuine_trade` | Genuine two-way trade |
| `not_circular` | Shell company, but not a circular ring |
| `already_open` | Already under investigation |
| `insufficient` | Insufficient evidence to act |
| `data_quality` | A data problem, not fraud |
| `other` | Something else, see the note |

The reason codes are the useful part. If half the dismissals say "genuine
two-way trade", that is a **specific, fixable model failure** — probably the
benign-loop features are underweighted — rather than a vague sense that
precision is poor. The reasons are, in other words, a diagnostic dataset about
the detector itself.

**Dismissals go into the ledger too.** Clearing a taxpayer is a decision about a
real business just as much as confirming one is, and the record that an
allegation was examined and dropped belongs in the audit trail. A department
should be able to show what it decided *not* to pursue, and why, and who
decided it.

**Decisions carry forward.** `pipeline._carry_forward_decisions()` keys prior
verdicts by the alert's order-independent signature, so re-running detection
over the same dataset does not ask anyone to review the same ring twice.

**Two guard rails.** `mark_confirmed()` and `mark_dismissed()` are the only
ways to change state, so `status` and the older `officer_confirmed` flag can
never disagree. And a confirmation, once written to the ledger, cannot be
reversed through the dismiss endpoint — it can only be superseded by a new
decision, which appends rather than edits.

**Nothing in this system ever auto-blocks a refund.** Every enforcement action
remains a human decision. The machine does the watching; the officer does the
deciding.

---

## 8b-2. Roles: who is allowed to decide

The review loop needed one more thing to be honest: not everyone should be able
to make every decision.

**Two roles, split at the point of real consequence.**

    OFFICER     upload data, run detection, review alerts, CLEAR an alert as
                not fraud, issue case reports.
    SUPERVISOR  everything above, plus CONFIRM an alert as fraudulent, see
                every officer's activity, and change detection policy.

**Why the line falls exactly there.** Confirming an alert is the act that
starts recovery proceedings against a real business. It is the one decision
that warrants a second, more senior pair of eyes, and it mirrors how GST
enforcement genuinely works: an officer builds a case, a superior sanctions it.

Clearing deliberately stays with the officer. Being able to say *"I looked, this
is a normal business"* is the feedback the detector needs (§8b), and gating it
behind a supervisor would mean it simply never happens — the queue would fill
up and the model would keep learning nothing.

**Where the rules live.** `core/roles.py` answers who is what;
`core/permissions.py` is the DRF class that enforces it. Membership is a Django
Group, so it is administered from `/admin/` or the in-app Team page with no code
change. Two safety rails: a superuser is always a supervisor (otherwise the
account made by `createsuperuser` could lock itself out of confirming anything),
and a supervisor cannot demote themselves.

**The UI knows, but does not decide.** `/api/auth/me/` returns a permissions map
that the frontend reads to avoid showing an action that would only be refused —
an officer sees the confirm button disabled with a sentence explaining why,
rather than a button that fails. Every one of those rules is still enforced
server-side and tested independently: `RoleTests` asserts that an officer's
POST to the confirm endpoint returns 403 and leaves the alert pending.

### The Team page

The reason the supervisor role exists at all. It shows every account with what
they have actually been doing — confirmed, cleared, runs, reports, last decision
— plus one merged activity feed across the whole team. Sanctioning a case
responsibly means knowing who prepared it and what else they have been clearing.

---

## 8b-3. Settings that are policy, not constants

Several values used to be literals in the source. The risk threshold was the
number `70` written into two different files with nothing justifying it, and the
supervisor's email address existed only in `.env`.

They are **policy**: they trade officer time against missed rings, and a
department should be able to move them without a redeploy. They now live in an
`AppSetting` table and resolve **database → environment → built-in default**,
with the Settings page showing which of the three each value is currently coming
from. Clearing a field removes the override and it falls back to `.env`.

Only a supervisor can change them. Officers can see them, because the policy in
force shapes every alert they are handed.

One deliberate exception: **email credentials stay in `.env`.** They are secrets,
and secrets do not belong in a database the application can read back and render
into a settings form.

---

## 8c. Datasets and detection runs

Two small pieces of bookkeeping that change how the system can be used.

**Datasets.** An upload used to wipe everything — companies, invoices, rings,
scores and the ledger. Now each upload is its own `Dataset` and becomes the
active one; nothing is deleted. An officer can come back next week, pick a past
upload, and its detection runs, alerts and scores all come back with it. GSTIN
uniqueness moved from global to per-dataset, so uploading the same file twice
is legal.

**Detection runs.** Each detection pass creates one `DetectionRun` recording
its name, the time, who ran it, **which model version** produced the scores,
and **at what risk threshold**. Rings and risk scores hang off the run rather
than floating in global state, so re-running never destroys the previous
result and two runs can be compared directly.

That provenance is not decoration. It is what lets you say, two years later in
front of a tribunal, not merely that the evidence is unaltered but exactly
which model, trained on which data, under which policy threshold, produced the
flag — and it makes promoting a new model version *visible in the audit trail*
rather than silent.

**The threshold is now a setting.** It used to be the literal `70` written into
two different files with nothing justifying it. It lives in
`settings.RISK_THRESHOLD` (from `.env`), and every run and every ledger block
records the value in force when it ran.

---

## 9. The audit ledger — what it does and why it matters

When an officer confirms a ring, the full evidence bundle — companies,
invoices, risk score, explanation, timestamp, who confirmed it — is written into
a **block**. Each block stores the SHA-256 hash of the block before it, and its
own hash is computed over its entire content *including* that link.

The consequence is the whole point: change one character of a historical payload
and that block's hash no longer matches. And because the next block committed to
the old hash, every block after it breaks too. `verify_chain()` walks the chain
and reports exactly which block was disturbed. Even a careful forger who
recomputes the edited block's own hash is caught, because the *following* block
still points at the pre-edit value. There is a test for exactly that.

**Why it matters here.** A confirmed ring becomes the basis for recovery
proceedings against real businesses. Months later, before a tribunal, the
department must show that the evidence on file is the evidence that was there
the day the officer signed off — not something quietly edited since. A plain
database row cannot demonstrate that; an `UPDATE` leaves no trace. This can.

**What this is NOT.** This is **not a cryptocurrency and not a public
blockchain.** There is no token, no wallet, no coin, no mining, no gas fee, no
network, no consensus protocol, no third party, and no cost to run it. It is
about 150 lines of Python and one database table, and it works entirely offline.
If someone at a demo asks "so you put it on Ethereum?" — no, and deliberately
not: a public chain would add fees, latency, an external dependency, and would
publish confidential taxpayer data to the world.

**The honest limit.** Because the chain lives in the same database as everything
else, someone with write access could in principle alter a block *and* recompute
every subsequent hash, producing a chain that verifies. What this design defends
against is silent, casual and accidental alteration — which is the overwhelming
majority of real evidence-integrity failures. Defending against a determined
administrator requires an anchor outside the system: publishing the head hash
somewhere the department does not control. The design is ready for that; the
head hash is the only thing that would need publishing.

### What the chain now records

The ledger used to hold one kind of record. It holds three:

| Record type | Written when | Carries |
|---|---|---|
| `confirmed_fraud_ring` | An officer confirms an alert | Full evidence bundle: companies, invoices, score, explanation, shape evidence |
| `dismissed_alert` | An officer clears an alert | Reason code, note, score, who decided |
| `case_report_issued` | A report goes to a supervisor | The report's SHA-256 content hash and its recipients |

Every one of them also carries a `model` block — version, threshold, which
detection run, which dataset. That is the provenance described in §8c.

For the report record, only the **hash** goes in, never the body. The block's
job is to let anyone prove later that a given document is the one that was
issued; copying confidential taxpayer details into a second table would widen
the exposure for no additional guarantee.

---

## 10. The supervisor's case report

The output of the whole system is not a screen. It is a document that lands in
somebody's inbox.

**The workflow.** An officer works through a run's alerts, confirming and
clearing each one, then issues a report. It goes to the officer and to every
configured supervisor, and its content hash goes into the ledger.

This adds a **second human role**, which is what "human in the loop" actually
means in an enforcement context: an officer prepares a case, a superior
sanctions action on it. That is how GST enforcement genuinely works.

**The document.** Deliberately one page. It leads with the decision and the
money — how many alerts were confirmed, how much value is at risk, how many
companies are implicated — then one block per confirmed case with its risk
score, the value, the companies, and the single strongest plain-English reason.
Alerts that were cleared get their own short section, broken down by reason,
with a line explaining why that section exists at all.

Provenance sits in the footer: model version, threshold, run time, and the
statement that every case was reviewed and confirmed by a named officer.

**Nothing in it is written by a language model.** Every number, name and
sentence comes from stored evidence — the score the model produced, the SHAP
sentences it already generated, the officer's own note. This document can
become the basis for recovery proceedings against a real business, and a
fabricated sentence in it would be a serious problem. It is rendered as
inline-styled HTML tables rather than a stylesheet, because that is the only
layout that survives Outlook, Gmail and Apple Mail intact.

**What is honest about the delivery, and what is not.** For this build the
report travels in the message body, which is what makes the demo work end to
end. In a real deployment it would not: the body carries GSTINs, company names
and risk assessments, and SMTP is not a channel confidential taxpayer
information should cross. Production would send a short notification plus an
authenticated link back into the application. That difference is stated in the
module docstring rather than quietly shipped.

With `EMAIL_HOST` unset, Django's console backend prints the report to the
backend terminal instead of sending it — so the workflow is fully demonstrable
before any credentials exist, and a missing configuration is obvious rather
than silent.

---

## 11. Running it locally

### With Docker (recommended)

```bash
cp .env.example .env
docker-compose up --build
```

Wait for all three containers to report ready. In a second terminal:

```bash
docker-compose exec backend python manage.py migrate
docker-compose exec backend python manage.py createsuperuser
docker-compose exec backend python manage.py setup_accounts \
  --supervisor 'supervisor:Name:email' --officer 'officer1:Name:email'
```

No CSV pair to hand? Open **http://localhost:5173/lab** — the Dataset Lab (§5b)
fabricates one, tells you what the detector makes of it, and can load it
straight into the console. It needs no account to generate or download.

Open http://localhost:5173, log in, upload a companies/invoices CSV pair via
**Upload CSV**, then click **Run detection**. See the project README for the
CSV schema and where to get a demo dataset.

Run the tests:

```bash
docker-compose exec backend python manage.py test
```

### Without Docker

The backend can run against SQLite, which is useful for running tests on a
machine with no PostgreSQL:

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows
# .venv/bin/pip install -r requirements.txt       # macOS / Linux

export USE_SQLITE=True          # Windows PowerShell: $env:USE_SQLITE="True"
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend defaults to `http://localhost:8000/api`; override with
`VITE_API_BASE_URL` if needed.

### Driving it from the API instead of the UI

Every endpoint but login needs `Authorization: Token <token>`:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login/ \
  -d "username=you&password=yourpass" | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

AUTH="Authorization: Token $TOKEN"

curl -H "$AUTH" -X POST http://localhost:8000/api/fraud/run/ \
  -H "Content-Type: application/json" -d '{"name":"Detection 1"}'
curl -H "$AUTH" http://localhost:8000/api/fraud/rings/
curl -H "$AUTH" -X POST http://localhost:8000/api/fraud/rings/1/confirm/
curl -H "$AUTH" -X POST http://localhost:8000/api/fraud/rings/2/dismiss/ \
  -H "Content-Type: application/json" -d '{"reason":"genuine_trade","note":"Known supplier."}'
curl -H "$AUTH" -X POST http://localhost:8000/api/fraud/runs/1/report/
curl -H "$AUTH" http://localhost:8000/api/ledger/verify/
```

---

## 12. How to explain this project to a judge in under 2 minutes

> **The problem.** Shell companies invoice each other in a circle — A bills B,
> B bills C, C bills A — so every one of them can claim a GST refund on
> purchases that never happened. No goods move. The government's current checks
> compare each seller's filing against each buyer's filing, but in a ring those
> always match, because the same people file both sides. Every individual
> invoice looks perfect. The fraud only exists in the shape of the network.
>
> **What we built.** We treat companies as nodes and invoices as arrows. Honest
> supply chains flow one direction — raw material to manufacturer to
> distributor to retailer — so they never form a circle. We find the circles.
> Tarjan's algorithm strips out everything acyclic in one linear pass, then
> Johnson's algorithm enumerates the loops in what's left. On our network that
> takes about three milliseconds.
>
> **The hard part.** Finding circles isn't enough, because honest businesses do
> trade both ways — a retailer returns unsold stock to its distributor, that's a
> circle too. Our detector finds 33 loops; only 7 are fraud. So we score every
> loop with an XGBoost model on 17 features: shared registered addresses,
> input-credit velocity, declared turnover versus invoice value, missing e-way
> bills, and how little the amount changes as it goes round the loop — because
> real trade adds margin at every step and fake trade doesn't. All 7 real rings
> score above 88. Every honest loop scores below 13.
>
> **And it explains itself.** Using SHAP, every score comes with plain-English
> reasons — "registered 353 days ago yet already trading at volume", "56% of
> invoices moved with no e-way bill". An officer gets evidence, not a number.
>
> **Not every fraud is a circle, and we handle that.** Two shapes a cycle
> detector is blind to. First, a ring that closes through a shared director or
> registered address instead of an invoice — A bills B, B bills C, and C and A
> are run by the same person. That's a real ring, and the smarter way to run
> one, because there's no closing invoice to find. We put ownership links into
> the graph as edges, so the same search finds them. Second, a fake invoice
> mill: a shell selling to dozens of unrelated businesses and buying from
> nobody. That's a star, not a loop, and it's probably the most common GST
> fraud there is. It gets its own detector.
>
> **And the officer can tell us we're wrong.** Confirming a ring was always
> possible. Clearing one wasn't — so the system could only ever be told it was
> right, and could never improve. Now every alert can be cleared with a reason,
> and those reasons are the training data that makes the next model better.
> Nothing here ever blocks a refund by itself.
>
> **Then we make it stick.** Every decision — confirmed, cleared, or a report
> issued to a supervisor — goes into a SHA-256 hash chain, along with the model
> version and threshold that produced it. Edit any past record and every block
> after it breaks, and we can say exactly which one. That matters because this
> evidence ends up in a tribunal two years later, where you need to prove not
> just that the file is unaltered but which model made the call. To be clear:
> it's a local hash chain, not a cryptocurrency — no wallets, no tokens, no gas
> fees, no public network.
>
> **On the data.** Real GSTN data is confidential, so we generate a realistic
> network with fraud rings injected deliberately. That's on purpose — because we
> know the ground truth, we can actually measure whether the detector works,
> which you can't do on unlabelled real data anyway.

**If a judge pushes back**, the strongest honest answers are:

- *"Isn't 0.9999 AUC too good to be true?"* — Yes, and we'd say so. Our fraud
  comes from a known generative process, so a model with 17 features separates
  it almost perfectly. What we'd defend is the *pipeline*, not the number. We
  deliberately made the problem harder — every feature has at least 24% class
  overlap, and honest businesses in our data are young, bursty, and miss e-way
  bills too — so no single feature can solve it. Real data would score lower.
- *"Why not just flag everyone in a cycle?"* — You'd flag 33 businesses to
  catch 7. That's 26 honest companies under investigation, and it's why this
  problem needs ranking, not a rule.
- *"What about fraud that isn't a loop?"* — The right question, and we'd miss
  most of it with cycle detection alone. See §6b and §6c: ownership-closed
  rings and fake invoice mills each get their own detector, feeding the same
  ranked queue. What we still don't catch: missing-trader chains, rings longer
  than six companies, and rings that close outside our data entirely.
- *"How do you know it's working?"* — Honestly, right now we don't, beyond
  synthetic ground truth. That's what the clear/confirm loop is for: it's the
  first mechanism in this system capable of telling us we were wrong.
- *"Why not a real blockchain?"* — Fees, latency, an external dependency, and
  publishing confidential taxpayer data to the world. We get the tamper-evidence
  property we actually need with a local hash chain, and we've documented
  exactly what that does and doesn't protect against.

---

## 13. Known limitations, and what production would require

**Data and integration**
- The system has never seen real GSTN data. Real invoice data is messier —
  amendments, credit notes, cancelled invoices, duplicate filings, companies
  that deregister mid-year. Real integration needs government API access and
  data-sharing agreements, which is a legal and institutional problem, not a
  technical one.
- Rings that span state boundaries, use genuine dormant companies rather than
  new shells, or route through intermediaries outside the modelled network would
  be harder to catch than anything in this dataset.

**The model**
- 0.9999 held-out AUC reflects synthetic fraud generated by a known process. It
  is evidence the pipeline is wired correctly, **not** a prediction of
  real-world accuracy. On real data, expect materially lower performance and a
  genuine false-positive rate that needs managing.
- The model is trained on labels we invented. Real deployment would need
  labels from confirmed enforcement cases, which are scarce, slow to accumulate,
  and biased towards the fraud that was already being caught. **Partly
  addressed:** the review loop (§8b) now records every officer decision in both
  directions with a reason code, which is exactly the labelled data a retrained
  model would need. What is still missing is the retraining step itself, and a
  human approval gate before a new model version goes live.
- The Dataset Lab's scorecard (§5b) makes evaluation *visible* — recall against
  planted fraud, false alarms against planted honest traders — which is a real
  improvement over asserting that it works. It is still a known process
  measuring itself: `5 of 5` on fabricated rings is not a claim about rings a
  fabricator did not think of.
- The mill detector (§6c) is rules, not a model, because no labelled mills
  exist yet. That is the honest choice today and a stated baseline for later,
  but its weights are hand-set and have never been validated against ground
  truth.
- No fairness or disparate-impact analysis has been done. Before this touched a
  real taxpayer it would need it — several features (recent registration, few
  counterparties, missing e-way bills) correlate with being small and new, not
  with being fraudulent, and a system that systematically flags small new
  businesses would be doing real harm.
- Every flag is a suggestion for a human. Nothing here should ever
  auto-block a refund.

**Scale**
- Cycle detection is fast here because the honest network is a DAG. India's real
  invoice graph has tens of millions of taxpayers and billions of invoices, and
  real data contains messy reciprocal trade everywhere, so SCCs would be far
  larger and denser. Johnson's algorithm on a large dense component is
  genuinely dangerous; the length bound helps but the real answer at national
  scale is a distributed graph engine, incremental detection on new filings
  rather than full rebuilds, and partitioning by state or sector.
- Everything is synchronous, which is correct at demo scale and wrong at
  national scale. That is a deliberate, documented trade-off, not an oversight.
  It is also still true after adding a second detector: a full run over 400
  companies and 6,700 invoices, both detectors and scoring included, completes
  in about 1.5 seconds.
- Adding control edges (§6b) increases the number of reported rings
  substantially, because co-located companies that also trade now form loops.
  They are badged and still ranked by risk, but at national scale the
  `MAX_SHARED_GROUP_SIZE` guard would need to be far more careful than a flat
  constant.
- Scoring recomputes every company's features on each run. Incremental feature
  updates would be needed for a large deployment.

**The ledger**
- Nothing here is automated. The evaluators asked for passive automation with a
  human in the loop; what exists is the *human in the loop* half — every
  decision is captured, reasoned and recorded. The system still only runs when
  somebody clicks. A scheduled job that ingests new filings and refreshes the
  queue on its own is the next step, and it is deliberately not faked here.
- As explained in §9, an actor with database write access could recompute the
  whole chain. Production should anchor the head hash externally — to a second
  institution, a public chain, or a signed daily published log — so that
  wholesale rewriting becomes detectable too.
- The ledger records confirmations only. A fuller audit trail would also record
  who *viewed* what, and any subsequent case outcome.

**Security and operations**
- Every endpoint requires an authenticated account (Django's built-in auth, DRF
  token authentication) and every decision is stamped with the authenticated
  user, not a client-supplied string. **Role-based permissions now exist**
  (§8b-2): confirming an alert, viewing the team and changing settings are
  supervisor-only and enforced server-side.
- Still missing for a real deployment: finer-grained permissions than two roles
  (a real department has ranges, zones and case ownership), account
  lockout/rate-limiting on login, token expiry/rotation (DRF's tokens don't
  expire on their own), and any audit of who *viewed* what as opposed to who
  decided what.
- Case reports are emailed with the evidence in the message body. As stated in
  §10, production would send a notification and an authenticated link instead;
  taxpayer detail should not cross SMTP.
- `DEBUG=True` and a placeholder secret key ship in `.env.example` for demo
  convenience. Both must change before any real deployment.
- CORS is fully open for local development.

---

## 14. Tech stack

**Backend**

| Piece | What it's for |
|---|---|
| [Django](https://www.djangoproject.com/) 5 | Web framework, ORM, migrations, `django.contrib.auth` |
| [Django REST Framework](https://www.django-rest-framework.org/) | The API layer: serializers, generic views, pagination |
| DRF `TokenAuthentication` | Officer auth — a bearer token, no session/CSRF dance for the SPA |
| `django-filter` | Queryset filtering on list endpoints |
| `django-cors-headers` | Lets the Vite dev server talk to Django cross-origin |
| [PostgreSQL](https://www.postgresql.org/) 14+ (via `psycopg2-binary`) | The real datastore |
| SQLite | Drop-in swap for Postgres in dev/test via `USE_SQLITE=True` — no server needed |
| `python-dotenv` | Loads `.env` into the process |

**Data / ML**

| Piece | What it's for |
|---|---|
| [NetworkX](https://networkx.org/) | The graph itself — Tarjan's SCC pre-filter + Johnson's cycle enumeration, over invoice **and** ownership edges |
| [pandas](https://pandas.pydata.org/) / [NumPy](https://numpy.org/) | Feature engineering, the graph-builder's DataFrames |
| [XGBoost](https://xgboost.ai/) | Gradient-boosted trees scoring each candidate ring 0–100 |
| [scikit-learn](https://scikit-learn.org/) | Train/test splitting, metrics (ROC AUC) |
| [SHAP](https://shap.readthedocs.io/) | Per-prediction feature attribution, turned into plain-English reasons |
| [Faker](https://faker.readthedocs.io/) | Realistic-looking fabricated company/director/address data for both generators |
| `zipfile` / `csv` (stdlib) | The Dataset Lab's download: two upload files, an answer key and a note, in one archive |

**Frontend**

| Piece | What it's for |
|---|---|
| [React](https://react.dev/) 18 | UI — function components + hooks throughout |
| [React Router](https://reactrouter.com/) | Real routed pages, so each area has a URL and the back button works |
| [Vite](https://vite.dev/) | Dev server and production build |
| [Tailwind CSS](https://tailwindcss.com/) v4 | Styling, class-based dark mode via `@custom-variant dark`, design tokens via `@theme` |
| [IBM Plex Sans / Mono](https://fonts.google.com/specimen/IBM+Plex+Sans) | Drawn for technical and institutional systems, which is what this is. Mono carries GSTINs, hashes and model versions |
| [Cytoscape.js](https://js.cytoscape.org/) | The interactive network graph (see §4's `GraphView.jsx` entry) |
| [Axios](https://axios-http.com/) | API calls, with a token-injecting request interceptor |

**Infra / tooling**

| Piece | What it's for |
|---|---|
| Docker + Docker Compose | Optional one-command local stack: postgres + backend + frontend containers |
| `django.core.mail` (SMTP) | Delivering case reports to officers and supervisors |
| Git | Version control |

**What's deliberately absent.** No task queue (Celery/Redis) — the whole
detection pipeline runs synchronously inside one HTTP request because it's
fast enough (§3). No state-management library on the frontend — `useState` at
the top of `Dashboard.jsx` is enough for one page. No icon package — `icons.jsx`
is a handful of inline SVGs. No CSS-in-JS — Tailwind utility classes only. No
PDF library — the case report is HTML, because that is what actually renders
in an inbox. And no language model anywhere in the report pipeline: every
sentence in a document that could support recovery proceedings comes from
stored evidence, never from generation (§10).
