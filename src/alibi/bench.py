"""Offline benchmark (PLAN 10.3-10.4, M6).

The suite, systems, scoring rules and caps are frozen in docs/evaluation-config.json
before the run. Every evidence bundle is generated once and reused across systems.
B0 and BR are run here. AI arms are only ever filled by real model runs; while no
zero-charge runtime exists they read "NOT RUN — runtime unavailable". A scripted
fixture can never be written into an AI arm: `validate_ai_run` refuses it.

    uv run alibi bench            run the declared offline suite, write results + docs
    uv run alibi bench --check    verify that the frozen config matches the code
"""

from __future__ import annotations

import json
import platform
import random
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alibi import baselines, scoring, verifier
from alibi.agents.tools import MAX_BYTES, MAX_RECORDS
from alibi.config import REPO_ROOT, RunCaps, Settings
from alibi.contracts import InvestigationReport, Score
from alibi.episode import _git_commit, _package_versions, create_episode, load_answer_key, load_manifest
from alibi.evidence.normalize import NORMALIZER_VERSION
from alibi.evidence.store import EvidenceStore
from alibi.reports import lock_report
from alibi.sim.scenario import SCENARIO_VERSION
from alibi.sim.world import BULK_THRESHOLD_BYTES, SIMULATOR_VERSION

SUITE = "offline-v1"
CONFIG_PATH = REPO_ROOT / "docs" / "evaluation-config.json"
OUT_DIR = REPO_ROOT / "benchmarks" / SUITE
RESULTS_PATH = OUT_DIR / "results.json"
REPORT_MD = REPO_ROOT / "docs" / "benchmark.md"
NOT_RUN = "NOT RUN — runtime unavailable"

# Declared test cases. These seeds were not used while building or tuning anything.
TEST_CASES: list[dict[str, Any]] = (
    [{"case_ref": f"T{i + 1:02d}", "variant": "incident_plain", "seed": 101 + i, "group": "straightforward incident"} for i in range(4)]
    + [{"case_ref": f"T{i + 5:02d}", "variant": "incident_coverup", "seed": 105 + i, "group": "cover-up incident"} for i in range(4)]
    + [{"case_ref": "T09", "variant": "benign_rotation", "seed": 109, "group": "benign control: forced log rotation"},
       {"case_ref": "T10", "variant": "benign_approved_transfer", "seed": 110, "group": "benign control: approved bulk transfer"},
       {"case_ref": "T11", "variant": "benign_remote_login", "seed": 111, "group": "benign control: legitimate remote login"},
       {"case_ref": "T12", "variant": "benign_collection_gap", "seed": 112, "group": "benign control: incomplete collection"}]
)
PILOT_CASE_REFS = ["T01", "T05", "T10", "T12"]  # predeclared: one straightforward, one cover-up, two controls

SYSTEMS: list[dict[str, Any]] = [
    {"id": "B0", "label": "Fixed keyword/regex recipe over the same evidence", "kind": "offline", "priority": "P0",
     "purpose": "Measures improvement over this specific search recipe"},
    {"id": "BR", "label": "Deterministic contradiction checks, templated findings, no model", "kind": "offline",
     "priority": "P0", "purpose": "Shows what the engineering alone accomplishes"},
    {"id": "B1", "label": "Single agent, generic evidence tools only", "kind": "ai", "priority": "P1",
     "purpose": "Original single-agent baseline"},
    {"id": "B1+", "label": "Single agent with the same checks and evidence as ALIBI", "kind": "ai",
     "priority": "first AI comparison", "purpose": "Isolates the contribution of delegation"},
    {"id": "B2", "label": "ALIBI architecture without contradiction checks", "kind": "ai", "priority": "P1",
     "purpose": "Original ablation"},
    {"id": "ALIBI", "label": "Lead + integrity-auditor + skeptic + checks", "kind": "ai",
     "priority": "first AI comparison", "purpose": "Full product"},
]


