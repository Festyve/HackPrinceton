# What the overhaul actually needs

Audit baseline: default branch `codex/alibi-build` at `6e7d322`, November 14, 2026. UI integration branch examined: `codex/eric-ui-wiring` at `1b9216d`. This is a source/documentation review, not a new run of the application tests. Repository visibility was independently checked: **public**.

## Diagnosis

The first two runs produced a useful evidence investigation system. They did not produce the team's central experiment: productive AI workers that change objectives inside a sandbox while an external investigator reconstructs their behavior. The gap is a missing simulation/control loop, not a lack of dashboard styling or another model provider.

The current investigator has real DeepAgents integration, notes, tools and checkpoints, but its prompt largely prescribes a fixed sequence: plan, delegate, check, challenge, finalize. That is not yet strong evidence of adaptive long-horizon investigation. The UI hides newer backend capabilities on the default branch. Fix these three gaps before adding new scenarios.

| Existing work | Keep/use it | Work still required |
|---|---|---|
| `sim/world.py`, `scenario.py`, `steps.py` | World state, evidence generation, permitted step effects | Worker goals/observations, scheduler, normal work, seeded role transitions and bounded model-selected fault actions |
| `agents/adversary.py` | Review its validation and earlier refusal record | A separately scoped synthetic fault controller; preserve refusal outcomes and the old disabled route |
| `episode.py`, evidence store, verifier, scoring | Frozen evidence, citations, sealed answer and commitment | Action tape, lineage and worker-to-account evidence; prevent new metadata from leaking roles/truth |
| `agents/investigator.py`, runner/tools | Real DeepAgent, StateBackend, explicit harness, SQLite checkpoints | Evidence-led replanning, bounded living case file, useful specialist tasks, resume/context-pressure proof |
| `agents/gateway.py` | Count/bound/reserve/settle budget and unknown outcomes | Route every new worker and fault call through the same ledger; add shared experiment caps |
| Questions, source experiments, export, capture | Already implemented and exercised | Preserve UI access and semantics during redesign |
| `codex/eric-ui-wiring` | Nine newer UI capabilities and browser coverage | Terry reviews and integrates this work before applying the new layout; do not recode these routes from memory |
| Historical benchmarks | Honest baseline and evidence of variance | New frozen protocol for worker simulation, resource comparisons and context pressure |

## What the build history reports

The 14:05 handoff reports 474 tests on the default branch and 494 on the UI wiring branch, four real-model recordings plus two scripted recordings, and about **$3.651786 cumulative estimated API spend** (650 calls, no open reservations at that checkpoint). These are previous-run reports, not checks rerun by this planning pass. Eric must read the current ledger before another paid call.

Captured evidence consists of three small Docker test-application bundles, not operating-system forensic images. They import as unscored cases; there is no sealed answer to reveal for them. Second-machine reproduction remains outstanding. IoT-CAD and a wider independent case set are still absent; neither blocks the team's required synthetic lab.

The old “make repository public” action is complete. Eric's decision to keep his configured key is recorded; this plan does not reopen that decision. Keep the key and private transcript out of Git and public artifacts.

## Results that must survive the rewrite

The six-case evaluation contained four incidents (16 effects) and two benign controls. Deterministic checks found 16/16 effects; one agent with checks established 15/16; three agents with checks established 12/16. Three-agent skepticism withdrew correct findings three times. In the eight-cell repeat, only two cells established exactly the same number of effects as before. See [the measured summary](../evaluation-summary.md) and its linked artifacts.

These findings are a design input: retain a useful fast mode, make extra delegation conditional on the case, and evaluate the new context-heavy workflow without promising a victory. A prettier chart or selectively chosen recording cannot reverse the result.

## The critique that matters

1. **Product identity drifted.** Generic case analysis, a scenario designer and more incident families cannot replace workers doing jobs and then becoming rogue. Make that lifecycle visible and executable.
2. **The advanced-agent claim is ahead of its evidence.** A fixed checklist with three role names does not demonstrate adaptation. Show a specific conflict changing the plan and a persisted fact needed later.
3. **Power is underspecified.** Permission breadth, decision budget, context allowance and available evidence are different interventions. Separate them and label each control's units.
4. **The experiment could leak its answer.** Role names, action streams, filenames, seed mappings and notes are new leakage channels. Explicitly test the investigator's actual inputs.
5. **The demo needs a causal story.** A judge should see productive work, misconduct, surviving traces and the investigator's evidence. A wall of agent messages does not provide that story.
6. **The next UI must be an application.** One main task, clear actions and evidence navigation matter more than mascots or glass. Keep the reference's visual treatment, but use opaque evidence surfaces and real accessible controls.
7. **Overnight agents need one spec.** The root product contract and this directory are current; earlier plans are history. Completion requires artifact-backed gates, not a long progress entry.

## Release evidence to add

Eric and Daniel maintain `docs/overhaul/ACCEPTANCE.md` with P1–P10 status, commit, command, run ID and artifact link. Start every new requirement as pending. Terry supplies screenshots and browser evidence. Rayan signs off on comprehension and the final claims. The planning pass does not mark any new gate passed.
