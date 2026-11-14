"""Run the declared worker-lab matrix (benchmarks/worker-lab-eric-matrix/protocol.json) and save every outcome.

    uv run python scripts/run_lab_matrix.py --check     # validate the protocol and its declared worst case; run nothing
    uv run python scripts/run_lab_matrix.py --run       # every declared cell, once, in order, through the budget gateway

The protocol is committed before any scored cell is run. Every cell is saved, including a stopped, refused
or failed one. A run is one process: derived cells need the cases made earlier in it. Nothing here chooses a
seed, drops a cell or repeats one after seeing a result.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from alibi.config import load_settings
from alibi.episode import load_episode_manifest
from alibi.orchestrator import Orchestrator

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "benchmarks" / "worker-lab-eric-matrix"
PROTOCOL = SUITE / "protocol.json"
WAIT_S = 420


def _git() -> str:
    return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()


def _clean() -> bool:
    return subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True).strip() == ""


def _wait(orch: Orchestrator, case_id: str) -> str:
    end = time.time() + WAIT_S
    while time.time() < end:
        state = orch.record(case_id).state
        if state in ("awaiting_review", "failed", "cancelled"):
            return state
        time.sleep(0.25)
    return orch.record(case_id).state


def _result(orch: Orchestrator, case_id: str, cell: dict, state: str) -> dict:
    rec = orch.record(case_id)
    view = orch.view(case_id)
    rep = view.get("report") or {}
    stop = next((q for q in rep.get("open_questions", []) if q.startswith("Incomplete run")), None)
    out = {
        "cell": cell["id"], "group": cell["group"], "case_id": case_id, "bundle_id": rec.bundle_id,
        "raw_bundle_sha256": view["manifest"]["raw_bundle_sha256"], "conditions": rec.lab["conditions"],
        "lineage": rec.lab["lineage"], "labels": view["case"]["labels"], "investigation_mode": rec.investigation_mode,
        "ordinary_work": rec.lab["provenance"]["ordinary_work"], "ordinary_requests": rec.lab["provenance"]["ordinary_requests"],
        "worker_usage": rec.lab["provenance"]["worker_usage"],
        "terminal_status": ("failed" if state == "failed" else "cancelled" if state == "cancelled" else
                            "did_not_finish_in_time" if state != "awaiting_review" else "stopped" if stop else "complete"),
        "stop_reason": stop, "error": rec.error,
        "allowed": {"investigator_requests": rec.lab["conditions"]["investigator_requests"],
                    "rogue_requests": rec.lab["conditions"]["rogue_requests"]},
        "used": {k: (rep.get("usage") or {}).get(k) for k in ("llm_calls", "tool_calls", "tokens_in", "tokens_out",
                                                               "cost_estimate_usd", "wall_seconds")},
        "findings": [{k: f[k] for k in ("claim_type", "category", "status", "verification_status")} for f in rep.get("findings", [])],
        "account_reported": (rep.get("attribution") or {}).get("account_used"),
        "person_named": (rep.get("attribution") or {}).get("named_person_accused"),
        "report_sha256": None, "scored": None,
    }
    if state == "awaiting_review":
        locked = orch.review(case_id, "accept", "")
        out["report_sha256"] = locked["report"].get("report_sha256")
        rv = orch.reveal(case_id)["reveal"]
        sc, truth = rv["score"], rv["truth"]
        out["scored"] = {
            "case_kind": truth["case_kind"], "changed_worker": ((truth.get("lab") or {}).get("transition") or {}).get("worker"),
            "executed_effects": [{"type": e["effect_type"], "observable": e["observable"]} for e in truth["effects"]],
            "effects_established": sc["step_recall"], "accepted_allegations_matched": sc["final_precision"],
            "benign_false_alert": sc.get("benign_false_alert"), "unsupported_accepted_allegations": sc.get("false_claims_final"),
            "account_truth": truth["attribution"].get("account_used"),
            "account_correct": (truth["attribution"].get("account_used") is not None
                                and truth["attribution"].get("account_used") == out["account_reported"]),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()
    proto = json.loads(PROTOCOL.read_text())
    cells = proto["cells"]
    ids = [c["id"] for c in cells]
    assert len(set(ids)) == len(ids), "duplicate cell ids in the protocol"
    live_cells = [c for c in cells if c["runner"] == "agent-live"]
    worst = sum(c["worst_case_usd"] for c in live_cells)
    print(f"protocol {proto['suite']} v{proto['version']}: {len(cells)} cells, {len(live_cells)} live; "
          f"declared worst case ${worst:.2f}, ceiling ${proto['ceiling_usd']:.2f}")
    if worst > proto["ceiling_usd"]:
        print("error: the declared worst case is above the ceiling; reduce the matrix before running it", file=sys.stderr)
        return 2
    if args.check or not args.run:
        return 0
    if not _clean():
        print("error: commit the protocol and the code before running scored cells", file=sys.stderr)
        return 2
    settings = load_settings()
    if settings.live_block_reason() is not None:
        print(f"error: live cells are blocked: {settings.live_block_reason()}", file=sys.stderr)
        return 2
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz")
    out_dir = SUITE / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="alibi-lab-matrix-"))
    orch = Orchestrator(replace(settings, runs_dir=tmp / "runs", sealed_dir=tmp / "sealed"), pace_s=0.0)
    made: dict[str, str] = {}  # cell id -> case id, for cells that others derive from
    for cell in cells:
        dest = out_dir / f"{cell['id']}.json"
        try:
            if cell.get("derive_from"):
                parent = made[cell["derive_from"]]
                rec = orch.lab_compare(parent, kind=cell["comparison"], investigator_requests=cell.get("investigator_requests"),
                                       rogue_permissions=cell.get("rogue_permissions"), client_token=f"matrix-{cell['id']}",
                                       runner_id=cell["runner"], investigation_mode=cell.get("mode"))
            else:
                rec = orch.create_lab_case(
                    variant=cell["variant"], seed=cell["seed"], preset=cell.get("preset"),
                    rogue_permissions=cell.get("rogue_permissions"), rogue_requests=cell.get("rogue_requests"),
                    investigator_requests=cell.get("investigator_requests"), context_load=cell.get("context_load"),
                    ordinary_work=cell["ordinary_work"], runner_id=cell["runner"], investigation_mode=cell.get("mode"),
                    client_token=f"matrix-{cell['id']}")
            made[cell["id"]] = rec.case_id
            orch.start_investigation(rec.case_id)
            state = _wait(orch, rec.case_id)
            result = _result(orch, rec.case_id, cell, state)
        except Exception as exc:  # noqa: BLE001 - a cell that cannot run is a result, not a gap
            result = {"cell": cell["id"], "group": cell["group"], "case_id": made.get(cell["id"]), "terminal_status": "error",
                      "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        result.update(declared=cell, git_commit=_git(), finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        dest.write_text(json.dumps(result, indent=1) + "\n")
        sc = (result.get("scored") or {})
        est = sc.get("effects_established") or {}
        print(f"{cell['id']}: {result['terminal_status']} · used {((result.get('used') or {}).get('llm_calls'))} of "
              f"{(result.get('allowed') or {}).get('investigator_requests')} request(s) · established {est.get('num')}/{est.get('den')} "
              f"· false alert {sc.get('benign_false_alert')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