def frozen_config() -> dict[str, Any]:
    """The evaluation configuration implied by the code. Must equal docs/evaluation-config.json."""
    caps = RunCaps()
    return {
        "suite": SUITE,
        "evidence_origin": "SIM",
        "versions": {"simulator": SIMULATOR_VERSION, "scenario": SCENARIO_VERSION, "normalizer": NORMALIZER_VERSION,
                     "verifier": verifier.VERIFIER_VERSION, "scorer": scoring.SCORER_VERSION,
                     "b0": baselines.B0_VERSION, "br": baselines.BR_VERSION},
        "seed_splits": {
            "development": "seeds 1-40: hand-inspected while building; used by the automated tests",
            "demo": [9023, 9002, 9003],
            "test": [c["seed"] for c in TEST_CASES],
            "note": "Test seeds were declared before the first run of this suite and are not used for tuning. "
                    "If results cause a rule or scorer change, the version is bumped and a fresh split is declared.",
        },
        "cases": TEST_CASES,
        "ai_pilot_case_refs": PILOT_CASE_REFS,
        "systems": SYSTEMS,
        "inputs_shared_by_all_systems": ["the same frozen bundle bytes", "the same neutral tip", "the same operational context",
                                         "the same report schema", "the same verifier", "the same scorer"],
        "scorable_effect_types": ["data_staging", "policy_violating_transfer", "local_log_removal"],
        "not_scored_as_effects": {"login_as": "assessed through account identification and attribution metrics, not recall",
                                  "failed or partial steps": "counted separately as attempts; never recall targets"},
        "matching": {
            "rule": "claim type == effect type AND same host AND (same object OR same session) AND finding window "
                    "<= max_window_s wide and overlapping the effect window within tolerance_s AND the finding cites "
                    "at least one record the executed step produced",
            "algorithm": "one-to-one maximum bipartite matching, findings and effects visited in id order",
            "tolerance_s": scoring.TOLERANCE_S, "max_window_s": scoring.MAX_WINDOW_S,
            "only_final_accepted_allegations_can_match": True,
        },
        "verifier": {"max_allegation_window_s": verifier.MAX_ALLEGATION_WINDOW_S,
                     "window_tolerance_s": verifier.WINDOW_TOLERANCE_S,
                     "note": "applied identically to every system; never adds findings; never reads the answer key"},
        "policy": {"bulk_threshold_bytes": BULK_THRESHOLD_BYTES},
        "b0_rules": [{"rule": r["rule"], "claim_type": r["claim_type"], "pattern": r["pattern"]} for r in baselines.B0_RULES],
        "batch_review": "skipped_for_benchmark (approved_by_human=false); the locked model/baseline output is graded as is",
        "ai_caps_per_investigation": {"max_calls": caps.max_calls, "max_input_tokens": caps.max_input_tokens,
                                      "max_output_tokens": caps.max_output_tokens, "max_seconds": caps.max_seconds,
                                      "tool_result_max_records": MAX_RECORDS, "tool_result_max_bytes": MAX_BYTES,
                                      "shared_across": "lead, specialists and retries"},
        "error_policy": "failed and timed-out runs are kept and counted; budget stops are marked censored; no replacement seeds",
        "paid_overage_authorized_usd": 0,
    }


def check_config() -> list[str]:
    if not CONFIG_PATH.exists():
        return [f"{CONFIG_PATH.relative_to(REPO_ROOT)} does not exist; run `uv run alibi bench --write-config`"]
    on_disk = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    want = json.loads(json.dumps(frozen_config()))
    return [f"config drift in '{k}': the frozen file and the code disagree" for k in sorted(set(on_disk) | set(want))
            if on_disk.get(k) != want.get(k)]


def write_config() -> Path:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(frozen_config(), indent=2) + "\n", encoding="utf-8")
    return CONFIG_PATH


