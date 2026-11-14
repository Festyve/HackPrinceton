# Daniel’s worker-lab verification

## Release handoff, November 14

GitHub’s default branch is `codex/alibi-build`. At `0814d24` it already
contains Daniel’s `dbc2936`, Terry’s worker Lab UI, and Eric’s two matrix
batches. Daniel has no separate merge to make. The published Eric checkpoint
`a829b09` is three commits ahead. It adds the scheduler-backed worker/account
link, two live examples and the acceptance writeup. Eric should confirm the
final release SHA before the release owner integrates those follow-up commits.

### Checks completed on `a829b09`

- Daniel’s frozen `benchmarks/worker-lab-v1/protocol.json` matches `dbc2936`
  byte for byte. Eric’s separate declaration is
  `benchmarks/worker-lab-eric-matrix/protocol.json`. His runner’s `--check`
  passed, and the saved runtime matrix has all 18 cells, with 17 complete
  and one stopped.
- Daniel’s offline and runtime results and Eric’s eight-cell live batch passed
  `python -m scripts.daniel.evaluate validate`. The live batch has seven
  completed runs and one capped run, four benign cells with zero accepted
  false allegations, and about $0.040 in recorded model cost. Both workflows
  missed the dependent lead. See
  `benchmarks/worker-lab-v1/eric/live/{results.json,summary.md,reports/}`.
- Recomputed the input audit from all eight saved payload files (50 captured
  requests). Their payload digests and computed audits match `input-audit.json`.
  The scanner found no private fields or canary. These eight cells had no
  evidence-linked plan revisions or successful later note reads under the
  audit criteria. The separate live resume trace records both, once. The
  worker-link feature check shows a cited scheduler assignment in two runs
  on one seed. The process that used the credential remains unresolved. See
  `benchmarks/feature-checks/worker-lab-resume-across-processes-haiku-5-5.json`
  and `benchmarks/feature-checks/worker-lab-worker-link-haiku-5-5.json`.
- In a clean checkout on Daniel’s machine, the locked dependencies installed,
  the frontend built, and the keyless release smoke passed. It covered startup,
  recorded replay, imported Docker evidence with three exact citations,
  report lock and Markdown export. All 40 tests in `tests/test_browser_lab.py`
  and `tests/test_m19_worker_lab.py` passed, including incident and benign
  control, comparisons, review and operator sealing.

### Final release checklist

1. Confirm Eric’s final published SHA and the intended release target. Check
   that the target contains `dbc2936` and that both declarations still resolve.
2. If the final SHA differs from the checked candidate, rerun the relevant
   validators and release checks on that SHA. Build with `npm --prefix web run
   build`, run the smoke command below against a clean checkout, and run
   `python -m pytest tests/test_browser_lab.py tests/test_m19_worker_lab.py`
   with `RUNTIME_MODE=offline` and `LLM_MAX_USD=0`. Save the clean launch
   record from Daniel’s machine for the released SHA.
3. Give Rayan the final SHA, these results, and the acceptance record. The
   fault actions remain scripted. The human usability review and final demo
   and submission remain release owner actions.

## Earlier work and findings

The six independent cases are in `tests/fixtures/daniel/worker-lab`. The
[protocol](../../../benchmarks/worker-lab-v1/protocol.json) was frozen at
`20f6d7d`. It pins the runtime and prompt sources separately from the latest
release reproduction. The scorer fixtures and runtime tapes belong on the
evaluator side of the evidence boundary.

## Findings for Rayan

1. On six synthetic cases per baseline, deterministic checks established two
   of three observable effects, with zero unsupported proposals on four benign
   cases. Keyword rules established zero effects and raised four unsupported
   proposals across three benign cases and one incident. The verifier accepted
   zero false allegations from either baseline. Both missed the dependent
   gateway lead.
2. All seven scripted runtime executions replayed to their recorded evidence
   hashes. On one incident seed, the deterministic investigator established
   4/4 observable effects under each request preset. This sample provides no
   evidence of a model budget or model-selected fault advantage.
3. Eric’s four live development attempts on seed 11 included one cap stop.
   The other three established 5/5, 3/5 and 4/5 effects with no accepted false
   allegations. The last recorded trace links auditor results to new plan
   items, and three traces record a later read of the case file. This is one
   run per prompt variant and there was no resume or independent worker
   attribution demonstration.

## Saved results and trace evidence

- [Offline score table](../../../benchmarks/worker-lab-v1/daniel/offline/summary.md)
  and [run records](../../../benchmarks/worker-lab-v1/daniel/offline/results.json).
- [Runtime score table](../../../benchmarks/worker-lab-v1/daniel/runtime/summary.md),
  [run records](../../../benchmarks/worker-lab-v1/daniel/runtime/results.json) and
  [replay hashes](../../../benchmarks/worker-lab-v1/daniel/runtime/replay-checks.json).
- [Scripted investigator input audit](../../../benchmarks/worker-lab-v1/daniel/runtime/input-audit.json).
  Captured 16 model-facing requests with tools across three roles on the pinned
  runtime. The scanner found no private fields or canary. It found no
  evidence-linked revision, later note read, or worker attribution in that run.
