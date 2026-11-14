"""Deterministic contradiction checks (PLAN 9.2): the scientific core.

Each check is a pure function over the read-only evidence store plus the
investigator-visible operational context. It returns compact structured
observations with event ids. Checks compute *observations under explicit coverage
assumptions*; they never decide guilt and never see the answer key.

Coverage rules (1.1.0)
  * A source that is not in the bundle makes the dependent comparison NOT ASSESSABLE. That is
    "unknown": never "consistent", never "no anomaly", never an allegation.
  * A collector-retained line is called unexplained only when a local record precedes it AND a
    local record follows it. A missing prefix (late-start capture) or missing tail is inconclusive.
  * Where a source declares when it was recording, lines outside that window are outside coverage.

P0 checks
  reconcile_logs      local log vs. collector copy, rotation/retention aware
  correlate_transfers bulk flows vs. destination policy, sessions and staged objects
  assess_presence     session origin vs. badge presence of the account's holder
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from alibi.contracts import Event, EvidenceManifest, iso
from alibi.evidence.store import EvidenceStore

CHECKS_VERSION = "1.1.0"  # 1.1.0: both local brackets required; declared coverage honored; absent sources are unknown
SIZE_TOLERANCE = 0.01  # staged object vs. transfer size
STAGING_LOOKBACK_S = 1800
GAP_FACTOR = 2.5  # heartbeat gap = silence longer than this many intervals
SAMPLE = 5

_LOCAL_SOURCES = ("auth", "syslog", "app", "mqtt")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _inner_ts(ev: Event) -> datetime:
    raw = ev.attrs.get("inner_ts")
    return _dt(raw) if raw else ev.ts


# --------------------------------------------------------------------------- context helpers


@dataclass
class Policy:
    capture_start: datetime
    capture_end: datetime
    heartbeat_interval_s: int
    forwarded: list[tuple[str, str]]
    rotation_keep: dict[tuple[str, str], int]
    bulk_threshold: int
    approved_ips: dict[str, str]  # ip -> name/purpose
    ip_role: dict[str, str]
    ip_name: dict[str, str]
    role_ip: dict[str, str]
    account_badge: dict[str, str | None]
    account_role: dict[str, str]
    remote_allowed: bool
    remote_via_ip: str | None
    # what the bundle actually contains (from the manifest, never from the stated policy)
    source_kinds: set[str] = field(default_factory=set)
    local_files: set[tuple[str, str]] = field(default_factory=set)
    declared_spans: dict[tuple[str, str], list[tuple[datetime, datetime]]] = field(default_factory=dict)
    known_gaps: dict[tuple[str, str], list[tuple[datetime, datetime, str]]] = field(default_factory=dict)
    collector_spans: list[tuple[datetime, datetime]] = field(default_factory=list)
    collector_gaps: list[tuple[datetime, datetime, str]] = field(default_factory=list)

    def has(self, kind: str) -> bool:
        return kind in self.source_kinds


def _coverage_from(manifest: EvidenceManifest) -> dict[str, Any]:
    kinds = {s.source for s in manifest.sources}
    local_files: set[tuple[str, str]] = set()
    undeclared: set[tuple[str, str]] = set()
    spans: dict[tuple[str, str], list[tuple[datetime, datetime]]] = {}
    gaps: dict[tuple[str, str], list[tuple[datetime, datetime, str]]] = {}
    c_spans: list[tuple[datetime, datetime]] = []
    c_gaps: list[tuple[datetime, datetime, str]] = []
    for src in manifest.sources:
        stated = src.coverage_declared and src.coverage_start is not None and src.coverage_end is not None
        if src.source == "collector":
            if stated:
                c_spans.append((src.coverage_start, src.coverage_end))
            c_gaps += [(g.start, g.end, g.reason) for g in src.known_gaps]
        elif src.source in _LOCAL_SOURCES and src.logical_file:
            key = (src.host, src.logical_file)
            local_files.add(key)
            if stated:
                spans.setdefault(key, []).append((src.coverage_start, src.coverage_end))
            else:
                undeclared.add(key)
            if src.known_gaps:
                gaps.setdefault(key, []).extend((g.start, g.end, g.reason) for g in src.known_gaps)
    # a window is only enforced for a file when EVERY captured generation of it states one
    spans = {k: v for k, v in spans.items() if k not in undeclared}
    return {"source_kinds": kinds, "local_files": local_files, "declared_spans": spans, "known_gaps": gaps,
            "collector_spans": c_spans, "collector_gaps": c_gaps}


def policy_from(manifest: EvidenceManifest) -> Policy:
    ctx = manifest.operational_context
    lp = ctx.get("logging_policy", {})
    tp = ctx.get("transfer_policy", {})
    inv = [e for e in ctx.get("network_inventory", []) if "ip" in e]
    via = (ctx.get("remote_access_policy", {}) or {}).get("via", "") or ""
    via_ip = via.split("(")[-1].rstrip(")") if "(" in via else None
    return Policy(
        capture_start=manifest.capture_start,
        capture_end=manifest.capture_end,
        heartbeat_interval_s=int(lp.get("heartbeat_interval_s", 10)),
        forwarded=[(f["host"], f["file"]) for f in lp.get("forwarded_files", [])],
        rotation_keep={(r["host"], r["file"]): int(r["keep"]) for r in lp.get("rotation", [])},
        bulk_threshold=int(tp.get("bulk_threshold_bytes", 5_000_000)),
        approved_ips={d["ip"]: f"{d['name']} ({d['purpose']})" for d in tp.get("approved_bulk_destinations", [])},
        ip_role={e["ip"]: e["role"] for e in inv},
        ip_name={e["ip"]: e["name"] for e in inv},
        role_ip={e["role"]: e["ip"] for e in inv},
        account_badge={a["account"]: a.get("badge") for a in ctx.get("accounts", [])},
        account_role={a["account"]: a.get("role", "") for a in ctx.get("accounts", [])},
        remote_allowed=bool((ctx.get("remote_access_policy", {}) or {}).get("allowed", False)),
        remote_via_ip=via_ip,
        **_coverage_from(manifest),
    )


@dataclass
class SessionView:
    session_id: str
    host: str
    account: str | None = None
    origin: str | None = None
    tty: str | None = None
    src_ip: str | None = None
    login_ts: datetime | None = None
    logout_ts: datetime | None = None
    login_local_ids: list[str] = field(default_factory=list)
    login_collector_ids: list[str] = field(default_factory=list)
    logout_local_ids: list[str] = field(default_factory=list)
    logout_collector_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        seen = []
        if self.login_local_ids:
            seen.append("local log")
        if self.login_collector_ids:
            seen.append("collector copy")
        return {
            "session_id": self.session_id, "host": self.host, "account": self.account, "origin": self.origin,
            "tty": self.tty, "src_ip": self.src_ip,
            "login_ts": iso(self.login_ts) if self.login_ts else None,
            "logout_ts": iso(self.logout_ts) if self.logout_ts else None,
            "login_event_ids": self.login_local_ids + self.login_collector_ids,
            "logout_event_ids": self.logout_local_ids + self.logout_collector_ids,
            "login_record_seen_in": seen,
        }


def reconstruct_sessions(store: EvidenceStore, host: str) -> dict[str, SessionView]:
    """Merge local auth records and collector copies into per-session views."""
    out: dict[str, SessionView] = {}
    local = store.scan(source="auth", host=host, action=["login", "logout"])
    fwd = store.scan(source="collector", origin_host=host, action=["login", "logout"])
    for ev, is_local in [(e, True) for e in local] + [(e, False) for e in fwd]:
        sid = ev.attrs.get("session_id")
        if not sid:
            continue
        sv = out.setdefault(sid, SessionView(session_id=sid, host=host))
        ts = ev.ts if is_local else _inner_ts(ev)
        sv.account = sv.account or ev.actor
        if ev.action == "login":
            sv.login_ts = sv.login_ts or ts
            sv.origin = sv.origin or ev.attrs.get("origin")
            sv.tty = sv.tty or ev.attrs.get("tty")
            sv.src_ip = sv.src_ip or ev.attrs.get("src_ip")
            (sv.login_local_ids if is_local else sv.login_collector_ids).append(ev.id)
        else:
            sv.logout_ts = sv.logout_ts or ts
            (sv.logout_local_ids if is_local else sv.logout_collector_ids).append(ev.id)
    return out


# --------------------------------------------------------------------------- heartbeat gaps


def heartbeat_gaps(store: EvidenceStore, pol: Policy, host: str) -> list[dict[str, Any]]:
    return heartbeat_view(store, pol, host)[0]


def heartbeat_view(store: EvidenceStore, pol: Policy, host: str) -> tuple[list[dict[str, Any]], str]:
    """Heartbeat gaps for one host, plus whether heartbeat data exists to look for gaps in.

    Fewer than two heartbeats means gaps cannot be measured: the answer is "not_available",
    which is different from "no gaps".
    """
    beats = store.scan(source="heartbeat", origin_host=host)
    availability = "available" if len(beats) >= 2 else "not_available"
    gaps: list[dict[str, Any]] = []
    limit = pol.heartbeat_interval_s * GAP_FACTOR
    svc = store.scan(source="collector", origin_host=host, action="service") + store.scan(source="syslog", host=host, action="service")
    for a, b in zip(beats, beats[1:]):
        delta = (b.ts - a.ts).total_seconds()
        if delta <= limit:
            continue
        restart = [e.id for e in svc if "log-forwarder" in (e.object or "")
                   and a.ts - timedelta(seconds=60) <= (_inner_ts(e) if e.source == "collector" else e.ts) <= b.ts + timedelta(seconds=60)]
        gaps.append({
            "gap_id": f"hbgap-{host}-{len(gaps) + 1}", "host": host, "start": iso(a.ts), "end": iso(b.ts),
            "seconds": delta, "missed_beats": int(delta // pol.heartbeat_interval_s) - 1,
            "before_event_id": a.id, "after_event_id": b.id,
            "sender_counter_reset": int(b.attrs.get("seq", 0)) < int(a.attrs.get("seq", 0)),
            "restart_evidence_ids": sorted(set(restart)),
            "cause": "recorded_service_restart" if restart else "unknown",
            "note": "A heartbeat gap shows collection was interrupted. It does not show why or by whom.",
        })
    return gaps, availability


# --------------------------------------------------------------------------- check 1: local vs collector


def _rotation_records(store: EvidenceStore, host: str, file: str) -> list[dict[str, Any]]:
    """Rotation records for one file, preferring the collector's independent copy."""
    recs: dict[str, dict[str, Any]] = {}
    for ev in store.scan(source="collector", origin_host=host, action="log_rotate"):
        if ev.object == file:
            ts = _inner_ts(ev)
            recs[iso(ts)] = {"ts": ts, "event_ids": [ev.id], "keep": ev.attrs.get("keep"),
                             "archived_offhost": bool(ev.attrs.get("archived_offhost")),
                             "discarded_previous": bool(ev.attrs.get("discarded_previous"))}
    for ev in store.scan(source="syslog", host=host, action="log_rotate"):
        if ev.object == file:
            r = recs.setdefault(iso(ev.ts), {"ts": ev.ts, "event_ids": [], "keep": ev.attrs.get("keep"),
                                             "archived_offhost": bool(ev.attrs.get("archived_offhost")),
                                             "discarded_previous": bool(ev.attrs.get("discarded_previous"))})
            r["event_ids"].append(ev.id)
    return sorted(recs.values(), key=lambda r: r["ts"])


