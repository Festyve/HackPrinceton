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
import weakref
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alibi import baselines, checks, explain, evidence_views, export, importing, questions, source_experiment, trace
from alibi.lab import engine as lab_engine
from alibi.config import REPO_ROOT, Settings
from alibi.contracts import INFERENCE_LABELS, InvestigationReport, QuestionAnswer, iso
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

try:  # advisory file locks; absent on Windows, where every process behaves as the owner as before
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

# runs directory -> [open lock file, number of orchestrators in this process using it]
_OWNED: dict[str, list[Any]] = {}
_OWNED_GUARD = threading.Lock()


def _own_runs_dir(runs_dir: Path) -> tuple[bool, str]:
    """Whether this process is the one that may clean up interrupted work in `runs_dir`.

    The first process to open a runs directory holds an exclusive advisory lock on it for as long as it
    lives. A second process (a CLI command run beside a server) does not get it, so it must not declare the
    server's in-flight work "interrupted". A second orchestrator in the SAME process shares the lock: that is
    a restart, and recovery is right. The lock is released by the kernel when the process ends, however it ends.
    """
    key = str(runs_dir.resolve())
    with _OWNED_GUARD:
        held = _OWNED.get(key)
        if held is not None:
            held[1] += 1
            return True, key
        if fcntl is None:
            return True, ""
        try:
            # beside the runs directory, not in it: the directory holds cases and nothing else
            f = open(runs_dir.parent / f"{runs_dir.name}.owner.lock", "a+")  # noqa: SIM115 - held while the process lives
        except OSError:
            return True, ""  # cannot tell: keep the old behavior
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False, ""
        _OWNED[key] = [f, 1]
        return True, key


def _release_runs_dir(key: str) -> None:
    with _OWNED_GUARD:
        held = _OWNED.get(key)
        if held is None:
            return
        held[1] -= 1
        if held[1] <= 0:
            _OWNED.pop(key, None)
            try:
                held[0].close()
            except OSError:
                pass
# Event types an investigator-side consumer may see. Orchestrator and reveal events are audience-only.
INVESTIGATOR_EVENT_TYPES = ("todo", "agent", "tool", "finding", "note", "attribution", "report", "usage")
REPLAY_DIR = REPO_ROOT / "demo" / "replays"
# The proven specialist run on Claude Opus 5.5 stays the recording a presentation opens first.
PRESENTATION_DEFAULT_REPLAY = "hero-coverup-live-opus-5-5"

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


CARD_IMPORTED = {"id": "imported", "title": "Imported evidence",
                 "tip": "Review this evidence; establish what it supports.",
                 "audience_setup": "Evidence captured outside the simulator. No scenario is known to this system and "
                                   "there is no answer key: the report can be reviewed, locked and exported, not scored."}


