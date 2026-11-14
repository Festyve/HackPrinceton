"""Run the declared worker-lab matrix (benchmarks/worker-lab-eric-matrix/protocol.json) and save every outcome.

    uv run python scripts/run_lab_matrix.py --check         # validate the protocol and its declared worst case; run nothing
    uv run python scripts/run_lab_matrix.py --run           # every declared cell, once, in order, through the budget gateway
    uv run python scripts/run_lab_matrix.py --run --again   # only when a run already exists: a second, separate run

The protocol is committed before any scored cell is run: --run refuses unless no tracked file has an uncommitted
change and the protocol file itself is tracked by git and unmodified. Every cell is saved, including a stopped,
refused or failed one. A run is one process: derived cells need the cases made earlier in it. Nothing here
chooses a seed or drops a cell, and no cell is attempted twice within a run.

A second run is a separate run, never a replacement. --run refuses when a run directory already exists under the
suite, unless --again is given; the new run then gets a new directory of its own and no earlier one is written
over. Repeating the matrix after seeing a result is therefore a deliberate act that stays visible: the reader
(scripts/read_lab_matrix.py) lists every run directory and says at the top of its report when there is more
than one.

Beside the <cell>.json of a cell that became a case, a run saves <cell>.trace.json (the recorded investigation)
and, if the cell's report was locked, <cell>.report.json (the locked report) and <cell>.scenario.json (the sealed
scenario specification, written only after the report is locked and revealed). The result names these files
under "attachments". A cell that could not be made or started has only its result, with the status `error`.
A cell that is still running when the wait ends is saved as did_not_finish_in_time; it is asked to stop, and
its result records whether it did.
"""

from __future__ import annotations

import argparse
import json
import os
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
CANCEL_WAIT_S = 30
DONE = ("awaiting_review", "failed", "cancelled")


def _git() -> str:
    return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()


def _clean(root: Path = ROOT) -> bool:
    """No tracked file has an uncommitted change. An untracked file is not seen here: see `_protocol_committed`."""
    return subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root, text=True).strip() == ""


def _protocol_committed(protocol: Path = PROTOCOL, root: Path = ROOT) -> bool:
    """The protocol file is tracked by git and has no uncommitted change, staged or not.

    `_clean` ignores untracked files, so on its own it would let a protocol that was never committed pass.
    """
    rel = os.path.relpath(protocol, root)
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", rel], cwd=root, capture_output=True, text=True)
    if tracked.returncode != 0:
        return False
    status = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=root, capture_output=True, text=True)
    return status.returncode == 0 and status.stdout.strip() == ""


def _runs(suite: Path = SUITE) -> list[str]:
    """The run directories already saved under the suite, oldest first (their names are UTC timestamps)."""
    return sorted(p.name for p in suite.iterdir() if p.is_dir()) if suite.is_dir() else []


def _run_refusal(suite: Path, run_id: str, again: bool) -> str | None:
    """Why a run named `run_id` may not start under `suite`, or None if it may.

    The matrix is run once. A second run needs --again, and its directory must still be new: it is a separate
    run, never a replacement of an earlier one.
    """
    earlier = _runs(suite)
    if (suite / run_id).exists():
        return f"the run directory {run_id} already exists; a run is never written over"
    if earlier and not again:
        return (f"this matrix already has {len(earlier)} run(s): {', '.join(earlier)}. A second run is a separate run, "
                "not a replacement; pass --again to make one")
    return None


def _wait(orch: Orchestrator, case_id: str) -> str:
    end = time.time() + WAIT_S
    while time.time() < end:
        state = orch.record(case_id).state
        if state in DONE:
            return state
        time.sleep(0.25)
    return orch.record(case_id).state


