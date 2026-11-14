# Importing captured evidence

`uv run alibi import <directory>` freezes a capture directory as an **unscored** case. No captured evidence ships with this build; this page describes the entry point a capture has to meet. The importer is `src/alibi/importing.py` (`load_capture`, `import_bundle`, `write_capture_manifest`).

## The capture directory

Original raw files, laid out as `<host role>/<path on that host>`, plus one manifest named `capture.json`:

```json
{
  "format": "alibi-capture/1",
  "capture_id": "lowercase-id",
  "captured_by": {"name": "tool name", "version": "1.2", "image_digests": {"service": "sha256:…"}},
  "capture_start": "2026-11-14T15:00:00+00:00",
  "capture_end": "2026-11-14T15:20:00+00:00",
  "evidence_origin": "DOCKER",
  "artifacts": [
    {"path": "workstation/var/log/auth.log", "sha256": "…64 hex…", "size_bytes": 1234, "origin": "DOCKER",
     "coverage_start": "…", "coverage_end": "…",
     "known_gaps": [{"start": "…", "end": "…", "reason": "agent restart"}],
     "coverage_note": "", "forwarded_to_collector": true}
  ],
  "operational_context": {"logging_policy": {}, "transfer_policy": {}, "accounts": []},
  "notes": []
}
```

Rules the importer enforces:

- Every path is relative, stays inside the directory, is not a link, and is listed once.
- Size and SHA-256 must match the file. A file changed after the manifest was written is refused.
- `evidence_origin` is `SIM`, `DOCKER` or `HYBRID`. If artifacts state different origins the capture must say `HYBRID`. The importer never changes an origin.
- **No ground truth.** Unknown top-level keys are refused. So is any key in `operational_context` named like an answer, however it is spelled (`truth`, `groundTruth`, `Answer_Key`, `labels`, `scenario`, `variant`, `steps`, `attacker`, `is_incident`, …), and any text there or in `notes` that announces one ("ground truth", "answer:", "the answer is"). Keep the record of what a capture fixture did on the capture side. This filter catches honest mistakes; it cannot understand ordinary prose, so what a capture author writes in a note is still their responsibility.
- **No tip.** `operational_context.tip` is refused. Every imported case starts from the same neutral tip, because the tip is the first thing an investigating model reads.
- Artifact paths use letters, digits, spaces and `. _ @ + = , ~ -` between slashes. The name is printed in reports and exports.
- The location must be one the normalizer reads: `…/var/log/auth.log`, `…/var/log/syslog`, `…/records-app/access.log`, `…/mosquitto/mosquitto.log`, `…/collected/collected.log`, `…/.bash_history`, `…/fs_stat.tsv`, `…/badge/*.jsonl`, `tap/flows.jsonl`, `…/sensors/*.jsonl`, `…/coldchain/*.csv`.

Bytes are copied verbatim and made read-only. Lines a parser does not understand stay in the evidence as unparsed records and are counted in that source's coverage note. Nothing is rewritten.

`coverage_start` and `coverage_end`, when given, are a statement by the capture about when a source was recording. The checks honor them: a record outside a stated window, or inside a stated gap, is outside coverage. It is never read as removed.

## What an imported case is

- State `frozen`, card `imported`, `case.scored = false`, `labels.ground_truth = "none · imported evidence is not scored"`.
- It can be investigated, questioned, reviewed, locked, exported and used for a source-removal experiment (the derived view is unscored too).
- `POST /api/cases/{id}/reveal` returns **409**: there is no answer key to unseal.
- It cannot be saved as a replayable recording, because a recording regenerates its evidence from a scenario.
- Import is a command, not an HTTP route, because it reads a path on the machine.

## For a capture that needs new parsing

Formats the normalizer does not read need their own parser. Add it with the capture code, reuse `load_capture` for the manifest and file checks, and hand the frozen episode to `Orchestrator.import_case` or build the case the same way it does. A controlled capture that has a trusted record of what its fixture did can supply scoped ground truth later; until that is designed, imported evidence is unscored rather than given an invented answer key.

## Paste into the capture agent

```text
Deliver captured evidence that ALIBI can import. Read docs/importing.md and docs/next-run/DANIEL.md. You own capture/, src/alibi/capture/, tests/test_capture*.py, docs/capture.md and your fixtures; do not edit src/alibi/importing.py, contracts.py, the orchestrator, the API or the CLI. Ask Eric for a schema change instead.

The receiving side already exists: `uv run alibi import <directory>` takes a directory of original raw files plus capture.json (format alibi-capture/1, described in docs/importing.md), checks every path, size and SHA-256, copies the bytes verbatim and creates an unscored case. Your capture only has to produce such a directory. `alibi.importing.write_capture_manifest()` writes capture.json from files on disk; pass origin "DOCKER" only for artifacts a real process in a container produced, and state coverage_start, coverage_end and known_gaps where collection started late or paused.

Lay artifacts out at locations the normalizer reads (listed in docs/importing.md). If your process logs in another format, add the parser in src/alibi/capture/ and tell Eric the entry point; do not rewrite the raw files to look like simulator output. Keep the record of what your fixture did (which line it removed, when) on your side, outside the capture directory: capture.json is refused if it carries anything that looks like ground truth.

Commit a small captured fixture directory (complete, missing-local-record, benign-gap), tests that import each one, and docs/capture.md with the exact commands. Push codex/daniel-capture.
```