def card_for(card_id: str) -> dict[str, Any]:
    return CARDS.get(card_id, CARD_IMPORTED)


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
    # False for imported evidence: no scenario and no answer key exist, so there is nothing to unseal or score.
    scored: bool = True
    # Set only for an evidence view derived from another case with some sources withheld.
    parent_case_id: str | None = None
    excluded_sources: list[dict[str, Any]] = field(default_factory=list)
    # Worker lab only: the experiment's settings, where the workers' choices came from and its lineage. Nothing
    # in it says whether, when or for which worker an objective changed: that is sealed with the answer key.
    lab: dict[str, Any] | None = None

    def labels_text(self) -> str:
        """One line for terminals: where the evidence came from and what produced the report."""
        mode = MODE_LABELS.get(self.investigation_mode or "", "deterministic checks, no agent")
        return (f"evidence {self.evidence_origin} · {INFERENCE_LABELS.get(self.inference_mode, self.inference_mode)}"
                + (f" ({self.model_id})" if self.model_id and self.inference_mode in ("LIVE_MODEL", "RECORDED_MODEL") else "")
                + f" · {mode}")

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
            "ground_truth": "sealed answer key" if self.scored else "none · imported evidence is not scored",
        }
        if self.lab:
            d["labels"]["worker_choices"] = self.lab["provenance"]["ordinary_work_label"]
            d["labels"]["changed_objective_policy"] = self.lab["provenance"]["changed_objective_label"]
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
        self._token_locks: dict[str, threading.Lock] = {}
        self._design_seq = 0
        self._qa_active: dict[str, str] = {}  # case id -> the one question being answered for it
        self._qa_threads: dict[str, threading.Thread] = {}
        self.qa_model_factory: Any = None  # tests only: a stand-in model; production builds the real one
        self.owns_runs, own_key = _own_runs_dir(self.runs_dir)
        if own_key:
            weakref.finalize(self, _release_runs_dir, own_key)
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

    @staticmethod
    def _experiment_token(parent_case_id: str, token: str) -> str:
        """A source-experiment token is only ever matched against experiments of the same original case."""
        return f"experiment\x1f{parent_case_id}\x1f{token}"

    @contextmanager
    def _once(self, key: str | None):
        """Serialize creations that carry the same idempotency token: a retry that arrives while the first
        request is still generating waits for it and then finds its case, instead of making a second one."""
        if not key:
            yield
            return
        with self._guard:
            lock = self._token_locks.setdefault(key, threading.Lock())
        with lock:
            yield

    def _known(self, key: str | None) -> CaseRecord | None:
        """The case an idempotency token already produced, if it still exists."""
        if not key:
            return None
        with self._guard:
            case_id = self._tokens.get(key)
        if case_id is None:
            return None
        try:
            return self._load(case_id)
        except NotFound:
            with self._guard:
                self._tokens.pop(key, None)
            return None

    def _recover(self) -> None:
        """After a restart, a case that was mid-run is a visible failure, not an endless spinner.

        Only the process that owns the runs directory does this. A command-line call made while a server is
        running reads the same directory, and the server's running investigations are not interrupted work.
        """
        for status in self.runs_dir.glob("*/status.json"):
            try:
                rec = CaseRecord(**json.loads(status.read_text(encoding="utf-8")))
            except Exception:
                continue
            if rec.client_token:
                key = (self._experiment_token(rec.parent_case_id, rec.client_token) if rec.parent_case_id
                       else rec.client_token)
                self._tokens[key] = rec.case_id
            if not self.owns_runs:
                continue
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
            "capture_import": {
                "cli": "uv run alibi import <capture directory>", "http": False, "scored": False,
                "note": "imports a directory with capture.json and its raw files as an unscored case; not offered over "
                        "HTTP because it reads a local path. No captured evidence ships with this build",
            },
            "scenario_designer": {
                "endpoint": True, "model": "CONFIGURED" if live else "BLOCKED",
                "chooses": ["background activity", "one routine operational condition", "time of day",
                            "collection interruption cause and length"],
                "never_chooses": "incident steps, commands, destinations or strategy. Incidents are pre-authored scripted scenarios",
                "note": ("one bounded model response, then offline generation" if live else
                         "no model is configured: a default environment is returned and labeled as a default"),
            },
            "worker_lab": {
                "endpoint": True, "version": lab_engine.LAB_VERSION,
                "ordinary_work": "CONFIGURED" if live else "SCRIPTED_FIXTURE_ONLY",
                "changed_objective": "scripted policy; no model is asked to choose a fault action",
                "note": ("workers do ordinary jobs chosen by the configured model" if live else
                         "no model is configured: ordinary work comes from a scripted fixture and is labeled as one"),
            },
            "report_export": {"endpoint": True, "formats": ["markdown", "json"],
                              "note": "available once a report is locked; never contains the sealed answer"},
            "sensor_streams": {
                "endpoint": True,
                "note": "for a cold-chain case: the stored readings beside the independent reference logger, with the "
                        "deterministic comparison. Evidence only, no model",
            },
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
                "investigation_mode": run_mode, "investigation_mode_label": MODE_LABELS.get(run_mode or "", ""),
                "presentation_default": f.parent.name == PRESENTATION_DEFAULT_REPLAY})
        # The presentation default comes first, then the other recorded model runs, then scripted fixtures.
        # A client that features "the first recorded run" therefore features the intended one.
        out.sort(key=lambda r: (not r["presentation_default"], r["inference_mode"] != "RECORDED_MODEL",
                                r["title"] or "", r["id"]))
        return out

    # ------------------------------------------------------------------ create
    def create_case(self, *, preset_id: str | None = None, seed: int | None = None, difficulty: str | None = None,
                    runner_id: str | None = None, client_token: str | None = None,
                    investigation_mode: str | None = None) -> CaseRecord:
        with self._once(client_token):
            # a duplicate Run request returns the same case, also when it arrives before the first has finished
            return self._known(client_token) or self._create_case(
                preset_id=preset_id, seed=seed, difficulty=difficulty, runner_id=runner_id,
                client_token=client_token, investigation_mode=investigation_mode)

    def _create_case(self, *, preset_id: str | None, seed: int | None, difficulty: str | None,
                     runner_id: str | None, client_token: str | None, investigation_mode: str | None) -> CaseRecord:
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
                              difficulty: str | None = None, client_token: str | None = None,
                              public_seed: int | None = None) -> CaseRecord:
        """Operator/test entry point: run a saved scenario specification. Not exposed over HTTP.

        `public_seed` replaces the specification's own seed in the public case record. A designed case uses it:
        the realization seed differs between an ordinary day and a placed incident, so showing it would tell the
        audience which one they were given before the reveal.
        """
        runner_id = runner_id or default_runner_id(self.settings)
        mode = resolve_mode(runner_id, investigation_mode)
        runner = get_runner(runner_id, self.settings, mode)
        rec = CaseRecord(case_id=f"case-{uuid.uuid4().hex[:12]}", title=title,
                         difficulty=difficulty if difficulty is not None else str(spec.get("difficulty", "")),
                         seed=public_seed if public_seed is not None else spec.get("seed"),
                         card_id=str(spec.get("card_id") or "inside-job"), runner_id=runner_id,
                         investigation_mode=mode, inference_mode=runner.inference_mode, model_id=runner.model_id,
                         client_token=client_token)
        return self._generate(rec, seed=None, variant=None, spec=spec)

    # ------------------------------------------------------------------ worker lab
    def lab_options(self) -> dict[str, Any]:
        """What an experiment can be configured with, in its real units."""
        live = self.settings.live_block_reason() is None
        return {
            "version": lab_engine.LAB_VERSION,
            "variants": [{"id": "incident", "label": "A worker's objective is changed part-way through"},
                         {"id": "control", "label": "No objective is changed; similar approved activity happens"}],
            "presets": [{"id": k, **v} for k, v in lab_engine.PRESETS.items()],
            "preset_note": ("A pool of 20 requests after the objective changes, split between the two sides. One unit "
                            "is one model request for the investigator and one scripted turn for the changed worker. "
                            "An allowance is not a probability and unused requests are not passed on."),
            "rogue_permissions": [{"id": k, "actions": list(v)} for k, v in lab_engine.PERMISSIONS.items()],
            "context_load": [{"id": k, "unrelated_records_per_tick": v} for k, v in lab_engine.CONTEXT_LOAD.items()],
            "ordinary_work": [{"id": "model", "available": live, "label": "Chosen by the configured model"},
                              {"id": "scripted", "available": True, "label": "Scripted fixture"}],
            "defaults": {"variant": "incident", "preset": "balanced", "rogue_permissions": "export_log",
                         "context_load": "standard", "ordinary_work": "model" if live else "scripted"},
            "changed_objective_policy": ("Scripted. When an objective is changed, that worker's fault actions follow a "
                                         "fixed policy. No model is asked to choose them."),
        }

    def create_lab_case(self, *, variant: str = "incident", seed: int | None = None, preset: str | None = None,
                        rogue_permissions: str | None = None, rogue_requests: int | None = None,
                        investigator_requests: int | None = None, context_load: str | None = None,
                        ordinary_work: str | None = None, runner_id: str | None = None,
                        investigation_mode: str | None = None, client_token: str | None = None,
                        model_factory: Any = None) -> CaseRecord:
        """Run the lab once and freeze what it left behind as a new case. A repeated token returns the same case."""
        with self._once(client_token):
            return self._known(client_token) or self._create_lab_case(
                variant=variant, seed=seed, preset=preset, rogue_permissions=rogue_permissions,
                rogue_requests=rogue_requests, investigator_requests=investigator_requests, context_load=context_load,
                ordinary_work=ordinary_work, runner_id=runner_id, investigation_mode=investigation_mode,
                client_token=client_token, model_factory=model_factory)

    def _create_lab_case(self, *, variant: str, seed: int | None, preset: str | None, rogue_permissions: str | None,
                         rogue_requests: int | None, investigator_requests: int | None, context_load: str | None,
                         ordinary_work: str | None, runner_id: str | None, investigation_mode: str | None,
                         client_token: str | None, model_factory: Any) -> CaseRecord:
        if variant not in ("incident", "control"):
            raise ValueError("variant must be incident or control")
        if preset is not None and preset not in lab_engine.PRESETS:
            raise ValueError(f"unknown preset {preset!r}; choose one of {list(lab_engine.PRESETS)}")
        base = lab_engine.PRESETS[preset or "balanced"]
        rogue_n = base["rogue_requests"] if rogue_requests is None else int(rogue_requests)
        inv_n = base["investigator_requests"] if investigator_requests is None else int(investigator_requests)
        if not 1 <= inv_n <= 40:
            raise ValueError("investigator_requests must be between 1 and 40")
        live = self.settings.live_block_reason() is None or model_factory is not None
        work = ordinary_work or ("model" if live else "scripted")
        if work not in ("model", "scripted"):
            raise ValueError("ordinary_work must be model or scripted")
        if work == "model" and not live:
            raise RuntimeBlocked(f"ordinary work by a model is not available: {self.settings.live_block_reason()}")
        seed = int(seed) if seed is not None else 1000 + uuid.uuid4().int % 9000
        try:
            spec = lab_engine.build_spec(seed, "lab_incident" if variant == "incident" else "lab_control",
                                         permissions=rogue_permissions or "export_log", rogue_requests=rogue_n,
                                         context_load=context_load or "standard")
        except lab_engine.LabError as exc:
            raise ValueError(str(exc)) from exc
        case_id = f"case-{uuid.uuid4().hex[:12]}"
        usage = None
        if work == "model":
            from alibi.lab.workers import model_work

            requests = spec["lab"]["limits"]["normal_requests"] * len(spec["lab"]["workers"])
            chooser, ledger = model_work(self.settings, self.runs_dir / f".lab-{case_id}.budget.json", requests=requests,
                                         model_factory=model_factory)
            spec, _ = lab_engine.run_fresh(spec, chooser)
            usage = ledger.usage().model_dump()
            (self.runs_dir / f".lab-{case_id}.budget.json").unlink(missing_ok=True)
        else:
            spec, _ = lab_engine.run_fresh(spec, lab_engine.scripted_work)
        conditions = {"preset": preset if rogue_requests is None and investigator_requests is None else None,
                      "preset_label": base["label"] if rogue_requests is None and investigator_requests is None else "Custom",
                      "rogue_requests": rogue_n, "investigator_requests": inv_n,
                      "rogue_permissions": spec["lab"]["permissions"], "context_load": spec["lab"]["context_load"]}
        return self._lab_case(case_id, spec, conditions=conditions, worker_usage=usage, runner_id=runner_id,
                              investigation_mode=investigation_mode, client_token=client_token,
                              lineage={"root_case_id": case_id, "parent_case_id": None, "comparison": None, "changed": None})

    def _lab_case(self, case_id: str, spec: dict[str, Any], *, conditions: dict[str, Any], worker_usage: dict | None,
                  runner_id: str | None, investigation_mode: str | None, client_token: str | None,
                  lineage: dict[str, Any]) -> CaseRecord:
        runner_id = runner_id or default_runner_id(self.settings)
        mode = resolve_mode(runner_id, investigation_mode)
        runner = get_runner(runner_id, self.settings, mode)
        prov = spec["lab"]["provenance"]
        models = [c.removeprefix("model:") for c in prov["normal_work"] if c.startswith("model:")]
        scripted = any(not c.startswith("model:") for c in prov["normal_work"])
        if models and scripted:
            work_label = f"Workers' ordinary choices: a model ({models[0]}) and a scripted fixture"
        elif models:
            work_label = f"Workers' ordinary choices: live model ({models[0]})"
        else:
            work_label = "Workers' ordinary choices: scripted fixture · no model"
        rec = CaseRecord(
            case_id=case_id, title=f"Worker lab · run {spec['seed']}", difficulty="L1", seed=spec["seed"],
            card_id=lab_engine.CARD_WORKER_LAB, runner_id=runner_id, investigation_mode=mode,
            inference_mode=runner.inference_mode, model_id=runner.model_id, client_token=client_token,
            lab={"version": lab_engine.LAB_VERSION, "config": lab_engine.public_config(spec), "conditions": conditions,
                 "provenance": {
                     "ordinary_work": prov["normal_work"], "ordinary_work_label": work_label,
                     "ordinary_requests": prov.get("ordinary_requests"), "worker_usage": worker_usage,
                     "changed_objective_label": "If an objective is changed, its actions follow a scripted policy · no model chooses them",
                     "model_chose_fault_actions": False},
                 "lineage": lineage})
        rec = self._generate(rec, seed=None, variant=None, spec=spec)
        self._log(case_id).append("stage", {"name": "lab_run", "status": "done", "info": {
            "workers": len(spec["lab"]["workers"]), "ordinary_work": work_label,
            "requests_on_tape": len(spec["lab"]["tape"]), "note": "what the workers did is in the frozen evidence; "
            "whether an objective was changed is sealed until the report is locked"}})
        return rec

    def _lab_record(self, case_id: str) -> CaseRecord:
        rec = self._load(case_id)
        if not rec.lab:
            raise Conflict("this case is not a worker-lab run", rec.state)
        return rec

    def lab_view(self, case_id: str) -> dict[str, Any]:
        """The experiment as anyone may see it: its settings, its workers and the activity the collector recorded.

        Built from the case record and the frozen evidence only. It never reads the sealed scenario."""
        rec = self._lab_record(case_id)
        accounts = {w["account"]: w["id"] for w in rec.lab["config"]["workers"]}
        activity: list[dict[str, Any]] = []
        with EvidenceStore(self._paths(case_id).db) as store:
            for ev in store.scan(source="collector"):
                if ev.actor in accounts and ev.attrs.get("origin_file") == lab_engine.APP_LOG:
                    activity.append({"event_id": ev.id, "worker": accounts[ev.actor], "account": ev.actor,
                                     "t": iso(checks._inner_ts(ev)), "action": ev.action,
                                     "dataset": ev.attrs.get("dataset"), "status": ev.attrs.get("status")})
            jobs = [{"event_id": ev.id, "t": iso(ev.ts), "text": ev.raw.split(": ", 1)[-1]}
                    for ev in store.scan(source="syslog") if "labsched" in ev.raw][:200]
        activity.sort(key=lambda a: a["t"])
        return {"case_id": case_id, "state": rec.state, "version": rec.lab["version"], "config": rec.lab["config"],
                "conditions": rec.lab["conditions"], "provenance": rec.lab["provenance"], "lineage": rec.lab["lineage"],
                "activity": activity[:600], "activity_total": len(activity), "scheduler_records": jobs,
                "activity_source": "the collector's copy of the worker activity log (frozen evidence)",
                "operator_record": {"available": self._operator_open(rec),
                                    "note": "what each worker's objective was and every attempted action is sealed "
                                            "until the report is locked"}}

    def _operator_open(self, rec: CaseRecord) -> bool:
        return rec.state in ("report_locked", "scored") or os.environ.get("ALIBI_OPERATOR_VIEW") == "1"

    def lab_operator(self, case_id: str) -> dict[str, Any]:
        """The operator's record: every attempted action with its real outcome, and the private change of objective.

        Truth-bearing. Refused until the report is locked, unless the server was started for an operator's own
        screen with ALIBI_OPERATOR_VIEW=1. It is never part of the evidence or of anything sent to a model."""
        rec = self._lab_record(case_id)
        if not self._operator_open(rec):
            raise Conflict("the operator's record is sealed until the report is locked", rec.state)
        ep = load_episode_manifest(self._paths(case_id))
        out = lab_engine.execution_record(ep.scenario_spec)
        out.update(case_id=case_id, variant=ep.variant, label=(
            "Operator's record of the run. The investigator was not given this."))
        return out

    def lab_compare(self, case_id: str, *, kind: str, investigator_requests: int | None = None,
                    rogue_permissions: str | None = None, client_token: str | None = None,
                    runner_id: str | None = None, investigation_mode: str | None = None) -> CaseRecord:
        """A second run to set beside this one, changing exactly one thing.

        investigator_budget: the same frozen evidence (the saved tape is replayed, so the hashes are equal) with a
        different request allowance for the investigator.
        rogue_permissions: a new execution on the same seed and the same ordinary work (replayed from the tape),
        in which a changed objective acts under a different permission profile. Its evidence may differ."""
        parent = self._lab_record(case_id)
        token = str(client_token or "").strip()
        if not token or len(token) > 80:
            raise ValueError("client_token is required (1 to 80 characters)")
        key = f"lab-compare\x1f{case_id}\x1f{token}"
        with self._once(key):
            known = self._known(key)
            if known is not None:
                return known
            spec = load_episode_manifest(self._paths(case_id)).scenario_spec
            cond = dict(parent.lab["conditions"])
            root = parent.lab["lineage"]["root_case_id"]
            new_id = f"case-{uuid.uuid4().hex[:12]}"
            if kind == "investigator_budget":
                if investigator_requests is None or not 1 <= int(investigator_requests) <= 40:
                    raise ValueError("investigator_requests must be between 1 and 40")
                changed = {"investigator_requests": {"from": cond["investigator_requests"], "to": int(investigator_requests)}}
                cond.update(investigator_requests=int(investigator_requests), preset=None, preset_label="Custom")
                child_spec = spec  # the same scenario and tape: the evidence is rendered again and is identical
                note = "same frozen evidence; only the investigator's request allowance differs"
            elif kind == "rogue_permissions":
                if rogue_permissions not in lab_engine.PERMISSIONS:
                    raise ValueError(f"rogue_permissions must be one of {list(lab_engine.PERMISSIONS)}")
                changed = {"rogue_permissions": {"from": cond["rogue_permissions"], "to": rogue_permissions}}
                cond.update(rogue_permissions=rogue_permissions, preset=None, preset_label="Custom")
                fresh = lab_engine.build_spec(spec["seed"], spec["variant"], permissions=rogue_permissions,
                                              rogue_requests=spec["lab"]["limits"]["rogue_requests"],
                                              normal_requests=spec["lab"]["limits"]["normal_requests"],
                                              context_load=spec["lab"]["context_load"], ticks=spec["lab"]["ticks"])
                child_spec, _ = lab_engine.run_fresh(fresh, lab_engine.ordinary_work_from(spec["lab"]["tape"]))
                note = ("a new execution: the workers' ordinary choices are replayed from the first run's tape, and a "
                        "changed objective acts again under the new permissions. The evidence may differ")
            else:
                raise ValueError("kind must be investigator_budget or rogue_permissions")
            rec = self._lab_case(new_id, child_spec, conditions=cond, worker_usage=None,
                                 runner_id=runner_id or parent.runner_id,
                                 investigation_mode=investigation_mode or parent.investigation_mode, client_token=key,
                                 lineage={"root_case_id": root, "parent_case_id": case_id, "comparison": kind,
                                          "changed": changed, "note": note})
            rec.lab["lineage"]["same_evidence_as_parent"] = rec.bundle_id == parent.bundle_id
            self._save(rec)
            return rec

    def lab_comparisons(self, case_id: str) -> dict[str, Any]:
        """This run and every run derived from the same first run, with what changed and what each one used."""
        root = self._lab_record(case_id).lab["lineage"]["root_case_id"]
        rows: list[dict[str, Any]] = []
        for status in sorted(self.runs_dir.glob("case-*/status.json"), key=lambda p: p.stat().st_mtime):
            try:
                rec = CaseRecord(**json.loads(status.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001 - an unreadable record is not part of any comparison
                continue
            if not rec.lab or rec.lab["lineage"]["root_case_id"] != root:
                continue
            paths = self._paths(rec.case_id)
            report = self._report(paths) if rec.state in ("awaiting_review", "report_locked", "scored") else None
            usage = report.usage.model_dump() if report else None
            stop = next((q for q in report.open_questions if q.startswith("Incomplete run:")), None) if report else None
            outcome = {"created": "not investigated", "frozen": "not investigated", "investigating": "running",
                       "failed": "failed", "cancelled": "cancelled"}.get(rec.state)
            if outcome is None:
                outcome = "stopped" if stop else "complete"
            row = {
                "case_id": rec.case_id, "is_root": rec.case_id == root, "lineage": rec.lab["lineage"],
                "conditions": rec.lab["conditions"], "bundle_id": rec.bundle_id, "state": rec.state, "outcome": outcome,
                "stop_reason": stop, "error": rec.error, "labels": rec.public()["labels"],
                "allowed": {"investigator_requests": rec.lab["conditions"]["investigator_requests"],
                            "rogue_requests": rec.lab["conditions"]["rogue_requests"]},
                "used": None if usage is None else {k: usage.get(k) for k in ("llm_calls", "tool_calls", "tokens_in",
                                                                             "tokens_out", "cost_estimate_usd", "wall_seconds")},
                "findings": None if report is None else {
                    "incident_allegations_accepted": sum(f.category == "incident_allegation" and f.status == "verified"
                                                         for f in report.findings),
                    "total": len(report.findings)},
                "scored": None,
            }
            if rec.state == "scored" and (paths.root / "score.json").exists():
                sc = json.loads((paths.root / "score.json").read_text(encoding="utf-8"))
                row["scored"] = {"case_kind": sc.get("case_kind"), "effects_established": sc["step_recall"],
                                 "accepted_allegations_matched": sc["final_precision"],
                                 "benign_false_alert": sc.get("benign_false_alert")}
            rows.append(row)
        bundles = {r["bundle_id"] for r in rows}
        return {"root_case_id": root, "runs": rows, "distinct_evidence_bundles": len(bundles),
                "note": ("Runs with the same bundle id investigated identical evidence. A run with a different bundle "
                         "id is a separate execution. One run per row: nothing here is an average or a rate.")}

    # ------------------------------------------------------------------ imported evidence (unscored)
    def import_case(self, src_dir: Path | str, *, title: str | None = None, runner_id: str | None = None,
                    investigation_mode: str | None = None) -> CaseRecord:
        """Operator action (CLI): freeze a capture directory as an unscored case. Not exposed over HTTP, because
        it reads a path on this machine."""
        runner_id = runner_id or default_runner_id(self.settings)
        mode = resolve_mode(runner_id, investigation_mode)
        runner = get_runner(runner_id, self.settings, mode)
        case_id = f"case-{uuid.uuid4().hex[:12]}"
        t0 = time.perf_counter()
        manifest = importing.import_bundle(Path(src_dir), self._paths(case_id))
        cap = manifest.operational_context.get("capture", {})
        rec = CaseRecord(case_id=case_id, title=title or f"Imported evidence · {cap.get('capture_id', 'capture')}",
                         card_id="imported", difficulty="unscored", seed=None, runner_id=runner_id, investigation_mode=mode,
                         evidence_origin=manifest.evidence_origin, inference_mode=runner.inference_mode,
                         model_id=runner.model_id, bundle_id=manifest.bundle_id, scored=False)
        rec.timings["import_s"] = round(time.perf_counter() - t0, 3)
        self._save(rec)
        log = self._log(case_id)
        log.append("state", {"state": "generating", "detail": "importing captured evidence"})
        log.append("stage", {"name": "import", "status": "done", "info": {
            "capture_id": cap.get("capture_id"), "evidence_origin": manifest.evidence_origin,
            "origins": sorted({s.origin for s in manifest.sources}), "ground_truth": "none"}})
        log.append("stage", {"name": "freeze", "status": "done",
                             "info": {"artifacts": len(manifest.sources), "raw_bundle_sha256": manifest.raw_bundle_sha256}})
        log.append("stage", {"name": "normalize", "status": "done",
                             "info": {"events": manifest.event_count, "errors": len(manifest.normalization_errors),
                                      "derived_db_sha256": manifest.derived_db_sha256}})
        self._set_state(rec, "frozen", "imported evidence frozen and hashed; there is no answer key for it")
        return rec

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
        index_file = ddir / "index.json"

        def read_index() -> dict[str, str]:
            return json.loads(index_file.read_text(encoding="utf-8")) if index_file.exists() else {}

        # The same token waits for the first request; the orchestrator-wide guard is held only around the small
        # index file, never across the model call, so event streams and other cases keep moving meanwhile.
        with self._once(f"design\x1f{token}"):
            with self._guard:
                index = read_index()
                if token in index:  # a retry: no second call
                    return json.loads((ddir / f"{index[token]}.json").read_text(encoding="utf-8"))
                self._design_seq = max(self._design_seq, len(index)) + 1
                seed = int(design_seed) if design_seed is not None else self._design_seq
            design_id = f"design-{uuid.uuid4().hex[:10]}"
            doc = designer.design_environment(self.settings, seed, model_factory=self.qa_model_factory,
                                              ledger_path=ddir / f"{design_id}.budget.json")
            doc.update(design_id=design_id, created_at=_iso_now(), fixtures=list(designer.FIXTURES))
            with self._guard:
                (ddir / f"{design_id}.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
                index = read_index()
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

        with self._once(client_token):
            known = self._known(client_token)
            if known is not None:
                return known
            doc = self.get_design(design_id)
            if not doc.get("design"):
                raise Conflict(f"this design request ended without a design ({doc['status']}); no case can be made from it")
            design = designer.EnvironmentDesign.model_validate(doc["design"])
            spec, realized = designer.realize(design, doc["design_seed"], fixture)
            spec["environment_provenance"] = designer.provenance(doc, realized, fixture)
            return self.create_case_from_spec(
                spec, title=f"Designed environment · exercise {doc['design_seed']}", runner_id=runner_id,
                investigation_mode=investigation_mode, difficulty="sealed", client_token=client_token,
                public_seed=int(doc["design_seed"]))

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
                             "info": {"card": card_for(rec.card_id)["title"], "evidence_origin": "SIM"}})
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
        caps = None
        allowance = ((rec.lab or {}).get("conditions") or {}).get("investigator_requests")
        if allowance:
            caps = replace(self.settings.caps, max_calls=min(self.settings.caps.max_calls, int(allowance)))
        return RunContext(case_id=rec.case_id, store=store, manifest=load_manifest(paths), case_dir=paths.case,
                          settings=self.settings, emit=lambda t, d: log.append(t, d), pace_s=pace,
                          is_cancelled=cancel.is_set, caps=caps)

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
                # imported evidence has no scenario behind it, and a lab case is not the clinic
                if importing.is_imported(ctx.manifest) or "lab" in ctx.manifest.operational_context:
                    report = baselines.report_for_imported(report, ctx.manifest)
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
            if not rec.scored:
                raise Conflict("this case has no answer key: imported evidence is not scored, so there is nothing to "
                               "unseal. The locked report can be exported", rec.state)
            if rec.state != "report_locked":
                raise Conflict("reveal refused: the report must be locked before truth is unsealed", rec.state)
            if rec.parent_case_id:
                # A derived view shares the original's answer. Unsealing it while the original's report can still
                # be changed would hand that reviewer the answer first.
                try:
                    parent_state: str | None = self._load(rec.parent_case_id).state
                except NotFound:
                    parent_state = None  # the original was reset: no unlocked report is left to protect
                if parent_state is not None and parent_state not in ("report_locked", "scored"):
                    raise Conflict("reveal refused: this is a derived view of another case and shares its answer. "
                                   "Lock the original case's report first, then unseal this one", rec.state)
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
            if "lab" in ep.scenario_spec:
                truth["plan_label"] = (
                    "Worker lab · the changed objective followed a scripted policy; no model chose a fault action"
                    if ep.scenario_spec["lab"]["transition"] else "Worker lab control · no worker's objective was changed")
                truth["lab"] = lab_engine.execution_record(ep.scenario_spec)
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

    def list_cases(self, limit: int | None = 50) -> list[dict[str, Any]]:
        out = []
        for status in sorted(self.runs_dir.glob("case-*/status.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                out.append(CaseRecord(**json.loads(status.read_text(encoding="utf-8"))).public())
            except Exception:
                continue
        return out if limit is None else out[:limit]

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
            "card": {"id": rec.card_id, "title": card_for(rec.card_id)["title"], "tip": card_for(rec.card_id)["tip"],
                     "audience_setup": card_for(rec.card_id)["audience_setup"]},
            "manifest": manifest.model_dump(mode="json"),
            "report": report.model_dump(mode="json") if report else None,
            "reveal": reveal,
            "last_seq": self._log(case_id).last_seq(),
            "runtime": self.settings.public_dict(),
        }

    def investigation_trace(self, case_id: str) -> dict[str, Any]:
        """The recorded plan, tool calls, delegations and case-file activity of this case's investigation."""
        rec = self._load(case_id)
        out = trace.investigation_trace(self._log(case_id).since(0))
        out.update(case_id=case_id, state=rec.state, labels=rec.public()["labels"])
        return out

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

    def evidence_sensor_streams(self, case_id: str) -> dict[str, Any]:
        """The two temperature records of a cold-chain bundle, from this case's own evidence only."""
        store, paths = self._store(case_id)
        with store:
            return evidence_views.sensor_streams(store, load_manifest(paths))

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
        self._load(case_id)  # an unknown case is "not found" whatever token came with the request
        key = self._experiment_token(case_id, token)
        with self._once(key):
            known = self._known(key)  # a retry: the same derived case of this same original
            return known or self._derive_case(case_id, excluded_source_ids, token, key, runner_id, investigation_mode)

    def _derive_case(self, case_id: str, excluded_source_ids: list[str], token: str, key: str,
                     runner_id: str | None, investigation_mode: str | None) -> CaseRecord:
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
            if cpaths.episode_manifest.exists():
                withheld = load_episode_manifest(cpaths).withheld_sources
            else:  # derived from imported evidence: unscored, with the operator record beside the evidence
                withheld = json.loads((cpaths.evidence / "derived_from.json").read_text(encoding="utf-8"))["withheld_sources"]
            what = ", ".join(sorted({source_experiment.source_words(w["host"], w["source"]) for w in withheld}))
            rec = CaseRecord(case_id=child_id, preset_id=parent.preset_id, title=f"{parent.title} · without {what}",
                             card_id=parent.card_id, difficulty=parent.difficulty, seed=parent.seed, runner_id=runner_id,
                             investigation_mode=mode, evidence_origin=parent.evidence_origin,
                             inference_mode=runner.inference_mode, model_id=runner.model_id, bundle_id=manifest.bundle_id,
                             client_token=token, parent_case_id=case_id, scored=parent.scored,
                             excluded_sources=[{k: v for k, v in w.items() if k != "sha256"} for w in withheld])
            rec.timings["derive_s"] = round(time.perf_counter() - t0, 3)
            self._save(rec)
            with self._guard:
                self._tokens[key] = child_id
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
            kids = [c for c in self.list_cases(limit=None) if c.get("parent_case_id") == case_id]
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
        qdir.mkdir(exist_ok=True)  # no parents: a case that was reset meanwhile must not be re-created by a late answer
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
        if not rec.scored or rec.parent_case_id:
            raise Conflict("a recording replays by regenerating its evidence from a scenario; imported evidence and "
                           "derived evidence views have none", rec.state)
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
        with self._once(client_token):
            return self._known(client_token) or self._open_replay(replay_id, f, client_token)

    def _open_replay(self, replay_id: str, f: Path, client_token: str | None) -> CaseRecord:
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
            if not questions_id_ok(q.question_id):  # the id becomes a file name: never take one that is not an id
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