def _stop(orch: Orchestrator, case_id: str, wait_s: float = CANCEL_WAIT_S) -> dict:
    """Ask a run that passed the wait to stop, so that its thread does not keep spending after its cell is saved.

    The investigation looks for the request between its steps, so a model call that is already under way ends
    first. Returns what was asked and whether the run had stopped when this gave up waiting.
    """
    orch.cancel(case_id)
    end = time.time() + wait_s
    state = orch.record(case_id).state
    while state == "investigating" and time.time() < end:
        time.sleep(0.25)
        state = orch.record(case_id).state
    return {"requested": True, "stopped": state != "investigating", "state_after": state, "waited_up_to_s": wait_s}


def _attach(out: dict, out_dir: Path, kind: str, read) -> None:
    """Save one attachment beside the cell's result and name it there.

    A failure is recorded in the result and not raised, so that the cell's own result is still saved.
    """
    name = f"{out['cell']}.{kind}.json"
    try:
        body = json.dumps(read(), indent=1) + "\n"
        (out_dir / name).write_text(body)
        out["attachments"][kind] = name
    except Exception as exc:  # noqa: BLE001 - a missing attachment is stated in the result, not hidden
        out.setdefault("attachment_errors", {})[kind] = f"{type(exc).__name__}: {str(exc)[:200]}"


def _result(orch: Orchestrator, case_id: str, cell: dict, state: str, out_dir: Path) -> dict:
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
        # file names beside this result; None where the file was not written (see `attachment_errors` if it failed)
        "attachments": {"report": None, "trace": None, "scenario": None},
    }
    if state == "awaiting_review":
        locked = orch.review(case_id, "accept", "")
        out["report_sha256"] = locked["report"].get("report_sha256")
        # the workers' request counts are sealed until the report is locked (they differ between an incident and a control)
        after = orch.lab_view(case_id)["provenance"]
        out["ordinary_requests"], out["worker_usage"] = after.get("ordinary_requests"), after.get("worker_usage")
        # the locked report, as the case holds it after the review
        _attach(out, out_dir, "report", lambda: orch.view(case_id)["report"])
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
        # Truth-bearing: the sealed scenario specification says whether an objective was changed, whose, and what
        # it did. It is written only here, AFTER the report is locked and the truth revealed, and never for a
        # cell whose report did not lock. With it the model-chosen run can be regenerated and audited.
        _attach(out, out_dir, "scenario", lambda: load_episode_manifest(orch._paths(case_id)).scenario_spec)
    # The recorded plan, tool calls and delegations. It is built from the event log and holds no truth, so it is
    # saved whatever the outcome.
    _attach(out, out_dir, "trace", lambda: orch.investigation_trace(case_id))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--again", action="store_true",
                    help="with --run, when a run already exists: make a second, separate run in a new directory")
    args = ap.parse_args(argv)
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
        earlier = _runs(SUITE)
        if earlier:
            print(f"note: this matrix already has {len(earlier)} run(s): {', '.join(earlier)}; --run refuses without --again")
        return 0
    if not _clean():
        print("error: commit the protocol and the code before running scored cells", file=sys.stderr)
        return 2
    if not _protocol_committed():
        print("error: the protocol file is not tracked by git, or it has uncommitted changes; commit it before "
              "running scored cells", file=sys.stderr)
        return 2
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz")
    refusal = _run_refusal(SUITE, run_id, args.again)
    if refusal:
        print(f"error: {refusal}", file=sys.stderr)
        return 2
    settings = load_settings()
    if settings.live_block_reason() is not None:
        print(f"error: live cells are blocked: {settings.live_block_reason()}", file=sys.stderr)
        return 2
    out_dir = SUITE / run_id
    out_dir.mkdir(parents=True, exist_ok=False)  # always a new directory: a run never writes into an earlier one
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
            # Still running when the wait ended: the cell is saved as did_not_finish_in_time whatever happens
            # next, so its thread is asked to stop instead of being left to spend.
            cancel = _stop(orch, rec.case_id) if state not in DONE else None
            result = _result(orch, rec.case_id, cell, state, out_dir)
            if cancel is not None:
                result["cancel"] = cancel
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
