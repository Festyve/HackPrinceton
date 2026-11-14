# Phase-two interfaces and file ownership

These were the **target contracts** written before the second run. **They are now implemented.** The reference for what exists, with real example payloads, is [`docs/api.md`](../api.md) and `docs/api-examples/`; build against that. Where this page and `docs/api.md` differ, `docs/api.md` is what the server does. Existing routes and fields are backward compatible.

## Product API

- Extend POST /api/cases with optional `investigation_mode: fast | specialist`. Existing runner and client_token behavior remains. Persist mode with the case.
- Add runtime capabilities for questions, source experiments and capture import. “Configured” does not mean a successful model call has been observed.
- POST /api/cases/{id}/questions: `{question: string (1–1000 chars), client_token: string}`. Return question_id, status (answered / insufficient_evidence / unavailable / failed), answer text, claims [{text, evidence_ids, support}], limitations, inference_mode, model_id and usage. An in-progress response may be polled through GET /api/cases/{id}/questions/{question_id}. Same token returns the same operation. No secrets or truth.
- POST /api/cases/{id}/source-experiments: `{excluded_source_ids: string[], client_token: string}`. Only IDs in the public manifest; no paths. Return child_case_id, parent bundle hash, excluded sources and coverage status. Child data goes through the same investigator and evidence APIs.
- GET /api/cases/{id}/source-experiment: parent/child relationship, original claim IDs and deterministic support changes with reasons/citations. No fabricated AI conclusions; before reveal no truth.
- GET /api/cases/{id}/report-export: human-readable downloaded report plus machine-readable manifest if requested. Preserve lock hash and provenance; no answer key in the standard export.

Limits: one active model operation per case, bounded inputs/results, cross-case isolation, safe error objects, no arbitrary filesystem access. This remains a localhost demo; any later public deployment must separately disable or authenticate billed/mutating endpoints.

## Capture handoff

Daniel owns `capture/`, `src/alibi/capture/`, `tests/test_capture*.py`, `docs/capture.md`, and sanitized capture fixtures. Produce an importer module with a documented Python entry point and a neutral input manifest:

- capture ID, tool and image versions/digests, UTC capture bounds;
- each raw artifact's relative path, host role, source kind, SHA-256, size, source origin, coverage bounds and known gaps;
- independent collector delivery/receipt metadata;
- no private ground-truth labels mixed into public evidence.

Eric owns contracts.py, episode.py, orchestrator.py, API routes, CLI wiring and generated TypeScript. Daniel supplies a requested schema diff in his handoff instead of concurrently editing those files. The shared contract already supports SIM / DOCKER / HYBRID; extend only where needed. External data with unknown truth needs an explicit unscored imported-case mode, not a fabricated AnswerKey.

## UI handoff

Terry owns web/ and visual browser assertions. Preserve behavior test IDs or update selectors deliberately. Eric alone regenerates web/src/generated/contracts.ts, then Terry consumes it. UI adapter code belongs in web/src/api.ts; backend shapes do not get invented inside a component.

Save representative JSON fixtures for each new success/error state under a UI fixture directory. Fixtures are development-only and never appear as real findings. Terry delivers a branch/commit and screenshots; Eric merges after API contract checks.

## Merge order

1. Eric's additive schema/API contract commit.
2. Daniel's capture module + Eric's integration.
3. Terry's UI branch after rebasing onto the additive contract.
4. Final real-model recording and complete behavior/browser checks.

No teammate modifies another's owner paths without a short coordination message. Never cherry-pick a whole branch blindly over uncommitted work.
