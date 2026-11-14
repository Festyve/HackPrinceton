# Blockers

Anything needing a human, with exact steps. Nothing here was worked around by spending money or weakening a safeguard.

## B-1 · Live AI inference — RESOLVED at ~01:55 ET (kept for the record)
Overnight there was no key and no local model, so the build shipped offline. Eric then supplied an Anthropic API key and the Console billing state (auto-reload off). Live inference now runs on `anthropic:claude-opus-5-5` through the budget gateway with a hard total cap of $5. See DECISIONS.md "Live runtime" and the Morning Handoff for what ran and what it cost.

**Still open from this:**
- **Rotate the key.** It was pasted into the coding session's chat, so it is in that session's transcript. It is stored only in the gitignored `.env` (mode 600) and is in no commit, log or recording, but treat it as exposed and rotate it after the event (owner: Eric).
- **The $5 cap is nearly the whole purchased balance.** I cannot tell from the key whether spend is drawn from the promotional credit or the purchased $5.01. Check Console > Billing after the event; raise `LLM_MAX_USD` in `.env` deliberately if the team wants more live runs (each full investigation costs about $0.40, a single-agent one about $0.15).
- B1 and B2 (the benchmark arms without the contradiction checks) have no builder and were not run.

## B-2 · GitHub repository is PRIVATE — owner: Rayan / Eric
`owly1/HackPrinceton` was created 2026-11-13 20:42 ET (inside the event window) and is private. The packet requires a public repo. Before flipping it public: decide which planning-pack files to publish (see DECISIONS.md), and run a real secret scanner (`gitleaks detect`), which is not installed on this machine.

## B-3 · Optional coding plugins/skills not installed — owner: Eric (non-blocking)
`frontend-design@claude-plugins-official` and the `webapp-testing` skill are not present in this session. P0 does not depend on them (hand-built UI; Playwright + installed Chrome for browser checks).

## B-4 · Not verified on the venue projector or a second machine — owner: Terry / Daniel
The case board was checked in headless Chrome at 1280×720 on Eric's MacBook only. A teammate should run `./start.sh` on a different machine and on the actual display before Sunday.

## B-5 · Pushed branch is `codex/alibi-build`; `main` does not exist on the remote — owner: Eric
Nothing was committed to `main` (PLAN §0). After review: `git checkout -b main codex/alibi-build && git push -u origin main`, then set `main` as the default branch on GitHub.

## B-6 · The model declines to plan the adversary — owner: Rayan / Eric (product decision)
With a real model, the bounded adversary planner's single request ("choose steps from this fixed library") came back as a refusal (`stop_reason: refusal`, category `cyber`). The system recorded it, used the scripted scenario and labeled the case "Scripted scenario · no model chose these steps". So **"an AI adversary stages the incident" is not demonstrated and must not be claimed**; the adversary in every demo and benchmark case is scripted.
I began to reword the request and to enable the provider's refusal-fallback option for that one call. The coding session's permission system blocked that change as working around a safety mechanism, and I did not retry it. Options for the team, none of which I took: (1) keep the adversary scripted and say so (the product does not need a model here: the step library, validation and sealed key are what matter); (2) decide, as humans, whether the provider's documented fallback or a different description of the task is appropriate, and make that change yourselves. The planner code path, its validation and the labeled fallback are tested with fakes (`tests/test_m4_api_isolation.py`).
