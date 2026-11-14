"""The phase-two paired evaluation: arms, no verifier feedback, declaration, harness, immutability. Offline.

The harness is exercised with stand-in runners. Their output is marked TEST_DOUBLE and is written only
to temporary directories: it is never a model result.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from alibi import bench, calibration, checks, cli, evaluation
from alibi.agents import gateway, investigator
from alibi.agents.runner import AgentRunner
from alibi.agents.tools import CHECK_TOOLS, FAMILY_CHECK_TOOLS, CaseToolbox
from alibi.baselines import run_br
from alibi.config import load_settings
from alibi.episode import load_manifest
from alibi.orchestrator import PRESETS
from alibi.runners import RuntimeBlocked
from alibi.verifier import verify_report

OFFLINE = load_settings({}, dotenv=False)


# ----------------------------------------------------------------- the declaration
def test_declared_matrix_is_four_new_cases_by_four_ai_arms_and_fits_its_ceiling():
    cfg = evaluation.declared_config()
    assert cfg["matrix"]["ai_cells"] == 16 and cfg["matrix"]["runs_per_cell"] == 1
    assert [s["id"] for s in cfg["systems"]] == ["B0", "BR", "B1", "B1+", "B2", "ALIBI"]
    assert cfg["cost_preflight"]["worst_case_usd_total"] <= cfg["cost_preflight"]["category_ceiling_usd"] == 0.75
    assert cfg["verifier_feedback_during_investigation"] is False and cfg["paid_overage_authorized_usd"] == 0
    seeds = {c["seed"] for c in evaluation.CASES}
    used_before = set(range(1, 41)) | {c["seed"] for c in bench.TEST_CASES} | {p["seed"] for p in PRESETS} | \
        {c["seed"] for c in calibration.CALIBRATION_CASES}
    assert len(seeds) == 4 and not seeds & used_before  # the old pilot cases are not reused as if unseen
    kinds = [c["variant"] for c in evaluation.CASES]
    assert kinds == ["incident_evasion", "incident_coverup", "benign_rotation", "benign_approved_transfer"]
    assert json.loads(json.dumps(cfg)) == cfg  # serializable exactly as declared
    # the first-run declaration is a different file and is still intact
    assert bench.check_config() == [] and bench.CONFIG_PATH != evaluation.CONFIG_PATH


def test_arms_without_checks_have_no_check_tool_and_no_prompt_that_mentions_one():
    tools = evaluation._tools_by_arm()
    for arm in ("B1", "B2"):
        for role, names in tools[arm].items():
            assert not set(names) & set(CHECK_TOOLS), (arm, role)
        graph, checks_on = evaluation.AI_ARMS[arm]
        assert checks_on is False
    assert set(CHECK_TOOLS) <= set(tools["B1+"]["single-agent"]) and set(CHECK_TOOLS) <= set(tools["ALIBI"]["integrity-auditor"])
    no_checks = [investigator.lead_prompt(False, False), investigator.auditor_prompt(False),
                 investigator.skeptic_prompt(False), investigator.single_prompt(False, False),
                 investigator.FAMILY_GENERIC_NOTE]
    for text in no_checks:
        for word in list(CHECK_TOOLS) + list(FAMILY_CHECK_TOOLS) + ["deterministic check", "contradiction check", "verifier answers"]:
            assert word not in text, word
    for text in (investigator.lead_prompt(True, False), investigator.single_prompt(True, False)):
        assert "verifier answers immediately" not in text and "does not tell you whether" in text
    # the product prompts are the originals, untouched
    assert investigator.lead_prompt() == investigator.LEAD_PROMPT and investigator.single_prompt() == investigator.SINGLE_AGENT_PROMPT
    assert investigator.auditor_prompt() == investigator.AUDITOR_PROMPT


# ----------------------------------------------------------------- no verifier feedback while investigating
def test_submit_finding_gives_no_verdict_in_the_evaluation_setting(coverup, store_for):
    st, m = store_for(coverup), load_manifest(coverup)
    br = run_br(st, m)
    true = next(f for f in br.findings if f.claim_type == "policy_violating_transfer")
    args = {"claim_type": true.claim_type, "category": true.category, "host": true.host,
            "t_start": true.t_start.isoformat(), "t_end": true.t_end.isoformat(),
            "object_or_session": true.object_or_session, "evidence_ids": true.evidence_ids, "rationale": "x"}
    wrong = {**args, "claim_type": "local_log_removal", "object_or_session": "/var/log/auth.log"}  # same ids, false claim
    box = CaseToolbox(st, m, verify_on_submit=False)
    submit = next(t for t in box.tools_for("single-agent") if t.name == "submit_finding")
    a, b = json.loads(submit.invoke(args)), json.loads(submit.invoke(wrong))
    for out in (a, b):  # a supported and an unsupported claim get the same, verdict-free acknowledgement
        assert set(out) == {"finding_id", "recorded", "references_resolve", "unknown_ids", "note"}
        assert out["recorded"] is True and out["references_resolve"] is True
    assert "does not tell you whether" in submit.description and "verified immediately" not in submit.description
    assert {f.verification_status for f in box.findings.values()} == {"not_checked"}
    ghost = json.loads(submit.invoke({**args, "evidence_ids": ["ev_does_not_exist"], "t_end": true.t_start.isoformat()}))
    assert ghost["references_resolve"] is False and ghost["unknown_ids"] == ["ev_does_not_exist"]
    # the product setting still answers at once
    live_box = CaseToolbox(st, m)
    now = json.loads(next(t for t in live_box.tools_for("single-agent") if t.name == "submit_finding").invoke(wrong))
    assert now["verification_status"] == "unresolved_interpretation"
    # support is decided once, afterwards, by the same verifier for everyone
    from alibi.contracts import InvestigationReport
    rep = verify_report(InvestigationReport(report_id="r", bundle_id=m.bundle_id, system_id="B1", inference_mode="LIVE_MODEL",
                                            model_id="x", findings=list(box.findings.values())), st, m)
    by = {f.claim_type: f for f in rep.findings if f.evidence_ids == true.evidence_ids}
    assert by["policy_violating_transfer"].status == "verified" and by["local_log_removal"].status != "verified"


def test_generic_search_supports_a_fair_investigation_without_checks(coverup, store_for):
    st, m = store_for(coverup), load_manifest(coverup)
    box = CaseToolbox(st, m, checks_enabled=False)
    assert [t.name for t in box.tools_for("single-agent") if t.name.startswith("check_")] == []
    search = next(t for t in box.tools_for("single-agent") if t.name == "search_events")
    copies = json.loads(search.invoke({"source": "collector", "origin_host": "workstation", "file": "/var/log/auth.log", "limit": 50}))
    local = json.loads(search.invoke({"host": "workstation", "file": "/var/log/auth.log", "limit": 50}))
    assert copies["total_matching"] > local["total_matching"] > 0  # the difference an investigator has to explain
    assert all(e["origin_file"] == "/var/log/auth.log" and "seq" in e and "inner_ts" in e for e in copies["events"])
    bulk = json.loads(search.invoke({"source": "flow", "min_bytes_out": 5_000_000}))
    want = {t["flow_event_id"] for t in checks.correlate_transfers(st, m)["transfers"]}
    assert {e["id"] for e in bulk["events"]} == want and all(e["bytes_out"] >= 5_000_000 for e in bulk["events"])
    page = json.loads(search.invoke({"source": "flow", "limit": 5, "offset": 5}))
    first = json.loads(search.invoke({"source": "flow", "limit": 10}))
    assert [e["id"] for e in page["events"]] == [e["id"] for e in first["events"]][5:] and page["offset"] == 5


# ----------------------------------------------------------------- the harness
class _Seq(BaseChatModel):
    """TEST DOUBLE: plays a fixed sequence of tool calls. Not a model."""

    turns: list = []

    @property
    def _llm_type(self) -> str:
        return "sequence-test-double"

    def bind_tools(self, tools, **kw):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kw) -> ChatResult:
        n = sum(isinstance(m, AIMessage) for m in messages)
        if n < len(self.turns):
            calls = [{"name": name, "args": args, "id": f"s-{n}-{i}", "type": "tool_call"} for i, (name, args) in enumerate(self.turns[n])]
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=calls))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done"))])


def _stand_in(arm, settings):
    """Checks arms: the scripted fixture. No-checks arms: a double that searches, then reports nothing found."""
    graph, with_checks = evaluation.AI_ARMS[arm]
    runner = AgentRunner("agent-fixture", settings, architecture=graph, with_checks=with_checks, verify_on_submit=False)
    if not with_checks:
        turns = [[("search_events", {"source": "flow", "min_bytes_out": 5_000_000})],
                 [("submit_attribution", {"statement": "No incident is alleged.", "human_identity": "not_assessed"})],
                 [("finalize_report", {"summary": "nothing established with generic tools", "open_questions": []})]]
        role = runner.lead_role
        runner._models = lambda ledger: {r: gateway.wrap(_Seq(turns=turns), ledger, r)  # type: ignore[method-assign]
                                         for r in (("single-agent",) if graph == "single-agent" else
                                                   ("lead-investigator", "integrity-auditor", "skeptic"))}
        assert role in ("single-agent", "lead-investigator")
    return runner


def test_harness_keeps_every_cell_scores_after_lock_and_never_overwrites(tmp_path):
    case = [{"case_ref": "D01", "variant": "incident_coverup", "seed": 5, "group": "development", "why": "test"},
            {"case_ref": "D02", "variant": "benign_rotation", "seed": 6, "group": "development", "why": "test"}]
    doc = evaluation.run(OFFLINE, cases=case, runner_factory=_stand_in, out_root=tmp_path, suite="unit-test")
    assert doc["inference"] == "TEST_DOUBLE" and doc["model"] is None and doc["verifier_feedback_during_investigation"] is False
    cells = {(r["system_id"], r["case_ref"]): r for r in doc["runs"]}
    assert len(cells) == 12 and {r["status"] for r in doc["runs"]} == {"completed"}
    for arm in ("BR", "B1+", "ALIBI"):  # the checks find all three effects; support was applied after lock
        s = cells[(arm, "D01")]["score"]
        assert (s["step_recall"]["num"], s["step_recall"]["den"]) == (3, 3) and s["false_claims_final"] == 0
        assert cells[(arm, "D02")]["score"]["benign_false_alert"] is False
    for arm in ("B1", "B2"):  # these stand-ins allege nothing: a miss is recorded as a miss
        s = cells[(arm, "D01")]["score"]
        assert (s["step_recall"]["num"], s["step_recall"]["den"]) == (0, 3) and s["proposals_incident"] == 0
    pair = doc["paired"]["checks_effect_one_agent"]  # B1+ minus B1 on the incident case
    assert pair["n"] == 1 and pair["per_case"][0]["difference_in_effects_caught"] == 3 and pair["cases_a_better"] == 1
    assert doc["paired"]["delegation_effect_with_checks"]["cases_equal"] == 1 and doc["system_runs_started"] == 8
    out = tmp_path / doc["run_id"].lower()
    assert (out / "results.json").exists() and len(list((out / "reports").glob("*.report.json"))) == 12
    rep = json.loads((out / "reports" / "D01-B1plus.report.json").read_text())
    assert rep["locked"] is True and rep["system_id"] == "B1+" and rep["attribution"]["review_status"] == "skipped_for_benchmark"
    assert rep["attribution"]["approved_by_human"] is False  # no human approval is fabricated
    assert {f["status"] for f in rep["findings"] if f["category"] == "incident_allegation"} == {"verified"}
    md = evaluation.render_markdown({**doc, "model": "test-double"})
    assert "| D01 |" in md and "3/3" in md and "0/3" in md and "not an accuracy estimate" in md
    # totals over several separately declared suites are a plain sum, and say so
    both = evaluation.combined([doc, doc])
    by = {x["id"]: x for x in both["systems"]}
    assert by["B1+"]["cells"] == 4 and by["B1+"]["aggregate"]["step_recall"] == {"num": 6, "den": 6, "value": 1.0}
    assert by["B1"]["aggregate"]["step_recall"]["num"] == 0 and "Not an accuracy estimate" in both["note"]
    assert evaluation.true_findings_not_accepted(doc) == []  # nothing correct was withdrawn in this stand-in run
    # a correct finding that a skeptic withdrew is found again from the saved report
    rep_file = out / "reports" / "D01-ALIBI.report.json"
    rep = json.loads(rep_file.read_text())
    victim = next(f for f in rep["findings"] if f["claim_type"] == "local_log_removal")
    victim["status"] = "downgraded_by_skeptic"
    rep_file.write_text(json.dumps(rep))
    edited = json.loads(json.dumps(doc))
    cell = next(r for r in edited["runs"] if r["system_id"] == "ALIBI" and r["case_ref"] == "D01")
    cell["score"]["finding_outcomes"] = [{"finding_id": victim["id"], "outcome": "matched_but_not_accepted"}]
    lost = evaluation.true_findings_not_accepted(edited)
    assert lost == [{"suite": "unit-test", "case_ref": "D01", "system_id": "ALIBI", "claim_type": "local_log_removal",
                     "status": "downgraded_by_skeptic", "check_result": "supported_observation", "skeptic_note": lost[0]["skeptic_note"]}]
    summary = evaluation.render_combined([edited])
    assert "Correct findings that did not count" in summary and "downgraded by skeptic" in summary
    (tmp_path / "frozen").mkdir()
    (tmp_path / "frozen" / "x").mkdir()
    assert evaluation.latest(tmp_path)["run_id"] == doc["run_id"]
    with pytest.raises(FileExistsError):
        out.mkdir()  # the result directory exists and a second writer cannot take its place


def test_a_real_run_is_refused_until_every_precondition_holds(tmp_path, monkeypatch):
    with pytest.raises(RuntimeBlocked) as err:
        evaluation.run(OFFLINE, out_root=tmp_path)
    assert "BLOCKED" in str(err.value) and list(tmp_path.iterdir()) == []
    live = {"RUNTIME_MODE": "live", "LIVE_PROVIDER_KIND": "included_credits", "LLM_MAX_USD": "5",
            "ALIBI_SPEND_LEDGER": str(tmp_path / "spend.json"), "LEAD_MODEL": "anthropic:claude-haiku-5-5",
            "LLM_PRICE_IN_PER_MTOK": "0.10", "LLM_PRICE_OUT_PER_MTOK": "0.50", "BENCH_MAX_SYSTEM_RUNS": "16"}
    ok = evaluation.preflight(load_settings(live, dotenv=False))
    assert ok["ok"] is True and ok["cells"] == 16 and ok["worst_case_usd_total"] == 0.72
    cases = [({"LEAD_MODEL": "anthropic:claude-opus-5-5"}, "declared for"),
             ({"LLM_PRICE_IN_PER_MTOK": "4"}, "prices differ"), ({"BENCH_MAX_SYSTEM_RUNS": "0"}, "BENCH_MAX_SYSTEM_RUNS"),
             ({"LLM_EFFORT": "high"}, "effort"), ({"LLM_SPEND_FLOOR_USD": "4.2"}, "development ceiling")]
    for change, expect in cases:
        pre = evaluation.preflight(load_settings({**live, **change}, dotenv=False))
        assert pre["ok"] is False and any(expect in p for p in pre["problems"]), (change, pre["problems"])
    # declared before, never after: once results exist the declaration cannot be rewritten
    monkeypatch.setattr(evaluation, "OUT_ROOT", tmp_path / "suite")
    monkeypatch.setattr(evaluation, "CONFIG_PATH", tmp_path / "config.json")
    assert evaluation.check_config() and evaluation.declare() == tmp_path / "config.json"
    assert evaluation.check_config() == []
    (tmp_path / "suite" / "20260101t000000z").mkdir(parents=True)
    (tmp_path / "suite" / "20260101t000000z" / "results.json").write_text("{}")
    with pytest.raises(RuntimeBlocked):
        evaluation.declare()


def test_first_run_commands_refuse_to_rewrite_their_results(capsys, monkeypatch):
    monkeypatch.setenv("RUNTIME_MODE", "offline")
    before = (bench.RESULTS_PATH.read_bytes(), (bench.PILOT_DIR / "results.json").read_bytes(), bench.CONFIG_PATH.read_bytes())
    assert cli.main(["pilot"]) == 2 and "kept exactly as recorded" in capsys.readouterr().err
    assert cli.main(["bench"]) == 2 and "kept exactly as recorded" in capsys.readouterr().err
    assert cli.main(["bench", "--write-config"]) == 2
    assert cli.main(["bench", "--check"]) == 0
    assert before == (bench.RESULTS_PATH.read_bytes(), (bench.PILOT_DIR / "results.json").read_bytes(), bench.CONFIG_PATH.read_bytes())
    assert bench.V1_VERSIONS["br"] == "1.0.1" and bench.current_versions()["br"] == "1.1.0"


def test_the_results_route_serves_the_same_summary_as_the_committed_result_files(tmp_path):
    """The interface's results table and docs/evaluation-summary.md are computed from the same files."""
    from dataclasses import replace as _replace

    from fastapi.testclient import TestClient

    from alibi.api.app import create_app
    from alibi.config import load_settings
    from alibi.orchestrator import Orchestrator

    settings = _replace(load_settings({}, dotenv=False), runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    got = TestClient(create_app(settings, Orchestrator(settings, pace_s=0.0))).get("/api/benchmark").json()["paired_summary"]
    assert got == json.loads(json.dumps(evaluation.summary()))
    assert [s["suite"] for s in got["suites"]] == [evaluation.SUITE, evaluation.REPLICATION_SUITE]
    assert got["incident_cases"] == 4 and got["benign_cases"] == 2 and got["verifier_feedback_during_investigation"] is False
    assert got["inference"] == "LIVE_MODEL" and "claude-haiku-5-5" in got["model"] and "not an accuracy estimate" in got["note"].lower()
    by = {s["id"]: s for s in got["systems"]}
    recall = {k: (v["aggregate"]["step_recall"]["num"], v["aggregate"]["step_recall"]["den"]) for k, v in by.items()}
    # the committed measurements; a change here means a result file changed, which must never happen silently
    assert recall == {"B0": (4, 16), "BR": (16, 16), "B1": (10, 16), "B1+": (15, 16), "B2": (7, 16), "ALIBI": (12, 16)}
    assert {k: v["censored"] for k, v in by.items()} == {"B0": 0, "BR": 0, "B1": 3, "B1+": 0, "B2": 3, "ALIBI": 0}
    assert all(v["aggregate"]["unsupported_named_attribution"] == 0 for v in by.values())
    assert len(got["correct_findings_not_counted"]) >= 3
    # with no result files there is nothing to show, and the route says so with null
    assert evaluation.summary({s: tmp_path / "none" / s for s in evaluation.SUITES}) is None
