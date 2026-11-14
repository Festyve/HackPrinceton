"""Scenario designer: a model chooses an ORDINARY operating environment. It plans no incident.

This is not the adversary planner, and it does not replace it. The one real request to plan an
adversary's steps was declined by the model; that route stays disabled and nothing here rephrases,
retries or reroutes it. The task below is a different one: pick, from fixed options, how busy an
ordinary working day is, which single routine operational condition occurs (a scheduled log rotation,
an approved backup transfer, a legitimate remote session, a maintenance window, an ordinary collection
interruption, or none), and when. There is no field for a step, a command, a destination or a strategy,
so no output of this module can be one.

Whether a case built on a designed environment also contains an incident is decided by the operator, who
may add one of the pre-authored scripted scenarios. Those steps are scripted and are labeled scripted.

One bounded model response, then everything is offline: trusted code turns the validated choices into a
scenario specification. Output that does not validate is replaced by defaults that are labeled as
defaults. A refusal ends the request.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from alibi.agents import gateway
from alibi.config import RunCaps, Settings
from alibi.sim.scenario import build_spec

DESIGNER_VERSION = "1.0.0"
DESIGN_CAPS = RunCaps(max_calls=1, max_input_tokens=4_000, max_output_tokens=900, max_seconds=60.0,
                      max_input_tokens_per_call=4_000)
SEED_NAMESPACE = 700_000  # designed cases draw their seeds from here, away from every other split
CANDIDATES = 40

Background = Literal["quiet", "normal", "busy"]
Condition = Literal["second_log_rotation", "approved_bulk_transfer", "remote_admin_login",
                    "collection_interruption", "maintenance_window"]
TimeOfDay = Literal["morning", "midday", "afternoon"]
Cause = Literal["agent_restart", "transport_loss"]

# each routine condition is an existing, tested benign building block of the simulator
CONDITION_VARIANT = {"second_log_rotation": "benign_rotation", "approved_bulk_transfer": "benign_approved_transfer",
                     "remote_admin_login": "benign_remote_login", "collection_interruption": "benign_collection_gap",
                     "maintenance_window": "benign_maintenance"}
_TIME_KEY = {"benign_rotation": "forced_rotation_at", "benign_approved_transfer": "start", "benign_remote_login": "start",
             "benign_collection_gap": "start", "benign_maintenance": "maintenance_start"}
# pre-authored scripted incident scenarios an operator may place in a designed environment
FIXTURES = {"none": None, "inside-job-plain": "incident_plain", "inside-job-coverup": "incident_coverup"}
CONDITION_WORDS = {
    "second_log_rotation": "an extra scheduled log rotation that discards the older log generation",
    "approved_bulk_transfer": "an approved bulk transfer to a destination on the approved list",
    "remote_admin_login": "a legitimate remote administrator session through the VPN gateway",
    "collection_interruption": "an ordinary interruption of log collection",
    "maintenance_window": "an approved maintenance window (forwarder restart, a restore, an administrator hop between hosts)",
}


class EnvironmentDesign(BaseModel):
    """The whole of what a model may choose. Every field is an enum or a bounded number."""

    model_config = ConfigDict(extra="forbid")

    background_activity: Background = "normal"
    routine_condition: Condition = "approved_bulk_transfer"
    condition_time: TimeOfDay = "midday"
    interruption_cause: Cause = "agent_restart"
    interruption_seconds: int = Field(default=180, ge=60, le=600)


DEFAULT_DESIGN = EnvironmentDesign()

DESIGNER_SYSTEM = """You help set up a training exercise in which people review evidence from a small clinic network.
Your only job is to choose an ordinary operating environment for one working day, from the fixed options of the
choose_environment tool:
- how busy the shared workstation is;
- the one routine, legitimate operational condition of the day (a scheduled log rotation, an approved backup
  transfer, an administrator working remotely, a maintenance window, or a short interruption of log collection);
