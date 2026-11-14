# ALIBI

**The log is missing. The evidence isn't.**

ALIBI is a research lab for investigating AI workers. The team is building a controlled environment where workers do useful jobs, one can go rogue, and an outside investigator reconstructs what happened from surviving evidence. The experiment varies rogue permissions and investigation resources, then compares a locked, cited report with sealed ground truth.

**Current build (branch `codex/eric-overhaul`):** three automated workers do ordinary jobs chosen by a real model. In an incident run the scheduler changes one worker's objective part-way through and that worker takes bounded fault actions, which follow a **scripted policy: no model chooses them**. An investigator outside the lab works from the frozen evidence, with one agent or three, under a request allowance. Runs can be compared, recorded, replayed and resumed. What is met and what is not, gate by gate: [acceptance record](docs/overhaul/ACCEPTANCE.md). Not met: a model choosing the fault actions (by the owner's decision), a recorded human usability review, the ≤120 second demo and the final release check. [Product definition](PRODUCT.md) · [Measured lab results](docs/worker-lab-eric-matrix.md) · [API](docs/api.md)

Built at HackPrinceton Fall 2026 by Eric Chen, Rayan, Daniel, and Terry.

![A missing host-log entry beside the copy retained by the collector](docs/screenshots/terry-ui/03-review-1440x900.png)

## Try it

