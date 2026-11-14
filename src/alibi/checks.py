"""Deterministic contradiction checks (PLAN 9.2): the scientific core.

Each check is a pure function over the read-only evidence store plus the
investigator-visible operational context. It returns compact structured
observations with event ids. Checks compute *observations under explicit coverage
assumptions*; they never decide guilt and never see the answer key.

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

CHECKS_VERSION = "1.0.0"
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
    beats = store.scan(source="heartbeat", origin_host=host)
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
    return gaps


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


def reconcile_file(store: EvidenceStore, pol: Policy, host: str, file: str,
                   gaps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Compare one host-local log (all captured generations) with the collector's copies."""
    gaps = heartbeat_gaps(store, pol, host) if gaps is None else gaps
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
        if after is None:
            row["reason"] = "no later local record brackets this line; the local capture may simply end earlier"
            inconclusive.append(row)
        else:
            unexplained.append(row)

    in_gap, not_in_gap = [], []
    for ev in missing_at_collector:
        g = next((g for g in gaps if _dt(g["start"]) <= ev.ts <= _dt(g["end"])), None)
        (in_gap if g else not_in_gap).append({"local_event_id": ev.id, "line_ts": iso(ev.ts), "gap_id": g["gap_id"] if g else None})

    if unexplained:
        status = "unexplained_local_absence"
    elif inconclusive or not_in_gap:
        status = "inconclusive"
    elif in_gap:
        status = "collection_gap"
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
            "samples": (in_gap + not_in_gap)[:SAMPLE],
            "all_local_event_ids": [r["local_event_id"] for r in in_gap + not_in_gap],
            "gap_ids": sorted({r["gap_id"] for r in in_gap if r["gap_id"]}),
        },
    }


def reconcile_logs(store: EvidenceStore, manifest: EvidenceManifest, host: str | None = None,
                   file: str | None = None) -> dict[str, Any]:
    """Run the local-vs-collector reconciliation for every forwarded file (or one)."""
    pol = policy_from(manifest)
    targets = [(h, f) for h, f in pol.forwarded if (host is None or h == host) and (file is None or f == file)]
    hosts = sorted({h for h, _ in targets})
    gaps = {h: heartbeat_gaps(store, pol, h) for h in hosts}
    files = [reconcile_file(store, pol, h, f, gaps[h]) for h, f in targets]
    return {
        "check": "local_vs_collector", "version": CHECKS_VERSION,
        "assumptions": [
            "the collector, tap and badge reader are not writable from the monitored hosts",
            "lines are matched on exact original text; duplicate deliveries are collapsed by sequence number",
            "a line absent locally is only called unexplained when it postdates the host's retention boundary "
            "and a later local record brackets it",
        ],
        "files": files,
        "heartbeat_gaps": [g for h in hosts for g in gaps[h]],
    }


# --------------------------------------------------------------------------- check 2: transfers


def _near(a: int, b: int, tol: float = SIZE_TOLERANCE) -> bool:
    return b > 0 and abs(a - b) <= max(4096, tol * b)


def correlate_transfers(store: EvidenceStore, manifest: EvidenceManifest) -> dict[str, Any]:
    """Bulk outbound flows vs. destination policy, overlapping sessions and staged objects."""
    pol = policy_from(manifest)
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
        row: dict[str, Any] = {
            "transfer_id": f"xfer-{n}", "flow_event_id": fl.id, "src": src, "src_host": src_host, "dst": dst,
            "dport": fl.attrs["dport"], "bytes_out": fl.attrs["bytes_out"], "start": iso(start), "end": iso(end),
            "policy_status": status, "policy_note": note, "sessions": [], "session_link": "none",
            "command_event_ids": [], "staged_object": None,
            "limits": ["a flow record shows bytes moved between two addresses; it does not show the content"],
        }
        if src_host in ("workstation", "records"):
            sess = sessions_cache.setdefault(src_host, reconstruct_sessions(store, src_host))
            over = [s for s in sess.values() if s.login_ts and s.login_ts <= start
                    and (s.logout_ts is None or s.logout_ts >= start)]
            row["sessions"] = [s.as_dict() for s in sorted(over, key=lambda s: s.session_id)]
            row["session_link"] = {0: "none", 1: "single_overlapping_session"}.get(len(over), "ambiguous_multiple")
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
                           if e.attrs.get("client") == src and _near(int(e.attrs.get("bytes", 0)), size)]
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
        "check": "transfer_session_correlation", "version": CHECKS_VERSION,
        "bulk_threshold_bytes": pol.bulk_threshold,
        "approved_bulk_destinations": pol.approved_ips,
        "transfers": transfers,
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
        return {"check": "account_vs_person", "version": CHECKS_VERSION, "session_id": session_id,
                "observation": "session_not_found", "supports_named_person": False, "limits": limits}
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
