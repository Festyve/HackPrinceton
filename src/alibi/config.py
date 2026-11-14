"""Runtime configuration with zero-spend defaults (PLAN sections 2.10 and 10.5).

Nothing here reads or prints credential values. The only thing other modules may ask
about a credential is whether a model route is *configured*.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    """Raised for unsafe or contradictory runtime settings."""


def _f(env: Mapping[str, str], key: str, default: float) -> float:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc
    if not math.isfinite(value):  # NaN and infinity silently defeat every comparison a cap relies on
        raise ConfigError(f"{key} must be a finite number, got {raw!r}")
    return value


def _i(env: Mapping[str, str], key: str, default: int) -> int:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def _s(env: Mapping[str, str], key: str) -> str | None:
    raw = (env.get(key) or "").strip()
    return raw or None


# LIVE_PROVIDER_KIND=local means "served on this machine, costs nothing". Only providers known to be
# local may use it; a hosted provider declared as local would be billed with no money accounting at all.
LOCAL_PROVIDERS = ("ollama",)
# Billed routes are limited to providers whose request counting and per-call output clamp are verified.
BILLED_PROVIDERS = ("anthropic",)
PER_CALL_INPUT_HARD_MAX = 95_000  # stay under the 100,000-token request size where some price tiers change
DEMO_RESERVE_USD = 0.50  # held back from automatic use for an operator-triggered live demo


@dataclass(frozen=True)
class RunCaps:
    """Per-investigation caps shared across lead, specialists and retries.

    Revised once from measured evidence (DECISIONS.md, 2026-11-14): the first real run used about
    8,000 input tokens per model call, almost all of it a cached prefix, so the planning guess of
    40,000 cumulative input tokens stopped a correct investigation after 5 calls.

    `max_input_tokens_per_call` is ENFORCED: the gateway counts the outgoing request (system prompt,
    tool schemas and messages) and refuses to send one that is larger.
    """

    max_calls: int = 16
    max_input_tokens: int = 200_000
    max_output_tokens: int = 10_000
    max_seconds: float = 180.0
    max_input_tokens_per_call: int = 40_000
    tool_result_max_records: int = 50
    tool_result_max_bytes: int = 8_192
    recursion_limit: int = 60

    def problems(self) -> list[str]:
        out = []
        if self.max_calls < 1:
            out.append("LLM_MAX_CALLS_PER_RUN must be at least 1")
        if self.max_input_tokens < 1:
            out.append("LLM_MAX_INPUT_TOKENS_PER_RUN must be at least 1")
        if self.max_output_tokens < 1:
            out.append("LLM_MAX_OUTPUT_TOKENS_PER_RUN must be at least 1")
        if not (math.isfinite(self.max_seconds) and self.max_seconds > 0):
            out.append("LLM_MAX_SECONDS_PER_RUN must be a positive, finite number")
        if not 1 <= self.max_input_tokens_per_call <= PER_CALL_INPUT_HARD_MAX:
            out.append(f"LLM_MAX_INPUT_TOKENS_PER_CALL must be between 1 and {PER_CALL_INPUT_HARD_MAX}")
        return out


@dataclass(frozen=True)
class Settings:
    runtime_mode: str = "offline"  # offline | live
    llm_max_usd: float = 0.0
    bench_max_system_runs: int = 0
    live_provider_kind: str | None = None  # local | included_credits
    lead_model: str | None = None
    subagent_model: str | None = None
    adversary_model: str | None = None
    price_in_per_mtok: float | None = None
    price_out_per_mtok: float | None = None
    effort: str = "low"  # reasoning effort for live models that support it
    max_tokens_per_call: int = 3000  # per-response ceiling; the ledger enforces the cumulative cap
    # LLM_MAX_USD is the absolute cap on estimated cumulative spend. Automatic calls stop at the
    # development ceiling beneath it; only an explicit operator action may use the rest.
    dev_ceiling_usd: float | None = None
    use_demo_reserve: bool = False
    spend_ledger_path: Path = REPO_ROOT / ".alibi" / "spend.json"
    spend_floor_usd: float = 0.0  # known earlier spend; a missing ledger starts here, never at zero
    caps: RunCaps = RunCaps()
    runs_dir: Path = REPO_ROOT / "runs"
    sealed_dir: Path = REPO_ROOT / "sealed"
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def offline(self) -> bool:
        return self.runtime_mode != "live"

    @property
    def spend_limit_usd(self) -> float:
        """The ceiling in force for this process: the development ceiling unless the reserve is opened."""
        if self.use_demo_reserve or self.dev_ceiling_usd is None:
            return self.llm_max_usd
        return min(self.llm_max_usd, self.dev_ceiling_usd)

    def live_block_reason(self) -> str | None:
        """Why live inference cannot run right now, or None if it may be attempted."""
        if self.runtime_mode != "live":
            return "RUNTIME_MODE is offline (default). No network model calls are made."
        if not self.lead_model:
            return "RUNTIME_MODE=live but LEAD_MODEL is not set."
        if self.live_provider_kind not in ("local", "included_credits"):
            return (
                "RUNTIME_MODE=live requires LIVE_PROVIDER_KIND=local or included_credits "
                "so the budget gateway knows how to account for usage."
            )
        models = [m for m in (self.lead_model, self.subagent_model, self.adversary_model) if m]
        providers = sorted({m.split(":", 1)[0] for m in models})
        if self.live_provider_kind == "local":
            hosted = [p for p in providers if p not in LOCAL_PROVIDERS]
            if hosted:
                return (f"LIVE_PROVIDER_KIND=local is only for models served on this machine ({', '.join(LOCAL_PROVIDERS)}). "
                        f"{', '.join(hosted)} is a hosted provider: use LIVE_PROVIDER_KIND=included_credits with LLM_MAX_USD "
                        "and prices, so its spend is counted.")
        if self.live_provider_kind == "included_credits":
            other = [p for p in providers if p not in BILLED_PROVIDERS]
            if other:
                return (f"Billed routes are limited to {', '.join(BILLED_PROVIDERS)}: request counting and the per-call "
                        f"output limit are verified only there. {', '.join(other)} stays disabled rather than run unbudgeted.")
            if self.llm_max_usd <= 0:
                return "LIVE_PROVIDER_KIND=included_credits requires LLM_MAX_USD>0 (credit cap)."
            if self.price_in_per_mtok is None or self.price_out_per_mtok is None:
                return (
                    "Unknown pricing: set LLM_PRICE_IN_PER_MTOK and LLM_PRICE_OUT_PER_MTOK. "
                    "Unknown pricing disables billed routes rather than guessing."
                )
            if self.price_in_per_mtok <= 0 or self.price_out_per_mtok <= 0:
                return "Pricing must be positive for a billed route: a zero price would hide all spend."
            others = {m for m in (self.subagent_model, self.adversary_model) if m}
            if others - {self.lead_model}:
                return (
                    "One price pair is configured, so every role must use the same model: set SUBAGENT_MODEL "
                    "and ADVERSARY_MODEL to LEAD_MODEL (or leave them empty)."
                )
        return None

    def public_dict(self) -> dict:
        """Safe to show in the UI/handoff: no secrets, only modes and caps."""
        return {
            "runtime_mode": self.runtime_mode,
            "llm_max_usd": self.llm_max_usd,
            "bench_max_system_runs": self.bench_max_system_runs,
            "live_provider_kind": self.live_provider_kind,
            "lead_model": self.lead_model,
            "subagent_model": self.subagent_model,
            "adversary_model": self.adversary_model,
            "live_block_reason": self.live_block_reason(),
            "effort": self.effort,
            "max_tokens_per_call": self.max_tokens_per_call,
            "dev_ceiling_usd": self.dev_ceiling_usd,
            "spend_limit_in_force_usd": self.spend_limit_usd,
            "demo_reserve_open": self.use_demo_reserve,
            "price_in_per_mtok": self.price_in_per_mtok,
            "price_out_per_mtok": self.price_out_per_mtok,
            "caps": {
                "max_calls": self.caps.max_calls,
                "max_input_tokens": self.caps.max_input_tokens,
                "max_output_tokens": self.caps.max_output_tokens,
                "max_seconds": self.caps.max_seconds,
                "max_input_tokens_per_call": self.caps.max_input_tokens_per_call,
                "tool_result_max_records": self.caps.tool_result_max_records,
                "tool_result_max_bytes": self.caps.tool_result_max_bytes,
            },
            "paid_overage_authorized_usd": 0,
        }


def load_settings(env: Mapping[str, str] | None = None, *, dotenv: bool = True) -> Settings:
    """Build Settings from the environment. Unsafe/ambiguous values raise ConfigError."""
    if env is None:
        if dotenv:
            try:
                from dotenv import load_dotenv

                load_dotenv(REPO_ROOT / ".env", override=False)
            except Exception:  # pragma: no cover - dotenv is optional at runtime
                pass
        env = os.environ

    if _s(env, "BENCH_MAX_LLM_EPISODES") is not None:
        raise ConfigError(
            "BENCH_MAX_LLM_EPISODES is ambiguous and no longer accepted. Use "
            "BENCH_MAX_SYSTEM_RUNS (one system-run = one investigator configuration on "
            "one evidence bundle)."
        )

    mode = (_s(env, "RUNTIME_MODE") or "offline").lower()
    if mode not in ("offline", "live"):
        raise ConfigError(f"RUNTIME_MODE must be offline or live, got {mode!r}")

    llm_max_usd = _f(env, "LLM_MAX_USD", 0.0)
    if llm_max_usd < 0:
        raise ConfigError("LLM_MAX_USD cannot be negative")
    max_runs = _i(env, "BENCH_MAX_SYSTEM_RUNS", 0)
    if max_runs < 0:
        raise ConfigError("BENCH_MAX_SYSTEM_RUNS cannot be negative")

    kind = _s(env, "LIVE_PROVIDER_KIND")
    if kind is not None:
        kind = kind.lower()
        if kind not in ("local", "included_credits"):
            raise ConfigError("LIVE_PROVIDER_KIND must be local or included_credits")

    price_in = _f(env, "LLM_PRICE_IN_PER_MTOK", -1.0)
    price_out = _f(env, "LLM_PRICE_OUT_PER_MTOK", -1.0)
    for key, value in (("LLM_PRICE_IN_PER_MTOK", price_in), ("LLM_PRICE_OUT_PER_MTOK", price_out)):
        if _s(env, key) is not None and value < 0:
            raise ConfigError(f"{key} cannot be negative")

    caps = RunCaps(
        max_calls=_i(env, "LLM_MAX_CALLS_PER_RUN", 16),
        max_input_tokens=_i(env, "LLM_MAX_INPUT_TOKENS_PER_RUN", 200_000),
        max_output_tokens=_i(env, "LLM_MAX_OUTPUT_TOKENS_PER_RUN", 10_000),
        max_seconds=_f(env, "LLM_MAX_SECONDS_PER_RUN", 180.0),
        max_input_tokens_per_call=_i(env, "LLM_MAX_INPUT_TOKENS_PER_CALL", 40_000),
    )
    if caps.problems():
        raise ConfigError("; ".join(caps.problems()))

    dev_raw = _s(env, "LLM_DEV_CEILING_USD")
    if dev_raw is None:
        dev_ceiling = max(0.0, llm_max_usd - DEMO_RESERVE_USD)
    else:
        dev_ceiling = _f(env, "LLM_DEV_CEILING_USD", 0.0)
        if dev_ceiling < 0 or dev_ceiling > llm_max_usd:
            raise ConfigError("LLM_DEV_CEILING_USD must be between 0 and LLM_MAX_USD")
    spend_floor = _f(env, "LLM_SPEND_FLOOR_USD", 0.0)
    if spend_floor < 0:
        raise ConfigError("LLM_SPEND_FLOOR_USD cannot be negative")
    ledger_raw = _s(env, "ALIBI_SPEND_LEDGER")
    if ledger_raw is not None and not Path(ledger_raw).is_absolute():
        raise ConfigError("ALIBI_SPEND_LEDGER must be an absolute path, so every worktree shares one ledger")
    ledger_path = Path(ledger_raw) if ledger_raw else REPO_ROOT / ".alibi" / "spend.json"

    effort = (_s(env, "LLM_EFFORT") or "low").lower()
    if effort not in ("low", "medium", "high", "xhigh", "max"):
        raise ConfigError("LLM_EFFORT must be one of low, medium, high, xhigh, max")
    per_call = _i(env, "LLM_MAX_TOKENS_PER_CALL", 3000)
    if per_call < 256:
        raise ConfigError("LLM_MAX_TOKENS_PER_CALL must be at least 256")

    runs_dir = Path(_s(env, "ALIBI_RUNS_DIR") or (REPO_ROOT / "runs"))
    sealed_dir = Path(_s(env, "ALIBI_SEALED_DIR") or (REPO_ROOT / "sealed"))

    return Settings(
        runtime_mode=mode,
        llm_max_usd=llm_max_usd,
        bench_max_system_runs=max_runs,
        live_provider_kind=kind,
        lead_model=_s(env, "LEAD_MODEL"),
        subagent_model=_s(env, "SUBAGENT_MODEL"),
        adversary_model=_s(env, "ADVERSARY_MODEL"),
        price_in_per_mtok=None if price_in < 0 else price_in,
        price_out_per_mtok=None if price_out < 0 else price_out,
        effort=effort,
        max_tokens_per_call=per_call,
        dev_ceiling_usd=dev_ceiling,
        use_demo_reserve=(_s(env, "ALIBI_USE_DEMO_RESERVE") == "1"),
        spend_ledger_path=ledger_path,
        spend_floor_usd=spend_floor,
        caps=caps,
        runs_dir=runs_dir,
        sealed_dir=sealed_dir,
        host=_s(env, "ALIBI_HOST") or "127.0.0.1",
        port=_i(env, "ALIBI_PORT", 8000),
    )