Install [uv](https://docs.astral.sh/uv/) and Node 20 or newer. Then, from this repository:

```sh
uv sync --frozen
./start.sh
```

Open **http://127.0.0.1:8000** and choose the recorded investigation of **Inside job · cover-up**. Follow the missing log entry, open a citation, accept the report, and unseal the answer key.

The recordings are saved runs of real Claude models. Playback needs no API key and no internet connection once dependencies are installed. A fresh investigation without a configured key uses a scripted fixture that is labeled as one.

Use `./start.sh --port 8010` if the default port is busy.

## What makes a case in the current build

A simulated clinic has a workstation, a records server, a badge reader, an IoT hub, a central log collector and a network tap. An incident leaves traces across those systems. Some traces can be removed locally; independent copies survive elsewhere.

ALIBI compares those witnesses. A missing line can matter, but so can an ordinary log rotation or a broken collector. The investigator has to explain the difference, and keep an account name separate from the person who owns it.

| Case family | The incident | What decides it | Sealed control |
|---|---|---|---|
| Inside job | A colleague's account copies the patient database out; optionally a host log line is removed, or four more attempts are made to cover it | The host's log against the collector's copy; network flows against transfer policy | Rotation, approved transfer, remote login, collection gap, maintenance window |
| Records heist | An administrator's credential exports the database on the records server itself | The application's export trail against change records and the tap | An export approved by a change record |
| Cold chain | A refrigerator warms past its range and the stored readings are overwritten | The hub's stored readings against an independent reference logger | A real excursion, honestly recorded |

```mermaid
flowchart LR
  scenario[Scripted incident] --> evidence[Frozen evidence]
  scenario --> truth[Sealed answer key]
  evidence --> checks[Deterministic checks]
  checks --> agent[AI investigator]
  agent --> review[Human review]
  review --> locked[Locked report]
  locked --> score[Compare with the answer]
  truth --> score
```

Python checks establish observations. A LangChain DeepAgent investigates, considers alternatives and writes a cited report. Its tools expose evidence, never the answer key. Human review locks the report; it does not certify that anyone is responsible.

## What you can do

- **Investigate** a case in fast mode (one agent, about 25 seconds on Claude Haiku 5.5) or specialist mode (a lead, an integrity auditor and a skeptic).
- **Ask a question** about a case. The answer comes back as single claims, each marked as confirmed by a deterministic check, merely cited, or the model's interpretation. Ids that are not in the evidence are dropped.
- **Remove a witness.** Derive a copy of the case without one evidence source and see which conclusions keep their support and which can no longer be established.
- **Export** the locked report with its hash, the model and mode that produced it, and the exact cited lines.
- **Design an environment.** A model picks an ordinary working day from fixed options; an operator may place a scripted incident in it.

All of this is in the backend API ([reference](docs/api.md)) and tested. The case board in `web/` on this branch covers the investigation, evidence, review and reveal flow, the newer controls (questions, removing a witness, export, mode choice, the results and the environment designer) and the worker lab (Terry's overhaul, merged at `63c4bc3`). Resuming a stopped investigation and saving a recording are terminal-only. The same features run from a terminal, against the same cases the case board shows:

```sh
uv run alibi run --preset hero-coverup          # investigate; stops at human review and prints the case id
uv run alibi experiment <case-id> --without collector
uv run alibi ask <case-id> "Who did it?"         # needs a configured model; offline it says so
uv run alibi review <case-id> accept
uv run alibi export <case-id> > report.md
uv run alibi import tests/fixtures/capture/missing-local-record --investigate   # captured evidence, unscored
uv run alibi lab run --variant incident --preset balanced --investigate         # the worker lab; offline it uses labeled fixtures
uv run alibi lab operator <case-id>                                             # what the workers did, once the report is locked
uv run alibi lab compare <case-id> --kind investigator_budget --investigator-requests 4 --investigate
uv run alibi trace <case-id>                                                    # plan, delegations, plan changes, case file
```

## What is real and what is not

- The investigator, the question answering and the environment designer have run on real models. Seven real-model recordings (one Opus, six Haiku, three of them worker-lab runs) are committed and replay offline, labeled "Recorded AI run"; two more are scripted fixtures and say so.
- In the worker lab the workers' ordinary work is chosen by a real model. A changed objective follows a **scripted policy**; no model chooses a fault action, and every lab run says so.
- Every incident is a **scripted scenario**. No model plans or stages an incident. The one request to have a model plan an adversary's steps was declined by the model, and that route stays disabled.
- All scored evidence is **simulated**. Three small captures written by running processes (a test application and an independent collector in Docker containers) import as **unscored** cases and go through the same pipeline: the deterministic comparison reports the one removed line and nothing on the two controls. A real model, run once on each, alleged nothing on the controls and described the missing line without calling it removal. These are not system logs and not a detection rate ([capture](docs/capture.md), [importing](docs/importing.md)).
- Scores are agreement with a simulation's sealed answer key. They are not real-world forensic accuracy.

## Measured results

First run, simulated cases ([details](docs/benchmark.md)):

| Comparison | Result |
|---|---|
| Keyword recipe, 12 cases | 16/20 incident effects; 0/4 cover-ups |
| Deterministic checks, same cases | 20/20 incident effects; 4/4 cover-ups |
| One agent with checks, four-case pilot on Claude Opus 5.5 | 5/5 effects; est. $0.50; median 19 s |
| Three agents with checks, same pilot | 5/5 effects; est. $1.30; median 59 s |

Second run: six new cases (four incidents, two benign controls), Claude Haiku 5.5, one run per cell ([summary](docs/evaluation-summary.md); per case: [first four](docs/evaluation-v2.md), [replication of the incident kinds](docs/evaluation-v2-rep1.md)). Here no AI system was told whether a finding was supported while it investigated; support was decided after each report was locked.

| System | Incident effects established | Cover-ups found | Runs stopped by a budget cap | Est. cost for six cases |
|---|---|---|---|---|
| Keyword recipe | 4/16 | 0/4 | – | – |
| Deterministic checks, no model | 16/16 | 4/4 | – | – |
| One agent, generic search tools only | 10/16 | 3/4 | 3 of 6 | $0.08 |
| One agent with the checks | 15/16 | 4/4 | 0 | $0.04 |
| Three agents, generic search tools only | 7/16 | 1/4 | 3 of 6 | $0.12 |
| Three agents with the checks | 12/16 | 2/4 | 0 | $0.08 |

No system made an accepted false allegation on the two benign controls, and none named a person. On these cases the checks helped the model in both configurations, one agent did better than three at half the cost, and the deterministic checks by themselves established everything. Three times the three-agent system lost a correct finding because its skeptic agent withdrew it although the check supported it. With one run per cell and four incident cases, this shows how the systems differed here. It is not an accuracy estimate.

We then ran the eight model cells of the first two incident cases once more on the same evidence ([repeat](docs/evaluation-v2-repeat1.md)). **Only 2 of the 8 established the same number of effects as the first time.** Out of 8 effects, one agent with the checks went from 7 to 8, three agents with the checks from 5 to 6, one agent without the checks from 5 to 4, and three agents without stayed at 5. A difference of one or two effects between systems is therefore within what a second run changes. What was the same both times: the deterministic checks established everything, one agent with the checks was ahead of three, only the systems without the checks ran out of budget, and no system made an unsupported accepted allegation or named a person.

## Live AI and budget

Live inference uses a server-side Anthropic key in a gitignored `.env`. **The total API allowance is $20 across all runs, including the overhaul.** About $3.92 has been used; read the current ledger before spending. Follow [current API setup](docs/overhaul/API_SETUP.md) and never delete the spend ledger.

Every model call goes through one budget gateway. It counts the outgoing request before sending it, refuses one that is too large or cannot be counted, reserves tokens and money so parallel agents cannot jointly pass a cap, and keeps the worst-case cost of any call whose billing outcome is unknown until someone reconciles it. Automatic calls stop $0.50 short of the cap. The totals are a conservative estimate at list prices, not a bill; the provider console is the billing authority.

```sh
uv run alibi runtime            # mode, model, caps, limits (no model call)
uv run alibi spend              # the cumulative spend estimate (no model call)
uv run alibi smoke --count-only # count a request with the provider's unbilled endpoint
uv run pytest                   # needs Google Chrome and a built UI for the browser tests
npm --prefix web run build
```

Tests use fixtures and need no model key.

## Read more

- [Team roles and deadline](docs/overhaul/TEAM.md) · [Eric/Terry launch messages](docs/overhaul/START_HERE.md) · [UI specification](docs/overhaul/UI.md)
- [New experiment protocol](docs/overhaul/EXPERIMENTS.md) · [Next-release demo](docs/overhaul/DEMO.md) · [Release acceptance](docs/overhaul/ACCEPTANCE.md)
- [Architecture](docs/architecture.md) · [API added in the second run](docs/api.md) · [claims and their support](docs/claims.md)
- [Two-minute demo](docs/demo-script.md) · [judge questions](docs/judge-qa.md)
- [Build history and handoff](PROGRESS.md) · [engineering decisions](DECISIONS.md) · [remaining owner actions](BLOCKERS.md)

`src/alibi/` contains the backend; `web/` the React case board; `tests/` the checks; `benchmarks/` the measured results; and `demo/replays/` the recordings.