def _not_assessable(host: str, file: str, reason: str, local_lines: int = 0, collector_lines: int = 0) -> dict[str, Any]:
    """Same shape as a reconciled file, with nothing concluded. Unknown is not a clean result."""
    return {
        "host": host, "file": file, "status": "not_assessable", "status_reason": reason,
        "local_lines": local_lines, "collector_lines": collector_lines, "collector_duplicate_deliveries": 0,
        "local_segments": [], "rotations": [], "local_coverage_start": None, "coverage_basis": "not_assessable",
        "coverage_boundary_event_ids": [], "unexplained_local_absence": [],
        "retention_explained_absence": {"count": 0, "first_ts": None, "last_ts": None, "sample_collector_event_ids": [],
                                        "all_collector_event_ids": [], "explanation": None},
        "inconclusive_local_absence": [],
        "missing_at_collector": {"in_heartbeat_gap": 0, "outside_heartbeat_gap": 0, "outside_collector_coverage": 0,
                                 "samples": [], "all_local_event_ids": [], "gap_ids": []},
        "heartbeat_coverage": "not_available",
    }


def _within(ts: datetime, spans: list[tuple[datetime, datetime]]) -> bool:
    return any(a <= ts <= b for a, b in spans)


def _gap_reason(ts: datetime, gaps: list[tuple[datetime, datetime, str]]) -> str | None:
    for a, b, why in gaps:
        if a <= ts <= b:
            return why or "a stated gap in this source's coverage"
    return None


