"""Deterministic checks for the phase-two case families and bounded steps.

Same rules as `checks.py`: pure functions over the read-only evidence store and the
investigator-visible operating context; structured observations with event ids; no answer
key; no decision about guilt or intent. A source that is not in the bundle makes the
dependent comparison NOT ASSESSABLE, which is "unknown", never "clean" and never an allegation.

  review_exports          bulk exports in the records application's log vs. approvals and transfers
  link_sessions           sessions opened on one monitored host from another, vs. access policy
  review_forwarding       collection gaps vs. recorded stop commands and approved maintenance
  review_file_times       files whose change time is long after their modification time
  review_shell_history    records activity from the workstation with no shell-history command
  compare_sensor_streams  the hub's stored temperature readings vs. the independent reference logger

`observations()` runs them all for bundles that carry the phase-two operating context;
`findings()` turns them into templated baseline findings; `predicate()` and
`note_predicate()` are the registered rule predicates the verifier applies.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from alibi import checks
from alibi.contracts import Event, EvidenceManifest, Finding, iso
from alibi.evidence.store import EvidenceStore

FAMILY_CHECKS_VERSION = "1.0.0"
METADATA_GAP_S = 3600  # a change time this long after the modification time is worth a look
ARRIVAL_LOOKBACK_S = 3600
SESSION_HOSTS = ("workstation", "records")
STOP_CMD, RESTART_CMD = "stop log-forwarder", "restart log-forwarder"
INCIDENT_CLAIMS = ("timestamp_alteration", "forwarding_stopped", "second_host_session", "sensor_stream_discrepancy")
NOTE_CLAIMS = ("shell_history_gap", "metadata_change", "temperature_excursion", "sensor_maintenance",
               "policy_consistent_access")


def applies(manifest: EvidenceManifest) -> bool:
    """True when the bundle carries the phase-two operating context. First-run bundles do not."""
    return "change_policy" in manifest.operational_context


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _when(ev: Event) -> datetime:
    """The time a record describes: for a collector copy, the original line's own timestamp."""
    raw = ev.attrs.get("inner_ts") if ev.source == "collector" else None
    return _dt(raw) if raw else ev.ts


def _origin(ev: Event) -> str:
    return ev.attrs.get("origin_host", ev.host) if ev.source == "collector" else ev.host


def _both_copies(store: EvidenceStore, local_source: str, **filters: Any) -> list[dict[str, Any]]:
    """Records of one kind from the host's own log and from the collector, merged on exact line text.

    Returns [{ts, event, local_ids, collector_ids}] in time order. A record that exists in only one
    place is still returned; which place is visible in the id lists.
    """
    merged: dict[str, dict[str, Any]] = {}
    for ev in store.scan(source=local_source, **filters):
        row = merged.setdefault(ev.raw, {"ts": ev.ts, "event": ev, "local_ids": [], "collector_ids": []})
        row["local_ids"].append(ev.id)
    seen: set[tuple] = set()
    for ev in store.scan(source="collector", **filters):
        if ev.attrs.get("inner_source") != local_source:
            continue
        key = (ev.attrs.get("origin_host"), ev.attrs.get("origin_file"), ev.attrs.get("seq"))
        if key in seen:  # a retransmitted delivery of the same sequence number
            continue
        seen.add(key)
        row = merged.setdefault(ev.attrs["inner_raw"], {"ts": _when(ev), "event": ev, "local_ids": [], "collector_ids": []})
        row["collector_ids"].append(ev.id)
    return sorted(merged.values(), key=lambda r: (r["ts"], r["event"].id))


def _change_cover(context: dict[str, Any], kind: str, host: str, ts: datetime) -> dict[str, Any] | None:
    """The approved change record of this kind that names the host and covers the time, if any."""
    for rec in context.get("change_records") or []:
        if rec.get("kind") != kind or host not in (rec.get("hosts") or [rec.get("source_host")]):
            continue
        try:
            if _dt(rec["window_start"]) <= ts <= _dt(rec["window_end"]):
                return rec
        except (KeyError, ValueError):
            continue
    return None


def _not_assessable(check: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"check": check, "version": FAMILY_CHECKS_VERSION, "status": "not_assessable", "status_reason": reason,
            "coverage_limits": [reason], **extra}


# --------------------------------------------------------------------------- records family: exports


