# Architecture

Status: runs offline end to end; the investigator, question answering and scenario designer are demonstrated on real models (Claude Opus 5.5 in the first run, Claude Haiku 5.5 in the second). Evidence origin: simulated (`SIM`). Every incident is a scripted scenario.

## Components

| Component | Code | Responsibility |
|---|---|---|
| Contracts | `src/alibi/contracts.py` | Typed schemas shared by every module: `Event`, `EvidenceManifest`, `Finding`, `AttributionAssessment`, `InvestigationReport`, `Score` (public) and `AnswerKeyStep`, `TruthEffect`, `AnswerKey`, `EpisodeManifest` (private). Unknown fields are rejected, so truth cannot ride along in a public type. TypeScript types for the UI are generated from them (`scripts/gen_types.py`). |
| SimBackend | `src/alibi/sim/` | Deterministic clinic world on a logical clock. Writes realistic artifacts: auth logs, syslog, an application access log, shell histories, file metadata, flow records, badge records, the collector's forwarded copies and heartbeats. |
| Step library | `src/alibi/sim/steps.py` | The only things the adversary can do. Plans are data, validated against allowlists and precondition order, at most eight steps. |
| Episode builder | `src/alibi/episode.py` | simulate → freeze (write, hash, read-only) → normalize → derived DuckDB (hashed separately) → public manifest → sealed answer key in a separate root. |
| Normalizer and store | `src/alibi/evidence/` | Parses frozen artifacts into events with provenance (artifact, line, byte offset). Unparseable lines stay visible. The store is opened read-only with external access disabled and offers typed filters only. |
| Checks | `src/alibi/checks.py`, `src/alibi/checks_families.py` | Deterministic contradiction checks returning observations with event ids. A source that is not in the bundle makes a check "not assessable": unknown, never clean. |
| Verifier | `src/alibi/verifier.py` | Validates references and recomputes registered predicates. Applied identically to every system. Never adds findings, never reads truth. |
| Scorer | `src/alibi/scoring.py` | One-to-one maximum matching of final accepted allegations to executed, successful, observable effects. Runs only on a locked report. |
| Baselines | `src/alibi/baselines.py` | B0 keyword recipe and BR rule-based findings. |
| Agents | `src/alibi/agents/` | Budget gateway, typed tools, the DeepAgents investigator graph (one agent or three), the scripted fixture policy, the scenario designer, and the disabled adversary planner. |
| Questions | `src/alibi/questions.py` | Bounded question answering over one case with read-only tools; trusted validation of every cited id and claim. |
| Source experiment | `src/alibi/source_experiment.py` | Derives an immutable evidence view with chosen sources withheld and re-checks the original claims against it. |
| Export | `src/alibi/export.py` | The locked report with its hash, provenance and exact cited lines. |
| Orchestrator and API | `src/alibi/orchestrator.py`, `src/alibi/api/app.py` | Case state machine, append-only event log, review, lock, reveal, reset, replay; FastAPI with server-sent events. |
| Case board | `web/` | React + TypeScript, no external assets. |
| Benchmark | `src/alibi/bench.py` | The first-run suites (`offline-v1`, `ai-pilot-v1`), kept as recorded. |
| Evaluation | `src/alibi/evaluation.py`, `src/alibi/calibration.py` | The phase-two paired evaluation (six systems, declared before it ran) and the model calibration check. |

## Episode lifecycle and states

`created → generating → frozen → investigating → awaiting_review → report_locked → scored`, plus `failed` and `cancelled`.

1. **Generate**: the scenario specification (world parameters, benign activity, the adversary plan) is derived from the seed and executed on the logical clock. An anti-forensic step at time *t* can only touch what existed locally at *t*.
2. **Freeze**: artifacts are written, hashed (SHA-256 per file and over the bundle) and made read-only.
3. **Normalize**: events go into one DuckDB file per episode; the writer is closed before the file is hashed.
4. **Seal**: executed steps, their real outcomes and scorable effects are written by the orchestrator to `sealed/<id>/`.
5. **Investigate**: a runner receives a `RunContext` (read-only store, public manifest, case directory, event emitter).
6. **Review and lock**: a human accepts or rejects. Either way the proposal is frozen with its review history and a content hash. Accepting does not certify that anyone is responsible.
7. **Reveal and score**: refused with HTTP 409 until the report is locked. Then the scorer reads the sealed key.

Duplicate Run, review and reveal requests are idempotent. Events carry stable sequence ids and the stream resumes from `Last-Event-ID`. After a server restart, a case awaiting review resumes from its SQLite checkpoint; a case that was mid-run becomes a visible `failed` state.

