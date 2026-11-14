"""The one budget gateway every model call passes through (PLAN 2.10, 10.5; phase-two review).

What it guarantees, and what it does not:

* Offline mode constructs no network model at all.
* Before a billed call is sent, the outgoing request (system prompt, tool schemas, messages) is
  COUNTED and compared with an enforced per-request ceiling. A request that cannot be counted is
  not sent.
* Input tokens, output tokens and money are reserved atomically, so parallel specialists cannot
  jointly pass a cap. The provider's output limit for the call is clamped to the output tokens
  that were actually reserved.
* A call whose billing outcome is unknown (timeout, lost response, missing usage, crashed
  process) keeps its WORST-CASE cost on the books until an operator reconciles it. Age never
  frees money. Settlement is idempotent.
* One persisted, file-locked ledger holds the cumulative total across runs, processes, branches
  and models. It is carried forward on format changes, fails closed if unreadable, and stores
  dollars as they were estimated at the time (history is never repriced).
* Automatic calls stop at a development ceiling beneath the absolute cap; only an explicit
  operator switch opens the remaining demo reserve.

The ledger is a conservative ESTIMATE at configured list prices. It is not the provider's bill;
the provider console is the authority on actual charges. Paid overage is never authorized.
"""

from __future__ import annotations

import json
import math
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
LEDGER_VERSION = 2
CACHE_WRITE_MULTIPLIER = 1.25  # conservative: 5-minute cache writes
CACHE_READ_MULTIPLIER = 0.10  # conservative upper bound for cache reads
MIN_OUTPUT_TOKENS = 256  # below this a response is likely to be cut off mid tool call
DEFAULT_MAX_TOKENS_PER_CALL = 3000
COUNT_HEADROOM = 1.05  # provider count plus 5% ...
COUNT_PAD = 256  # ... plus a fixed pad for request framing
UNCLAMPABLE_TYPES = {"chat-ollama"}  # output limit is fixed when the client is built (num_predict)
SETTLED_MEMORY = 5000  # recent settled reservation ids kept for idempotency


class BudgetExceeded(RuntimeError):
    """A cap was reached. The run stops; it is reported as censored, never retried silently."""


class LedgerError(BudgetExceeded):
    """The cumulative ledger cannot be read or written. Nothing is spent while that is true."""


class ModelRefused(RuntimeError):
    """The model declined the request (stop_reason == "refusal"). Recorded, never retried or rerouted."""


def call_cost_usd(tokens_in: int, tokens_out: int, cache_read: int, cache_write: int,
                  price_in: float, price_out: float) -> float:
    """Estimated cost of one call at configured rates. tokens_in is the TOTAL input (cached included)."""
    base = max(0, tokens_in - cache_read - cache_write)
    return (base * price_in + cache_write * price_in * CACHE_WRITE_MULTIPLIER
            + cache_read * price_in * CACHE_READ_MULTIPLIER + tokens_out * price_out) / 1_000_000


def worst_case_usd(tokens_in: int, tokens_out: int, price_in: float, price_out: float) -> float:
    """Upper estimate for one call: every input token written to cache, the full output limit used."""
    return (tokens_in * price_in * CACHE_WRITE_MULTIPLIER + tokens_out * price_out) / 1_000_000


# ----------------------------------------------------------------------------- cumulative ledger


