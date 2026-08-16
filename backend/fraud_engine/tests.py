"""
Tests for the fraud engine.

One file, split into classes by concern:
  CycleDetectionTests - does the graph layer actually find the rings?
  RiskScoringTests    - does the model rank fraud above benign trade?
  LedgerTests         - is the audit chain genuinely tamper-evident?
"""
from datetime import date, timedelta

import networkx as nx
import numpy as np
import pandas as pd
from django.test import TestCase

from core.management.commands.seed_demo_data import build_synthetic_network
from core.models import Company, Invoice
from fraud_engine import cycle_detection, ledger, risk_scoring
from fraud_engine.graph_builder import build_graph, build_graph_from_dataframes
from fraud_engine.models import LedgerBlock


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

    def test_detection_is_fast_enough_to_run_synchronously(self):
        """
        The SCC pre-filter is what makes a synchronous API call viable.
        If this ever gets slow, the design decision to skip a job queue is
        the thing that needs revisiting.
        """
        import time

        net = build_synthetic_network(seed=42)
        graph = graph_from_network(net)

        started = time.perf_counter()
        cycle_detection.find_cycles(graph)
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 2.0, "cycle detection is too slow for a sync request")

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


class RiskScoringTests(TestCase):
    """Feature engineering, model inference and SHAP explanation."""

    @classmethod
    def setUpTestData(cls):
        # Generating a network is the slow part, so do it once for the class.
        cls.net = build_synthetic_network(seed=42)
        cls.companies, cls.invoices = dataframes_from_network(cls.net)
        cls.graph = build_graph_from_dataframes(cls.companies, cls.invoices)
        cls.rings = cycle_detection.detect_rings(cls.graph)

    def test_pretrained_artifact_is_present(self):
        """A fresh clone must be able to score without training anything."""
        self.assertTrue(
            risk_scoring.MODEL_PATH.exists(),
            "the committed pretrained model is missing from models_artifacts/",
        )
        self.assertIsNotNone(risk_scoring.load_model())

    def test_feature_matrix_is_complete_and_finite(self):
        features = risk_scoring.engineer_features(
            self.companies, self.invoices, self.rings
        )

        self.assertEqual(list(features.columns), risk_scoring.FEATURE_NAMES)
        self.assertEqual(len(features), len(self.companies))
        self.assertFalse(features.isna().any().any(), "features contain NaN")
        self.assertTrue(np.isfinite(features.values).all(), "features contain inf")

    def test_shared_registration_details_are_counted(self):
        """Shell rings reuse addresses; the feature must actually see that."""
        features = risk_scoring.engineer_features(
            self.companies, self.invoices, self.rings
        )
        shell_ids = self.net.fraud_company_indices

        self.assertGreater(
            features.loc[list(shell_ids), "shared_address_count"].max(),
            0,
            "no shell company shares an address with another",
        )

    def test_companies_outside_every_loop_score_zero(self):
        """
        The model only judges what cycle detection surfaced. A company in no
        loop is not a circular-trade suspect and must not be given a score
        by a model that never trained on such companies.
        """
        scores = risk_scoring.score_network(self.companies, self.invoices, self.rings)
        candidates = risk_scoring.candidate_company_ids(self.rings)

        outsiders = [cid for cid in scores.index if cid not in candidates]
        self.assertTrue(outsiders, "expected some companies outside every loop")
        for cid in outsiders:
            self.assertEqual(scores.loc[cid, "score"], 0.0)

    def test_scores_stay_in_range(self):
        scores = risk_scoring.score_network(self.companies, self.invoices, self.rings)

        self.assertGreaterEqual(scores["score"].min(), 0.0)
        self.assertLessEqual(scores["score"].max(), 100.0)

    def test_fraud_rings_outrank_benign_loops(self):
        """
        The headline claim of the whole ML stage: given a mixed bag of real
        rings and genuine two-way trade, the real rings come out on top.
        """
        scores = risk_scoring.score_network(self.companies, self.invoices, self.rings)
        fraud_sets = {frozenset(r) for r in self.net.fraud_rings}

        ranked = sorted(
            (
                (risk_scoring.ring_risk(ring, scores)[0], frozenset(ring["company_ids"]))
                for ring in self.rings
            ),
            key=lambda pair: -pair[0],
        )

        top = [key for _, key in ranked[: len(fraud_sets)]]
        recovered = sum(1 for key in top if key in fraud_sets)

        self.assertEqual(
            recovered,
            len(fraud_sets),
            f"only {recovered}/{len(fraud_sets)} injected rings made the top of the queue",
        )

    def test_benign_loops_score_well_below_fraud_rings(self):
        scores = risk_scoring.score_network(self.companies, self.invoices, self.rings)
        fraud_sets = {frozenset(r) for r in self.net.fraud_rings}
        benign_sets = {frozenset(r) for r in self.net.benign_loops}

        fraud_scores, benign_scores = [], []
        for ring in self.rings:
            score = risk_scoring.ring_risk(ring, scores)[0]
            key = frozenset(ring["company_ids"])
            if key in fraud_sets:
                fraud_scores.append(score)
            elif key in benign_sets:
                benign_scores.append(score)

        self.assertGreater(min(fraud_scores), max(benign_scores))

    def test_explanations_are_human_readable(self):
        scores = risk_scoring.score_network(self.companies, self.invoices, self.rings)
        worst = scores["score"].idxmax()
        reasons = scores.loc[worst, "explanation"]

        self.assertTrue(reasons)
        for reason in reasons:
            self.assertIn(reason["feature"], risk_scoring.FEATURE_NAMES)
            self.assertIn(reason["direction"], {"increases_risk", "decreases_risk"})
            # A sentence, not a variable name dumped to screen.
            self.assertGreater(len(reason["text"]), 25)
            self.assertIn(" ", reason["text"])

    def test_ring_explanation_summarises_its_members(self):
        scores = risk_scoring.score_network(self.companies, self.invoices, self.rings)
        worst_ring = max(self.rings, key=lambda r: risk_scoring.ring_risk(r, scores)[0])

        score, explanation = risk_scoring.ring_risk(worst_ring, scores)

        self.assertGreater(score, 50.0)
        self.assertTrue(explanation)
        self.assertLessEqual(len(explanation), 4)

    def test_empty_database_does_not_crash(self):
        empty = pd.DataFrame()
        features = risk_scoring.engineer_features(empty, empty, [])

        self.assertTrue(features.empty)


