"""ALIBI command line. `uv run alibi --help`."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from alibi.config import ConfigError, load_settings


def _cmd_runtime(args: argparse.Namespace) -> int:
    settings = load_settings()
    print(json.dumps(settings.public_dict(), indent=2))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import socket

    import uvicorn

    from alibi.api.app import create_app

    settings = load_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex((host, port)) == 0:
            print(
                f"error: {host}:{port} is already in use. Stop the other process or run "
                f"`uv run alibi serve --port <free port>`.",
                file=sys.stderr,
            )
            return 2
    print(f"ALIBI case board: http://{host}:{port}  (runtime mode: {settings.runtime_mode})")
    uvicorn.run(create_app(settings), host=host, port=port, log_level="warning")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    from alibi.episode import create_episode, load_manifest

    settings = load_settings()
    paths = create_episode(seed=args.seed, variant=args.variant, runs_dir=settings.runs_dir,
                           sealed_dir=settings.sealed_dir, episode_id=args.episode_id)
    manifest = load_manifest(paths)
    print(json.dumps({
        "episode_id": paths.episode_id,
        "bundle_id": manifest.bundle_id,
        "evidence_origin": manifest.evidence_origin,
        "raw_bundle_sha256": manifest.raw_bundle_sha256,
        "derived_db_sha256": manifest.derived_db_sha256,
        "events": manifest.event_count,
        "artifacts": len(manifest.sources),
        "normalization_errors": len(manifest.normalization_errors),
        "evidence_dir": str(paths.evidence),
        "sealed_answer_key": str(paths.answer_key) + "  (sealed: never given to an investigator)",
    }, indent=2))
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    from alibi.episode import episode_paths, reproduce_raw_hash, verify_raw_integrity

    settings = load_settings()
    paths = episode_paths(args.episode_id, settings.runs_dir, settings.sealed_dir)
    problems = verify_raw_integrity(paths)
    saved, again = reproduce_raw_hash(paths)
    ok = not problems and saved == again
    print(json.dumps({
        "episode_id": args.episode_id,
        "frozen_bundle_intact": not problems,
        "integrity_problems": problems,
        "saved_raw_bundle_sha256": saved,
        "reproduced_raw_bundle_sha256": again,
        "reproducible_from_saved_scenario": saved == again,
    }, indent=2))
    return 0 if ok else 1


def _cmd_steps(args: argparse.Namespace) -> int:
    from alibi.episode import episode_paths, load_answer_key

    settings = load_settings()
    key = load_answer_key(episode_paths(args.episode_id, settings.runs_dir, settings.sealed_dir))
    print("SEALED ANSWER KEY (operator/audience view; never shown to an investigator)")
    for s in key.steps:
        print(f"  {s.step_id} {s.t_start:%H:%M:%S} {s.step_name:<17} {s.execution_status:<9} {s.outcome}")
    print(f"  scorable effects: {[e.effect_type for e in key.effects]}")
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    from alibi import bench

    if args.write_config:
        print(f"refused: {bench.V1_FROZEN_NOTE}", file=sys.stderr)
        return 2
    problems = bench.check_config()
    if problems:
        for line in problems:
            print(f"error: {line}", file=sys.stderr)
        print("The evaluation configuration is frozen. Changing rules means bumping a version and declaring a "
              "fresh test split (uv run alibi bench --write-config).", file=sys.stderr)
        return 1
    if args.check:
        print("the first-run declaration is intact: docs/evaluation-config.json")
        return 0
    if bench.RESULTS_PATH.exists():
        print(f"refused: {bench.V1_FROZEN_NOTE}", file=sys.stderr)
        return 2
    settings = load_settings()
    doc = bench.run_offline_suite(settings)
    bench.write_outputs(doc)
    print(f"suite {doc['suite']} run {doc['run_id']} commit {doc['git_commit']} · model calls made: 0")
    for s in doc["systems"]:
        a = s["aggregate"]
        if not a:
            print(f"  {s['id']:<6} {s['status_detail']}")
            continue
        r = lambda x: "N/A" if not x["den"] else f"{x['num']}/{x['den']}"  # noqa: E731
        print(f"  {s['id']:<6} cases {s['completed']}/{s['n_cases']} · effects caught {r(a['step_recall'])} · "
              f"final precision {r(a['final_precision'])} · raw precision {r(a['proposal_precision'])} · "
              f"cover-ups {r(a['coverup_detected'])} · account {r(a['account_identification'])} · "
              f"benign false alerts {r(a['benign_false_alert'])} · benign raw alerts {r(a['benign_raw_alert'])}")
    print("wrote benchmarks/offline-v1/results.json and docs/benchmark.md")
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    """Run one preset with the offline fixture runner and save it as a replayable recording."""
    import tempfile
    import time
    from dataclasses import replace
    from pathlib import Path

    from alibi.orchestrator import Orchestrator

    settings = load_settings()
    with tempfile.TemporaryDirectory(prefix="alibi-record-") as tmp:
        orch = Orchestrator(replace(settings, runs_dir=Path(tmp) / "runs", sealed_dir=Path(tmp) / "sealed"), pace_s=0.0)
        rec = orch.create_case(preset_id=args.preset, runner_id=args.runner, investigation_mode=args.mode)
        orch.start_investigation(rec.case_id)
        deadline = time.time() + max(60.0, settings.caps.max_seconds + 60.0)  # a real model sets its own pace
        while time.time() < deadline:
            state = orch.record(rec.case_id).state
            if state in ("awaiting_review", "failed", "cancelled"):
                break
            time.sleep(0.05)
        if state != "awaiting_review":
            print(f"error: the run ended in state {state}: {orch.record(rec.case_id).error}", file=sys.stderr)
            return 1
        asked = []
        for n, text in enumerate(args.question or []):  # answers are saved with the recording and replay as recorded
            q = orch.ask_question(rec.case_id, text, f"record-{n}")
            end = time.time() + 120
            while q.status == "pending" and time.time() < end:
                time.sleep(0.2)
                q = orch.get_question(rec.case_id, q.question_id)
            asked.append(f"{q.status} ({q.usage.llm_calls} model call(s))")
        out = orch.save_recording(rec.case_id, args.name, note=args.note)
        done = orch.record(rec.case_id)
        mode, how = done.inference_mode, done.investigation_mode or "no agent"
    print(f"saved {out}  (inference: {mode}; mode: {how}; replay it from the case board start screen or "
          f"POST /api/replays/{args.name}/open)" + (f"\nquestions: {', '.join(asked)}" if asked else ""))
    return 0


def _cmd_smoke(args: argparse.Namespace) -> int:
    """One tiny real model call through the budget gateway: does this runtime do tool calling at all?"""
    from langchain_core.tools import tool

    from alibi.agents import gateway
    from alibi.config import RunCaps

    settings = load_settings()
    reason = settings.live_block_reason()
    if reason is not None:
        print(f"live inference: BLOCKED\n  {reason}\nNo model call was made. See BLOCKERS.md B-1.")
        return 2

    @tool
    def ping(value: int) -> str:
        """Echo an integer back."""
        return f"pong {value}"

    ledger = gateway.make_ledger(settings, None, scripted=False, label="smoke",
                                 caps=RunCaps(max_calls=2, max_input_tokens=3000, max_output_tokens=600, max_seconds=60,
                                              max_input_tokens_per_call=2000))
    inner = gateway.live_chat_model(settings, settings.lead_model or "", ledger.max_tokens_per_call)
    model = gateway.wrap(inner, ledger, "smoke").bind_tools([ping])
    prompt = "Call the tool `ping` with value 7. Do not answer in text."
    if args.count_only:
        # Token counting is a separate, unbilled endpoint. This proves the request can be measured before
        # anything is sent, without making a model call.
        from langchain_core.messages import HumanMessage

        try:
            counted, method = gateway.count_request_tokens(inner, model.bound, [HumanMessage(prompt)])
        except gateway.CountFailed as exc:
            print(f"the request could not be counted, so nothing would be sent: {exc}")
            return 1
        print(json.dumps({"model_requested": settings.lead_model, "counted_input_tokens_with_headroom": counted,
                          "method": method, "model_call_made": False}, indent=2))
        return 0
    try:
        reply = model.invoke(prompt)
    except gateway.ModelRefused as exc:
        print(f"the model declined the smoke request: {exc}")
        return 1
    except gateway.BudgetExceeded as exc:
        print(f"stopped by the budget gateway before or during the call: {exc}")
        return 1
    calls = getattr(reply, "tool_calls", [])
    ok = any(c["name"] == "ping" and c["args"].get("value") == 7 for c in calls)
    spend = gateway.global_spend_for(settings)
    print(json.dumps({"model_requested": settings.lead_model, "model_served": ledger.state["models"],
                      "tool_call_ok": ok, "tool_calls": [{"name": c["name"], "args": c["args"]} for c in calls],
                      "stop_reason": (reply.response_metadata or {}).get("stop_reason"),
                      "usage": ledger.usage().model_dump(), "cache_write_tokens": ledger.state["tokens_cache_write"],
                      "total_spend": spend.snapshot() if spend else None}, indent=2, default=str))
    return 0 if ok else 1


def _cmd_spend(args: argparse.Namespace) -> int:
    """Show the cumulative spend ledger; optionally reconcile one amount whose billing outcome was unknown."""
    from alibi.agents import gateway

    settings = load_settings()
    spend = gateway.global_spend_for(settings)
    if spend is None:
        print(json.dumps({"total_spend": None, "note": "no billed route is configured; nothing can be spent"}, indent=2))
        return 0
    try:
        if args.reconcile:
            # Operator action: after checking the provider console, state what a held amount really cost.
            # This is the only way an unknown outcome or an abandoned reservation leaves the books.
            if args.actual is None:
                print("--reconcile needs --actual <usd>: the amount the provider console shows for that call "
                      "(0 if it was not billed)", file=sys.stderr)
                return 2
            done = spend.reconcile(args.reconcile, args.actual, note=args.note or "operator reconciliation")
            print(json.dumps({"reconciled": done}, indent=2))
        print(json.dumps(spend.snapshot(), indent=2))
    except (KeyError, ValueError) as exc:
        print(f"not reconciled: {exc}", file=sys.stderr)
        return 2
    except gateway.LedgerError as exc:
        print(f"the spend ledger cannot be used, so no model call will be made: {exc}"
              + (f"\n  file: {exc.path}" if exc.path else ""), file=sys.stderr)
        return 1
    return 0


def _cmd_calibrate(args: argparse.Namespace) -> int:
    """Run the configured model on a development incident and a benign control (see alibi/calibration.py)."""
    from alibi import calibration
    from alibi.runners import RuntimeBlocked

    settings = load_settings()
    try:
        doc = calibration.run_calibration(settings, mode=args.mode, runner_id=args.runner)
    except RuntimeBlocked as exc:
        print(f"{exc}\nNo model call was made.", file=sys.stderr)
        return 2
    for row in doc["cases"]:
        u = row.get("usage") or {}
        print(f"{row['ref']:13} {row['status']:10} checks={row['checks']} calls={u.get('llm_calls')} "
              f"in={u.get('tokens_in')} out={u.get('tokens_out')} cost=${u.get('cost_estimate_usd')} "
              f"wall={u.get('wall_seconds')}s" + (f"  error: {row['error']}" if row.get("error") else ""))
    print(f"model {doc['model_requested']} · mode {doc['mode']} · passed: {doc['passed']} · "
          f"estimated cost ${doc['estimated_cost_usd']} · results in {doc['result_dir']}")
    return 0 if doc["passed"] else 1


def _orchestrator() -> Any:
    from alibi.orchestrator import Orchestrator

    return Orchestrator(load_settings(), pace_s=0.0)


def _cmd_cases(args: argparse.Namespace) -> int:
    """List the cases in the runs directory (the same ones the case board shows)."""
    for c in _orchestrator().list_cases():
        print(f"{c['case_id']}  {c['state']:<16} {c['labels']['inference_label']:<40} {c['title']}")
    return 0


def _investigate_to_review(orch: Any, case_id: str, resume: bool = False, extra_requests: int | None = None) -> int:
    """Investigate a frozen case and stop at human review. Prints the drafted findings; 1 if it did not get there.

    With resume, an interrupted investigation is continued from its checkpoint instead."""
    import time

    if resume:
        orch.resume_investigation(case_id, extra_requests)
    else:
        orch.start_investigation(case_id)
    deadline = time.time() + max(60.0, load_settings().caps.max_seconds + 60.0)
    state = orch.record(case_id).state
    while time.time() < deadline:
        state = orch.record(case_id).state
        if state in ("awaiting_review", "failed", "cancelled"):
            break
        time.sleep(0.1)
    done = orch.record(case_id)
    print(f"case {case_id}: {done.title} · {done.labels_text()} · state {state}")
    if state != "awaiting_review":
        print(f"error: {done.error}", file=sys.stderr)
        return 1
    report = orch.view(case_id)["report"]
    for f in report["findings"]:
        print(f"  {f['category']:<22} {f['claim_type']:<28} {f['host']:<12} {f['status']}")
    stopped = next((q for q in report["open_questions"] if q.startswith("Incomplete run:")), None)
    if stopped:
        print(f"  {stopped} Continue it with: alibi investigate {case_id} --resume")
    if not report["findings"]:
        print("  no findings were recorded before it stopped" if stopped else
              "  no findings: nothing in this evidence is reported as an incident")
    print(f"  account: {report['attribution']['account_used']} · person: {report['attribution']['human_identity'].replace('_', ' ')}")
    print(f"next: alibi ask {case_id} \"...\" · alibi experiment {case_id} --without collector · "
          f"alibi review {case_id} accept")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Create a case from a preset in the runs directory, investigate it and stop at human review."""
    orch = _orchestrator()
    rec = orch.create_case(preset_id=args.preset, runner_id=args.runner, investigation_mode=args.mode)
    return _investigate_to_review(orch, rec.case_id)


