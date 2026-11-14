"""Runtime calibration: does this model, in this mode, complete the real workflow on development cases?

This is NOT a benchmark. It answers one operational question before a model is promoted to the
default live route (docs/next-run/API_SETUP.md): on a development incident and a benign control,
does the investigator

  * finish a full report and pause for human review,
  * cite only evidence ids that exist in the bundle,
  * allege nothing on the benign control,
  * catch the scored effects of the incident, and
  * resume and lock when the reviewer accepts?

Cases use development seeds only (1-40). Declared test seeds are never touched. Every run goes
through the ordinary orchestrator and the budget gateway, stops at a category spending ceiling,
and is written to a new, timestamped directory that is never overwritten.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alibi.config import REPO_ROOT, Settings
from alibi.runners import RuntimeBlocked

CALIBRATION_DIR = REPO_ROOT / "benchmarks" / "calibration"
CATEGORY_CEILING_USD = 0.25  # API_SETUP.md: calibration and feature checks
# Development seeds, fixed here before the first run. Not test seeds, not demo seeds.
CALIBRATION_CASES: list[dict[str, Any]] = [
    {"ref": "CAL-INCIDENT", "variant": "incident_coverup", "seed": 17, "kind": "incident",
     "purpose": "development incident with a cover-up"},
    {"ref": "CAL-BENIGN", "variant": "benign_rotation", "seed": 23, "kind": "benign",
     "purpose": "benign control: a log rotation that looks alarming in a naive diff"},
]
CRITERIA = ["full_report", "citations_resolve", "review_resume_locks", "benign_abstention", "incident_effects_caught"]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _wait(orch: Any, case_id: str, want: tuple[str, ...], timeout: float) -> str:
    end = time.time() + timeout
    state = orch.record(case_id).state
    while time.time() < end:
        state = orch.record(case_id).state
        if state in want + ("failed", "cancelled"):
            break
        time.sleep(0.1)
    return state


def run_calibration(settings: Settings, *, mode: str = "fast", runner_id: str = "agent-live",
                    ceiling_usd: float = CATEGORY_CEILING_USD, out_root: Path | None = None,
                    cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run the calibration cases and return the result document (also written under out_root)."""
    from alibi.agents import gateway
    from alibi.evidence.store import EvidenceStore
    from alibi.orchestrator import Orchestrator
    from alibi.sim.scenario import build_spec

    if runner_id == "agent-live":
        reason = settings.live_block_reason()
        if reason is not None:
            raise RuntimeBlocked(f"calibration refused, live inference is BLOCKED: {reason}")
    spend = gateway.global_spend_for(settings) if runner_id == "agent-live" else None
    start_committed = spend.snapshot()["committed_usd"] if spend else 0.0
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    model = settings.lead_model if runner_id == "agent-live" else "scripted-fixture"
    out_dir = (out_root or CALIBRATION_DIR) / f"{_slug(model or 'none')}-{mode}-{run_id.lower()}"
    if out_dir.exists():
        raise FileExistsError(f"{out_dir} already exists; calibration results are never overwritten")
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="alibi-calibrate-") as tmp:
        work = replace(settings, runs_dir=Path(tmp) / "runs", sealed_dir=Path(tmp) / "sealed")
        orch = Orchestrator(work, pace_s=0.0)
        for case in cases or CALIBRATION_CASES:
            row: dict[str, Any] = {**case, "status": "completed", "error": None, "checks": {}, "usage": None}
            used = (spend.snapshot()["committed_usd"] - start_committed) if spend else 0.0
            if spend is not None and used >= ceiling_usd:
                row["status"], row["error"] = "unrun_budget", (
                    f"not started: the calibration ceiling of ${ceiling_usd:.2f} is used up (${used:.4f})")
                rows.append(row)
                continue
            try:
                rec = orch.create_case_from_spec(build_spec(case["seed"], case["variant"]), title=case["ref"],
                                                 runner_id=runner_id, investigation_mode=mode)
                cid = rec.case_id
                orch.start_investigation(cid)
                state = _wait(orch, cid, ("awaiting_review",), settings.caps.max_seconds + 90)
                if state != "awaiting_review":
                    row["status"], row["error"] = "error", f"ended in state {state}: {orch.record(cid).error}"
                    rows.append(row)
                    continue
                draft = orch.view(cid)["report"]
                cited = sorted({i for f in draft["findings"] for i in f["evidence_ids"] + f["counterevidence_ids"]}
                               | set(draft["attribution"]["supporting_evidence_ids"])
                               | set(draft["attribution"]["contrary_evidence_ids"]))
                paths = orch._paths(cid)
                with EvidenceStore(paths.db) as store:
                    known = store.existing_ids(cited) if cited else set()
                incomplete = [q for q in draft["open_questions"] if q.startswith("Incomplete run")]
                allegations = [f for f in draft["findings"] if f["category"] == "incident_allegation"]
                row["checks"]["full_report"] = not incomplete and bool(draft["summary"]) and \
                    "did not write a summary" not in draft["summary"]
                row["checks"]["citations_resolve"] = set(cited) <= set(known)
                row["stop_note"] = incomplete[0] if incomplete else None
                row["cited_ids"], row["unresolved_ids"] = len(cited), sorted(set(cited) - set(known))
                locked = orch.review(cid, "accept", note="calibration run: accepted without human reading")
                draft_state = json.loads((paths.case / "draft_state.json").read_text(encoding="utf-8"))
                row["checks"]["review_resume_locks"] = (locked["case"]["state"] == "report_locked"
                                                         and bool(draft_state.get("finalized")))
                scored = orch.reveal(cid)
                score = scored["reveal"]["score"]
                outcomes = [o["outcome"] for o in score["effect_outcomes"]]
                if case["kind"] == "benign":
                    row["checks"]["benign_abstention"] = not allegations
                else:
                    row["checks"]["incident_effects_caught"] = bool(outcomes) and set(outcomes) == {"caught"}
                row["findings"] = [{"claim_type": f["claim_type"], "category": f["category"], "status": f["status"],
                                    "verification_status": f["verification_status"]} for f in scored["report"]["findings"]]
                row["effects"] = {"caught": outcomes.count("caught"), "missed": outcomes.count("missed"),
                                  "total": len(outcomes)}
                row["false_claims_final"] = score.get("false_claims_final")
                row["attribution"] = {k: scored["report"]["attribution"][k] for k in
                                      ("account_used", "human_identity", "named_person_accused", "named_person_exonerated")}
                row["usage"] = scored["report"]["usage"]
                row["model_id"], row["inference_mode"] = scored["report"]["model_id"], scored["report"]["inference_mode"]
                row["system_id"] = scored["report"]["system_id"]
                (out_dir / "reports").mkdir(parents=True, exist_ok=True)
                shutil.copyfile(paths.case / "report.json", out_dir / "reports" / f"{case['ref']}.report.json")
                transcript = paths.case / "transcript.json"
                if transcript.exists():  # tool traces stay local (gitignored)
                    (out_dir / "transcripts").mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(transcript, out_dir / "transcripts" / f"{case['ref']}.transcript.json")
            except RuntimeBlocked:
                raise
            except Exception as exc:  # noqa: BLE001 - a failed calibration case is a result
                row["status"], row["error"] = "error", f"{type(exc).__name__}: {str(exc)[:300]}"
            rows.append(row)
    results = {c: [r["checks"][c] for r in rows if c in r["checks"]] for c in CRITERIA}
    complete = all(r["status"] == "completed" for r in rows)
    passed = complete and all(results[c] and all(results[c]) for c in CRITERIA)
    after = spend.snapshot() if spend else None
    doc = {
        "kind": "runtime-calibration", "note": "Development cases only. An operational check, not a benchmark result.",
        "run_id": run_id, "generated_at": datetime.now(timezone.utc).isoformat(), "mode": mode, "runner": runner_id,
        "model_requested": model, "effort": settings.effort, "max_tokens_per_call": settings.max_tokens_per_call,
        "price_in_per_mtok": settings.price_in_per_mtok, "price_out_per_mtok": settings.price_out_per_mtok,
        "caps": {"max_calls": settings.caps.max_calls, "max_input_tokens": settings.caps.max_input_tokens,
                 "max_output_tokens": settings.caps.max_output_tokens, "max_seconds": settings.caps.max_seconds,
                 "max_input_tokens_per_call": settings.caps.max_input_tokens_per_call},
        "cases": rows, "criteria": {c: (all(v) if v else None) for c, v in results.items()},
        "passed": passed,
        "estimated_cost_usd": round(after["committed_usd"] - start_committed, 6) if after else 0.0,
        "category_ceiling_usd": ceiling_usd,
        "total_spend_after": {k: after[k] for k in ("spent_usd", "unreconciled_usd", "reserved_usd", "cap_usd",
                                                    "limit_in_force_usd")} if after else None,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "calibration.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    doc["result_dir"] = str(out_dir)
    return doc