def validate_ai_run(system_id: str, report: InvestigationReport) -> None:
    """An AI arm may only contain real model output. A stub can never be recorded as AI performance."""
    if report.inference_mode != "LIVE_MODEL":
        raise ValueError(f"refusing to record a {report.inference_mode} run under AI system {system_id}: "
                         "only LIVE_MODEL runs count as AI results")
    if not report.model_id:
        raise ValueError(f"AI system {system_id} run has no model id")


def _ratio(num: int, den: int) -> dict[str, Any]:
    return {"num": num, "den": den, "value": (num / den) if den else None}


def aggregate(scores: list[Score]) -> dict[str, Any]:
    """Aggregate by case. Pooled counts are labeled as pooled; small-n results are descriptive only."""
    inc = [s for s in scores if s.case_kind == "incident"]
    ben = [s for s in scores if s.case_kind == "benign"]
    cover = [s for s in inc if s.coverup_detected is not None]
    walls = [s.usage.wall_seconds for s in scores if s.usage.wall_seconds is not None]
    per_case = [s.step_recall.value for s in inc if s.step_recall.value is not None]
    cited = [s.evidence_reference_validity for s in scores if s.evidence_reference_validity.den]
    return {
        "step_recall": _ratio(sum(s.step_recall.num or 0 for s in inc), sum(s.step_recall.den or 0 for s in inc)),
        "incident_cases_fully_reconstructed": _ratio(sum(1 for s in inc if s.step_recall.value == 1.0), len(inc)),
        "median_case_recall": statistics.median(per_case) if per_case else None,
        "proposal_precision": _ratio(sum(s.proposal_precision.num or 0 for s in scores),
                                     sum(s.proposal_precision.den or 0 for s in scores)),
        "final_precision": _ratio(sum(s.final_precision.num or 0 for s in scores),
                                  sum(s.final_precision.den or 0 for s in scores)),
        "coverup_detected": _ratio(sum(1 for s in cover if s.coverup_detected), len(cover)),
        "account_identification": _ratio(sum(1 for s in inc if s.account_identification_correct), len(inc)),
        "benign_false_alert": _ratio(sum(1 for s in ben if s.benign_false_alert), len(ben)),
        "benign_raw_alert": _ratio(sum(1 for s in ben if s.proposals_incident > 0), len(ben)),
        "raw_incident_proposals": sum(s.proposals_incident for s in scores),
        "raw_incident_proposals_in_benign_cases": sum(s.proposals_incident for s in ben),
        "false_claims_final": sum(s.false_claims_final for s in scores),
        "unsupported_named_attribution": sum(s.unsupported_named_attribution for s in scores),
        "false_accusations": sum(1 for s in scores if s.false_accusation),
        "abstained": _ratio(sum(1 for s in scores if s.attribution_abstained), len(scores)),
        "evidence_reference_validity": _ratio(sum(r.num or 0 for r in cited), sum(r.den or 0 for r in cited)),
        "median_wall_seconds": round(statistics.median(walls), 3) if walls else None,
        "wall_seconds_range": [round(min(walls), 3), round(max(walls), 3)] if walls else None,
        "llm_calls": sum(s.usage.llm_calls for s in scores),
        "tokens_in": sum(s.usage.tokens_in for s in scores),
        "tokens_out": sum(s.usage.tokens_out for s in scores),
        "cost_estimate_usd": round(sum(s.usage.cost_estimate_usd for s in scores), 6),
    }


OFFLINE_RUNNERS = {"B0": baselines.run_b0, "BR": baselines.run_br}


