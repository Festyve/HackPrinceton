"""Strict result validation for the separately committed worker-lab protocol.

This module reads artifacts only. It has no provider client and cannot spend.
Missing cells are errors, including cells stopped before producing a report.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "benchmarks/worker-lab-v1/protocol.json"
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1)]
Count = Annotated[int, Field(strict=True, ge=0)]
Amount = Annotated[float, Field(ge=0, allow_inf_nan=False)]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def artifact(root: Path, relative: str) -> Path:
    """Resolve a result attachment without accepting an escape from its directory."""
    path = (root / relative).resolve()
    require(not Path(relative).is_absolute() and root.resolve() in path.parents, "artifact leaves result directory")
    require(path.is_file(), f"missing artifact {relative}")
    return path


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Resources(Strict):
    calls: Count
    actions: Count
    tokens_in: Count
    tokens_out: Count
    peak_input_tokens: Count
    seconds: Amount
    cost_usd: Amount


class Provenance(Strict):
    evidence: Literal["SIM", "DOCKER", "HYBRID"]
    inference: Literal["NO_MODEL_BASELINE", "SCRIPTED_FIXTURE", "LIVE_MODEL", "RECORDED_MODEL"]
    execution: Literal["FIXED_SNAPSHOT", "FRESH", "COUNTERFACTUAL_REPLAY", "RECORDED"]
    model: str | None
    source_run_id: str | None
    fault_policy: str | None

    @model_validator(mode="after")
    def validate_labels(self):
        modeled = self.inference in ("LIVE_MODEL", "RECORDED_MODEL")
        require(bool(self.model) == modeled, "model identity must agree with inference provenance")
        require(bool(self.source_run_id) == (self.inference == "RECORDED_MODEL"), "recorded inference needs its source run")
        require((self.execution == "RECORDED") == (self.inference == "RECORDED_MODEL"), "recorded execution/inference mismatch")
        return self


class Score(Strict):
    observable_effects: Count
    successful_effects: Count
    supported_effects: Count
    allegations: Count
    false_allegations: Count
    accepted_allegations: Count
    false_accepted_allegations: Count
    unresolved_findings: Count
    citations: Count
    valid_citations: Count
    benign: bool
    attribution: Literal["correct", "wrong", "unresolved", "not_applicable"]

    @model_validator(mode="after")
    def validate_counts(self):
        require(self.supported_effects <= self.observable_effects <= self.successful_effects, "effect count bounds")
        require(self.supported_effects <= self.allegations and self.false_allegations <= self.allegations, "allegation count bounds")
        require(self.false_accepted_allegations <= self.accepted_allegations <= self.allegations, "accepted allegation count bounds")
        require(self.valid_citations <= self.citations, "citation count bounds")
        require(not self.benign or self.successful_effects == 0, "benign case has successful effects")
        return self


class ReportLock(Strict):
    path: Identifier
    sha256: Hash
    locked_at: datetime
    scored_at: datetime


class Run(Strict):
    run_id: Identifier
    case_id: Identifier
    condition: Identifier
    repetition: Annotated[int, Field(strict=True, ge=1)]
    execution_id: Identifier
    root_execution_id: Identifier
    parent_execution_id: str | None
    world_seed: int | None
    evidence_sha256: Hash
    manifest_sha256: Hash
    tape_sha256: Hash | None
    permission: Identifier
    provenance: Provenance
    versions: dict[str, str]
    allowed: Resources
    used: Resources
    cumulative_cost_usd: Amount
    started_at: datetime
    ended_at: datetime
    status: Literal["completed", "failed", "refused", "capped", "unresolved", "cancelled"]
    stop_reason: str | None
    report: ReportLock | None
    score: Score | None

    @model_validator(mode="after")
    def validate_outcome(self):
        require(self.started_at.tzinfo is not None and self.ended_at.tzinfo is not None, "timestamps require timezone")
        require(self.started_at <= self.ended_at, "run ends before it starts")
        require(self.status == "completed" or bool(self.stop_reason), "stopped/unresolved run needs a reason")
        require((self.score is None) == (self.report is None), "scored report requires both a lock and a score")
        require(self.status not in ("completed", "unresolved") or self.report is not None, "completed outcome needs locked report")
        require(self.cumulative_cost_usd >= self.used.cost_usd, "cumulative cost below run cost")
        require(self.used.peak_input_tokens <= self.used.tokens_in, "peak request exceeds total input")
        if self.provenance.inference in ("NO_MODEL_BASELINE", "SCRIPTED_FIXTURE", "RECORDED_MODEL"):
            require(self.used.calls == self.used.tokens_in == self.used.tokens_out == self.used.cost_usd == 0,
                    "offline or playback run reports new model usage")
        if self.report:
            require(self.report.locked_at.tzinfo is not None and self.report.scored_at.tzinfo is not None,
                    "lock and score need timezone")
            require(self.started_at <= self.report.locked_at < self.report.scored_at <= self.ended_at,
                    "report must lock before scoring inside run interval")
        return self


class Results(Strict):
    format: Literal["daniel-worker-results/1"]
    protocol_sha256: Hash
    protocol_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    batch_id: Identifier
    runs: list[Run]


def read_protocol(path: Path = PROTOCOL) -> dict:
    protocol = json.loads(path.read_text())
    require(protocol["format"] == "daniel-worker-protocol/1", "unknown protocol format")
    cases = protocol["cases"]
    development = {key for key, case in cases.items() if case["split"] == "development"}
    evaluation = {key for key, case in cases.items() if case["split"] == "evaluation"}
    require(bool(development) and bool(evaluation) and development.isdisjoint(evaluation), "case splits must be distinct")
    seeds = [{case["seed"] for key, case in cases.items() if key in split and case["seed"] is not None}
             for split in (development, evaluation)]
    require(seeds[0].isdisjoint(seeds[1]), "runtime seeds overlap across splits")
    require(digest((ROOT / protocol["scorer_path"]).read_bytes()) == protocol["scorer_sha256"], "scorer fixture changed")
    from alibi.episode import bundle_hash
    from alibi.importing import load_capture
    for case in cases.values():
        if case["kind"] == "fixed_snapshot":
            source = ROOT / case["evidence_path"]
            capture, _ = load_capture(source)
            require(digest((source / "capture.json").read_bytes()) == case["capture_manifest_sha256"], "fixture metadata changed")
            require(bundle_hash({item.path: item.sha256 for item in capture.artifacts}) == case["raw_bundle_sha256"], "fixture bytes changed")
    for batch in protocol["batches"].values():
        keys = [(cell["case_id"], cell["condition"], cell["repetition"]) for cell in batch["cells"]]
        require(len(keys) == len(set(keys)), "duplicate declared cell")
        for case_id, condition, repetition in keys:
            require(case_id in cases and condition in protocol["conditions"] and repetition >= 1, "invalid declared cell")
    return protocol


def validate(doc: Results, result_root: Path, protocol_path: Path = PROTOCOL) -> dict:
    """Validate accounting, attachment integrity, and comparison identity before aggregating."""
    protocol = read_protocol(protocol_path)
    require(doc.protocol_sha256 == digest(protocol_path.read_bytes()), "protocol hash mismatch")
    relative_protocol = str(protocol_path.resolve().relative_to(ROOT))
    committed = subprocess.check_output(["git", "show", f"{doc.protocol_commit}:{relative_protocol}"], cwd=ROOT)
    require(committed == protocol_path.read_bytes(), "protocol commit does not contain declared protocol")
    frozen_at = datetime.fromisoformat(subprocess.check_output(
        ["git", "show", "-s", "--format=%cI", doc.protocol_commit], cwd=ROOT, text=True).strip())
    require(doc.batch_id in protocol["batches"], "unknown batch")
    batch = protocol["batches"][doc.batch_id]
    expected = {(c["case_id"], c["condition"], c["repetition"]) for c in batch["cells"]}
    cells = [(r.case_id, r.condition, r.repetition) for r in doc.runs]
    require(len({r.run_id for r in doc.runs}) == len(doc.runs), "duplicate run ID")
    require(len(cells) == len(set(cells)), "duplicate condition cell")
    require(set(cells) == expected, f"condition coverage mismatch, missing {sorted(expected - set(cells))}, extra {sorted(set(cells) - expected)}")
    index = {(r.case_id, r.condition, r.repetition): r for r in doc.runs}
    for run in doc.runs:
        require(frozen_at <= run.started_at, "run predates protocol commit")
        condition = protocol["conditions"][run.condition]
        case = protocol["cases"][run.case_id]
        require(run.world_seed == case["seed"], "world seed mismatch")
        require(run.permission == condition["permission"], "permission profile mismatch")
        require(run.provenance.model == condition["model"] and run.provenance.inference == condition["inference"], "condition provenance mismatch")
        require(run.allowed.model_dump() == condition["limits"], "resource allowance mismatch")
        require(run.versions.get("scorer") == protocol["versions"]["scorer"], "scorer version mismatch")
        source_key = "live_sources" if run.provenance.inference == "LIVE_MODEL" or case["kind"] == "worker_execution" else "baseline_sources"
        require(all(run.versions.get(p) == value for p, value in protocol["versions"][source_key].items()), "source/prompt version mismatch")
        exceeded = any(run.used.model_dump()[key] > value for key, value in run.allowed.model_dump().items())
        require(not exceeded or run.status in ("capped", "failed"), "completed run exceeded resource limits")
        require(run.cumulative_cost_usd < protocol["stopping_rules"]["cumulative_limit_usd"], "cumulative ceiling reached")
        if case["kind"] == "fixed_snapshot":
            require((run.evidence_sha256, run.manifest_sha256) == (case["raw_bundle_sha256"], case["capture_manifest_sha256"]), "frozen evidence/manifest hash mismatch")
            require(run.provenance.execution == "FIXED_SNAPSHOT" and run.tape_sha256 is None, "fixed snapshot provenance mismatch")
        else:
            require(run.tape_sha256 is not None and run.provenance.execution in ("FRESH", "COUNTERFACTUAL_REPLAY"), "worker execution needs tape and lineage")
            require(run.provenance.fault_policy == protocol["runtime"]["fault_policy"], "fault policy mismatch")
        if run.report:
            report = artifact(result_root, run.report.path)
            require(digest(report.read_bytes()) == run.report.sha256, "locked report hash mismatch")
            payload = json.loads(report.read_text())
            require(payload["inference_mode"] == run.provenance.inference, "report provenance mismatch")
            from alibi.contracts import InvestigationReport
            from alibi.reports import report_digest
            parsed = InvestigationReport.model_validate(payload)
            require(parsed.locked and parsed.locked_at == run.report.locked_at, "report is not locked at declared time")
            require(parsed.report_sha256 == report_digest(parsed), "substantive report digest mismatch")
            require(parsed.bundle_id == f"bndl-{run.evidence_sha256[:16]}", "report belongs to another evidence bundle")
            if case["kind"] == "fixed_snapshot":
                from scripts.daniel.evaluate import score_fixture
                require(run.score.model_dump() == score_fixture(payload, run.case_id, protocol), "score differs from locked report and scorer fixture")
    for comparison in batch["comparisons"]:
        for repetition in range(1, protocol["repetitions"] + 1):
            runs = [index[(comparison["case_id"], condition, repetition)] for condition in comparison["conditions"]]
            if comparison["kind"] == "same_evidence":
                require(len({(r.evidence_sha256, r.manifest_sha256, r.execution_id, r.permission) for r in runs}) == 1,
                        "same-evidence comparison identity mismatch")
            elif comparison["kind"] == "rogue_permissions":
                parent, *children = runs
                require(parent.parent_execution_id is None and parent.root_execution_id == parent.execution_id, "invalid root lineage")
                require(len({r.execution_id for r in runs}) == len(runs), "permission change reused execution")
                require(len({r.permission for r in runs}) == len(runs), "permission comparison did not change permission")
                require(all(r.parent_execution_id == parent.execution_id and r.root_execution_id == parent.execution_id for r in children),
                        "permission comparison lineage mismatch")
    return summarize(doc)


def summarize(doc: Results) -> dict:
    groups = {}
    for condition in sorted({run.condition for run in doc.runs}):
        runs = [run for run in doc.runs if run.condition == condition]
        scores = [run.score for run in runs if run.score is not None]
        benign = [score for score in scores if score.benign]
        groups[condition] = {
            "runs": len(runs), "scored": len(scores), "unscored": len(runs) - len(scores),
            "statuses": dict(Counter(run.status for run in runs)),
            "supported_effects": sum(score.supported_effects for score in scores),
            "observable_effects": sum(score.observable_effects for score in scores),
            "successful_effects": sum(score.successful_effects for score in scores),
            "false_allegations": sum(score.false_allegations for score in scores),
            "false_accepted_allegations": sum(score.false_accepted_allegations for score in scores),
            "benign_false_positive_cases": sum(score.false_allegations > 0 for score in benign),
            "benign_scored_cases": len(benign),
            "unresolved_findings": sum(score.unresolved_findings for score in scores),
            "unresolved_cases": sum(score.unresolved_findings > 0 for score in scores),
            "unresolved_attribution": sum(score.attribution == "unresolved" for score in scores),
            "used": {key: sum(getattr(run.used, key) for run in runs) for key in Resources.model_fields
                     if key != "peak_input_tokens"},
            "peak_input_tokens": max((run.used.peak_input_tokens for run in runs), default=0),
        }
    return {"batch": doc.batch_id, "runs": len(doc.runs), "conditions": groups}


def markdown(summary: dict) -> str:
    rows = ["| Condition | Runs / scored | Supported / observable effects | Unsupported proposals / accepted | Benign proposal FP cases / scored | Unresolved findings / attribution | Capped | Calls | Tokens in / out | Seconds | USD |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for condition, group in summary["conditions"].items():
        used = group["used"]
        rows.append(f"| {condition} | {group['runs']} / {group['scored']} | {group['supported_effects']} / {group['observable_effects']} | "
                    f"{group['false_allegations']} / {group['false_accepted_allegations']} | {group['benign_false_positive_cases']} / {group['benign_scored_cases']} | "
                    f"{group['unresolved_findings']} / {group['unresolved_attribution']} | {group['statuses'].get('capped', 0)} | "
                    f"{used['calls']} | {used['tokens_in']} / {used['tokens_out']} | {used['seconds']:.3f} | {used['cost_usd']:.6f} |")
    return "\n".join(rows) + "\n"
