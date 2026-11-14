"""Read one run of the declared worker-lab matrix, check it against the protocol, and render it.

    uv run python scripts/read_lab_matrix.py                 # the latest run directory
    uv run python scripts/read_lab_matrix.py <run-id> --write docs/worker-lab-eric-matrix.md

Checks, each of which fails the read:
  * every declared cell has exactly one result, and nothing undeclared is present;
  * a cell derived for the same evidence has its parent's bundle hash, and separate executions do not share one
    unless the protocol says they replay the same tape;
  * a live cell is labeled as a live model and a deterministic cell as the deterministic baseline;
  * a cell that did not complete is still present, with its status.
Nothing is averaged. A cell that stopped, failed or was not run stays in every count of cells.

Written by the same session that wrote the code under test. It is a consistency check, not an independent audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "benchmarks" / "worker-lab-eric-matrix"
SAME_EVIDENCE = ("investigator_budget", "workflow")


def load(run_id: str | None) -> tuple[dict, dict[str, dict], Path]:
    proto = json.loads((SUITE / "protocol.json").read_text())
    runs = sorted(p for p in SUITE.iterdir() if p.is_dir())
    if not runs:
        raise SystemExit("no run directory yet")
    run_dir = SUITE / run_id if run_id else runs[-1]
    results = {p.stem: json.loads(p.read_text()) for p in sorted(run_dir.glob("*.json"))}
    return proto, results, run_dir


def check(proto: dict, results: dict[str, dict]) -> list[str]:
    problems: list[str] = []
    declared = {c["id"]: c for c in proto["cells"]}
    for cid in declared:
        if cid not in results:
            problems.append(f"{cid}: declared but has no result")
    for cid in results:
        if cid not in declared:
            problems.append(f"{cid}: has a result but was not declared")
    seen_cases: dict[str, str] = {}
    for cid, r in results.items():
        cell = declared.get(cid)
        if cell is None:
            continue
        if r.get("declared") != cell:
            problems.append(f"{cid}: the saved declaration differs from the protocol")
        case = r.get("case_id")
        if case:
            if case in seen_cases:
                problems.append(f"{cid}: shares a case id with {seen_cases[case]}")
            seen_cases[case] = cid
        if r.get("terminal_status") in ("error", None):
            continue
        labels = r.get("labels") or {}
        want = "LIVE_MODEL" if cell["runner"] == "agent-live" else "NO_MODEL_BASELINE"
        if labels.get("inference") != want:
            problems.append(f"{cid}: labeled {labels.get('inference')}, expected {want}")
        if "no model chooses" not in str(labels.get("changed_objective_policy")):
            problems.append(f"{cid}: the changed-objective label is missing")
        parent = cell.get("derive_from")
        if parent and parent in results and results[parent].get("raw_bundle_sha256"):
            same = r.get("raw_bundle_sha256") == results[parent]["raw_bundle_sha256"]
            if cell["comparison"] in SAME_EVIDENCE and not same:
                problems.append(f"{cid}: declared as the same evidence as {parent} but the bundle hash differs")
            if cell["comparison"] not in SAME_EVIDENCE and same:
                problems.append(f"{cid}: declared as a new execution but has {parent}'s bundle hash")
        used, allowed = (r.get("used") or {}).get("llm_calls"), (r.get("allowed") or {}).get("investigator_requests")
        if cell["runner"] == "agent-live" and used is not None and allowed is not None and used > allowed:
            problems.append(f"{cid}: used {used} requests with an allowance of {allowed}")
        if r.get("person_named"):
            problems.append(f"{cid}: a person was named")
    return problems


def _ratio(x: dict | None) -> str:
    if not x or x.get("den") in (None, 0):
        return "n/a"
    return f"{x['num']} of {x['den']}"


def _row(cid: str, r: dict) -> str:
    if r.get("terminal_status") in ("error", None):
        return f"| {cid} | - | - | - | **{r.get('terminal_status')}**: {str(r.get('error'))[:90]} | - | - | - | - | - |"
    sc, used = r.get("scored") or {}, r.get("used") or {}
    kind = sc.get("case_kind")
    effects = sc.get("executed_effects") or []
    hidden = sum(not e["observable"] for e in effects)
    status = r["terminal_status"] + (f" ({str(r['stop_reason'])[16:70]})" if r.get("stop_reason") else "")
    alert = {True: "**yes**", False: "no", None: "n/a"}[sc.get("benign_false_alert")]
    # exact comparison only: a report that lists several accounts, or adds words, does not equal the account used
    reported = str(r.get("account_reported") or "none")
    acct = "n/a" if kind != "incident" else (
        f"yes (`{sc.get('account_truth')}`)" if sc.get("account_correct") else
        f"no: reported \"{reported[:60]}{'…' if len(reported) > 60 else ''}\", used `{sc.get('account_truth')}`")
    cost = used.get("cost_estimate_usd")
    return (f"| {cid} | `{str(r['bundle_id'])[-8:]}` | {r['allowed']['investigator_requests']} | {used.get('llm_calls', '-')} | {status} | "
            f"{_ratio(sc.get('effects_established'))}" + (f" ({hidden} more not observable)" if hidden else "") + " | "
            f"{_ratio(sc.get('accepted_allegations_matched'))} | {alert} | {acct} | "
            f"{'-' if cost is None else f'${cost:.4f}'} |")


def render(proto: dict, results: dict[str, dict], run_dir: Path, problems: list[str]) -> str:
    cells = proto["cells"]
    proto_hash = hashlib.sha256((SUITE / "protocol.json").read_bytes()).hexdigest()[:16]
    commits = sorted({r.get("git_commit") for r in results.values() if r.get("git_commit")})
    by_status: dict[str, int] = {}
    for c in cells:
        s = (results.get(c["id"]) or {}).get("terminal_status") or "no result"
        by_status[s] = by_status.get(s, 0) + 1
    inv_cost = sum(((r.get("used") or {}).get("cost_estimate_usd") or 0) for r in results.values())
    wk_cost = sum(((r.get("worker_usage") or {}).get("cost_estimate_usd") or 0) for r in results.values()
                  if not (r.get("declared") or {}).get("derive_from"))
    out = [
        "# Worker lab: the integration owner's declared matrix", "",
        f"Run `{run_dir.name}` · protocol `benchmarks/worker-lab-eric-matrix/protocol.json` (sha256 `{proto_hash}…`, declared "
        f"{proto['declared_at']}) · code at `{', '.join(commits)}` · results in `benchmarks/worker-lab-eric-matrix/{run_dir.name}/`.", "",
        f"**Who wrote this.** {proto['written_by']}", "",
        "**Correction.** The sentence above, and the suite name `worker-lab-v1` inside the protocol and result files, are "
        "wrong and are kept only so that the files stay byte-identical to what was committed before the run. Daniel had "
        "pushed his independent `worker-lab-v1` protocol to his own branch at 15:56 ET, twenty minutes before this one was "
        "declared; this session had not fetched it. This matrix is not that protocol. It uses different cases, and it was "
        "moved here from `benchmarks/worker-lab-v1/` after the run so that Daniel's protocol keeps its path and digest. "
        "Daniel's protocol and results are in `benchmarks/worker-lab-v1/`.", "",
        f"**What was asked.** {proto['question']}", "",
        f"**How to read it.** {proto['sample_size_note']} Every incident here has its objective changed by a scripted "
        "policy; no model chose a fault action. \"Effects established\" counts executed, observable effects that an accepted "
        "allegation matched after the report was locked. An effect that no captured source can show is not scored.", "",
        f"**All {len(cells)} declared cells:** " + ", ".join(f"{n} {s}" for s, n in sorted(by_status.items())) + ". "
        f"Estimated cost: ${inv_cost:.4f} for investigations and ${wk_cost:.4f} for the workers' ordinary work.", "",
    ]
    if problems:
        out += ["**The reader found problems with this run:**", ""] + [f"- {p}" for p in problems] + [""]
    else:
        out += ["The reader's checks passed: every declared cell has one result, same-evidence cells share their parent's "
                "bundle hash, labels match the runner, no allowance was exceeded and no person was named.", ""]
    head = ("| Cell | Evidence | Requests allowed | Requests used | Outcome | Effects established | Accepted allegations matched "
            "| Alleged an incident on a control | Reported account is exactly the account used | Est. cost |\n|---|---|---:|---:|---|---|---|---|---|---:|")
    for group, title in (("presets", "Allocation presets (three separate executions)"),
                         ("investigator_allowance", "The investigator's allowance on the same evidence"),
                         ("workflow", "One agent and three agents on the same evidence, heavier context"),
                         ("deterministic_checks", "The deterministic checks alone, no model")):
        out += [f"## {title}", "", proto["comparisons"][group], "", head]
        out += [_row(c["id"], results.get(c["id"]) or {}) for c in cells if c["group"] == group]
        out.append("")
    out += ["## What this does not show", "",
            "One run per cell on one seed. It is not a detection rate and not evidence that one configuration is better "
            "than another. The changed worker's behavior is scripted, so nothing here is about an adaptive adversary. "
            "The protocol, the code and this reader came from the same session.", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_id", nargs="?")
    ap.add_argument("--write", default=None)
    args = ap.parse_args()
    proto, results, run_dir = load(args.run_id)
    problems = check(proto, results)
    text = render(proto, results, run_dir, problems)
    if args.write:
        Path(args.write).write_text(text)
        print(f"wrote {args.write}")
    else:
        print(text)
    for p in problems:
        print("PROBLEM:", p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