def run_offline_suite(settings: Settings, *, cases: list[dict[str, Any]] | None = None,
                      work_dir: Path | None = None) -> dict[str, Any]:
    """Run B0 and BR on every declared case and return the machine-readable result document."""
    cases = cases if cases is not None else TEST_CASES
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    order_rng = random.Random(f"{SUITE}:{run_id}")  # system order is randomized per case and recorded
    tmp = None
    if work_dir is None:
        tmp = tempfile.TemporaryDirectory(prefix="alibi-bench-")
        work_dir = Path(tmp.name)
    case_rows, runs = [], []
    reports_dir = OUT_DIR / "reports"
    try:
        for case in cases:
            ep = f"bench-{case['case_ref'].lower()}-{run_id.lower()}"
            paths = create_episode(seed=case["seed"], variant=case["variant"], runs_dir=work_dir / "runs",
                                   sealed_dir=work_dir / "sealed", episode_id=ep)
            manifest, key = load_manifest(paths), load_answer_key(paths)
            order = list(OFFLINE_RUNNERS)
            order_rng.shuffle(order)
            case_rows.append({**case, "kind": key.case_kind, "bundle_id": manifest.bundle_id,
                              "raw_bundle_sha256": manifest.raw_bundle_sha256, "events": manifest.event_count,
                              "scorable_effects": sum(e.observable for e in key.effects),
                              "unobservable_effects": sum(not e.observable for e in key.effects),
                              "failed_or_partial_steps": sum(s.execution_status != "succeeded" for s in key.steps),
                              "system_order": order})
            with EvidenceStore(paths.db) as store:
                obs = verifier.compute_observations(store, manifest)
                for system_id in order:
                    row: dict[str, Any] = {"system_id": system_id, "case_ref": case["case_ref"], "status": "completed",
                                           "error": None, "score": None, "report_file": None}
                    try:
                        report = OFFLINE_RUNNERS[system_id](store, manifest)
                        report = verifier.verify_report(report, store, manifest, obs)
                        report = lock_report(report, "skipped_for_benchmark", by_human=False)
                        score = scoring.score_report(report, key, store)
                        row["score"] = score.model_dump(mode="json")
                        if cases is TEST_CASES:
                            reports_dir.mkdir(parents=True, exist_ok=True)
                            name = f"{case['case_ref']}-{system_id}.report.json"
                            (reports_dir / name).write_text(report.model_dump_json(indent=1), encoding="utf-8")
                            row["report_file"] = f"benchmarks/{SUITE}/reports/{name}"
                    except Exception as exc:  # noqa: BLE001 - failed runs are kept and counted
                        row["status"], row["error"] = "error", f"{type(exc).__name__}: {str(exc)[:300]}"
                    runs.append(row)
    finally:
        if tmp is not None:
            tmp.cleanup()

    blocked = settings.live_block_reason()
    systems = []
    for spec in SYSTEMS:
        mine = [r for r in runs if r["system_id"] == spec["id"]]
        if spec["kind"] == "offline":
            done = [Score.model_validate(r["score"]) for r in mine if r["status"] == "completed"]
            systems.append({**spec, "inference": "NO_MODEL_BASELINE", "status": "RUN", "status_detail": "",
                            "model_id": None, "n_cases": len(cases), "completed": len(done),
                            "errors": len(mine) - len(done), "aggregate": aggregate(done) if done else None})
        else:
            systems.append({**spec, "inference": None, "status": "NOT_RUN", "status_detail": NOT_RUN, "model_id": None,
                            "n_cases": 0, "completed": 0, "errors": 0, "aggregate": None,
                            "blocker": blocked or "BENCH_MAX_SYSTEM_RUNS is 0"})
    paired = paired_differences(runs, "BR", "B0")
    return {
        "suite": SUITE, "run_id": run_id, "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(), "scorer_version": scoring.SCORER_VERSION,
        "verifier_version": verifier.VERIFIER_VERSION, "simulator_version": SIMULATOR_VERSION,
        "scenario_version": SCENARIO_VERSION, "evidence_origin": "SIM",
        "config_file": "docs/evaluation-config.json", "package_versions": _package_versions(),
        "hardware": {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version()},
        "runtime": {"mode": settings.runtime_mode, "live_inference": "BLOCKED" if blocked else "CONFIGURED",
                    "live_block_reason": blocked, "llm_max_usd": settings.llm_max_usd,
                    "bench_max_system_runs": settings.bench_max_system_runs, "model_calls_made": 0},
        "cases": case_rows, "systems": systems, "runs": runs, "paired": paired,
        "notes": [
            "Controlled simulation benchmark: scores are agreement with executed steps in a synthetic world, "
            "not real-world forensic accuracy.",
            "n is small (12 cases: 8 incidents, 4 benign controls). Results are descriptive; no significance is claimed.",
            "BR's checks were developed against this simulator. Its score shows the checks work on the modeled "
            "world, not that they generalize.",
            "B0's final precision benefits from the shared verifier, which filters its raw keyword hits. Its raw "
            "proposal counts are reported next to it for that reason.",
            "In simulator v1 the adversary's staging and transfer commands stay in shell history, which favors the "
            "keyword baseline. Clearing history is a later difficulty level.",
            "AI arms were not run: no zero-charge model runtime was available. They are not zero; they are unrun.",
        ],
        "reproduce": ["uv run alibi bench --check", "uv run alibi bench"],
    }


