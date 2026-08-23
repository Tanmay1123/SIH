"""
Risk scoring: feature engineering -> XGBoost -> SHAP explanation.

All three stages live in one module because they are one pipeline and share
one contract: FEATURE_NAMES. Split them across files and the ordering of the
feature vector becomes a bug waiting to happen.

WHAT THE MODEL IS ACTUALLY FOR
------------------------------
Cycle detection has already narrowed the network from ~220 companies down to
~25 candidate rings. But genuine businesses trade both ways too, so most of
those candidates are innocent. The model's job is the hard part: rank the
candidates so an officer looks at the seven real rings first.

TRAINING
--------
`train_and_save()` generates several *fresh* synthetic networks (different
seeds from the demo database), runs the real graph + cycle pipeline over each,
engineers features, and labels a company positive if it was planted as a shell.
Training data never touches the demo database, so the shipped model has not
memorised the rows it is later asked to score.

The artifact is saved as XGBoost's native JSON, not a pickle: small, readable,
and portable across library versions - which is why it can be committed.
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
from django.conf import settings

from fraud_engine.cycle_detection import detect_rings
from fraud_engine.graph_builder import build_graph_from_dataframes, load_dataframes

MODEL_PATH = settings.MODEL_ARTIFACT_DIR / "risk_model.json"
META_PATH = settings.MODEL_ARTIFACT_DIR / "feature_meta.json"

# The feature vector contract. Order matters and must match the saved model.
FEATURE_NAMES = [
    "days_since_registration",
    "declared_turnover_log",
    "sales_value_log",
    "purchase_value_log",
    "turnover_to_invoice_ratio",
    "itc_velocity",
    "pass_through_ratio",
    "eway_missing_ratio",
    "shared_address_count",
    "shared_director_count",
    "counterparty_count",
    "round_amount_ratio",
    "invoice_burst_ratio",
    "in_cycle_count",
    "min_cycle_length",
    "min_cycle_amount_cv",
    "max_cycle_value_log",
]


# --------------------------------------------------------------------------
# Feature engineering
# --------------------------------------------------------------------------


def engineer_features(
    companies: pd.DataFrame,
    invoices: pd.DataFrame,
    rings: list[dict],
    as_of: date | None = None,
) -> pd.DataFrame:
    """
    Build the per-company feature matrix.

    Works on DataFrames, not Django objects, so the identical function serves
    both offline training (on generated data) and live scoring (on the DB).
    Returns a DataFrame indexed by company id with exactly FEATURE_NAMES columns.
    """
    as_of = as_of or date.today()
    as_of_ts = pd.Timestamp(as_of)

    if companies.empty:
        return pd.DataFrame(columns=FEATURE_NAMES)

    feats = pd.DataFrame(index=pd.Index(companies["id"].values, name="company_id"))

    # ---- registration age -------------------------------------------------
    # Shell companies are young by design: they are created, used to churn
    # credit for a few months, then abandoned before scrutiny arrives.
    reg = pd.to_datetime(companies["registered_date"]).values
    days = (as_of_ts - pd.to_datetime(reg)).days.values.astype(float)
    feats["days_since_registration"] = np.clip(days, 1.0, None)

    turnover = companies["declared_turnover"].astype(float).values
    feats["declared_turnover_log"] = np.log1p(np.clip(turnover, 0, None))

    # ---- trade volume -----------------------------------------------------
    if invoices.empty:
        zero = pd.Series(0.0, index=feats.index)
        sales_value = sales_count = purchase_value = purchase_count = zero
    else:
        sales = invoices.groupby("seller_id")["amount"].agg(["sum", "count"])
        purchases = invoices.groupby("buyer_id")["amount"].agg(["sum", "count"])
        sales_value = sales["sum"].reindex(feats.index).fillna(0.0)
        sales_count = sales["count"].reindex(feats.index).fillna(0)
        purchase_value = purchases["sum"].reindex(feats.index).fillna(0.0)
        purchase_count = purchases["count"].reindex(feats.index).fillna(0)

    feats["sales_value_log"] = np.log1p(sales_value.values)
    feats["purchase_value_log"] = np.log1p(purchase_value.values)

    # Declared turnover vs total invoice value handled (sales + purchases).
    # An honest business declares roughly what it trades; a shell declares a
    # few lakh while pushing crores through its books, so this ratio collapses
    # towards zero. Using both sides rather than sales alone matters: a
    # retailer legitimately sells almost nothing onward, and dividing by sales
    # alone would make every honest retailer look like a shell.
    feats["turnover_to_invoice_ratio"] = np.clip(
        turnover / (sales_value.values + purchase_value.values + 1.0), 0, 20
    )

    # ITC velocity: input credit accumulated per day of existence. A company
    # three months old that has already booked crores of purchases is claiming
    # credit far faster than a real supply chain could generate it.
    feats["itc_velocity"] = purchase_value.values / feats["days_since_registration"].values

    # Pass-through ratio: |sales - purchases| / (sales + purchases). Real firms
    # add margin and hold stock, so the two sides differ. A conduit whose only
    # purpose is relaying invoices has money in == money out, pushing this to 0.
    total_flow = sales_value.values + purchase_value.values
    feats["pass_through_ratio"] = np.where(
        total_flow > 0,
        np.abs(sales_value.values - purchase_value.values) / (total_flow + 1.0),
        1.0,
    )

    # ---- e-way bills ------------------------------------------------------
    # An e-way bill accompanies an actual goods movement. Invoices without one
    # are the clearest sign that paper moved but goods did not.
    total_invoices = (sales_count.values + purchase_count.values).astype(float)
    if invoices.empty:
        missing_total = np.zeros(len(feats))
    else:
        missing = invoices[~invoices["has_eway_bill"].astype(bool)]
        missing_sell = missing.groupby("seller_id").size().reindex(feats.index).fillna(0)
        missing_buy = missing.groupby("buyer_id").size().reindex(feats.index).fillna(0)
        missing_total = (missing_sell + missing_buy).values.astype(float)
    feats["eway_missing_ratio"] = np.where(
        total_invoices > 0, missing_total / np.maximum(total_invoices, 1.0), 0.0
    )

    # ---- shared registration details --------------------------------------
    # Multiple "unrelated" companies at one address, or under one director, is
    # the classic shell-factory footprint.
    addr_counts = companies["registered_address"].value_counts()
    dir_counts = companies["director_name"].value_counts()
    feats["shared_address_count"] = (
        companies["registered_address"].map(addr_counts).values - 1
    ).astype(float)
    feats["shared_director_count"] = (
        companies["director_name"].map(dir_counts).values - 1
    ).astype(float)

    # ---- counterparty diversity + invoice hygiene -------------------------
    if invoices.empty:
        feats["counterparty_count"] = 0.0
        feats["round_amount_ratio"] = 0.0
        feats["invoice_burst_ratio"] = 0.0
    else:
        partners: dict[int, set[int]] = {}
        for seller, buyer in zip(invoices["seller_id"].values, invoices["buyer_id"].values):
            partners.setdefault(seller, set()).add(buyer)
            partners.setdefault(buyer, set()).add(seller)
        feats["counterparty_count"] = [
            float(len(partners.get(cid, ()))) for cid in feats.index
        ]

        # Fabricated invoices are written by a person picking a number, so they
        # cluster on round figures far more than genuine priced transactions.
        is_round = (invoices["amount"] % 10_000 == 0).astype(float)
        round_sell = is_round.groupby(invoices["seller_id"]).sum().reindex(feats.index).fillna(0)
        round_buy = is_round.groupby(invoices["buyer_id"]).sum().reindex(feats.index).fillna(0)
        feats["round_amount_ratio"] = np.where(
            total_invoices > 0,
            (round_sell + round_buy).values / np.maximum(total_invoices, 1.0),
            0.0,
        )

        # Filing anomaly: a ring churns its whole invoice book inside a short
        # window, then goes quiet. Honest trade is spread across the year.
        feats["invoice_burst_ratio"] = _burst_ratios(invoices, feats.index)

    # ---- cycle-derived features -------------------------------------------
    feats = _add_cycle_features(feats, rings)

    return feats[FEATURE_NAMES].astype(float).fillna(0.0)


def _burst_ratios(invoices: pd.DataFrame, index: pd.Index, window_days: int = 30) -> list[float]:
    """Largest share of a company's invoices falling inside any 30-day window."""
    dates_by_company: dict[int, list[np.datetime64]] = {}
    inv_dates = pd.to_datetime(invoices["date"]).values
    for seller, buyer, when in zip(
        invoices["seller_id"].values, invoices["buyer_id"].values, inv_dates
    ):
        dates_by_company.setdefault(seller, []).append(when)
        dates_by_company.setdefault(buyer, []).append(when)

    window = np.timedelta64(window_days, "D")
    ratios = []
    for cid in index:
        stamps = dates_by_company.get(cid)
        if not stamps:
            ratios.append(0.0)
            continue
        stamps = np.sort(np.array(stamps))
        best = 0
        left = 0
        for right in range(len(stamps)):
            while stamps[right] - stamps[left] > window:
                left += 1
            best = max(best, right - left + 1)
        ratios.append(best / len(stamps))
    return ratios


