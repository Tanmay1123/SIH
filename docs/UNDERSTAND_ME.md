# Understand Me — a complete walkthrough of CodeNova

This document assumes you can program but know nothing about this project, GST,
or fraud detection. Read it top to bottom and you will understand what was
built, why each piece exists, and where the weak points are.

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

The generator is `backend/core/management/commands/seed_demo_data.py`. Nothing
in the system is hardcoded to the synthetic data: swap in real companies and
invoices and the entire pipeline downstream works unchanged.

---

## 3. Architecture and data flow

```
   ┌──────────────────────────────────────────────────────────────┐
   │  seed_demo_data.py        (synthetic generator)              │
   │  ~220 companies, ~3,700 invoices                             │
   │  7 fraud rings + 20 benign loops injected on purpose         │
   └──────────────────────────┬───────────────────────────────────┘
                              │ writes
                              ▼
                    ┌───────────────────┐
                    │   PostgreSQL      │
                    │  Company, Invoice │
                    └─────────┬─────────┘
                              │ read
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  graph_builder.py                                            │
   │  companies -> nodes, invoices -> directed edges               │
   │  (invoices between the same pair collapse into ONE edge)     │
   └──────────────────────────┬───────────────────────────────────┘
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  cycle_detection.py                                          │
   │  Stage 1: Tarjan SCC   — throw away everything acyclic       │
   │  Stage 2: Johnson's    — enumerate loops inside what's left  │
   │  ~33 candidate rings                                         │
   └──────────────────────────┬───────────────────────────────────┘
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  risk_scoring.py                                             │
   │  17 features -> XGBoost -> probability -> 0-100 score        │
   │  SHAP -> plain-English reasons                               │
   │  7 rings score 88-99, the other ~26 score under 13           │
   └──────────────────────────┬───────────────────────────────────┘
                              ▼
                    ┌───────────────────┐
                    │ FlaggedRing rows  │◄──── officer reviews in the UI
                    │ RiskScore rows    │
                    └─────────┬─────────┘
                              │ officer clicks "Confirm as fraudulent"
                              ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  ledger.py — SHA-256 hash chain                              │
   │  block N stores hash(content + hash of block N-1)            │
   │  evidence can no longer be silently rewritten                │
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

Two tables, because the whole problem only needs two.

- **`models.py`** — `Company` (GSTIN, PAN, name, director, registered address,
  registration date, declared turnover) and `Invoice` (seller FK, buyer FK,
  amount, date, goods description, `has_eway_bill`). A company is a node; an
  invoice is a directed edge. `director_name` and `registered_address` are
  indexed because the feature pipeline groups on them to find shell factories.
- **`serializers.py` / `views.py` / `urls.py`** — read-only REST endpoints for
  companies and invoices. Company detail also carries the latest risk score,
  its explanation, and which rings it belongs to.
- **`management/commands/seed_demo_data.py`** — the generator. Explained in §5.

### `backend/fraud_engine/` — everything detection-related

- **`graph_builder.py`** — reads the database into two pandas DataFrames and
  builds a NetworkX `DiGraph`. All invoices between the same pair of companies
  collapse into a single edge carrying totals (value, invoice count, how many
  lacked an e-way bill, date range). Cycle-finding only cares *whether* a trade
  relationship exists, so collapsing 3,700 invoices into ~1,200 edges is free
  speed. It works on DataFrames rather than Django objects so the exact same
  code can run on generated-but-never-saved data during training.
- **`cycle_detection.py`** — the two-stage search. Explained in §6.
- **`risk_scoring.py`** — features, model training, inference, SHAP. §7 and §8.
- **`ledger.py`** — the hash chain. §9.
- **`models.py`** — `FlaggedRing`, `RiskScore`, `LedgerBlock`.
- **`views.py` / `urls.py` / `serializers.py`** — the API.
- **`tests.py`** — 30 tests in three classes, one per concern.
- **`models_artifacts/`** — the committed pretrained model (`risk_model.json`
  plus `feature_meta.json`). Committed on purpose so a fresh clone can score
  immediately. Stored as XGBoost's native JSON rather than a pickle, which
  keeps it small, inspectable and portable across library versions.
- **`management/commands/train_risk_model.py`** — optional retraining.

### `frontend/src/`

- **`api.js`** — one Axios instance and every API call the app makes.
- **`Dashboard.jsx`** — the three-pane layout and all state.
- **`components/AlertsFeed.jsx`** — the ranked work queue.
- **`components/GraphView.jsx`** — Cytoscape network, nodes coloured by risk.
- **`components/CompanyDetail.jsx`** — the evidence panel and confirm action.
- **`components/LedgerViewer.jsx`** — blocks and chain verification status.

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
26 benign loops, the highest of which scores 12.5. Read §11 before quoting that
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

---

## 10. Running it locally

### With Docker (recommended)

```bash
cp .env.example .env
docker-compose up --build
```

Wait for all three containers to report ready. In a second terminal:

```bash
docker-compose exec backend python manage.py migrate
docker-compose exec backend python manage.py seed_demo_data
```

Open http://localhost:5173 and click **Run detection**.

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
python manage.py seed_demo_data
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

```bash
curl -X POST http://localhost:8000/api/fraud/rebuild-graph/
curl -X POST http://localhost:8000/api/fraud/score/
curl http://localhost:8000/api/fraud/rings/
curl -X POST http://localhost:8000/api/fraud/rings/1/confirm/
curl http://localhost:8000/api/ledger/verify/
```

---

## 11. How to explain this project to a judge in under 2 minutes

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
> **Then we make it stick.** When an officer confirms a ring, the evidence goes
> into a SHA-256 hash chain — each block sealed with the hash of the one before
> it. Edit any past record and every block after it breaks, and we can say
> exactly which one. That matters because this evidence ends up in a tribunal
> two years later. To be clear: it's a local hash chain, not a cryptocurrency —
> no wallets, no tokens, no gas fees, no public network.
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
- *"Why not a real blockchain?"* — Fees, latency, an external dependency, and
  publishing confidential taxpayer data to the world. We get the tamper-evidence
  property we actually need with a local hash chain, and we've documented
  exactly what that does and doesn't protect against.

---

## 12. Known limitations, and what production would require

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
  and biased towards the fraud that was already being caught.
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
- Scoring recomputes every company's features on each run. Incremental feature
  updates would be needed for a large deployment.

**The ledger**
- As explained in §9, an actor with database write access could recompute the
  whole chain. Production should anchor the head hash externally — to a second
  institution, a public chain, or a signed daily published log — so that
  wholesale rewriting becomes detectable too.
- The ledger records confirmations only. A fuller audit trail would also record
  who *viewed* what, and any subsequent case outcome.

**Security and operations**
- There is no authentication. Every endpoint is open, and "officer" is a string
  the client sends. Real deployment needs authenticated accounts, role-based
  access, and confirmations signed by an identified officer — the ledger's value
  depends on knowing who confirmed what.
- `DEBUG=True` and a placeholder secret key ship in `.env.example` for demo
  convenience. Both must change before any real deployment.
- CORS is fully open for local development.
