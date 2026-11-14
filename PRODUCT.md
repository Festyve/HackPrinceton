# ALIBI — product contract

**Team-approved direction, November 14, 2026.** This defines what to build next. It supersedes older product directions, not their implementation or measurements. See [the audit](docs/overhaul/STATUS.md) for what actually exists today and [START HERE](docs/overhaul/START_HERE.md) for each person's launch instructions.

## The product in one paragraph

ALIBI is a controlled research lab for investigating misbehaving AI workers. Workers ingest synthetic datasets, prepare reports and archive approved files. A seeded experiment can change a worker's objective partway through its normal work, allowing bounded sabotage inside the simulated environment. A LangChain DeepAgent outside that environment investigates a read-only evidence snapshot, builds a case file, delegates evidence work and follows conflicting records. An operator varies the resources available to the rogue worker and investigator, then compares evidence-backed conclusions with sealed ground truth.

The intended user is a security researcher or an engineer evaluating agent systems. The daily-use loop is **configure → run → investigate → inspect evidence → compare experiments → export**. The scientific question is: **under which resource and evidence conditions can an investigator reconstruct an AI worker's misconduct without accusing an innocent worker?**

## Required behavior

| ID | Requirement | Evidence required to call it complete |
|---|---|---|
| P1 | Workers perform useful normal jobs before a fault | At least two identifiable workers, each with a goal and recorded observe/choose/act outcomes; normal work produces inspectable artifacts. The hero live run includes genuine model-selected worker actions. |
| P2 | A worker can become rogue at a seeded time | The scheduler records the worker, transition tick and policy version privately. The model chooses among permitted synthetic actions; execution records success, failure and denial. A timestamped animation alone does not count. |
| P3 | The investigator operates outside the sandbox | Separate evidence/notes/truth interfaces; immutable snapshot hashes; no truth or worker-private objective in its prompts, tools, metadata or replay input. It cannot alter source evidence. |
| P4 | DeepAgents supplies a real investigation workflow | Actual planning, bounded case-file writes and later reads, specialist delegation, and a plan revision responding to an observed conflict. Each is visible in the recorded tool trace. No invented thoughts or simulated delegation in an AI-labeled run. |
| P5 | Resource imbalance is configurable | Reproducible 80/20, 50/50 and 20/80 allocation presets expose their exact units. Rogue permissions, investigator resources and evidence volume are separate settings. No unexplained “intelligence” slider. |
| P6 | Results are inspectable and scored after commitment | Each accepted claim opens exact evidence; account attribution is separated from human identity; unsupported cases can remain unresolved. Lock the report before revealing the truth or scoring. |
| P7 | There is a benign control | Similar export/log-gap activity with legitimate authorization or a collection failure; investigator must distinguish it from misconduct. Record false allegations, misses, abstentions and stopped runs. |
| P8 | Runs can be replayed and compared honestly | Save configuration, versions, action tape, snapshot hashes, public trace and report. Replay reproduces the saved run; a fresh LLM execution is not promised identical just because the seed matches. |
| P9 | A human can understand the interface | Show ordinary work, the experiment, the investigation and its supporting evidence. Terry's visual reference and Rayan's sketch govern presentation; all existing technical features remain reachable. |
| P10 | The release runs within constraints | Cumulative API cap $20, development cutoff $19.50, preserved ledger; offline playback; no secrets in Git; two-minute demo; submit by Sunday November 15, 08:00 ET. |

P1–P10 are release gates, not claims that this documentation change implemented them. A scripted regression fixture is useful but cannot satisfy the live worker/rogue gates. A failed or refused model run remains a failed/refused run, never relabeled as live success.

## Keep the good engineering

Keep the simulator, frozen bundles, deterministic checks, baseline systems, budget gateway, recordings, checkpoint/review flow, imports, questions, source-removal experiments, exports and historical results. Existing clinic cases remain regression scenarios and secondary demos. Add a research-lab preset and worker lifecycle on the existing machinery. Do not rebuild the app, remove useful detectors, or erase an unfavorable result to manufacture a model advantage.

The new home workflow is the worker experiment. Existing standalone case investigations and captured bundles stay available in the case library. Docker capture is useful validation, not a prerequisite for the simulation. No extra cloud deployment, paid service, large forensic dataset download or framework migration is required.

## Boundaries and honest claims

- The world contains synthetic organizations, accounts and files. “Export” means copying to a named sink inside this simulated world; it is not an internet transfer. Fault tools cannot operate on host paths or credentials.
- The trusted host may contact the configured model provider through the existing budget gateway. Worker tools have no network, shell or arbitrary execution capability. Distinguish these two boundaries.
- The demo operator may view the action tape, but investigation requests receive only the evidence view. Hide the operator's truth-bearing data from investigator-facing APIs until report lock, not merely with CSS.
- A worker ID, account and person are different entities. Attribute to a worker only if independent evidence supports the link. Sealed truth scores the answer; it does not supply the answer.
- A model choosing steps is different from code executing them. Describe both accurately. Refusal is an observable terminal outcome; do not disguise the request or change providers to defeat it.
- DeepAgents provides the planning, filesystem and delegation mechanisms this workflow uses. Do not say this is impossible without that library, or that more agents are more accurate. Existing results favor the single agent with checks on the small evaluated cases.
- A case file within one checkpointed investigation is not evidence of learning across investigations. Do not claim self-improvement, production incident response or real-world forensic accuracy.

## Change control

The implementer chooses module structure, sandbox internals, specialist roles, model scheduling and concrete UI components. Log consequential choices in `DECISIONS.md` with the relevant P-number, reason and validation. Do not substitute a new product, add unrelated sponsor integrations or silently downgrade a required behavior. Put new ideas after the release gates. Rayan owns changes to this contract; Eric integrates code; Terry owns `web/`; Daniel owns independent cases and experiment validation.

Judge the implementation by the saved run and its artifacts, not by the number of agents, tests or dashboard cards.