def _add_cycle_features(feats: pd.DataFrame, rings: list[dict]) -> pd.DataFrame:
    """
    Attach what the graph layer found about each company's loops.

    Note these features are shared by fraudulent AND benign loops - the
    generator injects both - so they narrow the field without giving the answer
    away. `min_cycle_amount_cv` is the discriminating one: value circulating
    almost unchanged means nothing was really produced.
    """
    in_cycle = pd.Series(0.0, index=feats.index)
    min_len = pd.Series(0.0, index=feats.index)
    min_cv = pd.Series(1.0, index=feats.index)
    max_value = pd.Series(0.0, index=feats.index)

    for ring in rings:
        cv = float(ring.get("amount_cv", 1.0))
        length = float(ring.get("length", 0))
        value = float(ring.get("total_cycle_value", 0.0))
        for cid in ring.get("company_ids", []):
            if cid not in feats.index:
                continue
            in_cycle[cid] += 1
            min_len[cid] = length if min_len[cid] == 0 else min(min_len[cid], length)
            min_cv[cid] = min(min_cv[cid], cv)
            max_value[cid] = max(max_value[cid], value)

    feats["in_cycle_count"] = in_cycle
    feats["min_cycle_length"] = min_len
    feats["min_cycle_amount_cv"] = min_cv
    feats["max_cycle_value_log"] = np.log1p(max_value)
    return feats