def _cmd_investigate(args: argparse.Namespace) -> int:
    """Investigate a case that is already frozen (an imported capture, for example) and stop at human review."""
    return _investigate_to_review(_orchestrator(), args.case_id, resume=args.resume, extra_requests=args.extra_requests)


def _wait_for_review(orch: Any, case_id: str) -> str:
    import time

    deadline = time.time() + max(60.0, load_settings().caps.max_seconds + 60.0)
    state = orch.record(case_id).state
    while time.time() < deadline:
        state = orch.record(case_id).state
        if state in ("awaiting_review", "failed", "cancelled"):
            break
        time.sleep(0.1)
    return state


def _lab_row(row: dict[str, Any]) -> str:
    cond, used, scored = row["conditions"], row["used"] or {}, row["scored"] or {}
    est = (scored.get("effects_established") or {})
    what = "first run" if row["is_root"] else f"{row['lineage']['comparison']}: " + ", ".join(
        f"{k} {v['from']} -> {v['to']}" for k, v in (row["lineage"]["changed"] or {}).items())
    return (f"{row['case_id']}  {row['bundle_id']}  {what:<52} allowed {cond['investigator_requests']:>2} "
            f"used {str(used.get('llm_calls', '-')):>2}  {row['outcome']:<16} "
            f"accepted allegations {(row['findings'] or {}).get('incident_allegations_accepted', '-')}"
            + (f"  established {est.get('num')}/{est.get('den')}" if est.get("den") else ""))