## Investigation modes

A case is investigated in one of two modes, saved with the case so a refresh, a restart or the review resume cannot switch it.

- **Fast**: one agent with the deterministic checks. The default for a live model, because in the first-run pilot it matched the three-agent graph's accuracy at about a third of the cost and time.
- **Specialist**: a lead that delegates to an integrity auditor and a skeptic. The mode of the recorded Opus run.

Fast mode constructs one model, specialist mode three. A case is never finished by a different model than the one that ran it: if the configured model changed, the review decision still locks the report and the model acknowledgement is skipped.

## Questions

`POST /api/cases/{id}/questions` gives a model at most three calls over read-only tools (evidence search, the checks, the public report) and no way to change the report. The answer is a set of single-fact claims with event ids. Trusted code then drops ids that are not in this bundle, compares each claim with the deterministic check that covers its kind (`checked`, `contradicted`, `unsupported`) and labels the rest `cited` or `interpretation`. An answer with nothing tied to evidence becomes `insufficient_evidence`. Nothing sealed is reachable before or after the reveal. Offline the status is `unavailable`; the predefined explanations stay labeled as predefined.

## Source-removal experiment

`POST /api/cases/{id}/source-experiments` derives a new case from an existing one with chosen manifest sources withheld. The original's bytes, report and sealed truth are only read. In the derived case the source is gone from the raw files, the rebuilt event store, the manifest and therefore from every check and model context; the case directory starts empty. `GET /api/cases/{id}/source-experiment` re-checks each claim of the original report with the same predicates and says which keep support and which can no longer be established, with reasons. For research scoring the executed truth is unchanged and observability is recomputed: every original effect is listed with both recall denominators, so a smaller denominator cannot read as better detection.

## Case families

| Card | Incident variants | Benign controls | What decides it |
|---|---|---|---|
| Inside job | plain, cover-up, covering tracks (four more steps) | forced rotation, approved transfer, remote login, collection gap, maintenance window | host log against collector copy; tap flows against transfer policy |
| Records heist | export from the records server, with or without a cover-up | approved export under a change record | the records application's export trail against change records and the tap |
| Cold chain | stored readings overwritten | a real excursion honestly recorded; sensor maintenance | the hub's stored readings against an independent reference logger |

The four added steps are clearing shell history, backdating a file, stopping log forwarding and hopping to a second host. Each has a legitimate counterpart. Cleared shell history has no independent copy, so it is recorded in the answer key as unobservable and is never scored.

## Scenario designer

`POST /api/scenario-designs` asks a model, once, to choose an ordinary operating environment from fixed options: how busy the day is, one routine operational condition, when it happens, and the cause and length of a collection interruption. There is no field for a step, a command or a destination. Trusted code turns the validated choices into a scenario specification offline. Output outside the options becomes a default that is labeled as a default; a refusal ends the request. An operator may place one of the pre-authored scripted incident scenarios in a designed environment; that choice is never the model's and the case is labeled the same either way until the reveal.

This is not the adversary planner. The one real request to plan an adversary's steps was declined by the model; that route stays disabled and is not rephrased, retried or rerouted.

## Information barrier

What is enforced and tested (`tests/test_m3_agents.py`, `tests/test_m4_api_isolation.py`):

- Investigator-side code is constructed from a read-only `EvidenceStore`, the public `EvidenceManifest` and a case directory. It is never given the sealed directory, the seed, the crime card or the scenario. `baselines.py`, `checks.py` and `verifier.py` do not import the truth-handling modules.
- Each agent's bound tools are audited against an exact allowlist. `execute`, `glob`, `grep` and `delete` are removed from the DeepAgents filesystem middleware; the auto-added general-purpose subagent is disabled through a harness profile; specialists cannot delegate or submit report tools.
- No tool accepts SQL, a path, a URL, a regex or a command. Agent files live in graph state (there is no disk behind them) and permissions allow only `/case/**`.
- A unique canary in the sealed key must not appear in any tool response, transcript, checkpoint, pre-reveal API response or stream event. The investigator event view never contains orchestrator or reveal events, including after reveal.
- A scripted hostile "model" tries the key path, a parent-directory path, a symlink to the key, `/etc/passwd`, `execute`, `glob`, a general-purpose subagent and SQL-shaped filters. All are refused.
- Evidence containing prompt-injection text and HTML is returned as a string, changes nothing in the run, and is rendered as text by the UI.

What this is **not**: an operating-system boundary. Everything runs as one user in one process. A hostile process with file access could read `sealed/`. The claim is about agent capabilities.

