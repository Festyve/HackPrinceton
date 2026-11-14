"""Fast and specialist investigation modes (docs/next-run/CONTINUE.md section 2). Offline: scripted fixture only."""

from __future__ import annotations

import json
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from alibi.agents import gateway
from alibi.agents.runner import AgentRunner
from alibi.api.app import create_app
from alibi.baselines import run_br
from alibi.config import load_settings
from alibi.episode import load_manifest
from alibi.evidence.store import EvidenceStore
from alibi.orchestrator import Orchestrator
from alibi.runners import RuntimeBlocked, resolve_mode


@pytest.fixture()
def env(tmp_path):
    settings = replace(load_settings({}, dotenv=False), runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    orch = Orchestrator(settings, pace_s=0.0)
    return settings, orch, TestClient(create_app(settings, orch))


def _wait(client, cid, want=("awaiting_review",), timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        view = client.get(f"/api/cases/{cid}").json()
        if view["case"]["state"] in want + ("failed",):
            assert view["case"]["state"] in want, view["case"]
            return view
        time.sleep(0.05)
    raise AssertionError(f"case {cid} never reached {want}")


def test_default_mode_is_fast_for_a_live_model_and_specialist_for_the_fixture():
    assert resolve_mode("agent-live", None) == "fast"
    assert resolve_mode("agent-live", "specialist") == "specialist"
    assert resolve_mode("agent-fixture", None) == "specialist"  # existing demos and recordings are unchanged
    assert resolve_mode("agent-fixture", "fast") == "fast"
    assert resolve_mode("deterministic", "fast") is None  # no agent, so no mode
    with pytest.raises(ValueError):
        resolve_mode("agent-live", "turbo")


def test_fast_mode_runs_one_agent_end_to_end_and_keeps_its_mode_across_a_restart(env):
    settings, orch, c = env
    caps = c.get("/api/runtime").json()["capabilities"]
    assert caps["investigation_modes"]["available"] == ["fast", "specialist"]
    assert caps["investigation_modes"]["default"] == "specialist" and caps["live_model"]["configured"] is False
    view = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "agent-fixture",
                                      "investigation_mode": "fast"}).json()
    cid = view["case"]["case_id"]
    assert view["case"]["investigation_mode"] == "fast"
    v = _wait(c, cid)
    assert v["case"]["labels"]["investigation_mode_label"] == "Fast investigation · one agent"
    assert v["case"]["labels"]["inference"] == "SCRIPTED_FIXTURE"  # a fixture stays labeled a fixture in either mode
    report = v["report"]
    assert report["system_id"] == "B1+-FIXTURE" and "single-agent graph" in report["system_label"]
    events = c.get(f"/api/cases/{cid}/events.json").json()["events"]
    tools = [e["data"] for e in events if e["type"] == "tool"]
    assert {t["agent"] for t in tools} == {"single-agent"}  # no specialists took part
    assert not [e for e in events if e["type"] == "agent" and e["data"]["agent"] in ("integrity-auditor", "skeptic")]
    assert {"check_local_vs_collector", "check_transfer_sessions", "check_account_vs_person", "submit_finding",
            "submit_attribution"} <= {t["tool"] for t in tools}
    budget = json.loads((settings.runs_dir / cid / "case" / "budget.json").read_text())
    assert set(budget["by_role"]) == {"single-agent"} and budget["llm_calls"] == 0  # scripted turns, no model call
    # the same findings as the deterministic baseline on the same evidence
    paths = orch._paths(cid)
    with EvidenceStore(paths.db) as st:
        br = run_br(st, load_manifest(paths))
    key = lambda f: (f["claim_type"] if isinstance(f, dict) else f.claim_type,  # noqa: E731
                     f["host"] if isinstance(f, dict) else f.host)
    assert sorted(key(f) for f in report["findings"]) == sorted(key(f) for f in br.findings)
    assert {f["status"] for f in report["findings"] if f["category"] == "incident_allegation"} == {"verified"}

    # a new server process: the saved mode decides how the paused run is resumed
    again = Orchestrator(settings, pace_s=0.0)
    assert again.record(cid).investigation_mode == "fast"
    c2 = TestClient(create_app(settings, again))
    locked = c2.post(f"/api/cases/{cid}/review", json={"decision": "accept"}).json()
    assert locked["case"]["state"] == "report_locked" and locked["report"]["locked"] is True
    after = [e["data"]["tool"] for e in c2.get(f"/api/cases/{cid}/events.json").json()["events"] if e["type"] == "tool"]
    assert after[-1] == "finalize_report" and after.count("submit_attribution") == 1
    scored = c2.post(f"/api/cases/{cid}/reveal").json()
    outcomes = [o["outcome"] for o in scored["reveal"]["score"]["effect_outcomes"]]
    assert outcomes and set(outcomes) == {"caught"}


def test_specialist_mode_is_still_the_full_graph_and_a_benign_case_alleges_nothing_in_fast_mode(env):
    _, _, c = env
    cid = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "agent-fixture",
                                     "investigation_mode": "specialist"}).json()["case"]["case_id"]
    v = _wait(c, cid)
    assert v["report"]["system_id"] == "ALIBI-FIXTURE" and v["case"]["investigation_mode"] == "specialist"
    agents = {e["data"]["agent"] for e in c.get(f"/api/cases/{cid}/events.json").json()["events"] if e["type"] == "agent"}
    assert {"lead-investigator", "integrity-auditor", "skeptic"} <= agents
    benign = c.post("/api/cases", json={"preset_id": "sealed-control", "runner": "agent-fixture",
                                        "investigation_mode": "fast"}).json()["case"]["case_id"]
    b = _wait(c, benign)
    assert not [f for f in b["report"]["findings"] if f["category"] == "incident_allegation"]
    assert b["report"]["attribution"]["human_identity"] == "not_assessed"


