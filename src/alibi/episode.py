"""Episode creation: simulate -> freeze -> hash -> normalize -> seal truth (PLAN 7).

Layout
    runs/<episode_id>/evidence/raw/...          frozen raw artifacts (read-only)
    runs/<episode_id>/evidence/derived/events.duckdb   derived, hashed separately
    runs/<episode_id>/evidence/manifest.json    investigator-visible manifest
    runs/<episode_id>/case/                     investigator notes, transcript, report
    sealed/<episode_id>/answer_key.json         sealed truth (separate root)
    sealed/<episode_id>/episode_manifest.json   seed, scenario spec, executed plan

The sealed directory being elsewhere is not itself an access control. The control is
that investigator-side code receives only an EvidenceStore handle and the public
manifest, never these paths (see tests/test_isolation.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from alibi.contracts import (
    AnswerKey,
    AnswerKeyStep,
    AttributionTruth,
    BenignOutcome,
    EpisodeManifest,
    EvidenceManifest,
    EvidencePointer,
    SourceInfo,
    TruthEffect,
)
from alibi.evidence.normalize import NORMALIZER_VERSION, classify, normalize_bundle
from alibi.evidence.store import build_store
from alibi.sim import steps as S
from alibi.sim.scenario import CARDS, SCENARIO_VERSION, SimOutput, build_spec, operational_context, simulate
from alibi.sim.world import SIMULATOR_VERSION, sha256_text

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
INDEPENDENT_KINDS = {"collector", "flow", "badge", "reference"}  # "reference": the cold-chain reference logger
LOGIN_STEPS = ("login_as", "login_remote")  # the step that establishes which account a plan used


class EpisodeError(RuntimeError):
    pass


@dataclass(frozen=True)
class EpisodePaths:
    episode_id: str
    root: Path
    sealed: Path

    @property
    def evidence(self) -> Path:
        return self.root / "evidence"

    @property
    def raw(self) -> Path:
        return self.evidence / "raw"

    @property
    def db(self) -> Path:
        return self.evidence / "derived" / "events.duckdb"

    @property
    def manifest(self) -> Path:
        return self.evidence / "manifest.json"

    @property
    def case(self) -> Path:
        return self.root / "case"

    @property
    def answer_key(self) -> Path:
        return self.sealed / "answer_key.json"

    @property
    def episode_manifest(self) -> Path:
        return self.sealed / "episode_manifest.json"


def validate_episode_id(episode_id: str) -> str:
    if not isinstance(episode_id, str) or not _ID_RE.match(episode_id):
        raise EpisodeError("episode id must match ^[a-z0-9][a-z0-9-]{2,63}$")
    return episode_id


def new_episode_id(prefix: str = "ep") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def episode_paths(episode_id: str, runs_dir: Path, sealed_dir: Path) -> EpisodePaths:
    validate_episode_id(episode_id)
    return EpisodePaths(episode_id=episode_id, root=Path(runs_dir) / episode_id, sealed=Path(sealed_dir) / episode_id)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def bundle_hash(file_hashes: dict[str, str]) -> str:
    """Hash over the sorted (artifact, sha256) list: the raw-evidence identity."""
    body = "".join(f"{k}\x00{v}\n" for k, v in sorted(file_hashes.items()))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def artifact_hashes(artifacts: dict[str, str]) -> dict[str, str]:
    return {k: hashlib.sha256(v.encode("utf-8")).hexdigest() for k, v in artifacts.items()}


def _make_readonly(path: Path) -> None:
    for p in sorted(path.rglob("*"), reverse=True):
        if p.is_file():
            p.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    for p in sorted([path, *[d for d in path.rglob("*") if d.is_dir()]], reverse=True):
        p.chmod(stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)


def _make_writable(path: Path) -> None:
    if not path.exists():
        return
    for p in [path, *path.rglob("*")]:
        try:
            p.chmod(p.stat().st_mode | stat.S_IWUSR)
        except OSError:
            pass


def remove_episode(paths: EpisodePaths, runs_dir: Path, sealed_dir: Path) -> None:
    """Delete one episode's directories. Only ever touches <runs>/<id> and <sealed>/<id>."""
    validate_episode_id(paths.episode_id)
    for target, parent in ((paths.root, Path(runs_dir)), (paths.sealed, Path(sealed_dir))):
        if target.resolve().parent != parent.resolve():
            raise EpisodeError(f"refusing to remove {target}: not directly inside {parent}")
        if target.exists():
            _make_writable(target)
            shutil.rmtree(target)


def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                             cwd=Path(__file__).resolve().parent)
        return out.stdout.strip() or None
    except Exception:
        return None