def review_exports(store: EvidenceStore, manifest: EvidenceManifest) -> dict[str, Any]:
    """Every bulk export the records application logged, with its approval status and onward transfer."""
    pol, ctx = checks.policy_from(manifest), manifest.operational_context
    if not (pol.has("app") or pol.has("collector")):
        return _not_assessable("export_review", "Neither the records application's log nor a collector copy of it is "
                               "in this bundle. Whether an export happened is unknown, not ruled out.", exports=[])
    xfer = checks.correlate_transfers(store, manifest)
    crons = _both_copies(store, "syslog", action="cron")
    rows: list[dict[str, Any]] = []
    for n, rec in enumerate(_both_copies(store, "app", action="export_bulk"), start=1):
        ev, ts = rec["event"], rec["ts"]
        client, user = ev.attrs.get("client"), ev.actor
        on_server = client == "127.0.0.1"
        ids = rec["local_ids"] + rec["collector_ids"]
        job = [c for c in crons if c["event"].actor == user and timedelta(0) <= ts - c["ts"] <= timedelta(seconds=30)]
        cover = None
        for cr in ctx.get("change_records") or []:
            try:
                ok = (cr.get("kind") == "bulk_export" and cr.get("dataset") == ev.attrs.get("dataset")
                      and cr.get("requested_by") == user and _dt(cr["window_start"]) <= ts <= _dt(cr["window_end"]))
            except (KeyError, ValueError):
                ok = False
            if ok:
                cover = cr
                break
        if job:
            approval = {"status": "scheduled_job", "evidence_ids": job[0]["local_ids"] + job[0]["collector_ids"],
                        "note": f"started by a scheduled job of {user}"}
        elif cover is not None:
            approval = {"status": "approved_change_record", "change_record_id": cover["id"], "evidence_ids": [],
                        "note": f"covered by change record {cover['id']} ({cover.get('dataset')} to {cover.get('destination_name')})"}
        elif not on_server:
            approval = {"status": "client_request", "evidence_ids": [],
                        "note": "requested from a clinic client; the change-record rule covers exports made on the server"}
        elif "change_records" not in ctx:
            approval = {"status": "approvals_not_stated", "evidence_ids": [],
                        "note": "this bundle states no change records, so approval cannot be assessed"}
        else:
            approval = {"status": "no_covering_change_record", "evidence_ids": [],
                        "note": (f"made on the records server by {user}; no approved change record names this "
                                 f"dataset, requester and time")}
        linked = [{"transfer_id": t["transfer_id"], "flow_event_id": t["flow_event_id"], "dst": t["dst"],
                   "dport": t["dport"], "policy_status": t["policy_status"], "start": t["start"]}
                  for t in xfer["transfers"] if t["staged_object"] and set(ids) & set(t["staged_object"]["export_event_ids"])]
        rows.append({
            "export_id": f"exp-{n}", "ts": iso(ts), "user": user, "client": client, "made_on_records_server": on_server,
            "dataset": ev.attrs.get("dataset"), "bytes": ev.attrs.get("bytes"),
            "local_event_ids": rec["local_ids"], "collector_event_ids": rec["collector_ids"],
            "record_seen_in": [x for x, ok in (("records-app log", rec["local_ids"]), ("collector copy", rec["collector_ids"])) if ok],
            "approval": approval, "linked_transfers": linked,
        })
    limits = list(xfer.get("coverage_limits", []))
    if not pol.has("collector"):
        limits.append("No collector copy is in this bundle: an export removed from the records application's own log "
                      "would not be visible here.")
    if not pol.has("app"):
        limits.append("The records application's own log is not in this bundle: only the collector's copies were read.")
    unapproved = [r for r in rows if r["approval"]["status"] == "no_covering_change_record"]
    return {
        "check": "export_review", "version": FAMILY_CHECKS_VERSION,
        "status": "unapproved_export_present" if unapproved else "all_exports_accounted_for",
        "exports": rows, "change_records": ctx.get("change_records"),
        "coverage": {"records_app_log": pol.has("app"), "collector": pol.has("collector"), "flow": pol.has("flow")},
        "coverage_limits": limits,
        "limits": ["an export record shows that the application produced a dataset; it does not show who typed the request",
                   "a missing change record is a policy observation, not evidence of intent"],
    }


# --------------------------------------------------------------------------- second-host sessions


def link_sessions(store: EvidenceStore, manifest: EvidenceManifest) -> dict[str, Any]:
    """Sessions opened on one monitored host FROM another, the sessions open on the source at the time,
    the tap's record of the connection, and what the stated access policy says about it."""
    pol, ctx = checks.policy_from(manifest), manifest.operational_context
    if not (pol.has("auth") or pol.has("collector")):
        return _not_assessable("cross_host_sessions", "No login records (host auth log or collector copy) are in this "
                               "bundle. Whether a session was opened from another host is unknown.", sessions=[])
    rap = ctx.get("remote_access_policy") or {}
    listed = {s.get("ip") for s in rap.get("admin_sources") or []}
    by_host = {h: checks.reconstruct_sessions(store, h) for h in SESSION_HOSTS}
    flows = store.scan(source="flow") if pol.has("flow") else []
    rows: list[dict[str, Any]] = []
    for host in SESSION_HOSTS:
        for sv in sorted(by_host[host].values(), key=lambda s: s.session_id):
            src_host = pol.ip_role.get(sv.src_ip or "")
            if sv.origin != "remote" or sv.login_ts is None or src_host not in SESSION_HOSTS or src_host == host:
                continue
            on_source = [s for s in by_host[src_host].values() if s.login_ts and s.login_ts <= sv.login_ts
                         and (s.logout_ts is None or s.logout_ts >= sv.login_ts)]
            conn = [f.id for f in flows if f.attrs["src"] == sv.src_ip and f.attrs["dst"] == pol.role_ip.get(host)
                    and f.attrs["dport"] == 22 and abs((f.ts - sv.login_ts).total_seconds()) <= 5]
            cover = _change_cover(ctx, "maintenance", host, sv.login_ts)
            if "admin_sources" not in rap:
                status, note = "policy_not_stated", "this bundle states no administrator source policy"
            elif sv.src_ip in listed:
                status, note = "listed_source", "the source is a listed administrator source"
            elif cover is not None:
                status, note = "covered_by_change_record", f"covered by approved change record {cover['id']}"
            else:
                status = "outside_stated_policy"
                note = (f"{sv.src_ip} ({src_host}) is not a listed administrator source "
                        f"({', '.join(sorted(x for x in listed if x))}) and no approved change record covers "
                        f"{host} at this time")
            rows.append({
                "link_id": f"hop-{len(rows) + 1}", "target_host": host, "source_host": src_host, "source_ip": sv.src_ip,
                "account": sv.account, "account_role": pol.account_role.get(sv.account or ""), "login_ts": iso(sv.login_ts),
                "session": sv.as_dict(), "source_host_sessions": [s.as_dict() for s in sorted(on_source, key=lambda s: s.session_id)],
                "connection_flow_event_ids": conn, "policy_status": status, "policy_note": note,
                "change_record_id": cover["id"] if cover else None,
            })
    limits = []
    if not pol.has("flow"):
        limits.append("No network flow source is in this bundle: the connection itself is not independently recorded.")
    return {
        "check": "cross_host_sessions", "version": FAMILY_CHECKS_VERSION, "status": "assessed", "sessions": rows,
        "coverage": {"login_records": True, "flow": pol.has("flow"), "access_policy": "admin_sources" in rap},
        "coverage_limits": limits,
        "limits": ["a session on the source host at the same time shows which account was signed in there, "
                   "not who opened the second session", "an account identifies a credential, not a person"],
    }


# --------------------------------------------------------------------------- forwarding stops


