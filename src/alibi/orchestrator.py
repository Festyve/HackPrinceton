"""Case orchestration: explicit states, an append-only event log, review/lock/reveal/reset.

States
    created -> generating -> frozen -> investigating -> awaiting_review
            -> report_locked -> scored            (also: failed, cancelled)

Information barrier (PLAN 7.3)
  * Runners receive a RunContext (read-only store + public manifest + case dir). They
    never receive the sealed directory, the seed, the preset or the scenario.
  * The sealed answer key is read in exactly one place, `reveal`, and only after the
    report is locked. Until then no API response or stream event carries truth.
  * The audience stream and the investigator stream use different serializers.
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alibi import explain, evidence_views, export, questions, source_experiment
from alibi.config import REPO_ROOT, Settings
from alibi.contracts import INFERENCE_LABELS, InvestigationReport, QuestionAnswer
from alibi.episode import (
    EpisodePaths,
    create_episode,
    episode_paths,
    load_answer_key,
    load_episode_manifest,
    load_manifest,
    remove_episode,
    validate_episode_id,
)
from alibi.evidence.store import EvidenceStore
from alibi.reports import lock_report
from alibi.runners import MODE_LABELS, Cancelled, RunContext, RuntimeBlocked, default_runner_id, get_runner, resolve_mode
from alibi.scoring import score_report
from alibi.sim.scenario import CARDS, VARIANT_CARD, build_spec
from alibi.verifier import verify_report

STATES = ("created", "generating", "frozen", "investigating", "awaiting_review", "report_locked", "scored",
          "failed", "cancelled")
TRANSIENT = ("generating", "investigating")
# Event types an investigator-side consumer may see. Orchestrator and reveal events are audience-only.
INVESTIGATOR_EVENT_TYPES = ("todo", "agent", "tool", "finding", "note", "attribution", "report", "usage")
REPLAY_DIR = REPO_ROOT / "demo" / "replays"

# Demo presets. Seeds here are disjoint from development seeds and declared benchmark seeds.
# `_variant` is private: it is never serialized to any client before reveal.
PRESETS: list[dict[str, Any]] = [
    {"id": "hero-coverup", "title": "Inside job · cover-up", "difficulty": "L2", "card_id": "inside-job", "seed": 9023,
     "blurb": "Someone uses a colleague's account, copies the synthetic patient database out, then edits a host log.",
     "_variant": "incident_coverup"},
    {"id": "hero-plain", "title": "Inside job · no cover-up", "difficulty": "L1", "card_id": "inside-job", "seed": 9002,
     "blurb": "The same crime with no anti-forensics.", "_variant": "incident_plain"},
    {"id": "sealed-control", "title": "Sealed control case", "difficulty": "sealed", "card_id": "inside-job", "seed": 9003,
     "blurb": "May or may not contain an incident. The investigator gets the same tip. Unseal to find out.",
     "_variant": "benign_approved_transfer"},
    # --- the remaining case families (phase two). Scripted scenarios on simulated evidence, like the others.
    {"id": "evasion", "title": "Inside job · covering tracks", "difficulty": "L3", "card_id": "inside-job", "seed": 9041,
     "blurb": "The same crime, then four attempts to cover it: cleared shell history, a backdated file, log "
              "forwarding stopped and a hop to a second host. One of them leaves nothing an investigator can see.",
     "_variant": "incident_evasion"},
    {"id": "maintenance-control", "title": "Sealed control case · maintenance window", "difficulty": "sealed",
     "card_id": "inside-job", "seed": 9042,
     "blurb": "May or may not contain an incident. The same kinds of activity can be legitimate maintenance. Unseal to find out.",
     "_variant": "benign_maintenance"},
    {"id": "records-heist", "title": "Records heist · cover-up", "difficulty": "H2", "card_id": "records-heist", "seed": 9041,
     "blurb": "Someone signs in to the records server with an administrator's credential, exports the synthetic "
              "patient database there, sends it out and edits the application's own log.",
     "_variant": "heist_coverup"},
    {"id": "records-control", "title": "Sealed control case · records export", "difficulty": "sealed",
     "card_id": "records-heist", "seed": 9043,
     "blurb": "May or may not contain an incident. An export from the records server can be approved work. Unseal to find out.",
     "_variant": "heist_approved_export"},
    {"id": "cold-chain", "title": "Cold chain · altered readings", "difficulty": "C1", "card_id": "cold-chain", "seed": 9041,
     "blurb": "The vaccine refrigerator warms past its range and the stored readings are overwritten to look normal. "
              "An independent reference logger kept recording.",
     "_variant": "coldchain_falsified"},
    {"id": "cold-chain-control", "title": "Sealed control case · cold chain", "difficulty": "sealed",
     "card_id": "cold-chain", "seed": 9044,
     "blurb": "May or may not contain an incident. A real excursion with honest records is not falsification. Unseal to find out.",
     "_variant": "coldchain_real_excursion"},
    {"id": "model-planned", "title": "Inside job · model-planned adversary", "difficulty": "L2", "card_id": "inside-job",
     "seed": 9027,
     "blurb": "A model chooses the adversary's steps from the bounded library (one planning response). "
              "Needs a live model runtime.",
     "_variant": "incident_coverup", "_planner": "model"},
]
_CUSTOM_VARIANT = {"L1": "incident_plain", "L2": "incident_coverup"}


def questions_id_ok(question_id: str) -> bool:
    import re

    return bool(re.fullmatch(r"q-[0-9a-f]{10}", str(question_id)))


def _recorded_mode(meta: dict[str, Any]) -> str | None:
    """The mode a recording was made in. Recordings from before modes existed all used the specialist graph."""
    if meta.get("runner_id", "deterministic") == "deterministic":
        return None
    return meta.get("investigation_mode") or "specialist"


class NotFound(LookupError):
    pass


class Conflict(RuntimeError):
    """The request is not valid in the case's current state."""

    def __init__(self, message: str, state: str | None = None):
        super().__init__(message)
        self.state = state


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


@dataclass
class CaseRecord:
    case_id: str
    state: str = "created"
    detail: str = ""
    created_at: str = field(default_factory=_iso_now)
    updated_at: str = field(default_factory=_iso_now)
    preset_id: str | None = None
    title: str = ""
    card_id: str = "inside-job"
    difficulty: str = ""
    seed: int | None = None
    runner_id: str = "deterministic"
    # fast (one agent) | specialist (lead + auditor + skeptic) | None for the deterministic runner. Saved with
    # the case, so a refresh, a restart or the review resume can never switch it.
    investigation_mode: str | None = None
    evidence_origin: str = "SIM"
    inference_mode: str = "NO_MODEL_BASELINE"
    playback: str = "LIVE"
    model_id: str | None = None
    bundle_id: str | None = None
    error: str | None = None
    client_token: str | None = None
    replay_of: str | None = None
    recorded_at: str | None = None
    review_decision: str | None = None
    review_note: str = ""
    timings: dict[str, float] = field(default_factory=dict)
    # Set only for an evidence view derived from another case with some sources withheld.
    parent_case_id: str | None = None
    excluded_sources: list[dict[str, Any]] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("client_token", None)
        d["labels"] = {
            "evidence_origin": self.evidence_origin,
            "inference": self.inference_mode,
            "inference_label": INFERENCE_LABELS.get(self.inference_mode, self.inference_mode),
            "playback": self.playback,
            "model_id": self.model_id,
            "investigation_mode": self.investigation_mode,
            "investigation_mode_label": MODE_LABELS.get(self.investigation_mode or "", "Deterministic checks · no agent"),
        }
        return d


