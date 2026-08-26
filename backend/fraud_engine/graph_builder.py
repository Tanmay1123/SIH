"""
Turns the invoice table into a directed graph.

Companies become nodes. Every invoice is a directed edge seller -> buyer.
Many invoices between the same two companies collapse into ONE edge carrying
aggregate attributes (total value, invoice count, how many lacked an e-way
bill, the date range). Collapsing matters: cycle-finding cares about *whether*
a trade relationship exists, and a multigraph with 3,500 parallel edges would
make that far more expensive for no extra information.

CONTROL EDGES
-------------
The graph optionally carries a second kind of edge. If two companies share a
registered address or a director, they are linked in both directions with a
`relation="control"` edge.

The reason is a real gap in pure cycle detection. Consider A -> B -> C by
invoice, where C and A share a director. That *is* a circular-trade ring - the
loop closes through ownership instead of through a bill, which is the smarter
way to run the fraud precisely because it leaves no closing invoice for anyone
to find. With invoice edges alone it looks like an innocent chain.

Control edges are marked, never counted as trade, and a cycle made only of them
is meaningless (it is just a list of companies at one address), so
cycle_detection requires at least one invoice hop before it will report a ring.
"""
from __future__ import annotations

from collections import defaultdict

import networkx as nx
import pandas as pd

from core.models import Company, Invoice, active_dataset

# A registered address or director shared by more companies than this is
# almost always a data artefact - "Address not available", a filing agent, a
# common-services provider - rather than a shell factory. Linking all pairs in
# such a group would add thousands of meaningless edges and swamp detection.
MAX_SHARED_GROUP_SIZE = 12


def load_dataframes(dataset=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pull the trade network out of the database as two DataFrames.

    Scoped to `dataset` if given, otherwise to the currently active dataset.
    When no dataset exists at all (a fresh install, or the test suite, which
    creates Company rows directly) everything is returned unfiltered.

    The feature pipeline works on DataFrames rather than Django objects so the
    identical code can run against generated-but-never-saved data at training
    time.
    """
    dataset = dataset or active_dataset()

    company_qs = Company.objects.all()
    invoice_qs = Invoice.objects.all()
    if dataset is not None:
        company_qs = company_qs.filter(dataset=dataset)
        invoice_qs = invoice_qs.filter(dataset=dataset)

    companies = pd.DataFrame(
        list(
            company_qs.values(
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
            invoice_qs.values(
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


def _add_control_edges(graph: nx.DiGraph, companies: pd.DataFrame) -> int:
    """
    Link companies that share a registered address or a director.

    Bidirectional, because control is not directional: if A and C are run by
    the same person, value can be moved either way between them without an
    invoice. Returns how many edges were added.
    """
    added = 0

    for field, label in (
        ("registered_address", "address"),
        ("director_name", "director"),
    ):
        if field not in companies.columns:
            continue

        groups: dict[str, list[int]] = defaultdict(list)
        for row in companies[["id", field]].to_dict("records"):
            key = (row.get(field) or "").strip().lower()
            if key:
                groups[key].append(int(row["id"]))

        for key, members in groups.items():
            if len(members) < 2 or len(members) > MAX_SHARED_GROUP_SIZE:
                continue
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    for source, target in ((a, b), (b, a)):
                        existing = graph.get_edge_data(source, target)
                        if existing is not None:
                            # A real trade relationship already exists. Record
                            # the shared detail on it as extra evidence, but
                            # never downgrade a trade edge to a control edge.
                            existing.setdefault("shared_via", []).append(label)
                            continue
                        graph.add_edge(
                            source,
                            target,
                            relation="control",
                            shared_via=[label],
                            shared_value=key,
                            total_amount=0.0,
                            invoice_count=0,
                            invoice_ids=[],
                            eway_missing=0,
                        )
                        added += 1

    return added


def build_graph_from_dataframes(
    companies: pd.DataFrame,
    invoices: pd.DataFrame,
    include_control_edges: bool = False,
) -> nx.DiGraph:
    """
    Build the directed trade graph from company/invoice DataFrames.

    `include_control_edges` adds the shared-address / shared-director links
    described in the module docstring. Off by default so the training pipeline
    and the existing tests keep seeing a pure invoice graph.
    """
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

    if not invoices.empty:
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
                relation="invoice",
                total_amount=float(chunk["amount"].sum()),
                invoice_count=int(len(chunk)),
                invoice_ids=[int(i) for i in chunk["id"].tolist()],
                eway_missing=int((~chunk["has_eway_bill"].astype(bool)).sum()),
                first_date=str(chunk["date"].min().date()),
                last_date=str(chunk["date"].max().date()),
            )

    if include_control_edges and not companies.empty:
        _add_control_edges(graph, companies)

    return graph


def build_graph(dataset=None, include_control_edges: bool = False) -> nx.DiGraph:
    """Convenience wrapper: read the database and build the graph."""
    companies, invoices = load_dataframes(dataset)
    return build_graph_from_dataframes(companies, invoices, include_control_edges)


def trade_subgraph(graph: nx.DiGraph) -> nx.DiGraph:
    """
    The invoice-only view of a graph that may also carry control edges.

    Used wherever control links would distort a number - trade totals, node
    degree in the dashboard, the mill detector's counterparty counts.
    """
    keep = [
        (u, v)
        for u, v, d in graph.edges(data=True)
        if d.get("relation", "invoice") == "invoice"
    ]
    return graph.edge_subgraph(keep).copy() if keep else nx.DiGraph()


def graph_summary(graph: nx.DiGraph) -> dict:
    """Small stats block, handy for API responses and for the dashboard header."""
    trade_edges = [
        d for _, _, d in graph.edges(data=True)
        if d.get("relation", "invoice") == "invoice"
    ]
    control_edges = graph.number_of_edges() - len(trade_edges)
    return {
        "companies": graph.number_of_nodes(),
        "trade_relationships": len(trade_edges),
        "control_links": control_edges,
        "invoices": int(sum(d.get("invoice_count", 0) for d in trade_edges)),
        "total_traded_value": round(
            sum(d.get("total_amount", 0.0) for d in trade_edges), 2
        ),
    }