def _cmd_lab(args: argparse.Namespace) -> int:
    """The worker lab from a terminal: run an experiment, read the operator's record, compare runs."""
    import tempfile
    import time
    import uuid
    from dataclasses import replace
    from pathlib import Path

    from alibi.orchestrator import Orchestrator

    if args.lab_cmd == "options":
        print(json.dumps(_orchestrator().lab_options(), indent=2))
        return 0
    if args.lab_cmd == "operator":
        rec = _orchestrator().lab_operator(args.case_id)
        tr = rec["transition"]
        print(rec["label"])
        print("objective changed: " + (f"worker {tr['worker']} at tick {tr['tick']} ({tr['t']}), permissions {tr['permissions']}, "
                                       f"policy {tr['policy_version']}" if tr else "no worker's objective was changed"))
        for r in rec["records"]:
            print(f"  {r['seq']:>3} tick {r['tick']:<2} {r['worker']} {r['objective']:<7} {r['action']:<21} "
                  f"{str(r['target'] or ''):<12} {r['status']:<9} {r['outcome']}")
        return 0
    if args.lab_cmd == "table":
        table = _orchestrator().lab_comparisons(args.case_id)
        for row in table["runs"]:
            print(_lab_row(row))
        print(table["note"])
        return 0
    if args.lab_cmd == "compare":
        orch = _orchestrator()
        rec = orch.lab_compare(args.case_id, kind=args.kind, investigator_requests=args.investigator_requests,
                               rogue_permissions=args.permissions, client_token=f"cli-{uuid.uuid4().hex[:10]}",
                               runner_id=args.runner, investigation_mode=args.mode)
        lin = rec.lab["lineage"]
        print(f"case {rec.case_id}: {lin['comparison']} · {lin['note']} · same evidence as the first run: {lin['same_evidence_as_parent']}")
        return _investigate_to_review(orch, rec.case_id) if args.investigate else 0
    # run
    settings = load_settings()
    if args.save_as:  # checked before anything is run or billed
        from alibi.episode import validate_episode_id
        from alibi.orchestrator import REPLAY_DIR

        validate_episode_id(args.save_as)
        if (REPLAY_DIR / args.save_as).exists():
            print(f"error: a recording named {args.save_as} already exists; choose another name", file=sys.stderr)
            return 1
    holder = tempfile.TemporaryDirectory(prefix="alibi-lab-record-") if args.save_as else None
    try:
        if holder:  # a recording is made beside the real case list, not in it
            settings = replace(settings, runs_dir=Path(holder.name) / "runs", sealed_dir=Path(holder.name) / "sealed")
        orch = Orchestrator(settings, pace_s=0.0)
        rec = orch.create_lab_case(
            variant=args.variant, seed=args.seed, preset=args.preset, rogue_permissions=args.permissions,
            rogue_requests=args.rogue_requests, investigator_requests=args.investigator_requests,
            context_load=args.context_load, ordinary_work=args.work, runner_id=args.runner, investigation_mode=args.mode,
            client_token=f"cli-{uuid.uuid4().hex[:10]}")
        cond, prov = rec.lab["conditions"], rec.lab["provenance"]
        print(f"case {rec.case_id}: {rec.title} · {cond['preset_label']} · changed worker {cond['rogue_requests']} request(s), "
              f"investigator {cond['investigator_requests']} · permissions {cond['rogue_permissions']} · context {cond['context_load']}")
        print(f"  {prov['ordinary_work_label']}")  # how many requests they made is shown once the report is locked
        print(f"  {prov['changed_objective_label']}")
        if not (args.investigate or args.save_as):
            print(f"next: alibi investigate {rec.case_id}")
            return 0
        code = _investigate_to_review(orch, rec.case_id)
        if code or not args.save_as:
            return code
        asked = []
        for n, text in enumerate(args.question or []):
            q = orch.ask_question(rec.case_id, text, f"record-{n}")
            end = time.time() + 120
            while q.status == "pending" and time.time() < end:
                time.sleep(0.2)
                q = orch.get_question(rec.case_id, q.question_id)
            asked.append(f"{q.status} ({q.usage.llm_calls} model call(s))")
        out = orch.save_recording(rec.case_id, args.save_as, note=args.note)
        print(f"saved {out}" + (f"\nquestions: {', '.join(asked)}" if asked else ""))
        return 0
    finally:
        if holder:
            holder.cleanup()


