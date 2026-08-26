"""
Dataset Lab: a fabricated GST trade network with a *controllable* risk mix.

WHY THIS EXISTS, AND WHY IT IS NOT `synthetic_network.py`
--------------------------------------------------------
`synthetic_network.py` is a training tool. Its job is to hand the XGBoost
trainer labelled shells, so it optimises for one thing: a clean fraud/not-fraud
split with enough hard cases that the model cannot cheat.

This module has a different job. It builds datasets for *people* - for a demo,
for a screenshot, for testing the console end to end - and the thing that makes
those useful is a spread. A dataset where every alert scores 95 tells you
nothing about whether the queue is usable, and neither does one where every
alert scores 8. What an officer's screen actually looks like in the field is a
handful of obvious cases, a pile of genuinely ambiguous ones, and a long tail
of honest businesses that merely look odd.

So the lab generates four bands on purpose:

  high    - textbook fraud. Circular-trade rings between shell companies, and
            fake invoice mills. Every tell present: shared addresses and
            directors, no e-way bills, turnover declared at a fraction of what
            was invoiced, round amounts, companies registered months ago.

  medium  - the grey zone, and the whole reason a human is in this loop. Real
            loops and real lopsided sellers, but with only one or two flags
            each: patchy e-way coverage, a partial under-declaration, one
            director shared between two members. Reasonable people disagree
            about these.

  low     - honest businesses that are structurally suspicious. Genuine
            two-way trade, mutual stock transfers between retailers,
            distributor pairs that buy and sell from each other. These form
            REAL cycles. Cycle detection alone would flag every one of them,
            which is precisely why the risk model exists.

  clean   - the background economy. A tiered supply chain that, by
            construction, contains no loops at all.

WHAT IS AND IS NOT GUARANTEED
-----------------------------
The band written into the answer key is what a company was *planted* as. It is
not a promise about the score it will receive - the score is whatever the real
model says, and the lab does not get to overrule it. `analyse()` runs the
actual detection pipeline over the generated data and reports the scores that
came out, so the two can be compared honestly. When they disagree, that is a
finding about the detector, not a bug in the generator.

NOTHING HERE IS REAL
--------------------
Every GSTIN, name, address and amount is fabricated. No real taxpayer data is
used, referenced, or reachable from this module.
"""
from __future__ import annotations

import csv
import io
import math
import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

import pandas as pd
from faker import Faker

from core.csv_import import TRUE_STRINGS

from .synthetic_network import (
    FRAUD_GOODS,
    RECIPROCAL_GOODS,
    TIER_GOODS,
    _log_uniform,
    _make_gstin,
    _make_pan,
    _random_date,
    build_synthetic_network,
)

# --------------------------------------------------------------------------
# Bands
# --------------------------------------------------------------------------

BAND_HIGH = "high"
BAND_MEDIUM = "medium"
BAND_LOW = "low"
BAND_CLEAN = "clean"
BAND_ORDER = [BAND_HIGH, BAND_MEDIUM, BAND_LOW, BAND_CLEAN]

BAND_LABELS = {
    BAND_HIGH: "High risk",
    BAND_MEDIUM: "Grey zone",
    BAND_LOW: "Suspicious but honest",
    BAND_CLEAN: "Ordinary trade",
}

BAND_BLURBS = {
    BAND_HIGH: "Planted fraud with the full pattern. The detector should catch these.",
    BAND_MEDIUM: "One or two flags each. These are the cases that need an officer.",
    BAND_LOW: "Genuine businesses that form real loops. False positives if flagged.",
    BAND_CLEAN: "Ordinary supply-chain trade. Contains no loops by construction.",
}

# A generated alert scoring at or above this - but below the department's
# high-risk threshold - is what we mean by "grey zone" when reporting results.
MEDIUM_FLOOR = 40.0

# Hard ceilings. The lab runs synchronously inside a request, and cycle
# enumeration is the expensive part, so the size is bounded rather than trusted.
MAX_COMPANIES = 1200
MIN_COMPANIES = 60
MAX_GROUPS = 25


# --------------------------------------------------------------------------
# The spec
# --------------------------------------------------------------------------


