"""Run the `live-investigator` batch of Daniel's worker-lab-v1 protocol through the budget gateway.

The protocol pins the investigator's source files. Run this with the interpreter of a checkout at the pinned
runtime commit, with THIS repository on PYTHONPATH (for the protocol, the fixtures and Daniel's scorer and
validator), and with ALIBI_SPEND_LEDGER pointing at the one real cumulative ledger:

    PYTHONPATH="$PWD" ALIBI_SPEND_LEDGER="$PWD/.alibi/spend.json" \
        <pinned checkout>/.venv/bin/python -m scripts.run_daniel_live_batch --check
    ... --run

It aborts before any model call if a pinned source differs, if the evidence of any cell of the batch differs
from the protocol, or if the batch's declared worst case does not fit the remaining allowance. Each cell is
attempted once. Every outcome is kept: a run that is capped, refused or fails is a row, not a gap, and a cell
that cannot be imported or run is a `failed` row after which the next cell is still attempted. The report is
locked before the scorer's fixture is opened for scoring; before that only its digest is compared with the
protocol. Everything the investigator model was sent is saved beside the results for audit.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import alibi
from alibi.agents import gateway
from alibi.config import load_settings
from alibi.episode import bundle_hash, episode_paths
from alibi.evidence.store import EvidenceStore
from alibi.importing import import_bundle, load_capture
from alibi.reports import lock_report
from alibi.runners import RunContext, get_runner
from alibi.verifier import verify_report
from scripts.daniel.audit import audit_requests
from scripts.daniel.evaluate import now, protocol_commit, score_fixture
from scripts.daniel.results import PROTOCOL, ROOT, Results, canonical, digest, markdown, read_protocol, require, validate

BATCH = "live-investigator"
RUNTIME_ROOT = Path(alibi.__file__).resolve().parents[2]


def _rows(messages: list) -> list[dict]:
    rows = []
    for message in messages:
        row = {"type": type(message).__name__, "content": message.content}
        for field in ("tool_calls", "tool_call_id", "status"):
            value = getattr(message, field, None)
            if value is not None:
                row[field] = value
        rows.append(row)
    return rows


def _tool_names(bound) -> list[str]:
    tools = (getattr(bound, "kwargs", None) or {}).get("tools") or []
    names = []
    for tool in tools:
        if isinstance(tool, dict):
            names.append(str(tool.get("name") or (tool.get("function") or {}).get("name")))
        else:
            names.append(str(getattr(tool, "name", tool)))
    return names


def _status_for(stop_reason: str | None) -> str:
    """The status of a row, from the stop text of its report. None means the run finished.

    A refusal is looked for first. The runner words it "stopped because the model declined this request ...",
    which contains neither "refus" nor "budget gateway", so "declined" has to count as one.
    """
    if stop_reason is None:
        return "completed"
    text = stop_reason.lower()
    if "declined" in text or "refus" in text:
        return "refused"
    if "budget gateway" in text:
        return "capped"
    return "unresolved"


def check_evidence(protocol: dict, root: Path = ROOT) -> dict[str, dict]:
    """Compare the fixture of every cell of the batch with the protocol. Reads files only; no model is involved.

    The same two comparisons as `read_protocol` makes: the digest of the capture manifest, and the bundle hash
    over the artifacts' digests (`load_capture` has hashed every artifact file against that manifest). Returns
    what was measured for each case.
    """
    measured: dict[str, dict] = {}
    for cell in protocol["batches"][BATCH]["cells"]:
        case_id = cell["case_id"]
        if case_id in measured:
            continue
        case = protocol["cases"][case_id]
        require(case["kind"] == "fixed_snapshot", f"{case_id} is not a fixed snapshot; this batch runs frozen fixtures only")
        source = root / case["evidence_path"]
        capture, _ = load_capture(source)
        found = {"capture_manifest_sha256": digest((source / "capture.json").read_bytes()),
                 "raw_bundle_sha256": bundle_hash({item.path: item.sha256 for item in capture.artifacts}),
                 "evidence_origin": capture.evidence_origin}
        require(found["capture_manifest_sha256"] == case["capture_manifest_sha256"],
                f"the capture manifest of {case_id} differs from the protocol")
        require(found["raw_bundle_sha256"] == case["raw_bundle_sha256"], f"the evidence of {case_id} differs from the protocol")
        measured[case_id] = found
    return measured


def preflight(protocol: dict, settings) -> dict:
    pins = protocol["versions"]["live_sources"]
    measured = {path: digest((RUNTIME_ROOT / path).read_bytes()) for path in pins}
    require(measured == pins, "a pinned investigator source differs from the protocol: "
            + ", ".join(p for p in pins if measured[p] != pins[p]))
    evidence = check_evidence(protocol)  # every cell of the batch, before any of them is run
    require(settings.live_block_reason() is None, f"live inference is blocked: {settings.live_block_reason()}")
    cells = protocol["batches"][BATCH]["cells"]
    models = {protocol["conditions"][c["condition"]]["model"] for c in cells}
    require(models == {settings.lead_model}, f"the configured model {settings.lead_model} is not the protocol's {sorted(models)}")
    ledger = gateway.global_spend_for(settings)
    require(ledger is not None, "no cumulative spend ledger is configured")
    snap = ledger.snapshot()
    worst = sum(protocol["conditions"][c["condition"]]["limits"]["cost_usd"] for c in cells)
    rules = protocol["stopping_rules"]
    require(worst <= rules["live_matrix_limit_usd"] + 1e-9, "the batch's declared worst case is above the protocol's limit")
    require(snap["remaining_to_limit_usd"] >= worst, "the batch's declared worst case does not fit the remaining allowance")
    require(snap["reserved_usd"] == 0 and snap["unreconciled_usd"] == 0, "the ledger has open reservations or unreconciled calls")
    return {"runtime_root_commit_pin": protocol["versions"]["runtime_commit"], "sources": measured, "evidence": evidence,
            "model": settings.lead_model, "cells": len(cells), "declared_worst_case_usd": worst,
            "live_matrix_limit_usd": rules["live_matrix_limit_usd"],
            "ledger_before": {k: snap[k] for k in ("cap_usd", "limit_in_force_usd", "spent_usd", "reserved_usd",
                                                    "unreconciled_usd", "remaining_to_limit_usd", "calls")},
            "note": "the worst case was checked against the remaining allowance before the first call; the gateway "
                    "then reserves each call individually", "checked_at": now()}


def run_batch(output: Path) -> dict:
    protocol = read_protocol()
    committed = protocol_commit()
    settings = load_settings()
    pre = preflight(protocol, settings)
    output.mkdir(parents=True, exist_ok=False)
    (output / "reports").mkdir()
    (output / "investigator-inputs").mkdir()
    (output / "preflight.json").write_text(json.dumps(pre, indent=2) + "\n")
    pins = protocol["versions"]["live_sources"]
    runs, audits = [], {}
    with tempfile.TemporaryDirectory(prefix="daniel-live-") as temporary:
        base = Path(temporary)
        for cell in protocol["batches"][BATCH]["cells"]:
            case_id, condition = cell["case_id"], cell["condition"]
            case, cond = protocol["cases"][case_id], protocol["conditions"][condition]
            limits = cond["limits"]
            run_id = f"{case_id}-{condition}-r{cell['repetition']}"
            requests: list[dict] = []
            peak = {"tokens": 0}
            original_generate, original_reserve = gateway.BudgetedChatModel._generate, gateway.BudgetLedger.reserve

            def observed(model, messages, *args, **kwargs):
                requests.append({"actor": model.role, "tools": _tool_names(model.bound), "messages": _rows(messages)})
                return original_generate(model, messages, *args, **kwargs)

            def reserving(ledger, role, input_tokens=0):
                peak["tokens"] = max(peak["tokens"], int(input_tokens))
                return original_reserve(ledger, role, input_tokens)

            # The row exists before anything can fail, so a cell that cannot even be imported is still a row.
            # Its evidence identity is the protocol's, which the preflight measured for every cell of the batch.
            record = {
                **cell, "run_id": run_id, "execution_id": case_id, "root_execution_id": case_id,
                "parent_execution_id": None, "world_seed": None, "evidence_sha256": case["raw_bundle_sha256"],
                "manifest_sha256": case["capture_manifest_sha256"], "tape_sha256": None, "permission": "fixed_snapshot",
                "provenance": {"evidence": pre["evidence"][case_id]["evidence_origin"], "inference": "LIVE_MODEL",
                               "execution": "FIXED_SNAPSHOT", "model": settings.lead_model, "source_run_id": None,
                               "fault_policy": None},
                "versions": {**pins, "scorer": protocol["versions"]["scorer"]}, "allowed": limits,
                "started_at": now(), "status": "completed", "stop_reason": None, "report": None, "score": None,
            }
            clock = time.perf_counter()
            usage, paths = None, None
            try:
                source = ROOT / case["evidence_path"]
                # A cheap second look. The preflight compared every cell's evidence with the protocol before the
                # first model call; this only catches a fixture that changed since, and it fails this cell alone.
                require(digest((source / "capture.json").read_bytes()) == case["capture_manifest_sha256"],
                        "the capture manifest changed after the preflight")
                paths = episode_paths(run_id.lower(), base / "runs", base / "sealed")
                manifest = import_bundle(source, paths)
                require(manifest.raw_bundle_sha256 == case["raw_bundle_sha256"], "the evidence changed after the preflight")
                caps = replace(settings.caps, max_calls=limits["calls"], max_input_tokens=limits["tokens_in"],
                               max_output_tokens=limits["tokens_out"], max_seconds=float(limits["seconds"]),
                               max_input_tokens_per_call=limits["peak_input_tokens"])
                cell_settings = replace(settings, caps=caps, runs_dir=base / "runs", sealed_dir=base / "sealed")
                record["started_at"], clock = now(), time.perf_counter()  # the run itself is timed from here
                with EvidenceStore(paths.db) as store:
                    runner = get_runner("agent-live", cell_settings, cond["mode"])
                    context = RunContext(case_id=paths.episode_id, store=store, manifest=manifest, case_dir=paths.case,
                                         settings=cell_settings, emit=lambda *args: None, pace_s=0)
                    with patch.object(gateway.BudgetedChatModel, "_generate", observed), \
                            patch.object(gateway.BudgetLedger, "reserve", reserving):
                        report = runner.run(context)
                    usage = report.usage
                    stop = next((q for q in report.open_questions if q.startswith("Incomplete run:")), None)
                    report = verify_report(report, store, manifest)
                    report = lock_report(report, "skipped_for_benchmark", by_human=False)
                    evidence_ids = {event.id for event in store.scan()}
                payload = report.model_dump(mode="json")
                filename = f"reports/{run_id}.json"
                locked = canonical(payload)
                with (output / filename).open("xb") as stream:
                    stream.write(locked)
                (output / filename).chmod(0o444)
                # Scorer-only fixture access starts after durable report creation.
                record["score"] = score_fixture(payload, case_id, protocol)
                record["report"] = {"path": filename, "sha256": digest(locked), "locked_at": report.locked_at.isoformat(),
                                    "scored_at": now()}
                record["stop_reason"], record["status"] = stop, _status_for(stop)
                audits[run_id] = audit_requests(requests, evidence_ids, ["daniel-private-canary-7219"])
            except gateway.ModelRefused as exc:
                record.update(status="refused", stop_reason=f"ModelRefused: {exc}", score=None, report=None)
            except Exception as exc:  # noqa: BLE001 - a cell that cannot be imported or run is an outcome, not a gap
                record.update(status="failed", stop_reason=f"{type(exc).__name__}: {str(exc)[:300]}", score=None, report=None)
            elapsed = time.perf_counter() - clock
            if usage is None:  # the cell raised: read what its own ledger counted, if it got as far as having one
                saved = paths.case / "budget.json" if paths is not None else None
                state = json.loads(saved.read_text()) if saved is not None and saved.exists() else {}
                used = {"calls": int(state.get("llm_calls", 0)), "actions": int(state.get("tool_calls", 0)),
                        "tokens_in": int(state.get("tokens_in", 0)), "tokens_out": int(state.get("tokens_out", 0)),
                        "cost_usd": float(state.get("cost_usd", 0.0))}
            else:
                used = {"calls": usage.llm_calls, "actions": usage.tool_calls, "tokens_in": usage.tokens_in,
                        "tokens_out": usage.tokens_out, "cost_usd": usage.cost_estimate_usd}
            record["used"] = {**used, "peak_input_tokens": min(peak["tokens"], used["tokens_in"]), "seconds": elapsed}
            record["cumulative_cost_usd"] = gateway.global_spend_for(settings).snapshot()["spent_usd"]
            record["ended_at"] = now()
            inputs = canonical(requests)
            (output / "investigator-inputs" / f"{run_id}.json").write_bytes(inputs)
            if run_id in audits:
                audits[run_id]["payload_sha256"] = digest(inputs)
                audits[run_id]["requests"] = len(requests)
            runs.append(record)
            # Preserve every terminal outcome as it occurs, even if a later cell crashes.
            with (output / "outcomes.jsonl").open("a") as stream:
                stream.write(json.dumps(record, allow_nan=False) + "\n")
            score = record["score"] or {}
            print(f"{run_id}: {record['status']} · {used['calls']} of {limits['calls']} request(s) · supported "
                  f"{score.get('supported_effects')}/{score.get('observable_effects')} · false accepted "
                  f"{score.get('false_accepted_allegations')} · ${used['cost_usd']:.4f}", flush=True)
    (output / "input-audit.json").write_bytes(canonical({"provenance": "LIVE_MODEL", "runs": audits}))
    doc = {"format": "daniel-worker-results/1", "protocol_commit": committed,
           "protocol_sha256": digest(PROTOCOL.read_bytes()), "batch_id": BATCH, "runs": runs}
    (output / "results.json").write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n")
    summary = validate(Results.model_validate(doc), output)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (output / "summary.md").write_text(markdown(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="run the preflight only: no model call")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    protocol = read_protocol()
    if args.check or not args.run:
        print(json.dumps(preflight(protocol, load_settings()), indent=2))
        return 0
    output = args.output or ROOT / protocol["outputs"]["live"]
    print(markdown(run_batch(output)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