class GlobalSpend:
    """One persisted, cross-process ledger for EVERYTHING that calls a billed model.

    `cap_usd` is the absolute authorization. `limit_usd` is the ceiling in force for this process
    (the development ceiling, or the cap when the operator has opened the demo reserve).

    committed = settled spend + unreconciled worst-case amounts + open reservations.
    A reservation leaves the books in exactly one way: `settle` (known usage), `release` (the
    request was certainly not billed) or `reconcile` (an operator states the real amount).
    """

    def __init__(self, path: Path, cap_usd: float, *, limit_usd: float | None = None, floor_usd: float = 0.0):
        for name, value in (("cap", cap_usd), ("limit", limit_usd if limit_usd is not None else cap_usd),
                            ("floor", floor_usd)):
            if not (isinstance(value, (int, float)) and math.isfinite(value) and value >= 0):
                raise LedgerError(f"spend {name} must be a finite, non-negative number")
        self.path = Path(path)
        self.cap_usd = float(cap_usd)
        self.limit_usd = min(float(cap_usd), float(limit_usd if limit_usd is not None else cap_usd))
        self.floor_usd = float(floor_usd)
        self._seq = 0

    # -- storage ---------------------------------------------------------------
    def _fresh(self) -> dict[str, Any]:
        return {"version": LEDGER_VERSION, "spent_usd": self.floor_usd, "uncertain_usd": 0.0, "calls": 0,
                "reservations": {}, "unreconciled": {}, "settled": [], "log": [],
                "carried_forward_usd": self.floor_usd}

    @staticmethod
    def _migrate(state: dict[str, Any]) -> dict[str, Any]:
        """Carry an older ledger forward. Spend already recorded is never dropped or repriced."""
        state.setdefault("spent_usd", 0.0)
        state.setdefault("calls", 0)
        state.setdefault("reservations", {})
        state.setdefault("log", [])
        state.setdefault("uncertain_usd", 0.0)
        state.setdefault("unreconciled", {})
        state.setdefault("settled", [])
        state.setdefault("carried_forward_usd", 0.0)
        state["version"] = LEDGER_VERSION
        return state

    def _locked(self, fn: Callable[[dict[str, Any]], Any]) -> Any:
        import fcntl

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.with_name(self.path.name + ".lock")
            with open(lock_path, "a+", encoding="utf-8") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    if self.path.exists():
                        raw = self.path.read_text(encoding="utf-8").strip()
                        if not raw:
                            raise LedgerError(f"spend ledger {self.path} is empty; refusing to treat it as zero spend")
                        try:
                            state = self._migrate(json.loads(raw))
                        except (ValueError, TypeError, AttributeError) as exc:
                            raise LedgerError(f"spend ledger {self.path} is unreadable ({type(exc).__name__}); "
                                              "refusing to spend until it is repaired") from exc
                        if not all(isinstance(state[k], (int, float)) and math.isfinite(state[k])
                                   for k in ("spent_usd", "uncertain_usd")):
                            raise LedgerError(f"spend ledger {self.path} holds a non-finite total")
                    else:
                        state = self._fresh()
                    if state["spent_usd"] < self.floor_usd:  # known earlier spend is a floor, never forgotten
                        state["carried_forward_usd"] = self.floor_usd
                        state["spent_usd"] = self.floor_usd
                    before = json.dumps(state, sort_keys=True)
                    out = fn(state)
                    after = json.dumps(state, sort_keys=True)
                    if after != before or not self.path.exists():
                        tmp = self.path.with_name(self.path.name + f".tmp{os.getpid()}")
                        tmp.write_text(json.dumps(state), encoding="utf-8")
                        os.replace(tmp, self.path)  # atomic: a crash cannot leave a half-written ledger
                    return out
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
        except OSError as exc:
            raise LedgerError(f"spend ledger {self.path} cannot be used: {exc}") from exc

    @staticmethod
    def _committed(state: dict[str, Any]) -> float:
        return (state["spent_usd"] + state["uncertain_usd"]
                + sum(v["usd"] for v in state["reservations"].values()))

    def _remember(self, state: dict[str, Any], token: str) -> None:
        state["settled"] = (state["settled"] + [token])[-SETTLED_MEMORY:]

    @staticmethod
    def _note(state: dict[str, Any], **entry: Any) -> None:
        state["log"] = (state["log"] + [{"ts": time.time(), **entry}])[-600:]

    # -- operations ------------------------------------------------------------
    def reserve(self, usd: float, what: str, model: str | None = None) -> str:
        if not (math.isfinite(usd) and usd >= 0):
            raise BudgetExceeded("a reservation must be a finite, non-negative amount")

        def _do(state: dict[str, Any]) -> str:
            committed = self._committed(state)
            if committed + usd > self.limit_usd + 1e-9:
                which = "LLM_MAX_USD" if self.limit_usd >= self.cap_usd else \
                    "the development ceiling (the demo reserve is held back; ALIBI_USE_DEMO_RESERVE=1 opens it)"
                raise BudgetExceeded(
                    f"total spend limit reached: ${committed:.4f} committed (spent ${state['spent_usd']:.4f}, "
                    f"unreconciled ${state['uncertain_usd']:.4f}, reserved "
                    f"${committed - state['spent_usd'] - state['uncertain_usd']:.4f}) + ${usd:.4f} needed > "
                    f"${self.limit_usd:.2f} ({which}). Paid overage is not authorized.")
            self._seq += 1
            token = f"{os.getpid()}-{time.time_ns()}-{self._seq}"
            state["reservations"][token] = {"usd": usd, "ts": time.time(), "what": what, "pid": os.getpid(),
                                            "model": model}
            return token
        return self._locked(_do)

    def settle(self, token: str, actual_usd: float, what: str | None = None, model: str | None = None) -> bool:
        """Close a reservation with known usage. Idempotent: a second call changes nothing."""
        def _do(state: dict[str, Any]) -> bool:
            res = state["reservations"].pop(token, None)
            if res is None:
                return False  # already settled, released or moved to unreconciled
            amount = max(0.0, float(actual_usd)) if math.isfinite(actual_usd) else res["usd"]
            state["spent_usd"] = round(state["spent_usd"] + amount, 6)
            state["calls"] += 1
            self._remember(state, token)
            self._note(state, usd=round(amount, 6), what=what or res.get("what"), model=model or res.get("model"))
            return True
        return self._locked(_do)

    def mark_uncertain(self, token: str, reason: str) -> bool:
        """The billing outcome is unknown: keep the worst case on the books until reconciled. Idempotent."""
        def _do(state: dict[str, Any]) -> bool:
            res = state["reservations"].pop(token, None)
            if res is None:
                return False
            state["unreconciled"][token] = {**res, "reason": reason[:200], "marked": time.time()}
            state["uncertain_usd"] = round(state["uncertain_usd"] + res["usd"], 6)
            state["calls"] += 1
            self._note(state, usd=round(res["usd"], 6), what=res.get("what"), model=res.get("model"),
                       uncertain=reason[:120])
            return True
        return self._locked(_do)

    def release(self, token: str, reason: str) -> bool:
        """The request was certainly not billed (never sent, or rejected before processing). Idempotent."""
        def _do(state: dict[str, Any]) -> bool:
            res = state["reservations"].pop(token, None)
            if res is None:
                return False
            self._remember(state, token)
            self._note(state, usd=0.0, what=res.get("what"), model=res.get("model"), released=reason[:120])
            return True
        return self._locked(_do)

    def reconcile(self, token: str, actual_usd: float, note: str = "") -> dict[str, Any]:
        """Operator action: state what an unreconciled or abandoned reservation really cost."""
        if not (math.isfinite(actual_usd) and actual_usd >= 0):
            raise ValueError("the reconciled amount must be a finite, non-negative number")

        def _do(state: dict[str, Any]) -> dict[str, Any]:
            if token in state["unreconciled"]:
                res = state["unreconciled"].pop(token)
                state["uncertain_usd"] = round(max(0.0, state["uncertain_usd"] - res["usd"]), 6)
            elif token in state["reservations"]:
                res = state["reservations"].pop(token)
                state["calls"] += 1
            else:
                raise KeyError(f"no open or unreconciled reservation {token!r}")
            state["spent_usd"] = round(state["spent_usd"] + actual_usd, 6)
            self._remember(state, token)
            self._note(state, usd=round(actual_usd, 6), what=res.get("what"), model=res.get("model"),
                       reconciled_from=round(res["usd"], 6), note=note[:160])
            return {"token": token, "held_usd": res["usd"], "actual_usd": actual_usd}
        return self._locked(_do)

    def snapshot(self) -> dict[str, Any]:
        def _do(state: dict[str, Any]) -> dict[str, Any]:
            now = time.time()
            reserved = sum(v["usd"] for v in state["reservations"].values())
            committed = self._committed(state)
            return {
                "cap_usd": self.cap_usd, "limit_in_force_usd": self.limit_usd,
                "demo_reserve_held_usd": round(self.cap_usd - self.limit_usd, 6),
                "spent_usd": state["spent_usd"], "unreconciled_usd": state["uncertain_usd"],
                "reserved_usd": round(reserved, 6), "committed_usd": round(committed, 6),
                "remaining_to_limit_usd": round(self.limit_usd - committed, 6),
                "remaining_to_cap_usd": round(self.cap_usd - committed, 6),
                "calls": state["calls"], "carried_forward_usd": state.get("carried_forward_usd", 0.0),
                "open_reservations": [{"token": k, "usd": round(v["usd"], 6), "what": v.get("what"),
                                       "age_s": int(now - v.get("ts", now)), "pid": v.get("pid")}
                                      for k, v in state["reservations"].items()],
                "unreconciled": [{"token": k, "usd": round(v["usd"], 6), "what": v.get("what"),
                                  "reason": v.get("reason")} for k, v in state["unreconciled"].items()],
                "note": "conservative estimate at configured prices; the provider console is the billing authority",
            }
        return self._locked(_do)


