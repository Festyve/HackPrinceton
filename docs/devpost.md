# Devpost draft

Draft for Rayan. Facts as of Nov 14, 2026, 01:30 ET. **Status: OFFLINE-READY; live AI not demonstrated.** Do not paste the bracketed notes. Update the marked sentences if a real model run exists before submission.

## Inspiration

When an account shows up in a breach, people tend to answer two different questions at once: what happened, and who did it. Real investigations almost never have ground truth, so it is hard to tell whether an investigator, or an AI agent sold as one, actually reconstructs an incident or simply accuses the name in the log. We wanted a place where that can be measured.

## What it does

ALIBI is a forensic proving ground. A bounded simulated adversary stages a synthetic incident in a small clinic network (a nurse workstation, a records server, an IoT badge reader, a central log collector, a network tap) and may remove a line from a host log to cover its tracks. The simulator seals what actually happened. An investigator receives only frozen, hashed evidence and a vague tip, and produces findings that cite evidence, plus an attribution statement that separates the account from the person. A human accepts or rejects the report, it is locked, and only then is the answer key unsealed and the report scored: caught, missed, unsupported.

The central screen is a comparison of the host's own log with the collector's copy: the missing line is drawn as a gap, next to the copy the collector retained.

[Offline status sentence, keep unless a real run exists:] In this submission the investigator shown is a scripted fixture driving our DeepAgents graph, and a deterministic rule-based baseline. A live model has not been run; the product labels this on screen.

## How we built it

- **Simulator:** a deterministic Python world model that writes realistic artifacts (auth logs, syslog, an application log, shell histories, file metadata, flow records, badge records, collector copies and heartbeats). The same seed reproduces byte-identical evidence.
- **Bounded adversary:** four allowlisted simulated steps. No shell, no code.
- **Evidence pipeline:** freeze, SHA-256 hashing, normalization into a read-only DuckDB with provenance for every row.
- **Deterministic checks:** host log vs. collector copy (aware of rotation and retention), bulk transfers vs. destination policy and sessions, account use vs. badge presence.
- **Verifier and scorer:** one verifier and one one-to-one matching scorer for every system.
- **Agents:** a LangChain `deepagents` graph (lead investigator, integrity auditor, skeptic) with typed read-only tools, a virtual case file, a shared budget gateway and a human review interrupt with checkpoint resume.
- **Case board:** FastAPI with server-sent events and a React + TypeScript UI with no external assets.
- **Tests:** 142 automated tests, 8 of them in a real browser.

## Challenges we ran into

- Making "missing evidence" a defensible finding. A naive diff of host log against collector flags every routine log rotation. The check needed retention boundaries, bracketing records and collection gaps before it stopped crying wolf on the benign controls.
- Keeping the answer key away from the investigator in a way we could test, not just assert: tool audits, a planted canary, hostile inputs.
- Not fooling ourselves. We had no free model runtime overnight, so we built the offline path and labeled it, instead of presenting a stub as AI.
- A crash when cancelling a run: the graph's checkpoint writer was still using a database connection we had closed.

## Accomplishments that we're proud of

- A held-out simulated suite where a keyword recipe detected 0 of 4 cover-ups and the contradiction checks 4 of 4, with no false alerts on four benign controls (12 cases; details and caveats in `docs/benchmark.md`).
- The report never names a person from account activity, and naming the framed account holder is scored as a false accusation.
- Every number on screen traces to a saved run and a scorer version.

## What we learned

- The honest baseline matters more than the headline: the rule-based checks alone match everything in this simulator, so any AI claim has to beat *that*, not grep.
- A verifier shared by all systems changes what "precision" means; raw proposals have to be reported next to it.
- Framework defaults move: in the installed `deepagents` version, planning todos are opt-in and a general-purpose subagent is added unless disabled.

## What's next

Run the declared AI pilot (single agent vs. lead + specialists, same checks and budget) once a zero-charge runtime is available; add the records-heist and cold-chain cards with their controls; capture one real artifact chain; test which claims survive when a witness source is removed.

## Track paragraphs

**Science & Discovery (main, recommended; Rayan confirms).** The research question is bounded: which evidence sources and investigator designs improve reconstruction of controlled incidents? ALIBI supplies the instrument: reproducible episodes with a sealed answer key, benign controls, a frozen evaluation config and paired comparisons. First measured result: on 12 held-out simulated cases, cross-source contradiction checks caught 20/20 scorable effects against 16/20 for a keyword recipe, the difference being exactly the four cover-ups. It is a simulation result with n = 12.

**Arlequin AI: AI-driven forensics.** Findings that keyword search cannot produce (a record that is absent on the host but retained by an independent collector), each with cited evidence an investigator can open, a verifier status, alternatives and a restrained attribution. Public/synthetic data only. Compute so far: zero model calls. [Do not claim AI-driven results unless a model run exists.]

**LangChain: `deepagents`.** A lead agent with planning todos, two specialist subagents with isolated context and minimal tools, a virtual case file, a human-in-the-loop interrupt on report finalization with SQLite checkpoint resume, and a harness profile that removes the shell and the general-purpose subagent. [Currently exercised with a scripted policy. This track needs a real model run to be a credible entry.]

**Amazon: practical AI innovation.** A working prototype with a clear use: forensic tool builders and DFIR training teams get graded practice cases on demand; security teams can ask whether their log architecture would expose a given cover-up. Documentation, quickstart and a tested UI are in the repository.
