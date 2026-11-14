"""The one budget gateway every model call passes through (PLAN 2.10, 10.5).

* Offline mode constructs no network model at all.
* A shared, persisted, thread-safe ledger enforces per-investigation caps on calls,
  tokens, wall time and (for included credits) estimated cost. It reserves before a
  call and commits after it, and counts failed calls.
* Unknown pricing or a credential/credit error disables the route. There is no
  automatic switch to another provider and no unbounded retry.
* Paid overage is never authorized. LLM_MAX_USD caps consumption of *included*
  credits only.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, Field

from alibi.config import REPO_ROOT, RunCaps, Settings
from alibi.contracts import Usage
from alibi.runners import RuntimeBlocked  # noqa: F401 - re-exported

GATEWAY_PROVIDER = "alibi_gateway"
SCRIPTED_TURN_CAP = 80
SPEND_PATH = REPO_ROOT / ".alibi" / "spend.json"
STALE_RESERVATION_S = 900
CACHE_WRITE_MULTIPLIER = 1.25  # conservative: 5-minute cache writes
CACHE_READ_MULTIPLIER = 0.10  # conservative upper bound for cache reads


class BudgetExceeded(RuntimeError):
    """A cap was reached. The run stops; it is reported as censored, never retried silently."""


class ModelRefused(RuntimeError):
    """The model declined the request (stop_reason == "refusal"). Recorded, never retried or rerouted."""


def call_cost_usd(tokens_in: int, tokens_out: int, cache_read: int, cache_write: int,
                  price_in: float, price_out: float) -> float:
    """Estimated cost of one call at documented rates. tokens_in is the TOTAL input (cached included)."""
    base = max(0, tokens_in - cache_read - cache_write)
    return (base * price_in + cache_write * price_in * CACHE_WRITE_MULTIPLIER
            + cache_read * price_in * CACHE_READ_MULTIPLIER + tokens_out * price_out) / 1_000_000


class GlobalSpend:
    """One persisted, cross-process spend ledger for EVERYTHING that calls a billed model.

    LLM_MAX_USD is a cap on this total (smoke tests, adversary planning, every investigation,
    the pilot), not a per-run allowance. Reservations are taken under an exclusive file lock
    before a call and settled after it, so parallel calls cannot jointly overshoot the cap.
    """

    def __init__(self, path: Path, cap_usd: float):
        self.path = Path(path)
        self.cap_usd = float(cap_usd)

    def _locked(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        import fcntl

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.seek(0)
                raw = fh.read().strip()
                state = json.loads(raw) if raw else {"spent_usd": 0.0, "calls": 0, "reservations": {}, "log": []}
                now = time.time()
                state["reservations"] = {k: v for k, v in state["reservations"].items()
                                         if now - v["ts"] < STALE_RESERVATION_S}
                out = fn(state)
                fh.seek(0)
                fh.truncate()
                fh.write(json.dumps(state))
                fh.flush()
                return out
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def reserve(self, usd: float, what: str) -> str:
        def _do(state: dict[str, Any]) -> str:
            held = sum(v["usd"] for v in state["reservations"].values())
            if state["spent_usd"] + held + usd > self.cap_usd + 1e-9:
                raise BudgetExceeded(
                    f"total spend cap reached: ${state['spent_usd']:.4f} spent + ${held:.4f} reserved + "
                    f"${usd:.4f} needed > LLM_MAX_USD=${self.cap_usd:.2f}. Paid overage is not authorized.")
            token = f"{os.getpid()}-{time.time_ns()}"
            state["reservations"][token] = {"usd": usd, "ts": time.time(), "what": what}
            return token
        return self._locked(_do)

    def settle(self, token: str, actual_usd: float, what: str, model: str | None = None) -> None:
        def _do(state: dict[str, Any]) -> None:
            state["reservations"].pop(token, None)
            state["spent_usd"] = round(state["spent_usd"] + actual_usd, 6)
            state["calls"] += 1
            state["log"] = (state["log"] + [{"ts": time.time(), "usd": round(actual_usd, 6), "what": what,
                                             "model": model}])[-400:]
        self._locked(_do)

    def snapshot(self) -> dict[str, Any]:
        def _do(state: dict[str, Any]) -> dict[str, Any]:
            held = sum(v["usd"] for v in state["reservations"].values())
            return {"cap_usd": self.cap_usd, "spent_usd": state["spent_usd"], "reserved_usd": round(held, 6),
                    "remaining_usd": round(self.cap_usd - state["spent_usd"] - held, 6), "calls": state["calls"]}
        return self._locked(_do)


@dataclass
class Reservation:
    """A held slot for one model call: its worst-case cost and the matching total-spend reservation."""

    usd: float = 0.0
    global_token: str | None = None


class BudgetLedger:
    """Atomic usage ledger for one investigation, persisted so a restart cannot reset it."""

    def __init__(self, path: Path | None, caps: RunCaps, *, kind: str = "scripted", max_usd: float = 0.0,
                 price_in_per_mtok: float | None = None, price_out_per_mtok: float | None = None,
                 global_spend: "GlobalSpend | None" = None, max_tokens_per_call: int | None = None,
                 label: str = "investigation"):
        self.path = path
        self.caps = caps
        self.kind = kind  # scripted | local | included_credits
        self.max_usd = max_usd
        self.price_in = price_in_per_mtok
        self.price_out = price_out_per_mtok
        self.global_spend = global_spend
        self.max_tokens_per_call = max_tokens_per_call
        self.label = label
        self._lock = threading.Lock()
        self.state: dict[str, Any] = {
            "kind": kind, "llm_calls": 0, "scripted_turns": 0, "reserved": 0, "tokens_in": 0, "tokens_out": 0,
            "tokens_cache_read": 0, "cost_usd": 0.0, "reserved_usd": 0.0, "retries": 0, "errors": 0,
            "tool_calls": 0, "started": None, "disabled_reason": None, "by_role": {},
            "tokens_cache_write": 0, "truncated_calls": 0, "refusals": 0, "models": [],
        }
        if path is not None and path.exists():
            self.state.update(json.loads(path.read_text(encoding="utf-8")))
            self.state["reserved"] = 0  # reservations of a dead process are released, spend is kept
            self.state["reserved_usd"] = 0.0

    def _persist(self) -> None:
        if self.path is None:
            return
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state), encoding="utf-8")
        os.replace(tmp, self.path)

    def _worst_case_call_usd(self) -> float:
        if self.kind != "included_credits":
            return 0.0
        left_in = min(max(0, self.caps.max_input_tokens - self.state["tokens_in"]), self.caps.max_input_tokens_per_call)
        left_out = max(0, self.caps.max_output_tokens - self.state["tokens_out"])
        if self.max_tokens_per_call:
            left_out = min(left_out, self.max_tokens_per_call)
        # worst case for ONE call: all remaining input written to cache, a full-length response
        return (left_in * (self.price_in or 0) * CACHE_WRITE_MULTIPLIER + left_out * (self.price_out or 0)) / 1_000_000

    def reserve(self, role: str) -> "Reservation":
        """Reserve one call before making it. Raises BudgetExceeded when any cap would be passed."""
        with self._lock:
            s = self.state
            if s["disabled_reason"]:
                raise BudgetExceeded(f"model route disabled: {s['disabled_reason']}")
            if s["started"] is None:
                s["started"] = time.time()
            if self.kind == "scripted":
                if s["scripted_turns"] + s["reserved"] >= SCRIPTED_TURN_CAP:
                    raise BudgetExceeded(f"scripted turn cap ({SCRIPTED_TURN_CAP}) reached")
                s["reserved"] += 1
                self._persist()
                return Reservation(usd=0.0)
            if time.time() - s["started"] > self.caps.max_seconds:
                raise BudgetExceeded(f"time cap reached ({self.caps.max_seconds:.0f} s per investigation)")
            if s["llm_calls"] + s["reserved"] >= self.caps.max_calls:
                raise BudgetExceeded(f"call cap reached ({self.caps.max_calls} model calls per investigation)")
            if s["tokens_in"] >= self.caps.max_input_tokens:
                raise BudgetExceeded(f"input token cap reached ({self.caps.max_input_tokens})")
            if s["tokens_out"] >= self.caps.max_output_tokens:
                raise BudgetExceeded(f"output token cap reached ({self.caps.max_output_tokens})")
            hold = self._worst_case_call_usd()
            token = None
            if self.kind == "included_credits":
                if self.price_in is None or self.price_out is None:
                    raise BudgetExceeded("unknown pricing: billed routes stay disabled rather than guessing")
                if s["cost_usd"] + s["reserved_usd"] + hold > self.max_usd:
                    raise BudgetExceeded(f"credit cap reached (LLM_MAX_USD={self.max_usd}); paid overage is not authorized")
                if self.global_spend is not None:
                    token = self.global_spend.reserve(hold, f"{self.label}:{role}")
            s["reserved"] += 1
            s["reserved_usd"] += hold
            self._persist()
            return Reservation(usd=hold, global_token=token)

    def commit(self, role: str, hold: "Reservation", *, tokens_in: int = 0, tokens_out: int = 0, cache_read: int = 0,
               cache_write: int = 0, ok: bool = True, retried: bool = False, truncated: bool = False,
               refused: bool = False, model: str | None = None) -> None:
        with self._lock:
            s = self.state
            s["reserved"] = max(0, s["reserved"] - 1)
            s["reserved_usd"] = max(0.0, s["reserved_usd"] - hold.usd)
            by = s["by_role"].setdefault(role, {"calls": 0, "tokens_in": 0, "tokens_out": 0})
            by["calls"] += 1
            if self.kind == "scripted":
                s["scripted_turns"] += 1
            else:
                s["llm_calls"] += 1  # failed calls count: they may be chargeable
                s["tokens_in"] += tokens_in
                s["tokens_out"] += tokens_out
                s["tokens_cache_read"] += cache_read
                s["tokens_cache_write"] += cache_write
                s["truncated_calls"] += int(truncated)
                s["refusals"] += int(refused)
                by["tokens_in"] += tokens_in
                by["tokens_out"] += tokens_out
                if model and model not in s["models"]:
                    s["models"].append(model)
                cost = 0.0
                if self.kind == "included_credits":
                    cost = call_cost_usd(tokens_in, tokens_out, cache_read, cache_write,
                                         self.price_in or 0, self.price_out or 0)
                    s["cost_usd"] += cost
                if self.global_spend is not None and hold.global_token is not None:
                    self.global_spend.settle(hold.global_token, cost, f"{self.label}:{role}", model)
            if not ok:
                s["errors"] += 1
            if retried:
                s["retries"] += 1
            self._persist()

    def disable(self, reason: str) -> None:
        with self._lock:
            self.state["disabled_reason"] = reason
            self._persist()

    def count_tool_call(self) -> None:
        with self._lock:
            self.state["tool_calls"] += 1
            self._persist()

    def usage(self, wall_seconds: float | None = None) -> Usage:
        s = self.state
        return Usage(llm_calls=s["llm_calls"], tokens_in=s["tokens_in"], tokens_out=s["tokens_out"],
                     tokens_cache_read=s["tokens_cache_read"], cost_estimate_usd=round(s["cost_usd"], 6),
                     wall_seconds=wall_seconds, tool_calls=s["tool_calls"], scripted_turns=s["scripted_turns"],
                     retries=s["retries"], errors=s["errors"])


_AUTH_MARKERS = ("401", "403", "authentication", "unauthorized", "permission", "credit", "billing", "quota", "payment")
_TRANSIENT_MARKERS = ("timeout", "timed out", "429", "overloaded", "503", "502", "500", "connection", "temporar")


def classify_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if any(m in text for m in _AUTH_MARKERS):
        return "fatal"
    if any(m in text for m in _TRANSIENT_MARKERS):
        return "transient"
    return "other"


class BudgetedChatModel(BaseChatModel):
    """Wraps any chat model (scripted or real) so that every call is reserved and accounted."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    inner: Any
    ledger: Any
    role: str = "lead-investigator"
    bound: Any = None
    on_bind: Any = Field(default=None, exclude=True)  # Callable[[str, list[str]], None]
    retry_sleep_s: float = 2.0

    @property
    def _llm_type(self) -> str:
        return "alibi-budget-gateway"

    def _get_ls_params(self, stop: list[str] | None = None, **kwargs: Any) -> Any:
        params = super()._get_ls_params(stop=stop, **kwargs)
        params["ls_provider"] = GATEWAY_PROVIDER  # selects the ALIBI harness profile
        return params

    def bind_tools(self, tools: Any, **kwargs: Any) -> "BudgetedChatModel":
        names = [getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else getattr(t, "__name__", "?"))
                 for t in tools]
        if self.on_bind is not None:
            self.on_bind(self.role, names)
        return self.model_copy(update={"bound": self.inner.bind_tools(tools, **kwargs)})

    def _call(self, messages: list[BaseMessage], stop: list[str] | None) -> AIMessage:
        target = self.bound if self.bound is not None else self.inner
        kwargs: dict[str, Any] = {}
        if stop:
            kwargs["stop"] = stop
        if getattr(self.inner, "_llm_type", None) == "anthropic-chat":
            # top-level automatic prompt caching: the agent loop resends a growing prefix every turn
            kwargs["cache_control"] = {"type": "ephemeral"}
        out = target.invoke(messages, **kwargs)
        if not isinstance(out, AIMessage):
            out = AIMessage(content=str(getattr(out, "content", out)))
        return out

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        attempt = 0
        while True:
            hold = self.ledger.reserve(self.role)
            try:
                ai = self._call(messages, stop)
            except BudgetExceeded:
                self.ledger.commit(self.role, hold, ok=False)
                raise
            except Exception as exc:  # noqa: BLE001
                kind = classify_error(exc)
                self.ledger.commit(self.role, hold, ok=False, retried=attempt > 0)
                if kind == "fatal":
                    self.ledger.disable(f"{type(exc).__name__}: credential/credit error; route disabled, no fallback provider")
                    raise
                if kind == "transient" and attempt == 0:  # exactly one bounded retry
                    attempt += 1
                    time.sleep(self.retry_sleep_s)
                    continue
                raise
            um = getattr(ai, "usage_metadata", None) or {}
            details = (um.get("input_token_details") or {}) if isinstance(um, dict) else {}
            cache_read = int(details.get("cache_read") or 0)
            cache_write = int((details.get("ephemeral_5m_input_tokens") or 0) + (details.get("ephemeral_1h_input_tokens") or 0)
                              or details.get("cache_creation") or 0)
            meta = getattr(ai, "response_metadata", None) or {}
            stop_reason = meta.get("stop_reason")
            refused = stop_reason == "refusal"
            self.ledger.commit(self.role, hold, tokens_in=int(um.get("input_tokens", 0) or 0),
                               tokens_out=int(um.get("output_tokens", 0) or 0), cache_read=cache_read,
                               cache_write=cache_write, ok=not refused, retried=attempt > 0,
                               truncated=stop_reason == "max_tokens", refused=refused,
                               model=meta.get("model_name") or meta.get("model"))
            if refused:
                category = (meta.get("stop_details") or {}).get("category") if isinstance(meta.get("stop_details"), dict) else None
                raise ModelRefused(f"the model declined this request (safety classifier category: {category or 'not given'})")
            return ChatResult(generations=[ChatGeneration(message=ai)])


