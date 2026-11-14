"""Read-only evidence views for the case board. No truth is involved anywhere here."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from alibi import checks
from alibi.contracts import Event, EvidenceManifest, InvestigationReport, iso
from alibi.evidence.store import EvidenceStore


class ViewError(ValueError):
    pass


def event_public(ev: Event) -> dict[str, Any]:
    return {
        "id": ev.id, "ts": iso(ev.ts), "ts_raw": ev.ts_raw, "host": ev.host, "source": ev.source,
        "actor": ev.actor, "action": ev.action, "object": ev.object, "attrs": ev.attrs, "raw": ev.raw,
        "artifact": ev.artifact_ref.artifact, "line": ev.artifact_ref.line, "byte_offset": ev.artifact_ref.byte_offset,
    }


def raw_context(raw_dir: Path, manifest: EvidenceManifest, artifact: str, line: int, radius: int = 6) -> dict[str, Any]:
    """Lines around a reference, read from the frozen raw file. Only manifest artifacts are readable."""
    src = next((s for s in manifest.sources if s.artifact == artifact), None)
    if src is None:
        raise ViewError("unknown artifact: only files listed in the evidence manifest can be opened")
    radius = max(0, min(int(radius), 40))
    path = raw_dir / src.artifact
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    line = max(1, min(int(line), max(1, len(lines))))
    lo, hi = max(1, line - radius), min(len(lines), line + radius)
    return {
        "artifact": src.artifact, "host": src.host, "source": src.source, "sha256": src.sha256,
        "tamper_exposure": src.tamper_exposure, "total_lines": len(lines), "focus_line": line,
        "coverage_note": src.coverage_note,
        "lines": [{"n": n, "text": lines[n - 1], "focus": n == line} for n in range(lo, hi + 1)],
    }


def compare_local_collector(store: EvidenceStore, manifest: EvidenceManifest, host: str, file: str,
                            focus_event_id: str | None = None, radius: int = 5) -> dict[str, Any]:
    """Side-by-side rows for one log: the host's own copy next to the collector's copy."""
    pol = checks.policy_from(manifest)
    if (host, file) not in pol.forwarded:
        raise ViewError("this file is not forwarded to the collector, so there is nothing to compare")
    radius = max(1, min(int(radius), 30))
    rec = checks.reconcile_file(store, pol, host, file)
    local = [e for e in store.scan(host=host, logical_file=file) if e.source in ("auth", "syslog", "app", "mqtt")]
    by_seq: dict[int, Event] = {}
    for ev in store.scan(source="collector", origin_host=host, origin_file=file):
        by_seq.setdefault(int(ev.attrs["seq"]), ev)
    unexplained = {r["collector_event_id"] for r in rec["unexplained_local_absence"]}
    retention = set(rec["retention_explained_absence"]["all_collector_event_ids"])
    inconclusive = {r["collector_event_id"] for r in rec["inconclusive_local_absence"]}
    local_only = set(rec["missing_at_collector"]["all_local_event_ids"])

    pool: dict[str, list[Event]] = {}
    for ev in local:
        pool.setdefault(ev.raw, []).append(ev)
    rows: list[dict[str, Any]] = []
    for seq in sorted(by_seq):
        cev = by_seq[seq]
        text = cev.attrs["inner_raw"]
        lev = pool[text].pop(0) if pool.get(text) else None
        if lev is not None:
            status = "both"
        elif cev.id in unexplained:
            status = "retained_by_collector"
        elif cev.id in retention:
            status = "rotated_out"
        elif cev.id in inconclusive:
            status = "inconclusive"
        else:
            status = "collector_only"
        ts = datetime.fromisoformat(cev.attrs["inner_ts"]) if cev.attrs.get("inner_ts") else cev.ts
        rows.append({"ts": iso(ts), "text": text, "status": status, "actor": cev.actor, "action": cev.action,
                     "session_id": cev.attrs.get("session_id"),
                     "local": None if lev is None else {"event_id": lev.id, "artifact": lev.artifact_ref.artifact,
                                                        "line": lev.artifact_ref.line},
                     "collector": {"event_id": cev.id, "seq": seq, "received": iso(cev.ts),
                                   "artifact": cev.artifact_ref.artifact, "line": cev.artifact_ref.line}})
    for ev in local:
        if ev.id in local_only:
            rows.append({"ts": iso(ev.ts), "text": ev.raw, "status": "local_only", "actor": ev.actor, "action": ev.action,
                         "session_id": ev.attrs.get("session_id"),
                         "local": {"event_id": ev.id, "artifact": ev.artifact_ref.artifact, "line": ev.artifact_ref.line},
                         "collector": None})
    rows.sort(key=lambda r: (r["ts"], (r["collector"] or {}).get("seq", 0)))

    focus = None
    if focus_event_id:
        focus = next((i for i, r in enumerate(rows) if focus_event_id in ((r["local"] or {}).get("event_id"),
                                                                           (r["collector"] or {}).get("event_id"))), None)
    if focus is None:
        focus = next((i for i, r in enumerate(rows) if r["status"] == "retained_by_collector"), None)
    if focus is None:
        focus = next((i for i, r in enumerate(rows) if r["status"] in ("local_only", "inconclusive")), None)
    if focus is None:
        focus = max(0, len(rows) - 1 - radius)
    lo, hi = max(0, focus - radius), min(len(rows), focus + radius + 1)
    window = [dict(r, focus=(i == focus)) for i, r in enumerate(rows[lo:hi], start=lo)]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "host": host, "file": file, "status": rec["status"], "counts": counts,
        "local_coverage_start": rec["local_coverage_start"], "coverage_basis": rec["coverage_basis"],
        "coverage_boundary_event_ids": rec["coverage_boundary_event_ids"], "rotations": rec["rotations"],
        "local_segments": rec["local_segments"], "rows": window, "rows_total": len(rows), "window_start": lo,
        "legend": {
            "both": "present on the host and at the collector",
            "retained_by_collector": "retained by collector; absent from the host's own log after its retention boundary",
            "rotated_out": "only at the collector because the host rotated this segment out (expected)",
            "local_only": "on the host only; the collector never received it (collection gap)",
            "inconclusive": "absent locally but no later local record brackets it",
            "collector_only": "only at the collector",
        },
    }


def timeline(store: EvidenceStore, manifest: EvidenceManifest, report: InvestigationReport | None = None,
             bucket_minutes: int = 10) -> dict[str, Any]:
    """Swimlane data: activity counts per source, marked gaps, and cited-evidence marks."""
    start, end = manifest.capture_start, manifest.capture_end
    bucket = timedelta(minutes=bucket_minutes)
    n = int((end - start) / bucket) + 1
    pol = checks.policy_from(manifest)
    rec = checks.reconcile_logs(store, manifest)

    def lane(key: str, label: str, witness: bool, events: list[Event], ts_of=lambda e: e.ts) -> dict[str, Any]:
        counts = [0] * n
        for ev in events:
            i = int((ts_of(ev) - start) / bucket)
            if 0 <= i < n:
                counts[i] += 1
        return {"key": key, "label": label, "independent_witness": witness, "counts": counts, "total": len(events),
                "gaps": [], "marks": []}

    inner = lambda e: datetime.fromisoformat(e.attrs["inner_ts"]) if e.attrs.get("inner_ts") else e.ts  # noqa: E731
    lanes = [
        lane("ws-auth-local", "workstation · auth.log (host copy)", False, store.scan(source="auth", host="workstation")),
        lane("ws-auth-collector", "workstation · auth.log (collector copy)", True,
             store.scan(source="collector", origin_host="workstation", origin_file="/var/log/auth.log"), inner),
        lane("rec-app-local", "records · access.log (host copy)", False, store.scan(source="app", host="records")),
        lane("rec-app-collector", "records · access.log (collector copy)", True,
             store.scan(source="collector", origin_host="records", origin_file="/var/log/records-app/access.log"), inner),
        lane("ws-history", "workstation · shell history", False, store.scan(source="shell_history", host="workstation")),
        lane("flows", "tap · bulk flows", True,
             [f for f in store.scan(source="flow") if max(f.attrs["bytes_out"], f.attrs["bytes_in"]) >= pol.bulk_threshold]),
        lane("badge", "badge reader", True, store.scan(source="badge")),
    ]
    by_key = {ln["key"]: ln for ln in lanes}
    lane_for = {("workstation", "/var/log/auth.log"): "ws-auth-local",
                ("records", "/var/log/records-app/access.log"): "rec-app-local"}
    for f in rec["files"]:
        key = lane_for.get((f["host"], f["file"]))
        if not key:
            continue
        ret = f["retention_explained_absence"]
        if ret["count"]:
            by_key[key]["gaps"].append({"kind": "rotated_out", "start": ret["first_ts"], "end": f["local_coverage_start"],
                                        "label": f"{ret['count']} lines rotated out (expected)",
                                        "evidence_ids": f["coverage_boundary_event_ids"]})
        for row in f["unexplained_local_absence"]:
            by_key[key]["gaps"].append({"kind": "missing_local", "start": row["line_ts"], "end": row["line_ts"],
                                        "label": "line absent locally, retained by collector",
                                        "evidence_ids": [row["collector_event_id"]]})
    for g in rec["heartbeat_gaps"]:
        tgt = by_key.get("ws-auth-collector" if g["host"] == "workstation" else "rec-app-collector")
        if tgt:
            tgt["gaps"].append({"kind": "collection_gap", "start": g["start"], "end": g["end"],
                                "label": f"collection gap {int(g['seconds'])} s (cause: {g['cause'].replace('_', ' ')})",
                                "evidence_ids": [g["before_event_id"], g["after_event_id"]]})
    if report is not None:
        cited: dict[str, list[str]] = {}
        for f in report.findings:
            for eid in f.evidence_ids:
                cited.setdefault(eid, []).append(f.id)
        for ev in store.get(list(cited)[:200]):
            if ev.source == "collector":
                key = {"/var/log/auth.log": "ws-auth-collector",
                       "/var/log/records-app/access.log": "rec-app-collector"}.get(ev.attrs.get("origin_file"))
                ts = inner(ev)
            else:
                key = {"auth": "ws-auth-local", "app": "rec-app-local", "shell_history": "ws-history",
                       "flow": "flows", "badge": "badge"}.get(ev.source)
                ts = ev.ts
            if key in by_key:
                by_key[key]["marks"].append({"event_id": ev.id, "ts": iso(ts), "finding_ids": cited[ev.id]})
    return {"start": iso(start), "end": iso(end), "bucket_minutes": bucket_minutes, "buckets": n, "lanes": lanes}
