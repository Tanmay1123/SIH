"""
Circular-trade detection: find closed invoice loops A -> B -> C -> A.

TWO-STAGE APPROACH
------------------
Stage 1 - Tarjan's strongly connected components (a pre-filter).
    A cycle can only ever live *inside* a strongly connected component: if two
    companies are on a common cycle, each can reach the other, which is the
    definition of being in the same SCC. Tarjan finds every SCC in O(V + E) -
    a single linear pass. In a healthy trade network almost every company is
    an SCC of size 1 (supply chains flow one way), so this one cheap pass
    throws away the overwhelming majority of the graph before the expensive
    work starts.

Stage 2 - Johnson's algorithm (the actual enumeration).
    Run inside each surviving SCC only. Johnson's enumerates every *simple*
    cycle (no repeated company) in O((V + E)(C + 1)) where C is the number of
    cycles found - it does no work proportional to cycles that do not exist,
    which is what makes it usable here.

WHY THE LENGTH BOUND
    The number of simple cycles in a dense graph grows factorially, so an
    unbounded search on a pathological component could run effectively
    forever. Real ITC fraud rings are short - the whole point is to return the
    credit to the originator quickly - so we cap ring length (default 6, see
    settings.MAX_RING_SIZE). If an SCC is small we let Johnson's run free and
    filter afterwards; if it is large we push the bound down into the search
    itself so it can never blow up.
"""
from __future__ import annotations

import networkx as nx
from django.conf import settings

# Above this size, an SCC gets the length-bounded search instead of unbounded
# Johnson's. Chosen so ordinary demo-scale components stay on the exact path.
UNBOUNDED_SCC_NODE_LIMIT = 25
UNBOUNDED_SCC_EDGE_LIMIT = 120


def canonical_cycle(cycle: list[int]) -> tuple[int, ...]:
    """
    Rotation-independent identity for a cycle.

    [A, B, C], [B, C, A] and [C, A, B] are the same ring traversed from
    different starting points. Rotating so the smallest company id comes first
    gives one canonical form, which is how duplicates are removed.
    """
    if not cycle:
        return ()
    start = cycle.index(min(cycle))
    return tuple(cycle[start:] + cycle[:start])


def find_cycles(graph: nx.DiGraph, max_length: int | None = None) -> list[list[int]]:
    """
    Return every simple directed cycle up to `max_length`, de-duplicated.

    Results are sorted shortest-first so the tightest (most suspicious) rings
    surface at the top of an investigator's queue.
    """
    if max_length is None:
        max_length = getattr(settings, "MAX_RING_SIZE", 6)

    seen: set[tuple[int, ...]] = set()
    cycles: list[list[int]] = []

    # --- Stage 1: Tarjan's SCC pre-filter -------------------------------
    for component in nx.strongly_connected_components(graph):
        if len(component) < 2:
            # A single node can only be on a cycle via a self-loop, which
            # build_graph_from_dataframes already discards.
            continue

        subgraph = graph.subgraph(component)

        # --- Stage 2: Johnson's algorithm, scoped to this component -----
        if (
            subgraph.number_of_nodes() <= UNBOUNDED_SCC_NODE_LIMIT
            and subgraph.number_of_edges() <= UNBOUNDED_SCC_EDGE_LIMIT
        ):
            # Small component: nx.simple_cycles with no bound is Johnson's.
            candidate_iter = nx.simple_cycles(subgraph)
        else:
            # Large component: bound the search itself so it cannot explode.
            candidate_iter = nx.simple_cycles(subgraph, length_bound=max_length)

        for cycle in candidate_iter:
            if len(cycle) < 2 or len(cycle) > max_length:
                continue
            key = canonical_cycle(cycle)
            if key in seen:
                continue
            seen.add(key)
            cycles.append(list(key))

    cycles.sort(key=lambda c: (len(c), c))
    return cycles


def cycle_evidence(graph: nx.DiGraph, cycle: list[int]) -> dict:
    """
    Collect the hard facts about one ring: which invoices form it, how much
    value circles it, how uniform the hops are, and how many legs moved
    without an e-way bill.

    `amount_cv` (coefficient of variation of the hop amounts) is the key
    number. Real trade adds margin at every step so amounts vary; fraudulent
    circular billing passes almost the same figure around the loop, driving
    the CV towards zero.
    """
    hops = list(zip(cycle, cycle[1:] + cycle[:1]))

    amounts: list[float] = []
    invoice_ids: list[int] = []
    invoice_count = 0
    eway_missing = 0

    for a, b in hops:
        data = graph.get_edge_data(a, b) or {}
        amounts.append(float(data.get("total_amount", 0.0)))
        invoice_ids.extend(data.get("invoice_ids", []))
        invoice_count += int(data.get("invoice_count", 0))
        eway_missing += int(data.get("eway_missing", 0))

    total = sum(amounts)
    mean = total / len(amounts) if amounts else 0.0
    if mean > 0:
        variance = sum((a - mean) ** 2 for a in amounts) / len(amounts)
        amount_cv = (variance**0.5) / mean
    else:
        amount_cv = 1.0

    return {
        "company_ids": list(cycle),
        "length": len(cycle),
        "hop_amounts": [round(a, 2) for a in amounts],
        "total_cycle_value": round(total, 2),
        "amount_cv": round(amount_cv, 4),
        "invoice_ids": sorted(set(invoice_ids)),
        "invoice_count": invoice_count,
        "eway_missing_count": eway_missing,
        "eway_missing_ratio": round(eway_missing / invoice_count, 4) if invoice_count else 0.0,
    }


def detect_rings(graph: nx.DiGraph, max_length: int | None = None) -> list[dict]:
    """Find every candidate ring and attach its evidence bundle."""
    return [cycle_evidence(graph, cycle) for cycle in find_cycles(graph, max_length)]
