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
- **No ground truth.** Unknown top-level keys are refused, and so is any key in `operational_context` named like an answer (`truth`, `labels`, `steps`, `attacker`, `is_incident`, …). Keep the record of what a capture fixture did on the capture side.
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
