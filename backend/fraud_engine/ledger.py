"""
A tamper-evident audit ledger for confirmed fraud rings.

WHAT THIS IS
------------
A hash chain. When an officer confirms a ring as fraudulent, the evidence
behind that decision - the companies, the invoices, the risk score, the
explanation, the timestamp - is written into a block. Each block stores the
SHA-256 hash of the block before it, and its own hash is computed over its
whole content *including* that link.

The consequence is the entire point: change one character of a historical
payload and that block's hash no longer matches, and because the next block
committed to the old hash, every block after it breaks too. You cannot quietly
rewrite a past finding. `verify_chain()` walks the chain and reports exactly
which block was disturbed.

Why that matters here: a confirmed ring becomes the basis for recovery
proceedings against real businesses. Months later, in front of a tribunal, the
department needs to show that the evidence on file is the evidence that was
there on the day the officer signed off - not something edited since. A plain
database row cannot demonstrate that; an UPDATE leaves no trace. This can.

WHAT THIS IS NOT
----------------
This is NOT a cryptocurrency and NOT a public blockchain. There is no token, no
wallet, no mining, no gas fee, no network, no consensus protocol, no third
party. It is a few dozen lines of Python and a database table, and it runs
entirely offline inside this deployment.

The honest limit of that design: because the chain lives in the same database
as everything else, someone with write access could in principle recompute
every subsequent hash after altering a block and present a chain that verifies.
What this defends against is silent, casual, or accidental alteration - which
is the overwhelming majority of real evidence-integrity failures. Defending
against a determined administrator needs an anchor outside the system: publish
the head hash somewhere the department does not control (a second institution,
a public chain, a signed daily log). That is a deliberate future step, noted in
docs/UNDERSTAND_ME.md, and the design here is ready for it - the head hash is
the only thing that would need publishing.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

# The first block has no predecessor, so it points at 64 zeroes by convention.
GENESIS_PREVIOUS_HASH = "0" * 64


@dataclass(frozen=True)
class Block:
    """An immutable in-memory view of one link in the chain."""

    index: int
    timestamp: str
    payload: dict
    previous_hash: str
    hash: str

    def recompute_hash(self) -> str:
        return compute_hash(self.index, self.timestamp, self.payload, self.previous_hash)

    def is_intact(self) -> bool:
        return self.hash == self.recompute_hash()


def canonical_payload(payload: dict) -> str:
    """
    Serialise a payload to exactly one deterministic string.

    Sorted keys and no incidental whitespace, so the same evidence always
    hashes to the same digest regardless of dictionary ordering. Without this,
    a payload could be re-serialised differently and appear tampered with when
    nothing had actually changed.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(index: int, timestamp: str, payload: dict, previous_hash: str) -> str:
    """SHA-256 over the block's full content, including its link to the past."""
    material = f"{index}|{timestamp}|{canonical_payload(payload)}|{previous_hash}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _row_to_block(row) -> Block:
    return Block(
        index=row.index,
        timestamp=row.timestamp.isoformat(),
        payload=row.payload,
        previous_hash=row.previous_hash,
        hash=row.hash,
    )


def get_head():
    """The most recent block, or None if the chain is empty."""
    from fraud_engine.models import LedgerBlock

    return LedgerBlock.objects.order_by("-index").first()


def append_block(payload: dict):
    """
    Append one block carrying `payload` and return the saved LedgerBlock row.

    Append-only: nothing here ever updates or deletes an existing block.
    """
    from fraud_engine.models import LedgerBlock

    head = get_head()
    index = 0 if head is None else head.index + 1
    previous_hash = GENESIS_PREVIOUS_HASH if head is None else head.hash

    timestamp = datetime.now(timezone.utc)
    block_hash = compute_hash(index, timestamp.isoformat(), payload, previous_hash)

    return LedgerBlock.objects.create(
        index=index,
        timestamp=timestamp,
        payload=payload,
        previous_hash=previous_hash,
        hash=block_hash,
    )


def verify_chain() -> dict:
    """
    Walk the whole chain and confirm nothing has been altered.

    Three things are checked at every block:
      1. its stored hash still matches a fresh hash of its own content
         (catches an edited payload or timestamp),
      2. its previous_hash matches the actual hash of the block before it
         (catches a block being removed, reordered or spliced in),
      3. indices are contiguous from zero (catches a deletion at the end).

    Returns a report rather than raising, because the API surfaces this to an
    officer as a status rather than as a crash.
    """
    from fraud_engine.models import LedgerBlock

    rows = list(LedgerBlock.objects.order_by("index"))

    if not rows:
        return {
            "valid": True,
            "block_count": 0,
            "head_hash": None,
            "message": "Ledger is empty. Nothing has been confirmed yet.",
        }

    expected_previous = GENESIS_PREVIOUS_HASH
    for position, row in enumerate(rows):
        block = _row_to_block(row)

        if block.index != position:
            return _broken(
                rows, block,
                f"Block index {block.index} found at position {position}: "
                "a block has been deleted or reordered.",
            )

        if block.previous_hash != expected_previous:
            return _broken(
                rows, block,
                f"Block #{block.index} points at previous hash "
                f"{block.previous_hash[:12]}... but the block before it hashes to "
                f"{expected_previous[:12]}...: the chain has been broken.",
            )

        if not block.is_intact():
            return _broken(
                rows, block,
                f"Block #{block.index} content no longer matches its recorded hash: "
                "its payload or timestamp has been altered since it was written.",
            )

        expected_previous = block.hash

    return {
        "valid": True,
        "block_count": len(rows),
        "head_hash": rows[-1].hash,
        "message": f"Chain intact. All {len(rows)} block(s) verified against SHA-256.",
    }