def _cmd_trace(args: argparse.Namespace) -> int:
    """What the recorded investigation of a case did: plan, delegations, plan changes, case-file use."""
    tr = _orchestrator().investigation_trace(args.case_id)
    if args.json:
        print(json.dumps(tr, indent=2))
        return 0
    b = tr["behaviors"]
    print(f"case {args.case_id} · {tr['labels']['inference_label']} · {tr['labels']['investigation_mode_label']}")
    first = {True: "yes", False: "no", None: "not applicable (no plan, or nothing examined)"}[b["plan_recorded_before_first_examination"]]
    print(f"plan recorded before the first examination: {first} · plan written by {tr['plan_written_by']}")
    for d in b["delegations"]:
        how = " (closed by a finish event that names no agent)" if d.get("closed_by") else ""
        print(f"delegated to {d['to']}: {d['tool_calls']} tool call(s), {d['status']}{how} · {str(d['result_summary'] or '')[:80]}")
    for r in b["plan_revisions"]:
        after = r["after"] or {}
        print(f"plan changed at event {r['seq']} (after event {after.get('seq')}: {after.get('what')}):")
        for item in r["added_new"]:
            print(f"    + {item}")
        for pair in r["reworded"]:
            print(f"    ~ reworded: {pair['to']}")
    cf = b["case_file"]
    print(f"case file: {cf['writes']} write(s), {cf['reads_after_a_write']} read(s) after a write · {', '.join(cf['paths']) or 'none'}")
    print(f"resumed: {b['resumed']['times']} time(s), {b['resumed']['tool_calls_after_resume']} tool call(s) afterwards")
    print(tr["note"])
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    """Record the human decision on a drafted report. Either decision locks the report as proposed."""
    view = _orchestrator().review(args.case_id, args.decision, args.note)
    print(f"case {args.case_id}: report {view['case']['review_decision']} and locked · sha256 {view['report']['report_sha256']}")
    print(f"next: alibi export {args.case_id}")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    """Ask one question about a case and print the answer with what trusted code made of each claim."""
    import time
    import uuid

    orch = _orchestrator()
    q = orch.ask_question(args.case_id, args.question, args.token or f"cli-{uuid.uuid4().hex[:10]}")
    end = time.time() + 120
    while q.status == "pending" and time.time() < end:
        time.sleep(0.2)
        q = orch.get_question(args.case_id, q.question_id)
    print(f"[{q.inference_label}{' · ' + q.model_id if q.model_id else ''}] status: {q.status}"
          + (f" · {q.usage.llm_calls} model call(s), est. ${q.usage.cost_estimate_usd:.4f}" if q.usage.llm_calls else ""))
    if q.error:
        print(f"note: {q.error}")
    if q.answer:
        print("\n" + q.answer + "\n")
    for c in q.claims:
        print(f"  {c.support.upper():<14} {c.text}\n{'':17}{c.basis}  [{', '.join(c.evidence_ids[:4]) or 'no citation'}]")
    for line in q.limitations:
        print(f"  limit: {line}")
    for line in q.follow_up_evidence:
        print(f"  would settle it: {line}")
    return 0 if q.status in ("answered", "insufficient_evidence") else 1