- when in the day it happens;
- if it is a collection interruption, its ordinary cause and how long it lasts.
Choose a realistic day. Call choose_environment exactly once and write nothing else."""


def bucket_of(spec: dict[str, Any], variant: str) -> str:
    """Morning, midday or afternoon: when the routine condition of this spec happens, relative to shift start."""
    t0 = datetime.fromisoformat(spec["t0"])
    at = datetime.fromisoformat(spec["benign"][_TIME_KEY[variant]])
    hours = (at - t0).total_seconds() / 3600
    return "morning" if hours < 2.5 else "midday" if hours < 5.0 else "afternoon"


def realize(design: EnvironmentDesign, design_seed: int, fixture: str = "none") -> tuple[dict[str, Any], dict[str, Any]]:
    """Trusted, offline: turn validated choices into a scenario specification. Returns (spec, realized).

    The simulator's own tested ranges are used: candidate specifications are generated from seeds in the
    designer's namespace and the first one whose routine condition falls where it was asked for is taken.
    What was asked for and what was obtained are both recorded.
    """
    if fixture not in FIXTURES:
        raise ValueError(f"unknown fixture {fixture!r}; choose one of {list(FIXTURES)}")
    base = SEED_NAMESPACE + (int(design_seed) % 5000) * 100
    notes: list[str] = []
    incident = FIXTURES[fixture]
    if incident is not None:
        spec = build_spec(base, incident)
        realized = {"seed": base, "variant_family": "pre-authored incident fixture", "routine_condition": None,
                    "condition_time": None}
        notes.append("the chosen routine condition was not applied: a pre-authored incident scenario does not combine "
                     "with it in this simulator. The background activity level was applied.")
    else:
        variant = CONDITION_VARIANT[design.routine_condition]
        best: tuple[float, int, dict[str, Any]] | None = None
        for i in range(CANDIDATES):
            cand = build_spec(base + i, variant)
            cost = 0.0 if bucket_of(cand, variant) == design.condition_time else 10.0
            if variant == "benign_collection_gap":
                cost += 0.0 if cand["benign"]["cause"] == design.interruption_cause else 5.0
                cost += abs(cand["benign"]["duration_s"] - design.interruption_seconds) / 600
            if best is None or cost < best[0]:
                best = (cost, base + i, cand)
            if cost < 0.2:
                break
        assert best is not None
        _, seed, spec = best
        realized = {"seed": seed, "variant_family": "routine day", "routine_condition": design.routine_condition,
                    "condition_time": bucket_of(spec, variant)}
        if realized["condition_time"] != design.condition_time:
            notes.append(f"no candidate placed the condition in the {design.condition_time}; the closest was used")
        if variant == "benign_collection_gap":
            realized.update(interruption_cause=spec["benign"]["cause"], interruption_seconds=spec["benign"]["duration_s"])
    spec["environment"] = {"background_activity": design.background_activity}
    realized["background_activity"] = design.background_activity
    realized["notes"] = notes
    return spec, realized


def preview(design: EnvironmentDesign) -> list[str]:
    """The design in plain words, for a person to read before anything is generated."""
    out = [f"Shared workstation: a {design.background_activity} day.",
           f"Routine condition: {CONDITION_WORDS[design.routine_condition]}, in the {design.condition_time}."]
    if design.routine_condition == "collection_interruption":
        out.append(f"Interruption: about {design.interruption_seconds} seconds, caused by "
                   f"{design.interruption_cause.replace('_', ' ')}.")
    out.append("No incident is part of a design. An operator may place a pre-authored, scripted incident scenario in "
               "this environment; that choice is not made by the model.")
    return out


def _label(source: str, model_id: str | None) -> str:
    if source == "model_designed":
        return (f"Environment chosen by a model ({model_id}) from fixed options. It planned no incident; "
                "any incident steps are a pre-authored scripted scenario.")
    if source == "default_after_invalid_output":
        return "Default environment · the model's output was not valid, so no model choice was used"
    return "Default environment · no model was asked"


def design_environment(settings: Settings, design_seed: int, *, model_factory: Any = None,
                       ledger_path: Any = None) -> dict[str, Any]:
    """One bounded model response choosing an environment. Never raises for model or budget problems.

    status: designed | default_used | refused | unavailable
    """
    out: dict[str, Any] = {"designer_version": DESIGNER_VERSION, "design_seed": int(design_seed), "status": "default_used",
                           "source": "default", "model_id": None, "design": DEFAULT_DESIGN.model_dump(),
                           "fallback_reason": None, "usage": None}
    if settings.live_block_reason() is not None and model_factory is None:
        out["fallback_reason"] = "no model is configured on this server"
        out["label"] = _label("default", None)
        out["preview"] = preview(DEFAULT_DESIGN)
        return out
    ledger = gateway.make_ledger(settings, ledger_path, scripted=False, label="scenario-design", caps=DESIGN_CAPS)
    ledger.max_tokens_per_call = 800
    chosen: dict[str, Any] = {}

    def choose_environment(background_activity: Background, routine_condition: Condition, condition_time: TimeOfDay,
                           interruption_cause: Cause = "agent_restart", interruption_seconds: int = 180) -> str:
        """Choose the ordinary operating environment for the day. interruption_cause and interruption_seconds
        (60 to 600) matter only when routine_condition is collection_interruption."""
        chosen.update(background_activity=background_activity, routine_condition=routine_condition,
                      condition_time=condition_time, interruption_cause=interruption_cause,
                      interruption_seconds=interruption_seconds)
        return "recorded"

    tool = StructuredTool.from_function(choose_environment)
    out["model_id"] = settings.lead_model
    try:
        model = model_factory(ledger) if model_factory else gateway.wrap(
            gateway.live_chat_model(settings, settings.lead_model or "", ledger.max_tokens_per_call), ledger,
            "scenario-designer")
        ai = model.bind_tools([tool]).invoke([
            SystemMessage(DESIGNER_SYSTEM),
            HumanMessage(f"Choose the environment for exercise number {int(design_seed)}.")])
        calls = [tc for tc in (getattr(ai, "tool_calls", None) or []) if tc["name"] == "choose_environment"]
        if not calls:
            raise ValueError("the model did not call choose_environment")
        tool.invoke(calls[0].get("args") or {})  # the tool's own schema rejects anything outside the options
        design = EnvironmentDesign.model_validate(chosen)
        out.update(status="designed", source="model_designed", design=design.model_dump())
    except gateway.ModelRefused as exc:
        # A refusal ends the request: no defaults are substituted, nothing is retried or sent elsewhere.
        out.update(status="refused", source="none", design=None, fallback_reason=str(exc))
    except gateway.BudgetExceeded as exc:
        out.update(status="unavailable", source="none", design=None,
                   fallback_reason=f"stopped by the budget gateway: {str(exc)[:200]}")
    except Exception as exc:  # noqa: BLE001 - invalid output or a provider error: labeled defaults
        out.update(status="default_used", source="default_after_invalid_output", design=DEFAULT_DESIGN.model_dump(),
                   fallback_reason=f"{type(exc).__name__}: {str(exc)[:200]}")
    out["usage"] = ledger.usage().model_dump()
    out["label"] = _label(out["source"], out["model_id"]) if out["design"] else "No environment was designed"
    out["preview"] = preview(EnvironmentDesign.model_validate(out["design"])) if out["design"] else []
    return out


def provenance(result: dict[str, Any], realized: dict[str, Any], fixture: str) -> dict[str, Any]:
    """What goes into the scenario specification (sealed side) and the audience log."""
    return {"designer_version": result["designer_version"], "source": result["source"], "label": result["label"],
            "model_id": result["model_id"] if result["source"] == "model_designed" else None,
            "requested": result["design"], "realized": realized, "fixture": fixture,
            "incident_steps_chosen_by_model": False, "usage": result.get("usage"),
            "fallback_reason": result.get("fallback_reason")}


__all__ = ["DEFAULT_DESIGN", "FIXTURES", "EnvironmentDesign", "design_environment", "preview", "provenance", "realize"]
_ = json
