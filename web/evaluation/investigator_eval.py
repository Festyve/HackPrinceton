"""Small local regression evaluation. No paid calls, new AI measurements or benchmark overwrites.

Run from the repo: .venv/bin/python web/evaluation/investigator_eval.py --output test-results/investigator-eval.json
"""
from __future__ import annotations

import argparse
import json
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from alibi.agents.runner import AgentRunner
from alibi.baselines import run_b0
from alibi.config import load_settings
from alibi.episode import create_episode, load_answer_key, load_manifest
from alibi.evidence.store import EvidenceStore
from alibi.reports import lock_report
from alibi.runners import RunContext
from alibi.scoring import score_report
from alibi.sim.scenario import build_spec
from alibi.verifier import verify_report

CASES = [("ordinary-transfer", "benign_approved_transfer", 21),
         ("ordinary-rotation", "benign_rotation", 22),
         ("suspicious-transfer", "incident_plain", 23),
         ("missing-record", "incident_coverup", 24),
         ("incomplete-collection", "benign_collection_gap", 25),
         ("failed-interference", "incident_coverup", 26)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("test-results/investigator-eval.json"))
    args = parser.parse_args()
    # Deny network at the transport boundary, including accidental provider use.
    def deny_network(*_args, **_kwargs):
        raise AssertionError("Network access is disabled in the investigator evaluation")
    socket.socket.connect = deny_network
    socket.create_connection = deny_network
    settings = load_settings({})
    rows = []
    with tempfile.TemporaryDirectory(prefix="alibi-ui-eval-") as tmp:
        root = Path(tmp)
        for label, variant, seed in CASES:
            spec = build_spec(seed, variant)
            if label == "failed-interference":
                # The modeled collector is independent; a removal attempt fails.
                spec["plan"] = [spec["plan"][0], {"step": "delete_log_lines", "params": {"host": "collector", "file": "/var/log/auth.log", "event_selection": "own_session_all"}, "delay_s": 40}]
            paths = create_episode(seed=seed, variant=variant, spec=spec,
                                   runs_dir=root / "runs", sealed_dir=root / "sealed",
                                   episode_id=f"eval-{label}")
            manifest = load_manifest(paths)
            store = EvidenceStore(paths.db)
            try:
                events = []
                ctx = RunContext(case_id=f"eval-{label}", store=store, manifest=manifest,
                                 case_dir=paths.case / "investigator", settings=settings,
                                 emit=lambda typ, data: events.append((typ, data)))
                report = AgentRunner("agent-fixture", settings).run(ctx)
                assert report.inference_mode == "SCRIPTED_FIXTURE" and report.usage.llm_calls == 0
                report = lock_report(verify_report(report, store, manifest), "skipped_for_benchmark", by_human=False)
                # Truth is loaded by the evaluator only after the report is locked.
                truth = load_answer_key(paths)
                baseline = lock_report(verify_report(run_b0(store, manifest), store, manifest), "skipped_for_benchmark", by_human=False)
                score = score_report(report, truth, store)
                baseline_score = score_report(baseline, truth, store)
                refs = score.evidence_reference_validity
                assert refs.value is None or refs.value == 1
                assert score.unsupported_named_attribution == 0
                assert report.attribution.named_person_accused is None
                if label in ("suspicious-transfer", "missing-record"):
                    expected = 3 if label == "missing-record" else 2
                    assert (score.step_recall.num, score.step_recall.den) == (expected, expected), label
                if label == "missing-record":
                    assert score.coverup_detected is True
                if label == "incomplete-collection":
                    assert any(f.claim_type == "collection_gap" and f.category == "unresolved" for f in report.findings)
                if label == "ordinary-rotation":
                    assert any(f.claim_type == "retention_explained_absence" for f in report.findings)
                if label in ("ordinary-transfer", "ordinary-rotation", "incomplete-collection", "failed-interference"):
                    assert not [f for f in report.findings if f.category == "incident_allegation"], label
                if label == "failed-interference":
                    assert truth.steps[-1].execution_status == "failed"
                    assert not truth.effects
                rows.append({"case": label, "variant": variant, "development_seed": seed,
                             "origin": manifest.evidence_origin, "bundle_sha256": manifest.raw_bundle_sha256,
                             "inference_mode": report.inference_mode, "tool_events": sum(t == "tool" for t, _ in events),
                             "executed_steps": [{"name": s.step_name, "status": s.execution_status} for s in truth.steps],
                             "investigator_score": score.model_dump(mode="json"),
                             "keyword_baseline_score": baseline_score.model_dump(mode="json")})
                print(f"PASS {label}: fixture {score.step_recall.num}/{score.step_recall.den}; keyword {baseline_score.step_recall.num}/{baseline_score.step_recall.den}", flush=True)
            finally:
                store.close()
    doc = {"generated_at": datetime.now(timezone.utc).isoformat(), "suite": "investigator-ui-regression-v1",
           "network": "denied", "model_calls_made": 0, "cases": rows,
           "limitations": ["Scripted policy exercises the real DeepAgents graph, not new model inference.",
                           "Development seeds, including a controlled failed attempt; not held-out accuracy.",
                           "Truth is evaluator-only after report lock. Existing official benchmark remains unchanged."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
