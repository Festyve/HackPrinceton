# ALIBI: context for a skeptical reader

Prepared November 19, 2026. Implementation and result references are pinned to the fetched `codex/alibi-build` commit `f109e4d5c6720ffa433aa65b0800994afbe416d7`. This note describes the original investigation lab; containment and recovery discussed later are proposals.

## The short explanation

ALIBI is a controlled testing lab for AI forensic investigators. It creates synthetic incidents with known outcomes, gives an investigator only the surviving evidence, and measures its report against a sealed answer after the report is locked.

The intended users are security researchers and engineers evaluating agent systems. They can ask: Does an investigator find the right effects? Does it confuse an authorized action with misconduct? Which evidence does it depend on? Do extra agents or model requests improve the outcome?

The contribution is an inspectable experiment: scenario, evidence, investigation, committed report, and independently recorded events can all be examined. Its value depends on whether those experiments answer useful questions.

## A concrete example

A worker copies a restricted synthetic dataset to an unapproved destination and removes its local export records. An independent collector retains those records, while a network tap records the transfer.

An investigator must distinguish this from legitimate bulk archiving and routine log rotation, which can also produce large transfers and missing local entries.

The evidence may support an unapproved transfer and an unexplained missing record without establishing who removed the record. A service account, an assigned worker, and a human operator are different attribution claims.

## What the system actually does

1. **Execute the scenario.** Workers ingest datasets, write summaries, and archive approved reports. Real models can choose ordinary actions from restricted menus. The changed-objective fault actions follow a scripted policy.
2. **Separate evidence and truth.** The simulator saves actual action outcomes separately from the surviving artifacts. The investigator receives a read-only evidence interface without the answer key.
3. **Preserve and index records.** Raw artifacts are hashed and normalized into a read-only DuckDB store, retaining source locations.
4. **Investigate.** Deterministic checks establish defined observations. A DeepAgent uses evidence tools, planning, notes, and optional specialist delegation to produce a cited report.
5. **Commit before grading.** Human acceptance or rejection locks the report. The evaluator then compares accepted allegations with executed, observable effects.
6. **Inspect and compare.** Users can replay recordings, export reports, ask evidence-linked questions, compare investigation settings, or withhold an evidence source.

Changing investigator settings can reuse identical frozen evidence. Changing worker permissions requires a new execution. Those are different experiments and must not be treated as interchangeable.

## “Isn't this just comparing logs?”

The demonstrated local-versus-collector discrepancy is a comparison problem. Ordinary Python performs it, including checks for retention, collection coverage, and local records bracketing the missing entry. A DeepAgent is unnecessary for that individual operation.

ALIBI adds the apparatus for testing investigators around those observations: evidence isolation, benign controls, cited findings, report commitment, scoring, matched comparisons, and recorded failures.

That is a useful research contribution if someone needs to compare investigation methods. It is not evidence of a novel detection algorithm.

## “What does the AI contribute?”

The model can select evidence tools, connect observations, test explanations, maintain case notes, and write an account with explicit uncertainty. Specialist mode uses a lead, integrity auditor, and skeptic; single-agent mode is also available.

DeepAgents supplies planning, filesystem-backed working context, delegation, and review interrupts; LangGraph checkpointing preserves configured execution state. These mechanisms are implemented, but demonstrating them does not establish that they improve accuracy or are uniquely necessary.

Python performs the forensic checks and reference validation. Trusted scoring code, rather than the model, compares the locked report with the sealed answer.

## What the recorded experiments actually found

The paired evaluation summary covers six synthetic cases across two declared suites, with one run per system-case cell. Four incident cases contain 16 observable effects; two cases are benign controls.

| System | Incident effects established | Cover-ups found |
| --- | --- | --- |
| Keyword recipe | 4/16 | 0/4 |
| Deterministic checks alone | 16/16 | 4/4 |
| Single agent, generic evidence tools | 10/16 | 3/4 |
| Single agent with checks | 15/16 | 4/4 |
| Three agents, generic evidence tools | 7/16 | 1/4 |
| Three agents with checks | 12/16 | 2/4 |

The checks alone performed best on these modeled cases. The specialist system withdrew three correct findings that the checks supported.

A separate worker-lab comparison on identical, heavier-context evidence established 4/4 observable effects with one agent and 2/4 with three agents, under the same model and request allowance. That was one run per condition.

These are descriptive outcomes, not real-world accuracy estimates. The checks were developed for the simulated world. Repeating eight incident model cells reproduced the same number of established effects in only two cells. Small differences cannot establish general superiority.

The useful finding is that additional agent coordination can lose information or spend more without improving the result. ALIBI makes that failure inspectable.

## Limits that matter

- Scored incidents are synthetic. Three small process-generated captures are supported as unscored cases; they do not establish production forensic accuracy.
- Fault actions are scripted. An adaptive malicious model does not choose the sabotage.
- The investigator examines frozen evidence after activity has occurred. It does not continuously monitor, stop workers, quarantine files, or repair damage.
- Evidence access is restricted through application capabilities. This is not an operating-system isolation boundary against a hostile process.
- The acceptance record documents a remaining spend/timing side-channel concern; the information barrier should not be described as perfectly leakage-free.
- Saved execution tapes support replay. Matching a seed does not guarantee identical fresh model choices.
- There is no demonstrated learning across investigations, universal attack detection, or superiority over simpler methods.
- No first-of-its-kind or market-exclusivity claim is established by this project.

## What would make it more compelling?

Stronger evidence would come from independently authored cases, public forensic artifacts, repeated matched experiments, and measured benefits over deterministic baselines. An adaptive investigation that follows an initially unknown lead would make the agent contribution clearer.

Selective containment and verified recovery would be a different, larger capability requiring new intervention tools and evaluations. It should be presented as future work until implemented and tested.

## A useful way to judge the prototype

Inspect a finding and its exact records. Lock the report and compare it with the actual action history. Withhold an independent witness and inspect which original claims lose support.

If those steps help a researcher understand why an investigator succeeded or failed, ALIBI has served its purpose. The strongest case for it is a working evaluation instrument that can expose weaknesses in forensic AI, including its own.

## Sources

All links below refer to the inspected upstream snapshot, rather than implying this older review checkout contains the latest release.

- [Product contract](https://github.com/owly1/HackPrinceton/blob/f109e4d5c6720ffa433aa65b0800994afbe416d7/PRODUCT.md)
- [Architecture and information boundary](https://github.com/owly1/HackPrinceton/blob/f109e4d5c6720ffa433aa65b0800994afbe416d7/docs/architecture.md)
- [Paired evaluation summary and repeat results](https://github.com/owly1/HackPrinceton/blob/f109e4d5c6720ffa433aa65b0800994afbe416d7/docs/evaluation-summary.md)
- [Worker-lab comparison, including caveats](https://github.com/owly1/HackPrinceton/blob/f109e4d5c6720ffa433aa65b0800994afbe416d7/docs/worker-lab-eric-matrix.md)
- [Acceptance record and remaining limitations](https://github.com/owly1/HackPrinceton/blob/f109e4d5c6720ffa433aa65b0800994afbe416d7/docs/overhaul/ACCEPTANCE.md)
