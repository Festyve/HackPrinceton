"""Budget gateway regression tests (phase-two review; docs/next-run/CONTINUE.md section 1).

Everything here runs offline against test doubles. No network, no model call, no real ledger.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from alibi.agents import gateway
from alibi.config import ConfigError, RunCaps, load_settings

P_IN, P_OUT = 4.0, 20.0  # USD per million tokens, as for the recorded Opus runs


class _Probe(BaseChatModel):
    """A chat model double that records exactly what the gateway sent it."""

    kind: str = "probe-test-double"
    usage: Any = {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200}
    count: int = 1000
    count_fails: bool = False
    fail: list = []
    delay: float = 0.0
    sent: list = []      # kwargs of every request that reached the "provider"
    counted: list = []   # (n_messages, tools) of every provider-side count

    @property
    def _llm_type(self) -> str:
        return self.kind

    def bind_tools(self, tools, **kw):
        return self.bind(tools=[{"name": t.name, "description": t.description, "input_schema": t.args} for t in tools], **kw)

    def get_num_tokens_from_messages(self, messages, tools=None, **kw) -> int:
        if self.count_fails:
            raise ConnectionError("count endpoint unreachable")
        self.counted.append((len(messages), tools))
        return self.count

    def _generate(self, messages, stop=None, run_manager=None, **kw) -> ChatResult:
        self.sent.append(kw)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise self.fail.pop(0)
        msg = AIMessage(content="ok", usage_metadata=self.usage) if self.usage else AIMessage(content="ok")
        return ChatResult(generations=[ChatGeneration(message=msg)])


class _Status(Exception):
    def __init__(self, status_code: int, text: str = "provider error"):
        super().__init__(text)
        self.status_code = status_code


def _probe(**kw) -> _Probe:
    return _Probe(sent=[], counted=[], fail=list(kw.pop("fail", [])), **kw)


def _billed(tmp_path: Path, caps: RunCaps | None = None, cap: float = 5.0, limit: float | None = None,
            per_call: int = 3000, label: str = "t") -> tuple[gateway.BudgetLedger, gateway.GlobalSpend]:
    spend = gateway.GlobalSpend(tmp_path / "spend.json", cap, limit_usd=limit)
    led = gateway.BudgetLedger(None, caps or RunCaps(), kind="included_credits", max_usd=cap, price_in_per_mtok=P_IN,
                               price_out_per_mtok=P_OUT, global_spend=spend, max_tokens_per_call=per_call, label=label,
                               model="anthropic:test")
    return led, spend


def _fixed(n: int):
    return lambda inner, bound, messages: n


# ----------------------------------------------------------------- the request is counted and bounded before it is sent
def test_oversized_request_is_refused_before_it_is_sent(tmp_path):
    led, spend = _billed(tmp_path, RunCaps(max_input_tokens_per_call=1000))
    inner = _probe()
    with pytest.raises(gateway.BudgetExceeded) as err:
        gateway.wrap(inner, led, "lead-investigator", counter=_fixed(5000)).invoke("x")
    assert "request too large" in str(err.value) and "not sent" in str(err.value)
    assert inner.sent == [] and led.usage().llm_calls == 0
    snap = spend.snapshot()
    assert snap["spent_usd"] == 0 and snap["reserved_usd"] == 0 and snap["unreconciled_usd"] == 0


def test_provider_count_sees_the_system_prompt_and_tool_schemas(tmp_path):
    @tool
    def lookup(event_id: str) -> str:
        """Fetch one evidence record by its id."""
        return event_id

    led, spend = _billed(tmp_path)
    inner = _probe(kind="anthropic-chat", count=2000)
    model = gateway.wrap(inner, led, "lead-investigator").bind_tools([lookup])
    model.invoke([SystemMessage("You are a careful investigator."), HumanMessage("Look at ev-1.")])
    n_messages, tools = inner.counted[0]
    assert n_messages == 2 and tools and tools[0]["name"] == "lookup"  # system + user, and the tool schema
    expect = math.ceil(2000 * gateway.COUNT_HEADROOM) + gateway.COUNT_PAD
    assert gateway.count_request_tokens(inner, model.bound, [HumanMessage("x")]) == (expect, "provider_count")
    # the request then went out with the reserved output limit and prompt caching
    assert inner.sent[0]["max_tokens"] == 3000 and inner.sent[0]["cache_control"] == {"type": "ephemeral"}
    assert inner.sent[0]["tools"][0]["name"] == "lookup"
    # the local bound (used where no provider count exists) grows with the tool schemas too
    msgs = [SystemMessage("s" * 400), HumanMessage("u" * 400)]
    assert gateway.local_token_bound(msgs, tools) > gateway.local_token_bound(msgs, None) >= 400 + 512


def test_a_billed_request_that_cannot_be_counted_is_not_sent(tmp_path):
    led, spend = _billed(tmp_path)
    inner = _probe(kind="anthropic-chat", count_fails=True)
    with pytest.raises(gateway.BudgetExceeded) as err:
        gateway.wrap(inner, led, "lead-investigator").invoke("x")
    assert "could not be counted" in str(err.value) and inner.sent == []
    assert spend.snapshot()["reserved_usd"] == 0 and led.usage().llm_calls == 0


def test_cumulative_input_cap_counts_the_next_request_before_sending(tmp_path):
    led, _ = _billed(tmp_path, RunCaps(max_input_tokens=2500, max_input_tokens_per_call=2000))
    inner = _probe()
    m = gateway.wrap(inner, led, "lead-investigator", counter=_fixed(900))
    m.invoke("a"); m.invoke("b")  # noqa: E702 - 2 x 1000 actual
    with pytest.raises(gateway.BudgetExceeded) as err:
        m.invoke("c")  # 2000 used + 900 counted > 2500
    assert "input token cap reached" in str(err.value) and len(inner.sent) == 2


# ----------------------------------------------------------------- output: what is sent is what was reserved
def test_output_limit_sent_to_the_provider_equals_the_output_reserved_near_the_cap(tmp_path):
    led, _ = _billed(tmp_path, RunCaps(max_output_tokens=4000))
    inner = _probe(usage={"input_tokens": 500, "output_tokens": 3000, "total_tokens": 3500})
    m = gateway.wrap(inner, led, "lead-investigator", counter=_fixed(500))
    m.invoke("a")
    assert inner.sent[0]["max_tokens"] == 3000
    inner.usage = {"input_tokens": 500, "output_tokens": 800, "total_tokens": 1300}
    m.invoke("b")  # only 1000 output tokens remain: the provider limit shrinks with the reservation
    assert inner.sent[1]["max_tokens"] == 1000
    with pytest.raises(gateway.BudgetExceeded) as err:
        m.invoke("c")  # 200 left is under the minimum useful response: not sent at all
    assert "output token cap reached" in str(err.value) and len(inner.sent) == 2
    assert led.usage().tokens_out == 3800 <= 4000


def test_a_model_that_cannot_take_a_per_call_limit_is_not_sent_an_unclamped_request(tmp_path):
    led = gateway.BudgetLedger(None, RunCaps(max_output_tokens=4000), kind="local", max_tokens_per_call=3000)
    inner = _probe(kind="chat-ollama", usage={"input_tokens": 100, "output_tokens": 3000, "total_tokens": 3100})
    m = gateway.wrap(inner, led, "lead-investigator")
    m.invoke("a")
    assert "max_tokens" not in inner.sent[0] and "num_predict" not in inner.sent[0]
    with pytest.raises(gateway.BudgetExceeded):
        m.invoke("b")  # 1000 left < the model's fixed 3000 limit
    assert len(inner.sent) == 1 and led.state["reserved"] == 0


# ----------------------------------------------------------------- parallel reservations are atomic
def _race(n: int, fn) -> list[Any]:
    gate, out = threading.Barrier(n), [None] * n

    def run(i: int) -> None:
        gate.wait()
        try:
            out[i] = fn()
        except gateway.BudgetExceeded as exc:
            out[i] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def test_parallel_specialists_cannot_jointly_pass_the_token_or_call_caps(tmp_path):
    led, _ = _billed(tmp_path, RunCaps(max_calls=50, max_input_tokens=10_000, max_output_tokens=50_000,
                                       max_input_tokens_per_call=5000), per_call=1000)
    got = _race(16, lambda: led.reserve("skeptic", 3000))
    held = [r for r in got if isinstance(r, gateway.Reservation)]
    assert len(held) == 3 and sum(r.input_tokens for r in held) == 9000 <= 10_000  # never 4 x 3000
    assert led.state["reserved_in"] == 9000 and led.state["reserved"] == 3

    out_led, _ = _billed(tmp_path / "o", RunCaps(max_calls=50, max_output_tokens=5000), per_call=2000)
    held = [r for r in _race(16, lambda: out_led.reserve("skeptic", 100)) if isinstance(r, gateway.Reservation)]
    assert sorted(r.output_tokens for r in held) == [1000, 2000, 2000]  # the third is clamped, a fourth is refused

    call_led, _ = _billed(tmp_path / "c", RunCaps(max_calls=4), per_call=300)
    assert sum(isinstance(r, gateway.Reservation) for r in _race(16, lambda: call_led.reserve("skeptic", 10))) == 4


def test_parallel_calls_through_the_wrapper_hold_their_reservations_while_in_flight(tmp_path):
    led, spend = _billed(tmp_path, RunCaps(max_calls=50, max_input_tokens=10_000, max_input_tokens_per_call=5000))
    inner = _probe(delay=0.15, usage={"input_tokens": 3000, "output_tokens": 50, "total_tokens": 3050})
    m = gateway.wrap(inner, led, "integrity-auditor", counter=_fixed(3000))
    got = _race(8, lambda: m.invoke("x"))
    assert sum(isinstance(r, AIMessage) for r in got) == 3 and len(inner.sent) == 3
    assert led.usage().tokens_in == 9000 and spend.snapshot()["reserved_usd"] == 0


def test_parallel_money_reservations_share_one_total_across_objects_and_processes(tmp_path):
    path = tmp_path / "spend.json"
    got = _race(20, lambda: gateway.GlobalSpend(path, 1.0).reserve(0.30, "race"))  # 20 separate ledger objects
    assert sum(isinstance(r, str) for r in got) == 3
    assert gateway.GlobalSpend(path, 1.0).snapshot()["reserved_usd"] == pytest.approx(0.90)

    other = tmp_path / "procs.json"
    code = ("import sys; from alibi.agents import gateway\n"
            "try:\n    gateway.GlobalSpend(sys.argv[1], 1.0).reserve(0.30, 'proc'); print('held')\n"
            "except gateway.BudgetExceeded:\n    print('refused')\n")
    procs = [subprocess.Popen([sys.executable, "-c", code, str(other)], stdout=subprocess.PIPE, text=True) for _ in range(6)]
    results = [p.communicate(timeout=60)[0].strip() for p in procs]
    assert sorted(results) == ["held"] * 3 + ["refused"] * 3
    snap = gateway.GlobalSpend(other, 1.0).snapshot()
    assert snap["reserved_usd"] == pytest.approx(0.90) and len(snap["open_reservations"]) == 3


# ----------------------------------------------------------------- unknown outcomes keep their worst case
def test_a_timeout_keeps_its_worst_case_cost_until_an_operator_reconciles_it(tmp_path, monkeypatch):
    led, spend = _billed(tmp_path)
    inner = _probe(fail=[TimeoutError("request timed out"), TimeoutError("request timed out")])
    m = gateway.wrap(inner, led, "lead-investigator", counter=_fixed(8000))
    m.retry_sleep_s = 0
    with pytest.raises(TimeoutError):
        m.invoke("x")
    worst = gateway.worst_case_usd(8000, 3000, P_IN, P_OUT)  # $0.10 per attempt
    assert len(inner.sent) == 2  # one bounded retry, and BOTH attempts may have been billed
    u = led.usage()
    assert (u.llm_calls, u.tokens_in, u.tokens_out) == (2, 16_000, 6000) and u.cost_estimate_usd == pytest.approx(2 * worst)
    assert led.state["uncertain_calls"] == 2
    snap = spend.snapshot()
    assert snap["unreconciled_usd"] == pytest.approx(2 * worst) and snap["spent_usd"] == 0 and snap["reserved_usd"] == 0
    assert snap["committed_usd"] == pytest.approx(2 * worst) and len(snap["unreconciled"]) == 2

    # age does not free the money: a month later, in a new process, it is all still held
    real = time.time
    monkeypatch.setattr(gateway.time, "time", lambda: real() + 30 * 86400)
    later = gateway.GlobalSpend(tmp_path / "spend.json", 5.0)
    assert later.snapshot()["unreconciled_usd"] == pytest.approx(2 * worst)
    with pytest.raises(gateway.BudgetExceeded):
        later.reserve(5.0 - 2 * worst + 0.01, "would only fit if the held amounts had expired")

    # the operator looks at the provider console and states the real cost of one of them
    token = snap["unreconciled"][0]["token"]
    done = later.reconcile(token, 0.012, note="console shows one billed attempt")
    assert done["held_usd"] == pytest.approx(worst)
    after = later.snapshot()
    assert after["spent_usd"] == pytest.approx(0.012) and after["unreconciled_usd"] == pytest.approx(worst)
    with pytest.raises(KeyError):
        later.reconcile(token, 0.012)  # reconciling twice cannot add the amount twice


def test_a_response_without_usage_is_unknown_cost_not_zero_cost(tmp_path):
    led, spend = _billed(tmp_path)
    inner = _probe(usage=None)
    reply = gateway.wrap(inner, led, "lead-investigator", counter=_fixed(4000)).invoke("x")
    assert reply.content == "ok"  # the answer is still used
    worst = gateway.worst_case_usd(4000, 3000, P_IN, P_OUT)
    assert led.usage().cost_estimate_usd == pytest.approx(worst) and led.usage().tokens_in == 4000
    assert led.state["uncertain_calls"] == 1 and spend.snapshot()["unreconciled_usd"] == pytest.approx(worst)
    zero = _probe(usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    gateway.wrap(zero, led, "lead-investigator", counter=_fixed(4000)).invoke("y")
    assert spend.snapshot()["unreconciled_usd"] == pytest.approx(2 * worst)  # an all-zero usage block is not believed


def test_errors_are_accounted_by_whether_the_request_could_have_been_billed(tmp_path):
    assert gateway.classify_error(_Status(400)) == {"billed_unknown": False, "fatal": False, "retry": False}
    assert gateway.classify_error(_Status(429)) == {"billed_unknown": False, "fatal": False, "retry": True}
    assert gateway.classify_error(_Status(401)) == {"billed_unknown": False, "fatal": True, "retry": False}
    assert gateway.classify_error(_Status(500)) == {"billed_unknown": True, "fatal": False, "retry": True}
    assert gateway.classify_error(_Status(529)) == {"billed_unknown": True, "fatal": False, "retry": True}
    assert gateway.classify_error(TimeoutError("timed out"))["billed_unknown"] is True
    assert gateway.classify_error(RuntimeError("something unexpected")) == {"billed_unknown": True, "fatal": False, "retry": False}

    led, spend = _billed(tmp_path)
    rejected = _probe(fail=[_Status(400, "invalid request")])
    with pytest.raises(_Status):
        gateway.wrap(rejected, led, "lead-investigator", counter=_fixed(4000)).invoke("x")
    snap = spend.snapshot()  # rejected before processing: certainly not billed, so nothing is held
    assert snap["unreconciled_usd"] == 0 and snap["reserved_usd"] == 0 and snap["spent_usd"] == 0
    assert led.usage().llm_calls == 0 and led.usage().errors == 1

    # a response lost after the request was written may have been billed: its worst case stays on the books
    # even though the single retry then succeeds and is charged at its real usage
    lost = _probe(fail=[RuntimeError("connection reset after the request was written")])
    m = gateway.wrap(lost, led, "lead-investigator", counter=_fixed(4000))
    m.retry_sleep_s = 0
    assert m.invoke("y").content == "ok" and len(lost.sent) == 2
    snap = spend.snapshot()
    assert snap["unreconciled_usd"] == pytest.approx(gateway.worst_case_usd(4000, 3000, P_IN, P_OUT))
    assert snap["spent_usd"] == pytest.approx(gateway.call_cost_usd(1000, 200, 0, 0, P_IN, P_OUT))
    assert led.usage().retries == 1 and led.state["uncertain_calls"] == 1

    odd = _probe(fail=[RuntimeError("something unexpected")])  # not recognizably transient: no retry, still held
    with pytest.raises(RuntimeError):
        gateway.wrap(odd, led, "lead-investigator", counter=_fixed(4000)).invoke("z")
    assert len(odd.sent) == 1
    assert spend.snapshot()["unreconciled_usd"] == pytest.approx(2 * gateway.worst_case_usd(4000, 3000, P_IN, P_OUT))


# ----------------------------------------------------------------- crashed processes and stale reservations
def test_a_crashed_process_leaves_its_reservation_held_whatever_its_age(tmp_path, monkeypatch):
    path = tmp_path / "spend.json"
    token = gateway.GlobalSpend(path, 1.0).reserve(0.40, "run that crashed mid-call", "anthropic:test")
    real = time.time
    monkeypatch.setattr(gateway.time, "time", lambda: real() + 10 * 86400)  # far past the old 900 s expiry
    later = gateway.GlobalSpend(path, 1.0)
    snap = later.snapshot()
    assert snap["reserved_usd"] == pytest.approx(0.40) and snap["open_reservations"][0]["age_s"] >= 10 * 86400
    with pytest.raises(gateway.BudgetExceeded):
        later.reserve(0.70, "next run")
    assert later.reserve(0.55, "fits beside the held amount")
    later.reconcile(token, 0.0, note="console shows that call never completed")
    assert later.snapshot()["reserved_usd"] == pytest.approx(0.55) and later.snapshot()["spent_usd"] == 0


def test_a_restarted_investigation_counts_its_interrupted_call_as_used(tmp_path):
    path = tmp_path / "budget.json"
    led, spend = _billed(tmp_path)
    led.path = path
    hold = led.reserve("lead-investigator", 6000)  # ... and the process dies before the response arrives
    again = gateway.BudgetLedger(path, RunCaps(), kind="included_credits", max_usd=5.0, price_in_per_mtok=P_IN,
                                 price_out_per_mtok=P_OUT, global_spend=spend, max_tokens_per_call=3000)
    u = again.usage()
    assert (u.llm_calls, u.tokens_in, u.tokens_out) == (1, 6000, 3000) and u.cost_estimate_usd == pytest.approx(hold.usd)
    assert again.state["reserved"] == 0 and again.state["uncertain_calls"] == 1
    assert spend.snapshot()["reserved_usd"] == pytest.approx(hold.usd)  # the money is still held in the shared ledger


# ----------------------------------------------------------------- settlement is idempotent
def test_settling_twice_charges_once(tmp_path):
    spend = gateway.GlobalSpend(tmp_path / "spend.json", 1.0)
    token = spend.reserve(0.20, "call")
    assert spend.settle(token, 0.05) is True
    assert spend.settle(token, 0.05) is False and spend.mark_uncertain(token, "late") is False
    assert spend.release(token, "late") is False
    snap = spend.snapshot()
    assert snap["spent_usd"] == pytest.approx(0.05) and snap["calls"] == 1 and snap["unreconciled_usd"] == 0

    led, shared = _billed(tmp_path / "l")
    hold = led.reserve("lead-investigator", 1000)
    for _ in range(3):
        led.commit("lead-investigator", hold, outcome="ok", tokens_in=1000, tokens_out=100)
    assert led.usage().llm_calls == 1 and led.usage().tokens_in == 1000
    assert shared.snapshot()["spent_usd"] == pytest.approx(gateway.call_cost_usd(1000, 100, 0, 0, P_IN, P_OUT))
    led.commit("lead-investigator", hold, outcome="uncertain")  # a late, conflicting report is ignored too
    assert shared.snapshot()["unreconciled_usd"] == 0


# ----------------------------------------------------------------- invalid numbers
@pytest.mark.parametrize("env", [
    {"LLM_MAX_USD": "nan"}, {"LLM_MAX_USD": "inf"}, {"LLM_MAX_USD": "-inf"}, {"LLM_MAX_USD": "-1"},
    {"LLM_PRICE_IN_PER_MTOK": "nan"}, {"LLM_PRICE_OUT_PER_MTOK": "-0.5"}, {"LLM_PRICE_OUT_PER_MTOK": "infinity"},
    {"LLM_MAX_CALLS_PER_RUN": "0"}, {"LLM_MAX_CALLS_PER_RUN": "-3"}, {"LLM_MAX_INPUT_TOKENS_PER_RUN": "0"},
    {"LLM_MAX_OUTPUT_TOKENS_PER_RUN": "-1"}, {"LLM_MAX_SECONDS_PER_RUN": "inf"}, {"LLM_MAX_SECONDS_PER_RUN": "nan"},
    {"LLM_MAX_SECONDS_PER_RUN": "0"}, {"LLM_MAX_INPUT_TOKENS_PER_CALL": "150000"}, {"LLM_MAX_INPUT_TOKENS_PER_CALL": "0"},
    {"LLM_MAX_USD": "5", "LLM_DEV_CEILING_USD": "nan"}, {"LLM_MAX_USD": "5", "LLM_DEV_CEILING_USD": "6"},
    {"LLM_SPEND_FLOOR_USD": "-1"}, {"LLM_SPEND_FLOOR_USD": "nan"}, {"ALIBI_SPEND_LEDGER": "relative/spend.json"},
    {"LLM_MAX_TOKENS_PER_CALL": "10"},
])
def test_non_finite_and_out_of_range_settings_are_rejected(env):
    with pytest.raises(ConfigError):
        load_settings(env, dotenv=False)


def test_non_finite_amounts_never_reach_the_ledgers(tmp_path):
    path = tmp_path / "spend.json"
    for bad in (float("nan"), float("inf"), -1.0):
        with pytest.raises(gateway.BudgetExceeded):
            gateway.GlobalSpend(path, bad)
        with pytest.raises(gateway.BudgetExceeded):
            gateway.GlobalSpend(path, 5.0, floor_usd=bad)
        with pytest.raises(gateway.BudgetExceeded):
            gateway.GlobalSpend(path, 5.0).reserve(bad, "x")
        with pytest.raises(gateway.BudgetExceeded):
            gateway.BudgetLedger(None, RunCaps(), kind="included_credits", max_usd=5.0, price_in_per_mtok=bad,
                                 price_out_per_mtok=P_OUT)
    spend = gateway.GlobalSpend(path, 5.0)
    token = spend.reserve(0.1, "x")
    with pytest.raises(ValueError):
        spend.reconcile(token, float("inf"))
    assert spend.settle(token, float("nan")) is True  # an unusable amount is settled at the reserved worst case
    assert spend.snapshot()["spent_usd"] == pytest.approx(0.1)
    with pytest.raises(gateway.BudgetExceeded):
        gateway.BudgetLedger(None, RunCaps(max_calls=0), kind="local")
    assert not path.with_name("spend.json.tmp").exists()


# ----------------------------------------------------------------- the ledger is carried forward, never reset
V1 = {"spent_usd": 2.922403, "calls": 91, "reservations": {"old-1": {"usd": 0.31, "ts": 1.0, "what": "pilot:lead"}},
      "log": [{"ts": 1.0, "usd": 0.37, "what": "hero:lead", "model": "claude-opus-5-5"}]}


def test_an_existing_ledger_keeps_its_spend_through_format_model_and_price_changes(tmp_path):
    path = tmp_path / "spend.json"
    path.write_text(json.dumps(V1))
    spend = gateway.GlobalSpend(path, 20.0, limit_usd=19.5)
    snap = spend.snapshot()
    assert snap["spent_usd"] == 2.922403 and snap["calls"] == 91
    assert snap["reserved_usd"] == pytest.approx(0.31)  # an old open reservation is kept, however old it is
    assert snap["remaining_to_limit_usd"] == pytest.approx(19.5 - 2.922403 - 0.31)
    assert snap["demo_reserve_held_usd"] == pytest.approx(0.5)

    # a cheaper model at different prices adds to the same total; history is not repriced
    cheap = gateway.BudgetLedger(None, RunCaps(), kind="included_credits", max_usd=20.0, price_in_per_mtok=0.10,
                                 price_out_per_mtok=0.50, global_spend=spend, max_tokens_per_call=3000, model="anthropic:cheap")
    gateway.wrap(_probe(), cheap, "lead-investigator", counter=_fixed(1000)).invoke("x")
    saved = json.loads(path.read_text())
    assert saved["version"] == gateway.LEDGER_VERSION and saved["calls"] == 92
    assert saved["spent_usd"] == pytest.approx(2.922403 + (1000 * 0.10 + 200 * 0.50) / 1e6)
    assert saved["log"][0]["model"] == "claude-opus-5-5" and saved["log"][-1]["model"] == "anthropic:cheap"


def test_a_missing_ledger_starts_from_the_recorded_floor_and_a_damaged_one_blocks_spending(tmp_path):
    fresh = gateway.GlobalSpend(tmp_path / "new" / "spend.json", 20.0, floor_usd=2.922403)
    assert fresh.snapshot()["spent_usd"] == 2.922403 and fresh.snapshot()["carried_forward_usd"] == 2.922403
    low = tmp_path / "low.json"
    low.write_text(json.dumps({"spent_usd": 1.0, "calls": 3, "reservations": {}, "log": []}))
    assert gateway.GlobalSpend(low, 20.0, floor_usd=2.922403).snapshot()["spent_usd"] == 2.922403  # never below known spend

    for text in ("{ this is not json", "", "[1, 2, 3]", json.dumps({"spent_usd": "lots"}), json.dumps({"spent_usd": float("nan")})):
        bad = tmp_path / "bad.json"
        bad.write_text(text)
        spend = gateway.GlobalSpend(bad, 20.0)
        with pytest.raises(gateway.LedgerError):
            spend.reserve(0.01, "x")
        with pytest.raises(gateway.BudgetExceeded):  # a LedgerError stops a run exactly like a reached cap
            spend.snapshot()
        assert bad.read_text() == text  # and the damaged file is left for a human, not overwritten with zeros


def test_the_ledger_path_is_configurable_absolute_and_shared(tmp_path):
    env = {"RUNTIME_MODE": "live", "LIVE_PROVIDER_KIND": "included_credits", "LEAD_MODEL": "anthropic:m",
           "LLM_MAX_USD": "5", "LLM_PRICE_IN_PER_MTOK": "4", "LLM_PRICE_OUT_PER_MTOK": "20",
           "ALIBI_SPEND_LEDGER": str(tmp_path / "shared" / "spend.json"), "LLM_SPEND_FLOOR_USD": "2.5"}
    settings = load_settings(env, dotenv=False)
    assert settings.spend_ledger_path == tmp_path / "shared" / "spend.json"
    a, b = gateway.global_spend_for(settings), gateway.global_spend_for(settings)  # e.g. two worktrees
    a.settle(a.reserve(0.2, "one"), 0.2)
    assert b.snapshot()["spent_usd"] == pytest.approx(2.7)
    assert gateway.global_spend_for(load_settings({"RUNTIME_MODE": "offline"}, dotenv=False)) is None


# ----------------------------------------------------------------- development ceiling and demo reserve
def test_automatic_calls_stop_at_the_development_ceiling_until_an_operator_opens_the_reserve(tmp_path):
    env = {"RUNTIME_MODE": "live", "LIVE_PROVIDER_KIND": "included_credits", "LEAD_MODEL": "anthropic:m",
           "LLM_MAX_USD": "5", "LLM_PRICE_IN_PER_MTOK": "4", "LLM_PRICE_OUT_PER_MTOK": "20",
           "ALIBI_SPEND_LEDGER": str(tmp_path / "spend.json"), "LLM_SPEND_FLOOR_USD": "4.40"}
    settings = load_settings(env, dotenv=False)
    assert settings.dev_ceiling_usd == 4.5 and settings.spend_limit_usd == 4.5
    dev = gateway.global_spend_for(settings)
    with pytest.raises(gateway.BudgetExceeded) as err:
        dev.reserve(0.15, "evaluation run")  # 4.40 + 0.15 > 4.50, though the cap is 5.00
    assert "development ceiling" in str(err.value) and "ALIBI_USE_DEMO_RESERVE" in str(err.value)
    demo_settings = load_settings({**env, "ALIBI_USE_DEMO_RESERVE": "1"}, dotenv=False)
    assert demo_settings.spend_limit_usd == 5.0
    demo = gateway.global_spend_for(demo_settings)
    token = demo.reserve(0.15, "judge's live request")
    with pytest.raises(gateway.BudgetExceeded) as err:
        demo.reserve(0.50, "past the absolute cap")
    assert "LLM_MAX_USD" in str(err.value) and "not authorized" in str(err.value)
    demo.settle(token, 0.09)
    assert load_settings({**env, "LLM_MAX_USD": "20"}, dotenv=False).dev_ceiling_usd == 19.5
    assert settings.public_dict()["dev_ceiling_usd"] == 4.5


def test_one_price_pair_means_one_model_for_every_role():
    base = {"RUNTIME_MODE": "live", "LIVE_PROVIDER_KIND": "included_credits", "LLM_MAX_USD": "5",
            "LLM_PRICE_IN_PER_MTOK": "0.10", "LLM_PRICE_OUT_PER_MTOK": "0.50", "LEAD_MODEL": "anthropic:small"}
    assert load_settings(base, dotenv=False).live_block_reason() is None
    mixed = load_settings({**base, "SUBAGENT_MODEL": "anthropic:large"}, dotenv=False)
    assert "same model" in (mixed.live_block_reason() or "")
    with pytest.raises(gateway.RuntimeBlocked):
        gateway.live_chat_model(mixed, "anthropic:large")
    unpriced = load_settings({**base, "LLM_PRICE_IN_PER_MTOK": "0"}, dotenv=False)
    assert unpriced.live_block_reason() is not None  # an unknown price is never treated as free


# ----------------------------------------------------------------- operator CLI
def test_spend_command_shows_and_reconciles_without_calling_a_model(tmp_path, monkeypatch, capsys):
    from alibi import cli

    path = tmp_path / "spend.json"
    for key, value in {"RUNTIME_MODE": "live", "LIVE_PROVIDER_KIND": "included_credits", "LEAD_MODEL": "anthropic:m",
                       "SUBAGENT_MODEL": "", "ADVERSARY_MODEL": "", "LLM_MAX_USD": "5", "LLM_PRICE_IN_PER_MTOK": "4",
                       "LLM_PRICE_OUT_PER_MTOK": "20", "ALIBI_SPEND_LEDGER": str(path), "LLM_SPEND_FLOOR_USD": "0",
                       "LLM_DEV_CEILING_USD": "", "ALIBI_USE_DEMO_RESERVE": ""}.items():
        monkeypatch.setenv(key, value)
    spend = gateway.GlobalSpend(path, 5.0, limit_usd=4.5)
    token = spend.reserve(0.25, "lost call")
    spend.mark_uncertain(token, "timeout")
    assert cli.main(["spend"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["unreconciled_usd"] == 0.25 and shown["limit_in_force_usd"] == 4.5 and shown["cap_usd"] == 5.0
    assert cli.main(["spend", "--reconcile", token]) == 2  # an amount is required; nothing is guessed
    assert cli.main(["spend", "--reconcile", "no-such-token", "--actual", "0"]) == 2
    capsys.readouterr()
    assert cli.main(["spend", "--reconcile", token, "--actual", "0.04", "--note", "console"]) == 0
    assert gateway.GlobalSpend(path, 5.0).snapshot()["spent_usd"] == pytest.approx(0.04)
    assert gateway.GlobalSpend(path, 5.0).snapshot()["unreconciled_usd"] == 0


def test_spend_endpoint_shows_totals_only_and_says_when_nothing_can_be_spent(tmp_path):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from alibi.api.app import create_app
    from alibi.orchestrator import Orchestrator

    off = replace(load_settings({}, dotenv=False), runs_dir=tmp_path / "r0", sealed_dir=tmp_path / "s0")
    c0 = TestClient(create_app(off, Orchestrator(off, pace_s=0.0)))
    assert c0.get("/api/spend").json() == {"configured": False,
                                           "note": "no billed model route is configured; nothing can be spent"}
    env = {"RUNTIME_MODE": "live", "LIVE_PROVIDER_KIND": "included_credits", "LEAD_MODEL": "anthropic:m",
           "LLM_MAX_USD": "5", "LLM_PRICE_IN_PER_MTOK": "4", "LLM_PRICE_OUT_PER_MTOK": "20",
           "ALIBI_SPEND_LEDGER": str(tmp_path / "spend.json"), "LLM_SPEND_FLOOR_USD": "1.25"}
    live = replace(load_settings(env, dotenv=False), runs_dir=tmp_path / "r1", sealed_dir=tmp_path / "s1")
    spend = gateway.global_spend_for(live)
    held = spend.reserve(0.10, "investigation:lead-investigator", "anthropic:m")
    lost = spend.reserve(0.20, "question:case-x")
    spend.mark_uncertain(lost, "timeout")
    c1 = TestClient(create_app(live, Orchestrator(live, pace_s=0.0)))
    got = c1.get("/api/spend").json()
    assert got["configured"] is True and got["readable"] is True
    assert (got["cap_usd"], got["limit_in_force_usd"], got["spent_usd"]) == (5.0, 4.5, 1.25)
    assert got["unreconciled_usd"] == 0.2 and got["reserved_usd"] == 0.1 and got["committed_usd"] == pytest.approx(1.55)
    assert got["open_reservations"] == 1 and got["unreconciled_items"] == 1
    blob = json.dumps(got)
    assert held not in blob and lost not in blob and "investigation:" not in blob and "log" not in got  # totals only
    (tmp_path / "spend.json").write_text("{ broken")
    bad = c1.get("/api/spend").json()
    assert bad["readable"] is False and "no model call will be made" in bad["note"]
