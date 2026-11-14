# API added in phase two

Everything here is implemented and tested on `codex/eric-phase2`; the worker-lab routes at the end are on `codex/eric-overhaul`. Real responses for each state are in [`api-examples/`](api-examples/), written by `scripts/gen_api_examples.py` from the running application. Types are in `web/src/generated/contracts.ts` (`QuestionAnswer`, `SourceInfo.source_id`, `CoverageGap`). Earlier routes are unchanged.

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

`GET /api/spend` returns the cumulative spend estimate for a status display: `cap_usd`, `limit_in_force_usd`, `spent_usd`, `unreconciled_usd`, `reserved_usd`, `remaining_to_limit_usd`, `calls` and counts of open items. Totals only. With no billed route it returns `{"configured": false}`. It is an estimate at configured prices, not a bill.

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
| `checked` | a deterministic check agrees with the claim for the cited records. A claim about which account a session belongs to is `checked` only when the account and session it names are the ones in the cited login record; naming another is `contradicted` |
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

A derived case shares its original's answer. `POST /api/cases/{child}/reveal` returns **409** until the original case's report is locked (or the original has been reset), so nobody can see the answer while the original report can still be changed.

`client_token` is matched only against experiments of the same original case: a retry returns the same derived case, and two requests that arrive together with one token make one case.

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

## Two temperature records

`GET /api/cases/{id}/evidence/sensor-streams` — for a cold-chain case, the readings stored on the hub beside the independent reference logger. Read from the case's own evidence; no model is involved and nothing sealed is in it.

| Field | Meaning |
|---|---|
| `applicable` | `false` for a case that states no cold-chain policy; then only `status: "not_applicable"` and `status_reason` |
| `status` | `consistent`, `discrepancy_explained`, `discrepancy_unexplained`, or `not_assessable` when one of the two records is not in the bundle |
| `series[]` | `key` (`stored`, `reference`), `label`, `present`, `host`, `artifacts`, `tamper_exposure`, and `points[]` of `event_id`, `ts`, `temp_c`, `seq` |
| `permitted_range_c`, `maintenance_windows[]` | the stated policy: the range, and each window's `id`, `start`, `end`, `note` |
| `discrepancies[]` | intervals where the reference disagrees with every nearby stored reading: `start`, `end`, both temperature ranges, `classification` (`unexplained`, `explained_maintenance`, `isolated_reading`) and the record ids on both sides |
| `excursions[]` | intervals where the reference left the permitted range, with `local_agrees` |
| `coverage_limits`, `assumptions`, `limits` | what could not be checked, what the comparison assumes, and what it cannot show |

Every `event_id` opens through `GET …/evidence/events` like any other citation. In a derived case with the reference logger withheld, its series is empty and marked `present: false`, and `status` is `not_assessable`. `capabilities.sensor_streams` in `GET /api/runtime` announces the endpoint. Example: `sensor-streams-cold-chain.json` (points shortened).

## Coverage fields in existing responses

- `GET /api/cases/{id}/evidence/compare` adds `status_reason` and `heartbeat_coverage`; `status` can be `not_assessable`; each row has `reason` when its status is `inconclusive`.
- Reports from the deterministic and scripted runners add `Coverage limit: …` entries to `open_questions` when a check could not be run.
- `SourceInfo` adds `coverage_declared` and `known_gaps` for captures that state when they were recording.

## Exports

All three are downloads (`Content-Disposition: attachment`).

`GET /api/cases/{id}/report-export?format=markdown|json` — available once the report is locked (`report_locked` or `scored`), otherwise **409**. `markdown` is the readable report; `json` is the machine-readable manifest it is rendered from: the locked report as stored, `lock.report_sha256` (and a recomputed value to compare), model, mode and playback labels, every source with its hash, and every cited record with its artifact, line number and exact text. It never contains the sealed answer, the score or the reveal, before or after unsealing.

`GET /api/cases/{id}/questions-export` — the case's questions and answers, separate from the report.

`GET /api/cases/{id}/reveal-export` — the unsealed answer and score. Only after the reveal (**409** before), and only through this explicit request.

`capabilities.report_export` in `GET /api/runtime` announces the endpoint.

## Scenario designer

A model chooses an ordinary operating environment from fixed options. It plans no incident: there is no field for a step, a command or a destination. The earlier adversary-planning route is a different feature and stays disabled.

`POST /api/scenario-designs` with `{"client_token": "required", "design_seed": 0..4999 (optional)}` makes one bounded model call and returns a stored design:

