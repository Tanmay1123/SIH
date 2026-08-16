"""
Turns the invoice table into a directed graph.

Companies become nodes. Every invoice is a directed edge seller -> buyer.
Many invoices between the same two companies collapse into ONE edge carrying
aggregate attributes (total value, invoice count, how many lacked an e-way
bill, the date range). Collapsing matters: cycle-finding cares about *whether*
a trade relationship exists, and a multigraph with 3,500 parallel edges would
make that far more expensive for no extra information.
"""
from __future__ import annotations

import networkx as nx
import pandas as pd

from core.models import Company, Invoice


def load_dataframes() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pull the whole trade network out of the database as two DataFrames.

    The feature pipeline works on DataFrames rather than Django objects so the
    identical code can run against generated-but-never-saved data at training
    time.
    """
    companies = pd.DataFrame(
        list(
            Company.objects.values(
                "id",
                "gstin",
                "pan",
                "name",
                "director_name",
                "registered_address",
                "registered_date",
                "declared_turnover",
            )
        )
    )
    invoices = pd.DataFrame(
        list(
            Invoice.objects.values(
                "id",
                "seller_id",
                "buyer_id",
                "amount",
                "date",
                "goods_description",
                "has_eway_bill",
            )
        )
    )

    if not companies.empty:
        companies["declared_turnover"] = companies["declared_turnover"].astype(float)
        companies["registered_date"] = pd.to_datetime(companies["registered_date"])
    if not invoices.empty:
        invoices["amount"] = invoices["amount"].astype(float)
        invoices["date"] = pd.to_datetime(invoices["date"])

    return companies, invoices


def build_graph_from_dataframes(
    companies: pd.DataFrame, invoices: pd.DataFrame
) -> nx.DiGraph:
    """Build the directed trade graph from company/invoice DataFrames."""
    graph = nx.DiGraph()

    for row in companies.to_dict("records"):
        graph.add_node(
            row["id"],
            gstin=row.get("gstin"),
            name=row.get("name"),
            director_name=row.get("director_name"),
            registered_address=row.get("registered_address"),
            declared_turnover=float(row.get("declared_turnover") or 0.0),
        )

    if invoices.empty:
        return graph

    # One row per (seller, buyer) pair with the aggregates we need downstream.
    grouped = invoices.groupby(["seller_id", "buyer_id"], sort=False)
    for (seller, buyer), chunk in grouped:
        # Self-invoicing is a data-quality artefact, not a trade relationship,
        # and a self-loop would register as a length-1 "ring".
        if seller == buyer:
            continue
        graph.add_edge(
            seller,
            buyer,
            total_amount=float(chunk["amount"].sum()),
            invoice_count=int(len(chunk)),
            invoice_ids=[int(i) for i in chunk["id"].tolist()],
            eway_missing=int((~chunk["has_eway_bill"].astype(bool)).sum()),
            first_date=str(chunk["date"].min().date()),
            last_date=str(chunk["date"].max().date()),
        )

    return graph


def build_graph() -> nx.DiGraph:
    """Convenience wrapper: read the database and build the graph."""
    companies, invoices = load_dataframes()
    return build_graph_from_dataframes(companies, invoices)


def graph_summary(graph: nx.DiGraph) -> dict:
    """Small stats block, handy for API responses and for the dashboard header."""
    return {
        "companies": graph.number_of_nodes(),
        "trade_relationships": graph.number_of_edges(),
        "invoices": int(
            sum(d.get("invoice_count", 0) for _, _, d in graph.edges(data=True))
        ),
        "total_traded_value": round(
            sum(d.get("total_amount", 0.0) for _, _, d in graph.edges(data=True)), 2
        ),
    }