# ----------------------------------------------------------------------------- per-investigation ledger


@dataclass
class Reservation:
    """A held slot for one model call: the tokens and money set aside for it."""

    usd: float = 0.0
    global_token: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0  # the provider output limit for this call MUST be this number
    closed: bool = False


class BudgetLedger:
    """Atomic usage ledger for one investigation, persisted so a restart cannot reset it."""

    def __init__(self, path: Path | None, caps: RunCaps, *, kind: str = "scripted", max_usd: float = 0.0,
                 price_in_per_mtok: float | None = None, price_out_per_mtok: float | None = None,
                 global_spend: "GlobalSpend | None" = None, max_tokens_per_call: int | None = None,
                 label: str = "investigation", model: str | None = None):
        if caps.problems():
            raise BudgetExceeded("invalid caps: " + "; ".join(caps.problems()))
        for name, value in (("max_usd", max_usd), ("price_in", price_in_per_mtok), ("price_out", price_out_per_mtok)):
            if value is not None and not (math.isfinite(value) and value >= 0):
                raise BudgetExceeded(f"{name} must be a finite, non-negative number")
        self.path = path
        self.caps = caps
        self.kind = kind  # scripted | local | included_credits
        self.max_usd = max_usd
        self.price_in = price_in_per_mtok
        self.price_out = price_out_per_mtok
        self.global_spend = global_spend
        self.max_tokens_per_call = min(max_tokens_per_call or DEFAULT_MAX_TOKENS_PER_CALL, caps.max_output_tokens)
        self.label = label
        self.model = model
        self._lock = threading.Lock()
        self.state: dict[str, Any] = {
            "kind": kind, "llm_calls": 0, "scripted_turns": 0, "reserved": 0, "reserved_in": 0, "reserved_out": 0,
            "tokens_in": 0, "tokens_out": 0, "tokens_cache_read": 0, "tokens_cache_write": 0, "cost_usd": 0.0,
            "reserved_usd": 0.0, "retries": 0, "errors": 0, "uncertain_calls": 0, "tool_calls": 0,
            "truncated_calls": 0, "refusals": 0, "started": None, "disabled_reason": None, "by_role": {},
            "models": [],
        }
        if path is not None and path.exists():
            self.state.update(json.loads(path.read_text(encoding="utf-8")))
            # A process that died mid-call left reservations behind. Their usage is unknown, so the
            # reserved tokens and money are kept as used (the cumulative ledger still holds the money).
            s = self.state
            if s.get("reserved", 0) or s.get("reserved_in", 0) or s.get("reserved_out", 0):
                s["uncertain_calls"] += s.get("reserved", 0)
                s["llm_calls"] += s.get("reserved", 0) if kind != "scripted" else 0
                s["tokens_in"] += s.get("reserved_in", 0)
                s["tokens_out"] += s.get("reserved_out", 0)
                s["cost_usd"] += s.get("reserved_usd", 0.0)
                s["reserved"] = s["reserved_in"] = s["reserved_out"] = 0
                s["reserved_usd"] = 0.0
                self._persist()

    def _persist(self) -> None:
        if self.path is None:
            return
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state), encoding="utf-8")
        os.replace(tmp, self.path)

    def reserve(self, role: str, input_tokens: int = 0) -> Reservation:
        """Reserve one call before it is made: a call slot, its counted input, an output allowance, money.

        Raises BudgetExceeded when any cap would be passed. The returned `output_tokens` is the
        output limit the request must be sent with.
        """
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
                return Reservation()
            input_tokens = int(input_tokens)
            if input_tokens < 0:
                raise BudgetExceeded("a request cannot have a negative size")
            if time.time() - s["started"] > self.caps.max_seconds:
                raise BudgetExceeded(f"time cap reached ({self.caps.max_seconds:.0f} s per investigation)")
            if s["llm_calls"] + s["reserved"] >= self.caps.max_calls:
                raise BudgetExceeded(f"call cap reached ({self.caps.max_calls} model calls per investigation)")
            if input_tokens > self.caps.max_input_tokens_per_call:
                raise BudgetExceeded(
                    f"request too large: {input_tokens} input tokens counted, the per-request ceiling is "
                    f"{self.caps.max_input_tokens_per_call}. It was not sent.")
            if s["tokens_in"] + s["reserved_in"] + input_tokens > self.caps.max_input_tokens:
                raise BudgetExceeded(
                    f"input token cap reached: {s['tokens_in']} used + {s['reserved_in']} reserved + "
                    f"{input_tokens} needed > {self.caps.max_input_tokens}")
            out_left = self.caps.max_output_tokens - s["tokens_out"] - s["reserved_out"]
            out = min(self.max_tokens_per_call, out_left)
            if out < MIN_OUTPUT_TOKENS:
                raise BudgetExceeded(
                    f"output token cap reached: {s['tokens_out']} used + {s['reserved_out']} reserved leaves "
                    f"{max(0, out_left)} of {self.caps.max_output_tokens}, under the {MIN_OUTPUT_TOKENS}-token minimum")
            usd, token = 0.0, None
            if self.kind == "included_credits":
                if not self.price_in or not self.price_out:
                    raise BudgetExceeded("unknown pricing: billed routes stay disabled rather than guessing")
                usd = worst_case_usd(input_tokens, out, self.price_in, self.price_out)
                if s["cost_usd"] + s["reserved_usd"] + usd > self.max_usd + 1e-9:
                    raise BudgetExceeded(
                        f"credit cap reached: ${s['cost_usd']:.4f} used + ${s['reserved_usd']:.4f} reserved + "
                        f"${usd:.4f} needed > ${self.max_usd:.2f} (LLM_MAX_USD). Paid overage is not authorized.")
                if self.global_spend is None:
                    raise BudgetExceeded("a billed route needs the cumulative spend ledger; none is configured")
                token = self.global_spend.reserve(usd, f"{self.label}:{role}", self.model)
            s["reserved"] += 1
            s["reserved_in"] += input_tokens
            s["reserved_out"] += out
            s["reserved_usd"] += usd
            self._persist()
            return Reservation(usd=usd, global_token=token, input_tokens=input_tokens, output_tokens=out)

    def commit(self, role: str, hold: Reservation, *, outcome: str = "ok", tokens_in: int = 0, tokens_out: int = 0,
               cache_read: int = 0, cache_write: int = 0, retried: bool = False, truncated: bool = False,
               model: str | None = None, reason: str = "") -> None:
        """Close a reservation. outcome: ok | refused | not_billed | uncertain. Idempotent per reservation.

        ok/refused   usage is known: actual tokens and estimated cost are recorded.
        not_billed   the request was never sent or was rejected before processing: everything is released.
        uncertain    the outcome is unknown (timeout, lost response, missing usage): the reserved worst
                     case is kept as used, here and in the cumulative ledger, until an operator reconciles it.
        """
        with self._lock:
            if hold.closed:
                return
            hold.closed = True
            s = self.state
            s["reserved"] = max(0, s["reserved"] - 1)
            by = s["by_role"].setdefault(role, {"calls": 0, "tokens_in": 0, "tokens_out": 0})
            by["calls"] += 1
            if self.kind == "scripted":
                s["scripted_turns"] += 1
                if outcome != "ok":
                    s["errors"] += 1
                self._persist()
                return
            s["reserved_in"] = max(0, s["reserved_in"] - hold.input_tokens)
            s["reserved_out"] = max(0, s["reserved_out"] - hold.output_tokens)
            s["reserved_usd"] = max(0.0, s["reserved_usd"] - hold.usd)
            if model and model not in s["models"]:
                s["models"].append(model)
            if outcome == "not_billed":
                s["errors"] += 1
                if self.global_spend is not None and hold.global_token:
                    self.global_spend.release(hold.global_token, reason or "not billed")
            elif outcome == "uncertain":
                s["llm_calls"] += 1
                s["uncertain_calls"] += 1
                s["errors"] += 1 if reason and "missing usage" not in reason else 0
                s["tokens_in"] += hold.input_tokens
                s["tokens_out"] += hold.output_tokens
                by["tokens_in"] += hold.input_tokens
                by["tokens_out"] += hold.output_tokens
                s["cost_usd"] += hold.usd
                if self.global_spend is not None and hold.global_token:
                    self.global_spend.mark_uncertain(hold.global_token, reason or "unknown billing outcome")
            else:  # ok | refused
                s["llm_calls"] += 1
                s["tokens_in"] += tokens_in
                s["tokens_out"] += tokens_out
                s["tokens_cache_read"] += cache_read
                s["tokens_cache_write"] += cache_write
                s["truncated_calls"] += int(truncated)
                by["tokens_in"] += tokens_in
                by["tokens_out"] += tokens_out
                if outcome == "refused":
                    s["refusals"] += 1
                    s["errors"] += 1
                cost = 0.0
                if self.kind == "included_credits":
                    cost = call_cost_usd(tokens_in, tokens_out, cache_read, cache_write,
                                         self.price_in or 0, self.price_out or 0)
                    s["cost_usd"] += cost
                if self.global_spend is not None and hold.global_token:
                    self.global_spend.settle(hold.global_token, cost, f"{self.label}:{role}", model or self.model)
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


