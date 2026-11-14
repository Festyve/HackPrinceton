# Remaining owner actions

Status on November 14 during the second run. This file lists what a person still has to do and what is waiting on someone else. Completed work is in [PROGRESS.md](PROGRESS.md).

| Item | Owner | Next action |
|---|---|---|
| The runtime key was pasted into a coding chat | Eric | Create a replacement in the Claude Console, edit only the key line in the existing `.env`, revoke the old key. Do this before sharing transcripts or making the repository public. Do not paste the new key into chat. |
| $20 cumulative API cap | Eric | Nothing to do unless the ledger and the Console disagree. `uv run alibi spend` shows the estimate; the Console is the billing authority. Nothing beyond $20 is authorized. |
| UI for the new backend features | Terry | Start from [`docs/ui-integration-brief.md`](docs/ui-integration-brief.md) (ordered list, labeling rules, a paste-ready prompt). Add controls against [`docs/api.md`](docs/api.md) and the real payloads in `docs/api-examples/`: questions, source-removal experiment, report export, fast/specialist choice, the six new presets, the scenario designer preview, and the `paired_v2` results. The backend routes exist and are tested; the merged UI does not call them yet. **A working fallback is on `codex/eric-ui-wiring`** (questions, witness removal, export, mode choice, spend line, temperature chart; 28 browser tests): take it, change it or replace it. It is not merged because `web/` is yours. If no UI wiring has arrived by the feature freeze (Sunday 00:00 ET), Eric's session merges the fallback. |
| Captured Linux evidence | Daniel | Push `codex/daniel-capture` with a small captured fixture. The receiving side exists (`uv run alibi import`); the format and a paste-ready prompt are in [`docs/importing.md`](docs/importing.md). Until it exists, capture import is not built and every bundle is simulated. Eric's session did not attempt a capture: Docker is running on Eric's machine but has no cached image, and pulling one needs a person's approval. Eric wires the importer into the CLI and API when it arrives. |
| IoT-CAD | Daniel | Verify the catalog, download and licence; ingest a relevant subset or record the exact blocker. |
| Private GitHub repository | Repository owner | Run the redacted secret scan described in the final handoff, then make the repository public. Keep its creation history. |
| Venue display and second machine | Terry + Daniel | Run the final build on a second machine and on the projector. Browser automation does not establish projector readability. |
| User consultation for the Peri track | Rayan | Enter only after a qualifying consultation, supporting evidence and a resulting change. |
| Video and submission | Rayan | Record at most two minutes from the working application; verify the link and the submission in a logged-out browser. |

## Not blockers, but do not change

- **The adversary planner stays disabled.** The model declined the one real request to plan an adversary's steps. Do not rephrase that request, add a refusal fallback or switch models to get around it. The scenario designer is a different task (it chooses an ordinary operating environment and no incident step) and must not be described as an AI attacker. Every incident in ALIBI is a scripted scenario and is labeled as one.
- **`offline-v1` and `ai-pilot-v1` are frozen.** `uv run alibi bench` and `uv run alibi pilot` refuse to rewrite them. New measurements go through `uv run alibi eval`.
- **The spend ledger is never deleted or reset.** `.alibi/spend.json` carries the first run's $2.92 forward.