def test_mode_is_validated_and_ignored_by_the_runner_without_an_agent(env):
    _, _, c = env
    assert c.post("/api/cases", json={"preset_id": "hero-coverup", "investigation_mode": "turbo"}).status_code == 422
    det = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "deterministic",
                                     "investigation_mode": "fast"}).json()
    assert det["case"]["investigation_mode"] is None
    assert det["case"]["labels"]["investigation_mode_label"] == "Deterministic checks · no agent"
    # the recorded specialist runs are listed with the mode they were recorded in
    replays = {r["id"]: r for r in c.get("/api/presets").json()["replays"]}
    assert replays["hero-coverup-live-opus-5-5"]["investigation_mode"] == "specialist"
    assert replays["hero-coverup-live-opus-5-5"]["inference_mode"] == "RECORDED_MODEL"


LIVE = {"RUNTIME_MODE": "live", "LIVE_PROVIDER_KIND": "included_credits", "LEAD_MODEL": "anthropic:test-model",
        "LLM_MAX_USD": "5", "LLM_PRICE_IN_PER_MTOK": "1", "LLM_PRICE_OUT_PER_MTOK": "5"}


def test_fast_mode_constructs_exactly_one_model(tmp_path, monkeypatch):
    built: list[str] = []

    def fake(settings, spec):
        built.append(spec)
        from alibi.agents.scripted import ScriptedPolicyModel
        return ScriptedPolicyModel(role="single-agent")  # never invoked here; construction is what is counted

    monkeypatch.setattr(gateway, "live_chat_model", fake)
    settings = load_settings({**LIVE, "ALIBI_SPEND_LEDGER": str(tmp_path / "spend.json")}, dotenv=False)
    ledger = gateway.make_ledger(settings, None, scripted=False)
    fast = AgentRunner.create("agent-live", settings, "fast")
    assert list(fast._models(ledger)) == ["single-agent"] and built == ["anthropic:test-model"]
    built.clear()
    full = AgentRunner.create("agent-live", settings, "specialist")
    assert list(full._models(ledger)) == ["lead-investigator", "integrity-auditor", "skeptic"] and len(built) == 3
    assert fast.inference_mode == full.inference_mode == "LIVE_MODEL"
    with pytest.raises(ValueError):
        AgentRunner.create("agent-live", settings, "turbo")
    assert not (tmp_path / "spend.json").exists()  # building runners spends and reserves nothing


def test_a_case_is_never_finished_by_a_different_model_than_the_one_that_ran_it(env):
    settings, orch, c = env
    cid = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "agent-fixture",
                                     "investigation_mode": "fast"}).json()["case"]["case_id"]
    _wait(c, cid)
    status = settings.runs_dir / cid / "status.json"
    saved = json.loads(status.read_text())
    saved.update(runner_id="agent-live", model_id="anthropic:the-model-that-ran-it", inference_mode="LIVE_MODEL")
    status.write_text(json.dumps(saved))  # as if a live model had run it, and .env was then pointed elsewhere
    locked = c.post(f"/api/cases/{cid}/review", json={"decision": "accept"}).json()
    assert locked["case"]["state"] == "report_locked"  # the human decision still locks the report
    skipped = [e for e in c.get(f"/api/cases/{cid}/events.json").json()["events"]
               if e["type"] == "stage" and e["data"]["name"] == "review_resume"]
    assert skipped and "no longer configured" in skipped[0]["data"]["info"]["note"]
    with pytest.raises(RuntimeBlocked):
        orch._same_model_or_refuse(orch.record(cid))


def test_calibration_harness_checks_the_whole_workflow_offline_and_never_overwrites(tmp_path):
    """The harness itself, driven by the scripted fixture. This is not a model result and is not stored as one."""
    from alibi import calibration

    settings = load_settings({}, dotenv=False)
    doc = calibration.run_calibration(settings, mode="fast", runner_id="agent-fixture", out_root=tmp_path)
    assert doc["passed"] is True and doc["runner"] == "agent-fixture" and doc["estimated_cost_usd"] == 0.0
    assert doc["criteria"] == {c: True for c in calibration.CRITERIA}
    incident, benign = doc["cases"]
    assert incident["effects"] == {"caught": 3, "missed": 0, "total": 3} and incident["unresolved_ids"] == []
    assert benign["checks"]["benign_abstention"] is True and benign["effects"]["total"] == 0
    assert all(r["inference_mode"] == "SCRIPTED_FIXTURE" for r in doc["cases"])
    out = tmp_path / doc["result_dir"].rsplit("/", 1)[1]
    assert (out / "calibration.json").exists() and (out / "reports" / "CAL-INCIDENT.report.json").exists()
    assert {c["seed"] for c in calibration.CALIBRATION_CASES} <= set(range(1, 41))  # development seeds only
    with pytest.raises(RuntimeBlocked):  # a live calibration is refused while live inference is blocked
        calibration.run_calibration(settings, mode="fast", out_root=tmp_path)