@dataclass
class LabSpec:
    """What to build. Every field is a knob exposed in the lab UI."""

    seed: int = 7
    companies: int = 260
    # High band
    rings: int = 4          # textbook circular-trade rings between shells
    mills: int = 3          # textbook fake invoice mills
    # Medium band
    grey_rings: int = 4     # real loops, partial evidence
    grey_mills: int = 3     # lopsided sellers that only just clear the gates
    # Low band
    honest_loops: int = 9   # genuine two-way trade between real businesses
    name: str = ""

    def clamped(self) -> "LabSpec":
        """Bring a client-supplied spec inside the bounds we will actually run."""

        def cap(value, low, high) -> int:
            try:
                return max(low, min(high, int(value)))
            except (TypeError, ValueError):
                return low

        return LabSpec(
            seed=cap(self.seed, 0, 10**9),
            companies=cap(self.companies, MIN_COMPANIES, MAX_COMPANIES),
            rings=cap(self.rings, 0, MAX_GROUPS),
            mills=cap(self.mills, 0, MAX_GROUPS),
            grey_rings=cap(self.grey_rings, 0, MAX_GROUPS),
            grey_mills=cap(self.grey_mills, 0, MAX_GROUPS),
            honest_loops=cap(self.honest_loops, 0, MAX_GROUPS * 2),
            name=str(self.name or "")[:120],
        )

    @classmethod
    def from_dict(cls, data: dict | None) -> "LabSpec":
        data = data or {}
        base = cls()
        known = {f for f in base.__dataclass_fields__}
        supplied = {k: v for k, v in data.items() if k in known}
        return cls(**{**asdict(base), **supplied}).clamped()

    def as_dict(self) -> dict:
        return asdict(self)


PRESETS = [
    {
        "key": "balanced",
        "label": "Even spread",
        "blurb": "Roughly equal numbers of obvious fraud, grey-zone cases and honest "
                 "look-alikes. The one to use for a demo or a screenshot.",
        "spec": LabSpec(seed=7, companies=280, rings=2, mills=3,
                        grey_rings=6, grey_mills=5, honest_loops=14).as_dict(),
    },
    {
        "key": "quick",
        "label": "Quick demo",
        "blurb": "Small and fast. Generates and runs detection in a few seconds, "
                 "with enough of each kind to show the workflow.",
        "spec": LabSpec(seed=21, companies=120, rings=2, mills=2,
                        grey_rings=2, grey_mills=1, honest_loops=4).as_dict(),
    },
    {
        "key": "haystack",
        "label": "Needle in a haystack",
        "blurb": "What the real world looks like: a large, mostly honest economy "
                 "hiding very little fraud. Tests whether the ranking is any good.",
        "spec": LabSpec(seed=104, companies=900, rings=2, mills=2,
                        grey_rings=5, grey_mills=4, honest_loops=18).as_dict(),
    },
    {
        "key": "no_loops",
        "label": "Fraud without loops",
        "blurb": "No circular trading at all - only invoice mills. Cycle detection "
                 "finds nothing here; it is the mill detector that has to work.",
        "spec": LabSpec(seed=55, companies=240, rings=0, mills=6,
                        grey_rings=0, grey_mills=4, honest_loops=8).as_dict(),
    },
    {
        "key": "grey",
        "label": "All grey zone",
        "blurb": "Almost nothing is clear-cut. Use it to see how the queue reads "
                 "when the officer has to make every call themselves.",
        "spec": LabSpec(seed=88, companies=300, rings=0, mills=0,
                        grey_rings=8, grey_mills=6, honest_loops=12).as_dict(),
    },
]


# --------------------------------------------------------------------------
# The generated dataset
# --------------------------------------------------------------------------

COMPANY_COLUMNS = [
    "gstin", "pan", "name", "director_name", "registered_address",
    "registered_date", "declared_turnover",
]
INVOICE_COLUMNS = [
    "seller_gstin", "buyer_gstin", "amount", "date", "goods_description",
    "has_eway_bill",
]
ANSWER_COLUMNS = ["gstin", "name", "band", "planted_as", "group"]


