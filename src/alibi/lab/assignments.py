"""What the scheduler's own records say about a worker-lab bundle, and what follows for attribution.

Three different things are kept apart here: a worker (W1), the service account it was given (wk-ingest), and
whoever or whatever used that credential. The scheduler records which worker and account were given which job.
That ties an account to a worker's assignments. It does not show which process used the credential, and it is
never a statement about a person.

Deterministic and evidence only: this module reads the frozen evidence store and the manifest. It never reads
the sealed scenario.
"""

from __future__ import annotations

import re
from typing import Any

from alibi.contracts import AttributionAssessment, EvidenceManifest, InvestigationReport, iso
from alibi.evidence.store import EvidenceStore
from alibi.sim.world import APP_LOG, SYSLOG

ASSIGNMENT = re.compile(r"job=(?P<job>\S+) kind=(?P<kind>\S+) dataset=(?P<dataset>\S+) assigned_to=(?P<worker>\S+) account=(?P<account>\S+)")
JOB_ACTIONS = ("ingest", "summarize", "archive")
LIMIT = ("The scheduler's records tie an account to a worker's assignments. They do not show which process used "
         "the credential, and they say nothing about a person.")


def applies(manifest: EvidenceManifest) -> bool:
    return "lab" in manifest.operational_context


def _inner_ts(ev: Any) -> Any:
    from alibi import checks

    return checks._inner_ts(ev) if ev.source == "collector" else ev.ts


def job_assignments(store: EvidenceStore, manifest: EvidenceManifest) -> dict[str, Any]:
    """Which worker and account was given which job, and what each account did that no assigned job explains."""
    if not applies(manifest):
        return {"applicable": False, "assignments": [], "accounts": {}, "unassigned_activity": [],
                "limits": ["this bundle carries no scheduler context"]}
    rows: dict[str, dict[str, Any]] = {}
    # the scheduler writes to the server's system log; the collector holds an independent copy of each line
    for ev in store.scan(source="syslog") + [e for e in store.scan(source="collector") if e.attrs.get("origin_file") == SYSLOG]:
        m = ASSIGNMENT.search(ev.raw)
        if not m:
            continue
        row = rows.setdefault(m["job"], {**m.groupdict(), "event_ids": [], "in_collector": False, "in_host_log": False})
        row["event_ids"].append(ev.id)
        row["in_collector" if ev.source == "collector" else "in_host_log"] = True
    assignments = sorted(rows.values(), key=lambda r: r["job"])
    accounts: dict[str, dict[str, Any]] = {}
    for r in assignments:
        a = accounts.setdefault(r["account"], {"workers": [], "jobs": 0, "kinds": [], "assignment_event_ids": []})
        a["jobs"] += 1
        a["assignment_event_ids"] += r["event_ids"]
        if r["worker"] not in a["workers"]:
            a["workers"].append(r["worker"])
        if r["kind"] not in a["kinds"]:
            a["kinds"].append(r["kind"])
    given = {(r["account"], r["kind"], r["dataset"]) for r in assignments}
    kinds = {(r["account"], r["kind"]) for r in assignments}
    # what each worker account was recorded doing: the collector's copies first, then lines only the host still has
    seen: dict[str, Any] = {}
    for ev in [e for e in store.scan(source="collector") if e.attrs.get("origin_file") == APP_LOG] + store.scan(source="app"):
        if ev.actor not in accounts or str(ev.attrs.get("status")) != "200":
            continue
        key = ev.raw.split(" msg=", 1)[-1] if ev.source == "collector" else ev.raw
        seen.setdefault(key, []).append(ev)
    unassigned: list[dict[str, Any]] = []
    for evs in seen.values():
        ev = evs[0]
        action, dataset = ev.action, ev.attrs.get("dataset")
        if action in JOB_ACTIONS and (ev.actor, action, dataset) in given:
            continue
        if action in JOB_ACTIONS and (ev.actor, action) in kinds:
            reason = "this account has jobs of this kind, but none for this dataset"
        elif action in JOB_ACTIONS:
            reason = "no job of this kind was assigned to this account"
        else:
            reason = "no kind of job the scheduler assigns produces this action"
        unassigned.append({"account": ev.actor, "action": action, "dataset": dataset, "t": iso(_inner_ts(ev)),
                           "event_ids": [e.id for e in evs], "reason": reason})
    unassigned.sort(key=lambda r: (r["t"], r["account"]))
    return {"applicable": True, "assignments": assignments[:200], "assignment_count": len(assignments), "accounts": accounts,
            "unassigned_activity": unassigned[:100], "unassigned_count": len(unassigned), "limits": [LIMIT],
            "produced_by": "deterministic comparison of the scheduler's records with the recorded activity"}


