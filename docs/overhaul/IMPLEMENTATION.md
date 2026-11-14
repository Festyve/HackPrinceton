# Eric: finish the worker experiment

Read [PRODUCT](../../PRODUCT.md), [STATUS](STATUS.md), [EXPERIMENTS](EXPERIMENTS.md) and [TEAM](TEAM.md). This specifies behavior and checks; choose the implementation details. Preserve historical fixtures and version the new scenario protocol. Do not spend the night rewriting the working evidence engine.

## 1. Establish a shared contract first — 30 minutes

Inspect the latest remote branches and local changes. Keep the current installed dependencies. Record the starting commit, current `alibi runtime`/`alibi spend` totals, remaining allowance and the exact paths each agent owns. Do not print secrets. This task authorizes $20 cumulative API usage, not $20 of new calls.

Review `codex/eric-ui-wiring` with Terry. It already connects questions, source experiments, export, investigation mode, sensor readings, results, designer and spend. Terry should merge or port it before restyling; Eric must not start another competing UI implementation.

Publish additive backend contracts and sample JSON before building the full engine. Extend existing case/event APIs where possible. Exact endpoint names are Eric's choice; document the final names in `docs/api.md`, regenerate TypeScript contracts and add real sample responses. Terry can build from clearly labeled development fixtures until they exist.

Minimum contract:

| Object | Required content |
|---|---|
| Experiment configuration | Version, world seed, scenario, worker count/jobs, normal-work duration, transition policy, rogue permission profile, separate rogue/investigator limits, context-load tier, model/runner provenance |
| Worker view | Stable worker ID, job, current public activity, artifact IDs and execution outcome; no private objective in the investigator view |
| Execution record | Event ID/sequence, simulation tick, wall time, actor, validated action, target object ID, outcome, resulting artifact IDs; truth-bearing fields restricted to operator/truth storage |
| Investigation trace | Run/span/parent IDs, start/end, actor, real tool name, safe argument/result summaries, evidence references, status, usage, plan revision reason; never hidden chain of thought |
| Comparison | Parent/world/action/snapshot/report identifiers, what changed, actual resources used, comparable/unscored status, complete/stopped/refused/failed outcome |

Reuse existing SSE and JSON polling with monotonic sequence numbers. A reconnect resumes from the last sequence; the UI deduplicates. Refresh cannot replay a billed POST. Creation and rerun requests have idempotency keys, cancellation stops future calls, and a cancelled run stays inspectable. Runtime capabilities distinguish supported/configured/available features.

**Pass:** checked-in schema/examples, one fixture renders in Terry's branch, old clients/recordings still load. Do not block frontend progress waiting for paid runs.

## 2. Turn the simulator into a working lab — about 2 hours

Implement a small research-lab preset on the current world and step library. Two or three workers are enough: ingest a synthetic dataset, produce a summary, archive an approved result. Normal work must produce files and independently recorded events before a role transition. Existing clinic scenarios stay available.

Each worker has a goal, a scoped observation, a small action menu and an observe/choose/act loop. Code executes validated actions and returns the real result. Use genuine model decisions in the hero run; batch an observation where practical rather than paying for each log line. Workers do not need full DeepAgent graphs. The external investigator does.

Use an explicit seeded scheduler for time, job arrivals and transition eligibility. Default: one eligible worker changes objective after a few successful normal actions. Support a no-transition control and configurable transition windows; multiple rogue workers are a later preset, not a prerequisite for P2. Record transition selection privately. Keep identity labels neutral so “rogue-worker” cannot become an evidence shortcut.

Define a finite synthetic fault action set, for example: copy an allowed synthetic restricted object to the world's quarantine sink; remove a record from the worker's mutable local log; alter a permitted field in a local record; delete a permitted temporary artifact. Each operation uses object IDs and has preconditions. It cannot touch immutable collector records, sealed truth, another case, host paths, real credentials or an external destination. Vary access using named permissions, not unrestricted shell access.

The privileged scheduler changes the allowed task objective, but does not tell the investigator. A role change is not proof that a fault succeeded. Keep denied/failed actions and legitimate actions distinct. No infinite retries when a worker chooses an impossible action.

Persist an action tape from execution, not from the planned actions. It contains enough validated results to reproduce the world offline. Preserve the distinction between scenario seed (exogenous events), model choices (stochastic) and replay (saved choices). Replaying the tape must reproduce the evidence hashes. Name model-generated and scripted tapes differently in the UI.

**Pass:** normal artifacts exist; a seeded transition occurs; at least one real model chooses a permitted synthetic fault and it produces a recorded effect; failed actions produce no phantom effects; the no-transition control completes useful work; tape replay matches frozen hashes. Deterministic policy fixtures test this cheaply but do not substitute for the live gate.

The optional fault-controller session has [its own scoped instructions](../sandbox-session/CLAUDE.md). If the provider declines the scoped task, record that outcome and complete the surrounding simulator/tests. Do not turn it into a disguised or cross-provider retry. P2 remains pending until a supported live implementation actually works.

## 3. Freeze evidence; keep the observer separate — about 45 minutes

Reuse the existing bundle/manifest/check pipeline. Add independently recorded job assignment, account/session and transfer-policy artifacts so a worker can be linked by evidence rather than by the answer key. The investigator sees only what survived collection. Collector availability, clock skew and delayed shipping must have explicit semantics; a lost record before shipment is not recoverable from an imaginary copy.