def global_spend_for(settings: Settings) -> "GlobalSpend | None":
    """The cross-run spend ledger. Only billed (included-credit) routes have one."""
    if settings.live_provider_kind != "included_credits":
        return None
    return GlobalSpend(SPEND_PATH, settings.llm_max_usd)


def make_ledger(settings: Settings, path: Path | None, *, scripted: bool, label: str = "investigation",
                caps: RunCaps | None = None) -> BudgetLedger:
    if scripted:
        return BudgetLedger(path, settings.caps, kind="scripted")
    return BudgetLedger(path, caps or settings.caps, kind=settings.live_provider_kind or "local",
                        max_usd=settings.llm_max_usd, price_in_per_mtok=settings.price_in_per_mtok,
                        price_out_per_mtok=settings.price_out_per_mtok, global_spend=global_spend_for(settings),
                        max_tokens_per_call=settings.max_tokens_per_call, label=label)


def live_model_kwargs(model_spec: str, settings: Settings, env: Any = None) -> dict[str, Any]:
    """Provider-specific construction arguments for a live model. Pure, so it can be tested offline.

    Anthropic (current models): sampling parameters such as temperature are rejected, thinking is
    adaptive and cannot be given a token budget, so depth is controlled with reasoning effort only.
    The SDK's own retries are off because the gateway does the single bounded retry and must see
    (and account for) every attempt.
    Ollama: a small default context window silently truncates the agent harness prompt (reported in
    a field note for deepagents 0.7.38; not verified on this machine), so num_ctx is set explicitly.
    """
    env = os.environ if env is None else env
    out_cap = min(settings.max_tokens_per_call, settings.caps.max_output_tokens)
    provider = model_spec.split(":", 1)[0]
    if provider == "ollama":
        raw = str(env.get("LLM_NUM_CTX") or "").strip()
        return {"temperature": 0, "num_ctx": int(raw) if raw.isdigit() else 16384, "num_predict": out_cap}
    if provider == "anthropic":
        return {"max_tokens": out_cap, "timeout": min(120.0, max(30.0, settings.caps.max_seconds)), "max_retries": 0,
                "reasoning_effort": settings.effort}
    return {"temperature": 0, "max_tokens": out_cap, "timeout": min(60.0, settings.caps.max_seconds), "max_retries": 0}


def live_chat_model(settings: Settings, model_spec: str) -> BaseChatModel:
    """Construct a real model. Refused unless a zero-charge route is explicitly configured."""
    reason = settings.live_block_reason()
    if reason is not None:
        raise RuntimeBlocked(reason)
    from langchain.chat_models import init_chat_model

    return init_chat_model(model_spec, **live_model_kwargs(model_spec, settings))


def wrap(inner: BaseChatModel, ledger: BudgetLedger, role: str,
         on_bind: Callable[[str, list[str]], None] | None = None) -> BudgetedChatModel:
    return BudgetedChatModel(inner=inner, ledger=ledger, role=role, on_bind=on_bind)