def reconcile_file(store: EvidenceStore, pol: Policy, host: str, file: str,
                   gaps: list[dict[str, Any]] | None = None, heartbeat: str | None = None) -> dict[str, Any]:
    """Compare one host-local log (all captured generations) with the collector's copies."""
    if not pol.has("collector"):
        return _not_assessable(host, file, "this bundle has no collector copy, so the host's own log cannot be "
                               "compared with an independent one. Its completeness is unknown.",
                               local_lines=len([e for e in store.scan(host=host, logical_file=file)
                                                if e.source in _LOCAL_SOURCES]))
    if (host, file) not in pol.local_files:
        return _not_assessable(host, file, f"the host's own copy of {file} is not in this bundle, so collector records "
                               "cannot be compared with it. That is a property of the bundle, not evidence of removal.",
                               collector_lines=len({int(e.attrs["seq"]) for e in
                                                    store.scan(source="collector", origin_host=host, origin_file=file)}))
    if gaps is None or heartbeat is None:
        gaps, heartbeat = heartbeat_view(store, pol, host)
    local = [e for e in store.scan(host=host, logical_file=file) if e.source in _LOCAL_SOURCES]
    fwd_all = store.scan(source="collector", origin_host=host, origin_file=file)
    by_seq: dict[int, Event] = {}
    for ev in fwd_all:
        by_seq.setdefault(int(ev.attrs["seq"]), ev)  # the first delivery of each sequence number
    fwd = [by_seq[s] for s in sorted(by_seq)]
    duplicates = len(fwd_all) - len(fwd)

    # multiset match on the exact original line text
    remaining = Counter(e.raw for e in local)
    missing_locally: list[Event] = []
    for ev in fwd:
        text = ev.attrs["inner_raw"]
        if remaining[text] > 0:
            remaining[text] -= 1
        else:
            missing_locally.append(ev)
    fwd_texts = Counter(e.attrs["inner_raw"] for e in fwd)
    missing_at_collector: list[Event] = []
    for ev in local:
        if fwd_texts[ev.raw] > 0:
            fwd_texts[ev.raw] -= 1
        else:
            missing_at_collector.append(ev)

    # local retention boundary from rotation records and the keep policy
    rotations = _rotation_records(store, host, file)
    keep = None
    if rotations and rotations[-1]["keep"] is not None:
        keep = int(rotations[-1]["keep"])
    if keep is None:
        keep = pol.rotation_keep.get((host, file), 1)
    idx = len(rotations) - keep
    if rotations and idx >= 1:
        boundary = rotations[idx - 1]
        coverage_start, basis = boundary["ts"], "rotation_record"
        boundary_ids = boundary["event_ids"]
    else:
        coverage_start, basis, boundary_ids = pol.capture_start, "capture_start", []

    local_sorted = sorted(local, key=lambda e: (e.ts, e.artifact_ref.artifact, e.artifact_ref.line))
    spans = pol.declared_spans.get((host, file), [])
    stated_gaps = pol.known_gaps.get((host, file), [])
    unexplained: list[dict[str, Any]] = []
    retention: list[Event] = []
    inconclusive: list[dict[str, Any]] = []
    for ev in missing_locally:
        ts = _inner_ts(ev)
        if ts <= coverage_start:
            retention.append(ev)
            continue
        before = next((e for e in reversed(local_sorted) if e.ts <= ts), None)
        after = next((e for e in local_sorted if e.ts >= ts), None)
        row = {
            "collector_event_id": ev.id, "seq": ev.attrs["seq"], "line_ts": iso(ts), "line": ev.attrs["inner_raw"],
            "actor": ev.actor, "action": ev.action, "session_id": ev.attrs.get("session_id"),
            "bracket_before_id": before.id if before else None, "bracket_after_id": after.id if after else None,
        }
        stated = _gap_reason(ts, stated_gaps)
        if stated is not None:
            row["reason"] = f"the host's capture of this file states a gap here ({stated}); the line is outside local coverage"
            inconclusive.append(row)
        elif spans and not _within(ts, spans):
            row["reason"] = ("this line falls outside the window in which the host's copy states it was captured "
                             "(late-start or partial capture); its absence there is not informative")
            inconclusive.append(row)
        elif before is None and after is None:
            row["reason"] = "the host's copy has no records at all to bracket this line; what it covered is unknown"
            inconclusive.append(row)
        elif before is None:
            row["reason"] = ("no earlier local record precedes this line; the host's copy may simply start later "
                             "(missing prefix or late-start capture)")
            inconclusive.append(row)
        elif after is None:
            row["reason"] = "no later local record follows this line; the host's copy may simply end earlier"
            inconclusive.append(row)
        else:  # a local record on BOTH sides: the file covered this moment and the line is not in it
            unexplained.append(row)

    in_gap, not_in_gap, outside_collector = [], [], []
    for ev in missing_at_collector:
        row = {"local_event_id": ev.id, "line_ts": iso(ev.ts), "gap_id": None}
        why = _gap_reason(ev.ts, pol.collector_gaps)
        if why is not None or (pol.collector_spans and not _within(ev.ts, pol.collector_spans)):
            outside_collector.append({**row, "reason": why or "outside the window the collector states it was recording"})
            continue
        g = next((g for g in gaps if _dt(g["start"]) <= ev.ts <= _dt(g["end"])), None)
        row["gap_id"] = g["gap_id"] if g else None
        (in_gap if g else not_in_gap).append(row)

    if unexplained:
        status = "unexplained_local_absence"
    elif inconclusive or not_in_gap:
        status = "inconclusive"
    elif in_gap:
        status = "collection_gap"
    elif outside_collector:
        status = "collector_coverage_limited"
    elif retention:
        status = "retention_explained_only"
    else:
        status = "consistent"
    segs: dict[str, list[Event]] = {}
    for e in local_sorted:
        segs.setdefault(e.artifact_ref.artifact, []).append(e)
    return {
        "host": host, "file": file, "status": status,
        "local_lines": len(local), "collector_lines": len(fwd), "collector_duplicate_deliveries": duplicates,
        "local_segments": [{"artifact": a, "lines": len(v), "first_ts": iso(v[0].ts), "last_ts": iso(v[-1].ts)}
                           for a, v in sorted(segs.items())],
        "rotations": [{"ts": iso(r["ts"]), "event_ids": r["event_ids"], "keep": r["keep"],
                       "archived_offhost": r["archived_offhost"], "discarded_previous": r["discarded_previous"]}
                      for r in rotations],
        "local_coverage_start": iso(coverage_start), "coverage_basis": basis, "coverage_boundary_event_ids": boundary_ids,
        "unexplained_local_absence": unexplained,
        "retention_explained_absence": {
            "count": len(retention),
            "first_ts": iso(_inner_ts(retention[0])) if retention else None,
            "last_ts": iso(_inner_ts(retention[-1])) if retention else None,
            "sample_collector_event_ids": [e.id for e in retention[:SAMPLE]],
            "all_collector_event_ids": [e.id for e in retention],
            "explanation": "these lines predate the oldest log generation still kept on the host" if retention else None,
        },
        "inconclusive_local_absence": inconclusive,
        "missing_at_collector": {
            "in_heartbeat_gap": len(in_gap), "outside_heartbeat_gap": len(not_in_gap),
            "outside_collector_coverage": len(outside_collector),
            "samples": (in_gap + not_in_gap)[:SAMPLE],
            "all_local_event_ids": [r["local_event_id"] for r in in_gap + not_in_gap],
            "gap_ids": sorted({r["gap_id"] for r in in_gap if r["gap_id"]}),
        },
        # "not_available": there is no heartbeat data to look for gaps in, so "no gap" cannot be said
        "heartbeat_coverage": heartbeat,
    }