def _broken(rows, block: Block, message: str) -> dict:
    return {
        "valid": False,
        "block_count": len(rows),
        "head_hash": rows[-1].hash,
        "broken_at_index": block.index,
        "message": message,
    }


def build_ring_payload(ring, companies, invoices, officer: str = "demo-officer") -> dict:
    """
    Assemble the evidence bundle recorded when a ring is confirmed.

    Everything needed to reconstruct the decision later is captured inline
    rather than referenced by id, so the block stays meaningful even if the
    underlying rows are later changed.

    The `model` section is what makes this auditable years later. It records
    which model version and which policy threshold produced the score the
    officer was looking at when they signed off. Without it you can prove the
    evidence is unaltered but not what actually generated the flag - and a
    silently promoted model would leave no trace at all.
    """
    run = getattr(ring, "run", None)
    return {
        "record_type": "confirmed_fraud_ring",
        "ring_id": ring.id,
        "pattern_kind": getattr(ring, "kind", "ring"),
        "closure": getattr(ring, "closure", "invoice"),
        "confirmed_by": officer,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "detected_at": ring.detected_at.isoformat() if ring.detected_at else None,
        "risk_score": round(ring.risk_score, 2),
        "ring_size": len(ring.company_ids or []),
        "company_ids": list(ring.company_ids or []),
        "companies": [
            {
                "id": c.id,
                "gstin": c.gstin,
                "name": c.name,
                "pan": c.pan,
                "director_name": c.director_name,
                "registered_address": c.registered_address,
                "declared_turnover": str(c.declared_turnover),
            }
            for c in companies
        ],
        "invoice_ids": list(ring.invoice_ids or []),
        "invoice_count": len(invoices),
        "total_cycle_value": str(ring.total_cycle_value),
        "explanation": ring.explanation or [],
        "shape_evidence": getattr(ring, "evidence", {}) or {},
        "model": {
            "version": getattr(run, "model_version", "") if run else "",
            "trained_at": getattr(run, "model_trained_at", "") if run else "",
            "risk_threshold": getattr(run, "risk_threshold", None) if run else None,
            "detection_run": getattr(run, "name", "") if run else "",
            "detection_run_id": getattr(run, "id", None) if run else None,
            "dataset": getattr(getattr(run, "dataset", None), "name", "") if run else "",
        },
    }


def build_dismissal_payload(ring, reason_label: str, officer: str, note: str = "") -> dict:
    """
    Recorded when an officer clears an alert as *not* fraud.

    A dismissal is a decision about a real taxpayer just as much as a
    confirmation is, and it is the record that shows an allegation was
    examined and dropped. Putting it in the same chain means the audit trail
    covers what the department decided not to pursue, not only what it did.
    """
    run = getattr(ring, "run", None)
    return {
        "record_type": "dismissed_alert",
        "ring_id": ring.id,
        "pattern_kind": getattr(ring, "kind", "ring"),
        "dismissed_by": officer,
        "dismissed_at": datetime.now(timezone.utc).isoformat(),
        "reason_code": ring.dismissal_reason,
        "reason": reason_label,
        "note": note,
        "risk_score": round(ring.risk_score, 2),
        "company_ids": list(ring.company_ids or []),
        "model": {
            "version": getattr(run, "model_version", "") if run else "",
            "risk_threshold": getattr(run, "risk_threshold", None) if run else None,
            "detection_run_id": getattr(run, "id", None) if run else None,
        },
    }


def build_report_payload(report, officer: str) -> dict:
    """
    Recorded when a report is issued - a run's case report or a single
    company's report; `report.report_type` says which.

    Only the hash of the report goes in, not its body: the block's job is to
    let anyone prove later that a given document is the one that was issued,
    and duplicating confidential contents into a second table would widen the
    exposure for no additional guarantee.

    A run report and a company report carry different provenance (a run has a
    model version and a dataset; a company has neither of its own - it borrows
    them from whichever run last scored it), so model info is read from
    `summary`, which both `reporting.build_summary` and
    `reporting.build_company_summary` populate with the same two keys, rather
    than reached for on `report.run` directly - that attribute is None for a
    company report and would raise.
    """
    summary = report.summary or {}
    payload = {
        "record_type": "case_report_issued",
        "report_id": report.id,
        "report_type": getattr(report, "report_type", "run"),
        "title": report.title,
        "issued_by": officer,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "recipients": list(report.recipients or []),
        "content_sha256": report.content_hash,
        "confirmed_count": summary.get("confirmed_count"),
        "confirmed_value": summary.get("confirmed_value"),
        "dismissed_count": summary.get("dismissed_count"),
        "model": {
            "version": summary.get("model_version"),
            "risk_threshold": summary.get("risk_threshold"),
        },
    }
    if report.run_id:
        payload["model"]["detection_run"] = report.run.name
        payload["model"]["detection_run_id"] = report.run.id
        payload["model"]["dataset"] = report.run.dataset.name
    if getattr(report, "company_id", None):
        payload["company"] = {
            "id": report.company_id,
            "name": report.company.name,
            "gstin": report.company.gstin,
        }
    return payload
