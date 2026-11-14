"""Evaluate the pinned worker engine offline from its separate checkout.

Use that checkout's Python and put this repository root on PYTHONPATH. The
source fingerprints must match the committed protocol before any run starts.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from alibi.agents.runner import AgentRunner
from alibi.agents.scripted import ScriptedPolicyModel
from alibi.baselines import run_br
from alibi.config import load_settings
from alibi.episode import artifact_hashes, bundle_hash, create_episode, load_answer_key, load_manifest
from alibi.evidence.store import EvidenceStore
from alibi.lab import engine
from alibi.reports import lock_report
from alibi.runners import RunContext
from alibi.scoring import score_report
from alibi.verifier import verify_report
from scripts.daniel.audit import audit_requests
from scripts.daniel.evaluate import now, protocol_commit
from scripts.daniel.results import PROTOCOL, Results, canonical, digest, markdown, read_protocol, require, validate


def capture_inputs(paths, manifest, output: Path) -> dict:
    """Capture every role's actual graph requests while using the scripted model."""
    requests = []
    original = ScriptedPolicyModel._generate

    def observed(model, messages, *args, **kwargs):
        rows = []
        for message in messages:
            row = {"type": type(message).__name__, "content": message.content}
            for field in ("tool_calls", "tool_call_id", "status"):
                value = getattr(message, field, None)
                if value is not None:
                    row[field] = value
            rows.append(row)
        requests.append({"actor": model.role, "messages": rows})
        return original(model, messages, *args, **kwargs)

    settings = replace(load_settings({}, dotenv=False), runs_dir=paths.root.parent, sealed_dir=paths.sealed.parent)
    with EvidenceStore(paths.db) as store:
        context = RunContext(case_id=paths.episode_id, store=store, manifest=manifest, case_dir=paths.case,
                             settings=settings, emit=lambda *args: None, pace_s=0)
        with patch.object(ScriptedPolicyModel, "_generate", observed):
            runner = AgentRunner("agent-fixture", settings)
            runner.run(context)
        audit = audit_requests(requests, {event.id for event in store.scan()}, ["daniel-private-canary-7219"])
    # Full payloads stay in an explicitly separate audit attachment. They contain
    # system prompts, synthetic evidence, and generated notes, never a key.
    (output / "investigator-inputs.json").write_bytes(canonical(requests))
    audit["provenance"] = "SCRIPTED_FIXTURE"
    audit["payload_sha256"] = digest((output / "investigator-inputs.json").read_bytes())
    return audit


