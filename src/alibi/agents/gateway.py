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
from pathlib import Path
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, Field

from alibi.config import RunCaps, Settings
from alibi.contracts import Usage
from alibi.runners import RuntimeBlocked  # noqa: F401 - re-exported

GATEWAY_PROVIDER = "alibi_gateway"
SCRIPTED_TURN_CAP = 80


class BudgetExceeded(RuntimeError):
    """A cap was reached. The run stops; it is reported as censored, never retried silently."""


class BudgetLedger:
    """Atomic usage ledger for one investigation, persisted so a restart cannot reset it."""

    def __init__(self, path: Path | None, caps: RunCaps, *, kind: str = "scripted", max_usd: float = 0.0,
                 price_in_per_mtok: float | None = None, price_out_per_mtok: float | None = None):
        self.path = path
        self.caps = caps
        self.kind = kind  # scripted | local | included_credits
        self.max_usd = max_usd
        self.price_in = price_in_per_mtok
        self.price_out = price_out_per_mtok
        self._lock = threading.Lock()
        self.state: dict[str, Any] = {
            "kind": kind, "llm_calls": 0, "scripted_turns": 0, "reserved": 0, "tokens_in": 0, "tokens_out": 0,
            "tokens_cache_read": 0, "cost_usd": 0.0, "reserved_usd": 0.0, "retries": 0, "errors": 0,
            "tool_calls": 0, "started": None, "disabled_reason": None, "by_role": {},
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
        left_in = max(0, self.caps.max_input_tokens - self.state["tokens_in"])
        left_out = max(0, self.caps.max_output_tokens - self.state["tokens_out"])
        return (left_in * (self.price_in or 0) + left_out * (self.price_out or 0)) / 1_000_000

    def reserve(self, role: str) -> float:
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
                return 0.0
            if time.time() - s["started"] > self.caps.max_seconds:
                raise BudgetExceeded(f"time cap reached ({self.caps.max_seconds:.0f} s per investigation)")
            if s["llm_calls"] + s["reserved"] >= self.caps.max_calls:
                raise BudgetExceeded(f"call cap reached ({self.caps.max_calls} model calls per investigation)")
            if s["tokens_in"] >= self.caps.max_input_tokens:
                raise BudgetExceeded(f"input token cap reached ({self.caps.max_input_tokens})")
            if s["tokens_out"] >= self.caps.max_output_tokens:
                raise BudgetExceeded(f"output token cap reached ({self.caps.max_output_tokens})")
            hold = self._worst_case_call_usd()
            if self.kind == "included_credits":
                if self.price_in is None or self.price_out is None:
                    raise BudgetExceeded("unknown pricing: billed routes stay disabled rather than guessing")
                if s["cost_usd"] + s["reserved_usd"] + hold > self.max_usd:
                    raise BudgetExceeded(f"credit cap reached (LLM_MAX_USD={self.max_usd}); paid overage is not authorized")
            s["reserved"] += 1
            s["reserved_usd"] += hold
            self._persist()
            return hold

    def commit(self, role: str, hold: float, *, tokens_in: int = 0, tokens_out: int = 0, cache_read: int = 0,
               ok: bool = True, retried: bool = False) -> None:
        with self._lock:
            s = self.state
            s["reserved"] = max(0, s["reserved"] - 1)
            s["reserved_usd"] = max(0.0, s["reserved_usd"] - hold)
            by = s["by_role"].setdefault(role, {"calls": 0, "tokens_in": 0, "tokens_out": 0})
            by["calls"] += 1
            if self.kind == "scripted":
                s["scripted_turns"] += 1
            else:
                s["llm_calls"] += 1  # failed calls count: they may be chargeable
                s["tokens_in"] += tokens_in
                s["tokens_out"] += tokens_out
                s["tokens_cache_read"] += cache_read
                by["tokens_in"] += tokens_in
                by["tokens_out"] += tokens_out
                if self.kind == "included_credits":
                    s["cost_usd"] += (tokens_in * (self.price_in or 0) + tokens_out * (self.price_out or 0)) / 1_000_000
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
        out = target.invoke(messages, stop=stop) if stop else target.invoke(messages)
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
            cache = (um.get("input_token_details") or {}).get("cache_read", 0) if isinstance(um, dict) else 0
            self.ledger.commit(self.role, hold, tokens_in=int(um.get("input_tokens", 0) or 0),
                               tokens_out=int(um.get("output_tokens", 0) or 0), cache_read=int(cache or 0),
                               ok=True, retried=attempt > 0)
            return ChatResult(generations=[ChatGeneration(message=ai)])


def make_ledger(settings: Settings, path: Path | None, *, scripted: bool) -> BudgetLedger:
    if scripted:
        return BudgetLedger(path, settings.caps, kind="scripted")
    return BudgetLedger(path, settings.caps, kind=settings.live_provider_kind or "local", max_usd=settings.llm_max_usd,
                        price_in_per_mtok=settings.price_in_per_mtok, price_out_per_mtok=settings.price_out_per_mtok)


def live_model_kwargs(model_spec: str, settings: Settings, env: Any = None) -> dict[str, Any]:
    """Provider-specific construction arguments for a live model. Pure, so it can be tested offline.

    Ollama: a small default context window silently truncates the agent harness prompt (reported in a
    field note for deepagents 0.7.38; not verified on this machine), so num_ctx is set explicitly
    (LLM_NUM_CTX, default 16384) and the output cap uses Ollama's own parameter name.
    """
    env = os.environ if env is None else env
    out_cap = min(1500, settings.caps.max_output_tokens)
    if model_spec.split(":", 1)[0] == "ollama":
        raw = str(env.get("LLM_NUM_CTX") or "").strip()
        return {"temperature": 0, "num_ctx": int(raw) if raw.isdigit() else 16384, "num_predict": out_cap}
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
