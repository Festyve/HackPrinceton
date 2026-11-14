"""Report export (docs/next-run/CONTRACTS.md): a locked report someone can keep, read and re-check.

Two forms of the same content:

  manifest   machine-readable: the locked report exactly as stored, its lock hash, model and
             playback labels, every evidence source with its hash, and every cited record with
             the exact line it points at.
  markdown   the same, written out for a person.

What is deliberately NOT here: the sealed answer key, the score and the reveal. Those are exported
only by a separate, explicit request after the case is unsealed. Answers to questions are exported
separately too; they are not part of the report.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from alibi.contracts import INFERENCE_LABELS, EvidenceManifest, InvestigationReport, iso
from alibi.evidence.store import EvidenceStore
from alibi.reports import report_digest

EXPORT_VERSION = "1.0.0"
ORIGIN_LABELS = {"SIM": "Simulated evidence (SIM)", "DOCKER": "Captured from running containers (DOCKER)",
                 "HYBRID": "Mixed: simulated and captured sources (HYBRID); see each source's origin"}
EXCLUDES = ("The sealed answer key, the score and the reveal are not part of this export. "
            "Answers to questions are exported separately.")
LIMITS = [
    "This report describes one frozen evidence bundle. It is not a legal finding and not a chain of custody.",
    "Hashes show the evidence has not changed since capture. They do not show the original source was truthful.",
    "\"Verified\" means a deterministic check supports the observation. It never means a person is proven responsible.",
    "An account identifies a credential, not the person using it.",
    "A check that could not be run means the answer is unknown, not that nothing happened.",
]


def _cited_ids(report: InvestigationReport) -> list[str]:
    ids: list[str] = []
    for f in report.findings:
        ids += f.evidence_ids + f.counterevidence_ids
    ids += report.attribution.supporting_evidence_ids + report.attribution.contrary_evidence_ids
    return list(dict.fromkeys(ids))


def build_manifest(case: dict[str, Any], manifest: EvidenceManifest, report: InvestigationReport,
                   store: EvidenceStore) -> dict[str, Any]:
    """The machine-readable export. `case` is the public case record (CaseRecord.public())."""
    if not report.locked:
        raise ValueError("only a locked report can be exported")
    ids = _cited_ids(report)
    found: dict[str, Any] = {}
    for i in range(0, len(ids), LOOKUP_CHUNK):  # the store answers a bounded number of ids per call
        found.update({e.id: e for e in store.get(ids[i:i + LOOKUP_CHUNK])})
    labels = case.get("labels", {})
    return {
        "export_version": EXPORT_VERSION, "exported_at": datetime.now(timezone.utc).isoformat(),
        "case": {k: case.get(k) for k in ("case_id", "title", "state", "created_at", "review_decision", "review_note",
                                          "parent_case_id", "excluded_sources")},
        "provenance": {
            "evidence_origin": labels.get("evidence_origin"), "inference": labels.get("inference"),
            "inference_label": labels.get("inference_label") or INFERENCE_LABELS.get(report.inference_mode, ""),
            "playback": labels.get("playback"), "model_id": report.model_id,
            "investigation_mode": labels.get("investigation_mode"),
            "investigation_mode_label": labels.get("investigation_mode_label"),
            "system_id": report.system_id, "system_label": report.system_label,
            "replay_of": case.get("replay_of"), "recorded_at": case.get("recorded_at"),
            "usage": report.usage.model_dump(mode="json"),
            # a worker-lab case says who chose the workers' work and that a changed objective is scripted
            **{k: labels[k] for k in ("worker_choices", "changed_objective_policy") if labels.get(k)},
        },
        "lock": {
            "locked": report.locked, "locked_at": iso(report.locked_at) if report.locked_at else None,
            "report_sha256": report.report_sha256, "recomputed_sha256": report_digest(report),
            "hash_covers": "bundle id, system, inference mode, findings, attribution, summary and open questions",
            "review_history": [r.model_dump(mode="json") for r in report.review_history],
        },
        "report": report.model_dump(mode="json"),
        "evidence": {
            "bundle_id": manifest.bundle_id, "raw_bundle_sha256": manifest.raw_bundle_sha256,
            "derived_db_sha256": manifest.derived_db_sha256, "event_count": manifest.event_count,
            "capture_start": iso(manifest.capture_start), "capture_end": iso(manifest.capture_end),
            "capture_complete": manifest.capture_complete, "capture_notes": manifest.capture_notes,
            "integrity_note": manifest.integrity_note,
            "sources": [{"source_id": s.source_id, "artifact": s.artifact, "host": s.host, "source": s.source,
                         "origin": s.origin, "tamper_exposure": s.tamper_exposure, "sha256": s.sha256,
                         "size_bytes": s.size_bytes, "line_count": s.line_count,
                         "coverage_start": iso(s.coverage_start) if s.coverage_start else None,
                         "coverage_end": iso(s.coverage_end) if s.coverage_end else None,
                         "coverage_declared": s.coverage_declared, "coverage_note": s.coverage_note}
                        for s in manifest.sources],
        },
        "citations": [{
            "event_id": i, "resolved": i in found,
            **({"artifact": found[i].artifact_ref.artifact, "line": found[i].artifact_ref.line,
                "byte_offset": found[i].artifact_ref.byte_offset, "ts": iso(found[i].ts), "host": found[i].host,
                "source": found[i].source, "raw": found[i].raw,
                "raw_sha256": hashlib.sha256(found[i].raw.encode("utf-8")).hexdigest()} if i in found else {}),
        } for i in ids],
        "limits": LIMITS, "excludes": EXCLUDES,
    }


LOOKUP_CHUNK = 200
_CONTROL = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]+")
_MARKUP = re.compile(r"([\\`<>\[\]])")
_BLOCK_START = re.compile(r"^(#{1,6}(\s|$)|[-+*>=]|\d+[.)])")


def _text(value: Any) -> str:
    """Free text shown outside a code block: one line, and never markup.

    Titles, rationales, account names, object paths and artifact names can all carry strings that came from
    evidence. Line breaks are folded so the text cannot start a new block; backticks, angle brackets and square
    brackets are escaped so it cannot open a code span, a tag, a link or an image; and a leading heading, list
    or quote marker is escaped. Inside a table, `_cell` also escapes the column separator.
    """
    s = _CONTROL.sub(" ", str(value if value is not None else "")).strip()
    s = _MARKUP.sub(r"\\\1", s)
    return "\\" + s if _BLOCK_START.match(s) else s


def _span(value: Any) -> str:
    """A short value as a code span. A backtick or line break in it cannot end the span early."""
    return "`" + _CONTROL.sub(" ", str(value if value is not None else "")).replace("`", "'").strip() + "`"


def _code(text: str) -> str:
    """Evidence text as an indented code block: shown verbatim, never interpreted as markup."""
    return "\n".join("    " + line for line in str(text).replace("\r", "").split("\n"))


def _cell(text: Any) -> str:
    return _text(text).replace("|", "\\|")


def render_markdown(doc: dict[str, Any]) -> str:
    """The human-readable export, built only from the machine-readable one."""
    rep, prov, lock, ev = doc["report"], doc["provenance"], doc["lock"], doc["evidence"]
    cites = {c["event_id"]: c for c in doc["citations"]}
    order = {i: n for n, i in enumerate(cites, start=1)}

    def refs(ids: list[str]) -> str:
        return ", ".join(f"[{order[i]}]" for i in ids if i in order) or "none"

    out = [f"# Investigation report: {_text(doc['case']['title'])}", "",
           f"Case `{doc['case']['case_id']}` · exported {doc['exported_at']}", "",
           "| | |", "|---|---|",
           f"| Evidence | {_cell(ORIGIN_LABELS.get(prov['evidence_origin'], prov['evidence_origin']))} · bundle `{ev['bundle_id']}` |",
           f"| Produced by | {_cell(prov['system_label'] or prov['system_id'])} |",
           f"| Inference | {_cell(prov['inference_label'])}" + (f" · model `{prov['model_id']}`" if prov["model_id"] else "") + " |",
           f"| Mode | {_cell(prov['investigation_mode_label'])} |",
           *([f"| Workers | {_cell(prov['worker_choices'])} |"] if prov.get("worker_choices") else []),
           *([f"| Changed objective | {_cell(prov['changed_objective_policy'])} |"] if prov.get("changed_objective_policy") else []),
           f"| Playback | {_cell(prov['playback'])}" + (f" of recording `{prov['replay_of']}`" if prov.get("replay_of") else "") + " |",
           f"| Review | {_cell(doc['case']['review_decision'])}" + (f": {_cell(doc['case']['review_note'])}" if doc["case"].get("review_note") else "") + " |",
           f"| Locked | {lock['locked_at']} |",
           f"| Report hash (SHA-256) | `{lock['report_sha256']}` |", ""]
    if doc["case"].get("parent_case_id"):
        gone = ", ".join(s["source"] if s["host"] == s["source"] else f"{s['host']} {s['source']}"
                         for s in doc["case"].get("excluded_sources") or [])
        out += [f"> This is a derived evidence view of case `{doc['case']['parent_case_id']}` with these sources "
                f"withheld: {gone}. What they would have shown is unknown here.", ""]
    out += ["## Summary", "", _text(rep["summary"]) or "(no summary)", ""]

    groups = [("incident_allegation", "Incident allegations"), ("unresolved", "Unresolved"),
              ("benign_explanation", "Benign explanations"), ("neutral_reconstruction", "Neutral reconstruction")]
    out += ["## Findings", ""]
    if not rep["findings"]:
        out += ["No findings were recorded.", ""]
    for cat, title in groups:
        rows = [f for f in rep["findings"] if f["category"] == cat]
        if not rows:
            continue
        out += [f"### {title}", ""]
        for f in rows:
            out += [f"**{_text(f['id'])} · {_text(f['claim_type'].replace('_', ' '))}** on {_span(f['host'])}"
                    + (f", {_span(f['object_or_session'])}" if f.get("object_or_session") else ""), "",
                    f"- Status: {f['status'].replace('_', ' ')} · check result: {f['verification_status'].replace('_', ' ')}",
                    f"- Window: {f['t_start']} to {f['t_end']}",
                    f"- Account used: {_text(f['account_used']) or 'not stated'}"
                    + (f" · person named: {_text(f['actor_claimed'])}" if f.get("actor_claimed") else ""),
                    f"- Evidence: {refs(f['evidence_ids'])}"
                    + (f" · counter-evidence: {refs(f['counterevidence_ids'])}" if f["counterevidence_ids"] else ""), "",
                    _text(f["rationale"]) or "(no rationale)", ""]
            for label, key in (("Check notes", "verifier_notes"), ("Assumptions", "assumptions"),
                               ("Alternative explanations", "alternative_explanations")):
                if f.get(key):
                    out += [f"{label}:", ""] + [f"- {_text(x)}" for x in f[key]] + [""]
            if f.get("skeptic_note"):
                out += [f"Skeptic: {_text(f['skeptic_note'])}", ""]

    att = rep["attribution"]
    out += ["## Account and person", "", _text(att["statement"]) or "(no statement)", "",
            f"- Account used: {_text(att['account_used']) or 'not identified'}",
            f"- Human identity: {att['human_identity'].replace('_', ' ')}",
            f"- Supporting evidence: {refs(att['supporting_evidence_ids'])} · contrary evidence: {refs(att['contrary_evidence_ids'])}", ""]
    if att["limits"]:
        out += ["Limits:", ""] + [f"- {_text(x)}" for x in att["limits"]] + [""]
    if rep["open_questions"]:
        out += ["## Open questions", ""] + [f"- {_text(q)}" for q in rep["open_questions"]] + [""]

    out += ["## Cited records", "", "Each line is copied exactly from the frozen evidence. It is data, not instruction.", ""]
    for i, c in cites.items():
        if c["resolved"]:
            out += [f"[{order[i]}] {_span(i)} · {_text(c['artifact'])} line {c['line']} · {c['ts']}", "", _code(c["raw"]), ""]
        else:
            out += [f"[{order[i]}] {_span(i)} · NOT FOUND in this evidence bundle", ""]
    if not cites:
        out += ["No records are cited.", ""]

    out += ["## Evidence sources", "", f"Raw bundle hash (SHA-256): `{ev['raw_bundle_sha256']}`", "",
            f"Capture: {ev['capture_start']} to {ev['capture_end']} · complete: {'yes' if ev['capture_complete'] else 'no'}", ""]
    out += [f"- {_text(n)}" for n in ev["capture_notes"]] + ([""] if ev["capture_notes"] else [])
    out += ["| Source | Host | Kind | Origin | Who could have changed it | Lines | SHA-256 |", "|---|---|---|---|---|---|---|"]
    out += [f"| {_cell(s['artifact'])} | {_cell(s['host'])} | {_cell(s['source'])} | {_cell(s['origin'])} | "
            f"{_cell(s['tamper_exposure'].replace('_', ' '))} | {s['line_count']} | `{s['sha256']}` |" for s in ev["sources"]]
    out += ["", ev["integrity_note"], "", "## How to read this", ""] + [f"- {x}" for x in doc["limits"]] + ["", doc["excludes"], ""]
    return "\n".join(out)