def reconcile_logs(store: EvidenceStore, manifest: EvidenceManifest, host: str | None = None,
                   file: str | None = None) -> dict[str, Any]:
    """Run the local-vs-collector reconciliation for every forwarded file (or one)."""
    pol = policy_from(manifest)
    targets = [(h, f) for h, f in pol.forwarded if (host is None or h == host) and (file is None or f == file)]
    hosts = sorted({h for h, _ in targets})
    views = {h: heartbeat_view(store, pol, h) for h in hosts}
    files = [reconcile_file(store, pol, h, f, views[h][0], views[h][1]) for h, f in targets]
    blind = [{"host": f["host"], "file": f["file"], "reason": f["status_reason"]} for f in files
             if f["status"] == "not_assessable"]
    no_beats = sorted(h for h in hosts if views[h][1] != "available")
    limits: list[str] = []
    if not pol.has("collector"):
        limits.append("No collector copy is in this bundle. Host-log completeness is unknown; it is not confirmed.")
    elif blind:
        limits.append(f"{len(blind)} forwarded file(s) could not be compared because the host's own copy is not in "
                      "this bundle. That is unknown, not a clean result and not evidence of removal.")
    if no_beats:
        limits.append("No heartbeat data for " + ", ".join(no_beats) + ": collection gaps there cannot be measured, "
                      "so the absence of a reported gap means nothing.")
    return {
        "check": "local_vs_collector", "version": CHECKS_VERSION,
        "assumptions": [
            "the collector, tap and badge reader are not writable from the monitored hosts",
            "lines are matched on exact original text; duplicate deliveries are collapsed by sequence number",
            "a line absent locally is only called unexplained when it postdates the host's retention boundary "
            "and a local record brackets it on BOTH sides (one before, one after)",
            "a source that is missing from the bundle makes the comparison not assessable: unknown, not clean",
        ],
        "files": files,
        "heartbeat_gaps": [g for h in hosts for g in views[h][0]],
        "coverage": {"collector_present": pol.has("collector"),
                     "heartbeat": {h: views[h][1] for h in hosts},
                     "files_not_assessable": blind},
        "coverage_limits": limits,
    }