- [Eric’s saved live feature check at 40907cd](https://github.com/owly1/HackPrinceton/blob/40907cd/benchmarks/feature-checks/worker-lab-adaptive-investigation-haiku-5-5.json).
  In attempt 4, the auditor returned at sequence 20. At sequence 21 the lead
  added tasks for the missing export records, transfers and scheduler lookup,
  then searched the scheduler. The lead wrote `/case/case.md` at 13 and read
  it at 34. The report tied `wk-ingest` to W1 via assignments and called out
  ambiguous sessions. That supports a worker/account association and leaves
  the issuing process unresolved. The saved trace summarizes tool events.
  Full provider payloads, worker attribution proof and resume remain pending.

| Live development prompt | Supported / observable | Accepted false | Outcome | Calls | Input / output tokens | Investigator seconds | Ledger USD |
|---|---|---|---|---|---|---|---|
| lab-lead/1 | 0/5 | 0 | Request size cap | 7 | 157132 / 3883 | 19.503 | 0.008810 |
| lab-lead/2 | 5/5 | 0 | Completed | 16 | 206693 / 15320 | 64.222 | 0.016070 |
| lab-lead/3 | 3/5 | 0 | Completed | 13 | 163674 / 14379 | 63.277 | 0.015825 |
| lab-lead/4 | 4/5 | 0 | Completed | 12 | 149924 / 13682 | 55.747 | 0.015028 |

The live figures are read from Eric’s saved feature check. Daniel’s runs used
zero model calls and incurred zero spend.

## Reproduce

From Daniel’s checkout with the locked environment installed:

```sh
export PYTHON_DOTENV_DISABLED=1 RUNTIME_MODE=offline LLM_MAX_USD=0
.venv/bin/python -m scripts.daniel.evaluate run --output /tmp/daniel-offline-new
.venv/bin/python -m scripts.daniel.evaluate validate benchmarks/worker-lab-v1/daniel/offline/results.json
.venv/bin/python -m scripts.daniel.evaluate validate benchmarks/worker-lab-v1/daniel/runtime/results.json
PYTHONPATH="$PWD" /path/to/463c9d1-checkout/.venv/bin/python -m scripts.daniel.runtime --output /tmp/daniel-runtime-new
npm --prefix web run build
.venv/bin/python -m pytest -p no:cacheprovider -o addopts='' -q -ra
```

Daniel’s branch passed 518 tests. After the final metric adjustment, the
32 validator tests also passed. Both revised result files validated.

The published release smoke used Eric’s integrated commit `6caa909`,
which includes Terry `9591107` and Eric’s source-panel fix. Locked Python
and npm dependencies were installed. The documented
startup command served the product in offline mode with no key. Recorded
replay reached review. The Docker import exposed three exact citations,
locked on review, exported Markdown and refused reveal as expected.
The full regression suite passed all 523 tests on this commit.
[Smoke observations](owner-reproduction/observations.json)
Eric’s later commit `30d8375` also passed the same clean checkout smoke.
Its matrix declaration passed `scripts/run_lab_matrix.py --check` with 18
cells, including 12 live cells, and a declared maximum estimate of $0.822.
All 25 targeted tests passed, including lab recording and replay and the
deleted-original browser regression.
[Lab candidate smoke observations](lab-reproduction/observations.json)

For the independent race reproduction, Daniel also merged Eric `40907cd`
and Terry `9591107` in a temporary checkout. The shared-status fix at
`c0500d4` passed the deleted-original test and the same smoke checks. Its
full regression suite passed all 523 tests. The patch applies to that earlier
merge with `git apply --unidiff-zero`.
[Candidate source-panel patch](source-comparison.patch)

Build the chosen candidate and run the smoke driver from Daniel’s checkout.

```sh
.venv/bin/python -m scripts.daniel.release --checkout /path/to/candidate --output /tmp/daniel-release-new
```

## Integration requests

- **Eric** Merge Daniel’s branch after review. Run the eight declared
  `live-investigator` cells through your existing ledger and return
  `results.json`, matching report artifacts, full investigator request/tool
  payloads for audit and all stopped outcomes. Use the pinned fingerprints or
  commit a separately approved prospective protocol before running with changed
  prompts. The seed-11 feature check does not supply those cells. Keep private
  scorer data outside the model graph and record remaining worker, note,
  resume and attribution gaps. Your matrix at `30d8375` adds a different
  protocol at the same path. During integration, retain Daniel’s committed
  bytes at `benchmarks/worker-lab-v1/protocol.json` so the validator can
  verify their original digest. Move the runtime-owned declaration to a
  distinct path and update `scripts/run_lab_matrix.py` to read it. The two
  matrices use different cases and their results need their own provenance.
- **Terry** Integrate the existing worker endpoints into the Lab screen.
  Eric shipped the original-case copy fix at `6caa909`. That implementation
  still renders the original-case link while its request is pending.
  Daniel’s patch shows how to share the response across both panels and
  wait for the status before rendering the link.
- **Release owner** Provide the merged candidate for final worker Lab and
  browser acceptance. The temporary checkout proves the flows listed above.
  Model-selected fault behavior, the live evaluation and human usability
  acceptance remain open.