# --------------------------------------------------------------------------
# Plain-language explanation
# --------------------------------------------------------------------------


def candidate_company_ids(rings: list[dict]) -> set[int]:
    """
    Every company that cycle detection surfaced in at least one loop.

    These, and only these, are what the model judges. That boundary is
    deliberate. A company outside every loop is not a circular-trade suspect,
    and including such companies in training taught the model nothing except
    to re-read the sentinel feature values they carry (no loop => cv 1.0,
    loop value 0) - i.e. to rediscover the output of the graph stage and score
    a perfect, meaningless AUC. Restricting to candidates makes the model
    answer the question that is actually open: of the loops we found, which
    ones are fraud rather than genuine two-way trade?
    """
    return {cid for ring in rings for cid in ring.get("company_ids", [])}


def _inr(amount: float) -> str:
    """Format rupees the way an Indian officer reads them."""
    if amount >= 1e7:
        return f"Rs {amount / 1e7:.2f} crore"
    if amount >= 1e5:
        return f"Rs {amount / 1e5:.2f} lakh"
    return f"Rs {amount:,.0f}"


def _describe(feature: str, value: float, raises_risk: bool) -> str:
    """Turn one feature value into a sentence an investigator can act on."""
    pct = lambda v: f"{v * 100:.0f}%"  # noqa: E731

    if feature == "eway_missing_ratio":
        return (
            f"{pct(value)} of its invoices moved with no e-way bill, so paper "
            "changed hands but there is no record of goods actually moving."
            if raises_risk
            else f"Only {pct(value)} of its invoices lack an e-way bill, consistent with real goods movement."
        )
    if feature == "turnover_to_invoice_ratio":
        return (
            f"Declared turnover covers only {pct(min(value, 1.0))} of the invoice "
            "value passing through its books - it is billing far more than it declared."
            if raises_risk
            else "Declared turnover is broadly consistent with the invoices on its books."
        )
    if feature == "shared_address_count":
        return (
            f"Shares its registered address with {int(value)} other companies - "
            "a shell-factory footprint."
            if raises_risk
            else "Registered at an address it does not share with other taxpayers."
        )
    if feature == "shared_director_count":
        return (
            f"Shares a director with {int(value)} other companies in the network."
            if raises_risk
            else "Its director is not linked to other companies in the network."
        )
    if feature == "itc_velocity":
        return (
            f"Accumulating input credit at {_inr(value)} of purchases per day since "
            "registration - faster than a real supply chain could generate."
            if raises_risk
            else f"Input-credit accumulation of {_inr(value)} per day is unremarkable."
        )
    if feature == "min_cycle_amount_cv":
        return (
            f"Invoice values barely change going round the loop (variation "
            f"{pct(value)}) - value is circulating, not being created."
            if raises_risk
            else f"Amounts vary by {pct(value)} around the loop, as real margin-taking trade does."
        )
    if feature == "days_since_registration":
        return (
            f"Registered only {int(value)} days ago yet already trading at volume."
            if raises_risk
            else f"An established taxpayer, registered {int(value)} days ago."
        )
    if feature == "pass_through_ratio":
        return (
            "Sales and purchases are almost exactly equal - money in equals money "
            "out, the signature of a pass-through conduit."
            if raises_risk
            else "Sales and purchases differ as expected for a business that adds margin."
        )
    if feature == "round_amount_ratio":
        return (
            f"{pct(value)} of its invoices are suspiciously round figures, typical "
            "of amounts written by hand rather than priced."
            if raises_risk
            else "Invoice amounts show the irregularity of genuinely priced transactions."
        )
    if feature == "in_cycle_count":
        return (
            f"Appears in {int(value)} closed invoice loop(s)."
            if raises_risk
            else f"Appears in {int(value)} closed invoice loop(s), which alone is not suspicious."
        )
    if feature == "min_cycle_length":
        return (
            f"Sits in a tight {int(value)}-company loop - the shorter the loop, the "
            "faster credit returns to its originator."
            if raises_risk
            else f"Its shortest loop spans {int(value)} companies."
        )
    if feature == "max_cycle_value_log":
        return (
            f"The loop it belongs to circulates {_inr(float(np.expm1(value)))}."
            if raises_risk
            else f"The loop it belongs to circulates a modest {_inr(float(np.expm1(value)))}."
        )
    if feature == "counterparty_count":
        return (
            f"Trades with only {int(value)} counterparties, a very narrow customer base."
            if raises_risk
            else f"Trades with {int(value)} counterparties, a normally diversified base."
        )
    if feature == "invoice_burst_ratio":
        return (
            f"{pct(value)} of its invoices were issued inside a single 30-day window "
            "- a burst of activity rather than steady trade."
            if raises_risk
            else "Invoicing is spread steadily over time rather than concentrated in a burst."
        )
    if feature == "declared_turnover_log":
        return (
            f"Declares a turnover of only {_inr(float(np.expm1(value)))}."
            if raises_risk
            else f"Declares a turnover of {_inr(float(np.expm1(value)))}."
        )
    if feature == "sales_value_log":
        return f"Has issued {_inr(float(np.expm1(value)))} of sales invoices."
    if feature == "purchase_value_log":
        return f"Has booked {_inr(float(np.expm1(value)))} of purchase invoices."
    return f"{feature} = {value:.3f}"