# --------------------------------------------------------------------------- check 2: transfers


def _near(a: int, b: int, tol: float = SIZE_TOLERANCE) -> bool:
    return b > 0 and abs(a - b) <= max(4096, tol * b)


def export_approval_for(context: dict[str, Any], src_host: str | None, dst: str, start: datetime) -> dict[str, Any] | None:
    """The approved bulk-export change record, if any, that covers a transfer from src_host to dst at `start`.

    A record covers exactly what it names: the source host, the destination address and the time window.
    """
    for rec in context.get("change_records") or []:
        if rec.get("kind") != "bulk_export" or rec.get("destination_ip") != dst or rec.get("source_host") != src_host:
            continue
        try:
            lo, hi = _dt(rec["window_start"]), _dt(rec["window_end"])
        except (KeyError, ValueError):
            continue
        if lo <= start <= hi:
            return rec
    return None


def correlate_transfers(store: EvidenceStore, manifest: EvidenceManifest) -> dict[str, Any]:
    """Bulk outbound flows vs. destination policy, overlapping sessions and staged objects."""
    pol = policy_from(manifest)
    has_sessions = pol.has("auth") or pol.has("collector")
    limits: list[str] = []
    if not pol.has("flow"):
        return {
            "check": "transfer_session_correlation", "version": CHECKS_VERSION, "status": "not_assessable",
            "bulk_threshold_bytes": pol.bulk_threshold, "approved_bulk_destinations": pol.approved_ips,
            "transfers": [],
            "coverage": {"flow": False, "sessions": has_sessions, "shell_history": pol.has("shell_history"),
                         "file_metadata": pol.has("fs_stat")},
            "coverage_limits": ["No network flow source is in this bundle. Whether a bulk transfer happened is "
                                "unknown; an empty list here does not mean there was none."],
        }
    if not has_sessions:
        limits.append("No login records (host auth log or collector copy) are in this bundle: transfers cannot be "
                      "linked to a session. 'No session' here means unknown.")
    if not pol.has("shell_history"):
        limits.append("No shell history is in this bundle: the command behind a transfer cannot be shown.")
    if not pol.has("fs_stat"):
        limits.append("No file metadata snapshot is in this bundle: staging before a transfer cannot be shown.")
    flows = store.scan(source="flow")
    bulk_out = [f for f in flows if f.attrs["bytes_out"] >= pol.bulk_threshold]
    bulk_in = [f for f in flows if f.attrs["bytes_in"] >= pol.bulk_threshold]
    sessions_cache: dict[str, dict[str, SessionView]] = {}
    transfers: list[dict[str, Any]] = []
    for n, fl in enumerate(bulk_out, start=1):
        src, dst = fl.attrs["src"], fl.attrs["dst"]
        src_host = pol.ip_role.get(src)
        start, end = fl.ts, _dt(fl.attrs["end"])
        if dst in pol.approved_ips:
            status, note = "approved", f"destination {dst} is an approved bulk destination: {pol.approved_ips[dst]}"
        elif pol.ip_role.get(dst) in ("workstation", "records", "iot-hub", "collector"):
            status, note = "internal", f"destination {dst} is the clinic host {pol.ip_name.get(dst)}"
        else:
            status, note = "not_approved", (f"destination {dst} is not on the approved bulk-destination list "
                                            f"({', '.join(sorted(pol.approved_ips))})")
        # --- phase two (records family): an approved change record can cover ONE export to a destination that
        # is not on the standing list. Bundles without change records are untouched by this block.
        covering = None
        if status == "not_approved" and "change_records" in manifest.operational_context:
            covering = export_approval_for(manifest.operational_context, src_host, dst, start)
            if covering is not None:
                status = "approved"
                note = (f"destination {dst} is named in approved change record {covering['id']} "
                        f"({covering.get('dataset')} to {covering.get('destination_name')}, "
                        f"{covering['window_start']} to {covering['window_end']})")
            else:
                note += "; no approved change record covers an export to it at this time"
        row: dict[str, Any] = {
            "transfer_id": f"xfer-{n}", "flow_event_id": fl.id, "src": src, "src_host": src_host, "dst": dst,
            "dport": fl.attrs["dport"], "bytes_out": fl.attrs["bytes_out"], "start": iso(start), "end": iso(end),
            "policy_status": status, "policy_note": note, "sessions": [], "session_link": "none",
            "command_event_ids": [], "staged_object": None,
            "limits": ["a flow record shows bytes moved between two addresses; it does not show the content"],
        }
        if covering is not None:
            row["change_record_id"] = covering["id"]
        if src_host in ("workstation", "records"):
            sess = sessions_cache.setdefault(src_host, reconstruct_sessions(store, src_host))
            over = [s for s in sess.values() if s.login_ts and s.login_ts <= start
                    and (s.logout_ts is None or s.logout_ts >= start)]
            row["sessions"] = [s.as_dict() for s in sorted(over, key=lambda s: s.session_id)]
            row["session_link"] = {0: "none", 1: "single_overlapping_session"}.get(len(over), "ambiguous_multiple")
            if not over and not has_sessions:
                row["session_link"] = "unknown_no_login_records_in_bundle"
            accounts = {s.account for s in over}
            cmds = [e for e in store.scan(source="shell_history", host=src_host,
                                          t_start=start - timedelta(seconds=10), t_end=start + timedelta(seconds=10))
                    if dst in (e.object or "") and (not accounts or e.actor in accounts)]
            row["command_event_ids"] = [e.id for e in cmds]
            # staged object: a file on the source host whose size matches, written shortly before
            lo = start - timedelta(seconds=STAGING_LOOKBACK_S)
            stats = [e for e in store.scan(source="fs_stat", host=src_host, t_start=lo, t_end=start)
                     if _near(e.attrs["size"], fl.attrs["bytes_out"])]
            if stats:
                st = stats[-1]
                size = st.attrs["size"]
                exports = [e for e in store.scan(source="app", action="export_bulk", t_start=lo, t_end=start)
                           + store.scan(source="collector", action="export_bulk", t_start=lo, t_end=start + timedelta(seconds=5))
                           if (e.attrs.get("client") == src
                               # phase two: an export made ON the source host itself is logged with a loopback client
                               or (e.attrs.get("client") == "127.0.0.1"
                                   and (e.attrs.get("origin_host") if e.source == "collector" else e.host) == src_host))
                           and _near(int(e.attrs.get("bytes", 0)), size)]
                retr = [f for f in bulk_in if f.attrs["src"] == src and lo <= f.ts <= start and _near(f.attrs["bytes_in"], size)]
                stage_cmds = [e for e in store.scan(source="shell_history", host=src_host, t_start=lo, t_end=start)
                              if (st.object or "\x00") in (e.object or "") and e.id not in row["command_event_ids"]]
                times = [st.ts] + [(_inner_ts(e) if e.source == "collector" else e.ts) for e in exports] + [f.ts for f in retr]
                row["staged_object"] = {
                    "path": st.object, "size": size, "owner": st.actor, "fs_stat_event_id": st.id,
                    "export_event_ids": [e.id for e in exports], "retrieval_flow_event_ids": [f.id for f in retr],
                    "staging_command_event_ids": [e.id for e in stage_cmds],
                    "dataset": next((e.attrs.get("dataset") for e in exports if e.attrs.get("dataset")), None),
                    "start": iso(min(times)), "end": iso(max(times)),
                }
        else:
            # server-side job: no interactive session; look for the app record that explains it
            near = store.scan(source="app", action="export_bulk", t_start=start - timedelta(seconds=60), t_end=end)
            row["job_event_ids"] = [e.id for e in near if e.attrs.get("client") == "127.0.0.1"]
        transfers.append(row)
    return {
        "check": "transfer_session_correlation", "version": CHECKS_VERSION, "status": "assessed",
        "bulk_threshold_bytes": pol.bulk_threshold,
        "approved_bulk_destinations": pol.approved_ips,
        "transfers": transfers,
        "coverage": {"flow": True, "sessions": has_sessions, "shell_history": pol.has("shell_history"),
                     "file_metadata": pol.has("fs_stat")},
        "coverage_limits": limits,
    }


