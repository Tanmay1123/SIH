"""
Tests for the fraud engine.

One file, split into classes by concern:
  CycleDetectionTests  - does the graph layer actually find the rings?
  RiskScoringTests     - does the model rank fraud above benign trade?
  LedgerTests          - is the audit chain genuinely tamper-evident?
  ControlEdgeTests     - do we find rings that close through shared ownership?
  MillDetectionTests   - do we find fraud that is not a loop at all?
  OfficerReviewTests   - can an officer tell the system it was wrong?
  DatasetHistoryTests  - do past uploads survive a new one?
  CaseReportTests      - does the supervisor's report say what happened?
  RoleTests            - can an officer do only what an officer should?
  AppSettingsTests     - does policy come from the database, then .env?
  DatasetLabTests      - does the generator produce what it says it does?
  ManagementCommandTests - do setup_accounts and reset_data behave?
  ReportPdfTests       - PDF generation, company reports, generate-vs-send
"""
from datetime import date, timedelta
from io import StringIO

import networkx as nx
import numpy as np
import pandas as pd
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from fraud_engine.synthetic_network import build_synthetic_network
from core.models import Company, Dataset, Invoice
from fraud_engine import (
    cycle_detection,
    dataset_lab,
    graph_builder,
    ledger,
    mailer,
    mill_detection,
    reporting,
    risk_scoring,
)
from fraud_engine.graph_builder import build_graph, build_graph_from_dataframes
from fraud_engine.models import CaseReport, DetectionRun, FlaggedRing, LedgerBlock
from fraud_engine.pipeline import execute_run
from fraud_engine.settings_helpers import risk_threshold, supervisor_emails
from core.management.commands.setup_accounts import make_password
from core.roles import is_supervisor
from core import roles
from core.settings_store import set_setting


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

# ---------------------------------------------------------------------------
# Non-loop fraud, ownership-closed rings, and the officer review loop
# ---------------------------------------------------------------------------


class ControlEdgeTests(TestCase):
    """
    Rings that close through shared ownership rather than through an invoice.

    A -> B -> C by bill, where C and A share a director, is a real circular
    trade ring. Invoice-only detection cannot see it at all - which is the gap
    an evaluator asked about.
    """

    def _frames(self, rows, invoice_pairs):
        companies = pd.DataFrame(rows)
        companies["registered_date"] = pd.to_datetime(companies["registered_date"])
        invoices = pd.DataFrame(
            [
                {
                    "id": i,
                    "seller_id": s,
                    "buyer_id": b,
                    "amount": 1_000_000.0,
                    "date": pd.Timestamp("2025-06-01"),
                    "goods_description": "goods",
                    "has_eway_bill": False,
                }
                for i, (s, b) in enumerate(invoice_pairs, start=1)
            ]
        )
        return companies, invoices

    def _three_companies(self, addresses, directors):
        return [
            {
                "id": i + 1,
                "gstin": f"27AAAAA0000A1Z{i}",
                "pan": f"AAAAA000{i}A",
                "name": f"Company {i}",
                "director_name": directors[i],
                "registered_address": addresses[i],
                "registered_date": "2024-01-01",
                "declared_turnover": 100000.0,
            }
            for i in range(3)
        ]

    def test_open_chain_stays_open_without_control_edges(self):
        """A -> B -> C is not a ring on an invoice-only graph."""
        rows = self._three_companies(
            ["Addr 1", "Addr 2", "Addr 3"], ["Dir 1", "Dir 2", "Dir 3"]
        )
        companies, invoices = self._frames(rows, [(1, 2), (2, 3)])

        graph = build_graph_from_dataframes(companies, invoices)

        self.assertEqual(cycle_detection.find_cycles(graph), [])

    def test_shared_director_closes_the_loop(self):
        """The same chain IS a ring once C and A are known to share a director."""
        rows = self._three_companies(
            ["Addr 1", "Addr 2", "Addr 3"], ["Same Person", "Dir 2", "Same Person"]
        )
        companies, invoices = self._frames(rows, [(1, 2), (2, 3)])

        graph = build_graph_from_dataframes(
            companies, invoices, include_control_edges=True
        )
        cycles = cycle_detection.find_cycles(graph)

        self.assertEqual(len(cycles), 1)
        self.assertEqual(set(cycles[0]), {1, 2, 3})

        evidence = cycle_detection.cycle_evidence(graph, cycles[0])
        self.assertEqual(evidence["closure"], "control")
        self.assertEqual(len(evidence["control_links"]), 1)
        self.assertIn("director", evidence["control_links"][0]["shared_via"])

    def test_shared_address_closes_the_loop(self):
        rows = self._three_companies(
            ["One Road", "Addr 2", "One Road"], ["Dir 1", "Dir 2", "Dir 3"]
        )
        companies, invoices = self._frames(rows, [(1, 2), (2, 3)])

        graph = build_graph_from_dataframes(
            companies, invoices, include_control_edges=True
        )

        self.assertEqual(len(cycle_detection.find_cycles(graph)), 1)

    def test_shared_address_alone_is_not_a_ring(self):
        """
        Companies at one address with no trade between them are not a ring.
        Without this guard every shared address would manufacture fake cycles.
        """
        rows = self._three_companies(
            ["One Road", "One Road", "One Road"], ["Dir 1", "Dir 2", "Dir 3"]
        )
        companies = pd.DataFrame(rows)
        companies["registered_date"] = pd.to_datetime(companies["registered_date"])
        invoices = pd.DataFrame(
            columns=["id", "seller_id", "buyer_id", "amount", "date",
                     "goods_description", "has_eway_bill"]
        )

        graph = build_graph_from_dataframes(
            companies, invoices, include_control_edges=True
        )

        self.assertEqual(cycle_detection.find_cycles(graph), [])

    def test_a_real_invoice_edge_is_never_downgraded_to_a_control_edge(self):
        """If A already sells to B, that stays a trade relationship."""
        rows = self._three_companies(
            ["One Road", "One Road", "Addr 3"], ["Dir 1", "Dir 2", "Dir 3"]
        )
        companies, invoices = self._frames(rows, [(1, 2)])

        graph = build_graph_from_dataframes(
            companies, invoices, include_control_edges=True
        )

        edge = graph.get_edge_data(1, 2)
        self.assertEqual(edge["relation"], "invoice")
        self.assertEqual(edge["total_amount"], 1_000_000.0)
        # The shared address is still recorded on it as extra evidence.
        self.assertIn("address", edge.get("shared_via", []))

    def test_control_edges_do_not_inflate_the_traded_total(self):
        rows = self._three_companies(
            ["One Road", "One Road", "One Road"], ["Dir 1", "Dir 2", "Dir 3"]
        )
        companies, invoices = self._frames(rows, [(1, 2)])

        graph = build_graph_from_dataframes(
            companies, invoices, include_control_edges=True
        )
        summary = graph_builder.graph_summary(graph)

        self.assertEqual(summary["trade_relationships"], 1)
        self.assertGreater(summary["control_links"], 0)
        self.assertEqual(summary["total_traded_value"], 1_000_000.0)


