"""Bounded adversary planner (PLAN 8.4).

The adversary never gets a shell, never writes code and never touches the world.
A model may produce ONE planning response: a JSON list of at most eight steps
chosen from the fixed step library with allowlisted parameters. Trusted code
validates it. An invalid plan gets exactly one repair attempt. If that also fails,
or no model is available, the scenario's SCRIPTED plan is used and labeled as such:
we never pretend a model selected it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from alibi.sim import steps as S
from alibi.sim.scenario import plan_context

ADVERSARY_SYSTEM_PROMPT = """You are the adversary in a closed, fully synthetic training simulation of a small
clinic network. Nothing here is real: no real systems, people or data exist. You cannot run commands. You can only
choose steps from a fixed library; a simulator executes them against a synthetic world model.

Reply with ONLY a JSON array of at most 8 steps: [{"step": <name>, "params": {...}, "delay_s": <20-600>}].
The first step must be login_as. Use only the step names, parameter names and values you are given."""

_JSON_ARRAY = re.compile(r"\[.*\]", re.S)


@dataclass
class PlanResult:
    plan: list[dict[str, Any]]
    source: str  # model_generated | scripted_scenario
    model_id: str | None = None
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    fallback_reason: str | None = None

    @property
    def label(self) -> str:
        if self.source == "model_generated":
            return f"Model-generated plan ({self.model_id})"
        return "Scripted scenario · no model chose these steps"


def planning_prompt(spec: dict[str, Any], ctx: S.PlanContext) -> str:
    allowed = S.LEVEL_STEPS[ctx.level]
    lib = {
        "login_as": {"account": list(ctx.accounts)},
        "stage_copy": {"src": [d for d in S.DATASETS if d in ctx.dataset_sizes], "dst_dir": list(S.STAGING_DIRS),
                       "dst_name": f"file name matching {S.STAGING_NAME_RE.pattern}"},
        "exfil_http": {"path": "a path staged earlier in this plan: <dst_dir>/<dst_name>", "dst": list(ctx.sink_ips)},
        "delete_log_lines": {"host": list(S.DELETE_HOSTS), "file": list(S.DELETE_FILES),
                             "event_selection": list(S.DELETE_SELECTIONS)},
    }
    return json.dumps({
        "goal": "copy the synthetic patient dataset to an internal dummy destination using another person's account",
        "difficulty": ctx.level,
        "allowed_steps": {name: lib[name] for name in allowed},
        "notes": ["in dst_dir, {account} is replaced by the account you logged in as",
                  "the log collector is an independent witness"],
    }, indent=1)


def _extract(text: str) -> list[dict[str, Any]]:
    m = _JSON_ARRAY.search(text or "")
    if not m:
        raise S.PlanError("the reply did not contain a JSON array of steps")
    try:
        data = json.loads(m.group(0))
    except ValueError as exc:
        raise S.PlanError(f"the JSON could not be parsed: {exc}") from exc
    if not isinstance(data, list):
        raise S.PlanError("the reply must be a JSON array")
    return data


def _text(msg: Any) -> str:
    content = getattr(msg, "content", msg)
    if isinstance(content, list):
        return "".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content)
    return str(content)


def plan_adversary(spec: dict[str, Any], model: Any | None, model_id: str | None = None) -> PlanResult:
    """Return a validated plan. With model=None (offline) this is always the scripted scenario."""
    ctx = plan_context(spec)
    scripted = S.validate_plan(spec["plan"], ctx)
    if model is None:
        return PlanResult(plan=scripted, source="scripted_scenario", fallback_reason="no model runtime (offline)")
    result = PlanResult(plan=scripted, source="scripted_scenario", model_id=model_id)
    messages: list[Any] = [SystemMessage(ADVERSARY_SYSTEM_PROMPT), HumanMessage(planning_prompt(spec, ctx))]
    for attempt in (1, 2):  # one planning response, at most one repair
        result.attempts = attempt
        try:
            reply = model.invoke(messages)
        except Exception as exc:  # noqa: BLE001 - budget stop or provider error: fall back, labeled
            result.errors.append(f"model call failed: {type(exc).__name__}: {str(exc)[:160]}")
            break
        try:
            plan = S.validate_plan(_extract(_text(reply)), ctx)
        except S.PlanError as exc:
            result.errors.append(str(exc))
            messages += [reply, HumanMessage(f"That plan is invalid: {exc}. Reply with a corrected JSON array only.")]
            continue
        return PlanResult(plan=plan, source="model_generated", model_id=model_id, attempts=attempt, errors=result.errors)
    result.fallback_reason = "the model did not produce a valid plan within one repair attempt"
    return result


def apply_plan(spec: dict[str, Any], result: PlanResult) -> dict[str, Any]:
    """Return a copy of the scenario specification that will execute this plan."""
    out = json.loads(json.dumps(spec))
    out["plan"] = result.plan
    out["plan_source"] = result.source
    return out
