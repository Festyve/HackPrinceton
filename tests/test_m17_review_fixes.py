"""Regression tests for defects an independent review found in the second-run routes. Offline, no model."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alibi import orchestrator as orch_mod
from alibi.agents import gateway
from alibi.api.app import create_app
from alibi.config import load_settings
from alibi.episode import load_answer_key
from alibi.orchestrator import REPLAY_DIR, Orchestrator
from tests.test_m9_questions import LIVE, _answer, _fake
from tests.test_m14_designer import GOOD, _FakeDesigner


@pytest.fixture()
def env(tmp_path):
    settings = replace(load_settings({}, dotenv=False), runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    orch = Orchestrator(settings, pace_s=0.0)
    return settings, orch, TestClient(create_app(settings, orch))


def _wait(c, cid, want="awaiting_review", timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        v = c.get(f"/api/cases/{cid}").json()
        if v["case"]["state"] in (want, "failed"):
            assert v["case"]["state"] == want, v["case"]
            return v
        time.sleep(0.05)
    raise AssertionError(cid)


def _collector(view):
    return [s["source_id"] for s in view["manifest"]["sources"] if s["source"] == "collector"]


def _derive(c, cid, ids, token, **more):
    return c.post(f"/api/cases/{cid}/source-experiments",
                  json={"excluded_source_ids": ids, "client_token": token, "runner": "deterministic", **more})


# ----------------------------------------------------------------- a derived view shares the original's answer
@pytest.mark.parametrize("parent_stage", ["frozen", "awaiting_review"])
def test_a_derived_view_cannot_be_unsealed_while_the_original_report_can_still_change(env, parent_stage):
    _, orch, c = env
    pid = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "deterministic",
                                     "autostart": parent_stage != "frozen"}).json()["case"]["case_id"]
    parent = _wait(c, pid, parent_stage)
    kid = _derive(c, pid, _collector(parent), "x", autostart=True).json()["child_case_id"]
    _wait(c, kid)
    assert c.post(f"/api/cases/{kid}/review", json={"decision": "accept"}).status_code == 200
    early = c.post(f"/api/cases/{kid}/reveal")
    assert early.status_code == 409 and "Lock the original case's report first" in early.json()["error"]
    key = load_answer_key(orch._paths(pid))
    leaked = early.text + json.dumps(c.get(f"/api/cases/{kid}").json()) + json.dumps(c.get(f"/api/cases/{kid}/events.json").json())
    for secret in (key.canary, "incident_coverup", "operator_true", "step_recall"):
        assert secret not in leaked
    assert c.get(f"/api/cases/{kid}").json()["case"]["state"] == "report_locked" and c.get(f"/api/cases/{kid}").json()["reveal"] is None
    assert c.get(f"/api/cases/{kid}/reveal-export").status_code == 409
    # once the original's report is locked, the derived view unseals as before, with both recall figures
    if parent_stage == "frozen":
        c.post(f"/api/cases/{pid}/investigate")
        _wait(c, pid)
    c.post(f"/api/cases/{pid}/review", json={"decision": "accept"})
    done = c.post(f"/api/cases/{kid}/reveal")
    assert done.status_code == 200 and done.json()["reveal"]["truth"]["variant"] == "incident_coverup"
    assert done.json()["reveal"]["source_experiment"]["scoring"] is not None


def test_a_derived_view_whose_original_was_reset_can_still_be_unsealed(env):
    _, _, c = env
    pid = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "deterministic"}).json()["case"]["case_id"]
    kid = _derive(c, pid, _collector(_wait(c, pid)), "x", autostart=True).json()["child_case_id"]
    _wait(c, kid)
    c.post(f"/api/cases/{kid}/review", json={"decision": "accept"})
    c.post(f"/api/cases/{pid}/reset")  # no unlocked report is left to protect
    assert c.post(f"/api/cases/{kid}/reveal").status_code == 200


# ----------------------------------------------------------------- a second process does not "recover" live work
_PROBE = """
import sys
from dataclasses import replace
from pathlib import Path
from alibi.config import load_settings
from alibi.orchestrator import Orchestrator
base = Path(sys.argv[1])
s = replace(load_settings({}, dotenv=False), runs_dir=base / "runs", sealed_dir=base / "sealed")
o = Orchestrator(s, pace_s=0.0)
print("owns" if o.owns_runs else "guest", len(o.list_cases()))
"""


def _probe(base: Path) -> str:
    out = subprocess.run([sys.executable, "-c", _PROBE, str(base)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-600:]
    return out.stdout.strip()


def test_a_command_run_beside_a_server_does_not_mark_its_running_work_as_failed(tmp_path):
    settings = replace(load_settings({**LIVE, "ALIBI_SPEND_LEDGER": str(tmp_path / "spend.json")}, dotenv=False),
                       runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    orch = Orchestrator(settings, pace_s=0.0)
    slow = Orchestrator(settings, pace_s=0.3)  # same process, same directory; the cases it runs take a while
    assert orch.owns_runs and slow.owns_runs
    c, c2 = TestClient(create_app(settings, orch)), TestClient(create_app(settings, slow))
    ready = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "deterministic"}).json()["case"]["case_id"]
    _wait(c, ready)
    # a question whose answer is still being produced, and a second case in the middle of its investigation
    model = _fake([_answer(status="insufficient_evidence", answer="Nothing establishes that.")])
    model.hold = threading.Event()
    orch.qa_model_factory = lambda *a, **k: model
    pending = c.post(f"/api/cases/{ready}/questions", json={"question": "why?", "client_token": "q"}).json()
    assert pending["status"] == "pending"
    running = c2.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "agent-fixture"}).json()["case"]["case_id"]
    end = time.time() + 30
    while time.time() < end and c2.get(f"/api/cases/{running}").json()["case"]["state"] != "investigating":
        time.sleep(0.05)
    assert c2.get(f"/api/cases/{running}").json()["case"]["state"] == "investigating"
    try:
        # what `alibi cases`, `alibi export` or `alibi ask` do: open the same directory from another process
        assert _probe(tmp_path) == "guest 2"
        assert c2.get(f"/api/cases/{running}").json()["case"]["state"] == "investigating"
        assert c2.get(f"/api/cases/{running}").json()["case"]["error"] is None
        assert c.get(f"/api/cases/{ready}/questions/{pending['question_id']}").json()["status"] == "pending"
    finally:
        model.hold.set()
    end = time.time() + 20
    while time.time() < end and c.get(f"/api/cases/{ready}/questions/{pending['question_id']}").json()["status"] == "pending":
        time.sleep(0.05)
    assert c.get(f"/api/cases/{ready}/questions/{pending['question_id']}").json()["status"] == "insufficient_evidence"
    done = _wait(c2, running, timeout=120)
    assert done["case"]["error"] is None
    seqs = [json.loads(ln)["seq"] for ln in (orch._paths(running).root / "events.jsonl").read_text().splitlines() if ln.strip()]
    assert len(seqs) == len(set(seqs))


def test_the_directory_is_owned_again_once_its_owner_has_exited_and_a_restart_still_recovers(tmp_path):
    assert _probe(tmp_path) == "owns 0"  # that process has ended, so its lock is gone
    settings = replace(load_settings({}, dotenv=False), runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    first = Orchestrator(settings, pace_s=0.0)
    assert first.owns_runs and not list((tmp_path / "runs").glob("*.lock"))  # the lock file is not among the cases
    c = TestClient(create_app(settings, first))
    cid = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "deterministic", "autostart": False}).json()["case"]["case_id"]
    rec = first._load(cid)
    rec.state = "investigating"  # as a crash in the middle of a run leaves it
    first._save(rec)
    again = Orchestrator(settings, pace_s=0.0)  # a restart in this process still cleans up
    assert again.owns_runs and again._load(cid).state == "failed" and "restart" in again._load(cid).error


# ----------------------------------------------------------------- idempotency tokens
def test_an_experiment_token_is_matched_only_against_experiments_of_the_same_case(env):
    _, orch, c = env
    other = c.post("/api/cases", json={"preset_id": "sealed-control", "runner": "deterministic", "autostart": False,
                                       "client_token": "tok-A"}).json()["case"]["case_id"]
    pid = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "deterministic"}).json()["case"]["case_id"]
    view = _wait(c, pid)
    made = _derive(c, pid, _collector(view), "tok-A", autostart=True)
    assert made.status_code == 200
    kid = made.json()["child_case_id"]
    assert kid != other and made.json()["case"]["parent_case_id"] == pid
    assert c.get(f"/api/cases/{other}").json()["case"]["state"] == "frozen"  # the unrelated case was not started
    assert [k["child_case_id"] for k in c.get(f"/api/cases/{pid}/source-experiment").json()["children"]] == [kid]
    # a retry returns the same derived case; the same token on another original makes that one's own
    assert _derive(c, pid, _collector(view), "tok-A").json()["child_case_id"] == kid
    p2 = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "deterministic"}).json()["case"]["case_id"]
    kid2 = _derive(c, p2, _collector(_wait(c, p2)), "tok-A").json()["child_case_id"]
    assert kid2 not in (kid, other) and c.get(f"/api/cases/{kid2}").json()["case"]["parent_case_id"] == p2
    # a case that does not exist is not found, whatever token comes with the request
    assert c.post("/api/cases/case-000000000000/source-experiments",
                  json={"excluded_source_ids": ["src-000000000000"], "client_token": "tok-A"}).status_code == 404
    # after a restart the token still leads to the same derived case
    assert Orchestrator(orch.settings, pace_s=0.0).create_source_experiment(pid, _collector(view), "tok-A").case_id == kid


def test_two_requests_with_one_token_arriving_together_make_one_case(env):
    _, orch, c = env
    pid = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "deterministic"}).json()["case"]["case_id"]
    sids = _collector(_wait(c, pid))
    got: dict[str, list[str]] = {"derive": [], "create": [], "replay": []}
    gate = threading.Barrier(4)

    def run(kind, fn):
        gate.wait(10)
        got[kind].append(fn().case_id)

    for kind, fn in (("derive", lambda: orch.create_source_experiment(pid, sids, "tok-R", runner_id="deterministic")),
                     ("create", lambda: orch.create_case(preset_id="sealed-control", runner_id="deterministic", client_token="tok-C")),
                     ("replay", lambda: orch.open_replay("hero-coverup-fixture", "tok-P"))):
        gate.reset()
        threads = [threading.Thread(target=run, args=(kind, fn)) for _ in range(4)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(60)
        assert len(got[kind]) == 4 and len(set(got[kind])) == 1, (kind, got[kind])
    assert len(c.get(f"/api/cases/{pid}/source-experiment").json()["children"]) == 1


# ----------------------------------------------------------------- the designer does not stall the server
def test_other_cases_keep_moving_while_a_design_request_waits_for_its_model(tmp_path, monkeypatch):
    settings = replace(load_settings({**LIVE, "ALIBI_SPEND_LEDGER": str(tmp_path / "spend.json")}, dotenv=False),
                       runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    orch = Orchestrator(settings, pace_s=0.0)
    c = TestClient(create_app(settings, orch))
    cid = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "deterministic"}).json()["case"]["case_id"]
    _wait(c, cid)
    entered, release = threading.Event(), threading.Event()

    class Slow(_FakeDesigner):
        def _generate(self, messages, stop=None, run_manager=None, **kw):
            entered.set()
            release.wait(20)
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kw)

    monkeypatch.setattr(gateway, "live_chat_model", lambda s, spec, *limit: Slow(reply=[("choose_environment", GOOD)], seen=[]))
    out: dict = {}
    th = threading.Thread(target=lambda: out.update(doc=orch.design_environment("slow-design", 5)))
    th.start()
    try:
        assert entered.wait(20)
        t0 = time.perf_counter()
        assert orch.events(cid, 0) and orch.view(cid)["case"]["state"] == "awaiting_review"
        other = orch.create_case(preset_id="sealed-control", runner_id="deterministic", client_token="meanwhile")
        assert time.perf_counter() - t0 < 5 and other.case_id  # none of this waited for the model
        assert th.is_alive()
    finally:
        release.set()
        th.join(30)
    assert out["doc"]["status"] == "designed"
    assert orch.design_environment("slow-design", 5)["design_id"] == out["doc"]["design_id"]  # a retry: the stored design


# ----------------------------------------------------------------- recordings and late answers
def test_a_recording_cannot_write_a_question_outside_its_case(env, tmp_path, monkeypatch):
    _, orch, c = env
    fake_dir = tmp_path / "replays"
    data = json.loads((REPLAY_DIR / "hero-coverup-fast-haiku-5-5" / "recording.json").read_text())
    assert len(data["questions"]) == 2
    data["questions"][0]["question_id"] = "../../../../escaped"
    (fake_dir / "crafted").mkdir(parents=True)
    (fake_dir / "crafted" / "recording.json").write_text(json.dumps(data))
    monkeypatch.setattr(orch_mod, "REPLAY_DIR", fake_dir)
    v = c.post("/api/replays/crafted/open", json={"autostart": False})
    assert v.status_code == 200
    cid = v.json()["case"]["case_id"]
    assert not list(tmp_path.rglob("escaped.json"))
    saved = [q["question_id"] for q in c.get(f"/api/cases/{cid}/questions").json()["questions"]]
    assert saved == [data["questions"][1]["question_id"]]  # the well-formed one is still replayed


def test_an_answer_that_arrives_after_its_case_was_reset_does_not_bring_the_case_back(tmp_path):
    settings = replace(load_settings({**LIVE, "ALIBI_SPEND_LEDGER": str(tmp_path / "spend.json")}, dotenv=False),
                       runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    orch = Orchestrator(settings, pace_s=0.0)
    c = TestClient(create_app(settings, orch))
    cid = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "deterministic"}).json()["case"]["case_id"]
    _wait(c, cid)
    model = _fake([_answer(status="insufficient_evidence", answer="Nothing establishes that.")])
    model.hold = threading.Event()
    orch.qa_model_factory = lambda *a, **k: model
    assert c.post(f"/api/cases/{cid}/questions", json={"question": "why?", "client_token": "q"}).json()["status"] == "pending"
    assert c.post(f"/api/cases/{cid}/reset").json()["existed"] is True
    model.hold.set()
    th = orch._qa_threads.get(cid)
    if th is not None:
        th.join(20)
    time.sleep(0.2)
    assert not (tmp_path / "runs" / cid).exists() and c.get(f"/api/cases/{cid}").status_code == 404


# ----------------------------------------------------------------- what an error message gives away
def test_a_damaged_ledger_is_reported_without_the_directory_it_lives_in(tmp_path):
    ledger = tmp_path / "deep" / "private" / "spend.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{not json")
    settings = replace(load_settings({**LIVE, "ALIBI_SPEND_LEDGER": str(ledger)}, dotenv=False),
                       runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    with pytest.raises(gateway.LedgerError) as err:
        gateway.global_spend_for(settings).snapshot()
    assert "spend.json" in str(err.value) and str(tmp_path) not in str(err.value) and "private" not in str(err.value)
    assert err.value.path == ledger  # the operator at the command line still gets the full path
    c = TestClient(create_app(settings, Orchestrator(settings, pace_s=0.0)))
    shown = c.get("/api/spend").json()
    assert shown["readable"] is False and "spend.json" in shown["note"] and str(tmp_path) not in json.dumps(shown)
