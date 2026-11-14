# Architecture

Status: OFFLINE-READY, with the investigator demonstrated on a real model (Claude Opus 5.5). Evidence origin: simulated (`SIM`). The adversary is a scripted scenario.

## Components

| Component | Code | Responsibility |
|---|---|---|
| Contracts | `src/alibi/contracts.py` | Typed schemas shared by every module: `Event`, `EvidenceManifest`, `Finding`, `AttributionAssessment`, `InvestigationReport`, `Score` (public) and `AnswerKeyStep`, `TruthEffect`, `AnswerKey`, `EpisodeManifest` (private). Unknown fields are rejected, so truth cannot ride along in a public type. TypeScript types for the UI are generated from them (`scripts/gen_types.py`). |
| SimBackend | `src/alibi/sim/` | Deterministic clinic world on a logical clock. Writes realistic artifacts: auth logs, syslog, an application access log, shell histories, file metadata, flow records, badge records, the collector's forwarded copies and heartbeats. |
| Step library | `src/alibi/sim/steps.py` | The only things the adversary can do. Plans are data, validated against allowlists and precondition order, at most eight steps. |
| Episode builder | `src/alibi/episode.py` | simulate → freeze (write, hash, read-only) → normalize → derived DuckDB (hashed separately) → public manifest → sealed answer key in a separate root. |
| Normalizer and store | `src/alibi/evidence/` | Parses frozen artifacts into events with provenance (artifact, line, byte offset). Unparseable lines stay visible. The store is opened read-only with external access disabled and offers typed filters only. |
| Checks | `src/alibi/checks.py` | Deterministic contradiction checks returning observations with event ids. |
| Verifier | `src/alibi/verifier.py` | Validates references and recomputes registered predicates. Applied identically to every system. Never adds findings, never reads truth. |
| Scorer | `src/alibi/scoring.py` | One-to-one maximum matching of final accepted allegations to executed, successful, observable effects. Runs only on a locked report. |
| Baselines | `src/alibi/baselines.py` | B0 keyword recipe and BR rule-based findings. |
| Agents | `src/alibi/agents/` | Budget gateway, typed tools, the DeepAgents investigator graph, the scripted fixture policy, the bounded adversary planner. |
| Orchestrator and API | `src/alibi/orchestrator.py`, `src/alibi/api/app.py` | Case state machine, append-only event log, review, lock, reveal, reset, replay; FastAPI with server-sent events. |
| Case board | `web/` | React + TypeScript, no external assets. |
| Benchmark | `src/alibi/bench.py` | Runs the frozen offline suite and generates `docs/benchmark.md`. |

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

- **Total cap.** `LLM_MAX_USD` bounds the estimated cost of every billed call across all runs and processes through one file-locked ledger (`.alibi/spend.json`): an estimated amount is reserved before each call and settled after it. Phase-two review identified unenforced request-size assumptions and uncertain-usage/crash gaps; those must be fixed before treating reservations as conservative bounds (see next-run/REVIEW.md). Cost is estimated at list price with conservative cache multipliers; the provider console is the authority on actual spend.
- **Caps per investigation**, shared across lead, specialists and retries: 16 model calls, 200,000 input tokens, 10,000 output tokens, 180 seconds; tool results are capped at 50 records and 8 KB. These were revised once from the first measured run (the planning guess of 40,000 input tokens stopped a correct run after 5 calls) and are part of the frozen evaluation config.
- **Model arguments.** For Claude: reasoning effort `low`, 3,000 output tokens per call, no sampling parameters, SDK retries off (the gateway does the single bounded retry and accounts for every attempt), automatic prompt caching for the agent loop.
- One bounded retry for transient errors; credential or credit errors disable the route. No automatic switch to another provider or model. Paid overage is never authorized.
