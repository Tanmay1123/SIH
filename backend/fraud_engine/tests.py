"""
Tests for the fraud engine.

One file, split into classes by concern:
  CycleDetectionTests - does the graph layer actually find the rings?
  RiskScoringTests    - does the model rank fraud above benign trade?
  LedgerTests         - is the audit chain genuinely tamper-evident?
"""
from datetime import date, timedelta

import networkx as nx
import pandas as pd
from django.test import TestCase

from core.management.commands.seed_demo_data import build_synthetic_network
from core.models import Company, Invoice
from fraud_engine import cycle_detection
from fraud_engine.graph_builder import build_graph, build_graph_from_dataframes


def dataframes_from_network(net) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Convert a generated network into the same DataFrame shape the database
    layer produces, so tests can exercise the real pipeline without saving
    thousands of rows.
    """
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
    return companies, invoices


def graph_from_network(net) -> nx.DiGraph:
    """Build a DiGraph straight from a generated network, without touching the DB."""
    return build_graph_from_dataframes(*dataframes_from_network(net))


class CycleDetectionTests(TestCase):
    """Stage 1 (Tarjan SCC) + stage 2 (Johnson's) behaviour."""

    def test_finds_a_simple_triangle(self):
        g = nx.DiGraph()
        g.add_edge(1, 2, total_amount=100.0, invoice_count=1, invoice_ids=[1], eway_missing=0)
        g.add_edge(2, 3, total_amount=100.0, invoice_count=1, invoice_ids=[2], eway_missing=0)
        g.add_edge(3, 1, total_amount=100.0, invoice_count=1, invoice_ids=[3], eway_missing=0)

        cycles = cycle_detection.find_cycles(g)

        self.assertEqual(len(cycles), 1)
        self.assertEqual(set(cycles[0]), {1, 2, 3})

    def test_ignores_a_pure_chain(self):
        """A -> B -> C with no way back is not a ring."""
        g = nx.DiGraph()
        g.add_edge(1, 2)
        g.add_edge(2, 3)

        self.assertEqual(cycle_detection.find_cycles(g), [])

    def test_rotations_are_deduplicated(self):
        """[1,2,3] and [2,3,1] are the same ring and must be reported once."""
        self.assertEqual(
            cycle_detection.canonical_cycle([2, 3, 1]),
            cycle_detection.canonical_cycle([1, 2, 3]),
        )
        self.assertEqual(
            cycle_detection.canonical_cycle([3, 1, 2]),
            cycle_detection.canonical_cycle([1, 2, 3]),
        )

    def test_respects_the_length_bound(self):
        g = nx.DiGraph()
        ring = list(range(1, 9))  # an 8-company ring
        for a, b in zip(ring, ring[1:] + ring[:1]):
            g.add_edge(a, b)

        self.assertEqual(cycle_detection.find_cycles(g, max_length=6), [])
        self.assertEqual(len(cycle_detection.find_cycles(g, max_length=8)), 1)

    def test_every_injected_fraud_ring_is_detected(self):
        """The headline guarantee: we find the rings we planted."""
        for seed in (42, 7, 1234):
            with self.subTest(seed=seed):
                net = build_synthetic_network(seed=seed)
                graph = graph_from_network(net)

                found = {
                    frozenset(c) for c in cycle_detection.find_cycles(graph)
                }
                for ring in net.fraud_rings:
                    self.assertIn(
                        frozenset(ring),
                        found,
                        f"injected fraud ring {ring} was not detected",
                    )

    def test_benign_reciprocal_loops_are_also_detected(self):
        """
        Cycle detection alone cannot tell fraud from genuine two-way trade -
        it finds both. That is exactly why the risk model exists.
        """
        net = build_synthetic_network(seed=42)
        graph = graph_from_network(net)
        found = {frozenset(c) for c in cycle_detection.find_cycles(graph)}

        for loop in net.benign_loops:
            self.assertIn(frozenset(loop), found)

    def test_detection_runs_against_the_database(self):
        """End-to-end through Django models, not just in-memory DataFrames."""
        today = date.today()
        companies = [
            Company.objects.create(
                gstin=f"27AAAAA0000A1Z{i}",
                pan=f"AAAAA000{i}A",
                name=f"Company {i}",
                director_name=f"Director {i}",
                registered_address=f"{i} Test Street",
                registered_date=today - timedelta(days=200),
                declared_turnover=1_000_000,
            )
            for i in range(3)
        ]
        for a, b in zip(companies, companies[1:] + companies[:1]):
            Invoice.objects.create(
                seller=a, buyer=b, amount=500_000, date=today - timedelta(days=10),
                goods_description="Test goods", has_eway_bill=False,
            )

        graph = build_graph()
        rings = cycle_detection.detect_rings(graph)

        self.assertEqual(len(rings), 1)
        self.assertEqual(rings[0]["length"], 3)
        self.assertEqual(rings[0]["eway_missing_count"], 3)
        self.assertEqual(rings[0]["total_cycle_value"], 1_500_000.0)

    def test_evidence_flags_uniform_hop_amounts(self):
        """Near-identical amounts round a loop drive the CV towards zero."""
        g = nx.DiGraph()
        for a, b, amt in [(1, 2, 1_000_000.0), (2, 3, 1_002_000.0), (3, 1, 998_000.0)]:
            g.add_edge(a, b, total_amount=amt, invoice_count=1, invoice_ids=[a], eway_missing=1)

        evidence = cycle_detection.cycle_evidence(g, [1, 2, 3])

        self.assertLess(evidence["amount_cv"], 0.01)
        self.assertEqual(evidence["eway_missing_ratio"], 1.0)

    def test_self_invoices_are_not_rings(self):
        """A company invoicing itself is a data artefact, not a length-1 ring."""
        companies = pd.DataFrame([{
            "id": 1, "gstin": "27AAAAA0000A1Z5", "pan": "AAAAA0000A", "name": "Solo",
            "director_name": "D", "registered_address": "A", "declared_turnover": 1.0,
            "registered_date": pd.Timestamp("2023-01-01"),
        }])
        invoices = pd.DataFrame([{
            "id": 1, "seller_id": 1, "buyer_id": 1, "amount": 100.0,
            "date": pd.Timestamp("2024-01-01"), "goods_description": "x",
            "has_eway_bill": True,
        }])

        graph = build_graph_from_dataframes(companies, invoices)

        self.assertEqual(cycle_detection.find_cycles(graph), [])
