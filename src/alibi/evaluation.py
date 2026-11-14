"""The phase-two paired evaluation (docs/next-run/CONTINUE.md section 5).

Six systems on the same frozen bundles, the same tip, the same report schema, the same verifier and
the same scorer:

    B0     fixed keyword recipe                                  (no model)
    BR     deterministic checks, templated findings              (no model)
    B1     one agent, generic evidence tools only
    B1+    one agent, generic tools + the deterministic checks
    B2     lead + auditor + skeptic, generic evidence tools only
    ALIBI  lead + auditor + skeptic, generic tools + the checks

What is different from the first-run pilot, and declared here before any run:

  * NO VERIFIER FEEDBACK. In every AI arm submit_finding only confirms that a finding is well-formed
    and that its ids exist. Rule support is applied once, after the report locks, identically for
    all six systems. An arm without the checks cannot recover their answers by probing a tool.
  * Arms without the checks get prompts that never mention them, and no check tool in any role.
  * One model, one effort level and one per-investigation budget for all four AI arms.
  * New seeds. The first-run test and pilot cases are not reused as if they were unseen.
  * Results go to a new timestamped directory that is never overwritten. offline-v1 and ai-pilot-v1
    are not touched.

Every cell is kept: completed, stopped by a cap (censored), refused, errored or not started.
One run per cell: this demonstrates that the systems work and differ; it does not estimate a rate.
"""

from __future__ import annotations

import hashlib
import json
import random
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alibi import baselines, bench, scoring, verifier
from alibi.agents import gateway
from alibi.config import REPO_ROOT, RunCaps, Settings
from alibi.contracts import Score
from alibi.episode import _git_commit, create_episode, load_answer_key, load_manifest
from alibi.evidence.store import EvidenceStore
from alibi.reports import lock_report
from alibi.runners import RunContext, RuntimeBlocked

SUITE = "paired-v2"
CONFIG_PATH = REPO_ROOT / "docs" / "evaluation-config-v2.json"
OUT_ROOT = REPO_ROOT / "benchmarks" / SUITE
REPORT_MD = REPO_ROOT / "docs" / "evaluation-v2.md"
CATEGORY_CEILING_USD = 0.75  # API_SETUP.md: new paired evaluation

MODEL = "anthropic:claude-haiku-5-5"
EFFORT = "low"
MAX_TOKENS_PER_CALL = 3000
PRICE_IN, PRICE_OUT = 0.10, 0.50
# One budget per investigation for every AI arm. Sized from calibration (benchmarks/calibration/): the
# specialist graph on this model needed up to 176k input and 13.5k output tokens on development cases.
# The per-request ceiling is 90,000 (the hard maximum is 95,000, under this model's 100,000-token price tier):
# a development check showed arms without the checks build larger requests from generic search results, and
# the product's 40,000 ceiling stopped them before they could report. That would have been a handicap, not a result.
CAPS = RunCaps(max_calls=24, max_input_tokens=280_000, max_output_tokens=20_000, max_seconds=240.0,
               max_input_tokens_per_call=90_000)

# arm -> (graph, has the deterministic check tools)
AI_ARMS: dict[str, tuple[str, bool]] = {"B1": ("single-agent", False), "B1+": ("single-agent", True),
                                        "B2": ("alibi", False), "ALIBI": ("alibi", True)}
OFFLINE_ARMS = {"B0": baselines.run_b0, "BR": baselines.run_br}
ARM_LABELS = {"B0": "Fixed keyword recipe (no model)", "BR": "Deterministic checks, templated findings (no model)",
              "B1": "One agent, generic evidence tools only", "B1+": "One agent, generic tools + checks",
              "B2": "Lead + auditor + skeptic, generic evidence tools only",
              "ALIBI": "Lead + auditor + skeptic, generic tools + checks"}

