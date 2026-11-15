# Two-minute demonstration

> **Historical handoff — superseded November 14 afternoon.** Use [../PRODUCT.md](../PRODUCT.md) and [the current owner instructions](overhaul/START_HERE.md) for this continuation. This file preserves the previous plan/demo; its schedule, setup tasks and product direction must not override the current contract. **Exception: the section on the worker-lab recordings below is current.**

Everything below works offline from a fresh start. Use the **Recorded AI run** for the timed pitch: it is a saved investigation by a real model and needs no key or network. A fresh live investigation is for a judge who asks, not for the two minutes.

Start with `./start.sh`, open http://127.0.0.1:8000 and keep the benign control ready in a second tab. Test once with Wi-Fi off.

| Time | Action | Spoken line |
|---|---|---|
| 0:00–0:12 | Show the library | "A login uses your account. A database leaves the network. Is that enough to say you did it?" |
| 0:12–0:25 | Open the recorded Inside job case | "ALIBI runs a scripted incident, seals the answer, and asks an AI investigator to reconstruct it. This is a recorded run of a real model." |
| 0:25–0:50 | Point to the aligned mismatch; open its citation | "The workstation lost this login entry. The independent collector kept it. That session overlaps a transfer to an unapproved destination. Every finding opens the actual record." |
| 0:50–1:05 | Show the account and person boundary | "The credential was used. The evidence does not establish who was typing. The report keeps those apart." |
| 1:05–1:25 | Accept, lock, unseal | "The report is locked before the answer is revealed. Here is what it established and what the evidence could not show." |
| 1:25–1:50 | Source-removal experiment (when the UI control exists; otherwise the benchmark table) | "Now take the collector away. The transfer is still proven. The deleted line is not: without that witness it cannot be established. That tells a log owner what this one source is worth." |
| 1:50–2:00 | Return to the evidence | "A practice range for investigators, and a way to test whether your logs keep the evidence you would need." |

Only show a feature on stage if you have just seen it work in the build you are presenting. The source-removal experiment, questions, export, the new cases and the scenario designer exist in the backend and are tested; whether a control for each is in the UI depends on the UI branch that is merged at the time.

## Where the controls are in the fallback interface

This applies only if the build you present includes the branch `codex/eric-ui-wiring` (check for a "Remove a witness" selector at the bottom of the Sources column). On the default branch without it, use the terminal commands below.

- **Remove a witness:** bottom of the Sources column. Choose "Log collector", press "Derive the reduced view". The derived case opens with "What the original report can still establish" at the top. "Open the original case" takes you back. A derived case can be unsealed only after the original's report is locked.
- **Ask a question:** the bar at the bottom. Recorded answers are listed closed above it; click one to open it. With no model configured a question is shown as "Not answered", never as an answer.
- **Export:** "Download the locked report" appears in the review panel once the report is locked.
- **Cold chain:** open the Cold chain recording. The chart "Two temperature records" is above the evidence comparison; hover or use the arrow keys to read both records.
- **Fast or specialist:** the "Investigation" selector above the case library, for fresh investigations.
- **Results:** the Benchmark tab starts with the six systems on the six new cases, and the repeat of eight cells below it.
- **Design an environment:** the link under the "Investigation" selector on the case library. With no model configured it returns a default and says so.

## The worker lab, from recordings

The pitch itself is in [`docs/overhaul/DEMO.md`](overhaul/DEMO.md). These are the saved runs it can use, all real model runs that replay with no key. The application does not say which run had an objective changed until its report is locked; this page does, for the presenter:

- **lab-run-a-three-agents-haiku-5-5** ("recorded run A · three agents"): an incident. Workers do their jobs, worker W1's objective is changed (scripted policy), it copies two restricted datasets to a destination that is not approved and removes its own export records. Three agents investigate: a plan, the checks delegated, the plan rewritten after the auditor's result, a recorded answer to "which worker does the scheduler tie this account to". It established 4 of the 5 executed effects; the skeptic downgraded one correct finding and that is visible on the finding.
- **lab-run-b-one-agent-haiku-5-5** ("recorded run B · one agent"): an incident of the same kind investigated by one agent; 5 of 5.
- **lab-run-c-one-agent-haiku-5-5** ("recorded run C · one agent"): the control. No objective is changed; approved bulk archives and a routine log rotation; no allegation.

Open one from the case library, accept the report, then open the workers' record: every attempted action with its real outcome and where the objective changed. Say "recorded" and "scripted policy" out loud; both are on the screen.

Known rough spots in these recordings, found by a browser smoke test and not fixed: in run A the expanded answer is cut off at 1440×900 (collapse it or use a taller window), and the answer's first claim is tagged "Unsupported" because the model filed a statement about a scheduler assignment as a claim about a login session. The three recordings were made before the worker link existed, so their reports name the account but tie it to no worker; a fresh run does.

On the redesigned interface (checked offline in a browser at 1440×900, November 14 evening): every flow above completed. Presenter notes: to open a lab recording go to Cases, scroll to Recorded replays, select the row, then scroll back up to "Open selected case"; the Activity list shows only its first rows while events arrive, so point at the Pip feed (bottom right) or press "Show all" afterwards; the Pip widget overlaps the top of Accept on arrival at review, so scroll a little first; a viewer sees the investigator's plan, delegations and tool activity as they happen, while the workers' actions are shown afterwards as a table and, once the report is locked, as a step-through operator record; reopening a run that was already unsealed shows the answer dialog immediately, so use a fresh run or a recording on stage.

## If someone asks to see more

- **Ask a question.** "What links the missing line to the transfer?" The answer comes back as single claims, each marked as checked by a deterministic check, cited, or the model's interpretation. Then ask "Who did it?": the answer names an account and says the person is not established.
- **A different case.** Records heist (the records server's own export trail) or Cold chain (stored temperature readings against an independent reference logger). Each has a sealed control where nothing wrong happened.
- **A live run.** Fast mode takes about 25 seconds on Claude Haiku 5.5 and costs under a cent. If it stalls, switch to the recording. Do not wait out inference in a timed pitch.
- **Export.** Download the locked report: its hash, the model and mode that produced it, and the exact cited lines.
- **Captured evidence.** `uv run alibi import tests/fixtures/capture/missing-local-record --investigate`, then open the case from the case library. It is labeled as captured evidence: the host's own log lacks a request that the collector kept. It has no answer key, so nothing can be unsealed.

## From a terminal

Every feature above also runs from a terminal against the same cases, which is the fallback if a control is not in the UI yet:

```sh
uv run alibi run --preset hero-coverup          # prints the case id and the findings
uv run alibi experiment <case-id> --without collector
uv run alibi ask <case-id> "What links the missing line to the transfer?"
uv run alibi review <case-id> accept
uv run alibi export <case-id>
```

Offline, `run` uses the scripted fixture and says so, and `ask` reports that no model is configured. `experiment` and `export` need no model.

## Sponsor questions

- **Arlequin (forensics):** open the missing record's source and a cited answer. Say which observations come from deterministic checks and which interpretation comes from the model. Show the source-removal comparison.
- **LangChain (deepagents):** show the recorded task and tool trace, the case notes, the specialists and the review checkpoint that survives a restart. Mention that fast mode is the same framework with one agent.
- **Amazon (practical AI):** show the ordinary flow and name the user: training teams, and builders who need to know which conclusions depend on which log source.

## Recovery

- Port busy: `./start.sh --port 8010`.
- A refresh restores the case. Review resumes after a restart.
- Reset twice before judging.
- For a case with no incident, use the sealed control, not a new billed run.

Record the final video from the working application, at most two minutes, and check the link from a logged-out browser.
