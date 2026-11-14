"""Regression checks for invalid experiments and evidence-free audit claims."""

from copy import deepcopy
import json

import pytest

from scripts.daniel.audit import audit_requests
from scripts.daniel.results import PROTOCOL, ROOT, Results, validate

OUTPUT = ROOT / "benchmarks/worker-lab-v1/daniel/offline"


@pytest.fixture()
def document():
    return json.loads((OUTPUT / "results.json").read_text())


def test_committed_results_have_complete_operational_and_scored_denominators(document):
    summary = validate(Results.model_validate(document), OUTPUT)
    assert summary["runs"] == 12
    assert summary["conditions"]["BR"]["supported_effects"] == 2
    assert summary["conditions"]["BR"]["observable_effects"] == 3
    assert summary["conditions"]["BR"]["benign_scored_cases"] == 4
    assert summary["conditions"]["B0"]["false_allegations"] == 4
    assert summary["conditions"]["B0"]["false_accepted_allegations"] == 0
    assert summary["conditions"]["BR"]["false_accepted_allegations"] == 0


@pytest.mark.parametrize("status", ["failed", "refused", "capped", "cancelled"])
def test_stopped_run_counts_in_operations_without_becoming_a_scored_negative(document, status):
    row = document["runs"][0]
    row.update(status=status, stop_reason="injected regression outcome", report=None, score=None)
    group = validate(Results.model_validate(document), OUTPUT)["conditions"]["B0"]
    assert group["runs"] == 6 and group["scored"] == 5 and group["unscored"] == 1
    assert group["statuses"][status] == 1
    assert group["benign_scored_cases"] == 3


def test_unresolved_report_is_retained_with_its_own_status(document):
    document["runs"][0].update(status="unresolved", stop_reason="incomplete evidence")
    summary = validate(Results.model_validate(document), OUTPUT)
    assert summary["conditions"]["B0"]["statuses"]["unresolved"] == 1


@pytest.mark.parametrize("change, message", [
    (lambda d: d["runs"].pop(), "coverage"),
    (lambda d: d["runs"].append(deepcopy(d["runs"][0])), "duplicate run"),
    (lambda d: d["runs"][1].update(run_id=d["runs"][0]["run_id"]), "duplicate run"),
    (lambda d: d["runs"][0].update(condition="unknown"), "coverage"),
    (lambda d: d["runs"][0].update(evidence_sha256="0" * 64), "evidence"),
    (lambda d: d["runs"][0].update(manifest_sha256="0" * 64), "manifest"),
    (lambda d: d["runs"][1].update(execution_id="another-execution"), "identity"),
    (lambda d: d["runs"][0]["report"].update(sha256="0" * 64), "report hash"),
    (lambda d: d["runs"][0]["report"].update(path="../outside.json"), "leaves"),
    (lambda d: d["runs"][0]["report"].update(scored_at=d["runs"][0]["report"]["locked_at"]), "before scoring"),
    (lambda d: d["runs"][0]["versions"].update(scorer="unknown"), "scorer"),
    (lambda d: d["runs"][0]["versions"].update({"src/alibi/baselines.py": "0" * 64}), "version"),
    (lambda d: d["runs"][0]["provenance"].update(inference="LIVE_MODEL"), "model identity"),
    (lambda d: d["runs"][0]["provenance"].pop("evidence"), "evidence"),
    (lambda d: d["runs"][0]["used"].update(cost_usd=float("nan")), "finite"),
    (lambda d: d["runs"][0]["used"].update(calls=-1), "greater"),
    (lambda d: d["runs"][0]["used"].update(calls=1), "model usage"),
    (lambda d: d["runs"][0]["used"].update(seconds=100), "resource limits"),
    (lambda d: d["runs"][0]["score"].update(false_allegations=0), "score differs"),
    (lambda d: d["runs"][0].update(status="failed"), "needs a reason"),
    (lambda d: d["runs"][0].update(ended_at="2020-01-01T00:00:00+00:00"), "ends before"),
    (lambda d: d["runs"][0].update(started_at="2020-01-01T00:00:00+00:00"), "predates protocol"),
    (lambda d: d.update(protocol_sha256="0" * 64), "protocol hash"),
])
def test_invalid_results_are_rejected(document, change, message):
    change(document)
    with pytest.raises(ValueError, match=message):
        validate(Results.model_validate(document), OUTPUT)