def _package_versions() -> dict[str, str]:
    vers: dict[str, str] = {}
    for pkg in ("alibi", "deepagents", "langgraph", "langchain", "langchain-core", "duckdb", "fastapi", "pydantic"):
        try:
            vers[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            pass
    return vers


def build_answer_key(episode_id: str, sim: SimOutput, canary: str, executed_plan_sha256: str) -> AnswerKey:
    spec = sim.spec
    steps: list[AnswerKeyStep] = []
    effects: list[TruthEffect] = []
    crime = spec.get("crime") or {}
    for i, r in enumerate(sim.step_results):
        step_id = f"s{i + 1}"
        effect_id = None
        if r.status == "succeeded" and r.effect_type and r.effect_window:
            effect_id = f"e{len(effects) + 1}"
            effects.append(TruthEffect(
                effect_id=effect_id, step_id=step_id, effect_type=r.effect_type, host=r.host,
                object=r.affected_object or "", session=r.affected_session,
                t_start=r.effect_window[0], t_end=r.effect_window[1],
                # an effect no captured source can show is recorded but never scored
                observable=getattr(r, "observable", True), unobservable_reason=getattr(r, "unobservable_reason", None),
                evidence=[EvidencePointer(artifact_logical=t.artifact_logical, raw_sha256=sha256_text(t.raw),
                                          role=t.role, ts=t.ts) for t in r.traces],
            ))
        meta = S.ATTACK_META[r.step]
        steps.append(AnswerKeyStep(
            step_id=step_id, step_name=r.step, attack_id=meta["attack_id"], attack_label=meta["label"],
            host=r.host, operator_true=crime.get("operator_person", "unknown"), account_used=r.account_used,
            t_start=r.t_start, t_end=r.t_end, params=r.params, artifacts_touched=r.artifacts_touched,
            difficulty=spec["difficulty"], crime_card_id=spec["card_id"], execution_status=r.status,
            outcome=r.outcome, affected_object=r.affected_object, affected_session=r.affected_session,
            effect_id=effect_id,
        ))
    benign = [BenignOutcome(outcome_id=f"b{i + 1}", **o) for i, o in enumerate(sim.benign_outcomes)]
    if spec["case_kind"] == "incident":
        # Truth is what was executed: the account comes from the login step that actually succeeded,
        # not from what the scenario or a planning model intended.
        logins = [r for r in sim.step_results if r.step in LOGIN_STEPS and r.status == "succeeded"]
        used = logins[0].account_used if logins else None
        attribution = AttributionTruth(
            account_used=used, account_owner_person=f"person:{used}" if used else None,
            operator_true=crime["operator_person"], framed=bool(used) and crime["operator_person"] != f"person:{used}",
            session=sim.adversary_session, named_attribution_supportable=False,
        )
    else:
        attribution = AttributionTruth()
    return AnswerKey(episode_id=episode_id, crime_card_id=spec["card_id"], case_kind=spec["case_kind"],
                     difficulty=spec["difficulty"], steps=steps, effects=effects, benign_outcomes=benign,
                     attribution=attribution, executed_plan_sha256=executed_plan_sha256, canary=canary)


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def create_episode(*, seed: int, variant: str, runs_dir: Path, sealed_dir: Path, episode_id: str | None = None,
                   spec: dict[str, Any] | None = None, plan_model_id: str | None = None) -> EpisodePaths:
    """Generate, freeze, normalize and seal one episode. Returns its paths.

    Pass `spec` to replay a saved scenario specification exactly (it wins over seed/variant).
    """
    episode_id = validate_episode_id(episode_id or new_episode_id())
    paths = episode_paths(episode_id, runs_dir, sealed_dir)
    if paths.root.exists() or paths.sealed.exists():
        raise EpisodeError(f"episode {episode_id} already exists; evidence is immutable, choose a new id")
    spec = spec if spec is not None else build_spec(seed, variant)
    sim = simulate(spec)

    # 5. freeze raw evidence: write, hash, make read-only
    file_hashes: dict[str, str] = {}
    for artifact, text in sorted(sim.artifacts.items()):
        dest = paths.raw / artifact
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(text.encode("utf-8"))
        file_hashes[artifact] = sha256_file(dest)
    raw_hash = bundle_hash(file_hashes)
    _make_readonly(paths.raw)

    # 6. normalize into a derived DB, close the writer, then hash it separately
    events, errors = normalize_bundle(paths.raw, list(file_hashes))
    build_store(paths.db, events)
    db_hash = sha256_file(paths.db)
    paths.db.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    by_artifact: dict[str, list] = {}
    for ev in events:
        if ev.action != "unparsed":
            by_artifact.setdefault(ev.artifact_ref.artifact, []).append(ev.ts)
    forwarded = {(f["host"], f["file"]) for f in operational_context(spec)["logging_policy"]["forwarded_files"]}
    sources: list[SourceInfo] = []
    for artifact in sorted(file_hashes):
        kind, role, logical, gen = classify(artifact)
        tss = by_artifact.get(artifact, [])
        snapshot = kind == "fs_stat"
        note = ""
        if snapshot:
            note = "point-in-time metadata snapshot taken at capture end"
        elif gen:
            note = f"rotated generation .{gen} still present on the host at capture"
        elif kind == "flow":
            note = "simulated flow records from the tap position; not a packet capture"
        elif kind == "reference":
            note = "independent reference logger with its own probe and clock (not network-synchronised)"
        elif kind == "sensor":
            note = "readings as stored on the hub (the stream a dashboard shows); writable on the hub"
        sources.append(SourceInfo(
            artifact=artifact, host=role, source={"history": "shell_history"}.get(kind, kind), logical_file=logical,
            sha256=file_hashes[artifact], size_bytes=(paths.raw / artifact).stat().st_size,
            line_count=sim.artifacts[artifact].count("\n"),
            tamper_exposure="independent_witness" if kind in INDEPENDENT_KINDS else "host_local_writable",
            coverage_start=None if snapshot or not tss else min(tss),
            coverage_end=None if snapshot or not tss else max(tss),
            coverage_note=note, forwarded_to_collector=(role, logical) in forwarded,
        ))
    context = operational_context(spec)
    context["tip"] = CARDS[spec["card_id"]]["tip"]
    manifest = EvidenceManifest(
        bundle_id=f"bndl-{raw_hash[:16]}", normalizer_version=NORMALIZER_VERSION,
        capture_start=datetime.fromisoformat(spec["capture_start"]),
        capture_end=datetime.fromisoformat(spec["capture_end"]),
        sources=sources, raw_bundle_sha256=raw_hash, derived_db_sha256=db_hash, event_count=len(events),
        normalization_errors=errors, operational_context=context,
    )
    _write_json(paths.manifest, manifest.model_dump(mode="json"))
    paths.case.mkdir(parents=True, exist_ok=True)

    # sealed truth, written by the orchestrator (never by an agent)
    executed = [{"step": r.step, "params": r.params, "t_start": r.t_start.isoformat(), "status": r.status}
                for r in sim.step_results]
    executed_hash = hashlib.sha256(json.dumps(executed, sort_keys=True).encode()).hexdigest()
    key = build_answer_key(episode_id, sim, canary=f"CANARY-{secrets.token_hex(12)}", executed_plan_sha256=executed_hash)
    paths.sealed.mkdir(parents=True, exist_ok=True)
    _write_json(paths.answer_key, key.model_dump(mode="json"))
    ep = EpisodeManifest(
        episode_id=episode_id, bundle_id=manifest.bundle_id, seed=spec["seed"], simulator_version=SIMULATOR_VERSION,
        scenario_version=SCENARIO_VERSION, crime_card_id=spec["card_id"], case_kind=spec["case_kind"],
        variant=spec["variant"], difficulty=spec["difficulty"], plan_source=spec.get("plan_source", "scripted_scenario"),
        plan_model_id=plan_model_id, scenario_spec=spec, executed_plan_sha256=executed_hash,
        raw_bundle_sha256=raw_hash, evidence_files=file_hashes, created_at=datetime.now(timezone.utc),
        git_commit=_git_commit(), package_versions=_package_versions(),
    )
    _write_json(paths.episode_manifest, ep.model_dump(mode="json"))
    os.chmod(paths.manifest, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return paths


# --------------------------------------------------------------------------- loading


def load_manifest(paths: EpisodePaths) -> EvidenceManifest:
    return EvidenceManifest.model_validate_json(paths.manifest.read_text(encoding="utf-8"))


def load_answer_key(paths: EpisodePaths) -> AnswerKey:
    """Trusted scorer/orchestrator code only."""
    return AnswerKey.model_validate_json(paths.answer_key.read_text(encoding="utf-8"))


def load_episode_manifest(paths: EpisodePaths) -> EpisodeManifest:
    """Trusted scorer/orchestrator code only."""
    return EpisodeManifest.model_validate_json(paths.episode_manifest.read_text(encoding="utf-8"))


def verify_raw_integrity(paths: EpisodePaths) -> list[str]:
    """Re-hash the frozen bundle. Returns a list of problems (empty = intact)."""
    manifest = load_manifest(paths)
    problems: list[str] = []
    seen: dict[str, str] = {}
    for src in manifest.sources:
        f = paths.raw / src.artifact
        if not f.exists():
            problems.append(f"missing artifact {src.artifact}")
            continue
        h = sha256_file(f)
        seen[src.artifact] = h
        if h != src.sha256:
            problems.append(f"hash mismatch for {src.artifact}")
    if not problems and bundle_hash(seen) != manifest.raw_bundle_sha256:
        problems.append("bundle hash mismatch")
    if manifest.derived_db_sha256 and paths.db.exists() and sha256_file(paths.db) != manifest.derived_db_sha256:
        problems.append("derived DB hash mismatch")
    return problems


def reproduce_raw_hash(paths: EpisodePaths) -> tuple[str, str]:
    """Re-run the saved scenario specification and return (saved, reproduced) raw bundle hashes."""
    ep = load_episode_manifest(paths)
    sim = simulate(ep.scenario_spec)
    return ep.raw_bundle_sha256, bundle_hash(artifact_hashes(sim.artifacts))