class MillDetectionTests(TestCase):
    """
    Fake invoice mills: a shell selling to many buyers and buying from nobody.

    This is a star, not a loop, so cycle detection is structurally blind to it -
    and it is the most common form of real GST fraud.
    """

    def _network(self, n_buyers=12, mill_has_purchases=False):
        rows = [
            {
                "id": 1,
                "gstin": "27MILLA0000A1Z0",
                "pan": "MILLA0000A",
                "name": "Mill Traders",
                "director_name": "Mill Director",
                "registered_address": "1 Mill Road",
                "registered_date": (date.today() - timedelta(days=120)).isoformat(),
                "declared_turnover": 50_000.0,
            }
        ]
        rows += [
            {
                "id": i,
                "gstin": f"27BUYER000A1Z{i}",
                "pan": f"BUYER{i:04d}A",
                "name": f"Buyer {i}",
                "director_name": f"Director {i}",
                "registered_address": f"{i} Buyer Street",
                "registered_date": "2015-01-01",
                "declared_turnover": 50_000_000.0,
            }
            for i in range(2, 2 + n_buyers)
        ]
        companies = pd.DataFrame(rows)
        companies["registered_date"] = pd.to_datetime(companies["registered_date"])

        invoice_rows = [
            {
                "id": i,
                "seller_id": 1,
                "buyer_id": buyer,
                "amount": 1_000_000.0,
                "date": pd.Timestamp("2025-06-01"),
                "goods_description": "goods",
                "has_eway_bill": False,
            }
            for i, buyer in enumerate(range(2, 2 + n_buyers), start=1)
        ]
        if mill_has_purchases:
            invoice_rows.append(
                {
                    "id": 999,
                    "seller_id": 2,
                    "buyer_id": 1,
                    "amount": 11_000_000.0,
                    "date": pd.Timestamp("2025-05-01"),
                    "goods_description": "goods",
                    "has_eway_bill": True,
                }
            )
        return companies, pd.DataFrame(invoice_rows)

    def test_cycle_detection_cannot_see_a_mill(self):
        """The premise: this fraud shape produces no cycle at all."""
        companies, invoices = self._network()
        graph = build_graph_from_dataframes(
            companies, invoices, include_control_edges=True
        )

        self.assertEqual(cycle_detection.find_cycles(graph), [])

    def test_mill_detector_finds_it(self):
        companies, invoices = self._network()

        mills = mill_detection.detect_mills(companies, invoices)

        self.assertEqual(len(mills), 1)
        found = mills[0]
        self.assertEqual(found["mill_company_id"], 1)
        self.assertEqual(found["kind"], "mill")
        self.assertGreater(found["risk_score"], 60)
        self.assertEqual(found["evidence"]["buyer_count"], 12)
        self.assertEqual(found["evidence"]["supplier_count"], 0)

    def test_a_company_that_actually_buys_what_it_sells_is_not_a_mill(self):
        """The one-way flow is the whole signal. Remove it and the alert goes."""
        companies, invoices = self._network(mill_has_purchases=True)

        mills = mill_detection.detect_mills(companies, invoices)

        self.assertEqual([m for m in mills if m["mill_company_id"] == 1], [])

    def test_too_few_buyers_is_not_a_mill(self):
        """A lopsided company with two customers is a small business."""
        companies, invoices = self._network(n_buyers=2)

        self.assertEqual(mill_detection.detect_mills(companies, invoices), [])

    def test_mill_explanations_are_human_readable(self):
        companies, invoices = self._network()

        found = mill_detection.detect_mills(companies, invoices)[0]

        self.assertTrue(found["explanation"])
        for reason in found["explanation"]:
            self.assertGreater(len(reason["text"]), 25)
            self.assertIn(" ", reason["text"])
            self.assertIn(reason["direction"], {"increases_risk", "decreases_risk"})

    def test_empty_input_does_not_crash(self):
        empty = pd.DataFrame()
        self.assertEqual(mill_detection.detect_mills(empty, empty), [])


