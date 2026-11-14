"""Report construction, locking and hashing helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from alibi.contracts import InvestigationReport, ReviewEvent


def report_digest(report: InvestigationReport) -> str:
    """Hash of the substantive content (findings, attribution, summary), not lock metadata."""
    attribution = report.attribution.model_dump(mode="json", exclude={"review_status", "approved_by_human", "approved_at"})
    # Fields added after reports were first locked count toward the digest only when they carry something, so a
    # report locked before they existed still verifies, and a report that does carry them is covered.
    for added_later in ("worker_id", "worker_link_evidence_ids"):
        if not attribution.get(added_later):
            attribution.pop(added_later, None)
    body = {
        "bundle_id": report.bundle_id,
        "system_id": report.system_id,
        "inference_mode": report.inference_mode,
        "findings": [f.model_dump(mode="json") for f in report.findings],
        "attribution": attribution,
        "summary": report.summary,
        "open_questions": report.open_questions,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def lock_report(report: InvestigationReport, decision: str, *, by_human: bool, note: str = "",
                now: datetime | None = None) -> InvestigationReport:
    """Freeze a report. Idempotent: locking an already locked report returns it unchanged.

    decision: accepted | rejected | skipped_for_benchmark. Batch mode never fabricates a
    human approval: by_human=False always yields approved_by_human=False.
    """
    if report.locked:
        return report
    if decision not in ("accepted", "rejected", "skipped_for_benchmark"):
        raise ValueError(f"unknown review decision {decision!r}")
    if decision == "skipped_for_benchmark" and by_human:
        raise ValueError("skipped_for_benchmark is a batch decision, not a human one")
    now = now or datetime.now(timezone.utc)
    out = report.model_copy(deep=True)
    out.review_history.append(ReviewEvent(at=now, decision=decision, by_human=by_human, note=note))
    out.attribution.review_status = decision
    out.attribution.approved_by_human = bool(by_human and decision == "accepted")
    out.attribution.approved_at = now if out.attribution.approved_by_human else None
    out.report_sha256 = report_digest(out)
    out.locked = True
    out.locked_at = now
    return out
