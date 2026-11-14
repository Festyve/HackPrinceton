"""M6: the benchmark pipeline, its frozen configuration and its honesty guards."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from alibi import bench
from alibi.agents.runner import AgentRunner
from alibi.baselines import run_br
from alibi.config import load_settings
from alibi.episode import load_manifest
from alibi.runners import RunContext

DEV_CASES = [
    {"case_ref": "D01", "variant": "incident_plain", "seed": 12, "group": "dev"},
    {"case_ref": "D02", "variant": "incident_coverup", "seed": 13, "group": "dev"},
    {"case_ref": "D03", "variant": "benign_rotation", "seed": 14, "group": "dev"},
]


def test_frozen_config_matches_the_code_and_separates_the_splits():
    assert bench.check_config() == []
    cfg = json.loads(bench.CONFIG_PATH.read_text())
    test_seeds, demo = set(cfg["seed_splits"]["test"]), set(cfg["seed_splits"]["demo"])
    assert len(test_seeds) == 12 and not (test_seeds & demo) and min(test_seeds) > 40  # dev seeds are 1-40
    groups = [c["variant"] for c in cfg["cases"]]
    assert groups.count("incident_plain") == 4 and groups.count("incident_coverup") == 4
    assert {v for v in groups if v.startswith("benign")} == {"benign_rotation", "benign_approved_transfer",
                                                             "benign_remote_login", "benign_collection_gap"}
    assert cfg["paid_overage_authorized_usd"] == 0 and len(cfg["ai_pilot_case_refs"]) == 4


def test_config_drift_is_detected(tmp_path, monkeypatch):
    drifted = tmp_path / "cfg.json"
    data = bench.frozen_config()
    data["matching"]["tolerance_s"] = 9999  # someone loosened the scorer after the fact
    drifted.write_text(json.dumps(data))
    monkeypatch.setattr(bench, "CONFIG_PATH", drifted)
    problems = bench.check_config()
    assert problems and "matching" in problems[0]


def test_suite_runs_offline_and_leaves_ai_arms_unrun_not_zero(tmp_path):
    settings = load_settings({})
    doc = bench.run_offline_suite(settings, cases=DEV_CASES, work_dir=tmp_path)
    assert doc["runtime"]["model_calls_made"] == 0 and doc["runtime"]["live_inference"] == "BLOCKED"
    by = {s["id"]: s for s in doc["systems"]}
    assert by["B0"]["status"] == by["BR"]["status"] == "RUN" and by["BR"]["completed"] == 3
    for ai in ("B1", "B1+", "B2", "ALIBI"):
        assert by[ai]["status"] == "NOT_RUN" and by[ai]["status_detail"] == "NOT RUN — runtime unavailable"
        assert by[ai]["aggregate"] is None and by[ai]["n_cases"] == 0  # unrun, never a zero score
    assert len(doc["runs"]) == 6 and all(r["status"] == "completed" for r in doc["runs"])
    assert {tuple(sorted(c["system_order"])) for c in doc["cases"]} == {("B0", "BR")}
    agg = by["BR"]["aggregate"]
    assert agg["step_recall"] == {"num": 5, "den": 5, "value": 1.0}
    assert agg["benign_false_alert"]["den"] == 1 and agg["llm_calls"] == 0
    # every displayed number traces to a saved per-run score with the scorer version
    for r in doc["runs"]:
        assert r["score"]["scorer_version"] == doc["scorer_version"] and r["score"]["review_status"] == "skipped_for_benchmark"
        assert r["score"]["approved_by_human"] is False
    md = bench.render_markdown(doc)
    assert "NOT RUN — runtime unavailable" in md and "not real-world forensic accuracy" in md
    assert "| **ALIBI** |" in md and "N/A means not applicable" in md


def test_aggregation_counts_cases_not_events(tmp_path):
    doc = bench.run_offline_suite(load_settings({}), cases=DEV_CASES, work_dir=tmp_path)
    b0 = next(s for s in doc["systems"] if s["id"] == "B0")["aggregate"]
    assert b0["incident_cases_fully_reconstructed"]["den"] == 2 and b0["coverup_detected"]["den"] == 1
    assert b0["raw_incident_proposals"] > b0["final_precision"]["den"]  # raw noise is reported, not hidden
    paired = doc["paired"]
    assert paired["n"] == 2 and paired["cases_a_better"] + paired["cases_equal"] + paired["cases_b_better"] == 2


def test_a_scripted_fixture_can_never_be_recorded_as_an_ai_result(coverup, store_for):
    st = store_for(coverup)
    m = load_manifest(coverup)
    ctx = RunContext(case_id="t-bench-guard", store=st, manifest=m, case_dir=coverup.case / "bench-guard",
                     settings=load_settings({}), emit=lambda t, d: None)
    fixture = AgentRunner("agent-fixture", load_settings({})).run(ctx)
    with pytest.raises(ValueError) as err:
        bench.validate_ai_run("ALIBI", fixture)
    assert "SCRIPTED_FIXTURE" in str(err.value) and "only LIVE_MODEL" in str(err.value)
    with pytest.raises(ValueError):
        bench.validate_ai_run("B1+", run_br(st, m))  # nor a deterministic baseline
    live_like = fixture.model_copy(update={"inference_mode": "LIVE_MODEL", "model_id": None})
    with pytest.raises(ValueError):
        bench.validate_ai_run("ALIBI", live_like)  # a live run without model metadata is not acceptable either


def test_committed_results_are_consistent_with_their_own_runs():
    if not bench.RESULTS_PATH.exists():
        pytest.skip("benchmark has not been run yet")
    doc = json.loads(bench.RESULTS_PATH.read_text())
    assert doc["suite"] == "offline-v1" and len(doc["cases"]) == 12 and doc["runtime"]["model_calls_made"] == 0
    from alibi.contracts import Score

    for s in doc["systems"]:
        mine = [Score.model_validate(r["score"]) for r in doc["runs"] if r["system_id"] == s["id"]]
        if s["status"] == "RUN":
            assert json.loads(json.dumps(bench.aggregate(mine))) == s["aggregate"], s["id"]  # no hand-entered headline number
        else:
            assert mine == [] and s["aggregate"] is None
    for r in doc["runs"]:
        assert (bench.REPO_ROOT / r["report_file"]).exists()


# ----------------------------------------------------------------- AI pilot plumbing (no model involved)
class _LiveDouble:
    """TEST DOUBLE. Relabels a fixture run as LIVE_MODEL so the pilot plumbing can be exercised.
    It exists only inside this test, writes only to a temp directory, and is not an AI result."""

    def __init__(self, system_id, settings):
        from alibi.bench import PILOT_SYSTEMS

        self.inner = AgentRunner("agent-fixture", settings, architecture="alibi")
        self.system_id = system_id
        assert system_id in PILOT_SYSTEMS

    def run(self, ctx):
        rep = self.inner.run(ctx)
        return rep.model_copy(update={"inference_mode": "LIVE_MODEL", "model_id": "test-double:not-a-model"})


def test_ai_pilot_is_refused_without_a_runtime_or_a_run_budget(tmp_path):
    from alibi.runners import RuntimeBlocked

    with pytest.raises(RuntimeBlocked) as err:
        bench.run_ai_pilot(load_settings({}), work_dir=tmp_path)
    assert "BLOCKED" in str(err.value)
    live_no_budget = load_settings({"RUNTIME_MODE": "live", "LEAD_MODEL": "x:y", "LIVE_PROVIDER_KIND": "local"})
    with pytest.raises(RuntimeBlocked) as err:
        bench.run_ai_pilot(live_no_budget, runner_factory=_LiveDouble, work_dir=tmp_path)
    assert "BENCH_MAX_SYSTEM_RUNS is 0" in str(err.value)


def test_ai_pilot_refuses_to_record_a_fixture_as_an_ai_run(tmp_path):
    settings = replace(load_settings({}), bench_max_system_runs=8)
    with pytest.raises(ValueError) as err:
        bench.run_ai_pilot(settings, runner_factory=lambda sid, s: AgentRunner("agent-fixture", s), work_dir=tmp_path)
    assert "only LIVE_MODEL runs count as AI results" in str(err.value)


def test_ai_pilot_plumbing_respects_the_system_run_budget(tmp_path):
    settings = replace(load_settings({}), bench_max_system_runs=3)
    doc = bench.run_ai_pilot(settings, runner_factory=_LiveDouble, work_dir=tmp_path)
    assert doc["suite"] == "ai-pilot-v1" and len(doc["cases"]) == 4 and len(doc["runs"]) == 8
    assert doc["system_runs_started"] == 3
    assert sum(r["status"] == "completed" for r in doc["runs"]) == 3
    assert sum(r["status"] == "unrun_budget" for r in doc["runs"]) == 5  # unrun is recorded, never silently dropped
    assert {s["id"] for s in doc["systems"]} == {"B1+", "ALIBI"}
    assert all(r["score"] is None for r in doc["runs"] if r["status"] != "completed")
    assert not (bench.PILOT_DIR / "results.json").exists()  # nothing from a test double reaches the repository


def test_benchmark_view_merges_pilot_rows_only_when_real_pilot_results_exist(tmp_path):
    if not bench.RESULTS_PATH.exists():
        pytest.skip("benchmark has not been run yet")
    base = bench.combined_results(pilot_path=tmp_path / "missing.json")
    assert {s["id"]: s["status"] for s in base["systems"]}["ALIBI"] == "NOT_RUN" and "ai_pilot" not in base
    pilot = {"suite": "ai-pilot-v1", "run_id": "r", "generated_at": "t", "git_commit": "c", "paired": {}, "system_runs_started": 1,
             "notes": ["pilot note"], "runs": [{"system_id": "ALIBI", "case_ref": "T01", "status": "completed", "score": None}],
             "systems": [{"id": "ALIBI", "status": "RUN", "label": "x", "aggregate": {}, "model_id": "m"},
                         {"id": "B1+", "status": "NOT_RUN", "status_detail": "no run completed", "aggregate": None}]}
    f = tmp_path / "pilot.json"
    f.write_text(json.dumps(pilot))
    merged = bench.combined_results(pilot_path=f)
    status = {s["id"]: s["status"] for s in merged["systems"]}
    assert status["ALIBI"] == "RUN" and status["B1+"] == "NOT_RUN" and status["B2"] == "NOT_RUN"
    assert next(s for s in merged["systems"] if s["id"] == "B1+")["status_detail"] == "NOT RUN — runtime unavailable"
    assert merged["ai_pilot"]["run_id"] == "r" and "pilot note" in merged["notes"]