@dataclass
class LabDataset:
    spec: LabSpec
    companies: list[dict] = field(default_factory=list)
    invoices: list[dict] = field(default_factory=list)
    answer_key: list[dict] = field(default_factory=list)

    def band_counts(self) -> dict[str, int]:
        counts = {band: 0 for band in BAND_ORDER}
        for row in self.answer_key:
            counts[row["band"]] = counts.get(row["band"], 0) + 1
        return counts

    def planted_gstins(self, band: str) -> set[str]:
        return {r["gstin"] for r in self.answer_key if r["band"] == band}

    # ---- serialisation ---------------------------------------------------

    def companies_csv(self) -> str:
        return _to_csv(self.companies, COMPANY_COLUMNS)

    def invoices_csv(self) -> str:
        return _to_csv(self.invoices, INVOICE_COLUMNS)

    def answer_key_csv(self) -> str:
        return _to_csv(self.answer_key, ANSWER_COLUMNS)

    def dataframes(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """The same two frames the pipeline reads out of the database.

        Ids are assigned here in memory so detection can be run over generated
        data without writing a single row.
        """
        id_by_gstin = {c["gstin"]: i for i, c in enumerate(self.companies)}
        companies = pd.DataFrame(
            [{"id": id_by_gstin[c["gstin"]], **c} for c in self.companies]
        )
        invoices = pd.DataFrame(
            [
                {
                    "id": i,
                    "seller_id": id_by_gstin[inv["seller_gstin"]],
                    "buyer_id": id_by_gstin[inv["buyer_gstin"]],
                    "amount": float(inv["amount"]),
                    "date": inv["date"],
                    "goods_description": inv["goods_description"],
                    # Parsed with the importer's own rule, not eyeballed. The
                    # rows here are CSV-shaped, so has_eway_bill is the string
                    # "true"/"false"; a bare astype(bool) would read BOTH as
                    # True (any non-empty string is truthy) and silently zero
                    # out every e-way signal in the preview.
                    "has_eway_bill": str(inv["has_eway_bill"]).strip().lower() in TRUE_STRINGS,
                }
                for i, inv in enumerate(self.invoices)
            ]
        )
        if not companies.empty:
            companies["declared_turnover"] = companies["declared_turnover"].astype(float)
            companies["registered_date"] = pd.to_datetime(companies["registered_date"])
        if not invoices.empty:
            invoices["date"] = pd.to_datetime(invoices["date"])
            invoices["has_eway_bill"] = invoices["has_eway_bill"].astype(bool)
        return companies, invoices


def _to_csv(rows: list[dict], columns: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in columns})
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