def build_explanation(
    feature_row: pd.Series, shap_row: np.ndarray, top_n: int = 4
) -> list[dict]:
    """
    Convert SHAP contributions into ranked, plain-language reasons.

    A positive SHAP value pushed this company towards "fraud"; negative pulled
    it away. We report the strongest few in either direction so the officer
    sees the counter-evidence too, not just the accusation.
    """
    order = np.argsort(-np.abs(shap_row))[:top_n]
    reasons = []
    for idx in order:
        feature = FEATURE_NAMES[idx]
        impact = float(shap_row[idx])
        value = float(feature_row.iloc[idx])
        reasons.append(
            {
                "feature": feature,
                "value": round(value, 4),
                "impact": round(impact, 4),
                "direction": "increases_risk" if impact > 0 else "decreases_risk",
                "text": _describe(feature, value, raises_risk=impact > 0),
            }
        )
    return reasons


# --------------------------------------------------------------------------
# Model training
# --------------------------------------------------------------------------


def _network_training_frame(seed: int) -> tuple[pd.DataFrame, np.ndarray]:
    """Generate one synthetic network and turn it into (features, labels)."""
    from fraud_engine.synthetic_network import build_synthetic_network

    net = build_synthetic_network(seed=seed, n_fraud_rings=8)

    companies = pd.DataFrame(
        [
            {
                "id": i,
                "gstin": c["gstin"],
                "pan": c["pan"],
                "name": c["name"],
                "director_name": c["director_name"],
                "registered_address": c["registered_address"],
                "registered_date": c["registered_date"],
                "declared_turnover": c["declared_turnover"],
            }
            for i, c in enumerate(net.companies)
        ]
    )
    invoices = pd.DataFrame(
        [
            {
                "id": i,
                "seller_id": inv["seller_idx"],
                "buyer_id": inv["buyer_idx"],
                "amount": inv["amount"],
                "date": inv["date"],
                "goods_description": inv["goods_description"],
                "has_eway_bill": inv["has_eway_bill"],
            }
            for i, inv in enumerate(net.invoices)
        ]
    )
    companies["registered_date"] = pd.to_datetime(companies["registered_date"])
    invoices["date"] = pd.to_datetime(invoices["date"])

    graph = build_graph_from_dataframes(companies, invoices)
    rings = detect_rings(graph)
    features = engineer_features(companies, invoices, rings)

    # Train only on the loop members - see candidate_company_ids() for why.
    candidates = candidate_company_ids(rings)
    features = features.loc[[cid for cid in features.index if cid in candidates]]

    fraud = net.fraud_company_indices
    labels = np.array([1 if cid in fraud else 0 for cid in features.index])
    return features, labels


