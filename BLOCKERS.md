# Blockers

Anything needing a human, with exact steps. Nothing here was worked around by spending money or weakening a safeguard.

## B-1 · Live AI inference is BLOCKED (no zero-charge runtime verified) — owner: Eric
**Observed 00:20 ET:** no `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENROUTER_API_KEY` in the environment, no `.env`, `ollama` not installed, nothing listening on 11434 or 1234.
**Effect:** every AI acceptance check (PLAN §14 items 7–9) is **BLOCKED, not passed**. AI benchmark arms read `NOT RUN — runtime unavailable`.
**To unblock (pick one, spend $0):**
1. *Local model:* install and start a tool-calling local model yourself (15-minute box), then in `.env`: `RUNTIME_MODE=live`, `LIVE_PROVIDER_KIND=local`, `LEAD_MODEL=<provider:model>` (for Ollama: `ollama:<model>`). A local provider package (e.g. `langchain-ollama`) needs `uv add`. Unverified pointers from another agent's field note on deepagents 0.7.38 + Ollama: the default 4096-token context silently truncates the harness prompt (this code therefore passes `num_ctx`, default 16384, override with `LLM_NUM_CTX`), and some local models reject tool calling outright, which `uv run alibi smoke` will show in one call.
2. *Verified included/sponsor credits with no paid fallback:* confirm the balance and that auto-reload/overage is off in the provider console, then in `.env`: the provider key, `RUNTIME_MODE=live`, `LIVE_PROVIDER_KIND=included_credits`, `LLM_MAX_USD=<credit cap>`, `LLM_PRICE_IN_PER_MTOK`, `LLM_PRICE_OUT_PER_MTOK`, `LEAD_MODEL=<provider:model>`.
Then follow "After the runtime is unblocked" in the Morning Handoff (PROGRESS.md). Do not paste keys into chat, logs or the frontend.

**What is ready for the moment a runtime exists:** the graph, tools, prompts, budget ledger and review interrupt (`src/alibi/agents/`), selected automatically when `uv run alibi runtime` shows `"live_block_reason": null`; `uv run alibi smoke` (one tiny tool-calling call); `uv run alibi pilot` (the predeclared 4 cases × B1+/ALIBI, capped by `BENCH_MAX_SYSTEM_RUNS`). Both commands refuse to run while blocked. The pilot plumbing is tested with a test double only. **Expect prompt and tool-schema fixes on first contact with a real model:** none of the prompts has ever been read by one, and B1 and B2 (the arms without checks) have no builder yet.

## B-2 · GitHub repository is PRIVATE — owner: Rayan / Eric
`owly1/HackPrinceton` was created 2026-11-13 20:42 ET (inside the event window) and is private. The packet requires a public repo. Before flipping it public: decide which planning-pack files to publish (see DECISIONS.md), and run a real secret scanner (`gitleaks detect`), which is not installed on this machine.

## B-3 · Optional coding plugins/skills not installed — owner: Eric (non-blocking)
`frontend-design@claude-plugins-official` and the `webapp-testing` skill are not present in this session. P0 does not depend on them (hand-built UI; Playwright + installed Chrome for browser checks).

## B-4 · Not verified on the venue projector or a second machine — owner: Terry / Daniel
The case board was checked in headless Chrome at 1280×720 on Eric's MacBook only. A teammate should run `./start.sh` on a different machine and on the actual display before Sunday.

## B-5 · Pushed branch is `codex/alibi-build`; `main` does not exist on the remote — owner: Eric
Nothing was committed to `main` (PLAN §0). After review: `git checkout -b main codex/alibi-build && git push -u origin main`, then set `main` as the default branch on GitHub.