def _cmd_experiment(args: argparse.Namespace) -> int:
    """Derive a view of a case without the named kinds of source and print what the original claims are worth there."""
    import uuid

    orch = _orchestrator()
    sources = orch.source_experiment(args.case_id).get("sources")
    if sources is None:
        print("error: run the experiment from the original case, not from a derived view", file=sys.stderr)
        return 1
    wanted = {k.strip() for k in args.without.split(",") if k.strip()}
    ids = [s["source_id"] for s in sources if s["source"] in wanted or s["source_id"] in wanted]
    if not ids:
        print(f"error: no source of kind {sorted(wanted)}. This case has: {sorted({s['source'] for s in sources})}", file=sys.stderr)
        return 1
    child = orch.create_source_experiment(args.case_id, ids, f"cli-{uuid.uuid4().hex[:10]}", runner_id=args.runner,
                                          investigation_mode=args.mode)
    exp = orch.source_experiment(child.case_id)
    cmp_ = exp["comparison"]
    print(f"derived case {child.case_id}: {child.title}")
    print(f"withheld: {', '.join(s['artifact'] for s in exp['excluded_sources'])}")
    print(f"events: {exp['events_original']} -> {exp['events_remaining']}\n")
    if not cmp_["claims"]:
        print(cmp_.get("note", "the original case has no report to compare"))
    for row in cmp_["claims"]:
        mark = {"retains_support": "STILL SUPPORTED", "loses_support": "CANNOT BE ESTABLISHED", "never_supported": "was not supported"}[row["change"]]
        print(f"  {mark:<22} {row['claim_type']} on {row['host']} ({row['object_or_session']})\n{'':25}{row['reason']}")
    if cmp_.get("attribution"):
        a = cmp_["attribution"]
        print(f"\n  account and person: {a['change']} ({a['parent_observation']} -> {a['child_observation']})")
    for line in cmp_["coverage"]["child"]["limits"]:
        print(f"  coverage limit: {line}")
    print("\nA claim that cannot be established here is unknown in this view. It is not shown to be false.")
    print(f"To investigate the derived view: alibi investigate {child.case_id}, or open it in the case board.")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    """Print the locked report of a case as markdown, or its machine-readable manifest."""
    from alibi import export

    doc = _orchestrator().report_export(args.case_id)
    print(json.dumps(doc, indent=2) if args.json else export.render_markdown(doc))
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    """Freeze a capture directory (capture.json + its raw files) as an unscored case."""
    from alibi.orchestrator import Orchestrator

    orch = Orchestrator(load_settings(), pace_s=0.0)
    rec = orch.import_case(args.directory, title=args.title, runner_id=args.runner, investigation_mode=args.mode)
    view = orch.view(rec.case_id)
    print(json.dumps({"case_id": rec.case_id, "state": rec.state, "bundle_id": rec.bundle_id,
                      "evidence_origin": rec.evidence_origin, "scored": rec.scored,
                      "sources": [{"artifact": s["artifact"], "origin": s["origin"], "lines": s["line_count"]}
                                  for s in view["manifest"]["sources"]],
                      "events": view["manifest"]["event_count"],
                      "unparsed_or_errors": len(view["manifest"]["normalization_errors"]),
                      "next": f"alibi investigate {rec.case_id}, or open it in the case board"}, indent=2))
    return _investigate_to_review(orch, rec.case_id) if args.investigate else 0


