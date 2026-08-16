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
13. [Notes for collaborators](#13-notes-for-collaborators)

---

## 1. What this project does

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
        └─ 4. MAKE IT STICK
              When an officer confirms a ring, the evidence goes into a
              SHA-256 hash chain. Edit any past record and every block after
              it breaks, and we can say exactly which one.
```

### About the data

Real GSTN invoice data is confidential taxpayer information behind government
data-sharing agreements — there is no legitimate way to obtain it. **This
project generates its own synthetic trade network with fraud rings injected on
purpose.** That is a deliberate design decision, not a shortcut: because we know
the ground truth, we can actually measure whether the detector works. Nothing is
hardcoded to the synthetic data — swap in real companies and invoices and the
whole pipeline runs unchanged.

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
docker-compose exec backend python manage.py seed_demo_data
```

You should see something like:

```
Seeded 220 companies and 3691 invoices.
  Injected fraud rings   : 7 (sizes [3, 3, 5, 4, 4, 4, 3])
  Injected benign loops  : 20 (genuine two-way trade, should NOT be flagged as fraud)
```

**Done.** Open http://localhost:5173

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
python manage.py seed_demo_data
python manage.py runserver
```

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

## 6. Check it actually worked

### Run the test suite

```bash
# Docker
docker-compose exec backend python manage.py test

# No Docker (venv active, USE_SQLITE set)
cd backend && python manage.py test
```

Expect **30 tests, OK**, in roughly 13 seconds. They cover cycle detection
(every injected ring is recovered across multiple generator seeds), risk scoring
(fraud rings outrank benign loops), and the ledger (tampering is detected even
when the forger recomputes the edited block's own hash).

### Check the API is alive

```bash
curl http://localhost:8000/api/fraud/status/
```

Should report `"companies": 220` and `"invoices": 3691`.

### Check the dashboard

Open http://localhost:5173. The header should show **220 companies**, **3691
invoices**, **Loops found 0**, **Ledger Intact**. If it shows an error bar
saying it can't reach the API, the backend isn't running.

---

## 7. How to demo it

This is the walkthrough to give a judge. It takes about two minutes.

1. **Open the dashboard.** Header shows ~220 companies and ~3,700 invoices
   seeded, zero loops found so far.

2. **Click "Run detection".** This rebuilds the graph, runs cycle detection,
   then scores every candidate. Takes a few seconds.
   - **"Loops found" jumps to ~33.** That's *every* closed loop in the network
     — including genuine two-way trade, which also forms cycles.
   - **"High risk" settles on 7.** Those are the 7 fraud rings actually
     injected. The other ~26 loops are honest reciprocal trade the model
     correctly pushed to the bottom.

3. **Click the top alert.** The graph dims everything except that ring and
   highlights the hops closing the loop. The right panel explains *why* in
   sentences — recent registration, invoice value far above declared turnover,
   missing e-way bills, near-identical amounts circling the loop. Below that:
   the member companies and the exact invoices involved.

4. **Scroll to the bottom of the alerts feed.** Those loops score near zero —
   established distributors doing genuine two-way trade. **This contrast is the
   whole point.** Cycle detection alone would have flagged all 33 equally,
   putting 26 honest businesses under investigation.

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

## 8. What gets downloaded

So nobody is surprised by the install size or wonders what a package is for.

### Python packages (`backend/requirements.txt`)

| Package | Why it's here |
|---|---|
| `Django`, `djangorestframework` | Web framework and REST API |
| `django-cors-headers`, `django-filter` | Cross-origin requests from the React dev server; queryset filtering |
| `psycopg2-binary` | PostgreSQL driver |
| `python-dotenv` | Reads `.env` |
| `Faker`, `pandas`, `numpy` | Synthetic data generation and the feature pipeline |
| `networkx` | The graph — Tarjan's SCC and Johnson's cycle enumeration |
| `scikit-learn`, `xgboost` | Risk model training and inference |
| `shap` | Explainability (pulls in `numba` + `llvmlite`, which are large) |

Roughly **700 MB – 1 GB** installed, mostly `xgboost`, `shap`, `numba` and
`scipy`. This is normal for a data-science stack.

### JavaScript packages (`frontend/package.json`)

| Package | Why it's here |
|---|---|
| `react`, `react-dom` | UI |
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
- **Any dataset.** The data is generated by `manage.py seed_demo_data`.
- **Any API keys, accounts or credentials.** Everything runs offline and local.

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
│   ├── core/                   # ── APP 1: the base data model ──
│   │   ├── models.py           #    Company (nodes) + Invoice (edges)
│   │   ├── serializers.py
│   │   ├── views.py
│   │   └── management/commands/
│   │       └── seed_demo_data.py   # the synthetic network generator
│   │
│   └── fraud_engine/           # ── APP 2: everything detection-related ──
│       ├── graph_builder.py    #    DB → NetworkX DiGraph
│       ├── cycle_detection.py  #    Tarjan SCC pre-filter + Johnson's
│       ├── risk_scoring.py     #    features → XGBoost → SHAP explanations
│       ├── ledger.py           #    SHA-256 hash chain
│       ├── models.py           #    FlaggedRing, RiskScore, LedgerBlock
│       ├── views.py            #    all fraud API endpoints
│       ├── tests.py            #    30 tests in 3 classes
│       ├── models_artifacts/   #    the committed pretrained model
│       └── management/commands/
│           └── train_risk_model.py  # optional retraining
│
├── frontend/
│   ├── package.json
│   └── src/
│       ├── api.js              # axios instance + every API call
│       ├── Dashboard.jsx       # three-pane layout + all state
│       └── components/
│           ├── AlertsFeed.jsx      # ranked work queue (left)
│           ├── GraphView.jsx       # Cytoscape network (centre)
│           ├── CompanyDetail.jsx   # evidence panel (right)
│           └── LedgerViewer.jsx    # audit chain
│
└── docs/
    └── UNDERSTAND_ME.md        # full technical walkthrough
```

Two Django apps, deliberately: `core` holds the data, `fraud_engine` holds the
detection. Each is short enough to read top to bottom.

---

## 10. API reference

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/companies/` | Companies (paginated, `?search=`, `?page_size=`) |
| GET | `/api/companies/{id}/` | Company + risk score + explanation + ring membership |
| GET | `/api/invoices/` | Invoices (`?company=` / `?seller=` / `?buyer=`) |
| POST | `/api/fraud/rebuild-graph/` | Rebuild graph, run cycle detection, store rings |
| POST | `/api/fraud/score/` | Feature engineering + XGBoost + SHAP over current rings |
| GET | `/api/fraud/rings/` | Flagged rings, highest risk first |
| GET | `/api/fraud/rings/{id}/` | Ring detail: companies, invoices, score, explanation |
| POST | `/api/fraud/rings/{id}/confirm/` | Officer confirms → appends a ledger block |
| GET | `/api/fraud/status/` | Dashboard summary counters |
| GET | `/api/fraud/graph/` | Whole network in one Cytoscape-shaped payload |
| GET | `/api/ledger/blocks/` | All ledger blocks |
| GET | `/api/ledger/verify/` | Walk the chain, report whether it's intact |

Driving the pipeline without the UI:

```bash
curl -X POST http://localhost:8000/api/fraud/rebuild-graph/
curl -X POST http://localhost:8000/api/fraud/score/
curl http://localhost:8000/api/fraud/rings/
curl -X POST http://localhost:8000/api/fraud/rings/1/confirm/
curl http://localhost:8000/api/ledger/verify/
```

There is **no authentication** — every endpoint is open. That is fine for a
prototype and unacceptable for production; see the limitations section of
`docs/UNDERSTAND_ME.md`.

---

## 11. Everyday commands

Prefix with `docker-compose exec backend` on Path A; run inside `backend/` with
your venv active on Path B.

| Task | Command |
|---|---|
| Reset and regenerate all demo data | `python manage.py seed_demo_data` |
| Generate a *different* network | `python manage.py seed_demo_data --seed 7` |
| Bigger network | `python manage.py seed_demo_data --companies 400 --rings 12` |
| Run the tests | `python manage.py test` |
| Run one test class | `python manage.py test fraud_engine.tests.LedgerTests` |
| Retrain the model (optional) | `python manage.py train_risk_model` |
| Apply new migrations | `python manage.py migrate` |
| After changing a model | `python manage.py makemigrations` |
| Create an admin login | `python manage.py createsuperuser` |

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

**"Loops found" is 33 but everything shows UNSCORED**
Detection ran but scoring didn't. The "Run detection" button does both; if you
called `/rebuild-graph/` directly via curl, follow it with `/score/`.

**`pip install` fails on `shap` or `numba`**
Almost always a too-new Python. `numba` lags new releases by months. Use Python
3.11 or 3.12.

**Setup caveat, stated honestly:** the no-Docker path (Path B) is the one that's
been exercised end to end on this codebase. The Docker path is standard and its
config is validated, but if you're the first person to run `docker-compose up`
and something snags, it's more likely an environment issue than a code one —
shout and we'll fix it in a commit.

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
- Run `python manage.py test` before pushing. All 30 should pass.
- The generator is seeded, so `seed_demo_data` is reproducible: same seed, same
  network. Use `--seed N` if you want to test against a different one.
- Retraining is deterministic too — `train_risk_model` regenerates a
  byte-identical artifact, so it won't show up as a spurious diff. If it *does*
  produce a diff, something upstream genuinely changed (a feature, the
  generator, or an XGBoost version) and that's worth understanding before you
  commit it.

**Where to make changes**

| You want to change... | Go to |
|---|---|
| What the synthetic data looks like | `backend/core/management/commands/seed_demo_data.py` |
| How cycles are found | `backend/fraud_engine/cycle_detection.py` |
| Risk features or the model | `backend/fraud_engine/risk_scoring.py` |
| The plain-English explanation wording | `_describe()` in `risk_scoring.py` |
| API endpoints | `backend/fraud_engine/views.py` + `urls.py` |
| The dashboard layout | `frontend/src/Dashboard.jsx` |
| The graph's look | `frontend/src/components/GraphView.jsx` |

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
demonstrates is that the pipeline is wired correctly. Section 11 of
`docs/UNDERSTAND_ME.md` has honest answers ready for judges who push on this.

---

## Further reading

**[docs/UNDERSTAND_ME.md](docs/UNDERSTAND_ME.md)** — the full technical
walkthrough: how Tarjan and Johnson work in words, what each of the 17 risk
features means and why it signals fraud, how the hash chain works and what it
does *not* protect against, a two-minute judge pitch with answers to likely
pushback, and an honest limitations section covering what production would
require.