## Why deterministic checks plus agents

Deterministic code computes observations under explicit coverage assumptions (retention boundary, bracketing records, heartbeat gaps, destination policy). Models are meant to plan, delegate, interpret and explain, and are never allowed to invent an event, a timestamp or a score. The verifier re-checks every allegation against the same predicates, so a model cannot cite its way into a supported claim.

Whether delegation adds anything over one agent with the same checks (B1+ vs ALIBI) was measured in a small pilot: on 4 cases both were equally accurate and the three-agent system cost about 2.6 times as much (see `docs/benchmark.md`). The offline results show what the engineering does by itself (BR) against a keyword recipe (B0).

## DeepAgents integration (verified against installed deepagents 0.7.38)

- `create_deep_agent` with a lead, two `SubAgent` specs (own model instance, own tools, own filesystem middleware and permissions), `TodoListMiddleware` added explicitly (planning is opt-in in this version), `interrupt_on` for `finalize_report`, and a `SqliteSaver` checkpointer keyed by case id.
- Every model, scripted or real, is wrapped by `BudgetedChatModel`, which reserves and commits each call in one shared persisted ledger and reports `ls_provider = alibi_gateway` so one harness profile applies to all of them.
- Case notes written with the virtual `write_file` exist only in graph state; trusted code exports them to `runs/<id>/case/notes/` afterwards.
- The offline path replaces the model with `ScriptedPolicyModel`, hand-written control flow that reuses the BR templating. It is labeled as a scripted fixture everywhere and can never be recorded as an AI benchmark arm (`bench.validate_ai_run`).
- Three things only a real model exposed, now handled and tested: findings must name their object in an exact form (`check_object_format`), a report tool called in the same turn as `finalize_report` is applied ahead of the review pause and not re-run on resume, and a refusal (`stop_reason: refusal`) is recorded and ends the run as incomplete instead of being retried or rerouted.
- The bounded adversary planner (`agents/adversary.py`) is one planning response plus at most one repair, validated against the step library. With a real model the request was declined; the labeled scripted fallback ran. The model-planned preset is therefore opt-in (`ALIBI_ENABLE_MODEL_ADVERSARY=1`).

## Budget and runtime modes

`RUNTIME_MODE=offline` (default) constructs no network model. Live mode needs an explicit `LIVE_PROVIDER_KIND` (`local`, or `included_credits` with a spend cap and known prices).

- **Total cap.** `LLM_MAX_USD` bounds the estimated cost of every billed call across all runs, processes and models through one file-locked ledger (`.alibi/spend.json`, or the absolute path in `ALIBI_SPEND_LEDGER`). The ledger is carried forward across format, model and price changes, never starts below `LLM_SPEND_FLOOR_USD`, and blocks all spending if it cannot be read.
- **Before a call.** The gateway counts the real outgoing request (system prompt, tool schemas, messages) with the provider's token-counting endpoint plus headroom. A request over `LLM_MAX_INPUT_TOKENS_PER_CALL`, or one that cannot be counted, is not sent. Input tokens, output tokens and worst-case money are reserved in one step, so parallel specialists cannot jointly pass a cap, and the output limit sent to the provider is exactly the output that was reserved.
- **After a call.** Known usage is settled once (settlement is idempotent). A timeout, a lost response, a response without usage or a crashed process leaves the worst-case amount on the books; age never frees it. Only an operator can clear it, with `uv run alibi spend --reconcile <token> --actual <usd>` after checking the console.
- **Development ceiling.** Automatic calls stop at `LLM_DEV_CEILING_USD` (default: the cap minus $0.50). `ALIBI_USE_DEMO_RESERVE=1` is the explicit operator switch for the remainder. One price pair is configured, so every role must use the same model.
- **What this is not.** The ledger is a conservative estimate at configured list prices, not a billing guarantee. The provider console is the authority on actual spend.
- **Caps per investigation**, shared across lead, specialists and retries: 16 model calls, 200,000 input tokens, 10,000 output tokens, 180 seconds; tool results are capped at 50 records and 8 KB. These were revised once from the first measured run (the planning guess of 40,000 input tokens stopped a correct run after 5 calls) and are part of the frozen evaluation config.
- **Model arguments.** For Claude: reasoning effort `low`, 3,000 output tokens per call, no sampling parameters, SDK retries off (the gateway does the single bounded retry and accounts for every attempt), automatic prompt caching for the agent loop.
- One bounded retry for transient errors; credential or credit errors disable the route. No automatic switch to another provider or model. Paid overage is never authorized.
