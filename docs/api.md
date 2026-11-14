# API added in phase two

Everything here is implemented and tested on `codex/eric-phase2`. Real responses for each state are in [`api-examples/`](api-examples/), written by `scripts/gen_api_examples.py` from the running application. Types are in `web/src/generated/contracts.ts` (`QuestionAnswer`, `SourceInfo.source_id`, `CoverageGap`). Earlier routes are unchanged.

The server is a localhost demo. Billed and mutating routes have no authentication.

## Runtime capabilities

`GET /api/runtime` now has `capabilities`. "Configured" means settings allow it; it does not mean a model call has succeeded.

| Field | Meaning |
|---|---|
| `capabilities.investigation_modes` | `available`, `labels`, `default` |
| `capabilities.live_model` | `configured`, `model_id` |
| `capabilities.questions` | `model_answers`: `CONFIGURED` or `BLOCKED`; limits |
| `capabilities.source_experiments` | `endpoint`, `max_excluded_sources` |
| `dev_ceiling_usd`, `spend_limit_in_force_usd`, `demo_reserve_open` | spending limits in force |

Examples: `runtime-offline.json`, `runtime-live.json`.

## Fast and specialist investigations

`POST /api/cases` accepts `investigation_mode: "fast" | "specialist"`.

- `fast`: one agent with the deterministic checks. Default for a live model.
- `specialist`: lead, integrity auditor and skeptic. Default for the scripted fixture, and the mode of the recorded Opus run.
- The deterministic runner has no agent, so its mode is `null`.

The mode is saved with the case and returned as `case.investigation_mode` and `case.labels.investigation_mode_label`. Refresh, restart and review resume use the saved mode. Recordings in `GET /api/presets` carry `investigation_mode` too. Example: `case-created-fast-mode.json`.

## Questions

A question is answered by a model with read-only access to this case's evidence, the deterministic checks and the public report. It never changes the report and never sees sealed truth, before or after the reveal.

`POST /api/cases/{id}/questions?wait_s=0..30`

```json
{"question": "1 to 1000 characters", "client_token": "required, at most 80 characters"}
```

Returns a `QuestionAnswer`. With `wait_s=0` (default) it returns at once with `status: "pending"`; poll `GET /api/cases/{id}/questions/{question_id}`. `GET /api/cases/{id}/questions` lists them.

| `status` | Meaning |
|---|---|
| `pending` | being answered |
| `answered` | at least one claim is tied to evidence in this bundle |
| `insufficient_evidence` | the evidence does not establish an answer, or nothing in the answer survived validation |
| `unavailable` | no model is configured, or the spending limit stopped it. `answer` is empty |
| `failed` | no structured answer within three model calls, a refusal, or a provider error. See `error` |

Each claim has `support`, decided by trusted code, not by the model:

| `support` | Meaning |
|---|---|
| `checked` | a deterministic check agrees with the claim for the cited records |
| `contradicted` | a deterministic check disagrees |
| `cited` | the cited records exist in this bundle; that they say this was not machine-checked |
| `interpretation` | the model's reading, offered as such |
| `unsupported` | no valid citation, or the check does not report this |

`claims[].basis` says what the label rests on. `dropped_evidence_ids` lists ids the model cited that are not in this bundle. `trace` lists the read-only tool calls. `inference_mode` is `LIVE_MODEL`, `RECORDED_MODEL` (a saved answer shown in a replay) or `NO_MODEL_BASELINE` (not answered).

Rules a client should handle:

- The same `client_token` always returns the same question. A retry is not charged twice.
- One question at a time per case: a second one while the first is pending gets **409**.
- Allowed in states `frozen`, `awaiting_review`, `report_locked`, `scored`. Otherwise **409**.
- At most 20 questions per case, three model calls per question.
- Empty or over-long text: **422** or **400**.

The predefined explanations at `GET /api/cases/{id}/explanations` are unchanged and stay labeled "Predefined evidence explanation · no model inference". They are not a fallback for a model answer.

Examples: `question-answered-live.json`, `question-insufficient-evidence-live.json` (real model answers on the demo case), `question-unavailable-offline.json`, `question-error-400.json`.

## Source-removal experiment

"Can you still prove it if this witness disappears?" A new case is derived from an existing one with chosen sources withheld. The original case is only read.

Every manifest source has a `source_id` (`manifest.sources[].source_id`, e.g. `src-3f9a…`). Only those ids are accepted, never paths.

`POST /api/cases/{id}/source-experiments`

```json
{"excluded_source_ids": ["src-…"], "client_token": "required",
 "runner": "deterministic | agent-fixture | agent-live (optional)",
 "investigation_mode": "fast | specialist (optional)", "autostart": false}
```

Returns `child_case_id`, both bundle ids and raw hashes, `excluded_sources`, event counts, and `coverage` for the original and the derived view. The derived case starts `frozen` with an empty case directory. It is an ordinary case: investigate, question, review and reveal it through the usual routes. A fresh investigation is a separate run and is not started unless `autostart` is true.

`GET /api/cases/{id}/source-experiment`

- For a derived case (`role: "derived"`): `comparison.claims[]`, one row per claim of the original report, re-checked against the reduced evidence with the same deterministic predicates. No model is involved and nothing sealed is read.
- For an original case (`role: "original"`): its `sources` and `children`.

| `comparison.claims[].change` | Meaning |
|---|---|
| `retains_support` | the check still supports the claim from the remaining evidence |
| `loses_support` | it cannot be established from this view. This is not "it did not happen" |
| `never_supported` | it was not supported in the original either |

Each row has `reason`, `evidence_ids_remaining` and `evidence_ids_withheld`. `comparison.attribution` shows how the account-versus-person assessment changes. `comparison.coverage.child.limits` lists what the reduced view cannot show.

In the derived case, withheld records do not exist: they are absent from the raw files, the event store, search, the checks and every model context. `case.parent_case_id` and `case.excluded_sources` identify it. Its manifest has `capture_complete: false` and a note naming what is not available.

After the derived case's own report is locked and revealed, `reveal.source_experiment.scoring` lists every original effect with `records_in_original`, `records_in_this_view` and an outcome of `caught`, `not_established` or `no_record_in_this_view`, plus two recall figures: of effects that still have a record here, and of all original effects.

Errors: unknown id or an id that is not a manifest source id, withholding every source, deriving from a derived case, or original evidence that fails its hashes: **400**. Original case not frozen yet: **409**.

Examples: `manifest-sources.json`, `source-experiment-created.json`, `source-experiment-derived.json`, `source-experiment-original.json`, `source-experiment-child-reveal.json`, `source-experiment-error-400.json`.

## Coverage fields in existing responses

- `GET /api/cases/{id}/evidence/compare` adds `status_reason` and `heartbeat_coverage`; `status` can be `not_assessable`; each row has `reason` when its status is `inconclusive`.
- Reports from the deterministic and scripted runners add `Coverage limit: …` entries to `open_questions` when a check could not be run.
- `SourceInfo` adds `coverage_declared` and `known_gaps` for captures that state when they were recording.

## Not built yet

Report export (`GET /api/cases/{id}/report-export`) and capture import. Do not show controls for them until they are listed here.
