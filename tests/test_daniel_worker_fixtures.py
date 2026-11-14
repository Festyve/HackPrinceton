"""Validate frozen worker-lab inputs and the evidence available to the investigator."""

import json
import re
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from alibi.agents import investigator
from alibi.agents.tools import CaseToolbox
from alibi.api.app import create_app
from alibi.baselines import run_br
from alibi.capture.manifest import COLLECTOR, LOCAL
from alibi.config import load_settings
from alibi.episode import episode_paths, load_manifest, sha256_file
from alibi.evidence.store import EvidenceStore
from alibi.importing import load_capture
from alibi.orchestrator import Orchestrator
from alibi.verifier import verify_report


ROOT = Path(__file__).parent / "fixtures" / "daniel" / "worker-lab"
EVIDENCE = ROOT / "evidence"
SCORER = ROOT / "scorer-only" / "expectations.json"
CASE_IDS = tuple(sorted(path.name for path in EVIDENCE.iterdir() if path.is_dir()))
AUTH = "records/var/log/auth.log"
GATEWAY = "gateway/var/log/syslog"
POLICY = "policy/var/log/syslog"
SCHEDULER = "scheduler/var/log/syslog"
TAP = "tap/flows.jsonl"
ARTIFACTS = {AUTH, COLLECTOR, GATEWAY, LOCAL, POLICY, SCHEDULER, TAP}
TIP = "Review this evidence; establish what it supports."
PRIVATE_MARKERS = re.compile(
    r"scorer-only|expectations\.json|alibi-worker-fixture-scorer|fault_attempts|incident_claims|"
    r"control_evidence|unresolved_worker|supported_worker|copy_report|reroute_delivery|remove_local_record"
)


