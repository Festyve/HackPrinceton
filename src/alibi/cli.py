"""ALIBI command line. `uv run alibi --help`."""

from __future__ import annotations

import argparse
import json
import sys

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
        out = orch.save_recording(rec.case_id, args.name, note=args.note)
        done = orch.record(rec.case_id)
        mode, how = done.inference_mode, done.investigation_mode or "no agent"
    print(f"saved {out}  (inference: {mode}; mode: {how}; replay it from the case board start screen or "
          f"POST /api/replays/{args.name}/open)")
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
    inner = gateway.live_chat_model(settings, settings.lead_model or "")
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
        print(f"the spend ledger cannot be used, so no model call will be made: {exc}", file=sys.stderr)
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

    p = sub.add_parser("pilot", help="the predeclared 8-system-run AI pilot (refused without a zero-charge runtime)")
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

        if isinstance(exc, (EpisodeError, ValueError, FileNotFoundError)):
            print(f"error: {exc}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
