"""Audit full captured model inputs and completed tool messages.

The input is an ordered stream per actor. Proposed tool calls alone cannot
prove a successful note write, read, or evidence-led plan revision.
"""

from __future__ import annotations

import json
import re
from typing import Any

EVENT_ID = re.compile(r"\bev_[0-9a-f]{12}\b")
PRIVATE_KEYS = {"operatortrue", "transition", "transitionplanned", "faultattempts", "incidentclaims",
                "scoreronly", "answerkey", "actiontape", "isincident", "casekind", "groundtruth", "variant"}


def private_fields(value: Any, path: str = "input") -> list[str]:
    """Inspect structured payloads and embedded JSON without matching denial prose."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if re.sub(r"[^a-z0-9]", "", key.lower()) in PRIVATE_KEYS:
                found.append(f"{path}.{key}")
            found.extend(private_fields(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(private_fields(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        try:
            embedded = json.loads(value)
        except (ValueError, TypeError):
            return found
        if isinstance(embedded, (dict, list)):
            found.extend(private_fields(embedded, path))
    return found


def audit_requests(requests: list[dict], evidence_ids: set[str], forbidden_values: list[str]) -> dict:
    """Check the exact messages that reached a model, preserving actor-local order.

Repeated message history is deduplicated per actor. An evidence-linked revision
requires changed todo content citing an earlier successful evidence result.
Notes retrieval requires a later successful read containing a saved evidence ID.
These mechanical checks document sequence, while semantic usefulness still
requires review of the saved payloads.
"""
    leaks = []
    seen = set()
    states = {}
    revisions, reads, attribution = [], [], []
    for request_index, request in enumerate(requests):
        actor = request["actor"]
        state = states.setdefault(actor, {"observed": set(), "calls": {}, "plan": None, "notes": {}})
        serialized = json.dumps(request, sort_keys=True)
        leaks.extend(private_fields(request, f"request[{request_index}]"))
        leaks.extend(f"request[{request_index}] contains private marker" for value in forbidden_values if value and value in serialized)
        for message in request["messages"]:
            identity = (actor, json.dumps(message, sort_keys=True))
            if identity in seen:
                continue
            seen.add(identity)
            if message["type"] == "AIMessage":
                for call in message.get("tool_calls", []):
                    state["calls"][call["id"]] = {**call, "observed_before": set(state["observed"])}
            if message["type"] != "ToolMessage":
                continue
            call = state["calls"].get(message.get("tool_call_id"))
            if call is None:
                continue
            content = message.get("content", "")
            text = content if isinstance(content, str) else json.dumps(content)
            try:
                decoded = json.loads(text)
            except ValueError:
                decoded = {}
            failed = message.get("status") == "error" or isinstance(decoded, dict) and "error" in decoded
            if failed or text.lstrip().lower().startswith("error"):
                continue
            name, args = call["name"], call.get("args", {})
            observed = set(EVENT_ID.findall(text)) & evidence_ids
            before = call["observed_before"]
            if name in ("search_events", "get_events", "check_local_vs_collector", "check_transfer_sessions", "task"):
                state["observed"].update(observed)
            if name == "write_todos":
                current = json.dumps(args.get("todos", []), sort_keys=True)
                references = set(EVENT_ID.findall(current)) & before
                if state["plan"] and current != state["plan"] and references:
                    revisions.append({"actor": actor, "request": request_index, "evidence_ids": sorted(references)})
                state["plan"] = current
            if name in ("write_file", "edit_file"):
                path = args.get("file_path")
                saved = args.get("content", args.get("new_string", ""))
                state["notes"][path] = {"request": request_index, "ids": set(EVENT_ID.findall(saved)) & before}
            if name == "read_file":
                note = state["notes"].get(args.get("file_path"))
                if note and request_index > note["request"] and observed & note["ids"]:
                    reads.append({"actor": actor, "request": request_index, "path": args["file_path"],
                                  "evidence_ids": sorted(observed & note["ids"])})
            if name == "submit_attribution":
                references = set(args.get("supporting_evidence_ids", []))
                attribution.append({"actor": actor, "request": request_index,
                                    "all_citations_previously_observed": bool(references) and references <= before,
                                    "worker_field_present": bool(args.get("worker_id")),
                                    "evidence_ids": sorted(references)})
    return {
        "requests": len(requests), "actors": sorted(states), "leaks": sorted(set(leaks)),
        "input_separation": "passed" if requests and not leaks else "failed",
        "evidence_linked_plan_revisions": revisions, "later_notes_reads": reads,
        "attribution_submissions": attribution,
        "limitations": ["Ordering and reference checks require semantic review of the cited records.",
                        "An account attribution does not establish an independent worker link."],
    }