def build_lab_dataset(spec: LabSpec, today: date | None = None) -> LabDataset:
    """Build a trade network matching `spec`, with an answer key."""
    spec = spec.clamped()
    today = today or date.today()
    rng = random.Random(spec.seed)
    fake = Faker("en_IN")
    Faker.seed(spec.seed)

    # Leave room for the companies this module adds on top of the base economy.
    added = (
        spec.mills
        + spec.grey_mills
        + spec.grey_rings * 4          # average grey-ring size
    )
    base_size = max(MIN_COMPANIES, spec.companies - added)

    # The honest economy, the textbook rings and the honest-but-loopy traders
    # all come from the training generator: it already models a tiered supply
    # chain, seasonal businesses, sloppy-but-honest filers and hard rings that
    # hide their shared addresses. There is no reason to rebuild that here.
    honest_pairs = max(spec.honest_loops * 4 // 10, 0)
    honest_distributors = max(spec.honest_loops * 3 // 10, 0)
    honest_triangles = max(spec.honest_loops - honest_pairs - honest_distributors, 0)

    net = build_synthetic_network(
        seed=spec.seed,
        n_companies=base_size,
        n_fraud_rings=spec.rings,
        n_benign_pairs=honest_pairs,
        n_benign_distributor_pairs=honest_distributors,
        n_benign_triangles=honest_triangles,
        today=today,
    )

    # ---- label what the base generator produced --------------------------
    for company in net.companies:
        company["_band"] = BAND_CLEAN
        company["_planted"] = "ordinary_trader"
        company["_group"] = ""

    for n, ring in enumerate(net.fraud_rings, start=1):
        for idx in ring:
            net.companies[idx]["_band"] = BAND_HIGH
            net.companies[idx]["_planted"] = "ring_shell"
            net.companies[idx]["_group"] = f"ring-{n}"

    for n, loop in enumerate(net.benign_loops, start=1):
        for idx in loop:
            net.companies[idx]["_band"] = BAND_LOW
            net.companies[idx]["_planted"] = "honest_two_way_trader"
            net.companies[idx]["_group"] = f"honest-loop-{n}"

    tiers: dict[int, list[int]] = {0: [], 1: [], 2: [], 3: []}
    for idx, company in enumerate(net.companies):
        tier = company.get("_tier")
        if tier in tiers:
            tiers[tier].append(idx)

    context = _Context(net=net, rng=rng, fake=fake, today=today, tiers=tiers)

    _add_grey_rings(context, spec.grey_rings)
    _add_mills(context, spec.mills, textbook=True)
    _add_mills(context, spec.grey_mills, textbook=False)

    return _materialise(spec, net)


@dataclass
class _Context:
    net: object
    rng: random.Random
    fake: Faker
    today: date
    tiers: dict[int, list[int]]

    def add_company(self, company: dict) -> int:
        idx = len(self.net.companies)
        self.net.companies.append(company)
        return idx

    def add_invoice(self, seller: int, buyer: int, amount: float, when: date,
                    goods: str, eway: bool) -> None:
        """Record an invoice, refusing to date it before either party existed.

        The trading windows are worked out from the group being planted - a
        mill's own registration, a grey ring's active period - but the
        counterparties are drawn from the wider economy, and a genuine minority
        of those are brand-new businesses. Without this clamp a mill registered
        two years ago cheerfully invoices a company that will not exist for
        another three months, which no importer should accept and no
        investigator would believe.
        """
        if amount < 1_000:
            return

        earliest = max(
            self.net.companies[seller]["registered_date"],
            self.net.companies[buyer]["registered_date"],
        ) + timedelta(days=3)
        if earliest > self.today:
            return  # they never coexisted; there is no invoice to write
        if when < earliest:
            when = _random_date(self.rng, earliest, self.today)

        self.net.invoices.append(
            {
                "seller_idx": seller,
                "buyer_idx": buyer,
                "amount": round(float(amount), 2),
                "date": when,
                "goods_description": goods,
                "has_eway_bill": bool(eway),
            }
        )


def _grey_company(ctx: _Context, *, age_days: tuple[int, int],
                  address: str | None = None, director: str | None = None) -> dict:
    """A company that reads as an established business at first glance."""
    pan = _make_pan(ctx.rng)
    return {
        "gstin": _make_gstin(ctx.rng, pan),
        "pan": pan,
        "name": ctx.fake.company(),
        "director_name": director or ctx.fake.name(),
        "registered_address": address or ctx.fake.address().replace("\n", ", "),
        "registered_date": ctx.today - timedelta(days=ctx.rng.randint(*age_days)),
        # Overwritten once we know what it actually traded.
        "declared_turnover": 0.0,
        "_tier": None,
        "_is_fraud": False,
        "_eway_rate": 0.6,
        "_season_offset": None,
    }


def _add_grey_rings(ctx: _Context, count: int) -> None:
    """
    Loops that are genuinely ambiguous.

    A textbook ring gives itself away six ways at once. These give themselves
    away once or twice, which is what the difficult half of a real queue looks
    like. Concretely: the loop is real and the value does circle, but the
    members are two to six years old, they file most of their e-way bills, they
    declare a believable share of what they invoice, and the hop amounts vary
    the way negotiated prices do rather than repeating to the rupee.

    At most one shared director across the ring, and never a shared address -
    a group with both is not ambiguous, it is a ring.
    """
    rng = ctx.rng
    for n in range(1, count + 1):
        size = rng.randint(3, 5)
        # About half of these groups share one director between two members -
        # a real flag, and on its own not nearly enough to convict.
        shared_director = ctx.fake.name() if rng.random() < 0.5 else None
        members: list[int] = []
        for position in range(size):
            director = shared_director if (shared_director and position < 2) else None
            company = _grey_company(ctx, age_days=(700, 2200), director=director)
            # Patchy but not absent. A small firm with a weak back office looks
            # exactly like this, and so does a ring being careful.
            company["_eway_rate"] = rng.uniform(0.45, 0.78)
            company["_band"] = BAND_MEDIUM
            company["_planted"] = "grey_ring_member"
            company["_group"] = f"grey-ring-{n}"
            members.append(ctx.add_company(company))

        window_end = ctx.today - timedelta(days=rng.randint(5, 60))
        window_start = window_end - timedelta(days=rng.randint(150, 420))

        base_amount = _log_uniform(rng, 3e5, 6e6)
        for _ in range(rng.randint(2, 4)):
            for a, b in zip(members, members[1:] + members[:1]):
                # A wide spread on purpose: nearly-identical hop amounts are one
                # of the strongest ring tells, so grey rings must not have it.
                hop = base_amount * rng.uniform(0.7, 1.35)
                ctx.add_invoice(
                    a, b, hop,
                    _random_date(rng, window_start, window_end),
                    rng.choice(TIER_GOODS[2] + RECIPROCAL_GOODS),
                    rng.random() < ctx.net.companies[a]["_eway_rate"],
                )

        # Ordinary trade on both sides, so the group is not an island.
        for member in members:
            for supplier in rng.sample(ctx.tiers[0], min(rng.randint(3, 7), len(ctx.tiers[0]))):
                ctx.add_invoice(
                    supplier, member, rng.uniform(80_000, 900_000),
                    _random_date(rng, window_start, window_end),
                    rng.choice(TIER_GOODS[0]), rng.random() < 0.85,
                )
            for customer in rng.sample(ctx.tiers[3], min(rng.randint(3, 8), len(ctx.tiers[3]))):
                ctx.add_invoice(
                    member, customer, rng.uniform(60_000, 800_000),
                    _random_date(rng, window_start, window_end),
                    rng.choice(TIER_GOODS[2]),
                    rng.random() < ctx.net.companies[member]["_eway_rate"],
                )


def _add_mills(ctx: _Context, count: int, *, textbook: bool) -> None:
    """
    Fake invoice mills - fraud with no loop in it at all.

    A mill sells to many unrelated buyers and buys from almost nobody, because
    nothing it invoiced ever existed. Its customers are often real businesses
    who simply wanted input credit. That shape is a star, not a cycle, so cycle
    detection cannot see it however long you let it run; `mill_detection.py`
    handles these on its own.

    `textbook=True` produces one with every flag showing. `textbook=False`
    produces one that only just clears the detector's gates: fewer buyers, some
    real purchases behind it, most e-way bills filed. The second kind is what
    an aggressive-but-legal trading intermediary also looks like.
    """
    rng = ctx.rng
    buyer_pool = ctx.tiers[1] + ctx.tiers[2] + ctx.tiers[3]
    if not buyer_pool:
        return

    for n in range(1, count + 1):
        if textbook:
            age = (35, 320)
            n_buyers = rng.randint(12, 30)
            eway_rate = rng.uniform(0.02, 0.18)
            coverage = rng.uniform(0.02, 0.12)     # declares 2-12% of what it bills
            purchase_share = rng.uniform(0.0, 0.06)
            round_share = rng.uniform(0.6, 0.95)
            sales_total = _log_uniform(rng, 2.5e6, 9e7)
            band, planted = BAND_HIGH, "invoice_mill"
            group = f"mill-{n}"
            goods = FRAUD_GOODS
        else:
            # Tuned to land either side of the mill detector's reporting
            # threshold rather than comfortably above it. Some of these will
            # score below it and never be reported at all - that is not a bug
            # in the generator, it is what the threshold costs, and seeing it
            # is the point of being able to plant them.
            age = (380, 950)
            n_buyers = rng.randint(8, 16)
            eway_rate = rng.uniform(0.35, 0.62)
            coverage = rng.uniform(0.18, 0.45)
            # It did buy something, unlike a real mill - just nowhere near
            # enough to account for what it sold.
            purchase_share = rng.uniform(0.05, 0.13)
            round_share = rng.uniform(0.25, 0.5)
            sales_total = _log_uniform(rng, 1.5e6, 1.6e7)
            band, planted = BAND_MEDIUM, "grey_mill"
            group = f"grey-mill-{n}"
            goods = TIER_GOODS[2] + ["Trading goods - assorted"]

        company = _grey_company(ctx, age_days=age)
        company["_eway_rate"] = eway_rate
        company["_band"] = band
        company["_planted"] = planted
        company["_group"] = group
        company["declared_turnover"] = round(sales_total * coverage, 2)
        mill = ctx.add_company(company)

        window_end = ctx.today - timedelta(days=rng.randint(2, 45))
        earliest = company["registered_date"] + timedelta(days=5)
        window_start = max(earliest, window_end - timedelta(days=rng.randint(60, 300)))
        if window_start >= window_end:
            window_start = earliest
            window_end = min(ctx.today, earliest + timedelta(days=30))

        buyers = rng.sample(buyer_pool, min(n_buyers, len(buyer_pool)))
        weights = [rng.uniform(0.4, 1.6) for _ in buyers]
        total_weight = sum(weights) or 1.0

        for buyer, weight in zip(buyers, weights):
            share = sales_total * weight / total_weight
            for _ in range(rng.randint(1, 3)):
                amount = share * rng.uniform(0.6, 1.4) / 2
                if rng.random() < round_share:
                    amount = round(amount, -4)
                ctx.add_invoice(
                    mill, buyer, amount,
                    _random_date(rng, window_start, window_end),
                    rng.choice(goods), rng.random() < eway_rate,
                )

        # Whatever purchases it books, so the sales/purchase ratio lands where
        # this kind of mill is supposed to land.
        purchase_total = sales_total * purchase_share
        if purchase_total > 0 and ctx.tiers[0]:
            suppliers = rng.sample(ctx.tiers[0], min(rng.randint(1, 4), len(ctx.tiers[0])))
            for supplier in suppliers:
                ctx.add_invoice(
                    supplier, mill, purchase_total / len(suppliers),
                    _random_date(rng, window_start, window_end),
                    rng.choice(TIER_GOODS[0]), rng.random() < 0.9,
                )


def _materialise(spec: LabSpec, net) -> LabDataset:
    """Turn index-keyed generator output into GSTIN-keyed CSV rows."""
    # Grey-ring members declare a believable but incomplete share of what they
    # invoiced. Doing it here, after all trade exists, is the only point where
    # the real figure is known.
    sold: dict[int, float] = {}
    for inv in net.invoices:
        sold[inv["seller_idx"]] = sold.get(inv["seller_idx"], 0.0) + inv["amount"]

    rng = random.Random(spec.seed ^ 0x5EED)
    for idx, company in enumerate(net.companies):
        if company.get("_planted") != "grey_ring_member":
            continue
        traded = sold.get(idx, 0.0)
        company["declared_turnover"] = round(traded * rng.uniform(0.4, 0.75), 2)

    companies = [
        {
            "gstin": c["gstin"],
            "pan": c["pan"],
            "name": c["name"],
            "director_name": c["director_name"],
            "registered_address": c["registered_address"],
            "registered_date": c["registered_date"].isoformat(),
            "declared_turnover": f"{float(c['declared_turnover']):.2f}",
        }
        for c in net.companies
    ]

    gstin_of = [c["gstin"] for c in net.companies]
    invoices = [
        {
            "seller_gstin": gstin_of[inv["seller_idx"]],
            "buyer_gstin": gstin_of[inv["buyer_idx"]],
            "amount": f"{float(inv['amount']):.2f}",
            "date": inv["date"].isoformat(),
            "goods_description": inv["goods_description"],
            "has_eway_bill": "true" if inv["has_eway_bill"] else "false",
        }
        for inv in net.invoices
    ]
    invoices.sort(key=lambda row: row["date"])

    answer_key = [
        {
            "gstin": c["gstin"],
            "name": c["name"],
            "band": c.get("_band", BAND_CLEAN),
            "planted_as": c.get("_planted", "ordinary_trader"),
            "group": c.get("_group", ""),
        }
        for c in net.companies
    ]

    return LabDataset(spec=spec, companies=companies, invoices=invoices,
                      answer_key=answer_key)


# --------------------------------------------------------------------------
# Running the real detector over generated data
# --------------------------------------------------------------------------


def analyse(dataset: LabDataset) -> dict:
    """
    Run the actual detection pipeline over a generated dataset, in memory.

    This is the honest half of the lab. The answer key says what each company
    was *planted* as; this says what the detector actually *found*. Nothing
    here is simulated or approximated - it is the same graph builder, the same
    cycle detection, the same mill rules and the same XGBoost model that a
    detection run uses, called with DataFrames instead of database rows.

    Nothing is written to the database.
    """
    from .cycle_detection import detect_rings
    from .graph_builder import build_graph_from_dataframes
    from .mill_detection import detect_mills
    from .risk_scoring import ring_risk, score_network
    from .settings_helpers import max_ring_size, mill_min_score, risk_threshold

    threshold = risk_threshold()
    companies, invoices = dataset.dataframes()
    if companies.empty:
        return {"alerts": [], "score_bands": {}, "scorecard": {}, "threshold": threshold}

    band_by_id: dict[int, str] = {}
    group_by_id: dict[int, str] = {}
    name_by_id: dict[int, str] = {}
    for i, row in enumerate(dataset.answer_key):
        band_by_id[i] = row["band"]
        group_by_id[i] = row["group"]
        name_by_id[i] = row["name"]

    # The same two-graph split the pipeline uses: features from the invoice-only
    # graph the model was trained on, alerts from the control-augmented one.
    trade_graph = build_graph_from_dataframes(companies, invoices)
    feature_rings = detect_rings(trade_graph, max_length=max_ring_size())

    graph = build_graph_from_dataframes(companies, invoices, include_control_edges=True)
    rings = detect_rings(graph, max_length=max_ring_size())
    mills = detect_mills(companies, invoices, min_score=mill_min_score())
    scores = score_network(companies, invoices, feature_rings)

    alerts: list[dict] = []
    for evidence in rings:
        score, explanation = ring_risk(evidence, scores)
        alerts.append(
            _alert_row(evidence, float(score), explanation, "ring",
                       band_by_id, group_by_id, name_by_id, threshold)
        )
    for evidence in mills:
        alerts.append(
            _alert_row(evidence, float(evidence["risk_score"]),
                       evidence["explanation"], "mill",
                       band_by_id, group_by_id, name_by_id, threshold)
        )

    alerts.sort(key=lambda a: -a["risk_score"])

    score_bands = {BAND_HIGH: 0, BAND_MEDIUM: 0, BAND_LOW: 0}
    for alert in alerts:
        score_bands[alert["score_band"]] += 1

    return {
        "threshold": threshold,
        "alerts": alerts,
        "score_bands": score_bands,
        "scorecard": _scorecard(dataset, alerts, threshold),
        "graph": {
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
        },
    }


def _alert_row(evidence: dict, score: float, explanation: list[dict], kind: str,
               band_by_id, group_by_id, name_by_id, threshold: float) -> dict:
    members = [int(c) for c in evidence.get("company_ids", [])]

    # A mill alert lists the mill first and then everyone who bought from it.
    # Those buyers are mostly honest businesses that were sold a fake invoice,
    # so crediting the alert to their planted group would be wrong: the
    # accusation is against the seller alone.
    if kind == "mill" and evidence.get("mill_company_id") is not None:
        accused = [int(evidence["mill_company_id"])]
    else:
        accused = members

    bands = [band_by_id.get(m, BAND_CLEAN) for m in accused]
    groups = sorted({group_by_id.get(m, "") for m in accused} - {""})

    # What the alert is really about: the strongest band any accused member was
    # planted as. A loop containing one planted shell is a hit even if its other
    # members are ordinary businesses caught up in it.
    truth = BAND_CLEAN
    for band in BAND_ORDER:
        if band in bands:
            truth = band
            break

    return {
        "kind": kind,
        "closure": evidence.get("closure", "invoice"),
        "risk_score": round(score, 2),
        "score_band": _score_band(score, threshold),
        "size": len(members),
        "value": round(float(evidence.get("total_cycle_value", 0.0)), 2),
        "invoice_count": int(evidence.get("invoice_count", 0) or 0),
        "members": [name_by_id.get(m, str(m)) for m in members[:4]],
        "planted_band": truth,
        "planted_groups": groups[:3],
        "reason": (explanation[0]["text"] if explanation else ""),
    }


def _score_band(score: float, threshold: float) -> str:
    if score >= threshold:
        return BAND_HIGH
    if score >= MEDIUM_FLOOR:
        return BAND_MEDIUM
    return BAND_LOW


def _scorecard(dataset: LabDataset, alerts: list[dict], threshold: float) -> dict:
    """
    How the detector did against the answer key.

    Two numbers matter and they pull against each other: how much of the
    planted fraud was surfaced at all, and how many honest businesses were
    pushed over the high-risk line. A generator that only reported the first
    would be marking its own homework.
    """
    planted_groups: dict[str, str] = {}
    for row in dataset.answer_key:
        if row["group"] and row["band"] in (BAND_HIGH, BAND_MEDIUM):
            planted_groups[row["group"]] = row["band"]

    surfaced = {g for alert in alerts for g in alert["planted_groups"]}
    high_groups = [g for g, b in planted_groups.items() if b == BAND_HIGH]
    medium_groups = [g for g, b in planted_groups.items() if b == BAND_MEDIUM]

    false_alarms = [
        a for a in alerts
        if a["risk_score"] >= threshold and a["planted_band"] in (BAND_LOW, BAND_CLEAN)
    ]

    return {
        "high_planted": len(high_groups),
        "high_found": sum(1 for g in high_groups if g in surfaced),
        "medium_planted": len(medium_groups),
        "medium_found": sum(1 for g in medium_groups if g in surfaced),
        "false_alarms": len(false_alarms),
        "alerts_total": len(alerts),
    }


def summarise(dataset: LabDataset) -> dict:
    """Composition of the generated data itself, before any detection runs."""
    total_value = sum(float(inv["amount"]) for inv in dataset.invoices)
    no_eway = sum(1 for inv in dataset.invoices if inv["has_eway_bill"] == "false")
    dates = [inv["date"] for inv in dataset.invoices]

    groups: dict[str, dict] = {}
    for row in dataset.answer_key:
        if not row["group"]:
            continue
        entry = groups.setdefault(
            row["group"], {"group": row["group"], "band": row["band"],
                           "planted_as": row["planted_as"], "members": 0}
        )
        entry["members"] += 1

    return {
        "companies": len(dataset.companies),
        "invoices": len(dataset.invoices),
        "total_value": round(total_value, 2),
        "missing_eway": no_eway,
        "first_invoice": min(dates) if dates else "",
        "last_invoice": max(dates) if dates else "",
        "bands": dataset.band_counts(),
        "band_labels": BAND_LABELS,
        "band_blurbs": BAND_BLURBS,
        "groups": sorted(groups.values(), key=lambda g: (BAND_ORDER.index(g["band"]), g["group"])),
    }


def readme_text(dataset: LabDataset, generated_at: str) -> str:
    """The note that ships inside the download, so the files explain themselves."""
    spec = dataset.spec
    counts = dataset.band_counts()
    return f"""CodeNova - generated test dataset
=================================
Generated {generated_at} by the Dataset Lab.

THIS IS FABRICATED DATA. Every GSTIN, company name, director, address, amount
and date in these files was made up by a random number generator seeded with
{spec.seed}. No real taxpayer information was used to produce it and none is
contained in it.

FILES
-----
companies.csv    {len(dataset.companies)} rows. Upload this as the companies file.
invoices.csv     {len(dataset.invoices)} rows. Upload this as the invoices file.
answer_key.csv   What each company was planted as. NOT an input - keep it out
                 of the console, it is for checking results afterwards.

WHAT WAS PLANTED
----------------
  {counts.get('high', 0):>4} companies  high risk    - {spec.rings} circular-trade rings, {spec.mills} invoice mills
  {counts.get('medium', 0):>4} companies  grey zone    - {spec.grey_rings} ambiguous loops, {spec.grey_mills} borderline sellers
  {counts.get('low', 0):>4} companies  honest loops - {spec.honest_loops} genuine two-way traders
  {counts.get('clean', 0):>4} companies  ordinary trade

The band is what the company was BUILT as, not what the detector scored it.
Comparing the two is the point of the exercise.

TO USE
------
Detections -> Upload dataset -> companies.csv and invoices.csv -> Run detection.

Regenerating with seed {spec.seed} and the same settings produces these exact
files again.
"""
