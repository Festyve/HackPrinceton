# Daniel’s worker-lab fixtures

`evidence/<case-id>/` contains six frozen, hand-authored `SIM` snapshots in the
existing `alibi-capture/1` format. Each snapshot includes normal ingest and
reporting activity, application records, collector receipts, session records,
worker assignments, delivery-gateway logs, policy records, and simulated flows.
The case IDs, paths, and import titles use the same naming convention across
the set. All addresses represent sinks in the simulation.

Give an investigator only the chosen evidence directory through the existing
importer. Keep this README, test code, and `scorer-only/expectations.json` out
of the investigator filesystem, metadata, prompts, and replay inputs. When
running an evaluation outside this app, expose only the selected snapshot and
the case’s writable notes workspace. The scorer file is accessible to anyone
who has the repository checkout.

## Offline validation

From the repository root, use the existing virtual environment. The import
command writes to disposable run and sealed directories. Use any opaque ID
from `evidence/` as the last path component.

```sh
scratch=$(mktemp -d)
RUNTIME_MODE=offline LLM_MAX_USD=0 ALIBI_RUNS_DIR="$scratch/runs" \
  ALIBI_SEALED_DIR="$scratch/sealed" .venv/bin/alibi import \
  tests/fixtures/daniel/worker-lab/evidence/wl-14c8 --runner deterministic --investigate

RUNTIME_MODE=offline LLM_MAX_USD=0 .venv/bin/python -m pytest \
  tests/test_daniel_worker_fixtures.py
```

## Scorer handoff

The scorer index pairs each ID with the raw-bundle SHA-256 and the `capture.json`
SHA-256. Verify both. The latter binds operational metadata such as declared
coverage and change windows, which can affect interpretation even when log bytes
match. `fault_attempts` records the scripted action, target, worker and outcome.
`incident_claims` lists observable effects with the expected claim type, object
and supporting citations. `control_evidence` names evidence for benign or denied
activity. Citations use artifact paths and one-based line numbers, or the
manifest field for a declared gap. `attribution` applies to the delivery request.
A known worker in `fault_attempts` does not establish an observable worker link.

The existing importer creates unscored cases. The fixture tests check
provenance, citations, input separation, deterministic findings on the direct
transfers, and the dependent lead through the actual read-only evidence tools.
The legacy transfer check applies host-level policy. The gateway pair requires
joining the request, source port, and dataset-specific policy records. The tests
exercise that join over returned evidence. Worker-runtime scoring, action tapes,
and the frozen experiment split are pending.