def review_forwarding(store: EvidenceStore, manifest: EvidenceManifest) -> dict[str, Any]:
    """Collection gaps, the commands recorded around them, and whether approved maintenance covers them."""
    pol, ctx = checks.policy_from(manifest), manifest.operational_context
    if not pol.has("collector"):
        return _not_assessable("forwarding_review", "No collector data is in this bundle, so there are no heartbeats "
                               "to measure a collection gap with. That is unknown, not gap-free.", gaps=[])
    hosts = sorted({h for h, _ in pol.forwarded})
    sudo = _both_copies(store, "auth", action="sudo")
    rows: list[dict[str, Any]] = []
    no_beats: list[str] = []
    for host in hosts:
        gaps, available = checks.heartbeat_view(store, pol, host)
        if available != "available":
            no_beats.append(host)
        for g in gaps:
            start = _dt(g["start"])
            near = [c for c in sudo if _origin(c["event"]) == host and STOP_CMD in (c["event"].object or "")
                    and timedelta(seconds=-120) <= c["ts"] - start <= timedelta(seconds=30)]
            restarts = [c for c in sudo if _origin(c["event"]) == host and RESTART_CMD in (c["event"].object or "")
                        and timedelta(seconds=-120) <= c["ts"] - start <= timedelta(seconds=30)]
            cover = _change_cover(ctx, "maintenance", host, start)
            row = {"gap_id": g["gap_id"], "host": host, "start": g["start"], "end": g["end"], "seconds": g["seconds"],
                   "cause": g["cause"], "before_event_id": g["before_event_id"], "after_event_id": g["after_event_id"],
                   "restart_evidence_ids": g["restart_evidence_ids"], "stop_command_event_ids": [],
                   "stopped_by_account": None, "session_id": None, "change_record_id": cover["id"] if cover else None}
            if near:
                ev = near[0]["event"]
                row.update(stop_command_event_ids=[i for c in near for i in c["local_ids"] + c["collector_ids"]],
                           stopped_by_account=ev.actor, session_id=ev.attrs.get("session_id"))
                if "change_records" not in ctx:
                    row["policy_status"] = "policy_not_stated"
                elif cover is not None:
                    row["policy_status"] = "covered_by_change_record"
                else:
                    row["policy_status"] = "outside_approved_maintenance"
            elif restarts:
                row.update(policy_status="recorded_restart",
                           stop_command_event_ids=[i for c in restarts for i in c["local_ids"] + c["collector_ids"]],
                           stopped_by_account=restarts[0]["event"].actor)
            else:
                row["policy_status"] = "no_stop_command_recorded"
            rows.append(row)
    limits = ["No heartbeat data for " + ", ".join(no_beats) + ": collection gaps there cannot be measured."] if no_beats else []
    return {
        "check": "forwarding_review", "version": FAMILY_CHECKS_VERSION, "status": "assessed", "gaps": rows,
        "coverage": {"collector": True, "heartbeat_not_available_for": no_beats, "change_records": "change_records" in ctx},
        "coverage_limits": limits,
        "limits": ["a recorded stop command shows which account issued it, not who was typing",
                   "a gap with no recorded command shows that collection stopped; it does not show why"],
    }


# --------------------------------------------------------------------------- file times


def review_file_times(store: EvidenceStore, manifest: EvidenceManifest) -> dict[str, Any]:
    """Files whose inode change time is long after their modification time, and what else in the
    evidence says about when their content arrived. A change time can move for ordinary reasons
    (restore, rename, permission change); only a contradiction by an independent record is reported
    as such."""
    pol, ctx = checks.policy_from(manifest), manifest.operational_context
    if not pol.has("fs_stat"):
        return _not_assessable("file_time_review", "No file metadata snapshot is in this bundle. File times are unknown.",
                               files=[])
    exports = _both_copies(store, "app", action="export_bulk")
    sudo = _both_copies(store, "auth", action="sudo")
    flows = store.scan(source="flow") if pol.has("flow") else []
    xfer = checks.correlate_transfers(store, manifest)
    rows: list[dict[str, Any]] = []
    for ev in store.scan(source="fs_stat"):
        mtime, ctime = ev.ts, _dt(ev.attrs["ctime"])
        gap = (ctime - mtime).total_seconds()
        if gap <= METADATA_GAP_S:
            continue
        host, size, path = ev.host, int(ev.attrs["size"]), ev.object or ""
        ip, lo = pol.role_ip.get(host), ctime - timedelta(seconds=ARRIVAL_LOOKBACK_S)
        # independent records that content of this size reached (or was produced on) this host after `mtime`
        exp = [x for x in exports if max(mtime, lo) < x["ts"] <= ctime
               and checks._near(int(x["event"].attrs.get("bytes", 0)), size)
               and (x["event"].attrs.get("client") == ip
                    or (x["event"].attrs.get("client") == "127.0.0.1" and _origin(x["event"]) == host))]
        retr = [f for f in flows if f.attrs["src"] == ip and max(mtime, lo) < f.ts <= ctime
                and checks._near(int(f.attrs["bytes_in"]), size)]
        folder = path.rsplit("/", 1)[0] + "/"
        restore = [c for c in sudo if _origin(c["event"]) == host and "rsync -a" in (c["event"].object or "")
                   and folder in (c["event"].object or "")
                   and timedelta(seconds=-180) <= ctime - c["ts"] <= timedelta(seconds=180)]
        cover = _change_cover(ctx, "maintenance", host, ctime)
        exp_ids = [i for x in exp for i in x["collector_ids"] + x["local_ids"]]
        row: dict[str, Any] = {
            "path": path, "host": host, "owner": ev.actor, "size": size, "mtime": iso(mtime), "ctime": iso(ctime),
            "gap_seconds": gap, "fs_stat_event_id": ev.id, "export_event_ids": exp_ids,
            "retrieval_flow_event_ids": [f.id for f in retr], "restore_event_ids": [], "change_record_id": None,
            "arrival_ts": None, "linked_transfer": None,
        }
        if restore:
            row.update(classification="explained_restore",
                       restore_event_ids=[i for c in restore for i in c["local_ids"] + c["collector_ids"]],
                       change_record_id=cover["id"] if cover else None,
                       note="an administrator's recorded archive restore at the change time preserves old modification times")
        elif exp or retr:
            arrival = min([x["ts"] for x in exp] + [f.ts for f in retr])
            later = [t for t in xfer["transfers"] if t["src_host"] == host and checks._near(size, int(t["bytes_out"]))
                     and arrival <= _dt(t["start"]) <= arrival + timedelta(seconds=checks.STAGING_LOOKBACK_S)]
            row.update(classification="contradicted_by_independent_records", arrival_ts=iso(arrival),
                       linked_transfer=({"transfer_id": later[0]["transfer_id"], "flow_event_id": later[0]["flow_event_id"],
                                         "policy_status": later[0]["policy_status"], "dst": later[0]["dst"],
                                         "dport": later[0]["dport"], "start": later[0]["start"]} if later else None),
                       note=(f"records independent of this host show content of this size arriving at {iso(arrival)}, "
                             f"after the modification time the file now carries"))
        else:
            row.update(classification="unexplained_metadata_change",
                       note="the change time moved without a recorded reason; renames and permission changes do this too")
        rows.append(row)
    limits = []
    if not pol.has("flow"):
        limits.append("No network flow source is in this bundle: a file's arrival cannot be checked against the tap.")
    if not (pol.has("app") or pol.has("collector")):
        limits.append("No records-application log or collector copy is in this bundle: exports cannot be compared.")
    return {
        "check": "file_time_review", "version": FAMILY_CHECKS_VERSION,
        "status": ("contradiction_present" if any(r["classification"] == "contradicted_by_independent_records" for r in rows)
                   else "assessed"),
        "threshold_seconds": METADATA_GAP_S, "files": rows,
        "coverage": {"file_metadata": True, "flow": pol.has("flow"), "exports": pol.has("app") or pol.has("collector")},
        "coverage_limits": limits,
        "limits": ["file metadata is host-local and can be changed on the host; the tap and the collector cannot",
                   "a changed modification time shows that metadata was edited, not who edited it or why"],
    }