@pytest.fixture()
def opened_case(tmp_path):
    settings = replace(load_settings({}, dotenv=False), runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    orchestrator = Orchestrator(settings, pace_s=0)

    def open_case(case_id):
        case = orchestrator.import_case(EVIDENCE / case_id, runner_id="deterministic")
        paths = episode_paths(case.case_id, settings.runs_dir, settings.sealed_dir)
        return case, paths, load_manifest(paths)

    with TestClient(create_app(settings, orchestrator)) as client:
        yield client, open_case


def invoke(tools, name, **arguments):
    result = json.loads(tools[name].invoke(arguments))
    assert "error" not in result, result
    return result


def fields(row):
    """Read the key/value fields present in a returned syslog record."""
    return dict(re.findall(r"(\w+)=([^\s]+)", row["raw"]))


def test_scorer_index_covers_exactly_the_neutral_evidence_directories():
    index = json.loads(SCORER.read_text())
    assert index["format"] == "alibi-worker-fixture-scorer/1"
    assert set(index["cases"]) == set(CASE_IDS)
    assert len({case["raw_bundle_sha256"] for case in index["cases"].values()}) == len(CASE_IDS)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_fixture_is_frozen_citable_and_scorer_data_stays_outside_investigator_inputs(case_id, opened_case, monkeypatch):
    client, open_case = opened_case
    private = json.loads(SCORER.read_text())["cases"][case_id]
    source = EVIDENCE / case_id
    capture, files = load_capture(source)
    case, paths, manifest = open_case(case_id)
    url = f"/api/cases/{case.case_id}"

    assert re.fullmatch(r"wl-[a-f0-9]{4}", case_id)
    assert capture.capture_id == case_id
    assert capture.notes == []
    assert set(capture.operational_context) <= {"accounts", "change_records", "logging_policy", "network_inventory", "transfer_policy"}
    assert {file.relative_to(source).as_posix() for file in source.rglob("*") if file.is_file()} == {
        "capture.json", *ARTIFACTS,
    }
    assert set(files) == ARTIFACTS
    assert manifest.raw_bundle_sha256 == private["raw_bundle_sha256"]
    assert sha256_file(source / "capture.json") == private["capture_manifest_sha256"]
    assert capture.evidence_origin == manifest.evidence_origin == "SIM"
    assert all(artifact.origin == "SIM" for artifact in capture.artifacts)
    witness_paths = {COLLECTOR, GATEWAY, POLICY, SCHEDULER, TAP}
    assert {src.artifact for src in manifest.sources if src.tamper_exposure == "independent_witness"} == witness_paths
    assert manifest.normalization_errors == []
    assert not paths.sealed.exists()

    public_files = {}
    for artifact, file in files.items():
        original = file.read_bytes()
        assert (paths.raw / artifact).read_bytes() == original
        public_files[artifact] = original.decode().splitlines()

    view_response = client.get(url)
    assert view_response.status_code == 200
    view = view_response.json()
    assert view["case"]["title"] == f"Imported evidence · {case_id}"
    assert view["case"]["seed"] is None and view["case"]["scored"] is False
    assert view["reveal"] is None
    assert view["manifest"]["operational_context"]["tip"] == TIP
    assert client.post(f"{url}/reveal").status_code == 409
    for artifact in ("expectations.json", "../../scorer-only/expectations.json"):
        response = client.get(f"{url}/evidence/raw", params={"artifact": artifact})
        assert response.status_code == 400

    with EvidenceStore(paths.db) as store:
        events = store.scan()
        refs = {(event.artifact_ref.artifact, event.artifact_ref.line): event for event in events}
        assert len(events) == len(refs) == sum(map(len, public_files.values()))
        citations = [*private["control_evidence"], *private["attribution"]["evidence"]]
        for claim in private["incident_claims"]:
            citations += claim["evidence"]
            assert len({ref["artifact"] for ref in claim["evidence"]}) >= 2
        for ref in citations:
            artifact = ref["artifact"]
            if "metadata" in ref:
                metadata = next(src for src in manifest.sources if src.artifact == artifact)
                assert ref["metadata"] == "known_gaps" and metadata.known_gaps
                continue
            event = refs[(artifact, ref["line"])]
            assert event.raw == public_files[artifact][ref["line"] - 1]
            line_at_offset = (paths.raw / artifact).read_bytes()[event.artifact_ref.byte_offset:].split(b"\n", 1)[0]
            assert event.raw.encode() == line_at_offset
            response = client.get(f"{url}/evidence/raw", params={"artifact": artifact, "line": ref["line"], "radius": 0})
            assert response.status_code == 200
            assert response.json()["lines"] == [{"n": ref["line"], "text": event.raw, "focus": True}]

        # Intercept the model builders and invoke their real bound evidence tools.
        # This exercises the prompt/tool boundary without a provider or a test-only prompt.
        monkeypatch.setattr(investigator, "create_deep_agent", lambda **kwargs: kwargs)
        toolbox = CaseToolbox(store, manifest, verify_on_submit=False)
        single = investigator.build_single_agent(toolbox, model=None, checkpointer=None)
        specialist = investigator.build_investigator(
            toolbox, lead_model=None, auditor_model=None, skeptic_model=None, checkpointer=None,
        )
        inputs = [view_response.text, (source / "capture.json").read_text(), *map(str, public_files.values())]
        for agent in (single, specialist, *specialist["subagents"]):
            tools = {tool.name: tool for tool in agent["tools"]}
            brief = invoke(tools, "get_case_brief")
            assert brief["tip"] == TIP
            rows = invoke(tools, "search_events", host="scheduler", limit=10)["events"]
            assert len(rows) >= 2
            inputs.extend((agent["system_prompt"], json.dumps(brief), json.dumps(rows)))
        assert not any(PRIVATE_MARKERS.search(value) for value in inputs)


@pytest.mark.parametrize("case_id, log_status, policy_status", [
    ("wl-14c8", "consistent", "approved"),
    ("wl-5ba1", "consistent", None),
    ("wl-73e0", "unexplained_local_absence", "not_approved"),
    ("wl-8d26", "inconclusive", "approved"),
])
def test_existing_checks_distinguish_direct_transfer_controls(case_id, log_status, policy_status, opened_case):
    _, open_case = opened_case
    _, paths, manifest = open_case(case_id)
    expected = json.loads(SCORER.read_text())["cases"][case_id]
    expected_claims = {(claim["claim_type"], claim["object"]) for claim in expected["incident_claims"]}
    with EvidenceStore(paths.db) as store:
        toolbox = CaseToolbox(store, manifest)
        tools = {tool.name: tool for tool in toolbox.tools_for("single-agent")}
        [comparison] = invoke(tools, "check_local_vs_collector")["files"]
        assert comparison["status"] == log_status
        transfers = invoke(tools, "check_transfer_sessions")["transfers"]
        assert [transfer["policy_status"] for transfer in transfers] == ([] if policy_status is None else [policy_status])
        report = verify_report(run_br(store, manifest), store, manifest)
        allegations = [finding for finding in report.findings if finding.category == "incident_allegation"]
        assert {(finding.claim_type, finding.object_or_session) for finding in allegations} == expected_claims
        assert all(finding.status == "verified" for finding in allegations)
        assert report.attribution.named_person_accused is None

        if log_status == "inconclusive":
            [gap] = comparison["inconclusive_local_absence"]
            assert "local sink paused during maintenance" in gap["reason"]
            assert comparison["unexplained_local_absence"] == []
            # The two missing-line cases contain the same local and forwarded bytes.
            for artifact in (LOCAL, COLLECTOR):
                assert (EVIDENCE / case_id / artifact).read_bytes() == (EVIDENCE / "wl-73e0" / artifact).read_bytes()
        if log_status == "unexplained_local_absence":
            [absent] = comparison["unexplained_local_absence"]
            # Link the transfer request to the scheduler through the retained record's lease.
            retained = fields({"raw": absent["line"]})
            [job] = invoke(tools, "search_events", host="scheduler", text_contains=f"lease={retained['lease']}")["events"]
            assert fields(job)["worker"] == expected["attribution"]["worker_id"]
            assert fields(job)["account"] == report.attribution.account_used == expected["attribution"]["account"]
            assert retained["request"] == expected["attribution"]["request"]
        if policy_status is None:
            [attempt] = invoke(tools, "search_events", source="app", action="export_bulk")["events"]
            assert fields(attempt)["status"] == "403"
            assert fields(attempt)["bytes"] == "0"
            assert all(fault["outcome"] == "denied" for fault in expected["fault_attempts"])


def test_dependent_lead_needs_gateway_join_and_shared_account_does_not_identify_worker(opened_case):
    harder, control = "wl-39f2", "wl-c461"
    hard_manifest, hard_files = load_capture(EVIDENCE / harder)
    control_manifest, control_files = load_capture(EVIDENCE / control)
    assert set(hard_files) == set(control_files)
    differing_paths = {path for path in hard_files if hard_files[path].read_bytes() != control_files[path].read_bytes()}
    assert differing_paths == {GATEWAY}
    assert hard_manifest.operational_context == control_manifest.operational_context
    _, open_case = opened_case
    expected = json.loads(SCORER.read_text())["cases"]

    for case_id in (harder, control):
        _, paths, manifest = open_case(case_id)
        with EvidenceStore(paths.db) as store:
            tools = {tool.name: tool for tool in CaseToolbox(store, manifest).tools_for("single-agent")}
            queue = invoke(tools, "search_events", source="app", action="queue_report")["events"]
            assert len(queue) == 2
            flows = invoke(tools, "search_events", source="flow")["events"]
            deliveries = {flow["sport"]: flow for flow in (json.loads(event["raw"]) for event in flows)}
            assert len(deliveries) == 2
            violations = {}
            for queued in queue:
                app = fields(queued)
                [gateway] = invoke(tools, "search_events", host="gateway", text_contains=f"request={app['request']}")["events"]
                delivery = deliveries[int(fields(gateway)["src_port"])]
                [policy] = invoke(tools, "search_events", host="policy", text_contains=f"dataset={app['dataset']}")["events"]
                assert {"worker", "lease", "session"}.isdisjoint(app)
                assert {"worker", "lease", "session"}.isdisjoint(fields(gateway))
                if delivery["dst"] not in fields(policy)["allowed_destinations"].split(","):
                    violations[app["request"]] = f"{delivery['dst']}:{delivery['dport']}"

            assert {queued["actor"] for queued in queue} == {"svc-delivery"}
            account = queue[0]["actor"]
            assignments = invoke(tools, "search_events", host="scheduler", text_contains=f"account={account}")["events"]
            logins = invoke(tools, "search_events", source="auth", actor=account, action="login")["events"]
            assert {fields(event)["worker"] for event in assignments} == {"W-42", "W-58"}
            assert {event["session_id"] for event in logins} == {"records#32", "records#33"}
        assert set(violations.values()) == {claim["object"] for claim in expected[case_id]["incident_claims"]}
        assert set(violations) == ({expected[harder]["attribution"]["request"]} if case_id == harder else set())

    assert expected[harder]["attribution"]["status"] == "unresolved_worker"
    assert expected[harder]["attribution"]["worker_id"] is None
    assert expected[harder]["fault_attempts"][0]["worker_id"] == "W-58"
    assert expected[control]["incident_claims"] == []
