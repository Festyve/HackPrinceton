# ALIBI

**Red-teaming AI forensic investigators.**

An AI worker goes rogue and covers its tracks. A LangChain DeepAgent rebuilds what happened from the logs it left behind, and its report is scored against a sealed record of what the worker actually did.

Live demo (recorded runs, no key needed): **https://whats-the-alibi.us** · Built at HackPrinceton Fall 2026 by Eric Chen, Rayan, Daniel and Terry.

![The lab: three workers in a sandbox, one gone rogue, and the investigator outside it](docs/screenshots/readme/lab.png)

## Why

Companies are starting to point AI agents at incident logs and ask them what happened. Nobody has a way to test those agents. A real incident has no answer key, so you can't tell whether the agent was right, missed something, or blamed the wrong worker. ALIBI makes incidents where the answer is known and hidden, so an investigator can be measured.

## How a run works

1. **Workers do their jobs.** Three automated workers (ingest, summarize, archive) do ordinary data jobs inside a sandbox. Their routine work is chosen by a real model.
2. **One goes rogue.** Partway through the day the scheduler changes one worker's objective. It copies restricted datasets out to an unapproved address and deletes the matching lines from its machine's `access.log`. These actions follow a scripted policy; no model chooses them.
3. **The evidence is frozen.** Everything the run left behind is hashed and handed to the investigator: the host log, a collector's forwarded copy of it (the workers can't write to that), network flows, change records and job assignments. What really happened goes into a sealed answer key the investigator's tools can't reach.
4. **The investigator works it out.** A DeepAgent plans with `write_todos`, keeps notes in its virtual filesystem, and, in Specialists mode, hands work to an integrity-auditor and a skeptic subagent. Deterministic checks flag the leads: lines the collector kept but the host lost, bulk transfers to addresses that aren't approved, actions that don't match any assigned job. The agent decides what each lead means, tests innocent explanations (log rotation, approved exports, collection gaps), ties the activity to an account and a worker, and writes a report where every claim cites evidence lines.
5. **Lock, reveal, score.** A human accepts or rejects the report, which locks it. Only then is the answer key unsealed and the report scored: which real effects it caught, what it missed, and any false allegations.

![Findings, each with the host and collector lines side by side](docs/screenshots/readme/investigation.png)

## Red-team controls

- **Power balance.** A 20-unit pool split between the rogue (how many actions it gets) and the investigator (how many requests it may make). Presets go from 16/4 to 4/16.
- **Solo or Specialists.** One agent, or a lead with an auditor and a skeptic.
- **Experiments.** Rerun the same evidence with one thing changed (investigator budget, rogue permissions, lineup) and compare what was caught.
- **Remove a witness.** Drop an evidence source, such as the collector, and see which conclusions still stand.
- **Ask a question.** Each claim in the answer is marked as confirmed by a check, merely cited, or the model's own interpretation.

| The investigation trace | The scored result |
|---|---|
| ![Plan, delegations and tool calls from the recorded run](docs/screenshots/readme/trace.png) | ![Locked report scored against the sealed record](docs/screenshots/readme/result.png) |

## What we found

Simulated cases, Claude Haiku 5.5, one run per cell ([summary](docs/evaluation-summary.md)). Scores mean agreement with a simulation's sealed answer key. They are not real-world forensic accuracy.

| System | Incident effects established | Cover-ups found |
|---|---|---|
| Keyword recipe | 4/16 | 0/4 |
| Deterministic checks alone | 16/16 | 4/4 |
| One agent with the checks | 15/16 | 4/4 |
| One agent, generic search only | 10/16 | 3/4 |
| Three agents with the checks | 12/16 | 2/4 |

- One agent beat three at half the cost. Three times the skeptic withdrew a correct finding that a check supported.
- In the worker lab, on the same evidence, one agent caught 4/4 and three agents 2/4.
- No system made an accepted false allegation on a benign control, and none named a person.
- Repeating 8 cells on the same evidence reproduced only 2 exactly. Treat a one-or-two-effect gap as noise.

## Run it locally

Needs [uv](https://docs.astral.sh/uv/) and Node 20+.

```sh
uv sync --frozen
./start.sh                # builds the UI, serves http://127.0.0.1:8000, offline by default
```

Offline, the lab runs a labeled scripted fixture, and the committed recordings of real model runs replay with no key. Live runs need an Anthropic key in a gitignored `.env` ([setup](docs/overhaul/API_SETUP.md)). Every model call goes through one budget gateway with a hard $20 project cap.

The same features from a terminal:

```sh
uv run alibi lab run --variant incident --preset balanced --mode specialist --investigate
uv run alibi trace <case-id>              # plan, delegations, notes, tool calls
uv run alibi review <case-id> accept      # lock the report
uv run alibi lab operator <case-id>       # what the workers really did (after locking)
uv run alibi lab compare <case-id> --kind investigator_budget --investigator-requests 4 --investigate
uv run pytest                             # fixtures only, no model key needed
```

## Limits

- The rogue's actions are scripted, not chosen by a model.
- All scored evidence is simulated. Three small captures from real running processes import as unscored cases.
- The checks are simple comparisons. Next, we want to use real forensic tooling: Z3 for timeline consistency, Plaso, Zeek, Sigma and YARA.

## More

[Product definition](PRODUCT.md) · [Architecture](docs/architecture.md) · [API](docs/api.md) · [Claims and their evidence](docs/claims.md) · [Worker lab results](docs/worker-lab-eric-matrix.md) · [Acceptance record](docs/overhaul/ACCEPTANCE.md) · [Hosting](docs/integrations/HOSTING.md) · [Build history](PROGRESS.md)

`src/alibi/` backend · `web/` React UI · `tests/` tests · `benchmarks/` results · `demo/replays/` recordings
