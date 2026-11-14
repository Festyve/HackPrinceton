"""An investigation's trace, derived from what was recorded while it ran.

Everything here is computed from the case's event log: real tool calls, real delegations, the plan as the
investigator wrote it, and its case-file writes and reads. Nothing is inferred about what a model was
thinking. Summaries are the summaries the tools returned.

`behaviors` answers narrow, checkable questions (was there a plan before any examination, was work delegated,
did the plan's content change after a result, was the case file written and read back later) from the order
of recorded events. "After" means "later in the recorded order"; it does not claim a cause.
"""

from __future__ import annotations

from typing import Any

TRACE_VERSION = "trace/1"
EXAMINATION_TOOLS = ("check_", "search_events", "get_events", "count_events")


def _text(items: list[dict[str, Any]]) -> list[str]:
    return [str(i.get("text", "")).strip() for i in items if str(i.get("text", "")).strip()]


def investigation_trace(events: list[dict[str, Any]], lead_roles: tuple[str, ...] = ("lead-investigator", "single-agent")
                        ) -> dict[str, Any]:
    spans: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    delegations: list[dict[str, Any]] = []
    open_by_agent: dict[str, dict[str, Any]] = {}
    root: dict[str, Any] | None = None
    last_result: dict[str, Any] | None = None
    resumes: list[dict[str, Any]] = []
    usage: dict[str, Any] | None = None
    for e in events:
        kind, d, seq, ts = e.get("type"), e.get("data") or {}, e.get("seq"), e.get("ts")
        if kind == "agent":
            agent = str(d.get("agent"))
            if d.get("status") == "started":
                span = {"span_id": f"a{seq}", "parent_id": None if agent in lead_roles else (root or {}).get("span_id"),
                        "kind": "run" if agent in lead_roles else "delegation", "actor": agent,
                        "task": d.get("task"), "start_seq": seq, "start": ts, "end_seq": None, "end": None,
                        "status": "running", "result_summary": None}
                spans.append(span)
                open_by_agent[agent] = span
                if agent in lead_roles and root is None:
                    root = span
                elif agent not in lead_roles:
                    delegations.append(span)
            elif agent in open_by_agent:
                span = open_by_agent.pop(agent)
                span.update(end_seq=seq, end=ts, status="finished", result_summary=d.get("summary"))
                if agent not in lead_roles:
                    last_result = {"seq": seq, "what": f"{agent} returned", "summary": d.get("summary")}
        elif kind == "tool":
            agent = str(d.get("agent"))
            parent = open_by_agent.get(agent) or root
            spans.append({"span_id": f"t{seq}", "parent_id": (parent or {}).get("span_id"), "kind": "tool", "actor": agent,
                          "tool": d.get("tool"), "arguments": d.get("args"), "result_summary": d.get("result_summary"),
                          "evidence_ids": list(d.get("evidence_ids") or []), "status": "ok" if d.get("ok", True) else "error",
                          "start_seq": seq, "start": ts, "ms": d.get("ms")})
            last_result = {"seq": seq, "what": f"{agent} · {d.get('tool')}", "summary": d.get("result_summary")}
        elif kind == "todo":
            items = list(d.get("items") or [])
            before = _text(plans[-1]["items"]) if plans else []
            now = _text(items)
            plans.append({"seq": seq, "t": ts, "items": items,
                          "added": [t for t in now if t not in before] if plans else [],
                          "removed": [t for t in before if t not in now],
                          "after": last_result})
        elif kind == "note":
            files.append({"seq": seq, "t": ts, "op": "edit" if d.get("op") == "edit_file" else "write",
                          "path": d.get("path"), "preview": d.get("preview")})
        elif kind == "note_read":
            files.append({"seq": seq, "t": ts, "op": "read", "path": d.get("path")})
        elif kind == "stage" and d.get("name") == "resume":
            resumes.append({"seq": seq, "t": ts, **(d.get("info") or {})})
        elif kind == "usage":
            usage = d.get("usage")
    examined = [s for s in spans if s["kind"] == "tool" and str(s.get("tool", "")).startswith(EXAMINATION_TOOLS)]
    first_look = min((s["start_seq"] for s in examined + delegations), default=None)
    revisions = [{"seq": p["seq"], "added": p["added"], "removed": p["removed"], "after": p["after"]}
                 for p in plans[1:] if p["added"] or p["removed"]]
    writes = [f for f in files if f["op"] in ("write", "edit")]
    reads_back = [f for f in files if f["op"] == "read" and any(w["path"] == f["path"] and w["seq"] < f["seq"] for w in writes)]
    after_resume = [s for s in spans if s["kind"] == "tool" and resumes and s["start_seq"] > resumes[0]["seq"]]
    return {
        "version": TRACE_VERSION,
        "note": ("Built from the recorded event log. Summaries are what the tools returned, not a model's thoughts. "
                 "'After' is the recorded order and does not claim a cause."),
        "spans": spans, "plan": plans, "case_file": files, "usage": usage,
        "behaviors": {
            "planned_before_examining": bool(plans) and (first_look is None or plans[0]["seq"] < first_look),
            "delegations": [{"span_id": s["span_id"], "to": s["actor"], "task": s["task"], "status": s["status"],
                             "result_summary": s["result_summary"],
                             "tool_calls": sum(1 for t in spans if t["kind"] == "tool" and t["parent_id"] == s["span_id"])}
                            for s in delegations],
            "plan_revisions": revisions,
            "case_file": {"writes": len(writes), "reads_after_a_write": len(reads_back),
                          "paths": sorted({str(f["path"]) for f in files})},
            "resumed": {"times": len(resumes), "resumes": resumes, "tool_calls_after_resume": len(after_resume)},
        },
    }


__all__ = ["TRACE_VERSION", "investigation_trace"]