Maintain three capabilities: mutable simulated world, read-only evidence bundle, and private controller/scorer truth. Investigator notes are writable in their own case namespace; evidence is not. A separate OS process is optional for this in-memory simulator, but capability separation is mandatory. Describe the actual isolation accurately.

An operator-only action timeline can explain the attack in a presentation. Keep it outside the evidence API, prompts, delegated tasks and public investigation trace. The scored reveal remains locked. Do not serialize the private tape or transition metadata into frontend state shared with investigator requests. Treat model questions after reveal as evidence-only too.

Test forbidden accesses using all new routes and actual prompt/tool payload capture: path traversal, cross-case IDs, raw truth-file requests, metadata leakage, evidence text posing as instructions and malicious-looking filenames. Escape artifacts as text. Reject the capability in code, not just in a prompt.

**Pass:** model input audit shows no answer-bearing fields; immutable hashes survive investigation/questions; reveal before lock fails; imported unscored cases still cannot reveal a nonexistent answer.

## 4. Make the DeepAgent investigation adapt — about 90 minutes

Keep the current `create_deep_agent`, explicit harness profile, tools, case-scoped StateBackend and SQLite checkpoints. Replace the rigid eight-step script with a bounded evidence-driven loop: identify current uncertainties, choose useful next evidence, update the case file, delegate when a distinct specialist task helps, revise the plan on contradiction, stop when supported or limited by resources. Do not insist that every small case uses every specialist.

For the hero long-horizon case, require these genuine behaviors:

1. The lead creates a short plan and hypotheses from the brief, without truth access.
2. It delegates timeline reconstruction and/or independent corroboration with a focused task and evidence references. Subagents get only the case capabilities and budget they need. They return concise findings and uncertainty, not their whole transcript.
3. A conflict causes an actual new task or changed priority. Example: the local file export lacks a record while a collector copy survives; investigate policy, collection coverage and account/job binding before attributing it. The decision must follow the observed tool output, not a timer.
4. It writes a compact case file (questions, hypotheses, evidence index, findings and unresolved issues), then later reads a saved fact needed for the next step. Use references to evidence, not duplicated raw log dumps.
5. It resumes from a checkpoint in a new process with the same case state, performs a further evidence action and retains correct citation links. Verify this before calling it long-horizon persistence.
6. It produces a report separating observations, interpretation and unresolved alternatives. A skeptic can challenge a finding, but a correct deterministic observation cannot silently disappear without an explicit, inspectable reason. A check proving a missing line does not itself prove malicious intent.

Pagination and bounded tool outputs keep root context finite. On-demand evidence retrieval stays available after any summarization. Record actual input/output tokens, peak request size, delegated work and file reads/writes. If a compaction event is shown, it must be an actual middleware event. A tested small context ceiling is a controlled pressure test; do not claim the model's physical context window overflowed.

Use `EXPERIMENTS.md` to compare fast mode and the full workflow. Do not force multi-agent success with an oracle, favorable seeds or weaker baseline limits.

**Pass:** one real trace proves all six behaviors; context-pressure run has complete resource accounting; an interrupted run resumes; harmless evidence prompt injection is inert. Label action summaries as summaries, not model thoughts.

## 5. Resource experiments — about 60 minutes, then Daniel validates

Implement the explicit allocation profiles in `EXPERIMENTS.md` with independent permission and context controls. Apply nested caps: cumulative ledger → experiment → side → run. Include all lead/subagent/worker decisions, retries and uncertain costs. Budget errors produce an inspectable stopped result, not an automatic fresh run.

Cache a frozen world/action tape for repeated investigator comparisons. Never regenerate it invisibly when a slider changes. A permission comparison creates a child execution with lineage. Report both budget allowed and budget consumed. A side which finishes early does not donate unspent calls to the other side.

**Pass:** all profiles produce valid terminal outcomes, including low-budget abstention; same-evidence comparisons share exact hashes; new executions have distinct IDs; deterministic baselines remain available; Daniel can reproduce the manifest without a key.

## 6. Integrate, record and release

Merge Terry's completed UI and Daniel's fixtures/protocol through the owner branches. Run meaningful regression checks: existing offline suite, new simulation boundaries, accounting under concurrent/cancelled calls, replay hashes, resumed investigations, and browser paths. Do not blindly assert old test counts. Build the frontend and launch a clean second-machine checkout without `.env`.

Record a new complete worker experiment and a benign control using the budgeted real route. Keep all historical replays. Playback must show configuration, model/version, saved action tape, trace and report; it must remain visibly recorded. Pin the release commit and capture its actual screen for the demo.

Update README, claims, API, PROGRESS and ACCEPTANCE from observed behavior. Preserve history and unfavorable outcomes. Required final handoff: exact launch command; current commit; accepted P1–P10 evidence; cumulative spend/open reservations; live/recorded/fixture labels; remaining concrete defects; 2-minute demonstration path and recovery.

## Execution discipline

Use one coordinating coding agent. At most two bounded helpers at a time can work on disjoint simulation and validation tasks after the API contract is fixed. Assign model tiers only from installed available choices; do not spend setup time installing another orchestrator. Terry's agent owns the UI separately. The coordinator reviews integration and is responsible for completion.

After 20 minutes without a new diagnostic result, narrow the failing slice and preserve a runnable checkpoint. This is not permission to declare an unmet product gate complete. At feature freeze, stop adding breadth and finish the integrated path. Never reset Git, overwrite teammate changes or discard the original product to make the status green.