| Field | Meaning |
|---|---|
| `status` | `designed`, `default_used` (no model configured, or its output was not valid), `refused`, `unavailable` (spending limit) |
| `source` | `model_designed`, `default`, `default_after_invalid_output`, `none` |
| `label` | the text to show, e.g. "Environment chosen by a model (…) from fixed options. It planned no incident; …" |
| `design` | `background_activity` (quiet, normal, busy), `routine_condition`, `condition_time`, `interruption_cause`, `interruption_seconds` |
| `preview` | the design in plain sentences, for a person to read before generating |
| `fixtures` | the pre-authored scripted incident scenarios an operator may place in it |

`GET /api/scenario-designs/{design_id}` returns it again. The same `client_token` returns the same design without a second model call.

`POST /api/cases` with `design_id` (and optionally `design_fixture`: `none`, `inside-job-plain`, `inside-job-coverup`) generates a case in that environment, offline. Its title, difficulty (`sealed`) and `seed` (the design seed) are the same whether or not a fixture was placed in it. The evidence is generated from a fixed design, so someone who generates all three variants themselves can still compare hashes; the case record does not give it away. After the reveal, `reveal.truth.environment_provenance` shows what was requested, what the simulator realized, and `incident_steps_chosen_by_model: false`; `plan_label` stays "Scripted scenario · no model chose these steps". A refused design cannot become a case (**409**).

## More cases and results

- `GET /api/presets` lists recordings with the presentation default first (`replays[].presentation_default: true`, the specialist run on Claude Opus 5.5), then the other recorded model runs, then scripted fixtures. Feature the marked one; do not rely on the title.
- `GET /api/presets` lists six more presets: `evasion`, `maintenance-control`, `records-heist`, `records-control`, `cold-chain`, `cold-chain-control`. `card.id` is `inside-job`, `records-heist` or `cold-chain`. Their evidence has two more source kinds, `sensor` and `reference`.
- Reports on those cases can carry more claim types: `timestamp_alteration`, `forwarding_stopped`, `second_host_session`, `sensor_stream_discrepancy` (allegations) and `shell_history_gap`, `metadata_change`, `temperature_excursion`, `sensor_maintenance`, `policy_consistent_access` (notes). An effect that no captured source can show has outcome `unobservable` in the reveal.
- `GET /api/benchmark` adds `paired_v2`: the latest result of the phase-two evaluation (six systems, four new cases), or `null`. It is a separate suite and is not merged into the first-run tables.
- `GET /api/benchmark` adds `paired_summary`: the six systems summed over that suite and its separately declared replication (six cases), or `null`. `systems[]` has `id`, `label`, `cells`, `censored` (runs stopped by a budget cap) and `aggregate` with `step_recall`, `coverup_detected`, `benign_false_alert`, `false_claims_final`, `unsupported_named_attribution` and `cost_estimate_usd`. `correct_findings_not_counted[]` lists findings that matched an executed effect but were not accepted, and why. `note` states that these are sums of one run per cell, not an accuracy estimate; show it with the table.

## Imported evidence

`uv run alibi import <directory>` freezes a capture directory as an unscored case ([format and rules](importing.md)). It is a command, not a route. An imported case appears in `GET /api/cases` like any other, with `case.scored: false`, `card.id: "imported"` and `labels.ground_truth` starting with `none`. Reveal returns **409** for it. Each source in its manifest keeps its own `origin` (`SIM`, `DOCKER`, `HYBRID`). `capabilities.capture_import` describes this. No captured evidence ships with this build.

## Worker lab

Implemented on `codex/eric-overhaul`. Real payloads: `api-examples/lab-*.json`, written by `scripts/gen_lab_examples.py` (offline, so those examples are labeled scripted fixture and deterministic checks). A lab run is an ordinary case once it is frozen: every existing route (events, evidence, questions, source experiment, review, reveal, export) works on it.

**What a run is.** Three automated workers (`W1` ingest, `W2` summarize, `W3` archive; accounts `wk-ingest`, `wk-report`, `wk-archive`) do jobs a scheduler assigns. In an `incident` run the scheduler changes one worker's objective part-way through, and that worker takes bounded fault actions. In a `control` run nothing changes and similar approved work happens. Ordinary work is chosen by the configured model, or by a scripted fixture when no model is configured. **A changed objective always follows a scripted policy. No model is asked to choose a fault action**, and the labels say so.

