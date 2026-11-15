"""The optional Gemini question route. Offline: no network, no key, the 'model' is a test double."""

from __future__ import annotations

import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from alibi.agents import gateway
from alibi.api.app import create_app
from alibi.config import load_settings
from alibi.integrations import gemini_qa
from tests.test_m9_questions import _answer, _fake

ON = {"ALIBI_QA_PROVIDER": "gemini", "GEMINI_API_KEY": "test-not-a-key", "GEMINI_MODEL": "test-gemini",
      "GEMINI_PRICE_IN_PER_MTOK": "1", "GEMINI_PRICE_OUT_PER_MTOK": "5", "LLM_MAX_USD": "5"}


def _settings(env, tmp_path):
    return replace(load_settings({**env, "ALIBI_SPEND_LEDGER": str(tmp_path / "spend.json")}, dotenv=False),
                   runs_dir=tmp_path / "runs", sealed_dir=tmp_path / "sealed")


def test_the_route_is_off_by_default_and_needs_every_setting(tmp_path):
    assert "not 'gemini'" in gemini_qa.block_reason(_settings({}, tmp_path), {})
    for missing in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_PRICE_IN_PER_MTOK", "GEMINI_PRICE_OUT_PER_MTOK"):
        env = {k: v for k, v in ON.items() if k != missing}
        assert gemini_qa.block_reason(_settings(env, tmp_path), env), missing
    no_cap = {**ON, "LLM_MAX_USD": "0"}
    assert "LLM_MAX_USD" in gemini_qa.block_reason(_settings(no_cap, tmp_path), no_cap)
    assert gemini_qa.block_reason(_settings(ON, tmp_path), ON) is None
    with pytest.raises(SystemExit):
        gemini_qa.build_orchestrator(_settings({}, tmp_path), {})


def test_the_stock_server_never_loads_the_integration():
    import subprocess
    import sys

    code = ("import sys; from alibi.api.app import create_app; from alibi import cli; "
            "print(any(m.startswith('alibi.integrations') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert out.stdout.strip() == "False", out.stderr[-400:]


def test_a_question_goes_through_the_budget_gateway_and_trusted_validation(tmp_path, monkeypatch):
    for k, v in ON.items():
        monkeypatch.setenv(k, v)
    model = _fake([("list_sources", {})], [_answer(claims=[
        {"text": "This id is invented.", "evidence_ids": ["ev-does-not-exist"], "kind": "record"}])])
    built = {}

    def fake_class():
        def make(**kw):
            built.update(kw)
            return model
        return make

    monkeypatch.setattr(gemini_qa, "_chat_class", fake_class)
    orch = gemini_qa.build_orchestrator(_settings(ON, tmp_path), ON)
    orch.pace_s = 0.0
    c = TestClient(create_app(orch.settings, orch))
    cid = c.post("/api/cases", json={"preset_id": "hero-coverup", "runner": "deterministic"}).json()["case"]["case_id"]
    end = time.time() + 60
    while time.time() < end and c.get(f"/api/cases/{cid}").json()["case"]["state"] != "awaiting_review":
        time.sleep(0.05)
    q = c.post(f"/api/cases/{cid}/questions?wait_s=20", json={"question": "What happened?", "client_token": "g1"}).json()
    assert q["status"] == "insufficient_evidence", q  # the only claim cited an id that is not in the bundle
    assert q["dropped_evidence_ids"] == ["ev-does-not-exist"]
    assert q["model_id"] == "gemini:test-gemini" and "Gemini" in q["inference_label"]
    assert q["usage"]["llm_calls"] == 2 and q["usage"]["cost_estimate_usd"] > 0
    assert built["max_output_tokens"] <= 2000 and built["max_retries"] == 0
    # the question tools are the stock read-only set: nothing that writes a report or reaches sealed truth
    names = set(model.tools_bound[0])
    assert "answer_question" in names and not any("seal" in n or "truth" in n or "submit" in n for n in names)
    # the cumulative spend ledger counted it
    snap = gateway.global_spend_for(orch.settings).snapshot()
    assert snap["spent_usd"] > 0
    # the environment designer still sees no model and keeps its offline default
    design = c.post("/api/scenario-designs", json={"client_token": "d1"})
    assert design.status_code == 200 and design.json()["source"] == "default", design.text
    assert len(model.seen) == 2


def test_the_factory_refuses_anything_but_a_question(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_qa, "_chat_class", lambda: (lambda **kw: _fake("x")))
    build = gemini_qa.model_factory(ON)
    ledger = gateway.make_ledger(gemini_qa.gemini_settings(_settings(ON, tmp_path), ON), None, scripted=False,
                                 label="scenario-design")
    with pytest.raises(gateway.RuntimeBlocked):
        build(ledger)


def test_the_client_adapter_sends_the_reserved_output_limit_and_reports_truncation(monkeypatch):
    from langchain_google_genai import ChatGoogleGenerativeAI

    seen = {}

    def fake_generate(self, messages, stop=None, run_manager=None, **kw):
        seen.update(kw)
        msg = AIMessage(content="", response_metadata={"finish_reason": "MAX_TOKENS"})
        return ChatResult(generations=[ChatGeneration(message=msg)])

    monkeypatch.setattr(ChatGoogleGenerativeAI, "_generate", fake_generate)
    llm = gemini_qa._chat_class()(model="test-gemini", google_api_key="test-not-a-key", max_output_tokens=900)
    out = llm.invoke([HumanMessage("hi")], max_tokens=321)
    assert seen.get("max_output_tokens") == 321 and "max_tokens" not in seen
    assert out.response_metadata["stop_reason"] == "max_tokens"
