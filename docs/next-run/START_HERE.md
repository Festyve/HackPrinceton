# Start the second run

The first build stays intact. This pack adds a concrete continuation, a full UI brief, a real technical assignment for Daniel, and a schedule through the hard deadline.

## Send Eric this

> Eric — the second-run review is ready. The investigator already ran on real Claude; the missing AI piece is the adversary. Keep the existing checkout, .env and .alibi/spend.json. The cap is still $5 TOTAL, including the first run.
>
> Pull the codex/phase2-handoff branch into your working branch, then use the prompt below in Claude Code signed into Max. Start with the budget fixes, then fast investigation, cited questions and the remove-a-witness experiment. Terry owns web/, Daniel owns capture/import and independent controls. Your agent owns backend/contracts and merges their work.
>
> Read docs/next-run/API_SETUP.md before live calls. Rotate the key that went into the earlier chat, locally; do not send it to anyone. Preserve the existing Opus recording. The first checkpoint is Saturday 09:00, feature freeze Sunday 00:00, submission target Sunday 06:00, hard deadline 08:00 ET.
>
> Please get the agent running now, verify it passes the first tests without a permissions prompt, and leave the laptop plugged in with sleep disabled.

In Eric's existing repo, after saving or committing current edits:

```sh
git fetch origin
git merge --no-edit origin/codex/phase2-handoff
```

If the remote has advanced or there are conflicts, have Claude inspect and merge the documentation without discarding newer work. Do not reset to the reviewed commit. Create the working branch codex/eric-phase2 if it does not exist. No need to clone or replace .env.

## Paste into Eric's Claude Code

```text
/goal Continue ALIBI in this existing repository through docs/next-run/CONTINUE.md. Read PROGRESS.md's latest handoff, DECISIONS.md, docs/next-run/REVIEW.md, CONTINUE.md, CONTRACTS.md, API_SETUP.md and TEAM.md. Preserve the original architecture and completed functionality; implement the next phase, do not recreate it.

You own backend, shared contracts, CLI, model integration, tests and final integration. Terry owns web/ and UI tests; Daniel owns capture/, src/alibi/capture/, its fixtures and tests. Do independent work while they build, then integrate their committed branches without overwriting their changes.

The total authorized API cap is $5 across BOTH runs. Preserve .alibi/spend.json and existing spend. First fix and regression-test the gateway reservations, uncertain usage and coverage issues before any paid call. Follow the inexpensive-model calibration and reserve policy in API_SETUP.md. Never purchase credits, reset a ledger, print secrets or route Claude Code coding work through the runtime API key. Preserve the proven Opus recording.

Finish fast/specialist investigation, bounded cited Q&A, immutable source-removal experiments, capture integration, remaining distinct case families, missing evaluation arms and the acceptance checks in CONTINUE.md. Do not bypass the prior adversary refusal; implement only the separate benign scenario-design task described there and label scripted incidents accurately. No fake AI results, stubbed production paths or invented measurements.

Use installed DeepAgents APIs and official docs when needed. Use native coding subagents only for isolated work that helps; no new orchestrator stack. Keep documentation concise and update it to what actually works. Commit and push completed slices and maintain PROGRESS.md.

Completion means the assigned implementation works end to end, tests/build/browser checks pass, real runs and offline replay are correctly labeled, measured results are versioned, and the handoff gives exact launch/demo commands, commits, costs, evidence and remaining human actions. Show a checkpoint Saturday Nov 14 at 09:00 America/New_York. At Sunday Nov 15 00:00 stop adding features and finish integration/release checks; submit-ready handoff by 06:00 before the hard 08:00 deadline. If the start is later, keep those absolute deadlines. Continue useful work without repeated confirmation; never represent blocked or unfinished work as complete.
```

If /goal is unavailable in that client, paste the same text without the /goal prefix. Use a permission mode already approved for the project and test it before leaving. Do not disable safeguards or install a hook to bypass a rejection.

## Send Terry this

> Terry — you own the entire UI upgrade. Read docs/next-run/TERRY.md and paste its final prompt into your agent. The direction is an investigator's desk: the missing local record next to its surviving collector copy, readable findings, questions and a source-removal experiment. You own web/ and UI tests; Eric owns backend. Use no paid API calls. First working redesign Saturday noon, integrated version by 19:00. Please start now on codex/terry-ui.

Terry needs a checkout of the repository plus TERRY.md and CONTRACTS.md. Daniel needs a checkout plus DANIEL.md and CONTRACTS.md; his complete prompt is in DANIEL.md. Both can work with the committed offline recordings immediately.

## Files

- CONTINUE.md — Eric's implementation sequence and acceptance gates
- API_SETUP.md — key location, rotation, exact profile and unchanged $5 cap
- CONTRACTS.md — shared API targets and file ownership
- TERRY.md — full UI direction and copy-paste prompt
- DANIEL.md — capture/evaluation assignment and copy-paste prompt
- TEAM.md — responsibilities, checkpoints, track fit and submission
- REVIEW.md — findings behind the changes

The old PLAN.md remains useful background. For phase-two budget, scheduling and ownership, this pack takes precedence.
