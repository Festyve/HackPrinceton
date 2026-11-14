"""The remaining case families through the product paths: presets, runners, tools, fixture, experiment. Offline."""

from __future__ import annotations

import json
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from alibi import checks_families
from alibi.agents.tools import FAMILY_CHECK_TOOLS, CaseToolbox, check_object_format
from alibi.api.app import create_app
from alibi.baselines import run_br
from alibi.config import load_settings
from alibi.episode import load_manifest
from alibi.evidence.store import EvidenceStore
from alibi.orchestrator import PRESETS, Orchestrator

FAMILY_PRESETS = {"evasion": ("inside-job", "incident"), "maintenance-control": ("inside-job", "benign"),
                  "records-heist": ("records-heist", "incident"), "records-control": ("records-heist", "benign"),
                  "cold-chain": ("cold-chain", "incident"), "cold-chain-control": ("cold-chain", "benign")}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("families")
    settings = replace(load_settings({}, dotenv=False), runs_dir=tmp / "runs", sealed_dir=tmp / "sealed")
    orch = Orchestrator(settings, pace_s=0.0)
    return settings, orch, TestClient(create_app(settings, orch))


def _wait(c, cid, want="awaiting_review", timeout=90.0):
    end = time.time() + timeout
    while time.time() < end:
        v = c.get(f"/api/cases/{cid}").json()
        if v["case"]["state"] in (want, "failed"):
            assert v["case"]["state"] == want, v["case"]
            return v
        time.sleep(0.05)
    raise AssertionError(cid)


def _run(c, preset, runner="deterministic", mode=None):
    body = {"preset_id": preset, "runner": runner}
    if mode:
        body["investigation_mode"] = mode
    cid = c.post("/api/cases", json=body).json()["case"]["case_id"]
    return cid, _wait(c, cid)


def _claims(report, category="incident_allegation"):
    return sorted((f["claim_type"], f["host"], f["object_or_session"]) for f in report["findings"] if f["category"] == category)


@pytest.mark.parametrize("preset", sorted(FAMILY_PRESETS))
def test_every_family_preset_runs_end_to_end_with_the_deterministic_runner(env, preset):
    _, orch, c = env
    card, kind = FAMILY_PRESETS[preset]
    assert preset in {p["id"] for p in c.get("/api/presets").json()["presets"]}
    cid, v = _run(c, preset)
    assert v["case"]["card_id"] == card and v["card"]["id"] == card and v["card"]["tip"]
    assert "_variant" not in json.dumps(v) and v["reveal"] is None
    paths = orch._paths(cid)
    with EvidenceStore(paths.db) as st:
        br = run_br(st, load_manifest(paths))
    assert _claims(v["report"]) == sorted((f.claim_type, f.host, f.object_or_session) for f in br.findings
                                           if f.category == "incident_allegation")
    allegations = _claims(v["report"])
    assert bool(allegations) == (kind == "incident")
    assert all(f["status"] == "verified" for f in v["report"]["findings"] if f["category"] == "incident_allegation")
    tools = {e["data"]["tool"] for e in c.get(f"/api/cases/{cid}/events.json").json()["events"] if e["type"] == "tool"}
    assert set(FAMILY_CHECK_TOOLS) <= tools  # the family checks ran and are in the activity trace
    c.post(f"/api/cases/{cid}/review", json={"decision": "accept"})
    reveal = c.post(f"/api/cases/{cid}/reveal").json()["reveal"]
    outcomes = [o["outcome"] for o in reveal["score"]["effect_outcomes"]]
    assert reveal["truth"]["case_kind"] == kind and "missed" not in outcomes
    assert reveal["truth"]["plan_label"].startswith("Scripted scenario")  # no model chose these steps
    if kind == "incident":
        assert outcomes.count("caught") >= 1 and reveal["score"]["false_claims_final"] == 0
    else:
        assert reveal["score"]["benign_false_alert"] is False
    if preset == "evasion":  # cleared shell history leaves nothing an investigator can see: recorded, not scored
        assert outcomes.count("unobservable") == 1 and reveal["score"]["unobservable_effects"] == 1


@pytest.mark.parametrize("preset, mode", [("records-heist", "specialist"), ("cold-chain", "fast"), ("evasion", "fast"),
                                          ("cold-chain-control", "specialist")])
def test_the_scripted_fixture_reaches_the_same_findings_on_family_cases(env, preset, mode):
    _, _, c = env
    _, det = _run(c, preset)
    cid, v = _run(c, preset, runner="agent-fixture", mode=mode)
    assert v["case"]["labels"]["inference"] == "SCRIPTED_FIXTURE"
    assert _claims(v["report"]) == _claims(det["report"])
    assert _claims(v["report"], "benign_explanation") == _claims(det["report"], "benign_explanation")
    assert {f["status"] for f in v["report"]["findings"] if f["category"] == "incident_allegation"} <= {"verified"}
    if FAMILY_PRESETS[preset][1] == "incident":
        c.post(f"/api/cases/{cid}/review", json={"decision": "accept"})
        outcomes = [o["outcome"] for o in c.post(f"/api/cases/{cid}/reveal").json()["reveal"]["score"]["effect_outcomes"]]
        assert "missed" not in outcomes and "caught" in outcomes