def _eval_report(evaluation: Any, suite: str, doc: dict[str, Any]) -> str:
    """A suite's report. A repeat is reported beside the run it repeats, cell by cell."""
    original = evaluation.SUITES[suite].get("repeat_of")
    first = evaluation.latest(suite=original) if original else None
    return evaluation.render_repeat(first, doc) if first else evaluation.render_markdown(doc)


def _cmd_eval(args: argparse.Namespace) -> int:
    """The phase-two paired evaluation: declare, check, preflight (none of which call a model) or run."""
    from alibi import evaluation
    from alibi.runners import RuntimeBlocked

    settings = load_settings()
    suite = args.suite
    spec = evaluation.SUITES[suite]
    try:
        if args.declare:
            print(f"declared: {evaluation.declare(suite)}")
            return 0
        if args.check:
            problems = evaluation.check_config(suite)
            for line in problems:
                print(f"error: {line}", file=sys.stderr)
            print("the declaration matches the code" if not problems else "the declaration and the code disagree")
            return 1 if problems else 0
        if args.preflight:
            cells = len(spec["cases"]) * len(evaluation.AI_ARMS)
            print(json.dumps(evaluation.preflight(settings, cells, spec["ceiling"]), indent=2))
            return 0
        if args.render:  # regenerate a suite's report from its saved results; reads only, no model call
            doc = evaluation.latest(suite=suite)
            if doc is None:
                print(f"{suite} has no results yet", file=sys.stderr)
                return 1
            name = "evaluation-v2.md" if suite == evaluation.SUITE else f"evaluation-{suite.replace('paired-', '')}.md"
            evaluation.REPORT_MD.with_name(name).write_text(_eval_report(evaluation, suite, doc), encoding="utf-8")
            print(f"wrote docs/{name} from {suite} run {doc['run_id']}")
            return 0
        if args.summary:
            docs = [d for d in (evaluation.latest(suite=name) for name in evaluation.summed_suites()) if d]
            out = evaluation.REPORT_MD.with_name("evaluation-summary.md")
            out.write_text(evaluation.render_combined(docs, (evaluation.summary() or {}).get("repeats")), encoding="utf-8")
            print(f"wrote {out}")
            return 0
        if args.dev_check:
            doc = evaluation.run(settings, cases=evaluation.DEV_CASES, suite="paired-v2-dev", ceiling_usd=0.25)
        elif args.run:
            doc = evaluation.run(settings, suite=suite)
            name = "evaluation-v2.md" if suite == evaluation.SUITE else f"evaluation-{suite.replace('paired-', '')}.md"
            evaluation.REPORT_MD.with_name(name).write_text(_eval_report(evaluation, suite, doc), encoding="utf-8")
        else:
            print("choose one of --declare, --check, --preflight, --dev-check, --run, --summary", file=sys.stderr)
            return 2
    except RuntimeBlocked as exc:
        print(f"{exc}\nNo model call was made.", file=sys.stderr)
        return 2
    for r in doc["runs"]:
        s = r["score"] or {}
        rec = s.get("step_recall") or {}
        u = s.get("usage") or {}
        print(f"  {r['case_ref']} {r['system_id']:<6} {r['status']:<10} effects {rec.get('num')}/{rec.get('den')} "
              f"accepted {s.get('final_accepted_incident')} raw {s.get('proposals_incident')} calls {u.get('llm_calls')} "
              f"cost ${u.get('cost_estimate_usd')}" + (f"  [{r['stop_note'] or r['error']}]" if r.get("stop_note") or r.get("error") else ""))
    print(f"suite {doc['suite']} run {doc['run_id']} · estimated cost ${doc['spend']['estimated_cost_usd']} · {doc['result_dir']}")
    return 0