class OfficerReviewTests(TestCase):
    """
    The human-in-the-loop half that did not exist before: an officer being
    able to say the system was WRONG, and that decision being recorded.
    """

    def setUp(self):
        self.dataset = Dataset.objects.create(name="Test dataset")
        today = date.today()
        self.companies = [
            Company.objects.create(
                dataset=self.dataset,
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
        for a, b in zip(self.companies, self.companies[1:] + self.companies[:1]):
            Invoice.objects.create(
                dataset=self.dataset, seller=a, buyer=b, amount=500_000,
                date=today - timedelta(days=10), goods_description="Test goods",
                has_eway_bill=False,
            )
        self.dataset.activate()
        self.officer = User.objects.create_user("officer", password="x")

    def test_a_run_captures_model_provenance(self):
        run = execute_run(name="Run 1", user=self.officer)

        self.assertEqual(run.name, "Run 1")
        self.assertEqual(run.dataset, self.dataset)
        self.assertTrue(run.model_version, "model version was not recorded")
        self.assertEqual(run.risk_threshold, risk_threshold())
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(run.rings_detected, 1)

    def test_running_again_does_not_destroy_the_previous_run(self):
        first = execute_run(name="Run 1")
        second = execute_run(name="Run 2")

        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(DetectionRun.objects.count(), 2)
        self.assertEqual(first.rings.count(), 1)
        self.assertEqual(second.rings.count(), 1)

    def test_alerts_start_pending(self):
        run = execute_run()
        alert = run.rings.first()

        self.assertEqual(alert.status, FlaggedRing.STATUS_PENDING)
        self.assertFalse(alert.officer_confirmed)

    def test_dismissing_records_a_reason_and_the_officer(self):
        run = execute_run()
        alert = run.rings.first()

        alert.mark_dismissed("genuine_trade", user=self.officer, note="Known supplier.")
        alert.refresh_from_db()

        self.assertEqual(alert.status, FlaggedRing.STATUS_DISMISSED)
        self.assertFalse(alert.officer_confirmed)
        self.assertEqual(alert.dismissal_reason, "genuine_trade")
        self.assertEqual(alert.reviewed_by, self.officer)
        self.assertIsNotNone(alert.reviewed_at)

    def test_confirming_and_dismissing_never_disagree(self):
        run = execute_run()
        alert = run.rings.first()

        alert.mark_confirmed(user=self.officer)
        alert.refresh_from_db()
        self.assertTrue(alert.officer_confirmed)
        self.assertEqual(alert.status, FlaggedRing.STATUS_CONFIRMED)

        alert.mark_dismissed("genuine_trade", user=self.officer)
        alert.refresh_from_db()
        self.assertFalse(alert.officer_confirmed)
        self.assertEqual(alert.status, FlaggedRing.STATUS_DISMISSED)
        self.assertIsNone(alert.confirmed_at)

    def test_decisions_carry_forward_to_the_next_run(self):
        """An officer should not have to re-review work they already did."""
        first = execute_run(name="Run 1")
        first.rings.first().mark_dismissed("genuine_trade", user=self.officer)

        second = execute_run(name="Run 2")
        carried = second.rings.first()

        self.assertEqual(carried.status, FlaggedRing.STATUS_DISMISSED)
        self.assertEqual(carried.dismissal_reason, "genuine_trade")
        self.assertEqual(carried.reviewed_by, self.officer)

    def test_confirmation_ledger_block_records_the_model_version(self):
        """
        Provenance is the point: two years later you must be able to say which
        model, at which threshold, produced the flag the officer acted on.
        """
        run = execute_run(name="Run 1")
        alert = run.rings.first()
        alert.mark_confirmed(user=self.officer)

        payload = ledger.build_ring_payload(alert, self.companies, [], officer="officer")
        block = ledger.append_block(payload)

        self.assertEqual(block.payload["model"]["version"], run.model_version)
        self.assertEqual(block.payload["model"]["risk_threshold"], run.risk_threshold)
        self.assertEqual(block.payload["model"]["detection_run"], "Run 1")
        self.assertTrue(ledger.verify_chain()["valid"])

    def test_dismissals_are_recorded_in_the_ledger_too(self):
        run = execute_run()
        alert = run.rings.first()
        alert.mark_dismissed("genuine_trade", user=self.officer, note="Checked.")

        block = ledger.append_block(
            ledger.build_dismissal_payload(
                alert, "Genuine two-way trade", officer="officer", note="Checked."
            )
        )

        self.assertEqual(block.payload["record_type"], "dismissed_alert")
        self.assertEqual(block.payload["reason_code"], "genuine_trade")
        self.assertTrue(ledger.verify_chain()["valid"])


class DatasetHistoryTests(TestCase):
    """Uploads accumulate instead of overwriting each other."""

    def _dataset_with_company(self, name, gstin="27AAAAA0000A1Z0"):
        dataset = Dataset.objects.create(name=name)
        Company.objects.create(
            dataset=dataset, gstin=gstin, pan="AAAAA0000A", name="C",
            director_name="D", registered_address="A",
            registered_date=date(2024, 1, 1), declared_turnover=1,
        )
        return dataset

    def test_the_same_gstin_may_appear_in_two_datasets(self):
        """Uploading the same file twice must not collide on GSTIN."""
        self._dataset_with_company("First")
        self._dataset_with_company("Second")

        self.assertEqual(Company.objects.count(), 2)

    def test_a_gstin_is_still_unique_within_one_dataset(self):
        dataset = self._dataset_with_company("First")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Company.objects.create(
                    dataset=dataset, gstin="27AAAAA0000A1Z0", pan="AAAAA0000A",
                    name="Duplicate", director_name="D", registered_address="A",
                    registered_date=date(2024, 1, 1), declared_turnover=1,
                )

    def test_only_one_dataset_is_active_at_a_time(self):
        first = self._dataset_with_company("First")
        second = self._dataset_with_company("Second", gstin="27BBBBB0000B1Z0")

        first.activate()
        second.activate()
        first.refresh_from_db()

        self.assertFalse(first.is_active)
        self.assertTrue(Dataset.objects.get(pk=second.pk).is_active)
        self.assertEqual(Dataset.objects.filter(is_active=True).count(), 1)

    def test_the_graph_only_sees_the_active_dataset(self):
        first = self._dataset_with_company("First")
        self._dataset_with_company("Second", gstin="27BBBBB0000B1Z0")

        first.activate()
        companies, _ = graph_builder.load_dataframes()

        self.assertEqual(len(companies), 1)
        self.assertEqual(companies.iloc[0]["gstin"], "27AAAAA0000A1Z0")


class CaseReportTests(TestCase):
    """The supervisor report, and its link into the audit ledger."""

    def setUp(self):
        self.dataset = Dataset.objects.create(name="Test dataset")
        today = date.today()
        companies = [
            Company.objects.create(
                dataset=self.dataset, gstin=f"27AAAAA0000A1Z{i}", pan=f"AAAAA000{i}A",
                name=f"Company {i}", director_name=f"Director {i}",
                registered_address=f"{i} Test Street",
                registered_date=today - timedelta(days=200), declared_turnover=1_000_000,
            )
            for i in range(3)
        ]
        for a, b in zip(companies, companies[1:] + companies[:1]):
            Invoice.objects.create(
                dataset=self.dataset, seller=a, buyer=b, amount=500_000,
                date=today - timedelta(days=10), goods_description="Test goods",
                has_eway_bill=False,
            )
        self.dataset.activate()
        self.officer = User.objects.create_user("officer", password="x", email="o@example.com")
        self.run = execute_run(name="Run 1", user=self.officer)

    def test_summary_counts_the_officers_decisions(self):
        alert = self.run.rings.first()
        alert.mark_confirmed(user=self.officer)

        summary = reporting.build_summary(self.run)

        self.assertEqual(summary["confirmed_count"], 1)
        self.assertEqual(summary["dismissed_count"], 0)
        self.assertEqual(summary["companies_implicated"], 3)
        self.assertEqual(len(summary["cases"]), 1)

    def test_dismissal_reasons_are_broken_out(self):
        self.run.rings.first().mark_dismissed("genuine_trade", user=self.officer)

        summary = reporting.build_summary(self.run)

        self.assertEqual(summary["dismissed_count"], 1)
        self.assertEqual(summary["dismissal_breakdown"], {"Genuine two-way trade": 1})

    def test_report_html_contains_the_evidence_and_escapes_input(self):
        alert = self.run.rings.first()
        alert.mark_confirmed(user=self.officer, note="<script>alert(1)</script>")

        summary = reporting.build_summary(self.run)
        html = reporting.render_report_html(self.run, summary, "officer", ["s@example.com"])

        self.assertIn("Run 1", html)
        self.assertIn("s@example.com", html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_content_hash_changes_when_the_report_changes(self):
        summary = reporting.build_summary(self.run)
        html = reporting.render_report_html(self.run, summary, "officer", [])

        first = reporting.content_hash(html, summary)
        second = reporting.content_hash(html + " ", summary)

        self.assertEqual(len(first), 64)
        self.assertNotEqual(first, second)

    def test_report_hash_goes_into_the_ledger(self):
        summary = reporting.build_summary(self.run)
        html = reporting.render_report_html(self.run, summary, "officer", [])
        report = CaseReport.objects.create(
            run=self.run, title="Case report", generated_by=self.officer,
            html=html, summary=summary,
            content_hash=reporting.content_hash(html, summary),
            recipients=["s@example.com"],
        )

        block = ledger.append_block(ledger.build_report_payload(report, "officer"))

        self.assertEqual(block.payload["record_type"], "case_report_issued")
        self.assertEqual(block.payload["content_sha256"], report.content_hash)
        self.assertEqual(block.payload["model"]["version"], self.run.model_version)
        self.assertTrue(ledger.verify_chain()["valid"])

    def test_sending_with_the_console_backend_succeeds(self):
        summary = reporting.build_summary(self.run)
        html = reporting.render_report_html(self.run, summary, "officer", [])
        report = CaseReport.objects.create(
            run=self.run, title="Case report", html=html, summary=summary,
            recipients=["supervisor@example.com"],
        )

        mailer.send_report(report, "officer")
        report.refresh_from_db()

        self.assertEqual(report.status, CaseReport.STATUS_SENT)
        self.assertIsNotNone(report.sent_at)
        self.assertEqual(report.error, "")

    def test_sending_with_no_recipients_fails_loudly_but_does_not_raise(self):
        report = CaseReport.objects.create(
            run=self.run, title="Case report", html="<p>x</p>", recipients=[]
        )

        mailer.send_report(report, "officer")
        report.refresh_from_db()

        self.assertEqual(report.status, CaseReport.STATUS_FAILED)
        self.assertIn("No recipients", report.error)


class ReportPdfTests(TestCase):
    """
    The PDF path, and the two report shapes that share it.

    A run report summarises a whole detection pass; a company report is one
    flagged node's own registration details and explanation, generated
    on-demand rather than tied to any officer decision. Both are rendered to
    HTML once, turned into a PDF on request, and use the same content_hash
    already written to the ledger to prove the PDF says what was issued.
    """

    def setUp(self):
        self.dataset = Dataset.objects.create(name="PDF dataset")
        today = date.today()
        companies = [
            Company.objects.create(
                dataset=self.dataset, gstin=f"27AAAAA0000A1Z{i}", pan=f"AAAAA000{i}A",
                name=f"Rupee Traders {i}", director_name=f"Director {i}",
                registered_address=f"{i} Test Street",
                registered_date=today - timedelta(days=200), declared_turnover=1_000_000,
            )
            for i in range(3)
        ]
        for a, b in zip(companies, companies[1:] + companies[:1]):
            Invoice.objects.create(
                dataset=self.dataset, seller=a, buyer=b, amount=500_000,
                date=today - timedelta(days=10), goods_description="Test goods",
                has_eway_bill=False,
            )
        self.dataset.activate()
        self.companies = companies
        self.officer = User.objects.create_user(
            "pdfofficer", password="pw-pdf-12345", email="o@example.com"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.officer)

    # ---- render_pdf --------------------------------------------------------

    def test_render_pdf_produces_a_real_pdf(self):
        pdf_bytes = reporting.render_pdf("<p>Hello</p>")

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_render_pdf_survives_the_rupee_sign(self):
        """
        xhtml2pdf's default fonts have no glyph for ₹ - this is a regression
        guard on the fallback, not just a "doesn't crash" smoke test.
        """
        pdf_bytes = reporting.render_pdf(f"<p>{reporting.inr(1_25_00_000)}</p>")

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    # ---- company report -----------------------------------------------------

    def test_company_summary_reads_the_same_evidence_as_the_evidence_panel(self):
        run = execute_run(name="Run 1", user=self.officer)
        company = self.companies[0]

        summary = reporting.build_company_summary(company)

        self.assertEqual(summary["gstin"], company.gstin)
        self.assertEqual(summary["director_name"], company.director_name)
        self.assertIsInstance(summary["explanation"], list)
        self.assertIsInstance(summary["alerts"], list)

    def test_company_report_html_contains_the_registration_details(self):
        summary = reporting.build_company_summary(self.companies[0])

        html = reporting.render_company_report_html(summary, "officer")

        self.assertIn("Rupee Traders 0", html)
        self.assertIn(self.companies[0].gstin, html)
        self.assertIn(self.companies[0].director_name, html)

    def test_a_company_with_no_alerts_still_gets_a_readable_report(self):
        """A clean company is a legitimate thing to ask about, not an error."""
        summary = reporting.build_company_summary(self.companies[0])

        html = reporting.render_company_report_html(summary, "officer")

        self.assertIn("does not appear in any flagged ring or mill", html)
        self.assertIn("not itself", html)  # the "not a finding of fraud" disclaimer

    def test_creating_a_company_report_writes_a_ledger_block(self):
        response = self.client.post(f"/api/companies/{self.companies[0].id}/report/")

        self.assertEqual(response.status_code, 201)
        report = CaseReport.objects.get(pk=response.data["id"])
        self.assertEqual(report.report_type, CaseReport.REPORT_TYPE_COMPANY)
        self.assertEqual(report.company_id, self.companies[0].id)
        self.assertIsNotNone(report.ledger_block)
        self.assertTrue(ledger.verify_chain()["valid"])

    def test_generating_a_company_report_does_not_send_it_by_default(self):
        response = self.client.post(f"/api/companies/{self.companies[0].id}/report/")

        self.assertEqual(response.data["status"], "draft")

    def test_an_officer_without_a_supervisor_role_can_still_request_one(self):
        """
        This is investigative material, not a decision - unlike confirming an
        alert, no supervisor gate applies here.
        """
        response = self.client.post(f"/api/companies/{self.companies[0].id}/report/")

        self.assertEqual(response.status_code, 201)

    def test_a_missing_company_returns_404_not_a_crash(self):
        response = self.client.post("/api/companies/999999/report/")

        self.assertEqual(response.status_code, 404)

    # ---- the pdf endpoint ---------------------------------------------------

    def test_report_pdf_endpoint_returns_a_pdf(self):
        created = self.client.post(f"/api/companies/{self.companies[0].id}/report/").data

        response = self.client.get(f"/api/reports/{created['id']}/pdf/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_report_pdf_endpoint_can_force_a_download(self):
        created = self.client.post(f"/api/companies/{self.companies[0].id}/report/").data

        response = self.client.get(f"/api/reports/{created['id']}/pdf/?download=1")

        self.assertIn("attachment", response["Content-Disposition"])

    def test_run_report_pdf_also_renders(self):
        run = execute_run(name="Run 1", user=self.officer)
        created = self.client.post(f"/api/fraud/runs/{run.id}/report/").data

        response = self.client.get(f"/api/reports/{created['id']}/pdf/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

    # ---- generate vs send is now two steps ----------------------------------

    def test_issuing_a_run_report_does_not_send_it_by_default(self):
        run = execute_run(name="Run 1", user=self.officer)

        response = self.client.post(f"/api/fraud/runs/{run.id}/report/")

        self.assertEqual(response.data["status"], "draft")

    def test_send_endpoint_delivers_a_generated_report(self):
        created = self.client.post(f"/api/companies/{self.companies[0].id}/report/").data

        response = self.client.post(f"/api/reports/{created['id']}/send/")

        self.assertEqual(response.data["status"], "sent")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_the_sent_email_carries_a_pdf_attachment_and_a_short_body(self):
        from django.core import mail

        report = CaseReport.objects.create(
            report_type=CaseReport.REPORT_TYPE_COMPANY,
            company=self.companies[0],
            title="Company report — Rupee Traders 0",
            html=reporting.render_company_report_html(
                reporting.build_company_summary(self.companies[0]), "officer"
            ),
            summary=reporting.build_company_summary(self.companies[0]),
            recipients=["supervisor@example.com"],
        )

        mailer.send_report(report, "officer")

        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(len(sent.attachments), 1)
        filename, content, mimetype = sent.attachments[0]
        self.assertEqual(mimetype, "application/pdf")
        self.assertTrue(content.startswith(b"%PDF"))
        # The body is a short cover note, not the whole report pasted in.
        self.assertLess(len(sent.body), 1000)
        self.assertIn("attached", sent.body.lower())


class RoleTests(TestCase):
    """
    Officers prepare and clear cases; supervisors sanction them.

    The split is the point of having roles at all: confirming an alert starts
    recovery proceedings against a real business, so it needs a second, more
    senior pair of eyes. Clearing stays with the officer, because that is the
    feedback the detector needs and gating it would mean it never happens.
    """

    def setUp(self):
        self.dataset = Dataset.objects.create(name="Roles dataset")
        today = date.today()
        companies = [
            Company.objects.create(
                dataset=self.dataset, gstin=f"27AAAAA0000A1Z{i}", pan=f"AAAAA000{i}A",
                name=f"Company {i}", director_name=f"Director {i}",
                registered_address=f"{i} Test Street",
                registered_date=today - timedelta(days=200), declared_turnover=1_000_000,
            )
            for i in range(3)
        ]
        for a, b in zip(companies, companies[1:] + companies[:1]):
            Invoice.objects.create(
                dataset=self.dataset, seller=a, buyer=b, amount=500_000,
                date=today - timedelta(days=10), goods_description="Goods",
                has_eway_bill=False,
            )
        self.dataset.activate()

        self.supervisors, _ = Group.objects.get_or_create(name="Supervisors")
        self.officer = User.objects.create_user("officer1", password="pw-officer-123")
        self.supervisor = User.objects.create_user("boss1", password="pw-boss-123")
        self.supervisor.groups.add(self.supervisors)

        self.run = execute_run(name="Role run", user=self.officer)
        self.alert = self.run.rings.first()

        self.client = APIClient()

    def _auth(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    # ---- role resolution --------------------------------------------------

    def test_a_plain_account_is_an_officer(self):
        self.assertFalse(roles.is_supervisor(self.officer))
        self.assertEqual(roles.role_of(self.officer), "officer")
        # Being an officer is about what you can SEE and CHANGE, not about
        # whether you may act on the queue - see the confirm tests below.
        self.assertFalse(roles.permissions_for(self.officer)["can_view_team"])
        self.assertFalse(roles.permissions_for(self.officer)["can_edit_settings"])

    def test_group_membership_makes_a_supervisor(self):
        self.assertTrue(roles.is_supervisor(self.supervisor))
        self.assertTrue(roles.permissions_for(self.supervisor)["can_confirm"])

    def test_a_superuser_is_always_a_supervisor(self):
        """Otherwise the first createsuperuser account could lock itself out."""
        root = User.objects.create_superuser("root1", "root@example.com", "pw-root-123")

        self.assertTrue(roles.is_supervisor(root))

    # ---- the boundary that matters ---------------------------------------

    def test_an_officer_can_confirm_an_alert(self):
        """
        Confirming used to be supervisor-only. It is an officer's call now -
        they are the one who read the evidence, and routing every confirmation
        through a supervisor made the supervisor a bottleneck on the queue
        rather than a check on it.

        What must not regress is the attribution: the confirmation has to
        record the officer who actually made it.
        """
        response = self._auth(self.officer).post(
            f"/api/fraud/rings/{self.alert.id}/confirm/"
        )

        self.assertEqual(response.status_code, 201)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, FlaggedRing.STATUS_CONFIRMED)
        self.assertEqual(self.alert.reviewed_by, self.officer)

    def test_a_supervisor_can_confirm_an_alert(self):
        response = self._auth(self.supervisor).post(
            f"/api/fraud/rings/{self.alert.id}/confirm/"
        )

        self.assertEqual(response.status_code, 201)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, FlaggedRing.STATUS_CONFIRMED)
        self.assertEqual(self.alert.reviewed_by, self.supervisor)

    def test_an_officer_CAN_dismiss_an_alert(self):
        """Clearing is the officer's job - it is the feedback the model needs."""
        response = self._auth(self.officer).post(
            f"/api/fraud/rings/{self.alert.id}/dismiss/",
            {"reason": "genuine_trade", "note": "Checked with the taxpayer."},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, FlaggedRing.STATUS_DISMISSED)
        self.assertEqual(self.alert.reviewed_by, self.officer)

    def test_an_officer_can_still_run_detection_and_issue_reports(self):
        client = self._auth(self.officer)

        self.assertEqual(client.post("/api/fraud/run/", {}, format="json").status_code, 201)
        self.assertEqual(
            client.post(f"/api/fraud/runs/{self.run.id}/report/", {"send": False}, format="json").status_code,
            201,
        )

    # ---- the team view ----------------------------------------------------

    def test_an_officer_cannot_see_the_team(self):
        self.assertEqual(self._auth(self.officer).get("/api/team/").status_code, 403)
        self.assertEqual(self._auth(self.officer).get("/api/team/activity/").status_code, 403)

    def test_a_supervisor_sees_every_officers_activity(self):
        self.alert.mark_dismissed("genuine_trade", user=self.officer)

        response = self._auth(self.supervisor).get("/api/team/")

        self.assertEqual(response.status_code, 200)
        by_name = {m["username"]: m for m in response.data["members"]}
        self.assertIn("officer1", by_name)
        self.assertEqual(by_name["officer1"]["activity"]["dismissed"], 1)
        self.assertEqual(by_name["officer1"]["activity"]["runs"], 1)
        self.assertEqual(by_name["boss1"]["role"], "supervisor")

    def test_activity_feed_merges_decisions_runs_and_reports(self):
        self.alert.mark_dismissed("genuine_trade", user=self.officer)

        response = self._auth(self.supervisor).get("/api/team/activity/")

        kinds = {event["kind"] for event in response.data}
        self.assertIn("dismissed", kinds)
        self.assertIn("run", kinds)

    def test_a_supervisor_cannot_demote_themselves(self):
        """The one move that could leave a deployment unable to confirm anything."""
        response = self._auth(self.supervisor).post(
            f"/api/team/{self.supervisor.id}/role/", {"role": "officer"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(roles.is_supervisor(self.supervisor))

    def test_a_supervisor_can_promote_an_officer(self):
        response = self._auth(self.supervisor).post(
            f"/api/team/{self.officer.id}/role/", {"role": "supervisor"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.officer.refresh_from_db()
        self.assertTrue(roles.is_supervisor(self.officer))

    # ---- the profile endpoint --------------------------------------------

    def test_me_reports_role_and_permissions(self):
        response = self._auth(self.officer).get("/api/auth/me/")

        self.assertEqual(response.data["role"], "officer")
        self.assertTrue(response.data["permissions"]["can_confirm"])
        self.assertTrue(response.data["permissions"]["can_dismiss"])
        # Still an officer: the team view and settings stay supervisor-only.
        self.assertFalse(response.data["permissions"]["can_view_team"])
        self.assertFalse(response.data["permissions"]["can_edit_settings"])

    def test_an_officer_can_update_their_own_email(self):
        response = self._auth(self.officer).patch(
            "/api/auth/me/", {"email": "officer@example.com"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.officer.refresh_from_db()
        self.assertEqual(self.officer.email, "officer@example.com")


class AppSettingsTests(TestCase):
    """Policy values live in the database, then .env, then a built-in default."""

    def setUp(self):
        self.supervisors, _ = Group.objects.get_or_create(name="Supervisors")
        self.officer = User.objects.create_user("officer2", password="pw-officer-123")
        self.supervisor = User.objects.create_user("boss2", password="pw-boss-123")
        self.supervisor.groups.add(self.supervisors)
        self.client = APIClient()

    def test_defaults_apply_when_nothing_is_set(self):
        self.assertEqual(risk_threshold(), 70.0)

    def test_a_database_override_wins(self):
        set_setting("risk_threshold", "55")

        self.assertEqual(risk_threshold(), 55.0)

    def test_clearing_an_override_falls_back(self):
        set_setting("risk_threshold", "55")
        set_setting("risk_threshold", "")

        self.assertEqual(risk_threshold(), 70.0)

    def test_supervisor_emails_come_from_settings_and_the_group(self):
        set_setting("report_supervisor_emails", "one@example.com, two@example.com")
        self.supervisor.email = "boss2@example.com"
        self.supervisor.save(update_fields=["email"])

        emails = supervisor_emails()

        self.assertIn("one@example.com", emails)
        self.assertIn("two@example.com", emails)
        self.assertIn("boss2@example.com", emails)

    def test_an_officer_may_read_but_not_change_settings(self):
        self.client.force_authenticate(user=self.officer)

        read = self.client.get("/api/settings/")
        write = self.client.patch("/api/settings/update/", {"risk_threshold": "50"}, format="json")

        self.assertEqual(read.status_code, 200)
        self.assertFalse(read.data["editable"])
        self.assertEqual(write.status_code, 403)
        self.assertEqual(risk_threshold(), 70.0)

    def test_a_supervisor_can_change_settings(self):
        self.client.force_authenticate(user=self.supervisor)

        response = self.client.patch(
            "/api/settings/update/", {"risk_threshold": "62"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(risk_threshold(), 62.0)

    def test_an_out_of_range_value_is_refused(self):
        self.client.force_authenticate(user=self.supervisor)

        response = self.client.patch(
            "/api/settings/update/", {"risk_threshold": "500"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(risk_threshold(), 70.0)

    def test_an_unknown_setting_is_refused(self):
        self.client.force_authenticate(user=self.supervisor)

        response = self.client.patch(
            "/api/settings/update/", {"not_a_setting": "x"}, format="json"
        )

        self.assertEqual(response.status_code, 400)


class DatasetLabTests(TestCase):
    """The generator produces what it claims, and the console can eat it."""

    @classmethod
    def setUpTestData(cls):
        cls.spec = dataset_lab.LabSpec(
            seed=3, companies=140, rings=2, mills=2,
            grey_rings=2, grey_mills=2, honest_loops=4,
        )
        cls.data = dataset_lab.build_lab_dataset(cls.spec)

    def test_the_same_seed_produces_the_same_dataset(self):
        again = dataset_lab.build_lab_dataset(self.spec)

        self.assertEqual(self.data.companies_csv(), again.companies_csv())
        self.assertEqual(self.data.invoices_csv(), again.invoices_csv())

    def test_a_different_seed_produces_a_different_dataset(self):
        other = dataset_lab.build_lab_dataset(
            dataset_lab.LabSpec(**{**self.spec.as_dict(), "seed": 4})
        )

        self.assertNotEqual(self.data.companies_csv(), other.companies_csv())

    def test_every_band_is_represented(self):
        counts = self.data.band_counts()

        for band in dataset_lab.BAND_ORDER:
            self.assertGreater(counts[band], 0, f"nothing planted in the {band} band")

    def test_gstins_are_unique(self):
        gstins = [c["gstin"] for c in self.data.companies]

        self.assertEqual(len(gstins), len(set(gstins)))

    def test_every_invoice_references_a_generated_company(self):
        known = {c["gstin"] for c in self.data.companies}

        for invoice in self.data.invoices:
            self.assertIn(invoice["seller_gstin"], known)
            self.assertIn(invoice["buyer_gstin"], known)

    def test_no_invoice_predates_either_party(self):
        registered = {c["gstin"]: c["registered_date"] for c in self.data.companies}

        for invoice in self.data.invoices:
            self.assertGreaterEqual(invoice["date"], registered[invoice["seller_gstin"]])
            self.assertGreaterEqual(invoice["date"], registered[invoice["buyer_gstin"]])

    def test_eway_flags_survive_the_round_trip_to_dataframes(self):
        """
        A regression guard with a real bug behind it.

        The CSV rows carry has_eway_bill as the string "true"/"false". An
        `astype(bool)` on those reads BOTH as True, because every non-empty
        string is truthy - which silently zeroed the e-way signal in preview
        scoring and knocked twenty points off every mill.
        """
        _, invoices = self.data.dataframes()

        self.assertEqual(invoices["has_eway_bill"].dtype, bool)
        self.assertTrue((~invoices["has_eway_bill"]).any(), "no missing e-way bills at all")

    def test_planted_high_risk_fraud_is_actually_detected(self):
        result = dataset_lab.analyse(self.data)
        card = result["scorecard"]

        self.assertGreater(card["high_planted"], 0)
        self.assertEqual(card["high_found"], card["high_planted"])

    def test_honest_loops_are_not_pushed_over_the_threshold(self):
        """The low band exists to catch us doing this, so it has to hold."""
        result = dataset_lab.analyse(self.data)

        self.assertEqual(result["scorecard"]["false_alarms"], 0)

    def test_generated_data_imports_through_the_real_upload_path(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from core.csv_import import load_dataset

        result = load_dataset(
            SimpleUploadedFile("companies.csv", self.data.companies_csv().encode()),
            SimpleUploadedFile("invoices.csv", self.data.invoices_csv().encode()),
            name="Lab test",
        )

        self.assertEqual(result.companies_created, len(self.data.companies))
        self.assertEqual(result.invoices_created, len(self.data.invoices))

    def test_an_oversized_request_is_clamped_not_refused(self):
        spec = dataset_lab.LabSpec.from_dict(
            {"companies": 999_999, "rings": 500, "seed": -4}
        )

        self.assertEqual(spec.companies, dataset_lab.MAX_COMPANIES)
        self.assertEqual(spec.rings, dataset_lab.MAX_GROUPS)
        self.assertEqual(spec.seed, 0)


class DatasetLabApiTests(TestCase):
    """The lab is open; loading its output into the console is not."""

    def setUp(self):
        self.client = APIClient()
        self.spec = {
            "seed": 5, "companies": 80, "rings": 1, "mills": 1,
            "grey_rings": 1, "grey_mills": 1, "honest_loops": 2,
        }

    def test_presets_need_no_account(self):
        response = self.client.get("/api/lab/presets/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["presets"])

    def test_preview_reports_both_what_was_planted_and_what_was_found(self):
        response = self.client.post(
            "/api/lab/preview/", {"spec": self.spec}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("bands", response.data["summary"])
        self.assertIn("scorecard", response.data["analysis"])

    def test_preview_writes_nothing_to_the_database(self):
        self.client.post("/api/lab/preview/", {"spec": self.spec}, format="json")

        self.assertEqual(Company.objects.count(), 0)
        self.assertEqual(Dataset.objects.count(), 0)

    def test_download_returns_a_zip_of_four_files(self):
        import io
        import zipfile

        response = self.client.post(
            "/api/lab/download/", {"spec": self.spec}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))
                                  if response.streaming else io.BytesIO(response.content))
        self.assertEqual(
            sorted(archive.namelist()),
            ["README.txt", "answer_key.csv", "companies.csv", "invoices.csv"],
        )

    def test_loading_into_the_console_requires_an_account(self):
        response = self.client.post("/api/lab/load/", {"spec": self.spec}, format="json")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(Dataset.objects.count(), 0)

    def test_an_officer_can_load_a_generated_dataset(self):
        officer = User.objects.create_user("labuser", password="pw-lab-123")
        self.client.force_authenticate(user=officer)

        response = self.client.post(
            "/api/lab/load/", {"spec": self.spec, "name": "Bench data"}, format="json"
        )

        self.assertEqual(response.status_code, 201)
        dataset = Dataset.objects.get(pk=response.data["dataset_id"])
        self.assertEqual(dataset.name, "Bench data")
        self.assertTrue(dataset.is_active)
        self.assertEqual(dataset.uploaded_by, officer)
        self.assertIn("No real taxpayer data", dataset.note)


class ManagementCommandTests(TestCase):
    """The two commands a team actually runs before a demo."""

    def _run(self, command, **kwargs):
        out = StringIO()
        call_command(command, stdout=out, stderr=out, **kwargs)
        return out.getvalue()

    # ---- setup_accounts --------------------------------------------------

    def test_it_creates_accounts_with_the_right_roles(self):
        self._run(
            "setup_accounts",
            supervisor=["boss:Vikram Mehta:boss@example.gov.in"],
            officer=["anita:Anita Rao", "raj:Raj Kumar"],
        )

        boss = User.objects.get(username="boss")
        self.assertTrue(is_supervisor(boss))
        self.assertEqual(boss.email, "boss@example.gov.in")
        self.assertEqual(boss.first_name, "Vikram")
        self.assertFalse(is_supervisor(User.objects.get(username="anita")))
        self.assertFalse(is_supervisor(User.objects.get(username="raj")))

    def test_running_it_twice_does_not_duplicate_accounts(self):
        for _ in range(2):
            self._run("setup_accounts", officer=["anita:Anita Rao"])

        self.assertEqual(User.objects.filter(username="anita").count(), 1)

    def test_it_does_not_change_an_existing_password_by_default(self):
        self._run("setup_accounts", officer=["anita"], password="first-pass-123")
        self._run("setup_accounts", officer=["anita"], password="second-pass-123")

        anita = User.objects.get(username="anita")
        self.assertTrue(anita.check_password("first-pass-123"))

    def test_reset_password_does_change_it(self):
        self._run("setup_accounts", officer=["anita"], password="first-pass-123")
        self._run(
            "setup_accounts",
            officer=["anita"],
            password="second-pass-123",
            reset_password=True,
        )

        self.assertTrue(User.objects.get(username="anita").check_password("second-pass-123"))

    def test_a_role_change_moves_the_account_between_groups(self):
        self._run("setup_accounts", officer=["anita"])
        self._run("setup_accounts", supervisor=["anita"])

        anita = User.objects.get(username="anita")
        self.assertTrue(is_supervisor(anita))
        self.assertFalse(anita.groups.filter(name="Officers").exists())

    def test_a_superuser_is_never_demoted_to_officer(self):
        """
        A superuser is always a supervisor (core.roles), so putting one in the
        officer group would make the UI and the API disagree about the account.
        """
        User.objects.create_superuser("root", password="pw-root-12345")

        self._run("setup_accounts", officer=["root"])

        root = User.objects.get(username="root")
        self.assertTrue(is_supervisor(root))
        self.assertTrue(root.groups.filter(name="Supervisors").exists())

    def test_it_refuses_to_delete_a_superuser(self):
        User.objects.create_superuser("root", password="pw-root-12345")

        with self.assertRaises(CommandError):
            self._run("setup_accounts", remove=["root"])

        self.assertTrue(User.objects.filter(username="root").exists())

    def test_generated_passwords_avoid_ambiguous_characters(self):
        """These get read off a screen and typed by someone else."""
        for _ in range(50):
            self.assertFalse(set(make_password()) & set("O0lI1"))

    # ---- reset_data ------------------------------------------------------

    def test_reset_data_refuses_without_confirmation(self):
        dataset = Dataset.objects.create(name="Something")
        Company.objects.create(
            dataset=dataset, gstin="27AAAAA0000A1Z5", pan="AAAAA0000A",
            name="Kept Ltd", director_name="A", registered_address="X",
            registered_date=date(2020, 1, 1), declared_turnover=100000,
        )

        with self.assertRaises(CommandError):
            self._run("reset_data")

        self.assertEqual(Company.objects.count(), 1)

    def test_reset_data_clears_case_data_but_keeps_accounts(self):
        User.objects.create_user("anita", password="pw-anita-12345")
        dataset = Dataset.objects.create(name="Something")
        Company.objects.create(
            dataset=dataset, gstin="27AAAAA0000A1Z5", pan="AAAAA0000A",
            name="Gone Ltd", director_name="A", registered_address="X",
            registered_date=date(2020, 1, 1), declared_turnover=100000,
        )
        DetectionRun.objects.create(dataset=dataset, name="Run 1")

        self._run("reset_data", yes=True)

        self.assertEqual(Dataset.objects.count(), 0)
        self.assertEqual(Company.objects.count(), 0)
        self.assertEqual(DetectionRun.objects.count(), 0)
        self.assertTrue(User.objects.filter(username="anita").exists())

    def test_dry_run_deletes_nothing(self):
        Dataset.objects.create(name="Something")

        self._run("reset_data", dry_run=True)

        self.assertEqual(Dataset.objects.count(), 1)
