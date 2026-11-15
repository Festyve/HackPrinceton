"""Optional Gemini route for evidence questions. OFF unless explicitly selected; nothing in the core imports it.

It answers the existing "ask a question about a case" feature with a Gemini model, and changes nothing else:

  * the SAME bounded exchange, read-only toolbox and trusted validation as `alibi.questions` are used, unmodified:
    cited ids must exist in the bundle, claims are compared with the deterministic checks, the model has no report
    tools and nothing that reaches sealed truth (the orchestrator opens only the evidence store, the public
    manifest and the report for a question);
  * every call goes through the existing budget gateway (`gateway.wrap`) as a billed route: counted before it is
    sent, reserved against the per-question caps AND the cumulative spend ledger (LLM_MAX_USD and its development
    ceiling), with the output limit sent per call;
  * investigations, recordings, the environment designer and the worker lab stay exactly as configured (offline by
    default). Only questions are routed here.

Enable it only on purpose (all required):

    ALIBI_QA_PROVIDER=gemini
    GEMINI_API_KEY=...                      # or GOOGLE_API_KEY; server-side only, never committed
    GEMINI_MODEL=<id from `models` below>   # no model name is assumed
    GEMINI_PRICE_IN_PER_MTOK=<USD>          # from Google's pricing page; unknown pricing keeps the route off
    GEMINI_PRICE_OUT_PER_MTOK=<USD>
    LLM_MAX_USD=<cap>                       # the existing cumulative cap; 0 keeps every billed route off

Then:

    uv run python -m alibi.integrations.gemini_qa status
    uv run python -m alibi.integrations.gemini_qa models          # lists model ids your key can use (no charge)
    uv run python -m alibi.integrations.gemini_qa serve --port 8000
    uv run python -m alibi.integrations.gemini_qa ask <case-id> "What happened to the missing log line?"

`./start.sh` and `alibi serve` never load this module.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from dataclasses import replace
from typing import Any, Mapping

from alibi.config import Settings, load_settings

PROVIDER_ENV = "ALIBI_QA_PROVIDER"
MODEL_PREFIX = "gemini:"
_REFUSALS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}


def _key(env: Mapping[str, str]) -> str | None:
    return (env.get("GEMINI_API_KEY") or env.get("GOOGLE_API_KEY") or "").strip() or None


def _price(env: Mapping[str, str], name: str) -> float | None:
    raw = (env.get(name) or "").strip()
    try:
        value = float(raw) if raw else None
    except ValueError:
        return None
    return value if value is not None and value > 0 and value < 1e6 else None


def block_reason(settings: Settings, env: Mapping[str, str] | None = None) -> str | None:
    """Why the Gemini question route cannot be used, or None when it is completely and explicitly configured."""
    env = os.environ if env is None else env
    if (env.get(PROVIDER_ENV) or "").strip().lower() != "gemini":
        return f"{PROVIDER_ENV} is not 'gemini' (default: off)."
    if not _key(env):
        return "GEMINI_API_KEY is not set."
    if not (env.get("GEMINI_MODEL") or "").strip():
        return "GEMINI_MODEL is not set. Run `models` to list the ids your key can use."
    if _price(env, "GEMINI_PRICE_IN_PER_MTOK") is None or _price(env, "GEMINI_PRICE_OUT_PER_MTOK") is None:
        return ("GEMINI_PRICE_IN_PER_MTOK and GEMINI_PRICE_OUT_PER_MTOK must be positive numbers. Unknown pricing keeps "
                "the route off rather than guessing.")
    if settings.llm_max_usd <= 0:
        return "LLM_MAX_USD is 0, which keeps every billed route off. Set the cumulative cap first."
    if settings.runtime_mode == "live":
        # one Settings carries one price pair; the investigator's live route and this one must not share it
        return "RUNTIME_MODE=live is set. The Gemini question route runs only beside the offline investigator."
    return None


def gemini_settings(settings: Settings, env: Mapping[str, str] | None = None) -> Settings:
    """Settings whose billed-route fields describe the Gemini question route. RUNTIME_MODE stays offline, so the
    investigator, recordings, designer and lab are unchanged; only the ledger a question builds uses these."""
    env = os.environ if env is None else env
    return replace(settings, live_provider_kind="included_credits",
                   price_in_per_mtok=_price(env, "GEMINI_PRICE_IN_PER_MTOK"),
                   price_out_per_mtok=_price(env, "GEMINI_PRICE_OUT_PER_MTOK"))


def _chat_class() -> type:
    from langchain_google_genai import ChatGoogleGenerativeAI

    class GatewayGemini(ChatGoogleGenerativeAI):
        """Adapts the client to the budget gateway's per-call contract: the gateway sends `max_tokens` (the output
        it reserved) and reads `stop_reason`; this client takes `max_output_tokens` and reports `finish_reason`."""

        def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
            if "max_tokens" in kwargs:
                kwargs["max_output_tokens"] = kwargs.pop("max_tokens")
            result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            for gen in result.generations:
                meta = gen.message.response_metadata
                reason = str(meta.get("finish_reason") or (gen.generation_info or {}).get("finish_reason") or "")
                if reason == "MAX_TOKENS":
                    meta["stop_reason"] = "max_tokens"
                elif reason in _REFUSALS:
                    meta["stop_reason"] = "refusal"
                    meta.setdefault("stop_details", {"category": reason.lower()})
            return result

    return GatewayGemini


def model_factory(env: Mapping[str, str] | None = None) -> Any:
    """A factory with the shape the orchestrator expects: ledger -> budgeted chat model."""
    from alibi.agents import gateway

    env = dict(os.environ if env is None else env)
    model_id = env["GEMINI_MODEL"].strip()
    key = _key(env)

    def build(ledger: Any) -> Any:
        if not str(getattr(ledger, "label", "")).startswith("question:"):
            raise gateway.RuntimeBlocked("the Gemini route answers questions only")
        inner = _chat_class()(model=model_id, google_api_key=key, temperature=0, max_retries=0, timeout=60.0,
                              max_output_tokens=ledger.max_tokens_per_call)
        return gateway.wrap(inner, ledger, "question")

    return build


def orchestrator_class() -> type:
    from alibi.orchestrator import Orchestrator

    class GeminiQAOrchestrator(Orchestrator):
        """The stock orchestrator; questions use Gemini, everything else sees no model factory."""

        _designing = threading.local()

        @property
        def qa_model_factory(self) -> Any:  # type: ignore[override]
            return None if getattr(self._designing, "on", False) else self.__dict__.get("_gemini_factory")

        @qa_model_factory.setter
        def qa_model_factory(self, value: Any) -> None:
            self.__dict__["_gemini_factory"] = value

        def design_environment(self, *args: Any, **kwargs: Any) -> Any:
            self._designing.on = True  # the designer runs in the request thread: it keeps its offline default
            try:
                return super().design_environment(*args, **kwargs)
            finally:
                self._designing.on = False

        def _answer(self, case_id: str, pending: Any) -> Any:
            done = super()._answer(case_id, pending)
            if done.inference_mode == "LIVE_MODEL":
                model = MODEL_PREFIX + os.environ.get("GEMINI_MODEL", "").strip()
                done = done.model_copy(update={"model_id": model,
                                               "inference_label": f"{done.inference_label} · Gemini (optional route)"})
            return done

    return GeminiQAOrchestrator


def build_orchestrator(settings: Settings | None = None, env: Mapping[str, str] | None = None) -> Any:
    settings = settings or load_settings()
    reason = block_reason(settings, env)
    if reason:
        raise SystemExit(f"Gemini question route is off: {reason}")
    orch = orchestrator_class()(gemini_settings(settings, env))
    orch.qa_model_factory = model_factory(env)
    return orch


# ----------------------------------------------------------------------------- command line


def _cmd_status(_: argparse.Namespace) -> int:
    reason = block_reason(load_settings())
    print(json.dumps({"route": "gemini questions", "enabled": reason is None, "reason": reason,
                      "model": os.environ.get("GEMINI_MODEL") or None, "key_configured": bool(_key(os.environ))}, indent=2))
    return 0


def _cmd_models(_: argparse.Namespace) -> int:
    """List generateContent models the key can use. Listing models is not billed."""
    key = _key(os.environ)
    if not key:
        print("GEMINI_API_KEY is not set.", file=sys.stderr)
        return 2
    from google import genai

    client = genai.Client(api_key=key)
    for m in client.models.list():
        if "generateContent" in (getattr(m, "supported_actions", None) or []):
            print((m.name or "").removeprefix("models/"))
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    import time
    import uuid

    orch = build_orchestrator()
    q = orch.ask_question(args.case_id, args.question, f"gemini-{uuid.uuid4().hex[:10]}")
    end = time.time() + 120
    while q.status == "pending" and time.time() < end:
        time.sleep(0.2)
        q = orch.get_question(args.case_id, q.question_id)
    print(f"[{q.inference_label} · {q.model_id}] status: {q.status}"
          + (f" · {q.usage.llm_calls} model call(s), est. ${q.usage.cost_estimate_usd:.4f}" if q.usage.llm_calls else ""))
    if q.error:
        print(f"note: {q.error}")
    if q.answer:
        print("\n" + q.answer + "\n")
    for c in q.claims:
        print(f"  {c.support.upper():<14} {c.text}  [{', '.join(c.evidence_ids[:4]) or 'no citation'}]")
    for line in q.limitations:
        print(f"  limit: {line}")
    return 0 if q.status in ("answered", "insufficient_evidence") else 1


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from alibi.api.app import create_app

    settings = load_settings()
    orch = build_orchestrator(settings)
    host, port = args.host or settings.host, args.port or settings.port
    print(f"ALIBI case board with Gemini questions: http://{host}:{port}  (investigator: {settings.runtime_mode})")
    uvicorn.run(create_app(orch.settings, orch), host=host, port=port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m alibi.integrations.gemini_qa", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(func=_cmd_status)
    sub.add_parser("models").set_defaults(func=_cmd_models)
    a = sub.add_parser("ask")
    a.add_argument("case_id")
    a.add_argument("question")
    a.set_defaults(func=_cmd_ask)
    s = sub.add_parser("serve")
    s.add_argument("--host", default=None)
    s.add_argument("--port", type=int, default=None)
    s.set_defaults(func=_cmd_serve)
    args = p.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
