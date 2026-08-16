# CodeNova — GST Fraud Ring Detection

**SIH26_95** · Detecting circular-trade GST Input Tax Credit fraud by modelling
companies as a graph, finding closed invoice loops, ranking them with machine
learning, and recording officer-confirmed rings in a tamper-evident ledger.

Shell companies issue fake invoices in a circle — A bills B, B bills C, C bills
A — so every participant can claim Input Tax Credit on purchases that never
happened. No goods move; only paper and refunds. Each individual filing looks
clean, which is exactly why rule-based invoice matching misses it. The fraud is
only visible in the *shape* of the network.

> **On the data:** real GSTN invoice data is confidential and not publicly
> accessible, so this project ships a synthetic trade-network generator with
> deliberately injected fraud rings. That is an intentional part of the design,
> not a shortcut: because the ground truth is known, the detector's accuracy can
> actually be measured. See [docs/UNDERSTAND_ME.md](docs/UNDERSTAND_ME.md).

---

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11, Django 5, Django REST Framework |
| Database | PostgreSQL 16 |
| Graph | NetworkX — Tarjan's SCC pre-filter + Johnson's simple-cycle enumeration |
| ML | scikit-learn, XGBoost (risk scoring), SHAP (explainability) |
| Data generation | Faker, pandas, numpy |
| Audit ledger | Custom SHA-256 hash chain in plain Python — no external blockchain, no network |
| Frontend | React 18, Vite, Cytoscape.js, Axios, TailwindCSS |
| Orchestration | Docker Compose — `postgres`, `backend`, `frontend` |

There is no Celery, Redis or task queue. Graph rebuilding, cycle detection and
scoring all run synchronously; at demo scale detection takes milliseconds and
scoring a couple of seconds, so a job queue would add moving parts for no
benefit. A test asserts detection stays fast enough for that to hold.

---

## Prerequisites

- Docker and Docker Compose

Nothing else. Python, Node and PostgreSQL all run inside containers.

---

## Setup

```bash
cp .env.example .env
docker-compose up --build
```

Then, in a second terminal:

```bash
docker-compose exec backend python manage.py migrate
docker-compose exec backend python manage.py seed_demo_data
```

That's it. A pretrained risk model is committed to the repository, so there is
no training step — scoring works immediately.

| Service | URL |
|---|---|
| Frontend dashboard | http://localhost:5173 |
| Backend API | http://localhost:8000/api/ |
| Django admin | http://localhost:8000/admin/ |

---

## How to demo it

1. **Open the dashboard** at http://localhost:5173. The header shows ~220
   companies and ~3,700 invoices seeded, and zero loops found so far.

2. **Click "Run detection".** This rebuilds the trade graph, runs cycle
   detection, then scores every candidate. It takes a few seconds.
   - "Loops found" jumps to ~33. That is *every* closed loop in the network —
     including genuine two-way trade, which also forms cycles.
   - "High risk" settles on **7**. Those are the 7 fraud rings that were
     actually injected. The other ~26 loops are honest reciprocal trade the
     model correctly pushed to the bottom.

3. **Click the top alert.** The graph dims everything except that ring and
   highlights the hops that close the loop. The right panel explains *why* it
   was flagged, in sentences — recent registration, invoice value far above
   declared turnover, missing e-way bills, near-identical amounts circling the
   loop. Below that are the member companies and the exact invoices involved.

4. **Scroll to the bottom of the alerts feed.** Those loops score near zero:
   established distributors doing genuine two-way trade. This contrast is the
   point — cycle detection alone would have flagged all 33 equally.

5. **Click "Confirm as fraudulent".** The evidence bundle is written to the
   audit ledger as a new block. The view switches to the ledger tab, where the
   new block's "links to" value is literally the previous block's hash.

6. **Check the ledger banner** — "CHAIN INTACT". To see it work the other way,
   edit any block's payload directly in the database; `GET /api/ledger/verify/`
   and the dashboard header will both report the chain as BROKEN and name the
   block that was disturbed.

---

## API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/companies/` | Companies (paginated, `?search=`) |
| GET | `/api/companies/{id}/` | Company + risk score + explanation + ring membership |
| GET | `/api/invoices/` | Invoices (paginated, `?company=` / `?seller=` / `?buyer=`) |
| POST | `/api/fraud/rebuild-graph/` | Rebuild graph, run cycle detection, store rings |
| POST | `/api/fraud/score/` | Feature engineering + XGBoost + SHAP over current rings |
| GET | `/api/fraud/rings/` | Flagged rings, highest risk first |
| GET | `/api/fraud/rings/{id}/` | Ring detail: companies, invoices, score, explanation |
| POST | `/api/fraud/rings/{id}/confirm/` | Officer confirms → appends a ledger block |
| GET | `/api/fraud/status/` | Dashboard summary counters |
| GET | `/api/fraud/graph/` | Whole network in one Cytoscape-shaped payload |
| GET | `/api/ledger/blocks/` | All ledger blocks |
| GET | `/api/ledger/verify/` | Walk the chain, report whether it is intact |

---

## Tests

```bash
docker-compose exec backend python manage.py test
```

30 tests covering cycle detection (including that every injected ring is
recovered across multiple generator seeds), risk scoring (including that fraud
rings outrank benign loops), and the ledger (including that tampering is
detected even when the forger recomputes the edited block's own hash).

## Retraining the model

Optional — a trained artifact is already committed.

```bash
docker-compose exec backend python manage.py train_risk_model
```

Training generates its own fresh synthetic networks and never reads the demo
database, so the shipped model has not memorised the data it scores.

---

## Running without Docker

Useful for running the test suite on a laptop with no Postgres:

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
export USE_SQLITE=True
python manage.py migrate && python manage.py seed_demo_data
python manage.py runserver
```

```bash
cd frontend && npm install && npm run dev
```

---

## Documentation

[docs/UNDERSTAND_ME.md](docs/UNDERSTAND_ME.md) is a full plain-English
walkthrough: the problem, the architecture, how cycle detection works, what
every risk feature means and why it signals fraud, what the ledger does, how to
pitch it to a judge in two minutes, and an honest account of the limitations.
