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

from alibi import explain, evidence_views
from alibi.config import REPO_ROOT, Settings
from alibi.contracts import INFERENCE_LABELS, InvestigationReport
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
from alibi.runners import Cancelled, RunContext, RuntimeBlocked, default_runner_id, get_runner
from alibi.scoring import score_report
from alibi.sim.scenario import CARDS, build_spec
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
    {"id": "model-planned", "title": "Inside job · model-planned adversary", "difficulty": "L2", "card_id": "inside-job",
     "seed": 9027,
     "blurb": "A model chooses the adversary's steps from the bounded library (one planning response). "
              "Needs a live model runtime.",
     "_variant": "incident_coverup", "_planner": "model"},
]
_CUSTOM_VARIANT = {"L1": "incident_plain", "L2": "incident_coverup"}


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

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("client_token", None)
        d["labels"] = {
            "evidence_origin": self.evidence_origin,
            "inference": self.inference_mode,
            "inference_label": INFERENCE_LABELS.get(self.inference_mode, self.inference_mode),
            "playback": self.playback,
            "model_id": self.model_id,
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

    # ------------------------------------------------------------------ presets / replays
    def presets(self) -> list[dict[str, Any]]:
        """Only presets that can actually run are offered (a model-planned case needs a live runtime)."""
        return [{k: v for k, v in p.items() if not k.startswith("_")} for p in PRESETS
                if p.get("_planner") != "model" or self._model_planner_enabled()]

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
            out.append({"id": f.parent.name, **{k: meta.get(k) for k in (
                "title", "model_id", "recorded_at", "runner_id", "git_commit", "note")},
                "inference_mode": mode, "inference_label": INFERENCE_LABELS.get(mode, "")})
        return out

    # ------------------------------------------------------------------ create
    def create_case(self, *, preset_id: str | None = None, seed: int | None = None, difficulty: str | None = None,
                    runner_id: str | None = None, client_token: str | None = None) -> CaseRecord:
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
        runner = get_runner(runner_id, self.settings)
        case_id = f"case-{uuid.uuid4().hex[:12]}"
        rec = CaseRecord(case_id=case_id, preset_id=preset_id, title=title, difficulty=diff, seed=seed,
                         runner_id=runner_id, inference_mode=runner.inference_mode, model_id=runner.model_id,
                         client_token=client_token)
        spec = None
        if preset_id is not None and preset.get("_planner") == "model":
            t0 = time.perf_counter()
            spec = self._plan_with_model(build_spec(seed, variant))
            rec.timings["adversary_plan_s"] = round(time.perf_counter() - t0, 3)
        return self._generate(rec, seed=seed, variant=variant, spec=spec)

    def create_case_from_spec(self, spec: dict[str, Any], *, title: str = "Custom scenario",
                              runner_id: str | None = None) -> CaseRecord:
        """Operator/test entry point: run a saved scenario specification. Not exposed over HTTP."""
        runner_id = runner_id or default_runner_id(self.settings)
        runner = get_runner(runner_id, self.settings)
        rec = CaseRecord(case_id=f"case-{uuid.uuid4().hex[:12]}", title=title, difficulty=str(spec.get("difficulty", "")),
                         seed=spec.get("seed"), runner_id=runner_id, inference_mode=runner.inference_mode,
                         model_id=runner.model_id)
        return self._generate(rec, seed=None, variant=None, spec=spec)

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
            runner = get_runner(rec.runner_id, self.settings)
            with EvidenceStore(paths.db) as store:
                ctx = self._context(rec, paths, store)
                self._log(case_id).append("stage", {"name": "investigate", "status": "started",
                                                    "info": {"runner": rec.runner_id, "inference": rec.inference_mode}})
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
                with EvidenceStore(paths.db) as store:
                    get_runner(rec.runner_id, self.settings).resume(self._context(rec, paths, store), decision)
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
                "steps": [s.model_dump(mode="json") for s in key.steps],
                "effects": [e.model_dump(mode="json", exclude={"evidence"}) for e in key.effects],
                "benign_outcomes": [b.model_dump(mode="json") for b in key.benign_outcomes],
                "attribution": key.attribution.model_dump(mode="json"),
            }
            payload = {"score": score.model_dump(mode="json"), "truth": truth}
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
                     "recorded_at": _iso_now(), "git_commit": ep.git_commit, "note": note,
                     "simulator_version": ep.simulator_version, "raw_bundle_sha256": ep.raw_bundle_sha256},
            "spec": ep.scenario_spec,
            "events": events,
            "report": draft.model_dump(mode="json"),
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
                         seed=data["spec"].get("seed"), runner_id=meta.get("runner_id", "deterministic"),
                         inference_mode=("RECORDED_MODEL" if meta["inference_mode"] == "LIVE_MODEL" else meta["inference_mode"]),
                         playback="REPLAY", model_id=meta.get("model_id"), replay_of=replay_id,
                         recorded_at=meta.get("recorded_at"), client_token=client_token)
        rec = self._generate(rec, seed=None, variant=None, spec=data["spec"])
        got = load_manifest(self._paths(rec.case_id)).raw_bundle_sha256
        if got != meta.get("raw_bundle_sha256"):
            rec.error = "the recording's evidence could not be reproduced byte-for-byte (simulator version changed?)"
            self._set_state(rec, "failed", rec.error)
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