def test_permission_change_requires_new_execution_and_parent_lineage(document):
    """Use the declared runtime cells with failed outcomes to test lineage only."""
    protocol = json.loads(PROTOCOL.read_text())
    document["batch_id"] = "runtime-controls"
    rows = []
    for cell in protocol["batches"]["runtime-controls"]["cells"]:
        row = deepcopy(document["runs"][0])
        profile = protocol["conditions"][cell["condition"]]
        execution = f"{cell['case_id']}-{cell['condition']}"
        parent = f"{cell['case_id']}-permission-export" if cell["condition"] == "permission-log" else None
        row.update(**cell, run_id=execution, execution_id=execution, root_execution_id=parent or execution,
                   parent_execution_id=parent, world_seed=protocol["cases"][cell["case_id"]]["seed"],
                   permission=profile["permission"], allowed=profile["limits"], tape_sha256="1" * 64,
                   versions={**protocol["versions"]["live_sources"], "scorer": protocol["versions"]["scorer"]},
                   status="failed", stop_reason="test fixture failure after capture", report=None, score=None)
        row["provenance"].update(execution="COUNTERFACTUAL_REPLAY" if parent else "FRESH",
                                 fault_policy=protocol["runtime"]["fault_policy"])
        rows.append(row)
    document["runs"] = rows
    assert validate(Results.model_validate(document), OUTPUT)["runs"] == 7
    broken = deepcopy(document)
    broken["runs"][1]["execution_id"] = broken["runs"][0]["execution_id"]
    with pytest.raises(ValueError, match="reused execution"):
        validate(Results.model_validate(broken), OUTPUT)
    document["runs"][1]["parent_execution_id"] = "unrelated-parent"
    with pytest.raises(ValueError, match="lineage"):
        validate(Results.model_validate(document), OUTPUT)


def trace_call(name, args, result, identity):
    return [
        {"type": "AIMessage", "content": "", "tool_calls": [{"id": identity, "name": name, "args": args}]},
        {"type": "ToolMessage", "tool_call_id": identity, "content": result},
    ]


def test_audit_requires_successful_evidence_before_revision_and_later_note_read():
    event = "ev_123456abcdef"
    messages = trace_call("write_todos", {"todos": [{"content": "Read the logs"}]}, "ok", "plan-1")
    messages += trace_call("search_events", {}, json.dumps({"events": [{"id": event}]}), "observe-1")
    messages += trace_call("write_todos", {"todos": [{"content": f"Resolve the conflict in {event}"}]}, "ok", "plan-2")
    messages += trace_call("write_file", {"file_path": "/case/notes.md", "content": event}, "ok", "write-1")
    requests = [{"actor": "lead", "messages": deepcopy(messages)}]
    messages += trace_call("read_file", {"file_path": "/case/notes.md"}, event, "read-1")
    requests.append({"actor": "lead", "messages": messages})
    audit = audit_requests(requests, {event}, [])
    assert len(audit["evidence_linked_plan_revisions"]) == len(audit["later_notes_reads"]) == 1
    messages[-1]["content"] = '{"error":"file unavailable"}'
    assert audit_requests(requests, {event}, [])["later_notes_reads"] == []
    assert audit_requests(requests, set(), [])["evidence_linked_plan_revisions"] == []


def test_audit_rejects_truth_in_structured_inputs_and_detects_private_canary():
    payload = [{"actor": "lead", "messages": [{"type": "HumanMessage", "content": '{"transition":{"worker":"W1"}}'}]}]
    assert audit_requests(payload, set(), [])["input_separation"] == "failed"
    payload[0]["messages"][0]["content"] = "Do not use private answers."
    assert audit_requests(payload, set(), [])["input_separation"] == "passed"
    assert audit_requests(payload, set(), ["private answers"])["input_separation"] == "failed"
    assert audit_requests([], set(), [])["input_separation"] == "failed"
