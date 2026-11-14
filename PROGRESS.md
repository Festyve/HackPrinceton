# Progress

> Times are America/New_York. Entries record concrete check results, not intentions.
> Status vocabulary: **OFFLINE-READY**, **AI-READY**, **INCOMPLETE** (PLAN §14).

## Pre-existing state (before the overnight goal)

**Last passing check (scaffold):** `uv run python -c "from deepagents import create_deep_agent"` (deepagents 0.7.38, langgraph 1.2.22)

Earlier scaffold milestones, kept for the record (superseded by PLAN.md §12):
1. First end-to-end workflow: Deep Agent + one real tool, a smoke test, and a demo command that turns a sample input into the expected artifact.
2. Resume: persistent SQLite checkpointer with a stable `thread_id`, resume tested in a fresh process.

## Overnight log (Nov 14, 2026)

### 00:17 — Goal started, preflight
- Read CLAUDE.md, PLAN.md (all 19 sections), CLAUDE_SETUP.md, START_HERE.md.
- Git: unborn `main`, no commits, remote `origin` reachable and empty (private, WRITE access). Created work branch `codex/alibi-build` (PLAN §0).
- Verified tools: uv 0.12.3, venv Python 3.13.15, Node 24.19.0, npm 11.17.0, Docker 29.6.2 daemon up (optional, unused), gh authenticated, ChatOverflow CLI 0.1.17, LangChain docs/reference MCP connected, Playwright 1.65.2 drives installed Chrome headlessly (verified with a real launch).
- Not installed: `frontend-design` plugin, `webapp-testing` skill, gitleaks/trufflehog, ollama. None block P0 (see DECISIONS.md).
- **Runtime: no provider key in the environment, no `.env`, no local model server (ports 11434/1234 closed). Mode = `offline`. Live inference = BLOCKED (BLOCKERS.md B-1).**

### 00:29 — M0 bootstrap (commit `ef85955`)
- Package renamed `hackprinceton` → `alibi`; added fastapi, uvicorn, duckdb, pydantic; dev: pytest, httpx, playwright.
- `.env.example` now defaults to `RUNTIME_MODE=offline`, `LLM_MAX_USD=0`, `BENCH_MAX_SYSTEM_RUNS=0`.
- Check: `uv run pytest` → 9 passed (contracts reject truth-bearing extra fields; settings default offline/zero-spend; live mode blocked without an explicit zero-charge route).
- Launch check: `uv run alibi serve --port 8765` answered `/api/health` and `/api/runtime` (mode offline), then stopped cleanly.
- Mode: offline · model budget used: 0 calls, $0.

### 00:41 — M1 SimBackend, step library, frozen evidence (commit `130f37f`)
- `uv run alibi generate --seed 7 --variant incident_coverup --episode-id m1-hero-7` → 16 artifacts, 12,745 events, 0 normalization errors; sealed key written outside the evidence tree.
- `uv run alibi verify m1-hero-7` → `frozen_bundle_intact: true`, saved and reproduced raw-bundle SHA-256 identical (`16724008…c2a9`).
- `uv run alibi steps m1-hero-7` → every executed step with its real outcome (succeeded/failed).
- Check: `uv run pytest` → 44 passed. The browser part of the M1 acceptance was completed in M4.

### 00:49 — M2 checks, verifier, scorer, B0/BR (commit `66e9c04`)
- Local-vs-collector reconciliation recovers the collector-retained line and classifies rotation, forced rotation and collection gaps as benign/open; transfer/session correlation; account-vs-person limits.
- Check: `uv run pytest` → 81 passed (17 check tests, 20 verifier/scorer fixtures incl. duplicates, wrong object, wrong host, broad window, fabricated citation, failed attack, no-crime, abstention).

### 00:57 — Orchestrator + HTTP API (commit `32212dc`); UI helper launched
- Hero flow exercised through the API: create → investigate → early reveal refused (409) → review → lock → reveal (3/3) → reset → 404.
- One bounded Sonnet-class helper built `web/` only (disjoint ownership), 00:57–01:02. Integrated and reviewed by the main session.

### 01:07 — M3 agents, offline-ready path (commit `4e22757`)
- Real DeepAgents 0.7.38 graph (lead + integrity-auditor + skeptic) driven by a **scripted fixture policy**: 17 real tool calls, case notes exported from graph state, review interrupt, resume from the SQLite checkpoint in a fresh runner. `llm_calls = 0`.
- Budget gateway, tool audit, breakout attempts (key path, symlink, `/etc/passwd`, `execute`, `glob`, general-purpose subagent, SQL-shaped filters) all refused; bounded adversary planner tested with fake planners.
- Check: `uv run pytest` → 99 passed. **Live AI acceptance: BLOCKED (B-1), not passed.**

### 01:13 — M4 case board integrated (commits `e26f2ca`, `e3b6cbe`)
- `./start.sh` builds the UI if needed and serves API + UI on localhost.
- Fixed during integration: a segfault when a run was cancelled (checkpoint writer used after the SQLite connection closed; the graph stream is now closed first), negative reported compute time under parallel display pacing, missing 409 for a blocked live runner.
- Check: `uv run pytest` → 114 passed; `uv run pytest tests/test_browser.py` → 7 passed in headless Chrome at 1280×720 (hero flow twice with reset, refresh during review, control case, explanations, hostile evidence rendered as text, benchmark tab, failed-case banner).

### 01:18 — M6 benchmark (config commit `6827f89`, first results `146a7a3`)
- Evaluation config frozen and committed **before** the first run on the declared test seeds 101–112.
- `uv run alibi bench` (first run): B0 16/20 effects, final precision 16/16, raw precision 16/172, cover-ups 0/4, benign final false alerts 0/4 (raw alerts 4/4). BR 20/20, 20/20, cover-ups 4/4, account 8/8, benign false alerts 0/4. AI arms: NOT RUN — runtime unavailable. Model calls: 0.

### 01:20 — ATT&CK label verified and corrected (commits `b6ec49c`, `0ffc5b8`, `4043f5a`)
- Checked displayed technique ids against attack.mitre.org: T1078, T1074.001, T1048.003, T1070.003 confirmed; **T1070.002 now redirects to T1685.006**, so the host-log-removal label was corrected (label only; BR 1.0.1). All 24 per-run benchmark scores verified identical before and after; results regenerated on a clean tree.
- **Honest note:** commits `b6ec49c` and `0ffc5b8` had one red test (a leak check that was too blunt once real benchmark results existed). Fixed in `4043f5a`; the branch is green from there.

### 01:22 — M7 demo assets (commit `d20e1cc`)
- `uv run alibi record --preset hero-coverup --name hero-coverup-fixture` and `sealed-control-fixture`: committed replays, labeled "Scripted fixture · no model inference". Replay regenerates the evidence from the saved scenario and refuses to play if the raw-bundle hash differs.
- Check: `uv run pytest tests/test_m7_demo.py tests/test_browser.py` → 17 passed (replay with network blocked and no runner; every displayed citation opens its raw record for all three presets).
- Measured with `./start.sh` (default display pacing 0.45 s/step, MacBook arm64): hero case generation 0.24 s; first finding on screen 3.4 s; review-ready 10.6 s (compute 0.67 s, the rest is display pacing); accept+lock 0.5 s; unseal+score 0.1 s. Replay of the recorded hero case: review-ready 15.5 s.
