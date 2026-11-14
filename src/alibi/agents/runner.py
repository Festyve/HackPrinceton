"""AgentRunner: runs the DeepAgents investigator for one case and pauses at human review.

agent-fixture  the real graph driven by the scripted fixture policy  -> SCRIPTED_FIXTURE
agent-live     the real graph driven by a real model via the gateway -> LIVE_MODEL
               (refused unless a zero-charge route is explicitly configured)

The graph checkpoints to SQLite inside the case directory with thread_id = case id,
so a report awaiting review survives a browser refresh and a server restart, and the
review decision resumes the same interrupted run instead of starting a new one.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from alibi.agents import gateway
from alibi.agents.investigator import CASE_DIR, build_investigator, build_single_agent
from alibi.agents.scripted import SCRIPTED_MODEL_ID, ScriptedPolicyModel
from alibi.agents.tools import CaseToolbox
from alibi.config import Settings
from alibi.contracts import AttributionAssessment, InvestigationReport
from alibi.runners import Cancelled, RunContext

_SAFE_NOTE = re.compile(r"[^A-Za-z0-9._-]+")
ROLES = ("lead-investigator", "integrity-auditor", "skeptic")
# investigation mode (product) -> graph architecture
MODE_ARCHITECTURE = {"fast": "single-agent", "specialist": "alibi"}
ARCHITECTURE_ROLES = {"alibi": ROLES, "single-agent": ("single-agent",)}
SYSTEM_LABELS = {
    ("alibi", False): "Specialist review: lead + integrity-auditor + skeptic with deterministic checks (benchmark arm ALIBI)",
    ("alibi", True): "DeepAgents graph (lead + integrity-auditor + skeptic) driven by a scripted fixture policy; "
                     "no model inference",
    ("single-agent", False): "Fast investigation: one agent with deterministic checks, no delegation "
                             "(same configuration as benchmark arm B1+)",
    ("single-agent", True): "DeepAgents single-agent graph driven by a scripted fixture policy; no model inference",
}
_CATEGORY_ORDER = {"incident_allegation": 0, "unresolved": 1, "benign_explanation": 2, "neutral_reconstruction": 3}


class AgentRunner:
    def __init__(self, runner_id: str, settings: Settings, *, architecture: str = "alibi"):
        if architecture not in ARCHITECTURE_ROLES:
            raise ValueError(f"unknown architecture {architecture!r}")
        self.runner_id = runner_id
        self.settings = settings
        self.architecture = architecture  # alibi | single-agent
        self.scripted = runner_id == "agent-fixture"
        self.inference_mode = "SCRIPTED_FIXTURE" if self.scripted else "LIVE_MODEL"
        self.model_id = SCRIPTED_MODEL_ID if self.scripted else settings.lead_model
        self.bound_tools: dict[str, list[str]] = {}

    @classmethod
    def create(cls, runner_id: str, settings: Settings, mode: str | None = None) -> "AgentRunner":
        """mode: fast (one agent) or specialist (lead + auditor + skeptic). None keeps the specialist graph."""
        if mode is not None and mode not in MODE_ARCHITECTURE:
            raise ValueError(f"investigation_mode must be fast or specialist, got {mode!r}")
        if runner_id == "agent-live":
            reason = settings.live_block_reason()
            if reason is not None:
                raise gateway.RuntimeBlocked(f"live inference is BLOCKED: {reason}")
        return cls(runner_id, settings, architecture=MODE_ARCHITECTURE.get(mode or "specialist", "alibi"))

    @property
    def lead_role(self) -> str:
        return ARCHITECTURE_ROLES[self.architecture][0]

    # ------------------------------------------------------------------ construction
    def _record_bind(self, role: str, names: list[str]) -> None:
        self.bound_tools[role] = list(names)

    def _models(self, ledger: gateway.BudgetLedger) -> dict[str, Any]:
        models: dict[str, Any] = {}
        for role in ARCHITECTURE_ROLES[self.architecture]:  # only the models this mode uses are constructed
            if self.scripted:
                inner: Any = ScriptedPolicyModel(role=role)
            else:
                spec = self.settings.lead_model if role in ("lead-investigator", "single-agent") else \
                    (self.settings.subagent_model or self.settings.lead_model)
                inner = gateway.live_chat_model(self.settings, spec or "")
            models[role] = gateway.wrap(inner, ledger, role, on_bind=self._record_bind)
        return models

    def _build(self, ctx: RunContext, toolbox: CaseToolbox, ledger: gateway.BudgetLedger, conn: sqlite3.Connection) -> Any:
        models = self._models(ledger)
        saver = SqliteSaver(conn)
        if self.architecture == "single-agent":
            return build_single_agent(toolbox, model=models["single-agent"], checkpointer=saver)
        return build_investigator(toolbox, lead_model=models["lead-investigator"],
                                  auditor_model=models["integrity-auditor"], skeptic_model=models["skeptic"],
                                  checkpointer=saver)

    def _parts(self, ctx: RunContext) -> tuple[CaseToolbox, gateway.BudgetLedger, sqlite3.Connection]:
        ctx.case_dir.mkdir(parents=True, exist_ok=True)
        ledger = gateway.make_ledger(self.settings, ctx.case_dir / "budget.json", scripted=self.scripted)
        toolbox = CaseToolbox(ctx.store, ctx.manifest, ctx.case_dir / "draft_state.json", emit=ctx.emit,
                              pace=ctx.pace_quiet, on_tool_call=ledger.count_tool_call)
        conn = sqlite3.connect(str(ctx.case_dir / "checkpoints.sqlite"), check_same_thread=False)
        return toolbox, ledger, conn

    def _config(self, ctx: RunContext) -> dict[str, Any]:
        limit = 120 if self.scripted else self.settings.caps.recursion_limit
        return {"configurable": {"thread_id": ctx.case_id}, "recursion_limit": limit}

    # ------------------------------------------------------------------ run until review
    def run(self, ctx: RunContext) -> InvestigationReport:
        t0 = time.perf_counter()
        toolbox, ledger, conn = self._parts(ctx)
        stop_reason: str | None = None
        try:
            graph = self._build(ctx, toolbox, ledger, conn)
            tip = ctx.manifest.operational_context.get("tip", "")
            brief = (f"Evidence bundle {ctx.manifest.bundle_id} is frozen and ready. Tip from the clinic: \"{tip}\" "
                     "Establish what the evidence supports, then submit a report for human review.")
            ctx.emit("agent", {"agent": self.lead_role, "status": "started", "task": "investigate the frozen bundle"})
            pending_tasks: dict[str, str] = {}
            already_ran = bool((graph.get_state(self._config(ctx)).values or {}).get("messages"))
            cancelled = False
            # Idempotent: a case that already has a checkpointed run is never investigated twice
            # (no duplicate tool work, no double-billed model calls). Its saved draft is returned.
            stream = None if already_ran else graph.stream(
                {"messages": [HumanMessage(brief)]}, self._config(ctx), stream_mode="updates")
            try:
                for chunk in stream or []:
                    if ctx.is_cancelled():
                        cancelled = True
                        break
                    for node, update in chunk.items():
                        if node == "__interrupt__" or not isinstance(update, dict):
                            continue
                        for msg in update.get("messages") or []:
                            self._observe(ctx, toolbox, msg, pending_tasks)
            except gateway.BudgetExceeded as exc:
                stop_reason = f"stopped by the budget gateway: {exc}"
            except gateway.ModelRefused as exc:
                stop_reason = f"stopped because {exc}"
            except Exception as exc:  # noqa: BLE001 - keep the partial draft; the failure is reported, not hidden
                if type(exc).__name__ == "GraphRecursionError":
                    stop_reason = "stopped at the turn limit before requesting review"
                else:
                    raise
            finally:
                # Close the graph stream BEFORE the SQLite connection: its background checkpoint
                # writer must finish first, or it would write through a closed connection.
                if stream is not None:
                    stream.close()
            if cancelled or ctx.is_cancelled():
                raise Cancelled()
            state = graph.get_state(self._config(ctx))
            awaiting = bool(state.next)
            if awaiting:
                self._apply_calls_held_by_review(ctx, toolbox, state.values.get("messages") or [])
            if not awaiting and stop_reason is None and not toolbox.finalized:
                stop_reason = "the investigator ended without requesting review"
            self._export_notes(ctx, state.values.get("files") or {})
            self._save_transcript(ctx, state.values.get("messages") or [])
        finally:
            conn.close()
        ctx.emit("agent", {"agent": self.lead_role, "status": "finished",
                           "summary": stop_reason or f"{len(toolbox.findings)} finding(s) submitted for review"})
        wall = max(0.0, time.perf_counter() - t0 - ctx.paced_seconds)
        return self._report(ctx, toolbox, ledger, wall, stop_reason)

    def _apply_calls_held_by_review(self, ctx: RunContext, toolbox: CaseToolbox, messages: list[Any]) -> None:
        """If the model batched report tools with finalize_report, apply them so the draft is complete."""
        last = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if last is None or not any(tc["name"] == "finalize_report" for tc in last.tool_calls):
            return
        role = self.lead_role
        for tc in last.tool_calls:
            if tc["name"] != "finalize_report":
                toolbox.apply_pending(role, tc["name"], dict(tc.get("args") or {}))

    def _observe(self, ctx: RunContext, toolbox: CaseToolbox, msg: Any, pending_tasks: dict[str, str]) -> None:
        """Turn graph updates into audience events. Only real tool calls are reported."""
        if isinstance(msg, AIMessage):
            for tc in msg.tool_calls:
                name, args = tc["name"], tc.get("args") or {}
                if name == "task":
                    agent = str(args.get("subagent_type", "subagent"))
                    pending_tasks[tc["id"]] = agent
                    ctx.emit("agent", {"agent": agent, "status": "started", "task": str(args.get("description", ""))[:240]})
                    ctx.pace_quiet()
                elif name == "write_todos":
                    ctx.emit("todo", {"items": [{"text": str(t.get("content", "")), "status": t.get("status", "pending")}
                                                for t in args.get("todos", [])]})
                    ctx.pace_quiet(0.5)
                elif name in ("write_file", "edit_file"):
                    ctx.emit("note", {"path": str(args.get("file_path", "")),
                                      "preview": str(args.get("content", args.get("new_string", "")))[:400]})
                elif name == "finalize_report":
                    toolbox.note_pending_final(str(args.get("summary", "")), list(args.get("open_questions") or []))
        elif isinstance(msg, ToolMessage) and msg.name == "task":
            agent = pending_tasks.pop(msg.tool_call_id, "subagent")
            text = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
            summary = text[:200]
            try:
                data = json.loads(text)
                if isinstance(data, dict) and "candidates" in data:
                    summary = f"{len(data['candidates'])} candidate finding(s) returned"
                elif isinstance(data, dict) and "verdicts" in data:
                    kept = sum(v.get("verdict") == "keep" for v in data["verdicts"])
                    summary = f"{len(data['verdicts'])} verdict(s): {kept} kept, {len(data['verdicts']) - kept} downgraded"
            except (ValueError, TypeError):
                pass
            ctx.emit("agent", {"agent": agent, "status": "finished", "summary": summary})

    def _report(self, ctx: RunContext, toolbox: CaseToolbox, ledger: gateway.BudgetLedger, wall: float,
                stop_reason: str | None) -> InvestigationReport:
        findings = sorted(toolbox.findings.values(),
                          key=lambda f: (_CATEGORY_ORDER.get(f.category, 9), f.t_start, f.claim_type, f.id))
        final = toolbox.final or {}
        questions = list(final.get("open_questions") or [])
        if stop_reason:
            questions.append(f"Incomplete run: {stop_reason}.")
        usage = ledger.usage(wall_seconds=round(wall, 3))
        if stop_reason and "budget" in stop_reason:
            usage.timed_out = "time cap" in stop_reason
        fixture = self.scripted
        return InvestigationReport(
            report_id=f"rep-{ctx.case_id}", bundle_id=ctx.manifest.bundle_id,
            system_id=("ALIBI-FIXTURE" if fixture else "ALIBI") if self.architecture == "alibi" else
                      ("B1+-FIXTURE" if fixture else "B1+"),
            system_label=SYSTEM_LABELS[(self.architecture, fixture)],
            inference_mode=self.inference_mode, model_id=self.model_id, findings=findings,
            attribution=toolbox.attribution or AttributionAssessment(
                human_identity="not_assessed", statement="The investigator did not submit an attribution assessment."),
            summary=str(final.get("summary") or "The investigator did not write a summary."),
            open_questions=questions, usage=usage,
        )

    # ------------------------------------------------------------------ resume after review
    def resume(self, ctx: RunContext, decision: str) -> None:
        """Deliver the human decision to the interrupted run. A second call is a no-op."""
        toolbox, ledger, conn = self._parts(ctx)
        try:
            graph = self._build(ctx, toolbox, ledger, conn)
            cfg = self._config(ctx)
            if not graph.get_state(cfg).next:
                return  # nothing is waiting: already resumed, or the run ended without requesting review
            if decision == "accept":
                payload: dict[str, Any] = {"decisions": [{"type": "approve"}]}
            else:
                payload = {"decisions": [{"type": "reject", "message": (
                    "The reviewer rejected the report. Do not call any more tools and do not change any finding. "
                    "Reply with one sentence acknowledging the rejection.")}]}
            cfg = {**cfg, "recursion_limit": 12}
            # The time cap measures investigation time, not how long a human took to review:
            # the clock restarts for the short acknowledgement turn. Call and token caps still apply.
            ledger.state["started"] = None
            try:
                graph.invoke(Command(resume=payload), cfg)
            except (gateway.BudgetExceeded, gateway.ModelRefused):
                pass  # the decision was delivered; the model could not acknowledge it
            state = graph.get_state(cfg)
            self._save_transcript(ctx, state.values.get("messages") or [])
        finally:
            conn.close()

    # ------------------------------------------------------------------ artifacts written by trusted code
    @staticmethod
    def _export_notes(ctx: RunContext, files: dict[str, Any]) -> None:
        """Copy the agent's virtual /case files to disk. A virtual write never touched the disk itself."""
        out = ctx.case_dir / "notes"
        for path, data in files.items():
            if not str(path).startswith(CASE_DIR + "/"):
                continue
            name = _SAFE_NOTE.sub("_", str(path)[len(CASE_DIR) + 1:]).strip("._") or "note"
            content = data.get("content", "") if isinstance(data, dict) else str(data)
            if isinstance(content, list):
                content = "\n".join(str(c) for c in content)
            out.mkdir(parents=True, exist_ok=True)
            (out / name[:80]).write_text(str(content)[:200_000], encoding="utf-8")

    @staticmethod
    def _save_transcript(ctx: RunContext, messages: list[Any]) -> None:
        rows = []
        for m in messages:
            row: dict[str, Any] = {"type": type(m).__name__, "name": getattr(m, "name", None)}
            content = m.content if isinstance(m.content, str) else json.dumps(m.content, default=str)
            row["content"] = content[:4000]
            if isinstance(m, AIMessage) and m.tool_calls:
                row["tool_calls"] = [{"name": tc["name"], "args": tc.get("args"), "id": tc.get("id")} for tc in m.tool_calls]
            if isinstance(m, ToolMessage):
                row["tool_call_id"] = m.tool_call_id
            rows.append(row)
        (ctx.case_dir / "transcript.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