class LedgerTests(TestCase):
    """The audit chain must be genuinely tamper-evident, not decoratively so."""

    def test_first_block_links_to_genesis(self):
        block = ledger.append_block({"ring": 1})

        self.assertEqual(block.index, 0)
        self.assertEqual(block.previous_hash, ledger.GENESIS_PREVIOUS_HASH)

    def test_blocks_chain_to_their_predecessor(self):
        first = ledger.append_block({"ring": 1})
        second = ledger.append_block({"ring": 2})
        third = ledger.append_block({"ring": 3})

        self.assertEqual(second.previous_hash, first.hash)
        self.assertEqual(third.previous_hash, second.hash)
        self.assertEqual([first.index, second.index, third.index], [0, 1, 2])

    def test_empty_chain_is_valid(self):
        report = ledger.verify_chain()

        self.assertTrue(report["valid"])
        self.assertEqual(report["block_count"], 0)

    def test_untouched_chain_verifies(self):
        for i in range(5):
            ledger.append_block({"ring": i, "risk_score": 90 + i})

        report = ledger.verify_chain()

        self.assertTrue(report["valid"])
        self.assertEqual(report["block_count"], 5)
        self.assertEqual(report["head_hash"], LedgerBlock.objects.order_by("-index").first().hash)

    def test_hashing_is_deterministic_regardless_of_key_order(self):
        """Re-serialising the same evidence must not look like tampering."""
        a = ledger.compute_hash(0, "2026-01-01T00:00:00", {"x": 1, "y": 2}, "0" * 64)
        b = ledger.compute_hash(0, "2026-01-01T00:00:00", {"y": 2, "x": 1}, "0" * 64)

        self.assertEqual(a, b)

    def test_tampering_with_a_payload_is_detected(self):
        """The headline guarantee: you cannot quietly edit a past finding."""
        for i in range(4):
            ledger.append_block({"ring": i, "risk_score": 95.0})

        # Someone edits a historical block directly in the database, exactly as
        # an UPDATE statement would - and does not touch any hash.
        victim = LedgerBlock.objects.get(index=1)
        victim.payload = {"ring": 1, "risk_score": 12.0}
        victim.save(update_fields=["payload"])

        report = ledger.verify_chain()

        self.assertFalse(report["valid"])
        self.assertEqual(report["broken_at_index"], 1)
        self.assertIn("altered", report["message"])

    def test_tampering_with_a_timestamp_is_detected(self):
        for i in range(3):
            ledger.append_block({"ring": i})

        victim = LedgerBlock.objects.get(index=2)
        victim.timestamp = victim.timestamp - timedelta(days=365)
        victim.save(update_fields=["timestamp"])

        report = ledger.verify_chain()

        self.assertFalse(report["valid"])
        self.assertEqual(report["broken_at_index"], 2)

    def test_deleting_a_block_is_detected(self):
        for i in range(4):
            ledger.append_block({"ring": i})

        LedgerBlock.objects.get(index=1).delete()

        report = ledger.verify_chain()

        self.assertFalse(report["valid"])

    def test_a_broken_link_is_detected_even_if_the_block_rehashes(self):
        """
        Recomputing one block's own hash is not enough to hide an edit: the
        NEXT block still commits to the old hash, so the break surfaces there.
        """
        for i in range(3):
            ledger.append_block({"ring": i})

        victim = LedgerBlock.objects.get(index=1)
        victim.payload = {"ring": "edited"}
        # The forger is careful and fixes this block's own hash...
        victim.hash = ledger.compute_hash(
            victim.index, victim.timestamp.isoformat(), victim.payload, victim.previous_hash
        )
        victim.save(update_fields=["payload", "hash"])

        report = ledger.verify_chain()

        # ...but block #2 still points at the pre-edit hash.
        self.assertFalse(report["valid"])
        self.assertEqual(report["broken_at_index"], 2)

    def test_payload_survives_a_round_trip(self):
        payload = {
            "record_type": "confirmed_fraud_ring",
            "company_ids": [4, 9, 17],
            "risk_score": 98.6,
            "explanation": [{"feature": "eway_missing_ratio", "text": "No e-way bills."}],
        }

        block = ledger.append_block(payload)
        stored = LedgerBlock.objects.get(index=block.index)

        self.assertEqual(stored.payload, payload)
        self.assertTrue(ledger.verify_chain()["valid"])