def summary(result: dict[str, Any]) -> tuple[str, list[str]]:
    if not result.get("applicable"):
        return "not applicable to this bundle", []
    ids = [i for r in result["unassigned_activity"] for i in r["event_ids"]]
    return (f"{result['assignment_count']} job assignment(s) for {len(result['accounts'])} account(s); "
            f"{result['unassigned_count']} recorded action(s) that no assigned job explains"), ids[:8]


def worker_link(attribution: AttributionAssessment, result: dict[str, Any]) -> AttributionAssessment:
    """Add what the scheduler's records support: the worker an account was assigned to, and nothing more.

    If the report named no account and exactly one account has recorded actions that no assigned job explains,
    that account is the one the records name, and the statement says on what basis. With several such accounts,
    or none, nothing is added.
    """
    if not result.get("applicable") or attribution.human_identity == "not_assessed":
        return attribution  # no incident is alleged, so there is nothing to attribute
    update: dict[str, Any] = {}
    account, statement = attribution.account_used, attribution.statement
    odd = result["unassigned_activity"]
    odd_accounts = sorted({r["account"] for r in odd})
    if account is None and len(odd_accounts) == 1:
        account = odd_accounts[0]
        ids = [i for r in odd for i in r["event_ids"]]
        update.update(account_used=account, supporting_evidence_ids=list(dict.fromkeys(attribution.supporting_evidence_ids + ids))[:20])
        statement = (f"Account used: {account}, the account named on {len(odd)} recorded action(s) that no assigned job "
                     "explains. Human operator not established.")
    info = result["accounts"].get(account or "")
    if info and len(info["workers"]) == 1:
        worker = info["workers"][0]
        update.update(worker_id=worker, worker_link_evidence_ids=info["assignment_event_ids"][:12])
        mine = [r for r in odd if r["account"] == account]
        statement += (f" The scheduler's records assign this account to worker {worker} ({', '.join(info['kinds'])} jobs)."
                      + (f" {len(mine)} of its recorded action(s) are explained by no assigned job." if mine else "")
                      + " The records do not show which process used the credential.")
    elif info and len(info["workers"]) > 1:
        statement += f" The scheduler's records assign this account to more than one worker ({', '.join(info['workers'])})."
    if not update and statement == attribution.statement:
        return attribution
    limits = attribution.limits if LIMIT in attribution.limits else attribution.limits + [LIMIT]
    return attribution.model_copy(update={**update, "statement": statement[:1200], "limits": limits[:8]})


def verify_worker_link(report: InvestigationReport, store: EvidenceStore, manifest: EvidenceManifest) -> InvestigationReport:
    """Keep a claimed worker link only if the scheduler's records support it. Otherwise remove it and say so."""
    att = report.attribution
    if not applies(manifest) or not att.worker_id:
        return report
    result = job_assignments(store, manifest)
    info = result["accounts"].get(att.account_used or "")
    supported = bool(info) and info["workers"] == [att.worker_id]
    known = set(store.existing_ids(att.worker_link_evidence_ids)) if att.worker_link_evidence_ids else set()
    if supported:
        cited = [i for i in att.worker_link_evidence_ids if i in known and i in info["assignment_event_ids"]]
        fixed = att.model_copy(update={"worker_link_evidence_ids": cited or info["assignment_event_ids"][:12]})
    else:
        note = (f"The report tied the account to worker {att.worker_id}. The scheduler's records do not support that "
                "link, so it was removed.")
        fixed = att.model_copy(update={"worker_id": None, "worker_link_evidence_ids": [],
                                       "limits": (att.limits + [note])[:8]})
    return report.model_copy(update={"attribution": fixed})


__all__ = ["LIMIT", "applies", "job_assignments", "summary", "verify_worker_link", "worker_link"]