# Declared cases. Seeds 201-212 are a new split: no bundle for them was generated or looked at before this
# declaration. They are disjoint from development (1-40), demo (9002-9044), first-run test (101-112) and
# calibration (17, 23) seeds.
CASES: list[dict[str, Any]] = [
    {"case_ref": "V01", "variant": "incident_evasion", "seed": 201, "group": "difficult incident",
     "why": "the inside job plus four attempts to cover it; one of them leaves nothing observable"},
    {"case_ref": "V02", "variant": "incident_coverup", "seed": 202, "group": "cover-up",
     "why": "a host log line removed after the transfer"},
    {"case_ref": "V03", "variant": "benign_rotation", "seed": 203, "group": "benign control: legitimate rotation",
     "why": "collector-only lines that a naive comparison would call missing"},
    {"case_ref": "V04", "variant": "benign_approved_transfer", "seed": 204, "group": "benign control: approved transfer",
     "why": "a bulk transfer with the same shape as the crime, to an approved destination"},
]
# Replication, declared separately after paired-v2 had run and before any bundle for these seeds existed: the two
# incident kinds again on two more of the reserved seeds, same model, arms, budget and rules. It exists because
# paired-v2 has only two incident cases; it is reported beside paired-v2, never merged into it.
REPLICATION_SUITE = "paired-v2-rep1"
REPLICATION_CASES: list[dict[str, Any]] = [
    {"case_ref": "V05", "variant": "incident_evasion", "seed": 205, "group": "difficult incident (replication)",
     "why": "the same kind of case as V01 on a new seed"},
    {"case_ref": "V06", "variant": "incident_coverup", "seed": 206, "group": "cover-up (replication)",
     "why": "the same kind of case as V02 on a new seed"},
]
PAIRED_V2_ESTIMATED_COST_USD = 0.2198  # what paired-v2 used of the shared $0.75 evaluation ceiling
SUITES: dict[str, dict[str, Any]] = {
    SUITE: {"cases": CASES, "config": CONFIG_PATH, "ceiling": CATEGORY_CEILING_USD, "reserved": list(range(205, 213))},
    REPLICATION_SUITE: {"cases": REPLICATION_CASES, "config": REPO_ROOT / "docs" / "evaluation-config-v2-rep1.json",
                        "ceiling": round(CATEGORY_CEILING_USD - PAIRED_V2_ESTIMATED_COST_USD, 4),
                        "reserved": list(range(207, 213))},
}

# Development check only (not an evaluation result): one development-seed incident through all four AI arms,
# to find harness faults before the declared cases are spent.
DEV_CASES: list[dict[str, Any]] = [
    {"case_ref": "D01", "variant": "incident_coverup", "seed": 29, "group": "development check", "why": "harness check"},
]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _prompt_fingerprints() -> dict[str, Any]:
    """Hashes of the exact prompts each arm gets, so a later prompt edit shows up as config drift."""
    from alibi.agents import investigator as inv

    out: dict[str, Any] = {}
    for arm, (graph, checks) in AI_ARMS.items():
        if graph == "single-agent":
            out[arm] = {"single": _sha(inv.single_prompt(checks, False))}
        else:
            out[arm] = {"lead": _sha(inv.lead_prompt(checks, False)), "auditor": _sha(inv.auditor_prompt(checks)),
                        "skeptic": _sha(inv.skeptic_prompt(checks))}
    out["family_addendum"] = {"vocabulary": _sha(inv.FAMILY_VOCABULARY), "with_checks": _sha(inv.FAMILY_CHECKS_NOTE),
                              "without_checks": _sha(inv.FAMILY_GENERIC_NOTE)}
    return out


def _tools_by_arm() -> dict[str, Any]:
    from alibi.agents.tools import CHECK_TOOLS, FAMILY_CHECK_TOOLS, ROLE_TOOLS

    out = {}
    for arm, (graph, checks) in AI_ARMS.items():
        roles = ("single-agent",) if graph == "single-agent" else ("lead-investigator", "integrity-auditor", "skeptic")
        out[arm] = {r: [n for n in ROLE_TOOLS[r] if checks or n not in CHECK_TOOLS] for r in roles}
    out["extra_checks_on_family_bundles"] = {"tools": list(FAMILY_CHECK_TOOLS),
                                             "given_to": "the same roles that hold the first-run checks; arms B1 and B2 get none"}
    return out


def declared_config(suite: str = SUITE) -> dict[str, Any]:
    """The evaluation as declared by the code. Must equal the suite's declared file before a run."""
    from alibi.agents.tools import MAX_BYTES, MAX_RECORDS

    spec = SUITES[suite]
    cases = spec["cases"]
    worst = gateway.worst_case_usd(CAPS.max_input_tokens, CAPS.max_output_tokens, PRICE_IN, PRICE_OUT)
    cells = len(cases) * len(AI_ARMS)
    doc = _declared(suite, cases, cells, worst, spec, MAX_RECORDS, MAX_BYTES)
    if suite != SUITE:
        doc["replicates"] = {"suite": SUITE, "note": "Same model, arms, prompts, tools, budget and rules as paired-v2, on "
                                                      "two more reserved seeds. Declared after paired-v2 ran, so it is a "
                                                      "replication and is reported separately.",
                             "shared_ceiling_usd": CATEGORY_CEILING_USD,
                             "already_used_by_paired_v2_usd": PAIRED_V2_ESTIMATED_COST_USD}
    return doc