| Route | What it returns |
|---|---|
| `GET /api/lab/options` | Variants, the three presets with their units, permission profiles and their actions, context loads, which kind of ordinary work is available, defaults |
| `POST /api/lab/experiments` | Runs the workers once, freezes the result, returns `{case, lab}`. Body: `variant` (`incident`, `control`), `seed?`, `preset?` (`offense_heavy`, `balanced`, `defense_heavy`), `rogue_permissions?` (`export_only`, `export_log`, `export_log_artifact`), `rogue_requests?`, `investigator_requests?` (at most the server's per-run cap), `context_load?` (`light`, `standard`, `heavy`), `ordinary_work?` (`model`, `scripted`), `runner?`, `investigation_mode?`, `client_token` (required), `autostart` (default false). With a model this makes up to 18 small model requests before it answers, so expect several seconds. The same `client_token` returns the same case and is never billed twice. **409** if `ordinary_work: "model"` is asked for and no model is configured |
| `GET /api/cases/{id}/lab` | `config` (workers, ticks), `conditions`, `provenance`, `lineage`, `activity` (what the collector recorded for each worker: `event_id`, `worker`, `account`, `t`, `action`, `dataset`, `status`), `scheduler_records`, `operator_record.available`. Built from the case record and the frozen evidence only |
| `GET /api/cases/{id}/lab/operator` | Every attempted action with its real outcome (`records[]`: `seq`, `tick`, `t`, `worker`, `objective`, `action`, `target`, `status` = `succeeded`, `failed` or `denied`, `outcome`, `artifacts`), the `transition` (worker, tick, time), permissions and allowances. **409 until the report is locked** |
| `POST /api/cases/{id}/lab/comparisons` | A second run that changes one thing; `lineage.changed` lists everything that differs. `kind: "investigator_budget"` with `investigator_requests` (must differ): the same frozen evidence (equal bundle id), a different request allowance. `kind: "runner"` with `runner` (must differ): the same evidence, a different investigator. `kind: "workflow"` with `investigation_mode` (`fast` or `specialist`, different from the first run's): the same frozen evidence, one agent against three. `kind: "rogue_permissions"` with `rogue_permissions` (must differ): a new execution on the same seed with the first run's ordinary work replayed; its evidence may differ. **409 until the first run's report is locked and no other run of the experiment has an open report**, because whether the evidence differs says whether anything was changed (`docs/api-examples/lab-comparison-new-execution-before-lock-409.json`). Body also takes `runner?`, `client_token` (required), `autostart` |
| `GET /api/cases/{id}/lab/comparisons` | The first run and every run derived from it: `lineage`, `conditions`, `bundle_id`, `outcome` (`not investigated`, `running`, `complete`, `stopped`, `failed`, `cancelled`), `stop_reason`, `allowed`, `used` (requests, tokens, cost, seconds), `findings`, and `scored` once that run is unsealed |

**On the case record.** A lab case has `case.card_id = "worker-lab"`, `case.lab` (the same `config`, `conditions`, `provenance`, `lineage`) and two extra labels: `labels.worker_choices` and `labels.changed_objective_policy`. Show both wherever the inference label is shown. `conditions.investigator_requests` is the investigator's model-request allowance for that run; a run that reaches it ends as an incomplete report and says so in `report.open_questions` ("Incomplete run: ...").

**The worker link.** On a lab case `report.attribution` has two more fields: `worker_id` and `worker_link_evidence_ids`. They say which worker the scheduler's own records assign the account to, and cite those assignment records. It is a link between a credential and a worker's jobs: the statement beside it says that the records do not show which process used the credential, and nothing here is about a person. A link the records do not support is removed when the report is verified. The check behind it is the tool `check_job_assignments` (auditor, skeptic, one-agent mode and question answering, on lab cases only) and it also lists each recorded action by a worker account that no assigned job explains. After the reveal, `score.worker_link_correct` is true, false, or null with `worker_link_na_reason`. Show the account and the worker as two separate lines.

**What stays sealed.** Nothing public says whether a run is an incident or a control, which worker changed, or when: not the case record, the lab view, the manifest or the event stream. An incident and a control on the same seed differ in nothing public but ids and evidence. Until the report is locked: `case.seed` is null and `config.world_seed` is absent (the seed regenerates the scenario); `provenance.ordinary_requests` and `provenance.worker_usage` are null (a changed worker stops being asked, so the count differs); they appear in `GET /api/cases/{id}/lab` once the report is locked. **No run of an experiment can be unsealed while another run of it has a report that is being written or awaits a decision**: the reveal and the operator's record answer 409 and name the open run, and the comparisons table withholds scores (`scores_withheld: true`). Lock every run's report first. The operator's record and `reveal.truth.lab` open when the report is locked, like the answer key. To drive an operator's own screen during a presentation, start the server with `ALIBI_OPERATOR_VIEW=1`; the investigator is never given that record either way. Do not copy it into anything that is sent with a question.

**Units.** A preset splits a pool of 20 requests: `offense_heavy` 16 for the changed worker and 4 for the investigator, `balanced` 10 and 10, `defense_heavy` 4 and 16. One unit is one model request for the investigator and one scripted turn for the changed worker. Show the numbers beside the preset name. An allowance is not a probability, and unused requests are not passed to the other side.

```ts
type LabConditions = { preset: string | null; preset_label: string; rogue_requests: number; investigator_requests: number;
                       rogue_permissions: "export_only" | "export_log" | "export_log_artifact"; context_load: "light" | "standard" | "heavy" };
type LabLineage = { root_case_id: string; parent_case_id: string | null; comparison: null | "investigator_budget" | "runner" | "workflow" | "rogue_permissions";
                    changed: null | Record<string, { from: unknown; to: unknown }>; note?: string; same_evidence_as_parent?: boolean };
type LabActivity = { event_id: string; worker: "W1" | "W2" | "W3"; account: string; t: string; action: string; dataset: string | null; status: string | null };
type LabOperatorRecord = { seq: number; tick: number; t: string; worker: string; account: string; objective: "normal" | "changed";
                           action: string; target: string | null; status: "succeeded" | "failed" | "denied"; outcome: string; artifacts: string[] };
```

## The investigation's trace

`GET /api/cases/{id}/trace` works for any case. It is built from the case's event log and nothing else:

- `spans[]`: the run, each delegation and each tool call, with `span_id`, `parent_id`, `kind` (`run`, `delegation`, `tool`), `actor`, `tool`, `arguments`, `result_summary`, `evidence_ids`, `status`, `start_seq`.
- `plan[]`: each version of the investigator's plan with `items[]`, what was `added` and `removed` against the version before (raw), which of the added items are `added_new` or `reworded`, and `after` (the last recorded result before that version).
- `case_file[]`: each write, edit and read of a case file, in order.
- `behaviors`: three separate facts, `plan_recorded`, `examined` and `plan_recorded_before_first_examination` (null when either of the first two is false; `planned_before_examining` is kept and is true only when the third is true); `delegations[]` with `status` (`finished`, `running` while the case is being investigated, or `not finished in the log`) and `closed_by` (set to `unnamed finish event` when the log's finish event named no agent, as after a resume, and the oldest open delegation took it); `plan_revisions[]` (only versions that add an item that is new, with `added_new`, `reworded` as `{from, to}` pairs and `removed`; ticking items off, rewording and dropping items are not revisions); `case_file` (`writes`, `reads_after_a_write`), `resumed` (`times`, `tool_calls_after_resume`). `version` is `trace/2`. A plan and a first examination recorded from the same model turn are ordered by the log, not by intent.
- `plan_written_by`: the model, a scripted fixture, or fixed code. Show it: a checklist written by code is not a plan.

Summaries are the tools' own return summaries. Nothing is a model's reasoning, and "after" is the recorded order, not a claimed cause.

## Resuming an interrupted investigation

`POST /api/cases/{id}/resume` with optional `{"extra_requests": n}` continues an agent's investigation that was cancelled, failed, or stopped incomplete (a cap or the turn limit). It continues from the last saved checkpoint with the same messages, case file and recorded findings; the step that was in progress when it was interrupted runs again. What was already used stays counted, and `extra_requests` is how many more model requests it may make, never beyond what this server allows one investigation in total; the token caps are not raised. On a lab case the grant is recorded in `lab.conditions.extra_requests_granted` and shown in the comparisons table. A decision on a run that stopped before asking for review is recorded without restarting it; only this route continues it. If a resume fails, the earlier draft stays reviewable. **409** for a finished investigation, a recording, or a run with no agent. The event log gets a `stage` event named `resume`, and the trace reports it.

## Lab runs as recordings

A lab run saved with `uv run alibi lab run ... --save-as <name>` is listed with the other recordings in `GET /api/presets`. A recording's name, title and note should not say whether anything was changed in it: they are public before the replayed report is locked. The three shipped ones are `lab-run-a-three-agents-haiku-5-5`, `lab-run-b-one-agent-haiku-5-5` and `lab-run-c-one-agent-haiku-5-5`. Opening it regenerates the evidence by replaying the saved action tape (the bundle hash must match or the case fails), rebuilds `case.lab` from the scenario rather than from what the file says about itself, and replays the recorded investigation. Its `labels.worker_choices` then reads "recorded choices of a model", never "live".

## Lab commands

```sh
uv run alibi lab options
uv run alibi lab run --variant incident --preset balanced --investigate      # prints the case id and the findings
uv run alibi lab operator <case-id>                                          # after the report is locked
uv run alibi lab compare <case-id> --kind investigator_budget --investigator-requests 4 --investigate
uv run alibi lab compare <case-id> --kind workflow --mode specialist --investigate
uv run alibi lab compare <case-id> --kind runner --runner deterministic --investigate
uv run alibi lab compare <case-id> --kind rogue_permissions --permissions export_only --investigate   # after the report is locked
uv run alibi lab table <case-id>
uv run alibi trace <case-id>
uv run alibi investigate <case-id> --resume --extra-requests 12
```
