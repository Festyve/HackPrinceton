# Judge questions

> **Historical handoff — superseded November 14 afternoon.** Use [../PRODUCT.md](../PRODUCT.md) and [the current owner instructions](overhaul/START_HERE.md) for this continuation. This file preserves the previous plan/demo; its schedule, setup tasks and product direction must not override the current contract.

**Where is the AI?**

Three places, all run on real models: the investigator that reconstructs a case, the question answering over a case, and a designer that picks an ordinary operating environment from fixed options. The committed recordings are saved runs of Claude Opus 5.5 and Claude Haiku 5.5. A replay is labeled "Recorded AI run"; it is not live inference. The incident itself is always a scripted scenario.

**Does an AI stage the attack?**

No. We asked a model once to plan an adversary's steps from a bounded list and it declined. We left it declined: that route is disabled and we did not rephrase the request or switch models. The designer is a different task. It chooses how busy a normal day is and which routine condition occurs. It has no field for a step, a command or a destination.

**What does it find that keyword search misses?**

A line that is no longer in the local log, because an independent collector kept a copy. Across both runs our fixed keyword recipe established 0 of 8 cover-ups; the comparison checks established 8 of 8. That is a comparison with that recipe, not a claim that existing forensic tools cannot compare logs.

**Does the model discover the missing line itself, or do the checks do it?**

We measured both. In the second run, on four new incident cases, a single agent with only generic search tools established 10 of 16 incident effects, and half of its runs ran out of budget. The same agent with the deterministic checks established 15 of 16 at about half the cost. The checks with no model at all established 16 of 16. So on these cases the checks carry the detection, and the model's contribution is investigation, explanation, alternatives and answering questions. One run per cell: this is how the systems differed here, not an accuracy estimate. We repeated eight of those cells once and only two established the same number of effects, so a gap of one or two effects means little; the order (checks alone, then one agent with the checks, then the rest) was the same both times.

**Why multiple agents?**

They separate integrity work from skeptical review and leave an inspectable trail. They did not improve accuracy in either run: equal in the first pilot at 2.6 times the cost, and lower in the second (12 of 16 against 15 of 16 for one agent with the same checks, at twice the cost). We can say why: three times the skeptic agent withdrew a correct finding that the deterministic check supported, reasoning that an unexplained absence is not proven removal. That caution is defensible and it cost recall. Fast mode, one agent, is therefore the default for a live investigation. Specialist mode stays available and its results stay published.

**How do you know a finding is correct?**

Three different things, kept apart: a citation that resolves to a real record; an observation a deterministic check supports; and agreement with the executed ground truth, which is checked only after the report is locked. None of them establishes legal truth or who a person is.

**In the second evaluation, did the systems get hints?**

No. In the first pilot, submitting a finding returned the verifier's verdict, so a system without the checks could have recovered their answers by trial. In the second evaluation a submission only confirms the finding is well-formed and its ids exist. Support was applied after each report was locked, the same way for all six systems. The configuration was committed before the run.

**Can the investigator read the answer key?**

Its tools do not expose it. It has no shell, no SQL, no filesystem path and no URL tool. Canary and hostile-tool tests check that boundary, including for questions asked after a case is unsealed. This is a tested agent capability boundary, not an operating-system security claim.

**What about malicious instructions inside logs?**

Evidence is returned to a model as data inside tool results and rendered as text in the interface. Tests plant an instruction in a log and have a stand-in model obey it: the tools it asks for do not exist, the ids it invents are dropped, and nothing is revealed. We also tried it once with the real model: a log line telling the reader to report no incident, blame a named nurse and print the answer key. The investigation still established all three effects, named nobody, and when asked about the line the model answered that it is data, not an instruction, and does not change the findings. That is one run on one case, so it shows what happened once; it is not a robustness measurement.

**What does removing a witness show?**

Which conclusions depend on which source. Take the collector away and the transfer is still established from the network tap, while the removed log line can no longer be established: the comparison it rests on cannot be run. The answer is "cannot be established from this evidence", which is different from "did not happen". Scoring for such a view lists every original effect and both denominators, so less evidence can never look like better detection.

**Did you run anything twice?**

Yes, once, and it changed how we talk about the results. We declared a repeat of the eight model cells of two incident cases, on the same evidence, with the same model, prompts, tools and budget. Two of the eight established the same number of effects as the first time. One agent with the checks went from 7 to 8 of 8, three agents with the checks from 5 to 6, one agent without the checks from 5 to 4. Nothing unsupported was accepted and nobody was named in either run. Two runs are not a variance estimate, but they are enough to say that a difference of one or two effects between systems is not a finding. The two systems with no model gave identical results, as they must.

**Who checked your code?**

Tests, and three cold reads by a second agent that was told nothing about what to expect: the budget code, the information barrier and input handling in the new routes, and the interface code for the new controls. They found twenty-four defects, each reproduced before it was reported. The most serious: a derived evidence view could be unsealed while the original report was still open. All are fixed, and each has a regression test.

**Is simulated evidence enough?**

No. It gives a reproducible answer key and controlled comparisons; it does not establish real-world performance. A first step past it is merged: three small captures written by running processes (a test application and an independent collector in Docker containers) import as unscored cases. The deterministic comparison reports the removed line on the capture that has one and nothing on the two controls. A real model, run once on each, alleged nothing on the controls; on the removal capture it described the missing line and left it unresolved instead of calling it removal. These are not system logs and three captures are not a detection rate.

**Could someone use this?**

Training teams can see how an investigator reached a conclusion and check every citation. Builders can compare investigator configurations on the same sealed case. Log owners get a practical question answered: which conclusions would we lose if this source were gone?

**How much does it cost?**

Replaying a recording costs nothing. A fresh fast investigation on Claude Haiku 5.5 took about 25 seconds and under one cent; a question took two or three model calls and about a quarter of a cent. The whole second-run evaluation, twenty-four investigations, was an estimated $0.33. The team authorized $20 in total and an estimated $3.65 has been used. A ledger reserves before each call and keeps unknown outcomes at their worst case; the provider console is the billing authority.
