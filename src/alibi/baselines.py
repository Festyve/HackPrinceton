"""Offline baselines (PLAN 10.3). No model inference in either.

B0  a fixed keyword/regex recipe over the same observable evidence. It measures
    improvement over *this specific search recipe*, nothing more general.
BR  the deterministic contradiction checks with templated findings. It shows what
    the engineering alone accomplishes, before any model is involved.

Both receive the same frozen bundle and operational context, emit the same report
schema, and go through the same verifier and scorer. Neither reads the answer key,
the seed, the scenario, or any fixture name.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from alibi import checks
from alibi.contracts import AttributionAssessment, EvidenceManifest, Finding, InvestigationReport, Usage
from alibi.evidence.store import EvidenceStore

B0_VERSION = "1.0.0"
BR_VERSION = "1.0.0"

# ----------------------------------------------------------------------------- B0

B0_RULES: list[dict[str, Any]] = [
    {"rule": "upload_tool", "claim_type": "policy_violating_transfer",
     "pattern": r"\bcurl\b.*\s(?:-T|--upload-file)\s|\bscp\s|\bwget\s+--post-file|\bnc\s+-|\brsync\s"},
    {"rule": "bulk_export", "claim_type": "data_staging", "pattern": r"export_bulk|--dataset\s"},
    {"rule": "log_tamper", "claim_type": "local_log_removal",
     "pattern": r"\brm\s+\S*(?:/var/log|\.log)|\bsed\s+-i\b.*(?:/var/log|\.log)|\btruncate\s|\bshred\s|"
                r"history\s+-c|unset\s+HISTFILE|logrotate\s+-f"},
]
_B0_SOURCES = ("shell_history", "auth", "syslog", "app", "collector")
_URL_HOST = re.compile(r"https?://([0-9.]+)(?::(\d+))?")
_OUT_PATH = re.compile(r"--out\s+(\S+)")
_LOG_PATH = re.compile(r"(/var/log/\S+|/etc/logrotate\S*)")


def _b0_object(rule: str, raw: str, ev_object: str | None) -> str:
    if rule == "upload_tool":
        m = _URL_HOST.search(raw)
        if m:
            return f"{m.group(1)}:{m.group(2) or '80'}"
    if rule == "bulk_export":
        m = _OUT_PATH.search(raw)
        if m:
            return m.group(1)
    if rule == "log_tamper":
        m = _LOG_PATH.search(raw)
        if m:
            return m.group(1)
    return ev_object or "unknown"


def run_b0(store: EvidenceStore, manifest: EvidenceManifest) -> InvestigationReport:
    """Grep-style baseline: every rule hit becomes an allegation citing the matching line(s)."""
    started = datetime.now(timezone.utc)
    compiled = [(r, re.compile(r["pattern"])) for r in B0_RULES]
    groups: dict[tuple, dict[str, Any]] = {}
    for ev in store.scan(source=list(_B0_SOURCES)):
        if ev.action == "heartbeat":
            continue
        text = ev.attrs.get("inner_raw", ev.raw) if ev.source == "collector" else ev.raw
        for rule, rx in compiled:
            if not rx.search(text):
                continue
            host = ev.attrs.get("origin_host", ev.host) if ev.source == "collector" else ev.host
            ts = datetime.fromisoformat(ev.attrs["inner_ts"]) if ev.attrs.get("inner_ts") else ev.ts
            obj = _b0_object(rule["rule"], text, ev.object)
            key = (rule["rule"], host, obj, int(ts.timestamp()) // 60)
            g = groups.setdefault(key, {"rule": rule, "host": host, "object": obj, "ts": [], "ids": [],
                                        "actors": [], "sample": text})
            g["ts"].append(ts)
            g["ids"].append(ev.id)
            if ev.actor:
                g["actors"].append(ev.actor)
    findings: list[Finding] = []
    for i, (key, g) in enumerate(sorted(groups.items(), key=lambda kv: (min(kv[1]["ts"]), kv[0])), start=1):
        actors = sorted(set(g["actors"]))
        findings.append(Finding(
            id=f"B0-{i:02d}", claim_type=g["rule"]["claim_type"], category="incident_allegation", host=g["host"],
            account_used=actors[0] if len(actors) == 1 else None,
            t_start=min(g["ts"]), t_end=max(g["ts"]) + timedelta(seconds=60), object_or_session=g["object"],
            evidence_ids=g["ids"], check_refs=[f"b0:{g['rule']['rule']}"], confidence=0.5,
            rationale=f"keyword rule '{g['rule']['rule']}' matched: {g['sample'][:160]}",
            assumptions=["a keyword match is treated as suspicious without cross-checking other sources"],
            produced_by="B0",
        ))
    upload_actors = sorted({f.account_used for f in findings
                            if f.claim_type == "policy_violating_transfer" and f.account_used})
    attribution = AttributionAssessment(
        account_used=upload_actors[0] if len(upload_actors) == 1 else None,
        human_identity="not_assessed",
        statement=("B0 is a keyword recipe. It reports the account only when every upload-tool match belongs to "
                   "one account, and it does not assess who operated an account."),
    )
    wall = (datetime.now(timezone.utc) - started).total_seconds()
    return InvestigationReport(
        report_id=f"rep-B0-{manifest.bundle_id}", bundle_id=manifest.bundle_id, system_id="B0",
        system_label="B0 · fixed keyword/regex recipe", inference_mode="NO_MODEL_BASELINE", findings=findings,
        attribution=attribution, summary=f"{len(findings)} keyword match group(s).",
        usage=Usage(wall_seconds=wall), created_at=started,
    )


# ----------------------------------------------------------------------------- BR templating
# These templating functions are also what the scripted fixture policy uses to turn
# check observations into findings. They are deterministic code, never a model.


def _dt(v: str) -> datetime:
    return datetime.fromisoformat(v)


def findings_from_reconcile(rec: dict[str, Any], produced_by: str = "BR") -> list[Finding]:
    out: list[Finding] = []
    for f in rec["files"]:
        host, file = f["host"], f["file"]
        rows = f["unexplained_local_absence"]
        if rows:
            ts = [_dt(r["line_ts"]) for r in rows]
            brackets = [b for r in rows for b in (r["bracket_before_id"], r["bracket_after_id"]) if b]
            accounts = sorted({r["actor"] for r in rows if r["actor"]})
            sessions = sorted({r["session_id"] for r in rows if r["session_id"]})
            out.append(Finding(
                id="", claim_type="local_log_removal", category="incident_allegation",
                attack_id="T1070.002", technique_family="Indicator removal: host log lines removed",
                host=host, account_used=accounts[0] if len(accounts) == 1 else None,
                t_start=min(ts), t_end=max(ts), object_or_session=file,
                evidence_ids=[r["collector_event_id"] for r in rows] + list(dict.fromkeys(brackets)),
                counterevidence_ids=f["coverage_boundary_event_ids"], check_refs=["local_vs_collector"],
                confidence=0.8,
                rationale=(f"{len(rows)} line(s) of {file} on {host} were received by the collector but are absent "
                           f"from the host's own copy, after the host's retention boundary "
                           f"({f['local_coverage_start']}, basis: {f['coverage_basis']}) and bracketed by later local "
                           f"records. Retained line: {rows[0]['line'][:150]}"
                           + (f" Session(s): {', '.join(sessions)}." if sessions else "")),
                assumptions=["the collector is not writable from the monitored host",
                             "the forwarder delivered the line before it disappeared locally"],
                alternative_explanations=["a local log-agent or filesystem fault dropped the line",
                                          "an administrator edited the file without recording it"],
                produced_by=produced_by,
            ))
        ret = f["retention_explained_absence"]
        if ret["count"]:
            out.append(Finding(
                id="", claim_type="retention_explained_absence", category="benign_explanation", host=host,
                t_start=_dt(ret["first_ts"]), t_end=_dt(ret["last_ts"]), object_or_session=file,
                evidence_ids=ret["sample_collector_event_ids"] + f["coverage_boundary_event_ids"],
                check_refs=["local_vs_collector"], confidence=0.9,
                rationale=(f"{ret['count']} line(s) of {file} on {host} exist only at the collector, and all of them "
                           f"predate the host's retention boundary at {f['local_coverage_start']} "
                           f"(log rotation). Their absence from the host is expected, not suspicious."),
                assumptions=["the rotation record and the stated retention policy are accurate"],
                produced_by=produced_by,
            ))
        mac = f["missing_at_collector"]
        if mac["in_heartbeat_gap"] or mac["outside_heartbeat_gap"]:
            gaps = [g for g in rec["heartbeat_gaps"] if g["gap_id"] in mac["gap_ids"]]
            ids = mac["all_local_event_ids"][:10] + [i for g in gaps for i in (g["before_event_id"], g["after_event_id"])]
            ids += [i for g in gaps for i in g["restart_evidence_ids"]]
            cause = gaps[0]["cause"].replace("_", " ") if gaps else "unknown"
            ts = [_dt(s["line_ts"]) for s in mac["samples"]] or [_dt(g["start"]) for g in gaps]
            out.append(Finding(
                id="", claim_type="collection_gap", category="unresolved", host=host,
                t_start=min([_dt(g["start"]) for g in gaps] + ts), t_end=max([_dt(g["end"]) for g in gaps] + ts),
                object_or_session=file, evidence_ids=list(dict.fromkeys(ids)), check_refs=["local_vs_collector", "heartbeat_gaps"],
                confidence=0.6,
                rationale=(f"{mac['in_heartbeat_gap'] + mac['outside_heartbeat_gap']} line(s) of {file} exist on {host} "
                           f"but never reached the collector"
                           + (f", during a {int(gaps[0]['seconds'])} s heartbeat gap (cause: {cause})." if gaps else
                              ", with no heartbeat gap to explain it.")
                           + " This is a collection gap. The evidence does not show why collection stopped."),
                alternative_explanations=["forwarder maintenance or restart", "transport loss", "collector outage",
                                          "deliberate interruption"],
                produced_by=produced_by,
            ))
    covered = {g for f in rec["files"] for g in f["missing_at_collector"]["gap_ids"]}
    for g in rec["heartbeat_gaps"]:
        if g["gap_id"] in covered:
            continue
        out.append(Finding(
            id="", claim_type="collection_gap", category="unresolved", host=g["host"], t_start=_dt(g["start"]),
            t_end=_dt(g["end"]), object_or_session="heartbeat",
            evidence_ids=[g["before_event_id"], g["after_event_id"], *g["restart_evidence_ids"]],
            check_refs=["heartbeat_gaps"], confidence=0.6,
            rationale=(f"No heartbeat from {g['host']} for {int(g['seconds'])} s (cause: {g['cause'].replace('_', ' ')}). "
                       "Collection was interrupted; the evidence does not show why."),
            alternative_explanations=["maintenance", "transport loss", "collector outage", "deliberate interruption"],
            produced_by=produced_by,
        ))
    return out


def findings_from_transfers(xfer: dict[str, Any], produced_by: str = "BR") -> list[Finding]:
    out: list[Finding] = []
    for t in xfer["transfers"]:
        host = t["src_host"] or "tap"
        sess = t["sessions"][0] if t["session_link"] == "single_overlapping_session" else None
        sess_ids = (sess["login_event_ids"] if sess else [])
        if t["policy_status"] == "not_approved":
            link = (f"It overlaps exactly one session on {host}: {sess['session_id']} (account {sess['account']}, "
                    f"{sess['origin']}; login record seen in: {', '.join(sess['login_record_seen_in'])})."
                    if sess else f"Session link: {t['session_link'].replace('_', ' ')}.")
            out.append(Finding(
                id="", claim_type="policy_violating_transfer", category="incident_allegation",
                technique_family="Transfer to a non-approved destination (exfiltration mapping is context-dependent)",
                host=host, account_used=sess["account"] if sess else None, t_start=_dt(t["start"]), t_end=_dt(t["end"]),
                object_or_session=f"{t['dst']}:{t['dport']}",
                evidence_ids=[t["flow_event_id"], *t["command_event_ids"], *sess_ids],
                check_refs=["transfer_session_correlation"], confidence=0.8,
                rationale=(f"{t['bytes_out']:,} bytes left {host} for {t['dst']}:{t['dport']} between {t['start']} and "
                           f"{t['end']}. {t['policy_note']}. {link}"),
                assumptions=["the supplied destination policy is complete and current"],
                alternative_explanations=["an approved destination missing from the supplied policy"],
                produced_by=produced_by,
            ))
            so = t["staged_object"]
            if so:
                out.append(Finding(
                    id="", claim_type="data_staging", category="incident_allegation", attack_id="T1074.001",
                    technique_family="Local data staging", host=host, account_used=sess["account"] if sess else so["owner"],
                    t_start=_dt(so["start"]), t_end=_dt(so["end"]), object_or_session=so["path"],
                    evidence_ids=[so["fs_stat_event_id"], *so["export_event_ids"], *so["retrieval_flow_event_ids"],
                                  *so["staging_command_event_ids"]],
                    check_refs=["transfer_session_correlation"], confidence=0.7,
                    rationale=(f"{so['path']} ({so['size']:,} bytes, owner {so['owner']}) was written on {host} shortly "
                               f"before the non-approved transfer and matches its size"
                               + (f"; the records application logged a bulk export of '{so['dataset']}' to this host."
                                  if so["dataset"] else ".")),
                    assumptions=["matching size and timing indicate the same object; content was not inspected"],
                    alternative_explanations=["an unrelated file of similar size"],
                    produced_by=produced_by,
                ))
        elif t["bytes_out"]:
            out.append(Finding(
                id="", claim_type="policy_consistent_transfer", category="benign_explanation", host=host,
                account_used=sess["account"] if sess else None, t_start=_dt(t["start"]), t_end=_dt(t["end"]),
                object_or_session=f"{t['dst']}:{t['dport']}",
                evidence_ids=[t["flow_event_id"], *t["command_event_ids"], *t.get("job_event_ids", [])],
                check_refs=["transfer_session_correlation"], confidence=0.9,
                rationale=f"{t['bytes_out']:,} bytes from {host} to {t['dst']}:{t['dport']}. {t['policy_note']}.",
                produced_by=produced_by,
            ))
    return out


def attribution_from(xfer: dict[str, Any], presence: dict[str, Any] | None,
                     findings: list[Finding]) -> AttributionAssessment:
    """Account-vs-person assessment. Never names a person from account activity."""
    bad = [t for t in xfer["transfers"] if t["policy_status"] == "not_approved"]
    removal = [f for f in findings if f.claim_type == "local_log_removal" and f.category == "incident_allegation"]
    if not bad and not removal:
        return AttributionAssessment(
            human_identity="not_assessed",
            statement="No incident is alleged from this evidence, so there is no attribution to assess.")
    linked = [t for t in bad if t["session_link"] == "single_overlapping_session"]
    if linked:
        sess = linked[0]["sessions"][0]
        account, session_ref, support = sess["account"], sess["session_id"], list(sess["login_event_ids"])
    else:
        accounts = sorted({f.account_used for f in removal if f.account_used})
        account, session_ref, support = (accounts[0] if len(accounts) == 1 else None), None, []
    limits = list((presence or {}).get("limits", [])) or [
        "an account identifies a credential, not the person typing"]
    statement = f"Account used: {account}. Human operator not established." if account else \
        "The account used could not be tied to one session. Human operator not established."
    if presence and presence.get("statement"):
        statement += " " + presence["statement"]
    return AttributionAssessment(
        account_used=account, session_ref=session_ref, human_identity="insufficient_evidence",
        supporting_evidence_ids=support, contrary_evidence_ids=list((presence or {}).get("badge_event_ids", [])),
        assumptions=["badge-to-account assignments in the supplied directory are current"],
        limits=limits, statement=statement,
    )


def number_findings(findings: list[Finding], prefix: str = "F") -> list[Finding]:
    order = {"incident_allegation": 0, "unresolved": 1, "benign_explanation": 2, "neutral_reconstruction": 3}
    ranked = sorted(findings, key=lambda f: (order[f.category], f.t_start, f.claim_type, f.host))
    return [f.model_copy(update={"id": f"{prefix}-{i:02d}"}) for i, f in enumerate(ranked, start=1)]


def run_br(store: EvidenceStore, manifest: EvidenceManifest) -> InvestigationReport:
    """Deterministic checks + templated findings. No model inference."""
    started = datetime.now(timezone.utc)
    rec = checks.reconcile_logs(store, manifest)
    xfer = checks.correlate_transfers(store, manifest)
    findings = findings_from_reconcile(rec) + findings_from_transfers(xfer)
    presence = None
    linked = [t for t in xfer["transfers"]
              if t["policy_status"] == "not_approved" and t["session_link"] == "single_overlapping_session"]
    if linked:
        presence = checks.assess_presence(store, manifest, linked[0]["sessions"][0]["session_id"])
    findings = number_findings(findings, "BR")
    attribution = attribution_from(xfer, presence, findings)
    n_inc = sum(f.category == "incident_allegation" for f in findings)
    wall = (datetime.now(timezone.utc) - started).total_seconds()
    return InvestigationReport(
        report_id=f"rep-BR-{manifest.bundle_id}", bundle_id=manifest.bundle_id, system_id="BR",
        system_label="BR · deterministic contradiction checks, templated findings", inference_mode="NO_MODEL_BASELINE",
        findings=findings, attribution=attribution,
        summary=(f"{n_inc} incident allegation(s), {len(findings) - n_inc} benign explanation(s)/open note(s). "
                 + attribution.statement),
        open_questions=([] if not n_inc else ["Who had access to the credential used in the linked session?",
                                              "Was the destination known to anyone at the clinic?"]),
        usage=Usage(wall_seconds=wall), created_at=started,
    )
