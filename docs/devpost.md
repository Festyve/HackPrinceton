# Devpost draft

Draft for Rayan. Facts as of Nov 14, 2026, 02:30 ET. **Status: offline-ready, with the investigator demonstrated on a real model (Claude Opus 5.5). The adversary is scripted; do not describe it as AI.** Do not paste the bracketed notes.

## Inspiration

When an account shows up in a breach, people tend to answer two different questions at once: what happened, and who did it. Real investigations almost never have ground truth, so it is hard to tell whether an investigator, or an AI agent sold as one, actually reconstructs an incident or simply accuses the name in the log. We wanted a place where that can be measured.

## What it does

ALIBI is a forensic proving ground. A bounded simulated adversary stages a synthetic incident in a small clinic network (a nurse workstation, a records server, an IoT badge reader, a central log collector, a network tap) and may remove a line from a host log to cover its tracks. The simulator seals what actually happened. An investigator receives only frozen, hashed evidence and a vague tip, and produces findings that cite evidence, plus an attribution statement that separates the account from the person. A human accepts or rejects the report, it is locked, and only then is the answer key unsealed and the report scored: caught, missed, unsupported.

The central screen is a comparison of the host's own log with the collector's copy: the missing line is drawn as a gap, next to the copy the collector retained.

The investigator is a LangChain deep agent running on Claude Opus 5.5: a lead that plans and delegates, an integrity auditor that runs the contradiction checks, and a skeptic that tries to explain each finding benignly. The incident itself is a scripted scenario built from four approved simulation steps. [Keep this sentence: a model declined to plan the incident, so the adversary is not AI.]

## How we built it

- **Simulator:** a deterministic Python world model that writes realistic artifacts (auth logs, syslog, an application log, shell histories, file metadata, flow records, badge records, collector copies and heartbeats). The same seed reproduces byte-identical evidence.
- **Bounded adversary:** four allowlisted simulated steps. No shell, no code.
- **Evidence pipeline:** freeze, SHA-256 hashing, normalization into a read-only DuckDB with provenance for every row.
- **Deterministic checks:** host log vs. collector copy (aware of rotation and retention), bulk transfers vs. destination policy and sessions, account use vs. badge presence.
- **Verifier and scorer:** one verifier and one one-to-one matching scorer for every system.
- **Agents:** a LangChain `deepagents` graph (lead investigator, integrity auditor, skeptic) on Claude Opus 5.5, with typed read-only tools, a virtual case file, prompt caching, one shared spend ledger and a human review interrupt with checkpoint resume. The same graph runs offline on a scripted policy for tests.
- **Case board:** FastAPI with server-sent events and a React + TypeScript UI with no external assets.
- **Tests:** over 150 automated tests that run offline, 9 of them in a real browser.

## Challenges we ran into

- Making "missing evidence" a defensible finding. A naive diff of host log against collector flags every routine log rotation. The check needed retention boundaries, bracketing records and collection gaps before it stopped crying wolf on the benign controls.
- Keeping the answer key away from the investigator in a way we could test, not just assert: tool audits, a planted canary, hostile inputs.
- Not fooling ourselves. The first version ran on a scripted stand-in for the model, and we labeled it that way instead of calling it AI. When the real model arrived, our own pilot showed that the three-agent design was no more accurate than one agent with the same tools, at about 2.6 times the cost. We kept that result.
- The first real run was stopped by our own token cap after five calls. The cap came from a planning guess; we revised it from the measurement and recorded the change.
- A real model batched two tool calls in one turn, and the human-review pause held back the one we needed. A scripted test model had never done that.
- We asked a model to choose the simulated intruder's steps. It declined. We left the adversary scripted.
- A crash when cancelling a run: the graph's checkpoint writer was still using a database connection we had closed.

## Accomplishments that we're proud of

- A held-out simulated suite where a keyword recipe detected 0 of 4 cover-ups and the contradiction checks 4 of 4, with no false alerts on four benign controls (12 cases; details and caveats in `docs/benchmark.md`).
- A real model investigating end to end: 11 model calls, about 77 seconds and an estimated $0.37 for the hero case, all three effects caught, every citation valid, and a report that says "account used; human operator not established". The run is saved and replays offline.
- The report never names a person from account activity, and naming the framed account holder is scored as a false accusation.
- Every number on screen traces to a saved run and a scorer version, and the whole project's model spend is an estimated $2.92.

## What we learned

- The honest baseline matters more than the headline: the rule-based checks alone match everything in this simulator, so an AI claim has to be about something other than raw accuracy here, such as the written reasoning and the restraint about who did it.
- More agents are not automatically better. In our pilot they cost more and took longer for the same answers.
- A verifier shared by all systems changes what "precision" means; raw proposals have to be reported next to it.
- Framework defaults move: in the installed `deepagents` version, planning todos are opt-in and a general-purpose subagent is added unless disabled.

## What's next

Harder cases that can separate one agent from three; the benchmark arms without the checks, to see whether a model finds the missing line unaided; repeated runs to measure variance; the records-heist and cold-chain cards with their controls; one real artifact chain; and a test of which claims survive when a witness source is removed.

## Track paragraphs

**Science & Discovery (main, recommended; Rayan confirms).** The research question is bounded: which evidence sources and investigator designs improve reconstruction of controlled incidents? ALIBI supplies the instrument: reproducible episodes with a sealed answer key, benign controls, a frozen evaluation config and paired comparisons. Two measured results: on 12 held-out simulated cases, cross-source contradiction checks caught 20/20 scorable effects against 16/20 for a keyword recipe, the difference being exactly the four cover-ups; and in a 4-case pilot with a real model, a single agent and a three-agent system were equally accurate while the single agent cost about a third as much. Both are simulation results with small n.

**Arlequin AI: AI-driven forensics.** Findings that keyword search cannot produce (a record that is absent on the host but retained by an independent collector), each with cited evidence an investigator can open, a verifier status, the alternatives considered and a restrained attribution. A real model produced such a report for the hero case with 29 of 29 citations valid. Public/synthetic data only. Compute is measured per investigation and capped in code.

**LangChain: `deepagents`.** A lead agent with planning todos, two specialist subagents with isolated context and minimal tools, a virtual case file, a human-in-the-loop interrupt on report finalization with SQLite checkpoint resume (verified across a process restart with a real model), and a harness profile that removes the shell and the general-purpose subagent. We also report what the framework did not buy us: in our pilot the subagents added cost, not accuracy.

**Amazon: practical AI innovation.** A working prototype with a clear use: forensic tool builders and DFIR training teams get graded practice cases on demand; security teams can ask whether their log architecture would expose a given cover-up. Documentation, quickstart, spend controls and a tested UI are in the repository.
