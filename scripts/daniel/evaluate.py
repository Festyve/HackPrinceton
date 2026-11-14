"""Run the existing offline baselines and inspect worker-lab result artifacts.

Usage from the repository root:
    python -m scripts.daniel.evaluate run --output /tmp/worker-results
    python -m scripts.daniel.evaluate validate /tmp/worker-results/results.json
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import time

from alibi.baselines import run_b0, run_br
from alibi.contracts import InvestigationReport
from alibi.episode import episode_paths
from alibi.evidence.normalize import normalize_bundle
from alibi.evidence.store import EvidenceStore
from alibi.importing import import_bundle, load_capture
from alibi.reports import lock_report
from alibi.verifier import is_accepted, verify_report
from scripts.daniel.results import (
    PROTOCOL, ROOT, Results, canonical, digest, markdown, read_protocol, require, validate,
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def protocol_commit() -> str:
    """Identify the commit containing the exact on-disk protocol bytes."""
    relative = str(PROTOCOL.relative_to(ROOT))
    commit = git("log", "-1", "--format=%H", "--", relative)
    committed = subprocess.check_output(["git", "show", f"{commit}:{relative}"], cwd=ROOT)
    require(committed == PROTOCOL.read_bytes(), "commit the protocol before running")
    return commit


def score_fixture(report: dict, case_id: str, protocol: dict) -> dict:
    """Score submitted effects against independent references after locking the report.