def _cmd_pilot(args: argparse.Namespace) -> int:
    from alibi import bench
    from alibi.runners import RuntimeBlocked

    if (bench.PILOT_DIR / "results.json").exists():
        print(f"refused: {bench.V1_FROZEN_NOTE}\nNo model call was made.", file=sys.stderr)
        return 2
    settings = load_settings()
    try:
        doc = bench.run_ai_pilot(settings)
    except RuntimeBlocked as exc:
        print(f"{exc}\nNo model call was made.", file=sys.stderr)
        return 2
    out = bench.write_pilot(doc)
    bench.write_report()
    for s in doc["systems"]:
        a = s["aggregate"]
        print(f"  {s['id']:<6} completed {s['completed']}/{s['n_cases']} errors {s['errors']} censored {s['censored']} "
              + (f"effects caught {a['step_recall']['num']}/{a['step_recall']['den']} model calls {a['llm_calls']} "
                 f"tokens {a['tokens_in']}/{a['tokens_out']}" if a else s["status_detail"]))
    print(f"wrote {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alibi", description="ALIBI forensic proving ground")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("runtime", help="print the runtime mode, caps and live-inference blocker")
    p.set_defaults(func=_cmd_runtime)

    p = sub.add_parser("generate", help="simulate, freeze, normalize and seal one episode")
    p.add_argument("--seed", type=int, required=True)
    from alibi.sim.scenario import ALL_VARIANTS

    p.add_argument("--variant", default="incident_coverup", choices=list(ALL_VARIANTS),
                   help="scenario variant (inside job, records heist, cold chain and their benign controls)")
    p.add_argument("--episode-id", default=None)
    p.set_defaults(func=_cmd_generate)

    p = sub.add_parser("verify", help="re-hash a frozen bundle and reproduce it from the saved scenario")
    p.add_argument("episode_id")
    p.set_defaults(func=_cmd_verify)

    p = sub.add_parser("steps", help="print the sealed executed-step record of an episode (operator only)")
    p.add_argument("episode_id")
    p.set_defaults(func=_cmd_steps)

    p = sub.add_parser("record", help="run a preset and save it under demo/replays/<name> for offline replay")
    p.add_argument("--preset", default="hero-coverup")
    p.add_argument("--name", required=True, help="recording id, e.g. hero-coverup-fixture")
    p.add_argument("--runner", default=None, help="deterministic | agent-fixture | agent-live (default: runtime default)")
    p.add_argument("--mode", default=None, choices=["fast", "specialist"],
                   help="fast = one agent, specialist = lead + auditor + skeptic (default: fast for a live model)")
    p.add_argument("--note", default="")
    p.add_argument("--question", action="append", default=[],
                   help="ask this question after the investigation and save the answer with the recording (repeatable)")
    p.set_defaults(func=_cmd_record)

    p = sub.add_parser("bench", help="run the declared offline benchmark suite (B0 and BR; no model calls)")
    p.add_argument("--check", action="store_true", help="only verify that the frozen config matches the code")
    p.add_argument("--write-config", action="store_true", help="(refused: the first-run declaration is frozen)")
    p.set_defaults(func=_cmd_bench)

    p = sub.add_parser("smoke", help="one tiny real model call to test tool calling (refused while live AI is blocked)")
    p.add_argument("--count-only", action="store_true",
                   help="only count the request with the provider's unbilled token-counting endpoint; no model call")
    p.set_defaults(func=_cmd_smoke)

    p = sub.add_parser("spend", help="show the cumulative spend estimate against the cap and the development ceiling")
    p.add_argument("--reconcile", metavar="TOKEN", default=None,
                   help="operator action: settle one unreconciled or abandoned reservation at its real cost")
    p.add_argument("--actual", type=float, default=None, help="with --reconcile: the real cost in USD (0 if not billed)")
    p.add_argument("--note", default="", help="with --reconcile: why (kept in the ledger log)")
    p.set_defaults(func=_cmd_spend)

    p = sub.add_parser("calibrate", help="check the configured model on a development incident and a benign control")
    p.add_argument("--mode", default="fast", choices=["fast", "specialist"])
    p.add_argument("--runner", default="agent-live", choices=["agent-live", "agent-fixture"],
                   help="agent-fixture exercises the harness offline with the scripted policy (no model)")
    p.set_defaults(func=_cmd_calibrate)

    p = sub.add_parser("cases", help="list the cases in the runs directory")
    p.set_defaults(func=_cmd_cases)

    p = sub.add_parser("run", help="create a case from a preset, investigate it and stop at human review")
    p.add_argument("--preset", default="hero-coverup")
    p.add_argument("--runner", default=None, help="deterministic | agent-fixture | agent-live (default: runtime default)")
    p.add_argument("--mode", default=None, choices=["fast", "specialist"])
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("review", help="accept or reject a drafted report; either way it is locked as proposed")
    p.add_argument("case_id")
    p.add_argument("decision", choices=["accept", "reject"])
    p.add_argument("--note", default="")
    p.set_defaults(func=_cmd_review)

    p = sub.add_parser("ask", help="ask one question about a case; each claim is checked against the evidence")
    p.add_argument("case_id")
    p.add_argument("question")
    p.add_argument("--token", default=None, help="reuse a token to get the same answer back without a new model call")
    p.set_defaults(func=_cmd_ask)

    p = sub.add_parser("experiment", help="derive a view of a case without some sources and compare the original claims")
    p.add_argument("case_id")
    p.add_argument("--without", required=True, help="source kinds or ids, comma separated, e.g. collector or badge,flow")
    p.add_argument("--runner", default=None)
    p.add_argument("--mode", default=None, choices=["fast", "specialist"])
    p.set_defaults(func=_cmd_experiment)

    p = sub.add_parser("export", help="print a case's locked report (markdown, or --json for the manifest)")
    p.add_argument("case_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_export)

    p = sub.add_parser("import", help="freeze a capture directory (capture.json + raw files) as an unscored case")
    p.add_argument("directory")
    p.add_argument("--title", default=None)
    p.add_argument("--runner", default=None, help="deterministic | agent-fixture | agent-live (default: runtime default)")
    p.add_argument("--mode", default=None, choices=["fast", "specialist"])
    p.add_argument("--investigate", action="store_true", help="investigate it straight away and stop at human review")
    p.set_defaults(func=_cmd_import)

    p = sub.add_parser("investigate", help="investigate a case that is already frozen and stop at human review")
    p.add_argument("case_id")
    p.add_argument("--resume", action="store_true",
                   help="continue an interrupted investigation (cancelled, failed or stopped incomplete) from its checkpoint")
    p.add_argument("--extra-requests", type=int, default=None, help="with --resume: how many more model requests it may make")
    p.set_defaults(func=_cmd_investigate)

    p = sub.add_parser("trace", help="what a case's recorded investigation did: plan, delegations, plan changes, case file")
    p.add_argument("case_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_trace)

    p = sub.add_parser("lab", help="the worker lab: run an experiment, read the operator's record, compare runs")
    lsub = p.add_subparsers(dest="lab_cmd", required=True)
    q = lsub.add_parser("options", help="presets in their units, permission profiles, context loads")
    q = lsub.add_parser("run", help="run the workers once and freeze what they left as a new case")
    q.add_argument("--variant", default="incident", choices=["incident", "control"])
    q.add_argument("--seed", type=int, default=None)
    q.add_argument("--preset", default=None, choices=["offense_heavy", "balanced", "defense_heavy"])
    q.add_argument("--permissions", default=None, choices=["export_only", "export_log", "export_log_artifact"])
    q.add_argument("--rogue-requests", type=int, default=None)
    q.add_argument("--investigator-requests", type=int, default=None)
    q.add_argument("--context-load", default=None, choices=["light", "standard", "heavy"])
    q.add_argument("--work", default=None, choices=["model", "scripted"], help="who chooses the workers' ordinary actions")
    q.add_argument("--runner", default=None, choices=["deterministic", "agent-fixture", "agent-live"],
                   help="default: the runtime's default")
    q.add_argument("--mode", default=None, choices=["fast", "specialist"])
    q.add_argument("--investigate", action="store_true", help="investigate it straight away and stop at human review")
    q.add_argument("--save-as", default=None, help="investigate, then save under demo/replays/<name> for offline replay")
    q.add_argument("--note", default="")
    q.add_argument("--question", action="append", help="with --save-as: ask this and save the answer with the recording")
    q = lsub.add_parser("operator", help="every attempted action and the change of objective (after the report is locked)")
    q.add_argument("case_id")
    q = lsub.add_parser("compare", help="a second run that changes one thing")
    q.add_argument("case_id")
    q.add_argument("--kind", required=True, choices=["investigator_budget", "runner", "rogue_permissions", "workflow"])
    q.add_argument("--investigator-requests", type=int, default=None)
    q.add_argument("--permissions", default=None, choices=["export_only", "export_log", "export_log_artifact"])
    q.add_argument("--runner", default=None)
    q.add_argument("--mode", default=None, choices=["fast", "specialist"])
    q.add_argument("--investigate", action="store_true")
    q = lsub.add_parser("table", help="this run and the runs derived from the same first run")
    q.add_argument("case_id")
    p.set_defaults(func=_cmd_lab)

    p = sub.add_parser("eval", help="the phase-two paired evaluation: six systems, four new cases, no verifier feedback")
    p.add_argument("--declare", action="store_true", help="write docs/evaluation-config-v2.json (before any run)")
    p.add_argument("--check", action="store_true", help="verify the declaration still matches the code")
    p.add_argument("--preflight", action="store_true", help="worst-case cost and limits; no model call")
    p.add_argument("--dev-check", action="store_true", help="one development case through the four AI arms (not a result)")
    p.add_argument("--run", action="store_true", help="run the declared matrix and write an immutable result directory")
    p.add_argument("--summary", action="store_true", help="write docs/evaluation-summary.md from the saved results")
    p.add_argument("--render", action="store_true", help="regenerate a suite's report from its saved results (no model call)")
    p.add_argument("--suite", default="paired-v2", choices=["paired-v2", "paired-v2-rep1", "paired-v2-repeat1"],
                   help="paired-v2 (four cases) or its separately declared replication on two more incident seeds")
    p.set_defaults(func=_cmd_eval)

    p = sub.add_parser("pilot", help="(refused: the first-run pilot is complete and kept as recorded)")
    p.set_defaults(func=_cmd_pilot)

    p = sub.add_parser("serve", help="serve the API and the built case board on localhost")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.set_defaults(func=_cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary: show a short reason, not a traceback
        from alibi.episode import EpisodeError
        from alibi.runners import RuntimeBlocked

        # NotFound and Conflict (a request that is not valid for a case's state) are ordinary answers, not crashes
        expected = (EpisodeError, ValueError, FileNotFoundError, RuntimeBlocked)
        if isinstance(exc, expected) or type(exc).__name__ in ("NotFound", "Conflict"):
            print(f"error: {exc}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
