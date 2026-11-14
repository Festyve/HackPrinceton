"""Runtime configuration with zero-spend defaults (PLAN sections 2.10 and 10.5).

Nothing here reads or prints credential values. The only thing other modules may ask
about a credential is whether a model route is *configured*.
"""

from __future__ import annotations

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
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc


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


@dataclass(frozen=True)
class RunCaps:
    """Per-investigation caps shared across lead, specialists and retries.

    Revised once from measured evidence (DECISIONS.md, 2026-11-14): the first real run used about
    8,000 input tokens per model call, almost all of it a cached prefix, so the planning guess of
    40,000 cumulative input tokens stopped a correct investigation after 5 calls.
    """

    max_calls: int = 16
    max_input_tokens: int = 200_000
    max_output_tokens: int = 10_000
    max_seconds: float = 180.0
    max_input_tokens_per_call: int = 40_000  # bound used to size the per-call spend reservation
    tool_result_max_records: int = 50
    tool_result_max_bytes: int = 8_192
    recursion_limit: int = 60


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
    caps: RunCaps = RunCaps()
    runs_dir: Path = REPO_ROOT / "runs"
    sealed_dir: Path = REPO_ROOT / "sealed"
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def offline(self) -> bool:
        return self.runtime_mode != "live"

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
        if self.live_provider_kind == "included_credits":
            if self.llm_max_usd <= 0:
                return "LIVE_PROVIDER_KIND=included_credits requires LLM_MAX_USD>0 (credit cap)."
            if self.price_in_per_mtok is None or self.price_out_per_mtok is None:
                return (
                    "Unknown pricing: set LLM_PRICE_IN_PER_MTOK and LLM_PRICE_OUT_PER_MTOK. "
                    "Unknown pricing disables billed routes rather than guessing."
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
            "price_in_per_mtok": self.price_in_per_mtok,
            "price_out_per_mtok": self.price_out_per_mtok,
            "caps": {
                "max_calls": self.caps.max_calls,
                "max_input_tokens": self.caps.max_input_tokens,
                "max_output_tokens": self.caps.max_output_tokens,
                "max_seconds": self.caps.max_seconds,
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

    caps = RunCaps(
        max_calls=_i(env, "LLM_MAX_CALLS_PER_RUN", 16),
        max_input_tokens=_i(env, "LLM_MAX_INPUT_TOKENS_PER_RUN", 200_000),
        max_output_tokens=_i(env, "LLM_MAX_OUTPUT_TOKENS_PER_RUN", 10_000),
        max_seconds=_f(env, "LLM_MAX_SECONDS_PER_RUN", 180.0),
    )

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
        caps=caps,
        runs_dir=runs_dir,
        sealed_dir=sealed_dir,
        host=_s(env, "ALIBI_HOST") or "127.0.0.1",
        port=_i(env, "ALIBI_PORT", 8000),
    )
