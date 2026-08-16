"""
Synthetic GST trade-network generator + database seeder.

WHY SYNTHETIC DATA
------------------
Real GSTN invoice data is not publicly accessible; it is confidential taxpayer
information behind government data-sharing agreements. So this project ships a
generator that builds a realistic company/invoice network *with known ground
truth* about which companies are fraudulent. That is not a compromise, it is a
feature: because we know the answer, we can measure whether the detector
actually finds the rings it is supposed to find.

HOW THE NETWORK IS SHAPED
-------------------------
1. Legitimate trade is a DAG. Every honest company sits in a supply-chain tier
   (0 raw material -> 1 component maker -> 2 distributor -> 3 retailer) and
   invoices only flow to a strictly higher tier. A strictly-increasing tier
   means the honest sub-graph mathematically cannot contain a cycle.

2. Benign reciprocal loops are injected on purpose. Genuine businesses do
   sometimes trade both ways (a retailer sells returns and scrap back to its
   distributor; three retailers do mutual stock transfers). These create *real*
   cycles that are *not* fraud. Without them, "is in a cycle" would perfectly
   predict fraud and the ML model would be a pointless rubber stamp.

3. Fraud rings are injected as closed circular-trade loops of 3-6 shell
   companies, carrying the fingerprints investigators actually look for:
   shared registered addresses and directors, invoice value far exceeding
   declared turnover, missing e-way bills, near-identical amounts circling the
   loop, and very recent registration.

So cycle detection narrows ~220 companies down to ~25 candidate rings, and the
ML model's real job is separating the fraudulent loops from the benign ones.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from faker import Faker

from core.models import Company, Invoice

# --------------------------------------------------------------------------
# Generator constants
# --------------------------------------------------------------------------

STATE_CODES = ["07", "27", "29", "33", "36", "19", "24", "06", "09", "32"]

TIER_GOODS = {
    0: ["Iron ore", "Raw cotton bales", "Crude polymer granules", "Bauxite",
        "Unprocessed timber", "Raw rubber sheets"],
    1: ["Steel coils", "Cotton yarn", "Moulded plastic parts", "Aluminium sheets",
        "Plywood panels", "Rubber gaskets"],
    2: ["Assembled pump units", "Garment lots", "Packaged fittings",
        "Kitchenware cartons", "Furniture sets", "Auto spare kits"],
    3: ["Retail display stock", "Consumer packs", "Shelf-ready cartons"],
}

# Goods descriptions used for the *reverse* leg of a genuine two-way trade.
RECIPROCAL_GOODS = [
    "Returned unsold stock", "Recovered packaging material",
    "Scrap and offcuts", "Warranty replacement units", "Inter-branch stock transfer",
]

# Vague, high-value, easily-faked descriptions typical of circular ITC fraud.
FRAUD_GOODS = [
    "Miscellaneous industrial goods", "Assorted electronic components",
    "General trading items", "Mixed hardware consignment",
    "Industrial consumables (assorted)", "Trading goods - general",
]

TIER_WEIGHTS = [0.18, 0.30, 0.32, 0.20]


@dataclass
class SyntheticNetwork:
    """A generated trade network plus the ground truth about it."""

    companies: list[dict] = field(default_factory=list)
    invoices: list[dict] = field(default_factory=list)
    # Each entry is a list of indices into `companies`, in cycle order.
    fraud_rings: list[list[int]] = field(default_factory=list)
    benign_loops: list[list[int]] = field(default_factory=list)

    @property
    def fraud_company_indices(self) -> set[int]:
        return {idx for ring in self.fraud_rings for idx in ring}


# --------------------------------------------------------------------------
# Identifier helpers
# --------------------------------------------------------------------------


def _make_pan(rng: random.Random) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return (
        "".join(rng.choice(letters) for _ in range(5))
        + "".join(str(rng.randint(0, 9)) for _ in range(4))
        + rng.choice(letters)
    )


def _make_gstin(rng: random.Random, pan: str) -> str:
    """State code (2) + PAN (10) + entity number (1) + 'Z' + checksum char (1)."""
    checksum = rng.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    return f"{rng.choice(STATE_CODES)}{pan}{rng.randint(1, 9)}Z{checksum}"


def _random_date(rng: random.Random, start: date, end: date) -> date:
    span = (end - start).days
    return start + timedelta(days=rng.randint(0, max(span, 0)))


def _log_uniform(rng: random.Random, low: float, high: float) -> float:
    """Draw uniformly on a log scale, giving a realistic heavy-tailed spread."""
    import math

    return math.exp(rng.uniform(math.log(low), math.log(high)))


# --------------------------------------------------------------------------
# Company builders
# --------------------------------------------------------------------------


def _build_legit_company(rng: random.Random, fake: Faker, tier: int, today: date) -> dict:
    pan = _make_pan(rng)
    # Most honest businesses are established: registered 1.5 - 12 years ago.
    # But a genuine minority are brand-new startups. They exist here on purpose:
    # if every young company were a shell, "recently registered" alone would
    # convict, and the detector would flag every real new business in India.
    if rng.random() < 0.14:
        registered = today - timedelta(days=rng.randint(70, 520))
        turnover_scale = rng.uniform(0.08, 0.35)
    else:
        registered = today - timedelta(days=rng.randint(550, 4400))
        turnover_scale = rng.uniform(0.45, 2.4)

    # Provisional only: step 6 of the generator overwrites this with what the
    # company actually traded, because honest filers declare roughly that.
    base_turnover = {0: 4.5e7, 1: 6.5e7, 2: 9.0e7, 3: 5.5e7}[tier]
    turnover = base_turnover * turnover_scale
    return {
        "gstin": _make_gstin(rng, pan),
        "pan": pan,
        "name": fake.company(),
        "director_name": fake.name(),
        "registered_address": fake.address().replace("\n", ", "),
        "registered_date": registered,
        "declared_turnover": round(turnover, 2),
        "_tier": tier,
        "_is_fraud": False,
        # Compliance is not uniform among honest taxpayers. Most are diligent,
        # but a real minority - small firms, poor back-office - routinely skip
        # e-way bills. Without them, "missing e-way bill" would be a perfect
        # fraud tell here and a source of false accusations in the field.
        "_eway_rate": rng.uniform(0.55, 0.82) if rng.random() < 0.18 else rng.uniform(0.9, 0.99),
        # Seasonal businesses (agri-produce, festival goods) concentrate their
        # entire year of invoicing into a few months. The offset is fixed per
        # company so all its invoices land in the SAME window - otherwise the
        # burst never materialises and only shells ever look bursty.
        "_season_offset": rng.random() if rng.random() < 0.3 else None,
        "_season_days": rng.randint(60, 130),
    }


def _build_shell_company(
    rng: random.Random,
    fake: Faker,
    today: date,
    shared_address: str | None,
    shared_director: str | None,
) -> dict:
    pan = _make_pan(rng)
    # Shell companies are young: registered 1 - 15 months ago.
    registered = today - timedelta(days=rng.randint(30, 450))
    # ...and declare tiny turnover relative to the invoice value they will push.
    turnover = rng.uniform(1.2e6, 9.0e6)
    return {
        "gstin": _make_gstin(rng, pan),
        "pan": pan,
        "name": fake.company(),
        "director_name": shared_director or fake.name(),
        "registered_address": shared_address or fake.address().replace("\n", ", "),
        "registered_date": registered,
        "declared_turnover": round(turnover, 2),
        "_tier": None,
        "_is_fraud": True,
        # Shells are sloppy about e-way bills; "hard" rings override this when
        # the ring is built.
        "_eway_rate": rng.uniform(0.05, 0.25),
        "_season_offset": None,
    }


# --------------------------------------------------------------------------
# The generator
# --------------------------------------------------------------------------


def build_synthetic_network(
    seed: int = 42,
    n_companies: int = 220,
    n_fraud_rings: int = 7,
    n_benign_pairs: int = 10,
    n_benign_distributor_pairs: int = 6,
    n_benign_triangles: int = 4,
    today: date | None = None,
) -> SyntheticNetwork:
    """
    Build a trade network whose only cycles are the ones we deliberately create.

    Returns plain dicts (not Django models) so the exact same code path can feed
    both the database seeder and the offline model trainer.
    """
    rng = random.Random(seed)
    fake = Faker("en_IN")
    Faker.seed(seed)
    today = today or date.today()

    net = SyntheticNetwork()

    # ---- 1. shell companies for the fraud rings -------------------------
    ring_sizes = [rng.randint(3, 6) for _ in range(n_fraud_rings)]
    n_shells = sum(ring_sizes)
    n_legit = max(n_companies - n_shells, 40)

    for size in ring_sizes:
        # Most rings reuse one address and/or one director across members.
        # A minority are "hard" rings that hide this, so the ML model cannot
        # rely on a single tell.
        hard_ring = rng.random() < 0.3
        addr = None if hard_ring else fake.address().replace("\n", ", ")
        director = None if hard_ring or rng.random() < 0.35 else fake.name()

        ring_indices = []
        for _ in range(size):
            use_addr = addr if (addr and rng.random() < 0.8) else None
            use_dir = director if (director and rng.random() < 0.75) else None
            company = _build_shell_company(rng, fake, today, use_addr, use_dir)
            company["_hard_ring"] = hard_ring
            ring_indices.append(len(net.companies))
            net.companies.append(company)
        net.fraud_rings.append(ring_indices)

    # ---- 2. legitimate companies, bucketed into supply-chain tiers -------
    tiers: dict[int, list[int]] = {0: [], 1: [], 2: [], 3: []}
    for _ in range(n_legit):
        tier = rng.choices([0, 1, 2, 3], weights=TIER_WEIGHTS)[0]
        idx = len(net.companies)
        net.companies.append(_build_legit_company(rng, fake, tier, today))
        tiers[tier].append(idx)

    # Guarantee every tier is populated so edge generation always has targets.
    for tier in (0, 1, 2, 3):
        while len(tiers[tier]) < 6:
            idx = len(net.companies)
            net.companies.append(_build_legit_company(rng, fake, tier, today))
            tiers[tier].append(idx)

    def add_invoice(seller: int, buyer: int, amount: float, when: date,
                    goods: str, eway: bool) -> None:
        net.invoices.append(
            {
                "seller_idx": seller,
                "buyer_idx": buyer,
                "amount": round(float(amount), 2),
                "date": when,
                "goods_description": goods,
                "has_eway_bill": eway,
            }
        )

    def trade_window(a: int, b: int) -> tuple[date, date]:
        """Invoices can only exist after both parties were registered."""
        start = max(
            net.companies[a]["registered_date"],
            net.companies[b]["registered_date"],
        ) + timedelta(days=5)
        start = min(start, today - timedelta(days=1))

        # A seasonal seller squeezes its whole year into one trading window.
        offset = net.companies[a].get("_season_offset")
        span = (today - start).days
        if offset is not None and span > 150:
            season_days = net.companies[a].get("_season_days", 110)
            season_start = start + timedelta(days=int(offset * max(span - season_days, 1)))
            return (season_start, min(season_start + timedelta(days=season_days), today))
        return (start, today)

    # ---- 3. legitimate trade: strictly tier-increasing, therefore acyclic --
    # Value enters at tier 0 and flows upward, each intermediary reselling
    # roughly what it bought plus a margin. Modelling it as a budget rather
    # than as independent random amounts matters: it means an honest
    # distributor's sales actually track its purchases, the way a real one's
    # do. Draw both sides independently and every mid-chain company looks
    # wildly unbalanced, which would hand the model a free giveaway feature.
    inflow: dict[int, float] = {}

    def emit_sales(seller: int, tier: int, budget: float) -> None:
        candidates = list(tiers[tier + 1])
        if tier + 2 <= 3:
            candidates += list(tiers[tier + 2])
        buyers = rng.sample(candidates, min(rng.randint(3, 9), len(candidates)))

        # Split the budget into invoices with uneven, realistic-looking shares.
        legs = [(buyer, rng.randint(1, 6)) for buyer in buyers]
        weights = [rng.uniform(0.5, 1.5) for _ in legs]
        total_weight = sum(w * n for (_, n), w in zip(legs, weights))

        for (buyer, count), weight in zip(legs, weights):
            start, end = trade_window(seller, buyer)
            for _ in range(count):
                amount = budget * (weight / total_weight) * rng.uniform(0.85, 1.15)
                if amount < 5_000:
                    continue
                inflow[buyer] = inflow.get(buyer, 0.0) + amount
                add_invoice(
                    seller,
                    buyer,
                    amount,
                    _random_date(rng, start, end),
                    rng.choice(TIER_GOODS[tier]),
                    rng.random() < net.companies[seller]["_eway_rate"],
                )

    # Tier 0 originates value. Budgets are drawn log-uniformly across two
    # orders of magnitude because real economies are heavy-tailed: a handful of
    # large traders move crores while most move lakhs. A narrow uniform range
    # would make "trades a lot" a perfect proxy for fraud.
    for seller in tiers[0]:
        emit_sales(seller, 0, _log_uniform(rng, 4e5, 6e7))

    # Tiers 1 and 2 resell what they bought. The margin sometimes lands at or
    # below 1.0 on purpose: commission agents and consignment traders really do
    # pass value straight through, and they are the honest businesses most
    # easily mistaken for conduits. The model has to learn to tell them apart.
    for tier in (1, 2):
        for seller in tiers[tier]:
            purchased = inflow.get(seller, 0.0)
            budget = (
                purchased * rng.uniform(0.98, 1.45)
                if purchased > 0
                # Sourced from outside the modelled network.
                else rng.uniform(300_000, 2_000_000)
            )
            emit_sales(seller, tier, budget)

    # ---- 4. benign reciprocal loops (genuine two-way trade) --------------
    # These are the "false positives" that cycle detection alone would flag.
    # Kept structurally isolated so each produces one small, exact SCC.
    used_in_loops: set[int] = set()

    # 4a. Retailer -> its own supplier back-edges, giving clean 2-cycles.
    #     Tier-3 companies have no other outgoing edges, so the strongly
    #     connected component is exactly {supplier, retailer}.
    supplier_pool = [i for i in tiers[2]]
    rng.shuffle(supplier_pool)
    retailer_pool = [i for i in tiers[3]]
    rng.shuffle(retailer_pool)
    for supplier, retailer in zip(supplier_pool, retailer_pool[:n_benign_pairs]):
        if supplier in used_in_loops or retailer in used_in_loops:
            continue
        start, end = trade_window(retailer, supplier)
        forward = rng.uniform(400_000, 1_800_000)
        # Ensure the forward leg exists so the pair really trades both ways.
        add_invoice(supplier, retailer, forward,
                    _random_date(rng, start, end), rng.choice(TIER_GOODS[2]),
                    rng.random() < net.companies[supplier]["_eway_rate"])
        # Usually the reverse leg is small (returns and scrap). Sometimes it is
        # a balanced consignment swap, which looks a lot like value recycling
        # on paper - a genuinely hard case for the model rather than a freebie.
        balanced = rng.random() < 0.35
        for _ in range(rng.randint(1, 3)):
            reverse = (
                forward * rng.uniform(0.9, 1.1) if balanced
                else rng.uniform(25_000, 180_000)
            )
            add_invoice(
                retailer,
                supplier,
                reverse,
                _random_date(rng, start, end),
                rng.choice(RECIPROCAL_GOODS),
                rng.random() < net.companies[retailer]["_eway_rate"],
            )
        used_in_loops.update({supplier, retailer})
        net.benign_loops.append([supplier, retailer])

    # 4b. Two distributors genuinely trading both ways. These are the hardest
    #     honest cases in the whole dataset: both sides buy and sell heavily,
    #     so the flow is balanced and the loop is tight - structurally almost
    #     indistinguishable from a shell pair. Only the boring evidence
    #     separates them: real turnover, years of history, e-way bills,
    #     unrelated directors and addresses.
    distributor_pool = [i for i in tiers[2] if i not in used_in_loops]
    rng.shuffle(distributor_pool)
    for _ in range(n_benign_distributor_pairs):
        if len(distributor_pool) < 2:
            break
        a, b = distributor_pool.pop(), distributor_pool.pop()
        base = _log_uniform(rng, 4e5, 1.2e7)
        for _ in range(rng.randint(2, 4)):
            for seller, buyer in ((a, b), (b, a)):
                start, end = trade_window(seller, buyer)
                add_invoice(
                    seller,
                    buyer,
                    base * rng.uniform(0.9, 1.1),
                    _random_date(rng, start, end),
                    rng.choice(TIER_GOODS[2]),
                    rng.random() < net.companies[seller]["_eway_rate"],
                )
        used_in_loops.update({a, b})
        net.benign_loops.append([a, b])

    # 4c. Mutual stock transfers between three retailers -> clean 3-cycles.
    free_retailers = [i for i in retailer_pool if i not in used_in_loops]
    for _ in range(n_benign_triangles):
        size = rng.randint(3, 5)
        if len(free_retailers) < size:
            break
        group = [free_retailers.pop() for _ in range(size)]
        # Mutual stock transfers move comparable value in each direction, so
        # these loops have nearly-uniform hop amounts - structurally the same
        # tell as circular billing. Their sizes overlap fraud ring sizes too,
        # so loop geometry alone decides nothing; the model has to separate
        # them on turnover, e-way bills, shared directors and company age.
        base = _log_uniform(rng, 8e4, 3e6)
        for _ in range(rng.randint(1, 3)):
            for a, b in zip(group, group[1:] + group[:1]):
                start, end = trade_window(a, b)
                add_invoice(
                    a,
                    b,
                    base * rng.uniform(0.94, 1.06),
                    _random_date(rng, start, end),
                    rng.choice(RECIPROCAL_GOODS),
                    rng.random() < net.companies[a]["_eway_rate"],
                )
        used_in_loops.update(group)
        net.benign_loops.append(group)

    # ---- 5. fraud rings: closed circular trade between shells ------------
    for ring in net.fraud_rings:
        hard_ring = net.companies[ring[0]]["_hard_ring"]

        # Rings churn faster than honest trade, but not all of them are
        # short-lived: some operate for the best part of a year before anyone
        # notices. Spanning 45 days to 10 months keeps "traded in a burst" a
        # useful hint rather than a giveaway.
        latest_reg = max(net.companies[i]["registered_date"] for i in ring)
        window_start = max(latest_reg + timedelta(days=7), today - timedelta(days=400))
        window_start = min(window_start, today - timedelta(days=40))
        window_days = rng.randint(45, 300)
        window_end = min(window_start + timedelta(days=window_days), today)

        # Value circles the loop almost unchanged: nothing is really produced.
        # The range overlaps what honest distributors move, so scale alone
        # cannot identify a ring - only the combination of evidence can.
        base_amount = _log_uniform(rng, 6e5, 1.4e7)
        n_rotations = rng.randint(2, 4)

        # Rings fabricate a small margin at each hop so the paperwork does not
        # look mechanically identical. It is still far tighter than the spread
        # of genuine trade, but it is not a giveaway either.
        hop_spread = rng.uniform(0.02, 0.08)

        for _ in range(n_rotations):
            amount = base_amount * rng.uniform(0.97, 1.03)
            for a, b in zip(ring, ring[1:] + ring[:1]):
                hop = amount * rng.uniform(1 - hop_spread, 1 + hop_spread)
                if not hard_ring:
                    # Suspiciously round figures are a common shell-invoice tell.
                    hop = round(hop, -4)
                add_invoice(
                    a,
                    b,
                    hop,
                    _random_date(rng, window_start, window_end),
                    rng.choice(FRAUD_GOODS),
                    # No goods actually move, so e-way bills are usually absent.
                    # "Hard" rings bother to fabricate them.
                    rng.random() < (0.75 if hard_ring else 0.12),
                )

        # A layer of ordinary-looking trade so the shells are not obviously
        # isolated. Buying only from tier 0 and selling only to tier 3 keeps the
        # ring's strongly connected component exactly equal to the ring itself.
        # Ring members deal with enough outside parties that a thin address
        # book alone will not identify them.
        for member in ring:
            for supplier in rng.sample(tiers[0], rng.randint(2, 6)):
                start, end = trade_window(supplier, member)
                add_invoice(supplier, member, rng.uniform(50_000, 300_000),
                            _random_date(rng, start, end),
                            rng.choice(TIER_GOODS[0]),
                            rng.random() < net.companies[supplier]["_eway_rate"])
            for customer in rng.sample(tiers[3], rng.randint(2, 6)):
                start, end = trade_window(member, customer)
                add_invoice(member, customer, rng.uniform(40_000, 250_000),
                            _random_date(rng, start, end),
                            rng.choice(TIER_GOODS[2]), rng.random() < 0.8)

    # ---- 6. make honest turnover declarations match reality ---------------
    # An honest business declares roughly what it actually traded. Leaving the
    # declaration as an independent random draw would make "declared turnover
    # vs invoice value" separate the classes perfectly for the wrong reason.
    # Shell declarations are left untouched - under-declaring while pushing
    # crores of invoices IS the fraud.
    sold: dict[int, float] = {}
    bought: dict[int, float] = {}
    for inv in net.invoices:
        sold[inv["seller_idx"]] = sold.get(inv["seller_idx"], 0.0) + inv["amount"]
        bought[inv["buyer_idx"]] = bought.get(inv["buyer_idx"], 0.0) + inv["amount"]

    for idx, company in enumerate(net.companies):
        if company["_is_fraud"]:
            continue
        # Retailers barely resell within the modelled network, so their
        # turnover follows what they bought plus a retail margin.
        traded = max(sold.get(idx, 0.0), bought.get(idx, 0.0) * rng.uniform(1.1, 1.4))
        if traded <= 0:
            continue
        company["declared_turnover"] = round(traded * rng.uniform(0.85, 1.2), 2)

    return net


# --------------------------------------------------------------------------
# Django management command
# --------------------------------------------------------------------------


class Command(BaseCommand):
    help = (
        "Wipe and reseed the database with a synthetic GST trade network "
        "containing deliberately injected circular-trade fraud rings."
    )

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=42,
                            help="RNG seed (same seed = same network).")
        parser.add_argument("--companies", type=int, default=220,
                            help="Approximate number of companies to generate.")
        parser.add_argument("--rings", type=int, default=7,
                            help="Number of fraud rings to inject (3-6 companies each).")

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Generating synthetic trade network...")
        net = build_synthetic_network(
            seed=options["seed"],
            n_companies=options["companies"],
            n_fraud_rings=options["rings"],
        )

        self.stdout.write("Clearing existing data...")
        # Reseeding invalidates every downstream fraud-engine result, because
        # they all reference company primary keys that are about to change.
        from fraud_engine.models import FlaggedRing, LedgerBlock, RiskScore

        Invoice.objects.all().delete()
        RiskScore.objects.all().delete()
        FlaggedRing.objects.all().delete()
        LedgerBlock.objects.all().delete()
        Company.objects.all().delete()

        self.stdout.write("Inserting companies...")
        companies = Company.objects.bulk_create(
            [
                Company(
                    gstin=c["gstin"],
                    pan=c["pan"],
                    name=c["name"],
                    director_name=c["director_name"],
                    registered_address=c["registered_address"],
                    registered_date=c["registered_date"],
                    declared_turnover=c["declared_turnover"],
                )
                for c in net.companies
            ],
            batch_size=500,
        )
        # bulk_create returns objects in input order, so index -> pk maps cleanly.
        pk_by_index = {i: obj.pk for i, obj in enumerate(companies)}

        self.stdout.write("Inserting invoices...")
        Invoice.objects.bulk_create(
            [
                Invoice(
                    seller_id=pk_by_index[inv["seller_idx"]],
                    buyer_id=pk_by_index[inv["buyer_idx"]],
                    amount=inv["amount"],
                    date=inv["date"],
                    goods_description=inv["goods_description"],
                    has_eway_bill=inv["has_eway_bill"],
                )
                for inv in net.invoices
            ],
            batch_size=1000,
        )

        fraud_gstins = [
            net.companies[i]["gstin"] for ring in net.fraud_rings for i in ring
        ]

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(net.companies)} companies and {len(net.invoices)} invoices."
        ))
        self.stdout.write(
            f"  Injected fraud rings   : {len(net.fraud_rings)} "
            f"(sizes {[len(r) for r in net.fraud_rings]})"
        )
        self.stdout.write(
            f"  Injected benign loops  : {len(net.benign_loops)} "
            "(genuine two-way trade, should NOT be flagged as fraud)"
        )
        self.stdout.write(f"  Shell companies        : {len(fraud_gstins)}")
        self.stdout.write(
            "\nNext: POST /api/fraud/rebuild-graph/ then POST /api/fraud/score/"
        )