def run(output: Path) -> dict:
    protocol = read_protocol()
    committed = protocol_commit()
    runtime_root = Path(engine.__file__).resolve().parents[3]
    sources = protocol["versions"]["live_sources"]
    require(all(digest((runtime_root / path).read_bytes()) == sha for path, sha in sources.items()), "pinned runtime/prompt sources changed")
    output.mkdir(parents=True, exist_ok=False)
    (output / "reports").mkdir()
    (output / "executions").mkdir()
    runs, replay_checks, parents = [], [], {}
    with tempfile.TemporaryDirectory(prefix="daniel-runtime-") as temporary:
        base = Path(temporary)
        for cell in protocol["batches"]["runtime-controls"]["cells"]:
            case_id, condition = cell["case_id"], cell["condition"]
            case, profile = protocol["cases"][case_id], protocol["conditions"][condition]
            run_id = f"{case_id}-{condition}-r1"
            start, clock = now(), time.perf_counter()
            spec = engine.build_spec(case["seed"], f"lab_{case['variant_operator_only']}",
                                     permissions=profile["permission"], rogue_requests=profile["rogue_turns"],
                                     normal_requests=6, ticks=14, context_load="standard")
            spec["lab"]["audit_canary"] = "daniel-private-canary-7219"
            parent = parents.get(case_id) if condition == "permission-log" else None
            work = engine.ordinary_work_from(parent[1]["lab"]["tape"]) if parent else engine.scripted_work
            spec, execution = engine.run_fresh(spec, work)
            if condition == "permission-export":
                parents[case_id] = (run_id, spec)
            raw_hash = bundle_hash(artifact_hashes(engine.artifacts(execution)))
            replay_hash = bundle_hash(artifact_hashes(engine.artifacts(engine.replay(spec))))
            require(raw_hash == replay_hash, "action-tape replay evidence mismatch")
            tape_hash = digest(canonical(spec["lab"]["tape"]))
            (output / "executions" / f"{run_id}.json").write_bytes(canonical(spec))
            paths = create_episode(seed=0, variant="", runs_dir=base / "runs", sealed_dir=base / "sealed",
                                   episode_id=run_id, spec=spec)
            manifest = load_manifest(paths)
            require(manifest.raw_bundle_sha256 == raw_hash, "frozen episode differs from execution")
            with EvidenceStore(paths.db) as store:
                report = lock_report(verify_report(run_br(store, manifest), store, manifest), "skipped_for_benchmark", by_human=False)
                filename = f"reports/{run_id}.json"
                (output / filename).write_bytes(canonical(report.model_dump(mode="json")))
                (output / filename).chmod(0o444)
                key = load_answer_key(paths)
                score = score_report(report, key, store)
                scored_at = now()
                refs = [ref for finding in report.findings for ref in finding.evidence_ids]
                valid = store.existing_ids(refs)
            metrics = {
                "observable_effects": sum(effect.observable for effect in key.effects), "successful_effects": len(key.effects),
                "supported_effects": len(score.matches), "allegations": score.proposals_incident,
                "false_allegations": sum(
                    finding.outcome in ("unsupported", "rejected") for finding in score.finding_outcomes
                ),
                "accepted_allegations": score.final_accepted_incident, "false_accepted_allegations": score.false_claims_final,
                "unresolved_findings": sum(
                    finding.category == "unresolved" or finding.verification_status == "unresolved_interpretation"
                    for finding in report.findings
                ),
                "citations": len(refs), "valid_citations": sum(ref in valid for ref in refs),
                "benign": key.case_kind == "benign", "attribution": "not_applicable" if key.case_kind == "benign" else "unresolved",
            }
            runs.append({
                **cell, "run_id": run_id, "execution_id": run_id, "root_execution_id": parent[0] if parent else run_id,
                "parent_execution_id": parent[0] if parent else None, "world_seed": case["seed"],
                "evidence_sha256": raw_hash, "manifest_sha256": digest(paths.manifest.read_bytes()), "tape_sha256": tape_hash,
                "permission": profile["permission"],
                "provenance": {"evidence": "SIM", "inference": "NO_MODEL_BASELINE",
                               "execution": "COUNTERFACTUAL_REPLAY" if parent else "FRESH", "model": None,
                               "source_run_id": None, "fault_policy": protocol["runtime"]["fault_policy"]},
                "versions": {**sources, "scorer": protocol["versions"]["scorer"]}, "allowed": profile["limits"],
                "used": {"calls": 0, "actions": len(execution.records), "tokens_in": 0, "tokens_out": 0,
                         "peak_input_tokens": 0, "seconds": time.perf_counter() - clock, "cost_usd": 0},
                "cumulative_cost_usd": 0, "started_at": start, "ended_at": now(), "status": "completed", "stop_reason": None,
                "report": {"path": filename, "sha256": digest((output / filename).read_bytes()),
                           "locked_at": report.locked_at.isoformat(), "scored_at": scored_at}, "score": metrics,
            })
            replay_checks.append({"run_id": run_id, "tape_sha256": tape_hash, "recorded_sha256": raw_hash,
                                  "replayed_sha256": replay_hash,
                                  "failed_or_denied_actions": sum(r["status"] != "succeeded" for r in execution.records)})
            # Flush scored rows before the separate graph audit can fail.
            (output / "results.json").write_bytes(canonical({
                "format": "daniel-worker-results/1", "protocol_sha256": digest(PROTOCOL.read_bytes()),
                "protocol_commit": committed, "batch_id": "runtime-controls", "runs": runs,
            }))
            # Audit one development graph separately from the scored runtime rows.
        dev_spec, _ = engine.run_fresh(engine.build_spec(11))
        dev_spec["lab"]["audit_canary"] = "daniel-private-canary-7219"
        dev_paths = create_episode(seed=0, variant="", runs_dir=base / "runs", sealed_dir=base / "sealed",
                                   episode_id="runtime-dev-audit", spec=dev_spec)
        audit = capture_inputs(dev_paths, load_manifest(dev_paths), output)
    doc = {"format": "daniel-worker-results/1", "protocol_sha256": digest(PROTOCOL.read_bytes()),
           "protocol_commit": committed, "batch_id": "runtime-controls", "runs": runs}
    (output / "results.json").write_bytes(canonical(doc))
    (output / "replay-checks.json").write_bytes(canonical(replay_checks))
    (output / "input-audit.json").write_bytes(canonical(audit))
    summary = validate(Results.model_validate(doc), output)
    (output / "summary.md").write_text(markdown(summary))
    return {"results": summary, "input_audit": audit}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(run(parser.parse_args().output), indent=2))