def train_and_save(seeds: list[int] | None = None, verbose: bool = True) -> dict:
    """
    Train the risk model on freshly generated networks and save the artifact.

    Returns a metrics dict. Held-out evaluation uses whole *networks* the model
    never saw, not a random row split - companies inside one network share a
    graph, so splitting rows would leak.
    """
    from sklearn.metrics import average_precision_score, roc_auc_score
    from xgboost import XGBClassifier

    seeds = seeds or [101, 202, 303, 404, 505, 606, 707, 808, 909, 1010]
    train_seeds, holdout_seeds = seeds[:-2], seeds[-2:]

    def stack(seed_list):
        frames, labels = [], []
        for seed in seed_list:
            f, y = _network_training_frame(seed)
            frames.append(f)
            labels.append(y)
            if verbose:
                print(f"  network seed={seed}: {len(f)} companies, {int(y.sum())} shells")
        return pd.concat(frames, ignore_index=True), np.concatenate(labels)

    if verbose:
        print("Generating training networks...")
    x_train, y_train = stack(train_seeds)
    if verbose:
        print("Generating held-out networks...")
    x_test, y_test = stack(holdout_seeds)

    # Shells are a small minority, so tell the model to weight them up rather
    # than let it score everything "clean" and be 90% accurate doing nothing.
    pos = max(int(y_train.sum()), 1)
    neg = len(y_train) - pos

    model = XGBClassifier(
        n_estimators=250,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        min_child_weight=2,
        reg_lambda=1.5,
        scale_pos_weight=neg / pos,
        eval_metric="aucpr",
        random_state=42,
        n_jobs=2,
    )
    model.fit(x_train[FEATURE_NAMES], y_train)

    probs = model.predict_proba(x_test[FEATURE_NAMES])[:, 1]
    metrics = {
        "trained_on_networks": train_seeds,
        "holdout_networks": holdout_seeds,
        "train_rows": int(len(x_train)),
        "train_positives": pos,
        "holdout_rows": int(len(x_test)),
        "holdout_positives": int(y_test.sum()),
        "holdout_roc_auc": round(float(roc_auc_score(y_test, probs)), 4),
        "holdout_avg_precision": round(float(average_precision_score(y_test, probs)), 4),
    }

    settings.MODEL_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(MODEL_PATH)
    META_PATH.write_text(
        json.dumps(
            {
                "feature_names": FEATURE_NAMES,
                "trained_at": date.today().isoformat(),
                "metrics": metrics,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return metrics


def load_model():
    """Load the committed pretrained model. Raises if it is missing."""
    from xgboost import XGBClassifier

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"No risk model at {MODEL_PATH}. Run: python manage.py train_risk_model"
        )
    model = XGBClassifier()
    model.load_model(MODEL_PATH)
    return model


def load_metadata() -> dict:
    if not META_PATH.exists():
        return {}
    return json.loads(META_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Inference
# --------------------------------------------------------------------------


def score_dataframe(features: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return (scores 0-100, SHAP value matrix) for a feature frame."""
    import shap

    model = load_model()
    matrix = features[FEATURE_NAMES]

    probabilities = model.predict_proba(matrix)[:, 1]
    scores = np.round(probabilities * 100.0, 2)

    explainer = shap.TreeExplainer(model)
    shap_values = np.asarray(explainer.shap_values(matrix))
    # Some SHAP/XGBoost version pairs return one matrix per class.
    if shap_values.ndim == 3:
        shap_values = shap_values[:, :, -1]

    return scores, shap_values


def score_network(
    companies: pd.DataFrame, invoices: pd.DataFrame, rings: list[dict]
) -> pd.DataFrame:
    """
    Score every company and attach its explanation.

    Companies that cycle detection did not place in any loop are not
    circular-trade suspects, so they are reported at zero risk rather than run
    through a model that was never trained on them. Their features are still
    recorded, so an officer can see the evidence that led nowhere.

    Returns a DataFrame indexed by company id with columns:
    score, features (dict), explanation (list of reason dicts).
    """
    features = engineer_features(companies, invoices, rings)
    if features.empty:
        return pd.DataFrame(columns=["score", "features", "explanation"])

    candidates = candidate_company_ids(rings)
    is_candidate = np.array([cid in candidates for cid in features.index])

    scores = np.zeros(len(features))
    explanations: list[list[dict]] = [
        [
            {
                "feature": "in_cycle_count",
                "value": 0.0,
                "impact": 0.0,
                "direction": "decreases_risk",
                "text": (
                    "Not part of any closed invoice loop, so it is not a "
                    "circular-trade suspect."
                ),
            }
        ]
        for _ in range(len(features))
    ]

    if is_candidate.any():
        candidate_features = features[is_candidate]
        candidate_scores, shap_values = score_dataframe(candidate_features)
        positions = np.flatnonzero(is_candidate)
        for offset, position in enumerate(positions):
            scores[position] = candidate_scores[offset]
            explanations[position] = build_explanation(
                candidate_features.iloc[offset], shap_values[offset]
            )

    return pd.DataFrame(
        {
            "score": scores,
            "features": [
                {k: round(float(v), 4) for k, v in row.items()}
                for _, row in features.iterrows()
            ],
            "explanation": explanations,
        },
        index=features.index,
    )


def ring_risk(ring: dict, company_scores: pd.DataFrame) -> tuple[float, list[dict]]:
    """
    Roll per-company scores up to a ring-level score and explanation.

    The mean is used rather than the max: a ring is a conspiracy, so what
    matters is that *the whole loop* looks wrong. One suspicious company inside
    an otherwise ordinary loop is far more likely to be a coincidence than a
    ring where every member is a shell.
    """
    members = [c for c in ring.get("company_ids", []) if c in company_scores.index]
    if not members:
        return 0.0, []

    score = float(np.mean([company_scores.loc[c, "score"] for c in members]))

    # Aggregate SHAP impact per feature across members, keep the strongest few,
    # and quote the member sentence that best represents each one.
    totals: dict[str, float] = {}
    best_text: dict[str, tuple[float, dict]] = {}
    for cid in members:
        for reason in company_scores.loc[cid, "explanation"]:
            key = reason["feature"]
            totals[key] = totals.get(key, 0.0) + reason["impact"]
            if key not in best_text or abs(reason["impact"]) > best_text[key][0]:
                best_text[key] = (abs(reason["impact"]), reason)

    ranked = sorted(totals.items(), key=lambda kv: -abs(kv[1]))[:4]
    explanation = [
        {
            "feature": feature,
            "impact": round(total / len(members), 4),
            "direction": "increases_risk" if total > 0 else "decreases_risk",
            "text": best_text[feature][1]["text"],
        }
        for feature, total in ranked
    ]
    return round(score, 2), explanation


def run_scoring() -> dict:
    """
    Live scoring pass over the current database.

    Reads companies/invoices, reuses the rings already stored by the
    rebuild-graph step, writes a fresh RiskScore per company, and updates each
    FlaggedRing's score and explanation. Synchronous on purpose - at demo scale
    this takes a couple of seconds and a job queue would be pure ceremony.
    """
    from django.utils import timezone

    from fraud_engine.models import FlaggedRing, RiskScore

    companies, invoices = load_dataframes()
    if companies.empty:
        return {"companies_scored": 0, "rings_scored": 0,
                "message": "No companies in the database. Upload a dataset first."}

    stored_rings = list(FlaggedRing.objects.all())

    # Recompute ring evidence from the live graph rather than trusting the
    # summary stored at detection time: invoices may have changed since, and
    # the feature pipeline needs hop-level amounts the stored row does not keep.
    graph = build_graph_from_dataframes(companies, invoices)
    rings = detect_rings(graph)

    company_scores = score_network(companies, invoices, rings)

    RiskScore.objects.all().delete()
    RiskScore.objects.bulk_create(
        [
            RiskScore(
                company_id=int(cid),
                score=float(row["score"]),
                feature_snapshot=row["features"],
                explanation=row["explanation"],
            )
            for cid, row in company_scores.iterrows()
        ],
        batch_size=500,
    )

    by_signature = {
        ",".join(str(c) for c in sorted(r["company_ids"])): r for r in rings
    }
    updated = 0
    for ring_row in stored_rings:
        evidence = by_signature.get(ring_row.signature)
        if evidence is None:
            continue
        score, explanation = ring_risk(evidence, company_scores)
        ring_row.risk_score = score
        ring_row.explanation = explanation
        ring_row.save(update_fields=["risk_score", "explanation"])
        updated += 1

    return {
        "companies_scored": int(len(company_scores)),
        "rings_scored": updated,
        "model": load_metadata().get("metrics", {}),
        "computed_at": timezone.now().isoformat(),
    }
