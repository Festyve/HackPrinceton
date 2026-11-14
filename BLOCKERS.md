# Remaining owner actions

> **Overhaul routing, November 14 afternoon:** current requirements and pending release gates are in [PRODUCT](PRODUCT.md), [STATUS](docs/overhaul/STATUS.md) and [ACCEPTANCE](docs/overhaul/ACCEPTANCE.md). The repository is public; the old visibility action is complete. The user confirmed the existing $20 cumulative cap. Entries below describe the previous build and remain as history, not instructions to repeat completed work. The new feature freeze is Saturday 23:00 ET.

Status on November 14 during the second run. This file lists what a person still has to do and what is waiting on someone else. Completed work is in [PROGRESS.md](PROGRESS.md).

| Item | Owner | Next action |
|---|---|---|
| The runtime key was pasted into a coding chat | Eric | Decided Saturday November 14: Eric keeps the current key. It is in the gitignored `.env` and in the local chat transcript, and in no commit on any branch (checked again that day). Nothing to do unless that transcript is shared; if it ever is, replace the key in the Claude Console first and edit only the key line in `.env`. |
| $20 cumulative API cap | Eric | Nothing to do unless the ledger and the Console disagree. `uv run alibi spend` shows the estimate; the Console is the billing authority. Nothing beyond $20 is authorized. |
| UI for the new backend features | Terry | Start from [`docs/ui-integration-brief.md`](docs/ui-integration-brief.md) (ordered list, labeling rules, a paste-ready prompt). Add controls against [`docs/api.md`](docs/api.md) and the real payloads in `docs/api-examples/`: questions, source-removal experiment, report export, fast/specialist choice, the six new presets, the scenario designer preview, and the `paired_v2` results. The backend routes exist and are tested; the merged UI does not call them yet. **A working fallback is on `codex/eric-ui-wiring`** (questions, witness removal, export, mode choice, spend line, temperature chart, results table, environment designer, captured cases; 41 browser tests; independently reviewed, nine findings fixed): take it, change it or replace it. To present from it today: `git switch codex/eric-ui-wiring && ./start.sh`. It is not merged because `web/` is yours. If no UI wiring has arrived by the feature freeze (Sunday 00:00 ET), Eric's session merges the fallback. |
| Captured evidence | Daniel, then Eric | **Delivered and merged** (Daniel's commit `ce01304`): three small Docker captures import as unscored cases and run through the whole pipeline. Still open: (1) reproducing the capture on a second machine. Eric's machine has Docker but no cached `python:3.13-slim` image, and pulling it needs a person's approval; (2) the case board on the default branch labels this evidence "Captured Linux evidence", which reads as more than a test application in a container, and shows an unseal button on an unscored case that then answers 409. The fallback branch says "Captured evidence · Docker containers" and hides the button (Terry to take or reword); (3) the wider independent case set in `docs/next-run/DANIEL.md` is not built. |
| IoT-CAD | Daniel | Verify the catalog, download and licence; ingest a relevant subset or record the exact blocker. |
| Private GitHub repository | Repository owner | Run the redacted secret scan described in the final handoff, then make the repository public. Keep its creation history. |
| Venue display and second machine | Terry + Daniel | Run the final build on a second machine and on the projector. Browser automation does not establish projector readability. |
| User consultation for the Peri track | Rayan | Enter only after a qualifying consultation, supporting evidence and a resulting change. |
| Video and submission | Rayan | Record at most two minutes from the working application; verify the link and the submission in a logged-out browser. |

## Not blockers, but do not change

- **The adversary planner stays disabled.** The model declined the one real request to plan an adversary's steps. Do not rephrase that request, add a refusal fallback or switch models to get around it. The scenario designer is a different task (it chooses an ordinary operating environment and no incident step) and must not be described as an AI attacker. Every incident in ALIBI is a scripted scenario and is labeled as one.
- **`offline-v1` and `ai-pilot-v1` are frozen.** `uv run alibi bench` and `uv run alibi pilot` refuse to rewrite them. New measurements go through `uv run alibi eval`.
- **The spend ledger is never deleted or reset.** `.alibi/spend.json` carries the first run's $2.92 forward.

Before the repository is made public, the repository owner or Terry should look at `docs/verification/terry-ui/screenshots.txt`: its first line contains an absolute path from a teammate's machine, including a user name. It is Terry's file, so this session did not edit it.