# --------------------------------------------------------------------------- check 3: account vs person


def assess_presence(store: EvidenceStore, manifest: EvidenceManifest, session_id: str) -> dict[str, Any]:
    """Session origin vs. badge presence of the account's holder. Never names a person."""
    pol = policy_from(manifest)
    host = session_id.split("#", 1)[0]
    sv = reconstruct_sessions(store, host).get(session_id)
    limits = [
        "an account identifies a credential, not the person typing",
        "badge readers record badge taps, not people; tailgating and shared badges are not visible",
        "this check cannot establish who operated the session and cannot clear anyone",
    ]
    if sv is None or sv.login_ts is None:
        out0: dict[str, Any] = {"check": "account_vs_person", "version": CHECKS_VERSION, "session_id": session_id,
                                "observation": "session_not_found", "supports_named_person": False, "limits": limits}
        if not (pol.has("auth") or pol.has("collector")):
            out0["observation"] = "login_records_not_in_bundle"
            out0["statement"] = "This bundle has no login records, so the session cannot be examined. That is unknown, not absent."
        return out0
    badge = pol.account_badge.get(sv.account or "")
    out: dict[str, Any] = {
        "check": "account_vs_person", "version": CHECKS_VERSION, "session": sv.as_dict(),
        "account": sv.account, "account_badge": badge, "supports_named_person": False, "limits": limits,
        "badge_event_ids": [], "alternatives": [],
    }
    if sv.origin == "remote":
        permitted = pol.remote_allowed and (pol.remote_via_ip is None or sv.src_ip == pol.remote_via_ip
                                            or pol.ip_role.get(sv.src_ip or "") == "admin-laptop")
        out["observation"] = "remote_session_badge_not_informative"
        out["remote_access_permitted_by_policy"] = bool(permitted)
        out["statement"] = (f"Session {session_id} for account {sv.account} came from {sv.src_ip}. Remote access is "
                            f"{'permitted' if permitted else 'not covered'} by policy; badge records say nothing about a remote user.")
        return out
    if not badge:
        out["observation"] = "no_badge_assigned"
        out["statement"] = f"No badge is assigned to account {sv.account}; physical presence cannot be compared."
        return out
    if not pol.has("badge"):
        out["observation"] = "badge_source_not_in_bundle"
        out["holder_badge_state_at_login"] = "unknown"
        out["statement"] = (f"This bundle has no badge-reader source, so the physical presence of the holder of "
                            f"account {sv.account} cannot be compared with the session. Presence is unknown.")
        return out
    taps = store.scan(source="badge", actor=badge)
    before = [e for e in taps if e.ts <= sv.login_ts]
    after = [e for e in taps if e.ts > sv.login_ts]
    last, nxt = (before[-1] if before else None), (after[0] if after else None)
    out["badge_event_ids"] = [e.id for e in (last, nxt) if e is not None]
    if last is None:
        state = "no_badge_data_before_session"
    else:
        state = "badged_in" if last.action == "badge_in" else "badged_out"
    out["holder_badge_state_at_login"] = state
    present_badges = []
    for acct, b in pol.account_badge.items():
        if not b or b == badge:
            continue
        prev = [e for e in store.scan(source="badge", actor=b) if e.ts <= sv.login_ts]
        if prev and prev[-1].action == "badge_in":
            present_badges.append(acct)
    out["other_account_holders_badged_in"] = sorted(present_badges)
    if state == "badged_out":
        out["observation"] = "console_session_while_holder_badged_out"
        out["statement"] = (
            f"Account {sv.account} opened a console session at {iso(sv.login_ts)} while the badge assigned to that "
            f"account ({badge}) had last tapped out at {iso(last.ts)}. This is inconsistent with the account holder "
            f"sitting at the console, but it does not identify who was.")
        out["alternatives"] = ["someone else used the credential", "the holder re-entered without a badge tap (tailgating)",
                               "a badge event was missed"]
    elif state == "badged_in":
        out["observation"] = "console_session_while_holder_badged_in"
        out["statement"] = (
            f"Account {sv.account} opened a console session at {iso(sv.login_ts)}; the badge assigned to that account "
            f"({badge}) was inside the building. That is compatible with the holder using it and equally with anyone "
            f"else who had the credential.")
        out["alternatives"] = ["the account holder", "another person with the credential"]
    else:
        out["observation"] = "no_badge_data_before_session"
        out["statement"] = f"No badge tap for {badge} precedes this session in the capture; presence is unknown."
    return out
