"""Predefined evidence explanations for the Ask box (P0 Q&A, PLAN 9.1).

These are deterministic answers computed from the checks, with citations. They are
not model output and are labeled as such. They never read the answer key.
"""

from __future__ import annotations

from typing import Any

from alibi import checks
from alibi.contracts import EvidenceManifest, InvestigationReport
from alibi.evidence.store import EvidenceStore

LABEL = "Predefined evidence explanation · no model inference"


def explanations(store: EvidenceStore, manifest: EvidenceManifest, report: InvestigationReport | None) -> list[dict[str, Any]]:
    rec = checks.reconcile_logs(store, manifest)
    xfer = checks.correlate_transfers(store, manifest)
    out: list[dict[str, Any]] = []
    missing = [(f, r) for f in rec["files"] for r in f["unexplained_local_absence"]]
    bad = [t for t in xfer["transfers"] if t["policy_status"] == "not_approved"]
    linked = next((t for t in bad if t["session_link"] == "single_overlapping_session"), None)

    q1 = {"key": "missing-line", "question": "What links the missing line to this session?", "label": LABEL}
    if missing:
        f, r = missing[0]
        ids = [r["collector_event_id"], r["bracket_before_id"], r["bracket_after_id"]]
        # the check only reports a line as unexplained when BOTH brackets exist; say so only then
        both = bool(r["bracket_before_id"] and r["bracket_after_id"])
        text = (f"The collector holds a record that the host's own {f['file']} no longer has: \"{r['line']}\". "
                + ("It is bracketed by local records before and after, and it" if both else "It")
                + f" postdates the host's retention boundary ({f['local_coverage_start']}), so rotation does not explain it.")
        if r["session_id"] and linked and linked["sessions"][0]["session_id"] == r["session_id"]:
            text += (f" That record opens session {r['session_id']}. The same session is the only one open on "
                     f"{linked['src_host']} when {linked['bytes_out']:,} bytes leave for {linked['dst']}:{linked['dport']}, "
                     f"a destination that is not on the approved list.")
            ids += [linked["flow_event_id"], *linked["command_event_ids"]]
        elif r["session_id"]:
            text += f" The record belongs to session {r['session_id']}; no non-approved transfer overlaps it."
        out.append({**q1, "available": True, "answer": text, "evidence_ids": [i for i in ids if i]})
    else:
        blind = [f for f in rec["files"] if f["status"] == "not_assessable"]
        open_rows = [(f, r) for f in rec["files"] for r in f["inconclusive_local_absence"]]
        if blind:
            answer = (f"Unknown. {len(blind)} forwarded log(s) could not be compared in this evidence: "
                      f"{blind[0]['status_reason']} Nothing here shows a missing line, and nothing rules one out.")
            ids: list[str] = []
        elif open_rows:
            f, r = open_rows[0]
            answer = (f"Inconclusive. The collector holds \"{r['line']}\" and the host's own {f['file']} does not, but "
                      f"{r['reason']}. That is not enough to say the line was removed.")
            ids = [i for i in (r["collector_event_id"], r["bracket_before_id"], r["bracket_after_id"]) if i]
        else:
            answer, ids = "No line is unexplainedly missing from a host log in this evidence.", []
        out.append({**q1, "available": bool(open_rows) and not blind, "evidence_ids": ids, "answer": answer})

    q2 = {"key": "identify-person", "question": "Can you identify the person?", "label": LABEL}
    if linked:
        pres = checks.assess_presence(store, manifest, linked["sessions"][0]["session_id"])
        out.append({**q2, "available": True,
                    "answer": ("No. " + pres.get("statement", "") + " Limits: " + "; ".join(pres["limits"]) + "."),
                    "evidence_ids": linked["sessions"][0]["login_event_ids"] + pres.get("badge_event_ids", [])})
    else:
        out.append({**q2, "available": bool(report and report.findings), "evidence_ids": [],
                    "answer": ("No incident is tied to a single session in this evidence, so there is no account "
                               "activity to attribute. Account activity would in any case identify a credential, "
                               "not a person.")})

    q3 = {"key": "other-gap", "question": "Why is the other gap not suspicious?", "label": LABEL}
    ret = [f for f in rec["files"] if f["retention_explained_absence"]["count"]]
    if ret:
        f = ret[0]
        r = f["retention_explained_absence"]
        out.append({**q3, "available": True, "evidence_ids": r["sample_collector_event_ids"][:3] + f["coverage_boundary_event_ids"],
                    "answer": (f"{r['count']} lines of {f['file']} on {f['host']} exist only at the collector, which looks "
                               f"alarming in a naive diff. Every one of them predates {f['local_coverage_start']}, when a "
                               f"recorded log rotation moved that segment off the host. The absence is expected under the "
                               f"stated retention policy, so it is reported as a benign explanation, not as tampering.")})
    else:
        gaps = rec["heartbeat_gaps"]
        no_beats = sorted(h for h, v in (rec.get("coverage", {}).get("heartbeat") or {}).items() if v != "available")
        none = ("Collection gaps cannot be measured in this evidence: there is no heartbeat data for "
                + ", ".join(no_beats) + ". That is unknown, not gap-free." if no_beats else
                "There is no other gap in this evidence.")
        out.append({**q3, "available": bool(gaps),
                    "evidence_ids": [i for g in gaps[:1] for i in (g["before_event_id"], g["after_event_id"])],
                    "answer": (f"There is a {int(gaps[0]['seconds'])} s collection gap from {gaps[0]['host']} "
                               f"(cause: {gaps[0]['cause'].replace('_', ' ')}). A gap shows collection stopped; it does not "
                               f"show why, so it stays an open note rather than an allegation." if gaps else none)})
    return out