def _declared(suite: str, cases: list[dict[str, Any]], cells: int, worst: float, spec: dict[str, Any],
              MAX_RECORDS: int, MAX_BYTES: int) -> dict[str, Any]:
    return {
        "suite": suite, "evidence_origin": "SIM",
        "supersedes": "nothing. offline-v1 and ai-pilot-v1 stay as recorded; this is a separate suite.",
        "versions": bench.current_versions(),
        "model": {"id": MODEL, "effort": EFFORT, "max_tokens_per_call": MAX_TOKENS_PER_CALL,
                  "price_in_per_mtok": PRICE_IN, "price_out_per_mtok": PRICE_OUT,
                  "same_for_every_role_and_arm": True, "refusal_fallback": "off"},
        "caps_per_investigation": {"max_calls": CAPS.max_calls, "max_input_tokens": CAPS.max_input_tokens,
                                   "max_output_tokens": CAPS.max_output_tokens, "max_seconds": CAPS.max_seconds,
                                   "max_input_tokens_per_call": CAPS.max_input_tokens_per_call,
                                   "tool_result_max_records": MAX_RECORDS, "tool_result_max_bytes": MAX_BYTES,
                                   "shared_across": "lead, specialists and retries"},
        "systems": [{"id": a, "label": ARM_LABELS[a], "kind": "offline"} for a in OFFLINE_ARMS]
        + [{"id": a, "label": ARM_LABELS[a], "kind": "ai", "graph": g, "checks": c} for a, (g, c) in AI_ARMS.items()],
        "tools": _tools_by_arm(), "prompt_sha256": _prompt_fingerprints(),
        "verifier_feedback_during_investigation": False,
        "verifier_feedback_note": ("submit_finding confirms form and reference validity only. Rule support is applied "
                                   "after the report is locked, identically for all six systems. The interactive product "
                                   "keeps immediate feedback; that is the one deliberate difference from this evaluation."),
        "seed_split": {"evaluation": [c["seed"] for c in cases], "reserved_unused": spec["reserved"],
                       "note": "Declared before any bundle for these seeds was generated. Not used for tuning. A rule or "
                               "prompt change after results are seen needs a new version and a new split."},
        "cases": cases,
        "matrix": {"ai_cells": cells, "runs_per_cell": 1, "offline_cells": len(cases) * len(OFFLINE_ARMS),
                   "system_order": "randomized per case from the run id and recorded"},
        "batch_review": "skipped_for_benchmark (approved_by_human=false); the locked output is graded as is",
        "matching": {"tolerance_s": scoring.TOLERANCE_S, "max_window_s": scoring.MAX_WINDOW_S,
                     "only_final_accepted_allegations_can_match": True,
                     "rule": "claim type == effect type AND same host AND (same object OR same session) AND the window "
                             "overlaps within tolerance AND the finding cites a record the executed step produced"},
        "cost_preflight": {"worst_case_usd_per_cell": round(worst, 6), "worst_case_usd_total": round(worst * cells, 6),
                           "category_ceiling_usd": spec["ceiling"],
                           "basis": "every input token priced as a cache write, the full output cap used"},
        "error_policy": "every cell is kept: completed, censored by a cap, refused, errored or not started. "
                        "No replacement seeds, no reruns of a finished cell.",
        "reported": ["per-case outcomes", "valid citations", "unsupported allegations", "false or unsupported named "
                     "attribution", "estimated cost", "latency", "sample size"],
        "what_this_cannot_show": "One run per cell on four simulated cases. It shows the systems run and how they "
                                 "differed here. It is not an accuracy estimate and has no statistical power.",
        "paid_overage_authorized_usd": 0,
    }


def _config_path(suite: str) -> Path:
    return CONFIG_PATH if suite == SUITE else SUITES[suite]["config"]


def check_config(suite: str = SUITE) -> list[str]:
    path = _config_path(suite)
    if not path.exists():
        return [f"{path.name} does not exist; declare it with `uv run alibi eval --declare`"]
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    want = json.loads(json.dumps(declared_config(suite)))
    return [f"config drift in '{k}': the declared file and the code disagree"
            for k in sorted(set(on_disk) | set(want)) if k != "declared_at" and on_disk.get(k) != want.get(k)]


def _out_root(suite: str) -> Path:
    return OUT_ROOT if suite == SUITE else REPO_ROOT / "benchmarks" / suite


