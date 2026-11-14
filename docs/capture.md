# Daniel's application-log capture

The disposable Compose setup runs a Python test service and an independent Python
collector. Three ordinary HTTP requests use the account `demo` and dummy record
IDs. Both processes write their own files. The collector fsyncs the exact received
line with its UTC receipt time and stable sequence ID before acknowledging it.

The runtime uses an internal network, an unprivileged numeric user, read-only
container roots and container-local tmpfs storage. The Docker build copies only
`runtime.py`. There are no host bind mounts or published ports. The collector's
storage is accessible only in its own container. Fixture controls execute through
the service container's CLI. The HTTP endpoints accept bounded test requests.

## Reproduce

Run from the repository root on `codex/daniel-capture`, with Docker Desktop running.
The runner checks for the base image and stops if it is absent. Obtain approval
before downloading an absent image.

```sh
docker image inspect python:3.13-slim
# Only after approval, if absent:
docker pull python:3.13-slim
uv sync --frozen
uv run python capture/run.py --output capture/output
```

Use a fresh output directory for each run. The runner builds from the cached image,
starts fresh containers for each case, copies original files through binary `docker compose exec -T` output, validates manifests, and removes the containers and network. Output
is published only after all three captures succeed. No model inference is involved.
The runner uses a unique Compose project so cleanup targets its own containers.

```sh
uv run alibi import capture/output/evidence/complete --runner deterministic
uv run alibi import capture/output/evidence/missing-local-record --runner deterministic
uv run alibi import capture/output/evidence/benign-gap --runner deterministic
```

Each imported bundle contains exactly three files.

```text
capture.json
records/var/log/records-app/access.log
collector/collected/collected.log
```

The source files are UTF-8 application records in the existing parser's format.
They are emitted directly by the running processes. Packaging preserves every raw
byte and computes SHA-256 and byte counts after the experiment. The manifest
records UTC capture and source coverage bounds, source origins, actual image IDs,
and the forwarding policy used by reconciliation. The base image ID and Docker
and Compose versions are also recorded in `capture/output/private/provenance.json`.
Image tags can change between runs. Consult the captured image IDs for a particular
run's identity. Reimporting a frozen bundle preserves its original bytes.

## Cases and private records

| Capture | Executed operation | Expected comparison |
|---|---|---|
| complete | Three local writes, each forwarded and acknowledged | `consistent` |
| missing-local-record | Remove request 2's local line after its durable collector acknowledgment, retain requests 1 and 3 | One `unexplained_local_absence` |
| benign-gap | Pause only the local sink during request 2 while forwarding continues, then resume | `inconclusive`, with the explicit maintenance gap and zero unexplained absences |

`capture/output/private/*.json` records actions, delivery acknowledgments and their
timestamps. These files are outside all import directories. The private directory
has mode 0700 and the individual control files mode 0600. Investigator code only
receives the evidence bundle. Public manifests contain operational coverage gaps,
without the removal action record or expected outcomes.

Each local record includes its sender timestamp. Each collector record includes
its receipt timestamp, sequence and original line. The service checks the hash in
the acknowledgment before the fixture can remove a line. Failed forwarding aborts
the experiment. Reruns require fresh containers and fresh output directories.

## Offline fixtures and verification

`tests/fixtures/capture/` contains the three small frozen Docker captures. Each
bundle imports without Docker or network access. The capture tests also exercise
the same HTTP handlers locally using SIM provenance for test-generated inputs.

```sh
uv run pytest tests/test_capture.py tests/test_m15_import.py
```

Tests verify exact imported bytes, hashes, parse success, line and byte-offset
citations, the three reconciliation outcomes, and refusal of a modified artifact.
The failed-forwarding regression checks that an absent receipt prevents removal.
Tests that exercise local HTTP servers require permission to bind localhost sockets.

## Integration and limits

The entry point is the existing `uv run alibi import <directory>`.
`alibi.capture.manifest.package_capture` prepares its neutral manifest and calls
`alibi.importing.load_capture` for validation. Imported cases remain unscored and
have no ALIBI answer key. Their private fixture controls are available for external
acceptance checks. Imported evidence can be reviewed and exported through the
existing application, with reveal unavailable for unscored cases.

Eric's shared schemas, importer, API and CLI need no change for these captures.
One observed limitation for Eric is that `evidence/store.py::_db_ts` truncates
fractional seconds. Reconciliation compares these timestamps with the collector's
full-precision `inner_ts`, so a subsecond sequence can lose its later bracket.
The fixture spaces requests by 1.05 seconds while retaining the original timestamps.
Preserving fractional seconds in the shared store would enable faster captures.

This captures a controlled application and its independent receipt trail. Docker
containers share a host clock. The fixture has three serial requests and does not
establish behavior for clock skew, overlapping sessions, authentic PAM audits or
large transfers. The broader independently declared evaluation suite in DANIEL.md,
IoT-CAD ingestion and second-machine/projector checks remain follow-up work.

## Verified run

The three fixtures total 7,887 bytes including manifests. They were produced using
Docker 29.8.0 and Compose 5.5.1, with base image digest
`sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90`.
The built service and collector image ID is recorded in each manifest.
All three imported through the CLI with `DOCKER` provenance, `scored=false`, and
zero normalization errors. Deterministic reconciliation produced the outcomes in
the table above. The complete and benign bundles generated zero removal findings.
The missing-local-record bundle generated exactly one `local_log_removal` finding.

The host test environment uses Python 3.14.5 because Python 3.13 was unavailable
locally. The containers use the approved Python 3.13 image. Frozen fixture checks require neither Docker access nor network access.

Validation completed with `35 passed` from
`pytest tests/test_capture.py tests/test_m15_import.py`. Compose configuration
validation and Python compilation also passed. Dependency deprecation warnings
were emitted by LangSmith under Python 3.14.
