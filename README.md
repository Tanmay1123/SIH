# CodeNova — GST Fraud Ring Detection

**Smart India Hackathon 2026 · Problem SIH26_95**

Detecting circular-trade GST Input Tax Credit fraud by modelling companies as a
graph, finding closed invoice loops, ranking them with machine learning, and
recording officer-confirmed rings in a tamper-evident hash-chained ledger.

> **New to the project? Read this file top to bottom.** It has everything you
> need to install and get it running. For how the system actually *works*
> internally, read [docs/UNDERSTAND_ME.md](docs/UNDERSTAND_ME.md) afterwards.

---

## Table of contents

1. [What this project does](#1-what-this-project-does)
2. [What you need to install](#2-what-you-need-to-install)
3. [Getting the code](#3-getting-the-code)
4. [Setup — Path A: Docker (recommended)](#4-setup--path-a-docker-recommended)
5. [Setup — Path B: no Docker](#5-setup--path-b-no-docker)
6. [Check it actually worked](#6-check-it-actually-worked)
7. [How to demo it](#7-how-to-demo-it)
8. [What gets downloaded](#8-what-gets-downloaded)
9. [Project structure](#9-project-structure)
10. [API reference](#10-api-reference)
11. [Everyday commands](#11-everyday-commands)
12. [Troubleshooting](#12-troubleshooting)
13. [Deploying it](#125-deploying-it) — Vercel + a container host
14. [Notes for collaborators](#13-notes-for-collaborators)

---

## 1. What this project does

> **What's new in this version.** Detection now finds fraud that isn't a loop
> (fake invoice mills, and rings that close through shared ownership rather
> than through an invoice); officers can **dismiss** an alert as well as confirm
> it, so the system finally has a record of where it was wrong; every upload is
> kept as its own **dataset** and every detection is a named, dated **run**;
> a one-page **case report** goes to the officer and their supervisor by
> email, hashed into the audit ledger; and there are now two **roles** —
> officers prepare and clear cases, supervisors sanction them. The console is a
> multi-page application with its own navigation. See §7.1–§7.4.

### The problem

When a business in India buys goods it pays GST, and can later claim that money
back as **Input Tax Credit (ITC)**. The system assumes the purchase was real.

Fraudsters register shell companies that invoice each other in a closed circle —
A bills B, B bills C, C bills A. **No goods ever move.** But on paper every
company now has "purchases" to claim ITC against, so all of them apply for
refunds on tax that was never really paid.

This is hard to catch because **every individual invoice looks perfect**. The
GSTIN is valid, amounts add up, filings are on time. The government's existing
checks compare a seller's declared sales against a buyer's claimed purchases and
flag mismatches — but in a well-run ring there is no mismatch, because the same
people file both sides. The fraud is invisible in any single record. It is only
visible in the **shape of the network**.

### Our approach

```
companies = nodes,  invoices = arrows
        │
        ├─ 1. FIND THE CIRCLES
        │     Honest supply chains flow one way (raw material → manufacturer
        │     → distributor → retailer) and never loop back. We use Tarjan's
        │     algorithm to strip out everything acyclic in one linear pass,
        │     then Johnson's algorithm to enumerate loops in what remains.
        │     Result: ~33 candidate loops out of 220 companies, in ~3ms.
        │
        ├─ 1b. FIND THE FRAUD THAT ISN'T A CIRCLE
        │     Two shapes cycle detection is blind to, both real:
        │       · a ring that closes through a shared DIRECTOR or ADDRESS
        │         instead of through an invoice — A→B→C by bill, where C and A
        │         are run by the same person. We add those ownership links to
        │         the graph as edges, and the same cycle search finds them.
        │       · a FAKE INVOICE MILL: a shell selling to dozens of unrelated
        │         buyers and buying from nobody. That's a star, not a loop, and
        │         it is the most common form of real GST fraud.
        │
        ├─ 2. RANK THEM
        │     Circles alone aren't enough — honest firms trade both ways too
        │     (a retailer returns unsold stock to its distributor). Only 7 of
        │     those 33 loops are fraud. An XGBoost model scores each loop on
        │     17 features: shared registered addresses, ITC velocity, declared
        │     turnover vs invoice value, missing e-way bills, and how little
        │     the amount changes going round the loop.
        │     Result: all 7 real rings score 88–99.7. Every honest loop ≤12.5.
        │
        ├─ 3. EXPLAIN THEM
        │     SHAP turns each score into plain-English reasons — "registered
        │     only 353 days ago yet already trading at volume", "56% of its
        │     invoices moved with no e-way bill". An officer gets evidence,
        │     not a number.
        │
        ├─ 4. LET A HUMAN DECIDE — BOTH WAYS
        │     The officer confirms an alert as fraud, or clears it as
        │     legitimate with a reason. Clearing matters as much as
        │     confirming: it is the only record of where the detector was
        │     wrong, and it is the training data that lets it improve.
        │
        └─ 5. MAKE IT STICK
              Every decision — confirmed, cleared, or a case report issued to
              a supervisor — goes into a SHA-256 hash chain, along with the
              model version and risk threshold that produced it. Edit any past
              record and every block after it breaks, and we can say exactly
              which one.
```

### About the data

Real GSTN invoice data is confidential taxpayer information behind government
data-sharing agreements — there is no legitimate way to obtain it. **So we
fabricate trade networks with the fraud planted on purpose.** That is a
deliberate design decision, not a shortcut: because we know the ground truth, we
can actually measure whether the detector works rather than just asserting it
does.

Two separate generators do this, and the split matters:

- **`synthetic_network.py`** feeds the *model trainer*. It optimises for a clean
  fraud/not-fraud split with enough hard cases that the model cannot cheat.
- **`dataset_lab.py`** — the **Dataset Lab** at `/lab` — feeds *people*. It
  optimises for a spread: obvious fraud, genuinely ambiguous cases, and honest
  businesses that merely look suspicious. See §5.1.

**The running application never generates its own data.** It only ever holds
what an officer uploaded — and data from the lab goes in through exactly the
same upload path, with no shortcut past the validation. Nothing is hardcoded to
fabricated data: swap in real companies and invoices and the whole pipeline runs
unchanged.

---

## 2. What you need to install

**Pick one path.** Path A is far less setup and is what we recommend for anyone
who just wants it running. Path B is better if you're actively writing backend
code and want a fast edit-run loop, or if Docker won't install on your machine.

### Path A: Docker only (recommended)

| Software | Version | Download |
|---|---|---|
| **Docker Desktop** | latest | https://www.docker.com/products/docker-desktop/ |
| **Git** | 2.30+ | https://git-scm.com/downloads |

That is genuinely everything. Python, Node.js and PostgreSQL all run **inside**
the containers — you do not install any of them on your own machine.

> **Windows users:** Docker Desktop needs WSL 2. The installer usually sets this
> up for you. If it complains, open PowerShell **as Administrator** and run
> `wsl --install`, then reboot.
>
> **Mac users:** download the build matching your chip (Apple Silicon vs Intel).

### Path B: no Docker

| Software | Version | Download | Notes |
|---|---|---|---|
| **Python** | 3.11 – 3.13 | https://www.python.org/downloads/ | On Windows, tick **"Add Python to PATH"** in the installer |
| **Node.js** | 18+ (20 or 22 LTS ideal) | https://nodejs.org/ | npm ships with it |
| **Git** | 2.30+ | https://git-scm.com/downloads | |
| **PostgreSQL** | 14+ | https://www.postgresql.org/download/ | **Optional** — skip it and use the SQLite mode described below |

> **Which Python version?** The Docker image uses **3.11**. The project has also
> been run on **3.13**. If you're installing fresh, 3.11 or 3.12 is the safest
> choice — `shap` depends on `numba`, which is usually the last package to
> support a brand-new Python release. Avoid 3.14 for now.

### Verify your install

Run these before going further. Every one should print a version:

```bash
git --version
docker --version              # Path A
docker compose version        # Path A
python --version              # Path B  (try `python3` on Mac/Linux)
node --version                # Path B
npm --version                 # Path B
```

If `docker --version` works but commands hang or say "cannot connect to the
Docker daemon", **Docker Desktop isn't running** — open the app and wait for the
whale icon to go steady.

---

## 3. Getting the code

```bash
git clone <your-repo-url>
cd sih26-fraud-detection
```

Then create your environment file from the template:

```bash
# Mac / Linux / Git Bash
cp .env.example .env

# Windows PowerShell
Copy-Item .env.example .env
```

The defaults in `.env.example` work as-is for local development — you do not
need to edit anything. **Never commit your `.env`;** it's gitignored on purpose.

---

## 4. Setup — Path A: Docker (recommended)

From the project root, with Docker Desktop running:

```bash
docker-compose up --build
```

The first build downloads base images and installs all dependencies. **Expect
5–10 minutes and roughly 2 GB of disk.** Later starts take seconds. Leave this
terminal running — it's your server log.

Open a **second terminal**, in the same folder, and set up the database:

```bash
docker-compose exec backend python manage.py migrate
docker-compose exec backend python manage.py createsuperuser
```

`createsuperuser` makes your officer login — pick a username and password,
you'll use them on the app's login page. There is no self-signup.

**Done.** Open http://localhost:5173, log in, then use **Upload CSV** to load
a dataset (companies.csv + invoices.csv — see §5.1 below for the schema and
how to generate one) before clicking **Run detection**.

| Service | URL |
|---|---|
| Frontend dashboard | http://localhost:5173 |
| Backend API | http://localhost:8000/api/ |
| Django admin | http://localhost:8000/admin/ |

To stop: press `Ctrl+C` in the first terminal, or run `docker-compose down`.

> There is **no model training step**. A pretrained model is committed to the
> repo, so scoring works the moment you clone.

---

## 5. Setup — Path B: no Docker

You'll need **two terminals**, one for the backend and one for the frontend.

### Terminal 1 — backend

```bash
cd backend

# create and activate a virtual environment
python -m venv .venv

# activate it:
.venv\Scripts\activate           # Windows PowerShell / CMD
source .venv/bin/activate        # Mac / Linux / Git Bash

pip install -r requirements.txt
```

Now tell Django to use SQLite instead of PostgreSQL, so you don't need a
database server at all:

```bash
# Windows PowerShell
$env:USE_SQLITE="True"

# Mac / Linux / Git Bash
export USE_SQLITE=True
```

> Prefer real PostgreSQL? Skip the `USE_SQLITE` step, create a database matching
> the `POSTGRES_*` values in your `.env`, and make sure `POSTGRES_HOST=localhost`
> (the committed default is `postgres`, which is the Docker service name).

Then:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

`createsuperuser` makes your officer login for the dashboard.
Backend is now on http://localhost:8000

### Terminal 2 — frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend is now on http://localhost:5173

> The frontend defaults to `http://localhost:8000/api`. Only set
> `VITE_API_BASE_URL` in `.env` if you moved the backend somewhere else.

**Remember:** `USE_SQLITE` is a per-terminal environment variable. If you close
the terminal, set it again before running any `manage.py` command, or Django
will try to reach a PostgreSQL server that isn't there.

---

## 5.1. Getting a dataset in

The console ships with **no data**, and it never invents its own — an officer
uploads it. (The Dataset Lab further down fabricates a file pair to upload, but
it is a separate page and its output still goes in through this same door.)

Log in, open **Detections → Upload dataset**, and provide two files:

**`companies.csv`**

| column | type | notes |
|---|---|---|
| `gstin` | text | unique |
| `pan` | text | |
| `name` | text | |
| `director_name` | text | |
| `registered_address` | text | |
| `registered_date` | date | `YYYY-MM-DD` |
| `declared_turnover` | number | |

**`invoices.csv`**

| column | type | notes |
|---|---|---|
| `seller_gstin` | text | must match a row in companies.csv |
| `buyer_gstin` | text | must match a row in companies.csv |
| `amount` | number | |
| `date` | date | `YYYY-MM-DD` |
| `goods_description` | text | |
| `has_eway_bill` | boolean | `true`/`false`, `1`/`0`, `yes`/`no` |

**Uploads no longer replace anything.** Each one is stored as its own named
dataset and becomes the active one; previous uploads, their detection runs and
the audit ledger all survive. Switch between them with the dataset button next
to the title in the header.

### Ready-made datasets: `datasets/`

Five CSV pairs are committed at [`datasets/`](datasets/) — one per Dataset Lab
preset, so there is something to upload the moment the repo is cloned:

| Folder | What it is |
|---|---|
| `balanced/` | Even spread of obvious fraud, grey-zone cases and honest look-alikes. **Use this to demo.** |
| `quick/` | Small and fast — generates and runs in seconds |
| `haystack/` | A large, mostly honest economy hiding very little fraud. Tests whether the *ranking* works |
| `no_loops/` | Fraud with no circular trading at all. Cycle detection finds nothing; the mill detector has to carry it |
| `grey/` | Almost nothing clear-cut. Shows what the queue reads like when every call is the officer's |

Each folder holds `companies.csv` and `invoices.csv` (the two you upload),
`answer_key.csv` (what each company was *planted* as — for checking results
afterwards, **not** an upload file), and a `README.txt`.

These were generated by the same code the Lab page calls, with the same seeds,
so picking the matching preset in the Lab reproduces them exactly.

### Want a different mix? Use the Dataset Lab

**<http://localhost:5173/lab>** — the same port as the dashboard, just a
different page. Also linked at the bottom of the nav rail and
inside the upload dialog.

The lab is a separate page that fabricates a whole GST trade network to order.
It is deliberately outside the console: its own look, no nav rail, no case
files, and no login needed to generate or download. Nothing it produces is a
finding about a real business, and it is built so that it can never be mistaken
for one.

Tell it how big the economy should be and how much of each kind of trouble to
plant in it:

| Knob | Plants | Lands in |
|---|---|---|
| Circular-trade rings | Shell companies invoicing each other in a closed loop, every flag showing | high risk |
| Fake invoice mills | Sells to dozens of buyers, buys from nobody. No loop to find | high risk |
| Ambiguous loops | Real loops with only one or two flags each | the grey zone |
| Borderline sellers | Lopsided books that only just clear the mill detector — some won't | the grey zone |
| Honest two-way traders | Genuine businesses that form real loops. Flagging these is a *mistake* | low risk |

That last row is the one that matters. Anyone can generate data where every
fraudster is obvious; a detector tested only on that looks brilliant and is
worthless. The honest look-alikes are there to catch us out.

**The lab then marks its own work — using the real detector.** After generating,
it runs the actual pipeline (same graph builder, same Tarjan/Johnson, same mill
rules, same XGBoost model) over the result and shows you:

- how the alerts scored — how many high, grey-zone and low
- **how much of the planted fraud was actually surfaced** (`5 of 5`)
- **how many honest businesses got pushed over the high-risk line** (`0`)

It ships an `answer_key.csv` recording what every company really was. The
detector never sees it. If it plants five rings and finds three, the screen says
*3 of 5* in plain sight.

Three ways out:

| Button | What it does | Account needed? |
|---|---|---|
| **Generate & test** | Builds it and runs detection over it, in memory. Saves nothing | no |
| **Download** | A zip: `companies.csv`, `invoices.csv`, `answer_key.csv` and a note | no |
| **Load straight into the console** | Creates it as a dataset and makes it active | **yes** |

Generating fabricated data needs no login — putting it behind the login of the
console it exists to fill would be a circle. Writing to the database does, and
it goes in through exactly the same validation an officer's upload does.

**The same seed always rebuilds the same dataset**, byte for byte, so a demo can
be repeated and a bug report can be reproduced.

---

## 6. Check it actually worked

### Run the test suite

```bash
# Docker
docker-compose exec backend python manage.py test

# No Docker (venv active, USE_SQLITE set)
cd backend && python manage.py test
```

Expect **111 tests, OK**, in roughly 14 seconds. They cover cycle detection
(every injected ring is recovered across multiple generator seeds), risk scoring
(fraud rings outrank benign loops), the ledger (tampering is detected even when
the forger recomputes the edited block's own hash), ownership-closed rings, the
mill detector, the officer review loop, dataset history, and the case report.

### Check the API is alive

```bash
curl http://localhost:8000/api/auth/login/ -X POST -d "username=you&password=yourpass" -H "Content-Type: application/x-www-form-urlencoded"
```

Should return a `token`. Every other endpoint needs it: add
`-H "Authorization: Token <token>"` to subsequent requests, e.g.
`curl -H "Authorization: Token <token>" http://localhost:8000/api/fraud/status/`.

### Check the dashboard

Open http://localhost:5173. You should land on a login page. Log in with the
account you created via `createsuperuser`. The header will show **0
companies** until you upload a dataset (§5.1) — that's expected, not an error.
If you see an error bar saying it can't reach the API, the backend isn't
running.

**A few interface things worth knowing before your first look:**

- **The console is a real multi-page app.** A navigation rail on the left runs
  Overview · Network · Detections · Reports · Audit ledger · Team (supervisors
  only) · Settings. Each has its own URL and the browser back button works.
- **Your account** is the button at the top right: click it for your profile,
  your role, settings and sign out.
- **Light/dark toggle** — the sun/moon button in the top bar. Choice persists
  across reloads (`localStorage`). Defaults to dark.
- **Collapsible alerts panel** — the lines icon at the top of the left panel
  collapses it to a slim strip and back, for when the graph needs the room.
- **Upload dataset** lives on the Detections page — a two-file drag-and-drop
  (companies + invoices). Both files are required.
- **The graph view is deliberately Obsidian-style**, not a generic force
  layout: node labels are hidden when zoomed out and fade in as you zoom into
  a region (so a 250-company network doesn't render as an unreadable wall of
  overlapping text), node size scales with how many companies each one trades
  with, and there are no arrowheads — direction is shown in the evidence
  panel's numbered loop list instead. Selecting a ring from the alerts feed
  forces that ring's labels visible at any zoom level. See
  `frontend/src/components/GraphView.jsx` for the mechanics, or
  [docs/UNDERSTAND_ME.md](docs/UNDERSTAND_ME.md) for why it's built that way.

---

## 7. How to demo it

This is the walkthrough to give a judge. It takes about two minutes. Numbers
below are from the ~250-company / ~3,800-invoice demo dataset (§5.1); yours
will differ if you upload a different one.

1. **Log in, then upload a dataset.** Header shows ~250 companies and ~3,800
   invoices loaded, zero loops found so far.

2. **Click "Run detection".** This rebuilds the graph, runs cycle detection,
   then scores every candidate. Takes a few seconds.
   - **"Loops found" jumps to ~32.** That's *every* closed loop in the network
     — including genuine two-way trade, which also forms cycles.
   - **"High risk" settles on 11.** Those are the fraud rings actually
     injected. The other ~21 loops are honest reciprocal trade the model
     correctly pushed to the bottom.

3. **Click the top alert.** The graph dims everything except that ring and
   highlights the hops closing the loop. The right panel explains *why* in
   sentences — recent registration, invoice value far above declared turnover,
   missing e-way bills, near-identical amounts circling the loop. Below that:
   the member companies and the exact invoices involved.

4. **Scroll to the bottom of the alerts feed.** Those loops score near zero —
   established distributors doing genuine two-way trade. **This contrast is the
   whole point.** Cycle detection alone would have flagged all ~32 equally,
   putting ~21 honest businesses under investigation.

5. **Click "Confirm as fraudulent".** The evidence bundle is written to the
   audit ledger as a new block. The view switches to the ledger tab, where the
   new block's "links to" value is literally the previous block's hash.

6. **Point at the "CHAIN INTACT" banner.** Then explain: edit any block's
   payload directly in the database and both `/api/ledger/verify/` and this
   header flip to **BROKEN**, naming the disturbed block.

> **If asked "is it on a blockchain?"** — No, deliberately not. It's a local
> SHA-256 hash chain: no wallet, no token, no mining, no gas fees, no public
> network. A public chain would add fees, latency, an external dependency, and
> would publish confidential taxpayer data to the world.

---

## 7.1. Fraud that isn't a loop

Cycle detection only finds closed loops, which means it is structurally blind
to some of the most common GST fraud. Two extra detectors close that gap, and
both appear in the same alerts queue.

**Fake invoice mills** (`fraud_engine/mill_detection.py`). A shell that sells
to dozens of unrelated real businesses and buys from almost nobody — it never
acquired anything it claims to have sold. That is a *star*, not a loop. The
detector gates on one-way flow, buyer count and value, then scores six named
signals (one-way flow, buyer spread, missing e-way bills, recent registration,
under-declared turnover, round amounts).

This detector is **rules, not ML, on purpose**: the XGBoost model was trained
on shells inside generated rings and has never seen a labelled mill, so asking
it to score one would be inference far outside its training distribution. Every
mill score reads back as the sentences that produced it. Once officer decisions
accumulate on mill alerts, these rules become the baseline a learned model has
to beat.

**Rings that close through ownership** (`graph_builder._add_control_edges`).
A → B → C by invoice, where C and A share a registered address or a director,
*is* a circular-trade ring — the loop closes through control instead of through
a bill, which is the smarter way to run it because it leaves no closing invoice
to find. Companies sharing an address or director are linked with
`relation="control"` edges, and the same Tarjan/Johnson search finds these rings
with no other change.

Two rules keep that honest: a reported cycle must contain **at least one
invoice hop** and **at most one control hop**, otherwise a group of companies
at one address would register as a "ring" purely for being co-located.

> **A methodological note worth knowing.** The model's four cycle features were
> learned on a pure invoice graph, so feeding it cycle counts inflated by
> control edges would score outside its training distribution. The pipeline
> therefore builds **two** graphs: features come from the invoice-only graph,
> exactly as at training time, while the reported alerts come from the
> control-augmented one. See the comment in `fraud_engine/pipeline.py`.

---

## 7.2. The review loop

Previously an officer could only ever tell the system it was **right**. There
was a "Confirm as fraudulent" button and nothing else, so the system held no
negative examples, could not measure its own precision, and could never improve.

Every alert now has three states — **pending**, **confirmed**, **dismissed** —
and the evidence panel offers both actions:

| Action | What it records |
|---|---|
| **Confirm as fraudulent** | Full evidence bundle → ledger block, plus the model version and threshold that produced the score |
| **Not fraud** | A structured reason code + optional note → ledger block, and a labelled negative example |

The dismissal reasons are the useful part: *genuine two-way trade · shell but
not circular · already under investigation · insufficient evidence · data
quality problem · other*. If most dismissals say "genuine two-way trade", that
is a specific, fixable model failure rather than a vague sense that precision
is poor.

Decisions **carry forward** between runs over the same dataset, keyed by the
alert's order-independent signature — nobody re-reviews work they already did.

**Nothing here ever auto-blocks a refund.** Every enforcement action stays a
human decision; the machine does the watching, not the deciding.

---

## 7.3. Datasets, runs and the supervisor's report

**Datasets.** Every upload is kept. Pick a past upload from the dataset button
in the header and its detection runs, alerts and scores all come back with it.
The same GSTIN may appear in several datasets (uniqueness is per dataset).

**Detection runs.** Each "Run detection" creates one named, dated
`DetectionRun` recording what was found, which model version found it and at
what threshold. Re-running never erases the previous run, so you can compare.
They are listed under the **History & reports** tab.

### Case reports

Reports are the output of this system. Not a screen — a **PDF document** you can
read on the page, save to disk, or send to a supervisor. There are two shapes,
sharing one table, one ledger, and one delivery path:

| | **Run report** | **Company report** |
|---|---|---|
| Covers | One detection run, end to end | One company |
| Contains | Confirmed cases highest-risk-first with the plain-English reason for each, the value at risk, and what was cleared and why | Registration details, trade totals, why its score is what it is, and every alert it appears in |
| Generated from | Detections → *Generate report* | Network → open a company → *Generate report* |
| Needs a decision first? | Written after an officer works the queue | No — *"why does this look clean"* is as legitimate a question as *"why is this red"* |

Both are also generatable straight from the **Reports** page: *Generate a
report* → pick a run, or search a company by name or GSTIN.

**Generating and sending are two separate actions.** A report is rendered,
hashed, and written to the audit ledger the moment it is generated — so what
was issued is on record either way. Nothing reaches an inbox until *Send* is
pressed and confirmed in a dialog naming the exact recipients. That
confirmation is not decoration: unlike almost everything else in this console,
an email landing in someone's inbox cannot be undone by fixing a row in a
table afterwards.

The report's SHA-256 content hash goes into the audit ledger, so the document a
supervisor received can later be proven to be the document on file. The PDF is
regenerated from the stored HTML on every request rather than cached as
binary — the content hash already proves that HTML has not changed.

> **Why xhtml2pdf and not WeasyPrint.** WeasyPrint renders more faithfully but
> needs Pango, Cairo and GDK-Pixbuf installed on the host. xhtml2pdf is pure
> Python (reportlab underneath), so the same code produces the same PDF in
> Docker, in CI, and on a teammate's laptop with nothing extra installed. The
> one thing it costs: its default fonts have no ₹ glyph, so the PDF renderer
> swaps `₹` for `Rs.` — on the PDF path only, not in the app or the email.

#### Email delivery

The message is a **short professional cover note with the PDF attached** — not
the whole report pasted into the body, which is what it used to be and which
read as a wall of formatting rather than a letter.

Configure delivery in `.env`:

```bash
EMAIL_HOST=smtp.gmail.com          # blank => printed to the backend console
EMAIL_PORT=587
EMAIL_HOST_USER=you@gmail.com
EMAIL_HOST_PASSWORD=your-app-password   # Gmail needs an App Password, not your login
EMAIL_USE_TLS=True
REPORT_SUPERVISOR_EMAILS=supervisor@dept.gov.in   # optional; see below
```

With `EMAIL_HOST` blank, reports print to the backend console instead of being
sent — so the whole workflow is demonstrable before any credentials exist.

**Recipients resolve automatically:** the officer who generated it, plus
everyone in the `Supervisors` group who has an email on their account, plus
anything in `REPORT_SUPERVISOR_EMAILS`, de-duplicated. Adding a supervisor via
`setup_accounts` or the Team page is enough — there is no second list to
remember to update.

> **If mail silently never arrives,** check the *sending* account's own inbox
> before suspecting the code. SMTP accepting a message (`250 OK`) only means
> the relay took it; a wrong recipient address bounces back **later**, as a
> Delivery Status Notification to the sender, and the app has no way to see
> that. A `550 5.1.1 ... does not exist` in that inbox means a typo'd address,
> not a broken feature.

> **Said plainly, because it matters:** the report carries GSTINs, company
> names and risk assessments, and SMTP is not a channel confidential taxpayer
> data should cross. A real deployment would email a short notification plus an
> authenticated link back into the application. That is a deliberate demo
> shortcut, not an oversight.

---

## 7.4. Roles: officers and supervisors

Two roles, mirroring how enforcement actually works.

| | Officer | Supervisor |
|---|---|---|
| Review alerts, read the evidence | ✓ | ✓ |
| **Clear** an alert as not fraud | ✓ | ✓ |
| Upload data, run detection | ✓ | ✓ |
| Issue case reports | ✓ | ✓ |
| **Confirm** an alert as fraudulent | — | ✓ |
| See every officer's activity | — | ✓ |
| Change detection settings | — | ✓ |

**Why the split falls there.** Confirming an alert is the act that starts
recovery proceedings against a real business, so it is the one decision that
warrants a second, more senior pair of eyes. Clearing deliberately stays with
the officer: being able to say *"I looked, this is a normal business"* is the
feedback the detector needs, and gating it behind a supervisor would mean it
never happens.

**How membership works.** Roles are Django Groups (`Officers`, `Supervisors`),
so they are administered from `/admin/` or from the in-app **Team** page — no
code change. A superuser is always treated as a supervisor, so the account
created by `createsuperuser` can never lock itself out of confirming. A
supervisor cannot demote themselves, for the same reason.

Every rule is enforced server-side (`core/permissions.py`). The UI reads a
permissions map from `/api/auth/me/` so it can avoid showing an action that
would only be refused — but hiding a button is a courtesy, never a control.

### The Team page

Supervisor-only. Every account with what they have actually been doing —
confirmed, cleared, runs, reports, last decision — plus a merged activity feed
across the whole team. It is what makes sanctioning a case responsible: you can
see who prepared it and what else they have been clearing.

### Settings you can change in the app

The **Settings** page holds detection policy and report delivery: organisation
name, supervisor email addresses, the high-risk threshold, the invoice-mill
alert threshold, and the longest ring to search for.

Each value resolves **database → `.env` → built-in default**, and the page shows
which of the three each one is currently coming from. Clearing a field removes
the override so it falls back to `.env`. Only a supervisor can change them;
officers see the policy in force, because it shapes every alert they get.

> Email *credentials* stay in `.env` and are deliberately not editable in the
> app — they are secrets, and secrets do not belong in a database the
> application can read back.

---

## 8. What gets downloaded

So nobody is surprised by the install size or wonders what a package is for.

### Python packages (`backend/requirements.txt`)

| Package | Why it's here |
|---|---|
| `Django`, `djangorestframework` | Web framework and REST API |
| `django-cors-headers`, `django-filter` | Cross-origin requests from the React dev server; queryset filtering |
| `psycopg2-binary` | PostgreSQL driver |
| `python-dotenv` | Reads `.env` |
| `xhtml2pdf` | Renders case reports as PDFs. Pure Python — no system libraries, unlike WeasyPrint |
| `certifi` | The CA bundle `settings.py` points TLS at, so SMTP works on Python installs that never got one |
| `Faker`, `pandas`, `numpy` | Used by the offline model trainer/tests (`fraud_engine/synthetic_network.py`) and the feature pipeline; not used to seed the running app |
| `networkx` | The graph — Tarjan's SCC and Johnson's cycle enumeration |
| `scikit-learn`, `xgboost` | Risk model training and inference |
| `shap` | Explainability (pulls in `numba` + `llvmlite`, which are large) |

Roughly **700 MB – 1 GB** installed, mostly `xgboost`, `shap`, `numba` and
`scipy`. This is normal for a data-science stack.

### JavaScript packages (`frontend/package.json`)

| Package | Why it's here |
|---|---|
| `react`, `react-dom` | UI |
| `react-router-dom` | Real routed pages, so the back button works |
| `vite`, `@vitejs/plugin-react` | Dev server and build tool |
| `cytoscape` | The interactive network graph |
| `axios` | API calls |
| `tailwindcss`, `@tailwindcss/vite` | Styling |

About **66 MB** across ~74 packages.

### Docker images (Path A only)

`postgres:16-alpine`, `python:3.11-slim`, `node:20-alpine` plus the installed
dependencies — **budget ~2 GB total**.

### What you do *not* need to download

- **The trained ML model.** It's committed at
  `backend/fraud_engine/models_artifacts/risk_model.json` (small, XGBoost's
  native JSON format, not a pickle). No training step required.
- **Any API keys.** Everything runs offline and local.

You **do** need a dataset to load, but you don't need to find one: five ready
CSV pairs ship in [`datasets/`](datasets/), and the Dataset Lab fabricates more
on demand (§5.1).

---

## 9. Project structure

```
sih26-fraud-detection/
├── docker-compose.yml          # 3 services: postgres, backend, frontend
├── .env.example                # copy to .env — every variable the project needs
├── README.md                   # you are here
│
├── backend/
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── config/                 # Django settings, root URLs, WSGI
│   │
│   ├── core/                   # ── APP 1: data model, auth, roles, settings ──
│   │   ├── models.py           #    Dataset, Company, Invoice, AppSetting
│   │   ├── roles.py            #    who is an officer, who is a supervisor
│   │   ├── permissions.py      #    IsSupervisor, used on the gated endpoints
│   │   ├── settings_store.py   #    DB → .env → default resolution
│   │   ├── team_views.py       #    profile, team overview, activity, settings
│   │   ├── serializers.py
│   │   ├── views.py             #    also: dataset CRUD, login/logout/whoami
│   │   ├── csv_import.py       #    parses+loads officer-uploaded CSVs
│   │   └── management/commands/
│   │       ├── setup_accounts.py  # the team's logins + roles, idempotent
│   │       └── reset_data.py      # wipe case data, keep the accounts
│   │
│   └── fraud_engine/           # ── APP 2: everything detection-related ──
│       ├── graph_builder.py    #    DB → NetworkX DiGraph (+ ownership edges)
│       ├── cycle_detection.py  #    Tarjan SCC pre-filter + Johnson's
│       ├── mill_detection.py   #    NON-LOOP fraud: fake invoice mills
│       ├── risk_scoring.py     #    features → XGBoost → SHAP explanations
│       ├── pipeline.py         #    one detection pass = one named DetectionRun
│       ├── reporting.py        #    both report shapes as HTML → PDF
│       ├── mailer.py           #    cover note + PDF attachment, failure recording
│       ├── settings_helpers.py #    risk threshold + supervisor recipients
│       ├── ledger.py           #    SHA-256 hash chain
│       ├── models.py           #    DetectionRun, FlaggedRing, RiskScore,
│       │                       #    LedgerBlock, CaseReport (run | company)
│       ├── views.py            #    all fraud API endpoints
│       ├── tests.py            #    126 tests in 14 classes
│       ├── models_artifacts/   #    the committed pretrained model
│       ├── synthetic_network.py     # generator used ONLY by tests + training,
│       │                            # never to seed the running app
│       ├── dataset_lab.py     #    THE DATASET LAB: fabricated networks with a
│       │                      #    controllable risk mix + an answer key
│       ├── lab_views.py       #    its API. Open to generate, gated to load
│       └── management/commands/
│           └── train_risk_model.py  # optional retraining
│
├── frontend/
│   ├── package.json
│   └── src/
│       ├── api.js              # axios instance + every API call
│       ├── App.jsx             # router + the shared investigation state
│       ├── useAuth.jsx         # signed-in account, role, permissions map
│       ├── useTheme.js         # dark/light mode hook, persisted to localStorage
│       ├── icons.jsx           # dependency-free inline SVG icons
│       ├── index.css           # design tokens: Plex type + blue-shifted neutrals
│       ├── Login.jsx           # officer sign-in page
│       ├── lab/                # THE DATASET LAB — deliberately not part of
│       │   ├── LabPage.jsx     # the console: own page, own look, own client
│       │   └── labApi.js
│       ├── layout/
│       │   ├── AppShell.jsx        # nav rail + top bar + routed outlet
│       │   └── UserMenu.jsx        # account dropdown: profile, role, sign out
│       ├── pages/
│       │   ├── OverviewPage.jsx    # where you land: counters + queue preview
│       │   ├── NetworkPage.jsx     # queue + graph + evidence (three panes)
│       │   ├── DetectionsPage.jsx  # run history, upload, run detection
│       │   ├── ReportsPage.jsx     # reports: generate, filter, view PDF, send
│       │   ├── LedgerPage.jsx      # the audit chain
│       │   ├── TeamPage.jsx        # SUPERVISOR ONLY: who did what
│       │   ├── SettingsPage.jsx    # editable detection policy
│       │   └── ProfilePage.jsx     # your details, permissions, password
│       └── components/
│           ├── ui.jsx              # shared primitives (Card, Button, Stat,
│           │                       # Dialog, ConfirmDialog, …)
│           ├── AlertsFeed.jsx      # ranked work queue (left), collapsible
│           ├── GraphView.jsx       # Cytoscape network, Obsidian-style (centre)
│           ├── CompanyDetail.jsx   # evidence panel + confirm/dismiss (right)
│           ├── DatasetPicker.jsx   # switch between uploads
│           └── LedgerViewer.jsx    # audit chain
│
├── datasets/                  # five ready CSV pairs, one per Lab preset
│   ├── balanced/  quick/  haystack/  no_loops/  grey/
│   └── README.txt             # what each one is for
│
└── docs/
    ├── UNDERSTAND_ME.md        # full technical walkthrough
    └── 10-year-old explanation of all the backend that is happening.md
```

Two Django apps, deliberately: `core` holds the data, `fraud_engine` holds the
detection. Each is short enough to read top to bottom.

---

## 10. API reference

Endpoints marked **S** are supervisor-only; everything else needs any
authenticated officer account.

| Method | Endpoint | Auth | Purpose |
|---|---|---|---|
| POST | `/api/auth/login/` | — | `{username, password}` → `{token, username}` |
| POST | `/api/auth/logout/` | ✓ | Invalidate the caller's token |
| GET | `/api/auth/whoami/` | ✓ | Validate a stored token |
| GET/PATCH | `/api/auth/me/` | ✓ | Your profile, role and permissions map; update your own name/email |
| POST | `/api/auth/change-password/` | ✓ | `{current_password, new_password}` → a fresh token |
| GET | `/api/team/` | **S** | Every account with its review activity |
| GET | `/api/team/activity/` | **S** | Merged feed of decisions, runs and reports |
| POST | `/api/team/{id}/role/` | **S** | `{"role": "officer"\|"supervisor"}` |
| GET | `/api/settings/` | ✓ | Every configurable value and where it came from |
| PATCH | `/api/settings/update/` | **S** | Change detection policy or report recipients |
| POST | `/api/data/upload/` | ✓ | `companies` + `invoices` CSV files (+ optional `name`) → a new dataset, made active |
| GET | `/api/datasets/` | ✓ | Every upload, newest first |
| PATCH | `/api/datasets/{id}/` | ✓ | Rename a dataset |
| POST | `/api/datasets/{id}/activate/` | ✓ | Switch which dataset the app is looking at |
| DELETE | `/api/datasets/{id}/delete/` | ✓ | Remove a dataset (refused if a report was issued from it) |
| GET | `/api/companies/` | ✓ | Companies in the active dataset (paginated, `?search=`, `?page_size=`) |
| GET | `/api/companies/{id}/` | ✓ | Company + risk score + explanation + alert membership |
| GET | `/api/invoices/` | ✓ | Invoices (`?company=` / `?seller=` / `?buyer=`) |
| POST | `/api/fraud/run/` | ✓ | Run both detectors + scoring as one named `DetectionRun` |
| GET | `/api/fraud/runs/` | ✓ | Every run, newest first (`?dataset=`) |
| GET | `/api/fraud/runs/{id}/` | ✓ | One run's counters and provenance |
| DELETE | `/api/fraud/runs/{id}/delete/` | ✓ | Discard a run (refused if it produced a report) |
| POST | `/api/fraud/runs/{id}/report/` | ✓ | Build a run's case report and hash it into the ledger. Does **not** send — `send` defaults to false |
| GET | `/api/fraud/rings/` | ✓ | Alerts for a run, highest risk first (`?run=`, `?status=`, `?kind=`) |
| GET | `/api/fraud/rings/{id}/` | ✓ | Alert detail: companies, invoices, score, explanation |
| POST | `/api/fraud/rings/{id}/confirm/` | **S** | Confirms as the *authenticated* supervisor → appends a ledger block |
| POST | `/api/fraud/rings/{id}/dismiss/` | ✓ | `{reason, note}` — clears an alert as not fraud → appends a ledger block |
| GET | `/api/fraud/dismissal-reasons/` | ✓ | The reason codes `dismiss` accepts |
| GET | `/api/fraud/status/` | ✓ | Dashboard summary counters |
| GET | `/api/fraud/graph/` | ✓ | Whole network in one Cytoscape-shaped payload |
| POST | `/api/companies/{id}/report/` | ✓ | Build one company's report — details + why it scored what it did — and hash it into the ledger |
| GET | `/api/reports/` | ✓ | Issued reports, both shapes (`?run=`, `?company=`) |
| GET | `/api/reports/{id}/` | ✓ | One report, including the rendered HTML |
| GET | `/api/reports/{id}/pdf/` | ✓ | The report as a PDF — inline for viewing, `?download=1` to save |
| POST | `/api/reports/{id}/send/` | ✓ | Email it as a PDF attachment. The **only** endpoint that sends |
| GET | `/api/reports/mail-status/` | ✓ | Is SMTP usable, and who would be copied in |
| GET | `/api/lab/presets/` | — | Dataset Lab starting points and limits |
| POST | `/api/lab/preview/` | — | Generate + run the real detector over it. Saves nothing |
| POST | `/api/lab/download/` | — | The same, as a zip of CSVs plus an answer key |
| POST | `/api/lab/load/` | ✓ | Generate and create it as a dataset, made active |
| GET | `/api/ledger/blocks/` | ✓ | All ledger blocks |
| GET | `/api/ledger/verify/` | ✓ | Walk the chain, report whether it's intact |

Everything except login and the three open Dataset Lab endpoints requires
`Authorization: Token <token>`. The lab's `presets`/`preview`/`download` read
nothing from the database and produce only fabricated CSV text, which is why
they need no account; `lab/load` writes rows, so it does. Driving the pipeline
without the UI:

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

Every endpoint requires an authenticated officer account (Django's built-in
auth, token-based). There is no self-signup — accounts are created with
`createsuperuser` or via `/admin/`.

---

## 11. Everyday commands

Prefix with `docker-compose exec backend` on Path A; run inside `backend/` with
your venv active on Path B.

| Task | Command |
|---|---|
| Load a dataset | Upload CSV button in the dashboard (§5.1) |
| Fabricate a test dataset | <http://localhost:5173/lab> (§5.1) |
| Switch dataset | Dataset button next to the title in the header |
| Create the first admin | `python manage.py createsuperuser` |
| Create the team's accounts | `python manage.py setup_accounts` (see below) |
| Wipe case data, keep accounts | `python manage.py reset_data --yes` |
| Run the tests | `python manage.py test` |
| Run one test class | `python manage.py test fraud_engine.tests.LedgerTests` |
| Retrain the model (optional) | `python manage.py train_risk_model` |
| Apply new migrations | `python manage.py migrate` |
| After changing a model | `python manage.py makemigrations` |

### Setting up the team's accounts

`createsuperuser` makes one account, interactively, with no role. A department
needs several with the right roles attached, and a team needs to recreate them
identically on someone else's laptop:

```bash
python manage.py setup_accounts \
  --supervisor 'supervisor:Vikram Mehta:vikram@example.gov.in' \
  --officer    'officer1:Anita Rao:anita@example.gov.in' \
  --officer    'officer2:Raj Kumar:raj@example.gov.in'
```

The format is `username:Full Name:email`; name and email are both optional and
can be filled in later by re-running the command. It prints a generated
password for each **new** account, once — Django stores only the hash, so
nothing can read them back out afterwards.

It is **idempotent**: run it twice and you get the same accounts, not six. An
existing account has its name, email and role brought into line, but its
password is left alone — silently changing someone's password is not an update,
it is a lockout. Pass `--reset-password` when you actually mean to. Other flags:
`--password` to set one you choose, and `--remove <username>` to delete an
account (it refuses to delete a superuser).

Email matters for more than the login: a case report is sent to the officer who
issued it *and* to every supervisor with an email on their account.

### Clearing the data before a demo

```bash
python manage.py reset_data --yes
```

Deletes datasets, companies, invoices, detection runs, alerts, ledger blocks
and case reports — and **keeps the accounts and their roles**, which is the
difference between this and `flush`. Add `--settings-too` to also drop database
setting overrides so policy falls back to `.env`. Use `--dry-run` to see the
counts first; without `--yes` it refuses to do anything.

### Clearing the data from pgAdmin instead

`reset_data` is the recommended route — it knows the delete order and can't
leave the database half-wiped. But if you want to do it by hand in pgAdmin:

**Connect.** Right-click *Servers → Register → Server*. Under **Connection**:
host `localhost`, port `5432`, database `fraud_db`, user `fraud_user`, password
from your `.env`. (Running under Docker, the containers talk to host
`postgres`, but pgAdmin on your own machine still connects to `localhost` —
compose publishes the port.)

**Then open the Query Tool** (right-click the `fraud_db` database → *Query
Tool*) and run:

```sql
TRUNCATE TABLE
    fraud_engine_casereport,
    fraud_engine_ledgerblock,
    fraud_engine_riskscore,
    fraud_engine_flaggedring,
    fraud_engine_detectionrun,
    core_invoice,
    core_company,
    core_dataset
RESTART IDENTITY CASCADE;
```

One statement, all eight tables, because they reference each other — truncating
`core_company` alone fails on the foreign keys pointing at it. `CASCADE` lets
Postgres follow those references, and `RESTART IDENTITY` resets the id counters
so the next dataset starts from 1 again.

**What this deliberately leaves alone:** `auth_user`, `auth_group` and
`core_appsetting` — your logins, roles and configured policy. Add
`core_appsetting` to the list if you also want settings back to `.env`
defaults. **Never** truncate the `auth_*` or `django_*` tables: that deletes
every account and the migration history with them.

> **Don't `DROP` anything.** Truncating empties tables; dropping deletes their
> structure, and Django will not recreate it without a fresh `migrate` on an
> empty database. If tables are dropped by accident, recover with
> `python manage.py migrate` and then re-run `setup_accounts`.

Verify from the Query Tool:

```sql
SELECT
    (SELECT count(*) FROM core_company)            AS companies,
    (SELECT count(*) FROM core_invoice)            AS invoices,
    (SELECT count(*) FROM fraud_engine_flaggedring) AS alerts,
    (SELECT count(*) FROM auth_user)                AS accounts;  -- should be unchanged
```

Docker-specific:

| Task | Command |
|---|---|
| Start everything | `docker-compose up` |
| Rebuild after changing dependencies | `docker-compose up --build` |
| Stop | `docker-compose down` |
| Stop **and wipe the database** | `docker-compose down -v` |
| Tail backend logs | `docker-compose logs -f backend` |
| Shell inside the backend | `docker-compose exec backend bash` |

---

## 12. Troubleshooting

**`docker: command not found` / "cannot connect to the Docker daemon"**
Docker Desktop isn't installed or isn't running. Open the app and wait for the
whale icon to stop animating.

**Port already in use (5432, 8000 or 5173)**
Something else is using it — often an existing PostgreSQL install on 5432. Stop
that service, or change the host-side port in `docker-compose.yml` (edit the
*left* number only, e.g. `"5433:5432"`).

**Dashboard shows "Cannot reach the API"**
The backend isn't running, or it crashed. Check the backend terminal, or
`docker-compose logs backend`. Confirm http://localhost:8000/api/fraud/status/
loads in a browser.

**`django.db.utils.OperationalError: could not connect to server`**
Django is trying to reach PostgreSQL and can't.
- Path B: you forgot to set `USE_SQLITE=True` in *this* terminal.
- Path A: Postgres hasn't finished starting — wait a few seconds and retry.
- Running natively against real Postgres: set `POSTGRES_HOST=localhost` in your
  `.env` (the default `postgres` is the Docker service name).

**"No risk model at ... Run: python manage.py train_risk_model"**
The committed model artifact is missing. It should be at
`backend/fraud_engine/models_artifacts/risk_model.json` — check it came down
with your clone. If not, `python manage.py train_risk_model` regenerates it in
about 20 seconds.

**`npm install` fails, or the frontend won't start**
Delete `node_modules` and `package-lock.json`, then `npm install` again. Confirm
`node --version` is 18 or higher.

**Frontend container fails after you ran `npm install` on your own machine**
Shouldn't happen — `frontend/.dockerignore` excludes `node_modules` precisely so
host-built native binaries never get copied into the Linux image. If you hit it
anyway, `docker-compose build --no-cache frontend`.

**Reports say "SMTP is not configured"**
`EMAIL_HOST` is blank in `.env`, so reports are printed to the backend terminal
instead of being emailed. That is the default and it is deliberate — fill in the
`EMAIL_*` values (§7.3) to send them for real. On Gmail, `EMAIL_HOST_PASSWORD`
must be an **App Password**, not your normal account password.

**A report says "No recipients"**
Your officer account has no email address, and `REPORT_SUPERVISOR_EMAILS` is
empty. Set one in `/admin/` under Users, or add supervisors to `.env`.

**Far more rings than before after upgrading**
Expected. Ownership edges (§7.1) surface rings that close through a shared
director or address, which invoice-only detection could not see. They carry a
"closes via shared ownership" badge, and the queue is still ranked by risk.

**`pip install` fails on `shap` or `numba`**
Almost always a too-new Python. `numba` lags new releases by months. Use Python
3.11 or 3.12.

**Setup caveat, stated honestly:** the no-Docker path (Path B) is the one that's
been exercised end to end on this codebase. The Docker path is standard and its
config is validated, but if you're the first person to run `docker-compose up`
and something snags, it's more likely an environment issue than a code one —
shout and we'll fix it in a commit.

---

## 12.5. Deploying it

### The shape of a deployment, and why

**The frontend goes on Vercel. The backend cannot.** That is a hard technical
limit, not a preference:

| | Vercel serverless | This backend |
|---|---|---|
| Bundle size | 250 MB unzipped, hard cap | **~634 MB installed** |
| Request timeout | 10 s Hobby / 60 s Pro | detection is synchronous and can take tens of seconds |
| Filesystem/process | ephemeral, per-invocation | long-lived worker, model loaded once |

The size isn't trimmable fat — `llvmlite` (125 MB), `scipy` (99 MB), `pandas`
(73 MB), `scikit-learn` (48 MB), `numpy` (36 MB) and `numba` (31 MB) are what
the risk model and its SHAP explanations actually need. Dropping SHAP entirely
still leaves ~295 MB, over the cap, and costs the explanations that make a
score defensible in the first place.

So:

```
  React frontend  ──►  Vercel          (static build + CDN — what Vercel is for)
        │ VITE_API_BASE_URL
        ▼
  Django backend  ──►  Render / Railway / Fly.io   (Docker, already in this repo)
        │
        ▼
  PostgreSQL      ──►  the same host's managed database
```

Deploy the **backend first** — the frontend needs its URL at build time.

### 1. Backend

Any host that runs a container works. `render.yaml` in the repo root is a ready
blueprint (Render → *New* → *Blueprint* → point at this repo); Railway and
Fly.io take the same `backend/Dockerfile` with their own config.

The image runs **gunicorn**, not `runserver` — the development server is
single-threaded and not built to face the internet. Static files are served by
**WhiteNoise** from inside the app, so `/admin/` has its CSS with no separate
web server.

Environment variables:

| Variable | Value | Why |
|---|---|---|
| `DATABASE_URL` | from your managed Postgres | Preferred over the five `POSTGRES_*` vars; hosts hand out one string |
| `DJANGO_SECRET_KEY` | a long random value | Generate: `python -c "import secrets;print(secrets.token_urlsafe(64))"` |
| `DJANGO_DEBUG` | `False` | Also switches on HTTPS redirect, secure cookies and HSTS |
| `DJANGO_ALLOWED_HOSTS` | your API hostname | Django rejects every other Host header |
| `CORS_ALLOWED_ORIGINS` | your Vercel URL | **Set this.** Left blank, CORS stays wide open |
| `CORS_ALLOW_VERCEL_PREVIEWS` | `True` | Also accept `*.vercel.app`, so preview deploys work |
| `EMAIL_HOST` etc. | your SMTP details | Omit and reports print to the log instead of sending |

Then create the accounts once, from the host's shell:

```bash
python manage.py setup_accounts --supervisor 'supervisor:Name:email@dept.gov.in'
```

Check it: `curl https://your-api.onrender.com/` returns `{"status": "ok", ...}`.

### 2. Frontend on Vercel

Import the GitHub repo, then set:

| Setting | Value |
|---|---|
| **Root Directory** | `frontend` |
| Framework preset | Vite (auto-detected) |
| Build command | `npm run build` (auto) |
| Output directory | `dist` (auto) |

Add one environment variable:

```
VITE_API_BASE_URL = https://your-api.onrender.com/api
```

Note the `/api` suffix and no trailing slash.

> **The one thing that catches everybody:** Vite bakes `VITE_*` variables into
> the bundle at **build** time. Setting the variable on an existing deployment
> changes nothing until you **redeploy**. If the deployed app throws network
> errors, open the browser console — the app prints an explicit message when it
> detects it was built without this variable.

`frontend/vercel.json` is already in the repo. Its `rewrites` rule is what makes
refreshing on `/reports` work: this is a single-page app, there is no
`/reports` file on disk, and without the rewrite Vercel returns its own 404.

### 3. After the first deploy

Set `CORS_ALLOWED_ORIGINS` on the backend to the Vercel URL you just got, and
restart it. Until you do, the browser blocks every API call — a CORS failure
shows up in the console as a blocked request, not as a server error.

### Mobile

The console is responsive from 320px up. Two things change on small screens:
the navigation rail becomes a drawer behind the header's menu button, and the
Network page's three panes (queue, graph, evidence) become three tabs, since
they need ~1000px to sit side by side. Everything remains reachable — nothing
is hidden from a phone except the header's dataset switcher, which is duplicated
on the Detections page.

---

## 13. Notes for collaborators

**Before you start work**

- Never commit `.env` — it's gitignored. If you add a new environment variable,
  add it to `.env.example` with a placeholder so everyone else knows it exists.
- Don't commit `node_modules/`, `__pycache__/`, `.venv/`, `dist/` or
  `db.sqlite3`. All gitignored already.
- **Do** commit `backend/fraud_engine/models_artifacts/` — that's the pretrained
  model, and it's deliberately tracked so a fresh clone works without training.
  There's a comment in `.gitignore` explaining the exception.

**Working on the code**

- Changed a Django model? Run `makemigrations`, and **commit the migration
  file** — otherwise everyone else's database breaks.
- Changed `requirements.txt` or `package.json`? Tell the team, and rebuild with
  `docker-compose up --build`.
- Run `python manage.py test` before pushing. All 83 should pass.
- `fraud_engine/synthetic_network.py` (used by tests and `train_risk_model`,
  never by the running app) is seeded, so it's reproducible: same seed, same
  network.
- Retraining is deterministic too — `train_risk_model` regenerates a
  byte-identical artifact, so it won't show up as a spurious diff. If it *does*
  produce a diff, something upstream genuinely changed (a feature, the
  generator, or an XGBoost version) and that's worth understanding before you
  commit it.

**Where to make changes**

| You want to change... | Go to |
|---|---|
| The test/training data generator | `backend/fraud_engine/synthetic_network.py` |
| The CSV upload format or validation | `backend/core/csv_import.py` |
| Non-loop (mill) detection | `backend/fraud_engine/mill_detection.py` |
| Ownership/control edges | `_add_control_edges()` in `graph_builder.py` |
| What one detection run does | `backend/fraud_engine/pipeline.py` |
| The supervisor report's wording or design | `backend/fraud_engine/reporting.py` |
| Email delivery | `backend/fraud_engine/mailer.py` + `.env` |
| How cycles are found | `backend/fraud_engine/cycle_detection.py` |
| Risk features or the model | `backend/fraud_engine/risk_scoring.py` |
| The plain-English explanation wording | `_describe()` in `risk_scoring.py` |
| API endpoints | `backend/fraud_engine/views.py` + `urls.py` |
| The dashboard layout | `frontend/src/Dashboard.jsx` |
| The graph's look and behaviour | `frontend/src/components/GraphView.jsx` |
| The login page | `frontend/src/Login.jsx` |
| Light/dark theme | `frontend/src/useTheme.js` |
| Who can do what | `backend/core/roles.py` + `permissions.py` |
| Editable settings | `backend/core/settings_store.py` |
| Navigation / app frame | `frontend/src/layout/AppShell.jsx` |
| Shared UI primitives | `frontend/src/components/ui.jsx` |

**One thing worth understanding before you touch the ML.** The risk model scores
*only* companies that cycle detection already surfaced. That boundary is
deliberate — an earlier version scored every company and hit a perfect ROC AUC
of 1.0 by simply relearning "is this company in a cycle" from the placeholder
feature values that non-loop companies carry. Impressive number, zero
information. If you widen what gets scored, you will reintroduce that bug.
`candidate_company_ids()` in `risk_scoring.py` has the full explanation.

**And a claim to be careful with.** Our held-out ROC AUC is 0.9999. Do not
present that as real-world accuracy — our fraud comes from a known generative
process, so a model with 17 features separates it almost perfectly. What it
demonstrates is that the pipeline is wired correctly. Section 12 of
`docs/UNDERSTAND_ME.md` has honest answers ready for judges who push on this.

---

## Further reading

**[docs/UNDERSTAND_ME.md](docs/UNDERSTAND_ME.md)** — the full technical
walkthrough: how Tarjan and Johnson work in words, what each of the 17 risk
features means and why it signals fraud, how the hash chain works and what it
does *not* protect against, a two-minute judge pitch with answers to likely
pushback, an honest limitations section covering what production would
require, and a full tech stack breakdown at the end.

**[docs/10-year-old explanation of all the backend that is happening.md](docs/10-year-old%20explanation%20of%20all%20the%20backend%20that%20is%20happening.md)**
— every part of the backend in plain English, no maths and no jargon: what the
fraud actually is, why a ring is a loop and a mill is a star, how Tarjan and
Johnson work as an idea, what XGBoost and SHAP are really doing, what the audit
ledger can and cannot protect against, and exactly what goes in the
supervisor's report and where it is sent. Start here if the technical
walkthrough is heavy going — or if you need to explain the project to someone
in two minutes.