Exact claim/object matching prevents repeated allegations from earning extra
recall. A matching claim needs a real cited record in the expected evidence
basis. Valid citations alone cannot prove a claim's interpretation.
"""
    parsed = InvestigationReport.model_validate(report)
    expected = json.loads((ROOT / protocol["scorer_path"]).read_text())["cases"][case_id]
    source = ROOT / protocol["cases"][case_id]["evidence_path"]
    _, files = load_capture(source)
    events, errors = normalize_bundle(source, list(files))
    require(not errors, "fixture failed normalization")
    by_ref = {(event.artifact_ref.artifact, event.artifact_ref.line): event.id for event in events}
    valid_ids = {event.id for event in events}
    remaining = list(expected["incident_claims"])
    supported = false = false_accepted = 0
    allegations = [finding for finding in parsed.findings if finding.category == "incident_allegation"]
    for finding in allegations:
        match = next((claim for claim in remaining
                      if claim["claim_type"] == finding.claim_type and claim["object"] == finding.object_or_session
                      and set(finding.evidence_ids) & {by_ref[(ref["artifact"], ref["line"])] for ref in claim["evidence"]}), None)
        if match is None:
            false += 1
            false_accepted += is_accepted(finding)
        else:
            if is_accepted(finding):
                supported += 1
                remaining.remove(match)
    citations = [citation for finding in parsed.findings for citation in finding.evidence_ids]
    attributed = parsed.attribution.account_used
    target = expected["attribution"]
    attribution = "not_applicable"
    if target["status"] != "not_applicable":
        attribution = "unresolved" if attributed is None else "wrong"
        if attributed == target["account"]:
            # The legacy schema has no worker ID. A correct account leaves the
            # worker link unresolved, so it earns no worker-attribution credit.
            attribution = "unresolved"
    if parsed.attribution.named_person_accused:
        attribution = "wrong"
    return {
        "observable_effects": len(expected["incident_claims"]),
        "successful_effects": sum(attempt["outcome"] == "succeeded" for attempt in expected["fault_attempts"]),
        "supported_effects": supported, "allegations": len(allegations), "false_allegations": false,
        "accepted_allegations": sum(is_accepted(finding) for finding in allegations),
        "false_accepted_allegations": false_accepted,
        "unresolved_findings": sum(finding.category == "unresolved" or finding.verification_status == "unresolved_interpretation"
                                   for finding in parsed.findings),
        "citations": len(citations), "valid_citations": sum(citation in valid_ids for citation in citations),
        "benign": not expected["incident_claims"], "attribution": attribution,
    }


def run_offline(output: Path) -> dict:
    protocol = read_protocol()
    committed = protocol_commit()
    sources = protocol["versions"]["baseline_sources"]
    require(all(digest((ROOT / path).read_bytes()) == value for path, value in sources.items()), "baseline source changed")
    output.mkdir(parents=True, exist_ok=False)
    (output / "reports").mkdir()
    runs = []
    with tempfile.TemporaryDirectory(prefix="daniel-worker-eval-") as temporary:
        base = Path(temporary)
        for cell in protocol["batches"]["offline-fixtures"]["cells"]:
            case_id, condition = cell["case_id"], cell["condition"]
            case = protocol["cases"][case_id]
            settings = protocol["conditions"][condition]
            run_id = f"{case_id}-{condition}-r{cell['repetition']}"
            paths = episode_paths(run_id.lower(), base / "runs", base / "sealed")
            source = ROOT / case["evidence_path"]
            require(digest((source / "capture.json").read_bytes()) == case["capture_manifest_sha256"], "capture manifest changed")
            manifest = import_bundle(source, paths)
            require(manifest.raw_bundle_sha256 == case["raw_bundle_sha256"], "evidence changed")
            start, clock = now(), time.perf_counter()
            record = {
                **cell, "run_id": run_id, "execution_id": case_id, "root_execution_id": case_id,
                "parent_execution_id": None, "world_seed": None, "evidence_sha256": manifest.raw_bundle_sha256,
                "manifest_sha256": case["capture_manifest_sha256"], "tape_sha256": None, "permission": "fixed_snapshot",
                "provenance": {"evidence": "SIM", "inference": "NO_MODEL_BASELINE", "execution": "FIXED_SNAPSHOT",
                               "model": None, "source_run_id": None, "fault_policy": None},
                "versions": {**sources, "scorer": protocol["versions"]["scorer"]}, "allowed": settings["limits"],
                "started_at": start, "status": "completed", "stop_reason": None, "report": None, "score": None,
                "cumulative_cost_usd": 0,
            }
            try:
                with EvidenceStore(paths.db) as store:
                    runner = {"B0": run_b0, "BR": run_br}[condition]
                    report = verify_report(runner(store, manifest), store, manifest)
                    report = lock_report(report, "skipped_for_benchmark", by_human=False)
                payload = report.model_dump(mode="json")
                filename = f"reports/{run_id}.json"
                locked = canonical(payload)
                with (output / filename).open("xb") as stream:
                    stream.write(locked)
                (output / filename).chmod(0o444)
                locked_at = report.locked_at.isoformat()
                # Scorer-only fixture access starts after durable report creation.
                record["score"] = score_fixture(payload, case_id, protocol)
                record["report"] = {"path": filename, "sha256": digest(locked), "locked_at": locked_at, "scored_at": now()}
            except Exception as exc:
                record.update(status="failed", stop_reason=f"{type(exc).__name__}: {exc}", score=None, report=None)
            elapsed = time.perf_counter() - clock
            record["used"] = {"calls": 0, "actions": 0, "tokens_in": 0, "tokens_out": 0,
                              "peak_input_tokens": 0, "seconds": elapsed, "cost_usd": 0}
            record["ended_at"] = now()
            runs.append(record)
            # Preserve every terminal outcome as it occurs, even if a later cell crashes.
            with (output / "outcomes.jsonl").open("a") as stream:
                stream.write(json.dumps(record, allow_nan=False) + "\n")
    doc = {"format": "daniel-worker-results/1", "protocol_commit": committed,
           "protocol_sha256": digest(PROTOCOL.read_bytes()), "batch_id": "offline-fixtures", "runs": runs}
    result_path = output / "results.json"
    result_path.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n")
    summary = validate(Results.model_validate(doc), output)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (output / "summary.md").write_text(markdown(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--output", required=True, type=Path)
    check = commands.add_parser("validate")
    check.add_argument("results", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        summary = run_offline(args.output)
    else:
        summary = validate(Results.model_validate_json(args.results.read_text()), args.results.parent)
    print(markdown(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
