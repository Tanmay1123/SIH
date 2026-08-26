"""
Non-loop fraud detection: fake invoice mills.

WHY THIS EXISTS
---------------
An evaluator asked the obvious question: what about companies committing fraud
without forming a loop? The honest answer was that we would miss them, and the
biggest miss is the *fake invoice mill* - which is probably the most common
form of real GST fraud in India.

A mill is a shell that exists only to issue invoices. It sells to dozens of
unrelated real businesses who want input credit to claim, and it buys from
almost nobody, because nothing it "sold" ever existed. Then it stops filing and
disappears.

That is a star, not a loop. Tarjan and Johnson will never see it: there is no
cycle to find. It needs its own detector, and it gets one here.

WHY THIS IS RULES AND NOT A MODEL
---------------------------------
The XGBoost model is trained on labelled shells that sit inside generated
rings. It has never seen a labelled mill, so asking it to score one would be
inference far outside its training distribution - a confident number with
nothing behind it.

So this detector is deliberately explicit: a handful of named signals, each
with a stated weight and a plain-English sentence. Every score can be read back
as the reasons that produced it. When officer decisions have accumulated enough
dismissals and confirmations on mill alerts (which is exactly what the new
review workflow collects), these rules become the baseline a learned model has
to beat.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

# --- gates: what is even worth looking at ---------------------------------
# A mill's whole business is issuing invoices to many parties, so a company
# with a couple of customers is not one however lopsided its books are.
MIN_BUYERS = 5
# Sales at least this many times purchases. A real trader buys what it sells;
# a mill invoices value it never acquired.
MIN_SALES_MULTIPLE = 4.0
# Ignore trivial amounts - a tiny lopsided company is a small business, not a
# fraud operation worth an officer's time.
MIN_SALES_VALUE = 1_000_000.0

# --- scoring weights (sum to 100) -----------------------------------------
WEIGHTS = {
    "one_way_flow": 30.0,      # sells a lot, buys nothing
    "buyer_spread": 18.0,      # many unrelated customers
    "eway_missing": 20.0,      # paper moved, goods did not
    "young": 12.0,             # registered recently
    "under_declared": 12.0,    # declares far less than it invoices
    "round_amounts": 8.0,      # amounts written by hand, not priced
}


def _inr(amount: float) -> str:
    if amount >= 1e7:
        return f"Rs {amount / 1e7:.2f} crore"
    if amount >= 1e5:
        return f"Rs {amount / 1e5:.2f} lakh"
    return f"Rs {amount:,.0f}"


def _ramp(value: float, low: float, high: float) -> float:
    """Linear 0..1 ramp, clamped. `low` scores 0, `high` scores 1."""
    if high <= low:
        return 0.0
    return float(np.clip((value - low) / (high - low), 0.0, 1.0))


def detect_mills(
    companies: pd.DataFrame,
    invoices: pd.DataFrame,
    as_of: date | None = None,
    min_score: float = 45.0,
) -> list[dict]:
    """
    Find companies that look like fake invoice mills.

    Returns a list of evidence dicts shaped like `cycle_detection.detect_rings`
    output, so the rest of the pipeline - storage, the API, the dashboard -
    handles both kinds of alert without special cases.
    """
    if companies.empty or invoices.empty:
        return []

    as_of = as_of or date.today()
    as_of_ts = pd.Timestamp(as_of)

    idx = pd.Index(companies["id"].values, name="company_id")

    sales = invoices.groupby("seller_id")["amount"].agg(["sum", "count"])
    purchases = invoices.groupby("buyer_id")["amount"].agg(["sum", "count"])

    sales_value = sales["sum"].reindex(idx).fillna(0.0)
    sales_count = sales["count"].reindex(idx).fillna(0)
    purchase_value = purchases["sum"].reindex(idx).fillna(0.0)

    buyers = invoices.groupby("seller_id")["buyer_id"].nunique().reindex(idx).fillna(0)
    suppliers = invoices.groupby("buyer_id")["seller_id"].nunique().reindex(idx).fillna(0)

    missing = invoices[~invoices["has_eway_bill"].astype(bool)]
    missing_sales = (
        missing.groupby("seller_id").size().reindex(idx).fillna(0)
        if not missing.empty
        else pd.Series(0, index=idx)
    )

    is_round = (invoices["amount"] % 10_000 == 0).astype(float)
    round_sales = is_round.groupby(invoices["seller_id"]).sum().reindex(idx).fillna(0)

    reg_days = (as_of_ts - pd.to_datetime(companies["registered_date"])).dt.days
    reg_days = pd.Series(np.clip(reg_days.values, 1, None), index=idx)
    turnover = pd.Series(companies["declared_turnover"].astype(float).values, index=idx)
    names = pd.Series(companies["name"].values, index=idx)

    # Invoice ids per seller, for the evidence bundle.
    ids_by_seller: dict[int, list[int]] = {}
    for seller, inv_id in zip(invoices["seller_id"].values, invoices["id"].values):
        ids_by_seller.setdefault(int(seller), []).append(int(inv_id))

    buyers_by_seller: dict[int, list[int]] = {}
    for seller, buyer in zip(invoices["seller_id"].values, invoices["buyer_id"].values):
        buyers_by_seller.setdefault(int(seller), []).append(int(buyer))

    results: list[dict] = []

    for cid in idx:
        sold = float(sales_value[cid])
        bought = float(purchase_value[cid])
        n_buyers = int(buyers[cid])

        # ---- gates -------------------------------------------------------
        if sold < MIN_SALES_VALUE or n_buyers < MIN_BUYERS:
            continue
        if bought > 0 and sold / bought < MIN_SALES_MULTIPLE:
            continue

        n_sales = max(int(sales_count[cid]), 1)
        eway_missing_ratio = float(missing_sales[cid]) / n_sales
        round_ratio = float(round_sales[cid]) / n_sales
        age_days = float(reg_days[cid])
        declared = float(turnover[cid])
        coverage = declared / sold if sold > 0 else 1.0

        # ---- signals -----------------------------------------------------
        # Purchases as a fraction of sales: 0 means it acquired nothing at all.
        purchase_share = bought / sold if sold > 0 else 1.0
        signals = {
            "one_way_flow": 1.0 - _ramp(purchase_share, 0.0, 0.25),
            "buyer_spread": _ramp(n_buyers, MIN_BUYERS, 30),
            "eway_missing": _ramp(eway_missing_ratio, 0.15, 0.75),
            "young": 1.0 - _ramp(age_days, 180, 1460),
            "under_declared": 1.0 - _ramp(coverage, 0.05, 0.6),
            "round_amounts": _ramp(round_ratio, 0.2, 0.8),
        }

        score = sum(WEIGHTS[key] * value for key, value in signals.items())
        if score < min_score:
            continue

        contributions = sorted(
            ((WEIGHTS[k] * v, k) for k, v in signals.items()), reverse=True
        )

        explanation = []
        for impact, key in contributions[:4]:
            if impact <= 0.5:
                continue
            explanation.append(
                {
                    "feature": key,
                    "value": round(float(signals[key]), 4),
                    "impact": round(float(impact), 4),
                    "direction": "increases_risk",
                    "text": _describe(
                        key,
                        sold=sold,
                        bought=bought,
                        n_buyers=n_buyers,
                        n_suppliers=int(suppliers[cid]),
                        eway_missing_ratio=eway_missing_ratio,
                        age_days=age_days,
                        declared=declared,
                        coverage=coverage,
                        round_ratio=round_ratio,
                    ),
                }
            )

        member_buyers = sorted(set(buyers_by_seller.get(int(cid), [])))
        results.append(
            {
                "kind": "mill",
                # The mill first, then its buyers - so the graph highlight and
                # the evidence panel both lead with the company under suspicion.
                "company_ids": [int(cid)] + member_buyers,
                "mill_company_id": int(cid),
                "mill_company_name": str(names[cid]),
                "length": 1 + len(member_buyers),
                "total_cycle_value": round(sold, 2),
                "invoice_ids": sorted(set(ids_by_seller.get(int(cid), []))),
                "invoice_count": n_sales,
                "risk_score": round(float(min(score, 100.0)), 2),
                "explanation": explanation,
                "closure": "invoice",
                "amount_cv": 1.0,
                "eway_missing_count": int(missing_sales[cid]),
                "eway_missing_ratio": round(eway_missing_ratio, 4),
                "evidence": {
                    "sales_value": round(sold, 2),
                    "purchase_value": round(bought, 2),
                    "buyer_count": n_buyers,
                    "supplier_count": int(suppliers[cid]),
                    "declared_turnover": round(declared, 2),
                    "turnover_coverage": round(coverage, 4),
                    "days_since_registration": int(age_days),
                    "eway_missing_ratio": round(eway_missing_ratio, 4),
                    "round_amount_ratio": round(round_ratio, 4),
                    "signals": {k: round(float(v), 4) for k, v in signals.items()},
                },
            }
        )

    results.sort(key=lambda r: -r["risk_score"])
    return results


def _describe(key: str, **f) -> str:
    """One signal, as a sentence an investigator can act on."""
    if key == "one_way_flow":
        if f["bought"] <= 0:
            return (
                f"Issued {_inr(f['sold'])} of sales invoices while booking no "
                "purchases at all - it never acquired anything it claims to have sold."
            )
        return (
            f"Sold {_inr(f['sold'])} against only {_inr(f['bought'])} of purchases. "
            "Value is being invoiced out that was never bought in."
        )
    if key == "buyer_spread":
        return (
            f"Invoices {f['n_buyers']} different buyers but has only "
            f"{f['n_suppliers']} supplier(s) - the fan-out pattern of an invoice mill, "
            "not a trading business."
        )
    if key == "eway_missing":
        return (
            f"{f['eway_missing_ratio'] * 100:.0f}% of its sales invoices moved with no "
            "e-way bill, so paper changed hands but no goods did."
        )
    if key == "young":
        return (
            f"Registered only {int(f['age_days'])} days ago yet already issuing "
            "invoices at volume."
        )
    if key == "under_declared":
        return (
            f"Declared a turnover of {_inr(f['declared'])}, covering just "
            f"{f['coverage'] * 100:.0f}% of the {_inr(f['sold'])} it has actually invoiced."
        )
    if key == "round_amounts":
        return (
            f"{f['round_ratio'] * 100:.0f}% of its invoices are round figures, typical of "
            "amounts written by hand rather than priced."
        )
    return key