def paired_differences(runs: list[dict[str, Any]], a: str, b: str) -> dict[str, Any]:
    """Case-level paired comparison of effects caught (a minus b) on incident cases."""
    by = {(r["system_id"], r["case_ref"]): r["score"] for r in runs if r["status"] == "completed"}
    rows = []
    for (sid, ref), sa in sorted(by.items()):
        if sid != a or (b, ref) not in by or sa["case_kind"] != "incident":
            continue
        sb = by[(b, ref)]
        rows.append({"case_ref": ref, a: f"{sa['step_recall']['num']}/{sa['step_recall']['den']}",
                     b: f"{sb['step_recall']['num']}/{sb['step_recall']['den']}",
                     "difference_in_effects_caught": sa["step_recall"]["num"] - sb["step_recall"]["num"]})
    diffs = [r["difference_in_effects_caught"] for r in rows]
    return {"a": a, "b": b, "metric": "effects caught per incident case", "per_case": rows,
            "cases_a_better": sum(d > 0 for d in diffs), "cases_equal": sum(d == 0 for d in diffs),
            "cases_b_better": sum(d < 0 for d in diffs), "n": len(diffs)}


# --------------------------------------------------------------------------- markdown report


def _r(x: dict[str, Any] | None) -> str:
    if not x or x.get("den") in (None, 0):
        return "N/A"
    return f"{x['num']}/{x['den']}"


