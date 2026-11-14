"""Deterministic verifier (PLAN 9.3). Applied identically to every system's output.

It validates references and re-computes registered rule predicates from the
evidence. It never adds findings, never reads the answer key, and never turns an
interpretation into a fact:

  invalid_reference          a cited id does not exist in the bundle
  structurally_valid         ids resolve (used for notes that make no allegation)
  supported_observation      a registered predicate confirms the modeled observation
  unresolved_interpretation  ids are fine but no predicate supports the allegation

`verified` therefore means "a deterministic predicate supports this modeled
observation". It does not mean a person is proven responsible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from alibi import checks, checks_families
from alibi.contracts import EvidenceManifest, Finding, InvestigationReport
from alibi.evidence.store import EvidenceStore

VERIFIER_VERSION = "1.1.0"  # 1.1.0: predicates for the phase-two claim types; absent sources give "cannot be run"
MAX_ALLEGATION_WINDOW_S = 1800
WINDOW_TOLERANCE_S = 120


@dataclass
class Observations:
    """Everything the registered predicates need, computed once from the evidence."""

    reconcile: dict[str, Any]
    transfers: dict[str, Any]
    removal: list[dict[str, Any]] = field(default_factory=list)
    retention_ids: set[str] = field(default_factory=set)
    gap_ids: dict[str, dict[str, Any]] = field(default_factory=dict)
    families: dict[str, Any] = field(default_factory=dict)  # phase-two observations; empty for first-run bundles


def compute_observations(store: EvidenceStore, manifest: EvidenceManifest) -> Observations:
    rec = checks.reconcile_logs(store, manifest)
    xfer = checks.correlate_transfers(store, manifest)
    obs = Observations(reconcile=rec, transfers=xfer)
    for f in rec["files"]:
        for row in f["unexplained_local_absence"]:
            obs.removal.append({"host": f["host"], "file": f["file"], **row})
        obs.retention_ids.update(f["retention_explained_absence"]["all_collector_event_ids"])
    for g in rec["heartbeat_gaps"]:
        obs.gap_ids[g["before_event_id"]] = g
        obs.gap_ids[g["after_event_id"]] = g
    obs.families = checks_families.observations(store, manifest)
    return obs


def _overlaps(f: Finding, start: datetime, end: datetime) -> bool:
    tol = timedelta(seconds=WINDOW_TOLERANCE_S)
    return f.t_start - tol <= end and start <= f.t_end + tol


def _staged_ids(so: dict[str, Any]) -> set[str]:
    return {so["fs_stat_event_id"], *so["export_event_ids"], *so["retrieval_flow_event_ids"],
            *so["staging_command_event_ids"]}


def _predicate(f: Finding, cited: set[str], obs: Observations) -> tuple[str, str]:
    """Return (verdict, note) with verdict in supported | rejected | unresolved."""
    if f.claim_type in checks_families.INCIDENT_CLAIMS:  # phase-two claim types have their own predicates
        return checks_families.predicate(f, cited, obs.families)
    if f.claim_type == "local_log_removal":
        hits = [o for o in obs.removal if o["host"] == f.host and o["collector_event_id"] in cited]
        if hits:
            ts = [datetime.fromisoformat(o["line_ts"]) for o in hits]
            if _overlaps(f, min(ts), max(ts)):
                return "supported", (f"{len(hits)} cited collector record(s) are absent from the local log after the "
                                     "host's retention boundary, bracketed by later local records")
            return "unresolved", "the cited collector records fall outside the stated time window"
        if cited & obs.retention_ids:
            return "rejected", ("the cited collector records predate the host's retention boundary (log rotation); "
                                "their absence from the local log is expected")
        blind = [x for x in obs.reconcile["files"] if x["host"] == f.host and x["status"] == "not_assessable"]
        if blind:
            return "unresolved", ("the comparison this claim rests on cannot be run on this bundle: "
                                  + blind[0]["status_reason"])
        return "unresolved", "no cited record is a collector-retained line that is unexplainedly absent locally"

    if obs.transfers.get("status") == "not_assessable" and f.claim_type in ("policy_violating_transfer", "data_staging"):
        return "unresolved", ("no network flow source is in this bundle, so the transfer this claim rests on "
                              "cannot be observed")
    rows = [t for t in obs.transfers["transfers"] if t["src_host"] == f.host]
    if f.claim_type == "policy_violating_transfer":
        hits = [t for t in rows if t["flow_event_id"] in cited or cited & set(t["command_event_ids"])]
        if not hits:
            return "unresolved", ("no cited record is a bulk transfer observed at the tap from this host, "
                                  "or the command that launched one")
        bad = [t for t in hits if t["policy_status"] == "not_approved"]
        if not bad:
            return "rejected", f"the cited transfer is consistent with policy: {hits[0]['policy_note']}"
        t = bad[0]
        if not _overlaps(f, datetime.fromisoformat(t["start"]), datetime.fromisoformat(t["end"])):
            return "unresolved", "the cited transfer falls outside the stated time window"
        basis = "flow record" if t["flow_event_id"] in cited else "launching command (flow record corroborates it)"
        return "supported", f"bulk transfer to a destination not on the approved list, cited via the {basis}"

    if f.claim_type == "data_staging":
        staged = [(t, t["staged_object"]) for t in rows if t["staged_object"]]
        hits = [(t, so) for t, so in staged if _staged_ids(so) & cited]
        if not hits:
            # phase two: an object whose modification time was changed is identified by independent arrival records
            alt = checks_families.staging_predicate(f, cited, obs.families)
            if alt is not None:
                return alt
            return "unresolved", "no cited record belongs to an object staged on this host ahead of a bulk transfer"
        bad = [(t, so) for t, so in hits if t["policy_status"] == "not_approved"]
        if not bad:
            return "rejected", "the staged object was sent to an approved destination; that is not an incident"
        t, so = bad[0]
        if not _overlaps(f, datetime.fromisoformat(so["start"]), datetime.fromisoformat(t["start"])):
            return "unresolved", "the cited staging records fall outside the stated time window"
        return "supported", "an object of matching size was written on this host shortly before a non-approved bulk transfer"

    return "unresolved", f"no registered predicate for incident claim type {f.claim_type!r}"


def _note_predicate(f: Finding, cited: set[str], obs: Observations) -> bool:
    """Predicates for non-allegation notes (benign explanations, unresolved anomalies)."""
    if f.claim_type in checks_families.NOTE_CLAIMS:
        return checks_families.note_predicate(f, cited, obs.families)
    if f.claim_type == "retention_explained_absence":
        return bool(cited & obs.retention_ids)
    if f.claim_type == "policy_consistent_transfer":
        return any(t["flow_event_id"] in cited and t["policy_status"] in ("approved", "internal")
                   for t in obs.transfers["transfers"])
    if f.claim_type == "collection_gap":
        return bool(cited & set(obs.gap_ids))
    return False


def verify_finding(f: Finding, store: EvidenceStore, obs: Observations) -> Finding:
    out = f.model_copy(deep=True)
    notes: list[str] = []
    cited = list(dict.fromkeys(out.evidence_ids))
    refs = cited + list(dict.fromkeys(out.counterevidence_ids))
    existing = store.existing_ids(refs)
    missing = [i for i in refs if i not in existing]
    downgraded = out.status == "downgraded_by_skeptic"

    if missing:
        out.verification_status = "invalid_reference"
        out.status = "rejected_by_verifier"
        notes.append(f"{len(missing)} cited id(s) do not exist in this evidence bundle: {missing[:5]}")
    elif out.t_end < out.t_start:
        out.verification_status = "unresolved_interpretation"
        out.status = "rejected_by_verifier"
        notes.append("the time window ends before it starts")
    elif out.category != "incident_allegation":
        if cited and _note_predicate(out, set(cited), obs):
            out.verification_status = "supported_observation"
            out.status = "verified" if not downgraded else out.status
            notes.append("a deterministic check supports this observation; it is not an incident allegation")
        else:
            out.verification_status = "structurally_valid" if cited else "not_checked"
            notes.append("references resolve; no allegation is made" if cited else "no evidence cited")
    elif not cited:
        out.verification_status = "unresolved_interpretation"
        out.status = "rejected_by_verifier"
        notes.append("an incident allegation must cite evidence; none was cited")
    elif (out.t_end - out.t_start).total_seconds() > MAX_ALLEGATION_WINDOW_S:
        out.verification_status = "unresolved_interpretation"
        notes.append(f"the time window is wider than {MAX_ALLEGATION_WINDOW_S // 60} minutes; too broad to verify")
    else:
        verdict, note = _predicate(out, set(cited), obs)
        notes.append(note)
        if verdict == "supported":
            out.verification_status = "supported_observation"
            if not downgraded:
                out.status = "verified"
        elif verdict == "rejected":
            out.verification_status = "unresolved_interpretation"
            out.status = "rejected_by_verifier"
        else:
            out.verification_status = "unresolved_interpretation"
    if out.actor_claimed:
        notes.append("names a person: account activity does not establish who operated the account")
    out.verifier_notes = notes
    return out


def verify_report(report: InvestigationReport, store: EvidenceStore, manifest: EvidenceManifest,
                  obs: Observations | None = None) -> InvestigationReport:
    """Return a copy of the report with every finding's verification status set."""
    obs = obs or compute_observations(store, manifest)
    out = report.model_copy(deep=True)
    out.findings = [verify_finding(f, store, obs) for f in report.findings]
    out.verifier_version = VERIFIER_VERSION
    if "lab" in manifest.operational_context:
        # worker lab: a claimed link from the account to a worker stays only if the scheduler's records support it
        from alibi.lab.assignments import verify_worker_link

        out = verify_worker_link(out, store, manifest)
    return out


def is_accepted(f: Finding) -> bool:
    """A final accepted incident allegation."""
    return f.category == "incident_allegation" and f.status == "verified"