class EventLog:
    """Append-only per-case event log with stable sequence ids."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._events.append(json.loads(line))

    def append(self, etype: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            ev = {"seq": len(self._events) + 1, "ts": _iso_now(), "type": etype, "data": data}
            self._events.append(ev)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, default=str) + "\n")
            return ev

    def since(self, after: int = 0, view: str = "audience") -> list[dict[str, Any]]:
        with self._lock:
            evs = [e for e in self._events if e["seq"] > after]
        if view == "investigator":
            evs = [e for e in evs if e["type"] in INVESTIGATOR_EVENT_TYPES]
        return evs

    def last_seq(self) -> int:
        with self._lock:
            return len(self._events)


class Orchestrator:
    def __init__(self, settings: Settings, *, pace_s: float | None = None):
        self.settings = settings
        self.runs_dir = Path(settings.runs_dir)
        self.sealed_dir = Path(settings.sealed_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.sealed_dir.mkdir(parents=True, exist_ok=True)
        env_pace = os.environ.get("ALIBI_DEMO_PACE_S")
        self.pace_s = pace_s if pace_s is not None else (float(env_pace) if env_pace else 0.45)
        self._guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}
        self._logs: dict[str, EventLog] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._tokens: dict[str, str] = {}
        self._qa_active: dict[str, str] = {}  # case id -> the one question being answered for it
        self._qa_threads: dict[str, threading.Thread] = {}
        self.qa_model_factory: Any = None  # tests only: a stand-in model; production builds the real one
        self._recover()

    # ------------------------------------------------------------------ plumbing
    def _paths(self, case_id: str) -> EpisodePaths:
        try:
            validate_episode_id(case_id)
        except Exception as exc:
            raise NotFound("no such case") from exc
        return episode_paths(case_id, self.runs_dir, self.sealed_dir)

    def _lock(self, case_id: str) -> threading.RLock:
        with self._guard:
            return self._locks.setdefault(case_id, threading.RLock())

    def _log(self, case_id: str) -> EventLog:
        with self._guard:
            if case_id not in self._logs:
                self._logs[case_id] = EventLog(self._paths(case_id).root / "events.jsonl")
            return self._logs[case_id]

    def _status_path(self, case_id: str) -> Path:
        return self._paths(case_id).root / "status.json"

    def _load(self, case_id: str) -> CaseRecord:
        path = self._status_path(case_id)
        if not path.exists():
            raise NotFound("no such case")
        return CaseRecord(**json.loads(path.read_text(encoding="utf-8")))

    def _save(self, rec: CaseRecord) -> None:
        rec.updated_at = _iso_now()
        path = self._status_path(rec.case_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(rec), indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _set_state(self, rec: CaseRecord, state: str, detail: str = "") -> None:
        assert state in STATES
        rec.state, rec.detail = state, detail
        self._save(rec)
        self._log(rec.case_id).append("state", {"state": state, "detail": detail})

    def _recover(self) -> None:
        """After a restart, a case that was mid-run is a visible failure, not an endless spinner."""
        for status in self.runs_dir.glob("*/status.json"):
            try:
                rec = CaseRecord(**json.loads(status.read_text(encoding="utf-8")))
            except Exception:
                continue
            if rec.client_token:
                self._tokens[rec.client_token] = rec.case_id
            if rec.state in TRANSIENT:
                rec.error = "interrupted by a server restart; reset the case and run it again"
                self._set_state(rec, "failed", rec.error)
            for qf in (status.parent / "case" / "questions").glob("q-*.json"):
                try:  # a question that was mid-answer is a visible failure too, never an endless "pending"
                    q = QuestionAnswer.model_validate_json(qf.read_text(encoding="utf-8"))
                    if q.status == "pending":
                        qf.write_text(q.model_copy(update={
                            "status": "failed", "answered_at": _now(),
                            "error": "interrupted by a server restart before an answer was produced; ask again",
                        }).model_dump_json(indent=1), encoding="utf-8")
                except Exception:
                    continue

    # ------------------------------------------------------------------ presets / replays
    def presets(self) -> list[dict[str, Any]]:
        """Only presets that can actually run are offered (a model-planned case needs a live runtime)."""
        return [{k: v for k, v in p.items() if not k.startswith("_")} for p in PRESETS
                if p.get("_planner") != "model" or self._model_planner_enabled()]

    def capabilities(self) -> dict[str, Any]:
        """What this server can do. "configured" means settings allow it, not that a model call has succeeded."""
        live = self.settings.live_block_reason() is None
        return {
            "investigation_modes": {
                "available": list(MODE_LABELS), "labels": MODE_LABELS,
                "default": resolve_mode(default_runner_id(self.settings), None),
                "note": "fast is the default for a live model; the scripted fixture defaults to specialist",
            },
            "live_model": {"configured": live, "model_id": self.settings.lead_model if live else None,
                           "note": "configured does not mean a successful model call has been observed"},
            "scenario_designer": {
                "endpoint": True, "model": "CONFIGURED" if live else "BLOCKED",
                "chooses": ["background activity", "one routine operational condition", "time of day",
                            "collection interruption cause and length"],
                "never_chooses": "incident steps, commands, destinations or strategy. Incidents are pre-authored scripted scenarios",
                "note": ("one bounded model response, then offline generation" if live else
                         "no model is configured: a default environment is returned and labeled as a default"),
            },
            "report_export": {"endpoint": True, "formats": ["markdown", "json"],
                              "note": "available once a report is locked; never contains the sealed answer"},
            "source_experiments": {
                "endpoint": True, "max_excluded_sources": source_experiment.MAX_EXCLUDED,
                "note": "derives a new evidence view with chosen sources withheld; the comparison of the original "
                        "claims is deterministic and needs no model. A fresh investigation of the view is a separate run",
            },
            "questions": {
                "endpoint": True, "model_answers": "CONFIGURED" if live else "BLOCKED",
                "max_question_chars": questions.MAX_QUESTION_CHARS, "max_model_calls": questions.MAX_MODEL_CALLS,
                "max_questions_per_case": questions.MAX_QUESTIONS_PER_CASE,
                "note": ("answers come from a model with read-only access to this case's evidence and report" if live else
                         "no model is configured: a question returns status 'unavailable'; the predefined, "
                         "labeled explanations remain available"),
            },
        }

    def _model_planner_enabled(self) -> bool:
        """The model-planned adversary preset is opt-in (ALIBI_ENABLE_MODEL_ADVERSARY=1) and needs a live runtime.

        It is off by default because the one model it was tried with declined the planning request, so the
        preset could only ever fall back to the scripted scenario. A control that cannot do what its
        label says is not offered.
        """
        return (os.environ.get("ALIBI_ENABLE_MODEL_ADVERSARY") == "1"
                and self.settings.live_block_reason() is None and bool(self.settings.adversary_model))

    def _plan_with_model(self, spec: dict[str, Any]) -> dict[str, Any]:
        """One bounded planning response (plus one repair) from the adversary model, through the gateway."""
        from alibi.agents import adversary, gateway
        from alibi.config import RunCaps

        ledger = gateway.make_ledger(self.settings, None, scripted=False, label="adversary-plan",
                                     caps=RunCaps(max_calls=2, max_input_tokens=8_000, max_output_tokens=3_000,
                                                  max_seconds=120, max_input_tokens_per_call=4_000))
        model = self._adversary_model(ledger)
        result = adversary.plan_adversary(spec, model, model_id=self.settings.adversary_model)
        out = adversary.apply_plan(spec, result)
        out["plan_provenance"]["usage"] = ledger.usage().model_dump()
        return out

    def _adversary_model(self, ledger: Any) -> Any:
        from alibi.agents import gateway

        return gateway.wrap(gateway.live_chat_model(self.settings, self.settings.adversary_model or ""), ledger, "adversary")

    @staticmethod
    def replays() -> list[dict[str, Any]]:
        out = []
        for f in sorted(REPLAY_DIR.glob("*/recording.json")):
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))["meta"]
            except Exception:
                continue
            # A saved real run is offered as a RECORDED model run. It is never listed as live.
            mode = "RECORDED_MODEL" if meta.get("inference_mode") == "LIVE_MODEL" else meta.get("inference_mode", "")
            run_mode = _recorded_mode(meta)
            out.append({"id": f.parent.name, **{k: meta.get(k) for k in (
                "title", "model_id", "recorded_at", "runner_id", "git_commit", "note")},
                "inference_mode": mode, "inference_label": INFERENCE_LABELS.get(mode, ""),
                "investigation_mode": run_mode, "investigation_mode_label": MODE_LABELS.get(run_mode or "", "")})
        return out

    # ------------------------------------------------------------------ create
    def create_case(self, *, preset_id: str | None = None, seed: int | None = None, difficulty: str | None = None,
                    runner_id: str | None = None, client_token: str | None = None,
                    investigation_mode: str | None = None) -> CaseRecord:
        with self._guard:
            if client_token and client_token in self._tokens:
                try:
                    return self._load(self._tokens[client_token])  # duplicate Run request: same case
                except NotFound:
                    self._tokens.pop(client_token, None)
        if preset_id is not None:
            preset = next((p for p in PRESETS if p["id"] == preset_id), None)
            if preset is None:
                raise NotFound("no such preset")
            variant, seed, title, diff = preset["_variant"], preset["seed"], preset["title"], preset["difficulty"]
            if preset.get("_planner") == "model" and not self._model_planner_enabled():
                reason = self.settings.live_block_reason()
                raise RuntimeBlocked("the model-planned adversary preset is not enabled: it needs a live runtime, "
                                     "ADVERSARY_MODEL and ALIBI_ENABLE_MODEL_ADVERSARY=1"
                                     + (f" ({reason})" if reason else ""))
        else:
            if difficulty not in _CUSTOM_VARIANT or seed is None:
                raise ValueError("custom cases need a seed and difficulty L1 or L2")
            variant, title, diff = _CUSTOM_VARIANT[difficulty], f"Inside job · seed {seed}", difficulty
        runner_id = runner_id or default_runner_id(self.settings)
        mode = resolve_mode(runner_id, investigation_mode)
        runner = get_runner(runner_id, self.settings, mode)
        case_id = f"case-{uuid.uuid4().hex[:12]}"
        rec = CaseRecord(case_id=case_id, preset_id=preset_id, title=title, difficulty=diff, seed=seed,
                         card_id=VARIANT_CARD.get(variant, "inside-job"),
                         runner_id=runner_id, investigation_mode=mode, inference_mode=runner.inference_mode,
                         model_id=runner.model_id, client_token=client_token)
        spec = None
        if preset_id is not None and preset.get("_planner") == "model":
            t0 = time.perf_counter()
            spec = self._plan_with_model(build_spec(seed, variant))
            rec.timings["adversary_plan_s"] = round(time.perf_counter() - t0, 3)
        return self._generate(rec, seed=seed, variant=variant, spec=spec)

    def create_case_from_spec(self, spec: dict[str, Any], *, title: str = "Custom scenario",
                              runner_id: str | None = None, investigation_mode: str | None = None,
                              difficulty: str | None = None, client_token: str | None = None) -> CaseRecord:
        """Operator/test entry point: run a saved scenario specification. Not exposed over HTTP."""
        runner_id = runner_id or default_runner_id(self.settings)
        mode = resolve_mode(runner_id, investigation_mode)
        runner = get_runner(runner_id, self.settings, mode)
        rec = CaseRecord(case_id=f"case-{uuid.uuid4().hex[:12]}", title=title,
                         difficulty=difficulty if difficulty is not None else str(spec.get("difficulty", "")),
                         seed=spec.get("seed"), card_id=str(spec.get("card_id") or "inside-job"), runner_id=runner_id,
                         investigation_mode=mode, inference_mode=runner.inference_mode, model_id=runner.model_id,
                         client_token=client_token)
        return self._generate(rec, seed=None, variant=None, spec=spec)

    # ------------------------------------------------------------------ scenario designer (environment only)
    def _design_dir(self) -> Path:
        return self.runs_dir / "_designs"

    def design_environment(self, client_token: str, design_seed: int | None = None) -> dict[str, Any]:
        """Ask a model, once, to choose an ordinary operating environment. Returns the stored design.

        The model chooses no incident and no step. Offline, a default environment is returned and labeled as one.
        """
        from alibi.agents import designer

        token = str(client_token or "").strip()
        if not token or len(token) > 80:
            raise ValueError("client_token is required (at most 80 characters); it makes a retried request safe")
        ddir = self._design_dir()
        ddir.mkdir(parents=True, exist_ok=True)
        with self._guard:
            index_file = ddir / "index.json"
            index = json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else {}
            if token in index:
                return json.loads((ddir / f"{index[token]}.json").read_text(encoding="utf-8"))  # a retry: no second call
            seed = int(design_seed) if design_seed is not None else (len(index) + 1)
            design_id = f"design-{uuid.uuid4().hex[:10]}"
            doc = designer.design_environment(self.settings, seed, model_factory=self.qa_model_factory,
                                              ledger_path=ddir / f"{design_id}.budget.json")
            doc.update(design_id=design_id, created_at=_iso_now(), fixtures=list(designer.FIXTURES))
            (ddir / f"{design_id}.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
            index[token] = design_id
            index_file.write_text(json.dumps(index), encoding="utf-8")
            return doc

    def get_design(self, design_id: str) -> dict[str, Any]:
        import re

        f = self._design_dir() / f"{design_id}.json"
        if not re.fullmatch(r"design-[0-9a-f]{10}", str(design_id)) or not f.exists():
            raise NotFound("no such design")
        return json.loads(f.read_text(encoding="utf-8"))

    def create_case_from_design(self, design_id: str, *, fixture: str = "none", runner_id: str | None = None,
                                investigation_mode: str | None = None, client_token: str | None = None) -> CaseRecord:
        """Generate a case in a designed environment. `fixture` optionally places a pre-authored, scripted incident
        scenario in it; that choice is the operator's, never the model's, and is not shown before the reveal."""
        from alibi.agents import designer

        with self._guard:
            if client_token and client_token in self._tokens:
                try:
                    return self._load(self._tokens[client_token])
                except NotFound:
                    self._tokens.pop(client_token, None)
        doc = self.get_design(design_id)
        if not doc.get("design"):
            raise Conflict(f"this design request ended without a design ({doc['status']}); no case can be made from it")
        design = designer.EnvironmentDesign.model_validate(doc["design"])
        spec, realized = designer.realize(design, doc["design_seed"], fixture)
        spec["environment_provenance"] = designer.provenance(doc, realized, fixture)
        return self.create_case_from_spec(
            spec, title=f"Designed environment · exercise {doc['design_seed']}", runner_id=runner_id,
            investigation_mode=investigation_mode, difficulty="sealed", client_token=client_token)

    def _generate(self, rec: CaseRecord, *, seed: int | None, variant: str | None, spec: dict | None) -> CaseRecord:
        case_id = rec.case_id
        t0 = time.perf_counter()
        try:
            prov = (spec or {}).get("plan_provenance") or {}
            paths = create_episode(seed=seed or 0, variant=variant or "", runs_dir=self.runs_dir,
                                   sealed_dir=self.sealed_dir, episode_id=case_id, spec=spec,
                                   plan_model_id=prov.get("model_id") if prov.get("source") == "model_generated" else None)
        except Exception as exc:
            raise ValueError(f"could not generate the case: {exc}") from exc
        manifest = load_manifest(paths)
        rec.bundle_id = manifest.bundle_id
        rec.timings["generate_s"] = round(time.perf_counter() - t0, 3)
        self._save(rec)
        if rec.client_token:
            with self._guard:
                self._tokens[rec.client_token] = case_id
        log = self._log(case_id)
        log.append("state", {"state": "generating", "detail": "simulating the shift"})
        log.append("stage", {"name": "generate", "status": "done",
                             "info": {"card": CARDS[rec.card_id]["title"], "evidence_origin": "SIM"}})
        log.append("stage", {"name": "freeze", "status": "done",
                             "info": {"artifacts": len(manifest.sources), "raw_bundle_sha256": manifest.raw_bundle_sha256}})
        log.append("stage", {"name": "normalize", "status": "done",
                             "info": {"events": manifest.event_count, "errors": len(manifest.normalization_errors),
                                      "derived_db_sha256": manifest.derived_db_sha256}})
        log.append("stage", {"name": "seal", "status": "done",
                             "info": {"note": "what actually happened is sealed until the report is locked"}})
        if spec is not None and spec.get("plan_provenance"):
            # who planned is shown to the audience; what was planned stays sealed
            log.append("stage", {"name": "adversary_plan", "status": "done",
                                 "info": {"planned_by": spec["plan_provenance"]["label"]}})
        if spec is not None and spec.get("environment_provenance"):
            # who chose the ordinary environment is shown; whether an incident scenario was placed in it stays sealed
            log.append("stage", {"name": "environment_design", "status": "done",
                                 "info": {"designed_by": spec["environment_provenance"]["label"]}})
        self._set_state(rec, "frozen", "evidence frozen and hashed; answer key sealed")
        return rec

    # ------------------------------------------------------------------ investigate
    def start_investigation(self, case_id: str) -> CaseRecord:
        with self._lock(case_id):
            rec = self._load(case_id)
            if rec.state != "frozen":
                return rec  # duplicate request: never start a second run
            self._cancel[case_id] = threading.Event()
            self._set_state(rec, "investigating", "investigator working on the frozen evidence")
            target = self._replay_thread if rec.playback == "REPLAY" else self._investigate_thread
            th = threading.Thread(target=target, args=(case_id,), name=f"investigate-{case_id}", daemon=True)
            self._threads[case_id] = th
            th.start()
            return rec

    def _context(self, rec: CaseRecord, paths: EpisodePaths, store: EvidenceStore) -> RunContext:
        log = self._log(rec.case_id)
        cancel = self._cancel.setdefault(rec.case_id, threading.Event())
        # Display pacing exists to make sub-second fixture runs readable. A real model sets its own pace.
        pace = 0.0 if rec.inference_mode == "LIVE_MODEL" else self.pace_s
        return RunContext(case_id=rec.case_id, store=store, manifest=load_manifest(paths), case_dir=paths.case,
                          settings=self.settings, emit=lambda t, d: log.append(t, d), pace_s=pace,
                          is_cancelled=cancel.is_set)

    def _finish_draft(self, rec: CaseRecord, paths: EpisodePaths, store: EvidenceStore,
                      report: InvestigationReport, compute_s: float) -> None:
        log = self._log(rec.case_id)
        report = verify_report(report, store, load_manifest(paths))
        report.created_at = report.created_at or _now()
        (paths.case / "report.draft.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        for f in report.findings:
            log.append("finding", {"finding": f.model_dump(mode="json"), "phase": "verified"})
        log.append("attribution", {"attribution": report.attribution.model_dump(mode="json")})
        log.append("usage", {"usage": report.usage.model_dump(mode="json")})
        log.append("report", {"report_id": report.report_id, "status": "awaiting_review",
                              "findings": len(report.findings)})
        rec.timings["investigate_s"] = round(compute_s, 3)
        self._set_state(rec, "awaiting_review", "report drafted; waiting for a human to accept or reject it")

    def _model_changed(self, rec: CaseRecord) -> bool:
        return rec.runner_id == "agent-live" and rec.model_id != self.settings.lead_model

    def _same_model_or_refuse(self, rec: CaseRecord) -> None:
        """A case is investigated by the model it was created with, or not at all."""
        if self._model_changed(rec):
            raise RuntimeBlocked(f"this case was created for {rec.model_id}, but the runtime is now configured for "
                                 f"{self.settings.lead_model}. Create a new case instead of switching models mid-case.")

    def _fail(self, case_id: str, exc: BaseException) -> None:
        rec = self._load(case_id)
        if isinstance(exc, Cancelled):
            self._set_state(rec, "cancelled", "cancelled by the operator")
            return
        try:
            (self._paths(case_id).case / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        except OSError:
            pass
        rec.error = f"{type(exc).__name__}: {str(exc)[:300]}"
        self._log(case_id).append("error", {"message": rec.error})
        self._set_state(rec, "failed", rec.error)

    def _investigate_thread(self, case_id: str) -> None:
        try:
            rec, paths = self._load(case_id), self._paths(case_id)
            self._same_model_or_refuse(rec)
            runner = get_runner(rec.runner_id, self.settings, rec.investigation_mode)
            with EvidenceStore(paths.db) as store:
                ctx = self._context(rec, paths, store)
                self._log(case_id).append("stage", {"name": "investigate", "status": "started",
                                                    "info": {"runner": rec.runner_id, "inference": rec.inference_mode,
                                                             "investigation_mode": rec.investigation_mode,
                                                             "model_id": rec.model_id}})
                t0 = time.perf_counter()
                report = runner.run(ctx)
                compute = max(0.0, time.perf_counter() - t0 - ctx.paced_seconds)
                with self._lock(case_id):
                    self._finish_draft(self._load(case_id), paths, store, report, compute)
        except BaseException as exc:  # noqa: BLE001 - a crashed run must become a visible state
            self._fail(case_id, exc)

    # ------------------------------------------------------------------ review / lock
    def review(self, case_id: str, decision: str, note: str = "") -> dict[str, Any]:
        if decision not in ("accept", "reject"):
            raise ValueError("decision must be accept or reject")
        with self._lock(case_id):
            rec, paths = self._load(case_id), self._paths(case_id)
            if rec.state in ("report_locked", "scored"):
                return self.view(case_id)  # duplicate review: the first decision stands
            if rec.state != "awaiting_review":
                raise Conflict(f"there is no report awaiting review (state: {rec.state})", rec.state)
            draft = InvestigationReport.model_validate_json((paths.case / "report.draft.json").read_text(encoding="utf-8"))
            if rec.playback != "REPLAY":
                if self._model_changed(rec):
                    # The model that investigated is no longer the configured one. The decision is recorded
                    # and the report locks; a different model is never asked to finish another model's run.
                    self._log(case_id).append("stage", {"name": "review_resume", "status": "skipped", "info": {
                        "note": "the model that ran this investigation is no longer configured, so the decision "
                                "was recorded without a model acknowledgement"}})
                else:
                    with EvidenceStore(paths.db) as store:
                        get_runner(rec.runner_id, self.settings, rec.investigation_mode).resume(
                            self._context(rec, paths, store), decision)
            status = "accepted" if decision == "accept" else "rejected"
            locked = lock_report(draft, status, by_human=True, note=note[:500])
            final = paths.case / "report.json"
            final.write_text(locked.model_dump_json(indent=2), encoding="utf-8")
            final.chmod(0o444)
            rec.review_decision, rec.review_note = status, note[:500]
            log = self._log(case_id)
            log.append("review", {"decision": status, "by_human": True, "note": note[:500]})
            log.append("locked", {"report_sha256": locked.report_sha256, "locked_at": locked.locked_at.isoformat()})
            self._set_state(rec, "report_locked", f"report {status} and locked; truth can now be unsealed")
            return self.view(case_id)

    # ------------------------------------------------------------------ reveal (the only reader of sealed truth)
    def reveal(self, case_id: str) -> dict[str, Any]:
        with self._lock(case_id):
            rec, paths = self._load(case_id), self._paths(case_id)
            if rec.state == "scored":
                return self.view(case_id)
            if rec.state != "report_locked":
                raise Conflict("reveal refused: the report must be locked before truth is unsealed", rec.state)
            report = InvestigationReport.model_validate_json((paths.case / "report.json").read_text(encoding="utf-8"))
            key = load_answer_key(paths)
            ep = load_episode_manifest(paths)
            with EvidenceStore(paths.db) as store:
                score = score_report(report, key, store)
            truth = {
                "case_kind": key.case_kind, "variant": ep.variant, "difficulty": key.difficulty, "seed": ep.seed,
                "plan_source": ep.plan_source, "plan_model_id": ep.plan_model_id,
                "plan_label": ("Scripted scenario · no model chose these steps" if ep.plan_source == "scripted_scenario"
                               else f"Model-generated plan ({ep.plan_model_id})"),
                "plan_provenance": ep.scenario_spec.get("plan_provenance"),
                "environment_provenance": ep.scenario_spec.get("environment_provenance"),
                "steps": [s.model_dump(mode="json") for s in key.steps],
                "effects": [e.model_dump(mode="json", exclude={"evidence"}) for e in key.effects],
                "benign_outcomes": [b.model_dump(mode="json") for b in key.benign_outcomes],
                "attribution": key.attribution.model_dump(mode="json"),
            }
            payload = {"score": score.model_dump(mode="json"), "truth": truth}
            if rec.parent_case_id:
                payload["source_experiment"] = self._child_scoring(rec, paths, score, key)
            (paths.root / "score.json").write_text(json.dumps(payload["score"], indent=2), encoding="utf-8")
            (paths.root / "reveal.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._log(case_id).append("reveal", {"summary": {
                "case_kind": key.case_kind, "caught": sum(o.outcome == "caught" for o in score.effect_outcomes),
                "missed": sum(o.outcome == "missed" for o in score.effect_outcomes),
                "unsupported": score.false_claims_final}})
            self._set_state(rec, "scored", "scored against the sealed answer key")
            return self.view(case_id)

    # ------------------------------------------------------------------ reset / cancel
    def cancel(self, case_id: str) -> dict[str, Any]:
        rec = self._load(case_id)
        if rec.state == "investigating":
            self._cancel.setdefault(case_id, threading.Event()).set()
        return self.view(case_id)

    def reset(self, case_id: str) -> dict[str, Any]:
        paths = self._paths(case_id)
        if not paths.root.exists():
            return {"reset": True, "case_id": case_id, "existed": False}
        ev = self._cancel.get(case_id)
        if ev:
            ev.set()
        th = self._threads.pop(case_id, None)
        if th and th.is_alive():
            th.join(timeout=10)
        with self._lock(case_id):
            remove_episode(paths, self.runs_dir, self.sealed_dir)
            with self._guard:
                self._logs.pop(case_id, None)
                self._cancel.pop(case_id, None)
                for tok, cid in list(self._tokens.items()):
                    if cid == case_id:
                        self._tokens.pop(tok)
        return {"reset": True, "case_id": case_id, "existed": True}

    # ------------------------------------------------------------------ views
    def events(self, case_id: str, after: int = 0, view: str = "audience") -> list[dict[str, Any]]:
        self._load(case_id)
        return self._log(case_id).since(after, view)

    def record(self, case_id: str) -> CaseRecord:
        return self._load(case_id)

    def list_cases(self) -> list[dict[str, Any]]:
        out = []
        for status in sorted(self.runs_dir.glob("case-*/status.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                out.append(CaseRecord(**json.loads(status.read_text(encoding="utf-8"))).public())
            except Exception:
                continue
        return out[:50]

    def _report(self, paths: EpisodePaths) -> InvestigationReport | None:
        for name in ("report.json", "report.draft.json"):
            f = paths.case / name
            if f.exists():
                return InvestigationReport.model_validate_json(f.read_text(encoding="utf-8"))
        return None

    def view(self, case_id: str) -> dict[str, Any]:
        rec, paths = self._load(case_id), self._paths(case_id)
        manifest = load_manifest(paths)
        report = self._report(paths) if rec.state in ("awaiting_review", "report_locked", "scored") else None
        reveal = None
        if rec.state == "scored" and (paths.root / "reveal.json").exists():
            reveal = json.loads((paths.root / "reveal.json").read_text(encoding="utf-8"))
        return {
            "case": rec.public(),
            "card": {"id": rec.card_id, "title": CARDS[rec.card_id]["title"], "tip": CARDS[rec.card_id]["tip"],
                     "audience_setup": CARDS[rec.card_id]["audience_setup"]},
            "manifest": manifest.model_dump(mode="json"),
            "report": report.model_dump(mode="json") if report else None,
            "reveal": reveal,
            "last_seq": self._log(case_id).last_seq(),
            "runtime": self.settings.public_dict(),
        }

    def _store(self, case_id: str) -> tuple[EvidenceStore, EpisodePaths]:
        self._load(case_id)
        paths = self._paths(case_id)
        return EvidenceStore(paths.db), paths

    def evidence_events(self, case_id: str, ids: list[str]) -> list[dict[str, Any]]:
        store, _ = self._store(case_id)
        with store:
            return [evidence_views.event_public(e) for e in store.get(ids[:60])]

    def evidence_raw(self, case_id: str, artifact: str, line: int, radius: int = 6) -> dict[str, Any]:
        self._load(case_id)
        paths = self._paths(case_id)
        return evidence_views.raw_context(paths.raw, load_manifest(paths), artifact, line, radius)

    def evidence_compare(self, case_id: str, host: str, file: str, focus: str | None, radius: int = 5) -> dict[str, Any]:
        store, paths = self._store(case_id)
        with store:
            return evidence_views.compare_local_collector(store, load_manifest(paths), host, file, focus, radius)

    def evidence_timeline(self, case_id: str) -> dict[str, Any]:
        store, paths = self._store(case_id)
        rec = self._load(case_id)
        report = self._report(paths) if rec.state in ("awaiting_review", "report_locked", "scored") else None
        with store:
            return evidence_views.timeline(store, load_manifest(paths), report)

    def explanations(self, case_id: str) -> list[dict[str, Any]]:
        rec = self._load(case_id)
        if rec.state not in ("awaiting_review", "report_locked", "scored"):
            raise Conflict("explanations are available once a report has been drafted", rec.state)
        store, paths = self._store(case_id)
        with store:
            return explain.explanations(store, load_manifest(paths), self._report(paths))

    # ------------------------------------------------------------------ export
    def report_export(self, case_id: str) -> dict[str, Any]:
        """The locked report with its provenance, hashes and cited lines. Never contains sealed truth."""
        rec, paths = self._load(case_id), self._paths(case_id)
        final = paths.case / "report.json"
        if rec.state not in ("report_locked", "scored") or not final.exists():
            raise Conflict("the report can be exported once it has been reviewed and locked", rec.state)
        report = InvestigationReport.model_validate_json(final.read_text(encoding="utf-8"))
        with EvidenceStore(paths.db) as store:
            return export.build_manifest(rec.public(), load_manifest(paths), report, store)

    def reveal_export(self, case_id: str) -> dict[str, Any]:
        """The unsealed answer and score, exported only on this explicit request and only after the reveal."""
        rec, paths = self._load(case_id), self._paths(case_id)
        f = paths.root / "reveal.json"
        if rec.state != "scored" or not f.exists():
            raise Conflict("the answer can be exported only after the case has been unsealed", rec.state)
        return {"case_id": case_id, "note": "Unsealed answer and score. This is not part of the report export.",
                **json.loads(f.read_text(encoding="utf-8"))}

    # ------------------------------------------------------------------ source-removal experiment
    _PARENT_STATES = ("frozen", "awaiting_review", "report_locked", "scored")

    def create_source_experiment(self, case_id: str, excluded_source_ids: list[str], client_token: str, *,
                                 runner_id: str | None = None, investigation_mode: str | None = None) -> CaseRecord:
        """Derive a new case whose evidence is the original's with the named sources withheld.

        The original case is only read. The new case starts frozen with an empty case directory and is
        investigated, questioned, reviewed and revealed through the ordinary endpoints.
        """
        token = str(client_token or "").strip()
        if not token or len(token) > 80:
            raise ValueError("client_token is required (at most 80 characters); it makes a retried request safe")
        with self._guard:
            if token in self._tokens:
                try:
                    return self._load(self._tokens[token])  # a retry: the same derived case
                except NotFound:
                    self._tokens.pop(token, None)
        with self._lock(case_id):
            parent, ppaths = self._load(case_id), self._paths(case_id)
            if parent.parent_case_id:
                raise ValueError("this case is itself a derived evidence view; run the experiment from the original case")
            if parent.state not in self._PARENT_STATES:
                raise Conflict(f"the original case has no frozen evidence to derive from (state: {parent.state})",
                               parent.state)
            runner_id = runner_id or default_runner_id(self.settings)
            mode = resolve_mode(runner_id, investigation_mode)
            runner = get_runner(runner_id, self.settings, mode)
            t0 = time.perf_counter()
            child_id = f"case-{uuid.uuid4().hex[:12]}"
            cpaths = self._paths(child_id)
            try:
                manifest = source_experiment.create_child_bundle(ppaths, cpaths, excluded_source_ids)
            except Exception:
                remove_episode(cpaths, self.runs_dir, self.sealed_dir)  # never leave a half-built evidence view
                raise
            withheld = load_episode_manifest(cpaths).withheld_sources
            what = ", ".join(sorted({f"{w['host']} {w['source']}" for w in withheld}))
            rec = CaseRecord(case_id=child_id, preset_id=parent.preset_id, title=f"{parent.title} · without {what}",
                             card_id=parent.card_id, difficulty=parent.difficulty, seed=parent.seed, runner_id=runner_id,
                             investigation_mode=mode, evidence_origin=parent.evidence_origin,
                             inference_mode=runner.inference_mode, model_id=runner.model_id, bundle_id=manifest.bundle_id,
                             client_token=token, parent_case_id=case_id,
                             excluded_sources=[{k: v for k, v in w.items() if k != "sha256"} for w in withheld])
            rec.timings["derive_s"] = round(time.perf_counter() - t0, 3)
            self._save(rec)
            with self._guard:
                self._tokens[token] = child_id
            log = self._log(child_id)
            pm = load_manifest(ppaths)
            log.append("state", {"state": "generating", "detail": "deriving an evidence view with sources withheld"})
            log.append("stage", {"name": "derive", "status": "done", "info": {
                "parent_case_id": case_id, "parent_raw_bundle_sha256": pm.raw_bundle_sha256,
                "withheld": [w["source_id"] for w in withheld], "what": what}})
            log.append("stage", {"name": "freeze", "status": "done",
                                 "info": {"artifacts": len(manifest.sources), "raw_bundle_sha256": manifest.raw_bundle_sha256}})
            log.append("stage", {"name": "normalize", "status": "done",
                                 "info": {"events": manifest.event_count, "errors": len(manifest.normalization_errors),
                                          "derived_db_sha256": manifest.derived_db_sha256}})
            log.append("stage", {"name": "seal", "status": "done", "info": {
                "note": "what actually happened is unchanged and stays sealed; what is observable is recomputed for this view"}})
            self._set_state(rec, "frozen", "evidence view frozen and hashed; nothing is carried over from the original case")
            return rec

    def source_experiment(self, case_id: str) -> dict[str, Any]:
        """The parent/child relationship and what the original claims are worth without the withheld sources.

        Deterministic. Reads the two evidence bundles and the original report only: no model, no sealed file.
        """
        rec = self._load(case_id)
        if rec.parent_case_id is None:
            kids = [c for c in self.list_cases() if c.get("parent_case_id") == case_id]
            return {"role": "original", "case_id": case_id, "bundle_id": rec.bundle_id,
                    "children": [{"child_case_id": k["case_id"], "title": k["title"], "state": k["state"],
                                  "excluded_sources": k["excluded_sources"], "bundle_id": k["bundle_id"]} for k in kids],
                    "sources": [source_experiment.public_source(s) for s in load_manifest(self._paths(case_id)).sources]}
        cpaths = self._paths(case_id)
        cm = load_manifest(cpaths)
        out: dict[str, Any] = {"role": "derived", "case_id": case_id, "parent_case_id": rec.parent_case_id,
                               "child_state": rec.state, "excluded_sources": rec.excluded_sources}
        try:
            parent = self._load(rec.parent_case_id)
        except NotFound:
            out["comparison"] = None
            out["note"] = "The original case no longer exists (it was reset), so its claims cannot be compared."
            return out
        ppaths = self._paths(rec.parent_case_id)
        pm = load_manifest(ppaths)
        out.update(source_experiment.describe(pm, cm, rec.excluded_sources))
        out["parent_state"] = parent.state
        report = self._report(ppaths) if parent.state in ("awaiting_review", "report_locked", "scored") else None
        out["parent_report"] = None if report is None else {
            "report_id": report.report_id, "locked": report.locked, "report_sha256": report.report_sha256,
            "system_id": report.system_id, "inference_mode": report.inference_mode}
        with EvidenceStore(ppaths.db) as pstore, EvidenceStore(cpaths.db) as cstore:
            out["comparison"] = source_experiment.compare(report, pstore, pm, cstore, cm)
        return out

    def _child_scoring(self, rec: CaseRecord, paths: EpisodePaths, score: Any, key: Any) -> dict[str, Any]:
        """Research scoring for a derived view: all original effects, both denominators. Trusted, post-lock only."""
        try:
            ppaths = self._paths(rec.parent_case_id or "")
            pkey = load_answer_key(ppaths)
            with EvidenceStore(paths.db) as cstore, EvidenceStore(ppaths.db) as pstore:
                return {"parent_case_id": rec.parent_case_id, "excluded_sources": rec.excluded_sources,
                        "scoring": source_experiment.scoring_summary(score, key, pkey, cstore, pstore)}
        except Exception as exc:  # noqa: BLE001 - e.g. the original case was reset
            return {"parent_case_id": rec.parent_case_id, "excluded_sources": rec.excluded_sources, "scoring": None,
                    "note": f"the original case is no longer available for comparison ({type(exc).__name__})"}

    # ------------------------------------------------------------------ questions (never change the report)
    _QUESTION_STATES = ("frozen", "awaiting_review", "report_locked", "scored")

    def _qdir(self, case_id: str) -> Path:
        return self._paths(case_id).case / "questions"

    def _read_question(self, case_id: str, question_id: str) -> QuestionAnswer:
        if not questions_id_ok(question_id):
            raise NotFound("no such question")
        f = self._qdir(case_id) / f"{question_id}.json"
        if not f.exists():
            raise NotFound("no such question")
        return QuestionAnswer.model_validate_json(f.read_text(encoding="utf-8"))

    def _write_question(self, q: QuestionAnswer) -> None:
        qdir = self._qdir(q.case_id)
        qdir.mkdir(parents=True, exist_ok=True)
        tmp = qdir / f"{q.question_id}.json.tmp"
        tmp.write_text(q.model_dump_json(indent=1), encoding="utf-8")
        os.replace(tmp, qdir / f"{q.question_id}.json")

    def _question_index(self, case_id: str) -> dict[str, str]:
        f = self._qdir(case_id) / "index.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    def ask_question(self, case_id: str, question: str, client_token: str) -> QuestionAnswer:
        """Register one question and start answering it. The same client_token always returns the same question."""
        text = questions.clean_question(question)
        token = str(client_token or "").strip()
        if not token or len(token) > 80:
            raise ValueError("client_token is required (at most 80 characters); it makes a retried request safe")
        with self._lock(case_id):
            rec = self._load(case_id)
            index = self._question_index(case_id)
            if token in index:
                return self._read_question(case_id, index[token])  # a retry: no second model call, no second charge
            if rec.state not in self._QUESTION_STATES:
                raise Conflict("questions can be asked once the evidence is frozen and no investigation is running "
                               f"(state: {rec.state})", rec.state)
            if case_id in self._qa_active:
                raise Conflict("another question is being answered for this case; wait for it to finish", rec.state)
            if len(index) >= questions.MAX_QUESTIONS_PER_CASE:
                raise Conflict(f"this case already has {questions.MAX_QUESTIONS_PER_CASE} questions, the most allowed",
                               rec.state)
            live = self.settings.live_block_reason() is None or self.qa_model_factory is not None
            pending = QuestionAnswer(
                question_id=f"q-{uuid.uuid4().hex[:10]}", case_id=case_id, bundle_id=rec.bundle_id or "", question=text,
                status="pending", inference_mode="LIVE_MODEL" if live else "NO_MODEL_BASELINE",
                inference_label=INFERENCE_LABELS["LIVE_MODEL"] if live else "No model answer",
                model_id=self.settings.lead_model if live else None, asked_at=_now())
            self._write_question(pending)
            index[token] = pending.question_id
            (self._qdir(case_id) / "index.json").write_text(json.dumps(index), encoding="utf-8")
            if not live:  # nothing to wait for: say so now
                done = self._answer(case_id, pending)
                self._write_question(done)
                return done
            self._qa_active[case_id] = pending.question_id
            th = threading.Thread(target=self._question_thread, args=(case_id, pending), daemon=True,
                                  name=f"question-{pending.question_id}")
            self._qa_threads[case_id] = th
            th.start()
            return pending

    def _answer(self, case_id: str, pending: QuestionAnswer) -> QuestionAnswer:
        """Only investigator-visible material is opened here: the evidence store, the public manifest and the report.
        The sealed directory, the reveal and the audience event log are never read, before or after a reveal."""
        paths = self._paths(case_id)
        with EvidenceStore(paths.db) as store:
            return questions.answer_question(
                self.settings, pending, store, load_manifest(paths), self._report(paths),
                ledger_path=self._qdir(case_id) / f"{pending.question_id}.budget.json",
                model_factory=self.qa_model_factory)

    def _question_thread(self, case_id: str, pending: QuestionAnswer) -> None:
        try:
            try:
                done = self._answer(case_id, pending)
            except Exception as exc:  # noqa: BLE001 - a crashed answer is a visible failure
                done = pending.model_copy(update={"status": "failed", "answered_at": _now(),
                                                  "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
            try:
                self._write_question(done)
            except OSError:
                pass  # the case was reset while the question was running
        finally:
            self._qa_active.pop(case_id, None)

    def get_question(self, case_id: str, question_id: str) -> QuestionAnswer:
        self._load(case_id)
        return self._read_question(case_id, question_id)

    def list_questions(self, case_id: str) -> list[QuestionAnswer]:
        self._load(case_id)
        out = []
        for f in self._qdir(case_id).glob("q-*.json"):
            try:
                out.append(QuestionAnswer.model_validate_json(f.read_text(encoding="utf-8")))
            except Exception:
                continue
        return sorted(out, key=lambda q: q.asked_at)

    # ------------------------------------------------------------------ recordings / replay
    def save_recording(self, case_id: str, name: str, note: str = "") -> Path:
        """Save a finished investigation so it can be replayed offline. Trusted operator action."""
        validate_episode_id(name)
        rec, paths = self._load(case_id), self._paths(case_id)
        if rec.state not in ("awaiting_review", "report_locked", "scored"):
            raise Conflict("only a case with a drafted report can be recorded", rec.state)
        ep = load_episode_manifest(paths)
        draft = InvestigationReport.model_validate_json((paths.case / "report.draft.json").read_text(encoding="utf-8"))
        events = [e for e in self._log(case_id).since(0, "investigator")
                  if not (e["type"] == "finding" and e["data"].get("phase") == "verified")
                  and e["type"] not in ("attribution", "usage", "report")]
        out = REPLAY_DIR / name / "recording.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "meta": {"title": rec.title, "preset_id": rec.preset_id, "difficulty": rec.difficulty,
                     "inference_mode": rec.inference_mode, "model_id": rec.model_id, "runner_id": rec.runner_id,
                     "investigation_mode": rec.investigation_mode,
                     "recorded_at": _iso_now(), "git_commit": ep.git_commit, "note": note,
                     "simulator_version": ep.simulator_version, "raw_bundle_sha256": ep.raw_bundle_sha256},
            "spec": ep.scenario_spec,
            "events": events,
            "report": draft.model_dump(mode="json"),
            # model answers given on this case; a replay shows them again as recorded answers, never as live ones
            "questions": [q.model_dump(mode="json") for q in self.list_questions(case_id)
                          if q.status in ("answered", "insufficient_evidence")],
        }, indent=1), encoding="utf-8")
        return out

    def open_replay(self, replay_id: str, client_token: str | None = None) -> CaseRecord:
        validate_episode_id(replay_id)
        f = REPLAY_DIR / replay_id / "recording.json"
        if not f.exists():
            raise NotFound("no such recording")
        with self._guard:
            if client_token and client_token in self._tokens:
                try:
                    return self._load(self._tokens[client_token])
                except NotFound:
                    self._tokens.pop(client_token, None)
        data = json.loads(f.read_text(encoding="utf-8"))
        meta = data["meta"]
        rec = CaseRecord(case_id=f"case-{uuid.uuid4().hex[:12]}", preset_id=meta.get("preset_id"),
                         title=meta.get("title", replay_id), difficulty=meta.get("difficulty", ""),
                         card_id=str(data["spec"].get("card_id") or "inside-job"),
                         seed=data["spec"].get("seed"), runner_id=meta.get("runner_id", "deterministic"),
                         investigation_mode=_recorded_mode(meta),
                         inference_mode=("RECORDED_MODEL" if meta["inference_mode"] == "LIVE_MODEL" else meta["inference_mode"]),
                         playback="REPLAY", model_id=meta.get("model_id"), replay_of=replay_id,
                         recorded_at=meta.get("recorded_at"), client_token=client_token)
        rec = self._generate(rec, seed=None, variant=None, spec=data["spec"])
        got = load_manifest(self._paths(rec.case_id)).raw_bundle_sha256
        if got != meta.get("raw_bundle_sha256"):
            rec.error = "the recording's evidence could not be reproduced byte-for-byte (simulator version changed?)"
            self._set_state(rec, "failed", rec.error)
            return rec
        for saved in data.get("questions") or []:
            try:
                q = QuestionAnswer.model_validate(saved)
            except Exception:
                continue
            recorded = q.inference_mode == "LIVE_MODEL"
            self._write_question(q.model_copy(update={
                "case_id": rec.case_id, "bundle_id": rec.bundle_id or q.bundle_id,
                "inference_mode": "RECORDED_MODEL" if recorded else q.inference_mode,
                "inference_label": "Recorded AI answer" if recorded else q.inference_label}))
        return rec

    def _replay_thread(self, case_id: str) -> None:
        try:
            rec, paths = self._load(case_id), self._paths(case_id)
            data = json.loads((REPLAY_DIR / (rec.replay_of or "") / "recording.json").read_text(encoding="utf-8"))
            log = self._log(case_id)
            cancel = self._cancel.setdefault(case_id, threading.Event())
            log.append("stage", {"name": "investigate", "status": "started",
                                 "info": {"runner": "replay", "inference": rec.inference_mode,
                                          "note": "replaying a saved transcript; no inference is running"}})
            for ev in data["events"]:
                if cancel.is_set():
                    raise Cancelled()
                log.append(ev["type"], ev["data"])
                if self.pace_s:
                    time.sleep(self.pace_s * (0.6 if ev["type"] == "finding" else 1.0))
            report = InvestigationReport.model_validate(data["report"])
            if report.inference_mode == "LIVE_MODEL":
                report.inference_mode = "RECORDED_MODEL"  # a replay of a real run is never presented as live
            report.report_id = f"rep-{case_id}"
            report.bundle_id = load_manifest(paths).bundle_id
            with EvidenceStore(paths.db) as store, self._lock(case_id):
                self._finish_draft(self._load(case_id), paths, store, report, report.usage.wall_seconds or 0.0)
        except BaseException as exc:  # noqa: BLE001
            self._fail(case_id, exc)