# ----------------------------------------------------------------------------- request counting


class CountFailed(RuntimeError):
    pass


def _bound_tools(bound: Any) -> Any:
    return (getattr(bound, "kwargs", None) or {}).get("tools") if bound is not None else None


def serialized_request_bytes(messages: list[BaseMessage], tools: Any) -> int:
    """Size of everything a request carries: system prompt, messages, tool calls and tool schemas."""
    total = 0
    for m in messages:
        content = m.content if isinstance(m.content, str) else json.dumps(m.content, default=str)
        total += len(content.encode("utf-8")) + 16
        calls = getattr(m, "tool_calls", None)
        if calls:
            total += len(json.dumps(calls, default=str).encode("utf-8"))
    if tools:
        try:
            total += len(json.dumps(tools, default=str).encode("utf-8"))
        except TypeError:
            total += sum(len(str(t).encode("utf-8")) for t in tools)
    return total


def local_token_bound(messages: list[BaseMessage], tools: Any) -> int:
    """A conservative token bound without a provider: one token per two bytes, plus framing."""
    return math.ceil(serialized_request_bytes(messages, tools) / 2) + 512


def count_request_tokens(inner: Any, bound: Any, messages: list[BaseMessage]) -> tuple[int, str]:
    """Count the outgoing request. Claude models are counted by the provider's token-counting endpoint
    (it sees the system prompt, the tool schemas and the messages exactly as they will be sent), with
    headroom added. Other models get a conservative local bound."""
    tools = _bound_tools(bound)
    if getattr(inner, "_llm_type", None) == "anthropic-chat":
        try:
            n = int(inner.get_num_tokens_from_messages(messages, tools=tools))
        except Exception as exc:  # noqa: BLE001
            raise CountFailed(f"{type(exc).__name__}: {str(exc)[:160]}") from exc
        return math.ceil(n * COUNT_HEADROOM) + COUNT_PAD, "provider_count"
    return local_token_bound(messages, tools), "local_bound"