def test_first_run_bundles_keep_their_tools_vocabulary_and_prompts(env, coverup, store_for):
    from alibi.agents import investigator as inv

    st = store_for(coverup)
    box = CaseToolbox(st, load_manifest(coverup))
    assert box.family is False and inv.family_addendum(box) == ""
    names = {role: [t.name for t in box.tools_for(role)] for role in ("lead-investigator", "integrity-auditor", "skeptic", "single-agent")}
    assert names["integrity-auditor"] == ["get_case_brief", "search_events", "count_events", "get_events",
                                          "check_local_vs_collector", "check_transfer_sessions", "check_account_vs_person"]
    assert not any(t in FAMILY_CHECK_TOOLS for ts in names.values() for t in ts)
    submit = next(t for t in box.tools_for("single-agent") if t.name == "submit_finding")
    enum = submit.args_schema.model_json_schema()["properties"]["claim_type"]["enum"]
    assert enum == ["local_log_removal", "policy_violating_transfer", "data_staging", "collection_gap",
                    "retention_explained_absence", "policy_consistent_transfer", "account_use", "other"]
    assert "fridge-01" not in submit.description
    assert checks_families.observations(st, load_manifest(coverup)) == {}


def test_family_bundles_get_the_extra_checks_only_where_checks_exist(env):
    _, orch, c = env
    cid, _ = _run(c, "cold-chain")
    paths = orch._paths(cid)
    with EvidenceStore(paths.db) as st:
        m = load_manifest(paths)
        box = CaseToolbox(st, m)
        assert box.family is True
        assert set(FAMILY_CHECK_TOOLS) <= {t.name for t in box.tools_for("integrity-auditor")}
        assert set(FAMILY_CHECK_TOOLS) <= {t.name for t in box.tools_for("question")}
        assert not set(FAMILY_CHECK_TOOLS) & {t.name for t in box.tools_for("lead-investigator")}
        bare = CaseToolbox(st, m, checks_enabled=False)  # arms B1 and B2: no check of any kind
        assert not [t.name for t in bare.tools_for("single-agent") if t.name.startswith("check_")]
        # what a tool returns is exactly what the baseline templating reads, after a JSON round trip
        obs = checks_families.observations(st, m)
        assert json.loads(json.dumps(obs)) == obs
        for tool, key in FAMILY_CHECK_TOOLS.items():
            out = json.loads(next(t for t in box.tools_for("single-agent") if t.name == tool).invoke({}))
            assert out == obs[key], tool
        submit = next(t for t in box.tools_for("single-agent") if t.name == "submit_finding")
        assert "sensor_stream_discrepancy" in submit.args_schema.model_json_schema()["properties"]["claim_type"]["enum"]
        assert "fridge-01" in submit.description


def test_object_formats_for_the_new_incident_claims():
    ok = [("second_host_session", "records#382"), ("forwarding_stopped", "log-forwarder"),
          ("timestamp_alteration", "/home/a/Downloads/x.db"), ("sensor_stream_discrepancy", "fridge-01")]
    for claim, obj in ok:
        check_object_format(claim, "incident_allegation", obj)
    bad = [("second_host_session", "ssh from the workstation"), ("forwarding_stopped", "the forwarder service"),
           ("timestamp_alteration", "x.db backdated"), ("sensor_stream_discrepancy", "Fridge 01 readings")]
    for claim, obj in bad:
        with pytest.raises(ValueError):
            check_object_format(claim, "incident_allegation", obj)
    check_object_format("temperature_excursion", "neutral_reconstruction", "anything goes for a note")


def test_withholding_the_reference_logger_makes_the_temperature_claim_unestablishable(env):
    _, _, c = env
    cid, view = _run(c, "cold-chain")
    ref = [s["source_id"] for s in view["manifest"]["sources"] if s["source"] == "reference"]
    assert len(ref) == 1
    made = c.post(f"/api/cases/{cid}/source-experiments", json={"excluded_source_ids": ref, "client_token": "cc-1"}).json()
    exp = c.get(f"/api/cases/{made['child_case_id']}/source-experiment").json()
    row = next(x for x in exp["comparison"]["claims"] if x["claim_type"] == "sensor_stream_discrepancy")
    assert row["change"] == "loses_support" and row["child"]["state"] == "cannot_be_established_here"
    assert any("reference" in x for x in exp["comparison"]["coverage"]["child"]["limits"]) or "reference" in row["reason"]
    assert {p["id"] for p in PRESETS} >= set(FAMILY_PRESETS)
