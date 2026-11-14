"""Investigation runners: what actually produces a report for a case.

Every runner receives ONLY a RunContext: a read-only evidence store, the public
manifest, a writable case directory and an event emitter. No runner is handed the
episode id's sealed directory, the seed, the crime card or the scenario.

  deterministic   BR checks with templated findings      -> NO_MODEL_BASELINE
  agent-fixture   DeepAgents graph + scripted policy     -> SCRIPTED_FIXTURE (alibi.agents)
  agent-live      DeepAgents graph + real model          -> LIVE_MODEL (blocked without a runtime)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from alibi import baselines, checks
from alibi.config import Settings
from alibi.contracts import EvidenceManifest, InvestigationReport, Usage
from alibi.evidence.store import EvidenceStore


class Cancelled(RuntimeError):
    pass


@dataclass
class RunContext:
    case_id: str
    store: EvidenceStore
    manifest: EvidenceManifest
    case_dir: Path
    settings: Settings
    emit: Callable[[str, dict[str, Any]], None]
    pace_s: float = 0.0
    is_cancelled: Callable[[], bool] = lambda: False
    paced_seconds: float = field(default=0.0)

    def pace(self, factor: float = 1.0) -> None:
        """Display pacing only. Never counted as compute time."""
        if self.is_cancelled():
            raise Cancelled()
        if self.pace_s > 0:
            delay = self.pace_s * factor
            time.sleep(delay)
            self.paced_seconds += delay


class Runner(Protocol):
    runner_id: str
    inference_mode: str
    model_id: str | None

    def run(self, ctx: RunContext) -> InvestigationReport: ...

    def resume(self, ctx: RunContext, decision: str) -> None: ...


def summarize_reconcile(rec: dict[str, Any]) -> tuple[str, list[str]]:
    un = [(f, r) for f in rec["files"] for r in f["unexplained_local_absence"]]
    ret = sum(f["retention_explained_absence"]["count"] for f in rec["files"])
    gaps = len(rec["heartbeat_gaps"])
    ids = [r["collector_event_id"] for _, r in un]
    return (f"{len(rec['files'])} forwarded logs compared: {len(un)} line(s) unexplainedly absent on the host, "
            f"{ret} explained by rotation, {gaps} collection gap(s)"), ids


def summarize_transfers(xfer: dict[str, Any]) -> tuple[str, list[str]]:
    rows = xfer["transfers"]
    bad = [t for t in rows if t["policy_status"] == "not_approved"]
    return (f"{len(rows)} bulk transfer(s): {len(bad)} to a non-approved destination, "
            f"{len(rows) - len(bad)} consistent with policy"), [t["flow_event_id"] for t in rows]


class DeterministicRunner:
    """BR: contradiction checks with templated findings. No model, no DeepAgents graph."""

    runner_id = "deterministic"
    inference_mode = "NO_MODEL_BASELINE"
    model_id = None
    system_id = "BR"

    def run(self, ctx: RunContext) -> InvestigationReport:
        t0 = time.perf_counter()
        ctx.emit("todo", {"items": [
            {"text": "Reconcile host logs with collector copies", "status": "in_progress"},
            {"text": "Correlate bulk transfers with policy and sessions", "status": "pending"},
            {"text": "Assess account use vs. physical presence", "status": "pending"},
            {"text": "Draft report for review", "status": "pending"}]})
        ctx.emit("agent", {"agent": "deterministic-checks", "status": "started", "task": "run the registered checks"})
        ctx.pace()
        t = time.perf_counter()
        rec = checks.reconcile_logs(ctx.store, ctx.manifest)
        summary, ids = summarize_reconcile(rec)
        ctx.emit("tool", {"agent": "deterministic-checks", "tool": "check_local_vs_collector", "args": {},
                          "result_summary": summary, "evidence_ids": ids[:8], "ok": True,
                          "ms": int((time.perf_counter() - t) * 1000)})
        ctx.pace()
        t = time.perf_counter()
        xfer = checks.correlate_transfers(ctx.store, ctx.manifest)
        summary, ids = summarize_transfers(xfer)
        ctx.emit("tool", {"agent": "deterministic-checks", "tool": "check_transfer_sessions", "args": {},
                          "result_summary": summary, "evidence_ids": ids[:8], "ok": True,
                          "ms": int((time.perf_counter() - t) * 1000)})
        ctx.pace()
        linked = [x for x in xfer["transfers"] if x["policy_status"] == "not_approved"
                  and x["session_link"] == "single_overlapping_session"]
        presence = None
        if linked:
            sid = linked[0]["sessions"][0]["session_id"]
            t = time.perf_counter()
            presence = checks.assess_presence(ctx.store, ctx.manifest, sid)
            ctx.emit("tool", {"agent": "deterministic-checks", "tool": "check_account_vs_person",
                              "args": {"session_id": sid}, "result_summary": presence.get("observation", ""),
                              "evidence_ids": presence.get("badge_event_ids", []), "ok": True,
                              "ms": int((time.perf_counter() - t) * 1000)})
            ctx.pace()
        findings = baselines.number_findings(
            baselines.findings_from_reconcile(rec) + baselines.findings_from_transfers(xfer), "F")
        attribution = baselines.attribution_from(xfer, presence, findings)
        for f in findings:
            ctx.emit("finding", {"finding": f.model_dump(mode="json"), "phase": "proposed"})
            ctx.pace(0.6)
        ctx.emit("agent", {"agent": "deterministic-checks", "status": "finished",
                           "summary": f"{len(findings)} templated finding(s)"})
        n_inc = sum(f.category == "incident_allegation" for f in findings)
        wall = time.perf_counter() - t0 - ctx.paced_seconds
        return InvestigationReport(
            report_id=f"rep-{ctx.case_id}", bundle_id=ctx.manifest.bundle_id, system_id=self.system_id,
            system_label="Deterministic contradiction checks with templated findings",
            inference_mode="NO_MODEL_BASELINE", findings=findings, attribution=attribution,
            summary=(f"{n_inc} incident allegation(s), {len(findings) - n_inc} benign explanation(s)/open note(s). "
                     + attribution.statement),
            open_questions=([] if not n_inc else ["Who had access to the credential used in the linked session?",
                                                  "Was the destination known to anyone at the clinic?"]),
            usage=Usage(wall_seconds=round(wall, 3), tool_calls=3 if linked else 2),
        )

    def resume(self, ctx: RunContext, decision: str) -> None:
        return None


def get_runner(runner_id: str, settings: Settings) -> Runner:
    if runner_id == "deterministic":
        return DeterministicRunner()
    if runner_id in ("agent-fixture", "agent-live"):
        from alibi.agents.runner import AgentRunner  # imported lazily: heavy dependency tree

        return AgentRunner.create(runner_id, settings)
    raise ValueError(f"unknown runner {runner_id!r}")


def default_runner_id(settings: Settings) -> str:
    """Live model only when a zero-charge route is explicitly configured; otherwise the labeled fixture.

    ALIBI_DEFAULT_RUNNER=deterministic|agent-fixture is an operator fallback switch. It can
    never select a live model that the settings do not already allow.
    """
    import os

    forced = (os.environ.get("ALIBI_DEFAULT_RUNNER") or "").strip()
    if forced in ("deterministic", "agent-fixture"):
        return forced
    return "agent-live" if settings.live_block_reason() is None else "agent-fixture"