def declare(suite: str = SUITE) -> Path:
    """Write the declaration. Refused once any result of this suite exists: it is declared before, not after."""
    root, path = _out_root(suite), _config_path(suite)
    if root.exists() and any(root.glob("*/results.json")):
        raise RuntimeBlocked(f"{suite} already has results; its declaration is frozen")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {**declared_config(suite), "declared_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


def preflight(settings: Settings, n_cells: int | None = None, ceiling_usd: float = CATEGORY_CEILING_USD) -> dict[str, Any]:
    """Everything that must hold before a paid cell starts. Makes no model call."""
    cells = n_cells if n_cells is not None else len(CASES) * len(AI_ARMS)
    worst = gateway.worst_case_usd(CAPS.max_input_tokens, CAPS.max_output_tokens, PRICE_IN, PRICE_OUT)
    problems: list[str] = []
    reason = settings.live_block_reason()
    if reason is not None:
        problems.append(f"live inference is BLOCKED: {reason}")
    if settings.lead_model != MODEL:
        problems.append(f"the runtime model is {settings.lead_model}; this suite is declared for {MODEL}")
    if (settings.price_in_per_mtok, settings.price_out_per_mtok) != (PRICE_IN, PRICE_OUT):
        problems.append("the configured prices differ from the declared ones")
    if settings.effort != EFFORT or settings.max_tokens_per_call != MAX_TOKENS_PER_CALL:
        problems.append("effort or per-call output limit differs from the declaration")
    if settings.bench_max_system_runs < cells:
        problems.append(f"BENCH_MAX_SYSTEM_RUNS is {settings.bench_max_system_runs}; {cells} system-runs are declared. "
                        "Set it only after this preflight passes otherwise")
    if worst * cells > ceiling_usd + 1e-9:
        problems.append(f"worst case ${worst * cells:.4f} exceeds the ${ceiling_usd:.2f} ceiling for this evaluation")
    spend = gateway.global_spend_for(settings)
    snap = spend.snapshot() if spend else None
    if snap is not None and snap["remaining_to_limit_usd"] < worst * cells:
        problems.append(f"only ${snap['remaining_to_limit_usd']:.4f} remains under the development ceiling; "
                        f"the worst case is ${worst * cells:.4f}")
    return {"cells": cells, "worst_case_usd_per_cell": round(worst, 6), "worst_case_usd_total": round(worst * cells, 6),
            "category_ceiling_usd": ceiling_usd, "spend": snap, "problems": problems, "ok": not problems}


def _live_runner(arm: str, settings: Settings) -> Any:
    from alibi.agents.runner import AgentRunner

    graph, checks = AI_ARMS[arm]
    return AgentRunner("agent-live", settings, architecture=graph, with_checks=checks, verify_on_submit=False)


def _tag(case_ref: str, arm: str) -> str:
    return f"{case_ref}-{arm.replace('+', 'plus')}"


def run(settings: Settings, *, cases: list[dict[str, Any]] | None = None, runner_factory: Any = None,
        out_root: Path | None = None, suite: str = SUITE, work_dir: Path | None = None,
        ceiling_usd: float = CATEGORY_CEILING_USD) -> dict[str, Any]:
    """Run every declared cell and write an immutable result directory. Returns the result document.

    runner_factory(arm, settings) is for tests: it supplies a stand-in runner. Real runs build the live
    runner, and a report that is not a live model's is refused, so a stub can never be recorded as AI.
    """
    declared = suite in SUITES
    if cases is None:
        cases = SUITES[suite]["cases"] if declared else CASES
        if declared and ceiling_usd == CATEGORY_CEILING_USD:
            ceiling_usd = SUITES[suite]["ceiling"]
    live = runner_factory is None
    if live:
        pre = preflight(settings, len(cases) * len(AI_ARMS), ceiling_usd)
        if not pre["ok"]:
            raise RuntimeBlocked("evaluation refused: " + "; ".join(pre["problems"]))
        if declared:
            drift = check_config(suite)
            if drift:
                raise RuntimeBlocked("evaluation refused: " + "; ".join(drift))
    settings = replace(settings, caps=CAPS)
    factory = runner_factory or _live_runner
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = (out_root or (REPO_ROOT / "benchmarks" / suite)) / run_id.lower()
    if out_dir.exists():
        raise FileExistsError(f"{out_dir} already exists; evaluation results are never overwritten")
    out_dir.mkdir(parents=True)
    spend = gateway.global_spend_for(settings) if live else None
    start = spend.snapshot()["committed_usd"] if spend else 0.0
    order_rng = random.Random(f"{suite}:{run_id}")
    tmp = None
    if work_dir is None:
        tmp = tempfile.TemporaryDirectory(prefix="alibi-eval-")
        work_dir = Path(tmp.name)
    runs: list[dict[str, Any]] = []
    case_rows = []
    started = 0
    try:
        for case in cases:
            ep = f"eval-{case['case_ref'].lower()}-{run_id.lower()}"
            paths = create_episode(seed=case["seed"], variant=case["variant"], runs_dir=work_dir / "runs",
                                   sealed_dir=work_dir / "sealed", episode_id=ep)
            manifest, key = load_manifest(paths), load_answer_key(paths)
            order = list(AI_ARMS)
            order_rng.shuffle(order)
            case_rows.append({**case, "kind": key.case_kind, "bundle_id": manifest.bundle_id,
                              "raw_bundle_sha256": manifest.raw_bundle_sha256, "events": manifest.event_count,
                              "scorable_effects": sum(e.observable for e in key.effects),
                              "unobservable_effects": sum(not e.observable for e in key.effects),
                              "effect_types": sorted(e.effect_type for e in key.effects if e.observable),
                              "system_order": order})
            with EvidenceStore(paths.db) as store:
                obs = verifier.compute_observations(store, manifest)
                for arm, fn in OFFLINE_ARMS.items():
                    row = _cell(suite, arm, case, "offline")
                    try:
                        report = lock_report(verifier.verify_report(fn(store, manifest), store, manifest, obs),
                                             "skipped_for_benchmark", by_human=False)
                        row["score"] = scoring.score_report(report, key, store).model_dump(mode="json")
                        row["report_file"] = _save_report(out_dir, case["case_ref"], arm, report)
                    except Exception as exc:  # noqa: BLE001
                        row["status"], row["error"] = "error", f"{type(exc).__name__}: {str(exc)[:300]}"
                    runs.append(row)
            for arm in order:
                row = _cell(suite, arm, case, "ai")
                used = (spend.snapshot()["committed_usd"] - start) if spend else 0.0
                if started >= settings.bench_max_system_runs and live:
                    row["status"], row["error"] = "unrun_budget", "not started: BENCH_MAX_SYSTEM_RUNS reached"
                    runs.append(row)
                    continue
                if spend is not None and used + gateway.worst_case_usd(
                        CAPS.max_input_tokens, CAPS.max_output_tokens, PRICE_IN, PRICE_OUT) > ceiling_usd + 1e-9:
                    row["status"], row["error"] = "unrun_budget", (
                        f"not started: ${used:.4f} of the ${ceiling_usd:.2f} evaluation ceiling is used and one more "
                        "cell could pass it")
                    runs.append(row)
                    continue
                started += 1
                try:
                    with EvidenceStore(paths.db) as store:  # a fresh store and a fresh case directory per cell
                        ctx = RunContext(case_id=f"{ep}-{_tag('', arm).strip('-').lower()}", store=store, manifest=manifest,
                                         case_dir=paths.case / _tag(case["case_ref"], arm), settings=settings,
                                         emit=lambda t, d: None)
                        report = factory(arm, settings).run(ctx).model_copy(update={"system_id": arm})
                        if live:
                            bench.validate_ai_run(arm, report)
                        report = lock_report(verifier.verify_report(report, store, manifest),
                                             "skipped_for_benchmark", by_human=False)
                        stop = next((q for q in report.open_questions if q.startswith("Incomplete run")), None)
                        row.update(censored=stop is not None, stop_note=stop, refused="declined" in (stop or ""),
                                   model_id=report.model_id, inference_mode=report.inference_mode)
                        row["score"] = scoring.score_report(report, key, store).model_dump(mode="json")
                        row["report_file"] = _save_report(out_dir, case["case_ref"], arm, report)
                        transcript = ctx.case_dir / "transcript.json"
                        if transcript.exists():  # tool traces stay local (gitignored)
                            (out_dir / "transcripts").mkdir(exist_ok=True)
                            (out_dir / "transcripts" / f"{_tag(case['case_ref'], arm)}.transcript.json").write_text(
                                transcript.read_text(encoding="utf-8"), encoding="utf-8")
                except ValueError:
                    raise  # a non-live result must never be recorded as an AI arm: stop loudly
                except Exception as exc:  # noqa: BLE001 - provider errors are results too
                    row["status"], row["error"] = "error", f"{type(exc).__name__}: {str(exc)[:300]}"
                runs.append(row)
    finally:
        if tmp is not None:
            tmp.cleanup()
    end = spend.snapshot() if spend else None
    doc = {
        "suite": suite, "run_id": run_id, "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(), "evidence_origin": "SIM", "scorer_version": scoring.SCORER_VERSION,
        "versions": bench.current_versions(),
        "config_sha256": (_sha(_config_path(suite).read_text(encoding="utf-8"))
                          if suite in SUITES and _config_path(suite).exists() else None),
        "inference": "LIVE_MODEL" if live else "TEST_DOUBLE", "model": settings.lead_model if live else None,
        "caps": {"max_calls": CAPS.max_calls, "max_input_tokens": CAPS.max_input_tokens,
                 "max_output_tokens": CAPS.max_output_tokens, "max_seconds": CAPS.max_seconds},
        "verifier_feedback_during_investigation": False,
        "cases": case_rows, "runs": runs, "systems": _systems(runs, len(cases)),
        "paired": {"checks_effect_one_agent": bench.paired_differences(runs, "B1+", "B1"),
                   "checks_effect_three_agents": bench.paired_differences(runs, "ALIBI", "B2"),
                   "delegation_effect_with_checks": bench.paired_differences(runs, "ALIBI", "B1+"),
                   "delegation_effect_without_checks": bench.paired_differences(runs, "B2", "B1")},
        "system_runs_started": started,
        "spend": {"estimated_cost_usd": round(end["committed_usd"] - start, 6) if end else 0.0,
                  "unreconciled_usd_after": end["unreconciled_usd"] if end else 0.0,
                  "total_after_usd": end["committed_usd"] if end else None, "ceiling_usd": ceiling_usd},
        "notes": [f"One run per cell on {_count_words(len(cases))} simulated cases: a demonstration that the six systems "
                  "run and how they differed here, not an accuracy estimate. Model output varies between runs; that "
                  "variance was not measured.",
                  "No AI arm received verifier feedback while investigating. Rule support was applied after lock, "
                  "identically for all six systems.",
                  "Scores describe agreement with a controlled simulation, not real-world forensic accuracy."],
    }
    (out_dir / "results.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    if suite in SUITES and _config_path(suite).exists():
        (out_dir / "config.json").write_text(_config_path(suite).read_text(encoding="utf-8"), encoding="utf-8")
    doc["result_dir"] = str(out_dir)
    return doc


def _cell(suite: str, arm: str, case: dict[str, Any], kind: str) -> dict[str, Any]:
    return {"suite": suite, "system_id": arm, "kind": kind, "case_ref": case["case_ref"], "status": "completed",
            "error": None, "censored": False, "refused": False, "stop_note": None, "score": None, "report_file": None}


def _save_report(out_dir: Path, case_ref: str, arm: str, report: Any) -> str:
    (out_dir / "reports").mkdir(exist_ok=True)
    f = out_dir / "reports" / f"{_tag(case_ref, arm)}.report.json"
    f.write_text(report.model_dump_json(indent=1), encoding="utf-8")
    try:
        return str(f.relative_to(REPO_ROOT))
    except ValueError:
        return str(f)


def _systems(runs: list[dict[str, Any]], n_cases: int) -> list[dict[str, Any]]:
    out = []
    for arm in list(OFFLINE_ARMS) + list(AI_ARMS):
        mine = [r for r in runs if r["system_id"] == arm]
        done = [Score.model_validate(r["score"]) for r in mine if r["status"] == "completed" and r["score"]]
        out.append({"id": arm, "label": ARM_LABELS[arm], "kind": "offline" if arm in OFFLINE_ARMS else "ai",
                    "n_cases": n_cases, "completed": len(done), "errors": sum(r["status"] == "error" for r in mine),
                    "censored": sum(bool(r["censored"]) for r in mine), "refused": sum(bool(r["refused"]) for r in mine),
                    "unrun": sum(r["status"] == "unrun_budget" for r in mine),
                    "aggregate": bench.aggregate(done) if done else None})
    return out


def latest(out_root: Path | None = None, suite: str = SUITE) -> dict[str, Any] | None:
    """The most recent result of a suite, or None. Read-only."""
    root = out_root or _out_root(suite)
    files = sorted(root.glob("*/results.json")) if root.exists() else []
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def _r(x: dict[str, Any] | None) -> str:
    return "n/a" if not x or not x.get("den") else f"{x['num']}/{x['den']}"


def _count_words(n: int) -> str:
    return {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}.get(n, str(n))


def _notes(doc: dict[str, Any]) -> list[str]:
    """The stored notes, with one known wording error corrected in the open.

    The first replication's results file carries a note written with a fixed "four simulated cases" although
    that suite has two. Result files are never edited, so the correction is made here and stated.
    """
    notes = list(doc["notes"])
    n = _count_words(len(doc["cases"]))
    if notes and "four simulated cases" in notes[0] and len(doc["cases"]) != 4:
        notes[0] = notes[0].replace("four simulated cases", f"{n} simulated cases")
        notes.append(f"Erratum: the first note stored in the results file says \"four simulated cases\"; this suite has {n}. "
                     "It is corrected above. No measurement is affected and the results file is unchanged.")
    return notes


def render_markdown(doc: dict[str, Any]) -> str:
    """docs/evaluation-v2.md, generated only from a result document."""
    sysd = {s["id"]: s for s in doc["systems"]}
    cells = {(r["system_id"], r["case_ref"]): r for r in doc["runs"]}
    arms = [s["id"] for s in doc["systems"]]
    out = [f"# Paired evaluation ({doc['suite']})", "",
           f"> Generated by `uv run alibi eval --run` from `benchmarks/{doc['suite']}/{doc['run_id'].lower()}/results.json`. "
           "Do not edit by hand.", "",
           f"Run `{doc['run_id']}` · commit `{doc['git_commit']}` · model `{doc['model']}` · simulated evidence · "
           f"estimated cost ${doc['spend']['estimated_cost_usd']:.4f}", "",
           f"**Read this first.** One run per cell on {_count_words(len(doc['cases']))} simulated cases. It shows that "
           "the six systems run and how they differed here. It is not an accuracy estimate. No AI arm was told whether "
           "a finding was supported while it investigated; support was decided after each report was locked, the same "
           "way for every system.", "",
           "## Systems", "", "| Arm | What it is | Cells done | Stopped by a cap | Errors | Not started |", "|---|---|---|---|---|---|"]
    out += [f"| {a} | {sysd[a]['label']} | {sysd[a]['completed']}/{sysd[a]['n_cases']} | {sysd[a]['censored']} | "
            f"{sysd[a]['errors']} | {sysd[a]['unrun']} |" for a in arms]
    out += ["", "## Per case", "", "Incident cases: effects established / observable effects. Benign cases: accepted "
            "incident allegations (0 is correct), with raw proposals in brackets.", "",
            "| Case | What it is | " + " | ".join(arms) + " |", "|---|---|" + "---|" * len(arms)]
    for c in doc["cases"]:
        row = []
        for a in arms:
            r = cells.get((a, c["case_ref"]))
            if r is None or r["status"] != "completed" or not r["score"]:
                row.append((r or {}).get("status", "missing").replace("_", " "))
                continue
            s = r["score"]
            mark = " (stopped by a cap)" if r["censored"] else ""
            row.append((f"{s['step_recall']['num']}/{s['step_recall']['den']}" if c["kind"] == "incident" else
                        f"{s['final_accepted_incident']} [{s['proposals_incident']}]") + mark)
        extra = f"; {c['unobservable_effects']} more not observable" if c.get("unobservable_effects") else ""
        out.append(f"| {c['case_ref']} | {c['group']} ({c['scorable_effects']} observable effect(s){extra}) | " + " | ".join(row) + " |")
    out += ["", "## Totals over the completed cells", "",
            "| Arm | Effects established | Cover-ups found | Benign cases with an accepted allegation | Unsupported accepted "
            "allegations | Valid citations | Unsupported named attribution | Model calls | Est. cost | Median time |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for a in arms:
        g = sysd[a]["aggregate"]
        if not g:
            out.append(f"| {a} | no completed cell | | | | | | | | |")
            continue
        out.append(f"| {a} | {_r(g['step_recall'])} | {_r(g['coverup_detected'])} | {_r(g['benign_false_alert'])} | "
                   f"{g['false_claims_final']} | {_r(g['evidence_reference_validity'])} | {g['unsupported_named_attribution']} | "
                   f"{g['llm_calls']} | ${g['cost_estimate_usd']:.4f} | "
                   f"{g['median_wall_seconds'] if g['median_wall_seconds'] is not None else 'n/a'} s |")
    out += ["", "## Notes", ""] + [f"- {n}" for n in _notes(doc)]
    stops = [r for r in doc["runs"] if r.get("stop_note") or r.get("error")]
    if stops:
        out += ["", "## Cells that did not complete normally", ""]
        out += [f"- {r['system_id']} on {r['case_ref']}: {r.get('stop_note') or r.get('error')}" for r in stops]
    out += ["", f"Locked reports for every cell: `benchmarks/{doc['suite']}/{doc['run_id'].lower()}/reports/`. "
            "The first-run results are unchanged in [benchmark.md](benchmark.md).", ""]
    return "\n".join(out)


def combined(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-system totals over several result documents (for example paired-v2 and its replication).

    A plain sum of completed cells, stated as such. The suites stay separate records; this only saves a
    reader the addition.
    """
    scores: dict[str, list[Score]] = {a: [] for a in list(OFFLINE_ARMS) + list(AI_ARMS)}
    censored: dict[str, int] = {a: 0 for a in scores}
    for doc in docs:
        for r in doc["runs"]:
            if r["status"] == "completed" and r["score"]:
                scores[r["system_id"]].append(Score.model_validate(r["score"]))
                censored[r["system_id"]] += int(bool(r["censored"]))
    return {"suites": [{"suite": d["suite"], "run_id": d["run_id"], "cases": len(d["cases"])} for d in docs],
            "systems": [{"id": a, "label": ARM_LABELS[a], "cells": len(v), "censored": censored[a],
                         "aggregate": bench.aggregate(v) if v else None} for a, v in scores.items()],
            "note": "Sums over completed cells of separately declared suites, one run per cell. Not an accuracy estimate."}


def summary(out_roots: dict[str, Path] | None = None) -> dict[str, Any] | None:
    """The latest result of every declared suite, summed per system, for a results display. Read-only.

    The same figures as docs/evaluation-summary.md, from the same result files. None when no suite has run.
    """
    docs = [d for d in (latest((out_roots or {}).get(s), suite=s) for s in SUITES) if d]
    if not docs:
        return None
    return {**combined(docs), "model": docs[0].get("model"), "inference": docs[0].get("inference"),
            "evidence_origin": docs[0].get("evidence_origin"),
            "verifier_feedback_during_investigation": any(d.get("verifier_feedback_during_investigation") for d in docs),
            "incident_cases": sum(c["kind"] == "incident" for d in docs for c in d["cases"]),
            "benign_cases": sum(c["kind"] != "incident" for d in docs for c in d["cases"]),
            "correct_findings_not_counted": [x for d in docs for x in true_findings_not_accepted(d)],
            "reports": ["docs/evaluation-summary.md"]}


def true_findings_not_accepted(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Findings that matched an executed effect but did not count, and what stopped them.

    Read from the saved, locked reports. The usual causes are a skeptic agent downgrading a finding the
    deterministic check supported, or the verifier not finding support for the records that were cited.
    """
    out = []
    for r in doc["runs"]:
        if r["kind"] != "ai" or not r["score"] or not r["report_file"]:
            continue
        wanted = {o["finding_id"] for o in r["score"]["finding_outcomes"] if o["outcome"] == "matched_but_not_accepted"}
        f = REPO_ROOT / r["report_file"]
        if not wanted or not f.exists():
            continue
        for finding in json.loads(f.read_text(encoding="utf-8"))["findings"]:
            if finding["id"] in wanted:
                out.append({"suite": doc["suite"], "case_ref": r["case_ref"], "system_id": r["system_id"],
                            "claim_type": finding["claim_type"], "status": finding["status"],
                            "check_result": finding["verification_status"],
                            "skeptic_note": (finding.get("skeptic_note") or "")[:240]})
    return out


def render_combined(docs: list[dict[str, Any]]) -> str:
    c = combined(docs)
    out = ["# Evaluation summary", "",
           "> Generated by `uv run alibi eval --summary` from the result files below. Do not edit by hand.", "",
           "Suites summed here, each declared before it ran:", ""]
    out += [f"- `{x['suite']}` run `{x['run_id']}`, {x['cases']} case(s)" for x in c["suites"]]
    out += ["", "One run per cell on simulated cases. No AI system was told whether a finding was supported while it "
            "investigated. This shows how the systems differed on these cases; it is not an accuracy estimate.", "",
            "| System | Cells | Effects established | Cover-ups found | Benign cases with an accepted allegation | "
            "Unsupported accepted allegations | Named a person | Stopped by a cap | Est. cost |",
            "|---|---|---|---|---|---|---|---|---|"]
    for x in c["systems"]:
        g = x["aggregate"]
        if not g:
            continue
        out.append(f"| {x['id']}: {x['label']} | {x['cells']} | {_r(g['step_recall'])} | {_r(g['coverup_detected'])} | "
                   f"{_r(g['benign_false_alert'])} | {g['false_claims_final']} | {g['unsupported_named_attribution']} | "
                   f"{x['censored']} | ${g['cost_estimate_usd']:.4f} |")
    lost = [x for d in docs for x in true_findings_not_accepted(d)]
    if lost:
        out += ["", "## Correct findings that did not count", "",
                "These findings matched an executed effect, but were not accepted in the locked report, so they earned "
                "nothing. \"Downgraded by skeptic\" means the skeptic agent withdrew a finding; the check result column "
                "shows what the deterministic check said about the same finding.", "",
                "| Suite | Case | System | Finding | Why it did not count | Check result |", "|---|---|---|---|---|---|"]
        out += [f"| {x['suite']} | {x['case_ref']} | {x['system_id']} | {x['claim_type'].replace('_', ' ')} | "
                f"{x['status'].replace('_', ' ')} | {x['check_result'].replace('_', ' ')} |" for x in lost]
    out += ["", "Per-case tables: " + ", ".join(
        f"[{d['suite']}]({'evaluation-v2.md' if d['suite'] == SUITE else 'evaluation-' + d['suite'].replace('paired-', '') + '.md'})"
        for d in docs) + ".", ""]
    return "\n".join(out)