# --------------------------------------------------------------------------- shell history


def review_shell_history(store: EvidenceStore, manifest: EvidenceManifest) -> dict[str, Any]:
    """Workstation sessions in which the records application logged requests from the workstation but
    the account's shell history holds no matching command. Shell history has no independent copy, so
    this can never show that a command was removed; it is an open observation."""
    pol, ctx = checks.policy_from(manifest), manifest.operational_context
    missing = [what for what, ok in (("shell history", pol.has("shell_history")),
                                     ("records-application log or collector copy", pol.has("app") or pol.has("collector")),
                                     ("login records", pol.has("auth") or pol.has("collector"))) if not ok]
    if missing:
        return _not_assessable("shell_history_review", "Not in this bundle: " + ", ".join(missing) + ". Shell-history "
                               "consistency is unknown.", sessions=[])
    ws_ip = pol.role_ip.get("workstation")
    reqs = [r for r in _both_copies(store, "app") if r["event"].attrs.get("client") == ws_ip and r["event"].actor]
    hist: dict[str, list[datetime]] = {}
    for ev in store.scan(source="shell_history", host="workstation"):
        hist.setdefault(ev.actor or "", []).append(ev.ts)
    rows: list[dict[str, Any]] = []
    for sv in sorted(checks.reconstruct_sessions(store, "workstation").values(), key=lambda s: s.session_id):
        if sv.login_ts is None or not sv.account:
            continue
        end = sv.logout_ts or pol.capture_end
        mine = [r for r in reqs if r["event"].actor == sv.account and sv.login_ts <= r["ts"] <= end]
        cmds = hist.get(sv.account, [])
        bare = [r for r in mine if not any(timedelta(seconds=-15) <= c - r["ts"] <= timedelta(seconds=5) for c in cmds)]
        if not bare:
            continue
        in_session = sum(sv.login_ts <= c <= end for c in cmds)
        rows.append({
            "session_id": sv.session_id, "account": sv.account, "origin": sv.origin, "login_ts": iso(sv.login_ts),
            "logout_ts": iso(sv.logout_ts) if sv.logout_ts else None, "requests": len(mine),
            "requests_without_history_command": len(bare), "history_commands_in_session": in_session,
            "request_event_ids": [i for r in bare[:10] for i in (r["collector_ids"] or r["local_ids"])[:1]],
            "login_event_ids": sv.login_local_ids + sv.login_collector_ids,
            "classification": "no_history_for_session" if in_session == 0 else "partial_history",
        })
    hp = ctx.get("history_policy") or {}
    return {
        "check": "shell_history_review", "version": FAMILY_CHECKS_VERSION,
        "status": "gaps_present" if rows else "consistent", "sessions": rows,
        "coverage": {"shell_history": True, "history_policy_stated": bool(hp)},
        "coverage_limits": [],
        "limits": [hp.get("note") or "this bundle does not state which clients write shell history",
                   "shell history is host-local and is not forwarded: no source can show that a command once existed"],
    }


# --------------------------------------------------------------------------- cold chain


