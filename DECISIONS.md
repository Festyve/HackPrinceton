# Decisions

One line per decision: **decision** · reason · how to reverse.

## Process and repository
- **Work branch `codex/alibi-build`, nothing committed to `main`** · PLAN §0 names this branch when Eric has not selected one; the repo was on an unborn `main` · `git checkout main && git merge --ff-only codex/alibi-build` (or push the branch to `main`).
- **Human-owned planning pack left untracked and unmodified** (`PLAN.md`, `PLAN_REVIEW.md`, `PLAN_CHANGES.diff`, `TEAM_RUNBOOK.md`, `JUDGING_KIT.md`, `SOURCES.md`, `START_HERE.md`, `CLAUDE.md`, `CLAUDE_SETUP.md`) · the repo must become public for Devpost and these contain team strategy; publishing them is a human call (PLAN §2.1, §15) · `git add <file>` for whichever ones the team wants public.
- **Project/package renamed `hackprinceton` → `alibi`; the 2-line `uv init` hello-world module was replaced** · one coherent package name for CLI, imports and docs · rename in `pyproject.toml` and `src/`.
- **Single integration owner; at most two bounded helpers after contracts stabilized** · PLAN §0 · n/a.

## Tooling
- **Browser QA uses Playwright (Python) driving the installed Google Chrome (`channel="chrome"`)** · the `webapp-testing` skill is not installed; cached Playwright Chromium build (1243) does not match the installed Playwright (needs 1255) and no download is needed with the system browser · `uv run playwright install chromium` and drop the `channel` argument.
- **`frontend-design` plugin not installed; the case board is hand-built to PLAN §13** · plugin install is an interactive `/plugin` action Eric did not run; not a P0 blocker · install it and restyle.
- **No dedicated secret scanner available (gitleaks/trufflehog absent)** · no sudo/system installs overnight (PLAN §2.8); staged files are inspected and scanned with a multi-pattern grep before every push, which PLAN §2.1 notes is not a complete scan · install gitleaks and run `gitleaks detect` before making the repo public.

## Runtime and budget
- **Runtime mode `offline`; live inference BLOCKED** · no key, no local model, $0 budget (PLAN §1.5–1.6) · see BLOCKERS.md B-1.
- **Claude Code's own subscription session is not used as the application's model runtime** · PLAN §1.6/§9.1: the Max subscription does not supply the app's model connection and subscription sessions must not be proxied into an unofficial API · n/a (human decision).
- **`BENCH_MAX_LLM_EPISODES` is rejected with an error instead of converted** · PLAN §10.5 allows either documenting a conversion or rejecting; rejecting cannot silently mis-size a run · accept it in `alibi/config.py` with a documented conversion.

## DeepAgents (verified against installed deepagents 0.7.38)
- **`create_deep_agent(model, tools, *, system_prompt, middleware, subagents, skills, memory, permissions, backend, interrupt_on, response_format, state_schema, context_schema, checkpointer, store, debug, name, cache)`** · read from the installed signature, not from docs · n/a.
- **`SubAgent` keys: `name`, `description` (required), `tools`, `model`, `middleware`, `interrupt_on`, `skills`, `permissions`, `response_format`, `system_prompt`, plus experimental `mode="fork"`** · read from the installed TypedDict · n/a.
- **Built-in tools per installed docstring: `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute`, `task`. Passing `tools=` is additive and never removes a built-in** · so `execute` must be removed explicitly (custom `FilesystemMiddleware(tools=[...])` and/or a harness profile) and audited per agent · n/a.
