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
starts fresh containers for each case, copies original files through binary
`docker compose exec -T` output, validates manifests, and removes the containers
and network. Output
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
locally. The containers use the approved Python 3.13 image. Frozen fixture checks require
neither Docker access nor network access.

Validation completed with `35 passed` from
`pytest tests/test_capture.py tests/test_m15_import.py`. Compose configuration
validation and Python compilation also passed. Dependency deprecation warnings
were emitted by LangSmith under Python 3.14.


## Fresh verification on November 14, 2026

Capture source commit `ce01304` was rerun at 12:30 America/New_York, using the
already cached base image. All three container runs and cleanup completed with
exit code 0. The generated run is local and gitignored at
`capture/output/verification-20261114-01`. The original committed fixtures remain
available for offline regression testing.

The following commands were executed from the repository root. The existing
virtual environment contains the locked dependencies and Python 3.14.5.

```sh
.venv/bin/python capture/run.py --output capture/output/verification-20261114-01
RUNTIME_MODE=offline LLM_MAX_USD=0 .venv/bin/python -m pytest tests/test_capture.py tests/test_m15_import.py -o addopts='' -q
.venv/bin/python capture/verify.py capture/output/verification-20261114-01
docker compose -f capture/compose.yaml config --quiet
.venv/bin/python -m compileall -q capture/verify.py
```

Choose a new output directory when repeating the capture command. The verifier
invokes the existing command as `python -m alibi.cli import <bundle> --runner
deterministic` for each scenario, with `RUNTIME_MODE=offline`, `LLM_MAX_USD=0`,
and run/sealed roots inside the capture output. It stores its detailed result at
`<output>/private/verification.json`, including CLI output, file hashes, bundle
hashes, coverage and private action checks. Repeating verification creates fresh
imported case IDs. The verifier's report contains control information and belongs
outside imported evidence directories.

Equivalent direct CLI imports are shown below. These commands use the same
isolated output roots as the verifier.

```sh
export RUNTIME_MODE=offline LLM_MAX_USD=0
export ALIBI_RUNS_DIR="$PWD/capture/output/verification-20261114-01/imported-runs"
export ALIBI_SEALED_DIR="$PWD/capture/output/verification-20261114-01/imported-sealed"
.venv/bin/alibi import capture/output/verification-20261114-01/evidence/complete --runner deterministic
.venv/bin/alibi import capture/output/verification-20261114-01/evidence/missing-local-record --runner deterministic
.venv/bin/alibi import capture/output/verification-20261114-01/evidence/benign-gap --runner deterministic
```

All three actual CLI responses reported `state=frozen`, `evidence_origin=DOCKER`,
`scored=false`, and zero unparsed records/errors. No answer key was created.
No model calls were made. Observed results follow.

| Scenario | Imported case | Local / collector lines | Reconciliation | Removal findings |
|---|---|---|---|---|
| complete | `case-0d5f4d3b38d9` | 3 / 3 | `consistent` | 0 |
| missing-local-record | `case-2b946353d70b` | 2 / 3 | `unexplained_local_absence` | 1 |
| benign-gap | `case-4f2dea04b48b` | 2 / 3 | `inconclusive` | 0 |

All six artifact SHA-256 values and sizes matched the manifests. Imported raw
files matched their original bytes, and every normalized event's line and byte
offset resolved to its original record. The fresh raw-bundle hashes were

- complete — `d222ce0d8815b78037c125ae19894c2ca19b8709098abb07fa28b2362ca7b595`
- missing-local-record — `cec1315ddd5d16b93bb19c9dcec53fcb9f3e7c3f8b2d8f5020932c1813c9eded`
- benign-gap — `d82e65c24af93f95f5e488212b28a73e1b9661db66d6da2014b16dc3b642e6eb`

For the removal case, collector receipt was `2026-11-14T17:30:31.375445+00:00`
and the fixture recorded removal at `2026-11-14T17:30:31.376972+00:00`.
The retained original line hashes to
`d0d2b742436219e11b8d8889439185cafa0e814e8af3cac83338026cae99d21d`, matching
both the acknowledgment and the private removal record. That line is absent
from the local copy and present in the collector copy.

The benign local source declared capture bounds
`2026-11-14T17:30:39.411927+00:00` through
`2026-11-14T17:30:42.593081+00:00`, with a known gap from
`2026-11-14T17:30:40.477236+00:00` through
`2026-11-14T17:30:40.481538+00:00`, reason `local sink paused for maintenance`.
The retained middle record's sender time falls inside that gap. The imported
manifest preserved the coverage declaration, and reconciliation reported one
inconclusive absence with zero unexplained local absences.

Actual test output was

```text
35 passed, 13 warnings in 21.04s
```

All warnings were LangSmith's use of deprecated `asyncio.iscoroutinefunction`
under Python 3.14. Compose validation and compilation exited 0. A separate negative
check changed `dummy-1` to `dummy-X` in a temporary copy, preserving file size.
Verification correctly exited 1 with

```text
artifact 'records/var/log/records-app/access.log' does not match its SHA-256 in the manifest
```

The verifier recorded this failure and successfully checked the other two
scenarios. The captured originals were preserved. This deliberate failure checks
that a matching size cannot bypass hash verification.

### Failures and limitations recorded

The fresh run had no unexpected capture, import or test failures. Earlier setup
and implementation attempts encountered these failures, which informed the final
implementation.

- Docker's daemon was initially unavailable. The user started Docker and approved
  downloading the missing `python:3.13-slim` image.
- `docker compose cp` reported that `/data/evidence/.` did not exist on tmpfs.
  Binary `docker compose exec -T` export succeeded and is now used by the runner.
- Initial HTTP tests could not bind localhost under the execution sandbox. They
  passed with localhost socket access enabled.
- A subsecond removal experiment returned `inconclusive` because the shared
  store truncates timestamps to seconds. The final fixture spaces requests by
  1.05 seconds, and the fresh removal run produced the expected finding.

The comparison results are deterministic checks on unscored imported evidence.
The test service supplies no heartbeat stream, so heartbeat-derived collection-gap
measurement is unavailable. The benign control relies on explicitly declared
coverage. This verification covers the three serial synthetic scenarios, raw-byte
integrity, citations and CLI import. Broader evaluation, independent clock skew,
second-machine validation and IoT-CAD remain outside this verified result.

Eric can integrate the capture branch using the existing importer and CLI. No
shared contract, API or CLI change is required. The fractional-second storage
limitation described above is the requested follow-up in Eric's owned code.