# ----------------------------------------------------------------------------- error classification

_NOT_BILLED_STATUS = {400, 401, 403, 404, 405, 409, 413, 422, 429}
_AUTH_STATUS = {401, 403}
_AUTH_MARKERS = ("401", "403", "authentication", "unauthorized", "permission", "credit", "billing", "quota", "payment")
_TRANSIENT_MARKERS = ("timeout", "timed out", "429", "overloaded", "503", "502", "500", "529", "connection", "temporar")


def classify_error(exc: BaseException) -> dict[str, bool]:
    """How to account for a failed call.

    billed_unknown  True unless the provider certainly rejected the request before processing it.
    fatal           credential/credit problems: disable the route, no retry, no fallback provider.
    retry           transient: one bounded retry is allowed.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    text = f"{type(exc).__name__} {exc}".lower()
    if isinstance(status, int):
        return {"billed_unknown": status not in _NOT_BILLED_STATUS, "fatal": status in _AUTH_STATUS,
                "retry": status == 429 or status >= 500}
    if any(m in text for m in _AUTH_MARKERS):
        return {"billed_unknown": False, "fatal": True, "retry": False}
    if any(m in text for m in _TRANSIENT_MARKERS):
        return {"billed_unknown": True, "fatal": False, "retry": True}
    return {"billed_unknown": True, "fatal": False, "retry": False}


# ----------------------------------------------------------------------------- the wrapper


class BudgetedChatModel(BaseChatModel):
    """Wraps any chat model (scripted or real) so that every call is counted, reserved and accounted."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    inner: Any
    ledger: Any
    role: str = "lead-investigator"
    bound: Any = None
    on_bind: Any = Field(default=None, exclude=True)  # Callable[[str, list[str]], None]
    counter: Any = Field(default=None, exclude=True)  # Callable[[inner, bound, messages], int] for tests
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

    def _count(self, messages: list[BaseMessage]) -> int:
        if self.ledger.kind == "scripted":
            return 0
        try:
            if self.counter is not None:
                return int(self.counter(self.inner, self.bound, messages))
            return count_request_tokens(self.inner, self.bound, messages)[0]
        except Exception as exc:  # noqa: BLE001 - an uncounted request is an unbudgeted request
            raise BudgetExceeded(f"the request could not be counted, so it was not sent ({exc})") from exc

    def _call(self, messages: list[BaseMessage], stop: list[str] | None, max_output: int) -> AIMessage:
        target = self.bound if self.bound is not None else self.inner
        kwargs: dict[str, Any] = {}
        if stop:
            kwargs["stop"] = stop
        llm_type = getattr(self.inner, "_llm_type", None)
        if self.ledger.kind != "scripted":
            if llm_type in UNCLAMPABLE_TYPES:
                # this client takes its output limit at construction only; a smaller reservation cannot be honored
                if max_output < self.ledger.max_tokens_per_call:
                    raise BudgetExceeded("output token cap reached: the remaining allowance is smaller than this "
                                         "model's fixed per-call output limit")
            else:
                kwargs["max_tokens"] = max_output  # the provider's output limit is exactly what was reserved
        if llm_type == "anthropic-chat":
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
            counted = self._count(messages)
            hold = self.ledger.reserve(self.role, counted)
            try:
                ai = self._call(messages, stop, hold.output_tokens)
            except BudgetExceeded:
                self.ledger.commit(self.role, hold, outcome="not_billed", reason="not sent")
                raise
            except Exception as exc:  # noqa: BLE001
                kind = classify_error(exc)
                why = f"{type(exc).__name__}: {str(exc)[:120]}"
                self.ledger.commit(self.role, hold, outcome="uncertain" if kind["billed_unknown"] else "not_billed",
                                   retried=attempt > 0, reason=why)
                if kind["fatal"]:
                    self.ledger.disable(f"{type(exc).__name__}: credential/credit error; route disabled, no fallback provider")
                    raise
                if kind["retry"] and attempt == 0:  # exactly one bounded retry
                    attempt += 1
                    time.sleep(self.retry_sleep_s)
                    continue
                raise
            um = getattr(ai, "usage_metadata", None) or {}
            details = (um.get("input_token_details") or {}) if isinstance(um, dict) else {}
            cache_read = int(details.get("cache_read") or 0)
            cache_write = int((details.get("ephemeral_5m_input_tokens") or 0) + (details.get("ephemeral_1h_input_tokens") or 0)
                              or details.get("cache_creation") or 0)
            tokens_in = int(um.get("input_tokens", 0) or 0) if isinstance(um, dict) else 0
            tokens_out = int(um.get("output_tokens", 0) or 0) if isinstance(um, dict) else 0
            meta = getattr(ai, "response_metadata", None) or {}
            stop_reason = meta.get("stop_reason")
            refused = stop_reason == "refusal"
            served = meta.get("model_name") or meta.get("model")
            if self.ledger.kind != "scripted" and tokens_in <= 0:
                # the provider answered but reported no usage: the cost is unknown, so the worst case stays
                self.ledger.commit(self.role, hold, outcome="uncertain", retried=attempt > 0, model=served,
                                   reason="missing usage in the response")
            else:
                self.ledger.commit(self.role, hold, outcome="refused" if refused else "ok", tokens_in=tokens_in,
                                   tokens_out=tokens_out, cache_read=cache_read, cache_write=cache_write,
                                   retried=attempt > 0, truncated=stop_reason == "max_tokens", model=served)
            if refused:
                category = (meta.get("stop_details") or {}).get("category") if isinstance(meta.get("stop_details"), dict) else None
                raise ModelRefused(f"the model declined this request (safety classifier category: {category or 'not given'})")
            return ChatResult(generations=[ChatGeneration(message=ai)])


