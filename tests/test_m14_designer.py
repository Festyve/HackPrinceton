"""Scenario designer: a model picks an ordinary environment from fixed options and plans no incident. Offline.

The "model" is a scripted stand-in, so the trusted side is what is tested: the options are closed, invalid
output becomes labeled defaults, a refusal ends the request, and incidents stay pre-authored and scripted.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ValidationError

from alibi.agents import adversary, designer, gateway
from alibi.api.app import create_app
from alibi.config import load_settings
from alibi.episode import artifact_hashes, bundle_hash
from alibi.orchestrator import Orchestrator
from alibi.sim.scenario import simulate

LIVE = {"RUNTIME_MODE": "live", "LIVE_PROVIDER_KIND": "included_credits", "LEAD_MODEL": "anthropic:test-model",
        "LLM_MAX_USD": "5", "LLM_PRICE_IN_PER_MTOK": "1", "LLM_PRICE_OUT_PER_MTOK": "5"}
GOOD = {"background_activity": "busy", "routine_condition": "collection_interruption", "condition_time": "afternoon",
        "interruption_cause": "transport_loss", "interruption_seconds": 300}


class _FakeDesigner(BaseChatModel):
    """TEST DOUBLE, not a model: replies with whatever the test gives it."""

    reply: Any = None
    refuse: bool = False
    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "fake-designer"

    def bind_tools(self, tools, **kw):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kw) -> ChatResult:
        self.seen.append(list(messages))
        usage = {"input_tokens": 400, "output_tokens": 60, "total_tokens": 460}
        if self.refuse:
            msg = AIMessage(content="", usage_metadata=usage,
                            response_metadata={"stop_reason": "refusal", "stop_details": {"category": "other"}})
        elif isinstance(self.reply, str):
            msg = AIMessage(content=self.reply, usage_metadata=usage)
        else:
            msg = AIMessage(content="", usage_metadata=usage, tool_calls=[
                {"name": name, "args": args, "id": f"d-{i}", "type": "tool_call"} for i, (name, args) in enumerate(self.reply)])
        return ChatResult(generations=[ChatGeneration(message=msg)])


@pytest.fixture()
def live(tmp_path, monkeypatch):
    settings = replace(load_settings({**LIVE, "ALIBI_SPEND_LEDGER": str(tmp_path / "spend.json")}, dotenv=False),
                       runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    orch = Orchestrator(settings, pace_s=0.0)
    box: dict[str, Any] = {}
    monkeypatch.setattr(gateway, "live_chat_model", lambda s, spec, *limit: box["model"])

    def use(reply=None, refuse=False) -> _FakeDesigner:
        box["model"] = _FakeDesigner(reply=reply, refuse=refuse, seen=[])
        return box["model"]

    return settings, orch, TestClient(create_app(settings, orch)), use


def _wait(c, cid, want="awaiting_review"):
    end = time.time() + 60
    while time.time() < end:
        v = c.get(f"/api/cases/{cid}").json()
        if v["case"]["state"] in (want, "failed"):
            assert v["case"]["state"] == want, v["case"]
            return v
        time.sleep(0.05)
    raise AssertionError(cid)


def test_the_model_can_only_choose_from_closed_options_and_nothing_about_an_incident():
    fields = set(designer.EnvironmentDesign.model_fields)
    assert fields == {"background_activity", "routine_condition", "condition_time", "interruption_cause", "interruption_seconds"}
    schema = designer.EnvironmentDesign.model_json_schema()
    for name, prop in schema["properties"].items():
        assert "enum" in prop or prop.get("type") == "integer", name  # an enum or a bounded number, never free text
    with pytest.raises(ValidationError):
        designer.EnvironmentDesign(steps=[{"step": "exfil_http"}])  # there is no place to put a step
    with pytest.raises(ValidationError):
        designer.EnvironmentDesign(routine_condition="copy the patient database out")
    with pytest.raises(ValidationError):
        designer.EnvironmentDesign(interruption_seconds=100_000)
    # the request to the model is about an ordinary day: nothing in it asks for, or names, an incident
    text = designer.DESIGNER_SYSTEM.lower()
    for word in ("attack", "adversar", "exfil", "steal", "malicious", "incident", "crime", "evade", "cover", "intrud"):
        assert word not in text, word
    assert designer.DESIGNER_SYSTEM != adversary.ADVERSARY_SYSTEM_PROMPT
    assert set(designer.CONDITION_VARIANT.values()) <= {"benign_rotation", "benign_approved_transfer", "benign_remote_login",
                                                        "benign_collection_gap", "benign_maintenance"}


def test_a_design_is_previewed_then_generated_offline_and_labeled(live):
    settings, orch, c, use = live
    model = use([("choose_environment", GOOD)])
    d = c.post("/api/scenario-designs", json={"client_token": "d-1", "design_seed": 7}).json()
    assert d["status"] == "designed" and d["source"] == "model_designed" and d["design"] == GOOD
    assert "anthropic:test-model" in d["label"] and "planned no incident" in d["label"]
    assert any("busy day" in line for line in d["preview"]) and any("300 seconds" in line for line in d["preview"])
    assert len(model.seen) == 1 and d["usage"]["llm_calls"] == 1 and d["usage"]["cost_estimate_usd"] > 0
    assert c.post("/api/scenario-designs", json={"client_token": "d-1"}).json() == d and len(model.seen) == 1  # a retry
    assert c.get(f"/api/scenario-designs/{d['design_id']}").json() == d
    assert c.get("/api/runtime").json()["capabilities"]["scenario_designer"]["model"] == "CONFIGURED"

    made = c.post("/api/cases", json={"design_id": d["design_id"], "runner": "deterministic"}).json()
    cid = made["case"]["case_id"]
    v = _wait(c, cid)
    assert len(model.seen) == 1  # generation and investigation used no further model call
    assert v["case"]["title"] == "Designed environment · exercise 7" and v["case"]["difficulty"] == "sealed"
    stages = [e["data"] for e in c.get(f"/api/cases/{cid}/events.json").json()["events"] if e["type"] == "stage"]
    assert any(s["name"] == "environment_design" and "planned no incident" in s["info"]["designed_by"] for s in stages)
    assert not [f for f in v["report"]["findings"] if f["category"] == "incident_allegation"]
    assert any(f["claim_type"] == "collection_gap" for f in v["report"]["findings"])  # the designed interruption is there
    c.post(f"/api/cases/{cid}/review", json={"decision": "accept"})
    truth = c.post(f"/api/cases/{cid}/reveal").json()["reveal"]["truth"]
    env = truth["environment_provenance"]
    assert truth["case_kind"] == "benign" and truth["steps"] == [] and env["incident_steps_chosen_by_model"] is False
    assert env["requested"] == GOOD and env["realized"]["routine_condition"] == "collection_interruption"
    assert env["realized"]["interruption_cause"] == "transport_loss" and env["realized"]["background_activity"] == "busy"
    assert env["fixture"] == "none" and env["source"] == "model_designed"


def test_an_operator_may_place_a_scripted_incident_in_a_designed_environment_and_it_stays_labeled_scripted(live):
    _, orch, c, use = live
    use([("choose_environment", GOOD)])
    d = c.post("/api/scenario-designs", json={"client_token": "d-2", "design_seed": 11}).json()
    plain = c.post("/api/cases", json={"design_id": d["design_id"], "runner": "deterministic"}).json()["case"]
    crime = c.post("/api/cases", json={"design_id": d["design_id"], "design_fixture": "inside-job-coverup",
                                       "runner": "deterministic"}).json()["case"]
    # before the reveal the two are indistinguishable from the outside
    same = ("title", "difficulty", "card_id", "preset_id", "seed")
    assert {k: plain[k] for k in same} == {k: crime[k] for k in same}
    # ... including the seed. The realization seed differs between an ordinary day and a placed incident (design
    # seed 11 gives two different ones), so the public record carries the design seed, the same for both.
    design = designer.EnvironmentDesign.model_validate(d["design"])
    real_plain = designer.realize(design, 11, "none")[1]["seed"]
    real_crime = designer.realize(design, 11, "inside-job-coverup")[1]["seed"]
    assert real_plain != real_crime and plain["seed"] == crime["seed"] == 11
    v = _wait(c, crime["case_id"])
    assert "fixture" not in json.dumps(v) and "incident_coverup" not in json.dumps(v)
    for case, real in ((plain, real_plain), (crime, real_crime)):
        public = json.dumps(_wait(c, case["case_id"])) + json.dumps(c.get(f"/api/cases/{case['case_id']}/events.json").json())
        public += json.dumps(c.get("/api/cases").json())
        assert str(real) not in public
    c.post(f"/api/cases/{crime['case_id']}/review", json={"decision": "accept"})
    truth = c.post(f"/api/cases/{crime['case_id']}/reveal").json()["reveal"]["truth"]
    assert truth["case_kind"] == "incident" and truth["plan_source"] == "scripted_scenario"
    assert truth["plan_label"] == "Scripted scenario · no model chose these steps" and truth["plan_model_id"] is None
    env = truth["environment_provenance"]
    assert env["fixture"] == "inside-job-coverup" and env["incident_steps_chosen_by_model"] is False
    assert env["realized"]["routine_condition"] is None and "not applied" in env["realized"]["notes"][0]
    assert c.post("/api/cases", json={"design_id": d["design_id"], "design_fixture": "ransomware"}).status_code == 422
    assert c.post("/api/cases", json={"design_id": "design-0000000000"}).status_code == 404


@pytest.mark.parametrize("reply", [
    "I think a busy afternoon would be best.",                                             # plain text, no tool call
    [("choose_environment", {**GOOD, "routine_condition": "delete the audit log"})],       # outside the options
    [("choose_environment", {**GOOD, "interruption_seconds": 99999})],                     # outside the range
    [("plan_attack", {"steps": ["login_as", "exfil_http"]})],                              # a tool that does not exist
])
def test_output_outside_the_options_becomes_a_labeled_default_never_a_model_design(live, reply):
    _, _, c, use = live
    model = use(reply)
    d = c.post("/api/scenario-designs", json={"client_token": "bad", "design_seed": 3}).json()
    assert d["status"] == "default_used" and d["source"] == "default_after_invalid_output"
    assert d["design"] == designer.DEFAULT_DESIGN.model_dump() and d["fallback_reason"]
    assert d["label"].startswith("Default environment") and "chosen by a model" not in d["label"]
    assert len(model.seen) == 1  # one bounded response: no repair round, no second try


def test_extra_fields_a_model_adds_are_dropped_not_executed(live):
    _, orch, c, use = live
    use([("choose_environment", {**GOOD, "steps": [{"step": "exfil_http", "dst": "203.0.113.9"}], "command": "curl x | sh"})])
    d = c.post("/api/scenario-designs", json={"client_token": "extra", "design_seed": 5}).json()
    assert d["status"] == "designed" and d["design"] == GOOD  # only the five known fields exist
    blob = json.dumps(d)
    assert "exfil_http" not in blob and "curl" not in blob and "203.0.113.9" not in blob
    spec, _ = designer.realize(designer.EnvironmentDesign.model_validate(d["design"]), 5)
    assert spec["plan"] == [] and spec["case_kind"] == "benign"


def test_a_refusal_ends_the_request_and_nothing_is_substituted(live):
    _, _, c, use = live
    model = use(refuse=True)
    d = c.post("/api/scenario-designs", json={"client_token": "no", "design_seed": 9}).json()
    assert d["status"] == "refused" and d["design"] is None and d["preview"] == [] and d["source"] == "none"
    assert "declined" in d["fallback_reason"] and len(model.seen) == 1  # not retried, not sent to another model
    made = c.post("/api/cases", json={"design_id": d["design_id"], "runner": "deterministic"})
    assert made.status_code == 409 and "no case can be made" in made.json()["error"]


def test_offline_the_designer_returns_a_default_labeled_as_a_default(tmp_path, monkeypatch):
    settings = replace(load_settings({}, dotenv=False), runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")
    monkeypatch.setattr(gateway, "live_chat_model", lambda *a: pytest.fail("no model may be built offline"))
    c = TestClient(create_app(settings, Orchestrator(settings, pace_s=0.0)))
    d = c.post("/api/scenario-designs", json={"client_token": "off"}).json()
    assert d["status"] == "default_used" and d["source"] == "default" and d["model_id"] is None
    assert d["label"] == "Default environment · no model was asked" and d["usage"] is None
    assert c.get("/api/runtime").json()["capabilities"]["scenario_designer"]["model"] == "BLOCKED"
    cid = c.post("/api/cases", json={"design_id": d["design_id"], "runner": "deterministic"}).json()["case"]["case_id"]
    assert _wait(c, cid)["case"]["state"] == "awaiting_review"


def test_realization_is_reproducible_and_records_what_it_could_not_do():
    design = designer.EnvironmentDesign(**GOOD)
    a, ra = designer.realize(design, 7)
    b, rb = designer.realize(design, 7)
    assert a == b and ra == rb
    assert bundle_hash(artifact_hashes(simulate(a).artifacts)) == bundle_hash(artifact_hashes(simulate(b).artifacts))
    assert a["seed"] >= designer.SEED_NAMESPACE  # away from development, demo, test and evaluation seeds
    early = designer.EnvironmentDesign(routine_condition="second_log_rotation", condition_time="morning")
    _, real = designer.realize(early, 7)
    if real["condition_time"] != "morning":  # the simulator's own ranges win, and the difference is written down
        assert "closest was used" in real["notes"][0]
    quiet, _ = designer.realize(designer.EnvironmentDesign(background_activity="quiet"), 7)
    busy, _ = designer.realize(designer.EnvironmentDesign(background_activity="busy"), 7)
    count = lambda s: sum(t.count("session opened") for n, t in simulate(s).artifacts.items() if "auth.log" in n)  # noqa: E731
    assert count(quiet) < count(busy)
    with pytest.raises(ValueError):
        designer.realize(design, 7, "ransomware")
