# Devpost copy

> **Historical handoff — superseded November 14 afternoon.** Use [../PRODUCT.md](../PRODUCT.md) and [the current owner instructions](overhaul/START_HERE.md) for this continuation. This file preserves the previous plan/demo; its schedule, setup tasks and product direction must not override the current contract.

Copy for the submission, matching the build on `codex/eric-phase2`. Every number is from a saved run in `benchmarks/`.

## Inspiration

A stolen credential can make an innocent person's account appear in an incident. A missing log can look like a cover-up, or it can be an ordinary retention policy. We wanted a way to test whether an investigator can tell those apart instead of repeating the name in a log.

## What it does

ALIBI is a practice range for digital investigations. A scripted incident runs inside a simulated clinic network. The system freezes the evidence and seals what actually happened. An AI investigator reconstructs the incident, cites its sources, and keeps account activity separate from human identity. A person reviews and locks the report before the answer is revealed and scored.

The central interaction compares a workstation's log with an independent collector. One entry is missing locally; the collector still has it. From there you can ask a question and see which parts of the answer a deterministic check confirms, or remove a witness and see which conclusions no longer stand.

There are three case families with different deciding evidence: an inside job on a shared workstation, an export from the records server itself, and a vaccine refrigerator whose stored readings disagree with an independent logger. Each has sealed controls where nothing wrong happened.

## How we built it

The backend uses Python, FastAPI, Pydantic and read-only DuckDB. A seeded simulator generates evidence with hashes and exact-line provenance. Deterministic checks compare sources and test explanations such as rotation, approved transfers and collection gaps. A check that lacks a source says "cannot be assessed" instead of "nothing found".

LangChain deepagents supplies the investigator: one agent in fast mode, or a lead with an integrity auditor and a skeptic, with case notes and a review gate that survives a restart. Every model call goes through one budget gateway that counts the request before sending it and keeps a cumulative ledger. The React interface makes each finding open its source. Saved real-model investigations replay offline.

## What we learned

A fixed keyword recipe missed every removed-log case in both of our evaluations. The comparison checks found all of them.

The AI results were more humbling, and we report them as measured. In the first pilot one agent and three agents were equally accurate and the single agent was faster and cheaper. In the second evaluation, on six new cases where no system was told whether its findings were supported, the checks with no model established 16 of 16 incident effects, one agent with the checks 15 of 16, and three agents 12 of 16. Without the checks the same agents established 10 and 7. When we ran eight of those model cells a second time on the same evidence, only two established the same number of effects, so we do not read anything into a gap of one or two. What held both times: the checks alone established everything, the model did better with the checks than without, and one agent with the checks stayed ahead of three. Delegation did not help: three times in the first runs the skeptic agent withdrew a correct finding. So fast mode is the default, and the model's job is what it is good at here: investigating, explaining alternatives, answering questions and writing the report.

We also asked a model to plan the adversary's steps. It declined, and we kept it declined. Incidents are scripted and labeled scripted.

These are small, simulated measurements with one run per cell, and one repeat of eight cells that showed how much a second run can differ. They are not real-world forensic accuracy. An account name is never treated as proof of who was typing.

## What comes next

Three small captures from running processes already go through the same pipeline as unscored cases. Next: real system logs, more cases, and repeated runs of the evaluation.

## Submission fields

Use the final public repository URL, the final video URL, all four team members and their Discord usernames. Choose Science & Discovery as the single main track, plus the relevant special tracks. Replace this section with the actual Devpost fields; it is not part of the project story.