# ----------------------------------------------------------------------------- construction


def global_spend_for(settings: Settings) -> "GlobalSpend | None":
    """The cumulative spend ledger. Only billed (included-credit) routes have one."""
    if settings.live_provider_kind != "included_credits":
        return None
    return GlobalSpend(settings.spend_ledger_path, settings.llm_max_usd, limit_usd=settings.spend_limit_usd,
                       floor_usd=settings.spend_floor_usd)


def make_ledger(settings: Settings, path: Path | None, *, scripted: bool, label: str = "investigation",
                caps: RunCaps | None = None) -> BudgetLedger:
    if scripted:
        return BudgetLedger(path, settings.caps, kind="scripted")
    return BudgetLedger(path, caps or settings.caps, kind=settings.live_provider_kind or "local",
                        max_usd=settings.llm_max_usd, price_in_per_mtok=settings.price_in_per_mtok,
                        price_out_per_mtok=settings.price_out_per_mtok, global_spend=global_spend_for(settings),
                        max_tokens_per_call=settings.max_tokens_per_call, label=label, model=settings.lead_model)


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
         on_bind: Callable[[str, list[str]], None] | None = None,
         counter: Callable[[Any, Any, list[BaseMessage]], int] | None = None) -> BudgetedChatModel:
    return BudgetedChatModel(inner=inner, ledger=ledger, role=role, on_bind=on_bind, counter=counter)