def render_markdown(doc: dict[str, Any]) -> str:
    L: list[str] = []
    L += [f"# Benchmark: {doc['suite']}", "",
          "> **Auto-generated by `uv run alibi bench` from `benchmarks/offline-v1/results.json`. Do not edit by hand.**", "",
          f"- Generated: {doc['generated_at']} · commit `{doc['git_commit']}` · run `{doc['run_id']}`",
          f"- Evidence origin: **{doc['evidence_origin']}** (simulated). Simulator {doc['simulator_version']}, scenario "
          f"{doc['scenario_version']}, verifier {doc['verifier_version']}, scorer {doc['scorer_version']}.",
          f"- Runtime mode: `{doc['runtime']['mode']}` · live inference: **{doc['runtime']['live_inference']}** · "
          f"model calls made: **{doc['runtime']['model_calls_made']}** · paid spend: **$0**",
          f"- Hardware: {doc['hardware']['platform']} · Python {doc['hardware']['python']}",
          "- Frozen configuration: [`docs/evaluation-config.json`](evaluation-config.json)", "",
          "## What this does and does not show", ""]
    L += [f"- {n}" for n in doc["notes"]]
    L += ["", "## Systems", "",
          "| System | What it is | Status | Cases | Effects caught (pooled) | Incident cases fully reconstructed | "
          "Final precision | Raw proposal precision | Cover-ups detected | Account identified | "
          "Benign cases with a final false alert | Benign cases with raw alerts | Median time |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in doc["systems"]:
        a = s["aggregate"]
        if s["status"] != "RUN" or not a:
            L.append(f"| **{s['id']}** | {s['label']} | **{s['status_detail']}** | 0 | — | — | — | — | — | — | — | — | — |")
            continue
        L.append(f"| **{s['id']}** | {s['label']} | run, no model | {s['completed']}/{s['n_cases']} | {_r(a['step_recall'])} | "
                 f"{_r(a['incident_cases_fully_reconstructed'])} | {_r(a['final_precision'])} | {_r(a['proposal_precision'])} | "
                 f"{_r(a['coverup_detected'])} | {_r(a['account_identification'])} | {_r(a['benign_false_alert'])} | "
                 f"{_r(a['benign_raw_alert'])} ({a['raw_incident_proposals_in_benign_cases']} raw claims) | "
                 f"{a['median_wall_seconds']} s |")
    L += ["", "Reading the table: *effects caught* pools scorable effects over the 8 incident cases; *final precision* "
          "counts accepted allegations after the shared verifier; *raw proposal precision* counts every allegation a "
          "system proposed, including those the verifier rejected. Attribution: unsupported named attributions were "
          + ", ".join(f"{s['id']}: {s['aggregate']['unsupported_named_attribution']}" for s in doc["systems"] if s["aggregate"])
          + "; false accusations were "
          + ", ".join(f"{s['id']}: {s['aggregate']['false_accusations']}" for s in doc["systems"] if s["aggregate"]) + ".", ""]
    p = doc["paired"]
    L += [f"## Paired comparison: {p['a']} vs {p['b']} ({p['metric']})", "",
          f"| Case | {p['a']} | {p['b']} | {p['a']} − {p['b']} |", "|---|---|---|---|"]
    L += [f"| {r['case_ref']} | {r[p['a']]} | {r[p['b']]} | {r['difference_in_effects_caught']:+d} |" for r in p["per_case"]]
    L += ["", f"{p['a']} caught more effects in {p['cases_a_better']} of {p['n']} incident cases, the same number in "
          f"{p['cases_equal']}, fewer in {p['cases_b_better']}. With n = {p['n']} this is a descriptive result.", ""]
    L += ["## Per case", "",
          "| Case | Group | Seed | Events | Scorable effects | System | Recall | Final precision | Raw proposals (incident) | "
          "Accepted | False final claims | Cover-up | Account | Benign false alert |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    by_case = {c["case_ref"]: c for c in doc["cases"]}
    yn = lambda v: "n/a" if v is None else ("yes" if v else "no")  # noqa: E731
    for r in sorted(doc["runs"], key=lambda r: (r["case_ref"], r["system_id"])):
        c = by_case[r["case_ref"]]
        if r["status"] != "completed":
            L.append(f"| {c['case_ref']} | {c['group']} | {c['seed']} | {c['events']} | {c['scorable_effects']} | {r['system_id']} | "
                     f"ERROR: {r['error']} | | | | | | | |")
            continue
        s = r["score"]
        L.append(f"| {c['case_ref']} | {c['group']} | {c['seed']} | {c['events']} | {c['scorable_effects']} | {r['system_id']} | "
                 f"{_r(s['step_recall'])} | {_r(s['final_precision'])} | {s['proposals_incident']} | {s['final_accepted_incident']} | "
                 f"{s['false_claims_final']} | {yn(s['coverup_detected'])} | {yn(s['account_identification_correct'])} | "
                 f"{yn(s['benign_false_alert'])} |")
    L += ["", "N/A means not applicable (for example recall in a case where nothing happened), never zero.", "",
          "## Reproduce", "", "```sh"] + doc["reproduce"] + ["```", "",
          "Evidence bundles are regenerated from the declared seeds; their raw-bundle hashes are recorded in "
          "`results.json` and must match. Locked reports for every system-run are in `benchmarks/offline-v1/reports/`.", ""]
    return "\n".join(L)


def write_outputs(doc: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    REPORT_MD.write_text(render_markdown(doc), encoding="utf-8")