def compare_sensor_streams(store: EvidenceStore, manifest: EvidenceManifest) -> dict[str, Any]:
    """The hub's stored temperature readings against the independent reference logger.

    A reference reading is compared with every local reading inside the stated clock allowance around
    it. Two or more consecutive reference readings that no nearby local reading comes close to form a
    discrepancy. A discrepancy inside a stated maintenance window is explained by it. The check reports
    that two records disagree. It does not say why.
    """
    pol, ctx = checks.policy_from(manifest), manifest.operational_context
    cp = ctx.get("coldchain_policy")
    missing = [what for what, ok in (("the hub's stored sensor readings", pol.has("sensor")),
                                     ("the independent reference logger", pol.has("reference")),
                                     ("a stated cold-chain policy", bool(cp))) if not ok]
    if missing:
        return _not_assessable("sensor_stream_comparison", "Not in this bundle: " + "; ".join(missing) + ". The stored "
                               "readings cannot be compared with an independent record: unknown, not confirmed.",
                               discrepancies=[], excursions=[])
    sensor = cp["sensor"]
    lo, hi = cp["permitted_range_c"]
    ref_pol = cp.get("reference") or {}
    allow = timedelta(seconds=int(ref_pol.get("max_clock_offset_s", 120)) + int(cp.get("local_interval_s", 60)) // 2)
    tol = float(ref_pol.get("probe_tolerance_c", 0.8))
    windows = []
    for mw in cp.get("maintenance_windows") or []:
        try:
            windows.append((_dt(mw["window_start"]) - allow, _dt(mw["window_end"]) + allow, mw.get("id")))
        except (KeyError, ValueError):
            continue
    local = [e for e in store.scan(source="sensor") if e.object == sensor and e.action == "reading"]
    ref = [e for e in store.scan(source="reference") if e.object == sensor and e.action == "reading"]
    if not local or not ref:
        return _not_assessable("sensor_stream_comparison", "One of the two temperature records holds no readings for "
                               f"{sensor}; they cannot be compared.", discrepancies=[], excursions=[])

    def near(r: Event) -> list[Event]:
        return [e for e in local if r.ts - allow <= e.ts <= r.ts + allow]

    # per reference reading: (event, nearby local readings, distance from the RANGE those readings span).
    # Comparing with the range, not the nearest value, keeps a fast real temperature change (where
    # one-minute readings are far apart in value) from looking like a disagreement.
    marks = []
    for r in ref:
        nb = near(r)
        if nb:
            temps = [e.attrs["temp_c"] for e in nb]
            diff: float | None = max(0.0, min(temps) - r.attrs["temp_c"], r.attrs["temp_c"] - max(temps))
        else:
            diff = None
        marks.append((r, nb, diff))

    def runs(flag) -> list[list[tuple]]:
        out, cur = [], []
        for m in marks:
            if flag(m):
                cur.append(m)
            elif cur:
                out.append(cur)
                cur = []
        if cur:
            out.append(cur)
        return out

    discrepancies: list[dict[str, Any]] = []
    for run in runs(lambda m: m[2] is not None and m[2] > tol):
        start, end = run[0][0].ts, run[-1][0].ts
        mw = next((w for w in windows if w[0] <= start and end <= w[1]), None)
        loc = list({e.id: e for m in run for e in m[1]}.values())
        kind = "explained_maintenance" if mw else ("unexplained" if len(run) >= 2 else "isolated_reading")
        discrepancies.append({
            "discrepancy_id": f"disc-{len(discrepancies) + 1}", "start": iso(start), "end": iso(end),
            "reference_readings": len(run), "reference_event_ids": [m[0].id for m in run],
            "local_event_ids": [e.id for e in sorted(loc, key=lambda e: e.ts)],
            "local_start": iso(min(e.ts for e in loc)), "local_end": iso(max(e.ts for e in loc)),
            "reference_range_c": [min(m[0].attrs["temp_c"] for m in run), max(m[0].attrs["temp_c"] for m in run)],
            "local_range_c": [min(e.attrs["temp_c"] for e in loc), max(e.attrs["temp_c"] for e in loc)],
            "max_difference_c": round(max(m[2] for m in run), 1),
            "reference_out_of_range": any(not lo <= m[0].attrs["temp_c"] <= hi for m in run),
            "local_out_of_range": any(not lo <= e.attrs["temp_c"] <= hi for e in loc),
            "classification": kind, "maintenance_id": mw[2] if mw else None,
        })
    excursions: list[dict[str, Any]] = []
    for run in runs(lambda m: not lo <= m[0].attrs["temp_c"] <= hi):
        if len(run) < 2:
            continue
        loc = list({e.id: e for m in run for e in m[1]}.values())
        out_loc = [e for e in loc if not lo <= e.attrs["temp_c"] <= hi]
        excursions.append({
            "excursion_id": f"exc-{len(excursions) + 1}", "start": iso(run[0][0].ts), "end": iso(run[-1][0].ts),
            "peak_c": max(m[0].attrs["temp_c"] for m in run), "reference_event_ids": [m[0].id for m in run],
            "local_agrees": bool(out_loc) and all(m[2] is not None and m[2] <= tol for m in run),
            "local_event_ids": [e.id for e in sorted(out_loc or loc, key=lambda e: e.ts)][:40],
        })
    # sequence counters of the stored stream
    gaps, restarts = [], []
    for a, b in zip(local, local[1:]):
        step = b.attrs["seq"] - a.attrs["seq"]
        if step > 1:
            gaps.append({"after_event_id": a.id, "before_event_id": b.id, "missing": step - 1, "at": iso(b.ts)})
        elif step < 1:
            restarts.append({"event_id": b.id, "at": iso(b.ts),
                             "in_maintenance_window": any(w[0] <= b.ts <= w[1] for w in windows)})
    counter: dict[str, Any] = {"status": "not_available", "collector_publish_records": None, "local_readings": len(local)}
    if pol.has("collector"):
        seen: set[tuple] = set()
        for ev in store.scan(source="collector", action="publish"):
            if f"/{sensor}/" in (ev.object or ""):
                seen.add((ev.attrs.get("origin_file"), ev.attrs.get("seq")))
        counter.update(collector_publish_records=len(seen),
                       status="match" if len(seen) == len(local) else "mismatch")
    unexplained = [d for d in discrepancies if d["classification"] == "unexplained"]
    status = ("discrepancy_unexplained" if unexplained else
              "discrepancy_explained" if any(d["classification"] == "explained_maintenance" for d in discrepancies) else
              "consistent")
    return {
        "check": "sensor_stream_comparison", "version": FAMILY_CHECKS_VERSION, "status": status, "sensor": sensor,
        "permitted_range_c": [lo, hi], "local_readings": len(local), "reference_readings": len(ref),
        "clock_allowance_s": allow.total_seconds(), "temperature_tolerance_c": tol,
        "discrepancies": discrepancies, "excursions": excursions,
        "sequence": {"local_gaps": gaps, "local_restarts": restarts}, "publish_counter": counter,
        "coverage": {"local_stream": True, "reference": True, "collector": pol.has("collector")},
        "coverage_limits": [] if pol.has("collector") else
        ["No collector data is in this bundle: the number of readings the hub published cannot be cross-checked."],
        "assumptions": ["the reference logger is not reachable from the hub",
                        f"the two clocks differ by no more than the stated {ref_pol.get('max_clock_offset_s', 120)} s",
                        f"the two probes agree within {tol} C when they measure the same air"],
        "limits": ["a discrepancy shows that the two records disagree; it does not show which one was changed, "
                   "when, why or by whom", "temperature alone says nothing about intent"],
    }


# --------------------------------------------------------------------------- everything, for BR and the verifier


def observations(store: EvidenceStore, manifest: EvidenceManifest) -> dict[str, Any]:
    """All phase-two observations for one bundle; empty for a bundle without the phase-two context."""
    if not applies(manifest):
        return {}
    kinds = {s.source for s in manifest.sources}
    cold = "coldchain_policy" in manifest.operational_context or bool(kinds & {"sensor", "reference"})
    return {
        "exports": review_exports(store, manifest),
        "cross_host": link_sessions(store, manifest),
        "forwarding": review_forwarding(store, manifest),
        "file_times": review_file_times(store, manifest),
        "shell_history": review_shell_history(store, manifest),
        # the temperature comparison only concerns a bundle that has, or is stated to have, temperature records
        "sensors": compare_sensor_streams(store, manifest) if cold else {
            "check": "sensor_stream_comparison", "version": FAMILY_CHECKS_VERSION, "status": "not_applicable",
            "status_reason": "this bundle has no temperature records and states no cold-chain policy",
            "discrepancies": [], "excursions": [], "coverage_limits": []},
    }


def coverage_limits(obs: dict[str, Any]) -> list[str]:
    """What the phase-two checks could not assess, as plain statements for a report."""
    out: list[str] = []
    for res in obs.values():
        out += [x for x in res.get("coverage_limits", []) if x not in out]
    return out


def _f(claim: str, category: str, host: str, t0: datetime, t1: datetime, obj: str | None, ids: list[str],
       rationale: str, produced_by: str, **kw: Any) -> Finding:
    return Finding(id="", claim_type=claim, category=category, host=host, t_start=t0, t_end=t1, object_or_session=obj,
                   evidence_ids=list(dict.fromkeys(i for i in ids if i)), rationale=rationale, produced_by=produced_by, **kw)


def findings(obs: dict[str, Any], produced_by: str = "BR") -> list[Finding]:
    """Templated findings from the phase-two observations. Deterministic code, never a model."""
    out: list[Finding] = []
    if not obs:
        return out
    for s in obs["cross_host"].get("sessions", []):
        sess, ts = s["session"], _dt(s["login_ts"])
        on_src = ", ".join(f"{x['session_id']} ({x['account']})" for x in s["source_host_sessions"]) or "none recorded"
        ids = sess["login_event_ids"] + s["connection_flow_event_ids"] + [i for x in s["source_host_sessions"] for i in x["login_event_ids"]]
        if s["policy_status"] == "outside_stated_policy":
            out.append(_f("second_host_session", "incident_allegation", s["target_host"], ts, ts + timedelta(seconds=2),
                          sess["session_id"], ids,
                          (f"Account {s['account']} opened session {sess['session_id']} on {s['target_host']} from "
                           f"{s['source_ip']} ({s['source_host']}) at {s['login_ts']}. {s['policy_note']}. Sessions open "
                           f"on {s['source_host']} at that moment: {on_src}."), produced_by,
                          technique_family="Session on a second host opened from a monitored host, outside access policy",
                          account_used=s["account"], check_refs=["cross_host_sessions"], confidence=0.75,
                          assumptions=["the stated administrator source policy is complete and current"],
                          alternative_explanations=["approved work that was not recorded as a change",
                                                    "the administrator signed in from the shared workstation in person"]))
        elif s["policy_status"] == "covered_by_change_record":
            out.append(_f("policy_consistent_access", "benign_explanation", s["target_host"], ts, ts + timedelta(seconds=2),
                          sess["session_id"], ids,
                          (f"Account {s['account']} opened a session on {s['target_host']} from {s['source_host']}; "
                           f"{s['policy_note']}."), produced_by, check_refs=["cross_host_sessions"], confidence=0.9))
    for g in obs["forwarding"].get("gaps", []):
        ids = g["stop_command_event_ids"] + [g["before_event_id"], g["after_event_id"], *g["restart_evidence_ids"]]
        t0, t1 = _dt(g["start"]), _dt(g["end"])
        if g.get("policy_status") == "outside_approved_maintenance":
            out.append(_f("forwarding_stopped", "incident_allegation", g["host"], t0, t1, "log-forwarder", ids,
                          (f"Log forwarding from {g['host']} stopped for {int(g['seconds'])} s. A stop command by account "
                           f"{g['stopped_by_account']} is recorded at the start of the gap"
                           + (f" in session {g['session_id']}" if g["session_id"] else "")
                           + ", and no approved change record covers maintenance on that host at that time."), produced_by,
                          technique_family="Log forwarding stopped by a recorded command outside approved maintenance",
                          account_used=g["stopped_by_account"], check_refs=["forwarding_review", "heartbeat_gaps"],
                          confidence=0.75, assumptions=["the supplied change records are complete for this shift"],
                          alternative_explanations=["maintenance that was approved but not recorded"]))
        elif g.get("policy_status") == "covered_by_change_record":
            out.append(_f("policy_consistent_access", "benign_explanation", g["host"], t0, t1, "log-forwarder", ids,
                          (f"Log forwarding from {g['host']} was stopped by {g['stopped_by_account']} for "
                           f"{int(g['seconds'])} s under approved change record {g['change_record_id']}."), produced_by,
                          check_refs=["forwarding_review"], confidence=0.9))
    for r in obs["file_times"].get("files", []):
        ctime = _dt(r["ctime"])
        base_ids = [r["fs_stat_event_id"], *r["export_event_ids"], *r["retrieval_flow_event_ids"], *r["restore_event_ids"]]
        if r["classification"] == "contradicted_by_independent_records":
            out.append(_f("timestamp_alteration", "incident_allegation", r["host"], ctime, ctime, r["path"], base_ids,
                          (f"{r['path']} on {r['host']} carries a modification time of {r['mtime']}, but its metadata "
                           f"changed at {r['ctime']} and {r['note']}. The recorded modification time is contradicted; "
                           f"who changed it is not shown."), produced_by,
                          technique_family="File modification time contradicted by independent records",
                          account_used=r["owner"], check_refs=["file_time_review"], confidence=0.75,
                          assumptions=["matching size identifies the same object; content was not inspected"],
                          alternative_explanations=["an unrelated file of the same size with a legitimately old date"]))
            lt = r["linked_transfer"]
            if lt and lt["policy_status"] == "not_approved":
                arrival = _dt(r["arrival_ts"])
                out.append(_f("data_staging", "incident_allegation", r["host"], arrival, arrival + timedelta(seconds=30),
                              r["path"], [*r["export_event_ids"], *r["retrieval_flow_event_ids"], r["fs_stat_event_id"]],
                              (f"{r['path']} ({r['size']:,} bytes) reached {r['host']} at {r['arrival_ts']} according to "
                               f"records independent of that host, shortly before the non-approved transfer of the same "
                               f"size to {lt['dst']}:{lt['dport']}. Its modification time was changed afterwards, so it "
                               f"is identified by its change time."), produced_by, attack_id="T1074.001",
                              technique_family="Local data staging", account_used=r["owner"],
                              check_refs=["file_time_review", "transfer_session_correlation"], confidence=0.7,
                              assumptions=["matching size and timing indicate the same object; content was not inspected"],
                              alternative_explanations=["an unrelated file of similar size"]))
        elif r["classification"] == "unexplained_metadata_change":
            out.append(_f("metadata_change", "unresolved", r["host"], ctime, ctime, r["path"], base_ids,
                          f"The metadata of {r['path']} on {r['host']} changed at {r['ctime']}, long after its "
                          f"modification time ({r['mtime']}); {r['note']}.", produced_by,
                          check_refs=["file_time_review"], confidence=0.4))
    restored = [r for r in obs["file_times"].get("files", []) if r["classification"] == "explained_restore"]
    if restored:
        times = [_dt(r["ctime"]) for r in restored]
        out.append(_f("metadata_change", "benign_explanation", restored[0]["host"], min(times), max(times),
                      restored[0]["path"].rsplit("/", 1)[0],
                      [i for r in restored for i in (r["fs_stat_event_id"], *r["restore_event_ids"])],
                      (f"{len(restored)} file(s) on {restored[0]['host']} have old modification times and a recent change "
                       f"time. An administrator's archive restore is recorded at that moment"
                       + (f" under change record {restored[0]['change_record_id']}" if restored[0]["change_record_id"] else "")
                       + "; a restore preserves modification times."), produced_by,
                      check_refs=["file_time_review"], confidence=0.85))
    for s in obs["shell_history"].get("sessions", []):
        t0 = _dt(s["login_ts"])
        t1 = _dt(s["logout_ts"]) if s["logout_ts"] else t0
        out.append(_f("shell_history_gap", "unresolved", "workstation", t0, t1, s["session_id"],
                      s["request_event_ids"] + s["login_event_ids"],
                      (f"In session {s['session_id']} (account {s['account']}) the records application logged "
                       f"{s['requests_without_history_command']} request(s) from the workstation with no matching "
                       f"shell-history command ({s['history_commands_in_session']} command(s) recorded in the session). "
                       f"Shell history has no independent copy, so this cannot show that anything was removed."),
                      produced_by, check_refs=["shell_history_review"], confidence=0.4,
                      alternative_explanations=["the touch-screen client was used; it writes no shell history",
                                                "history entries were removed on the host"]))
    sens = obs["sensors"]
    for d in sens.get("discrepancies", []):
        t0, t1 = _dt(d["start"]), _dt(d["end"])
        ids = d["reference_event_ids"] + d["local_event_ids"]
        said = (f"the reference logger reads {d['reference_range_c'][0]}-{d['reference_range_c'][1]} C while the hub's "
                f"stored readings for the same period read {d['local_range_c'][0]}-{d['local_range_c'][1]} C "
                f"(difference up to {d['max_difference_c']} C)")
        if d["classification"] == "unexplained":
            out.append(_f("sensor_stream_discrepancy", "incident_allegation", "iot-hub", t0, t1, sens["sensor"], ids,
                          (f"Between {d['start']} and {d['end']} {said}. The difference is larger than the stated probe "
                           f"tolerance, lasts {d['reference_readings']} consecutive reference readings and falls outside "
                           f"every stated maintenance window. The two records disagree; the evidence does not show which "
                           f"was changed, why, or by whom."), produced_by,
                          technique_family="Stored sensor readings disagree with the independent reference",
                          check_refs=["sensor_stream_comparison"], confidence=0.75,
                          assumptions=["the reference logger is independent of the hub and its clock is within the stated allowance"],
                          alternative_explanations=["a fault in one probe", "the hub's probe was moved without a recorded window"]))
        elif d["classification"] == "explained_maintenance":
            out.append(_f("sensor_maintenance", "benign_explanation", "iot-hub", t0, t1, sens["sensor"], ids,
                          f"Between {d['start']} and {d['end']} {said}. This falls inside stated maintenance window "
                          f"{d['maintenance_id']}, during which the hub's probe does not measure the refrigerator.",
                          produced_by, check_refs=["sensor_stream_comparison"], confidence=0.9))
    for e in sens.get("excursions", []):
        out.append(_f("temperature_excursion", "neutral_reconstruction", "iot-hub", _dt(e["start"]), _dt(e["end"]),
                      sens["sensor"], e["reference_event_ids"] + (e["local_event_ids"] if e["local_agrees"] else []),
                      (f"The reference logger recorded temperatures outside the permitted range from {e['start']} to "
                       f"{e['end']} (peak {e['peak_c']} C). "
                       + ("The hub's stored readings show the same warming." if e["local_agrees"] else
                          "The hub's stored readings do not show it.")
                       + " A temperature record does not show why the refrigerator warmed."), produced_by,
                      check_refs=["sensor_stream_comparison"], confidence=0.9))
    return out


# --------------------------------------------------------------------------- rule predicates for the verifier


def _overlaps(f: Finding, start: datetime, end: datetime, tol_s: int = 120) -> bool:
    tol = timedelta(seconds=tol_s)
    return f.t_start - tol <= end and start <= f.t_end + tol


def predicate(f: Finding, cited: set[str], obs: dict[str, Any]) -> tuple[str, str]:
    """(verdict, note) for a phase-two incident allegation; verdict in supported | rejected | unresolved."""
    if not obs:
        return "unresolved", "this bundle does not carry the operating context this claim type is checked against"
    if f.claim_type == "second_host_session":
        res = obs["cross_host"]
        if res["status"] == "not_assessable":
            return "unresolved", res["status_reason"]
        hits = [s for s in res["sessions"] if s["target_host"] == f.host and cited & set(s["session"]["login_event_ids"] + s["connection_flow_event_ids"])]
        if not hits:
            return "unresolved", "no cited record is a session opened on this host from another monitored host"
        bad = [s for s in hits if s["policy_status"] == "outside_stated_policy"]
        if not bad:
            return ("rejected" if all(s["policy_status"] in ("covered_by_change_record", "listed_source") for s in hits)
                    else "unresolved"), f"the cited session is not outside the stated policy: {hits[0]['policy_note']}"
        ts = _dt(bad[0]["login_ts"])
        if not _overlaps(f, ts, ts):
            return "unresolved", "the cited session falls outside the stated time window"
        return "supported", "a session on this host was opened from another monitored host outside the stated access policy"
    if f.claim_type == "forwarding_stopped":
        res = obs["forwarding"]
        if res["status"] == "not_assessable":
            return "unresolved", res["status_reason"]
        hits = [g for g in res["gaps"] if g["host"] == f.host
                and cited & set(g["stop_command_event_ids"] + [g["before_event_id"], g["after_event_id"]])]
        if not hits:
            return "unresolved", "no cited record belongs to a collection gap on this host"
        bad = [g for g in hits if g.get("policy_status") == "outside_approved_maintenance"]
        if not bad:
            g = hits[0]
            if g.get("policy_status") == "covered_by_change_record":
                return "rejected", f"the stop is covered by approved change record {g['change_record_id']}"
            return "unresolved", ("a collection gap is recorded, but no stop command is recorded for it or no change "
                                  "records are stated; the evidence does not show why collection stopped")
        if not _overlaps(f, _dt(bad[0]["start"]), _dt(bad[0]["end"])):
            return "unresolved", "the cited gap falls outside the stated time window"
        return "supported", "a recorded stop command opens this collection gap and no approved change record covers it"
    if f.claim_type == "timestamp_alteration":
        res = obs["file_times"]
        if res["status"] == "not_assessable":
            return "unresolved", res["status_reason"]
        hits = [r for r in res["files"] if r["host"] == f.host
                and cited & {r["fs_stat_event_id"], *r["export_event_ids"], *r["retrieval_flow_event_ids"]}]
        if not hits:
            return "unresolved", "no cited record belongs to a file whose change time is long after its modification time"
        bad = [r for r in hits if r["classification"] == "contradicted_by_independent_records"]
        if not bad:
            if hits[0]["classification"] == "explained_restore":
                return "rejected", "a recorded archive restore explains the old modification time"
            return "unresolved", "the metadata changed, but no independent record contradicts the modification time"
        if not _overlaps(f, _dt(bad[0]["arrival_ts"]), _dt(bad[0]["ctime"])):
            return "unresolved", "the cited file's change falls outside the stated time window"
        return "supported", "an independent record shows the content arriving after the modification time the file carries"
    if f.claim_type == "sensor_stream_discrepancy":
        res = obs["sensors"]
        if res["status"] in ("not_assessable", "not_applicable"):
            return "unresolved", res["status_reason"]
        hits = [d for d in res["discrepancies"] if cited & set(d["reference_event_ids"] + d["local_event_ids"])]
        if not hits:
            return "unresolved", "no cited reading belongs to a period in which the two temperature records disagree"
        bad = [d for d in hits if d["classification"] == "unexplained"]
        if not bad:
            if any(d["classification"] == "explained_maintenance" for d in hits):
                return "rejected", "the cited readings fall inside a stated maintenance window"
            return "unresolved", "a single differing reference reading is not enough to establish a discrepancy"
        if not any(_overlaps(f, _dt(d["start"]), _dt(d["end"])) for d in bad):
            return "unresolved", "the cited discrepancy falls outside the stated time window"
        return "supported", ("the hub's stored readings and the independent reference disagree beyond the stated "
                             "tolerance, outside every stated maintenance window")
    return "unresolved", f"no registered predicate for incident claim type {f.claim_type!r}"


def staging_predicate(f: Finding, cited: set[str], obs: dict[str, Any]) -> tuple[str, str] | None:
    """A staged object that the size-and-modification-time rule cannot see because its modification time
    was changed: identified by independent arrival records instead. None when this does not apply."""
    for r in (obs.get("file_times") or {}).get("files", []):
        if r["host"] != f.host or r["classification"] != "contradicted_by_independent_records":
            continue
        if not cited & {r["fs_stat_event_id"], *r["export_event_ids"], *r["retrieval_flow_event_ids"]}:
            continue
        lt = r["linked_transfer"]
        if lt is None:
            return "unresolved", "the cited object was not followed by a bulk transfer of matching size"
        if lt["policy_status"] != "not_approved":
            return "rejected", "the object was sent to an approved destination; that is not an incident"
        if not _overlaps(f, _dt(r["arrival_ts"]), _dt(lt["start"])):
            return "unresolved", "the cited staging records fall outside the stated time window"
        return "supported", ("an object of matching size reached this host, per records independent of it, shortly "
                             "before a non-approved bulk transfer")
    return None


def note_predicate(f: Finding, cited: set[str], obs: dict[str, Any]) -> bool:
    """Whether a deterministic observation supports a phase-two note (never an allegation)."""
    if not obs:
        return False
    if f.claim_type == "shell_history_gap":
        return any(cited & set(s["request_event_ids"] + s["login_event_ids"]) for s in obs["shell_history"].get("sessions", []))
    if f.claim_type == "metadata_change":
        return any(cited & {r["fs_stat_event_id"], *r["restore_event_ids"]} for r in obs["file_times"].get("files", [])
                   if r["classification"] in ("explained_restore", "unexplained_metadata_change"))
    if f.claim_type == "temperature_excursion":
        return any(cited & set(e["reference_event_ids"]) for e in obs["sensors"].get("excursions", []))
    if f.claim_type == "sensor_maintenance":
        return any(cited & set(d["reference_event_ids"] + d["local_event_ids"]) for d in obs["sensors"].get("discrepancies", [])
                   if d["classification"] == "explained_maintenance")
    if f.claim_type == "policy_consistent_access":
        hops = any(cited & set(s["session"]["login_event_ids"]) for s in obs["cross_host"].get("sessions", [])
                   if s["policy_status"] == "covered_by_change_record")
        stops = any(cited & set(g["stop_command_event_ids"]) for g in obs["forwarding"].get("gaps", [])
                    if g.get("policy_status") == "covered_by_change_record")
        return hops or stops
    return False
