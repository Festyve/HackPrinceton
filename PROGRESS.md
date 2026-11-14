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

### 01:35 — Final verification
- Fresh clone of the branch into a temp directory: `uv sync` → `./start.sh --port 8031` installed npm packages, built the UI and served it; `uv run pytest` passed there; the hero flow ran against that server (early reveal 409 → review → lock → reveal 3/3 → reset).
- Added, because they cost little and unblock Saturday: `uv run alibi smoke` and `uv run alibi pilot` (both refuse to run while live AI is blocked; pilot plumbing tested with a marked test double), provider-aware model arguments for a local Ollama route.
- Pushed `codex/alibi-build` to `origin` (private team repository). Local `runs/` and `sealed/` from tonight's dev servers were removed (gitignored, regenerable).

---

# Morning Handoff (written 01:40 ET, Saturday Nov 14, 2026)

## Status: **OFFLINE-READY**

Not AI-READY. Live inference is **BLOCKED** (no zero-charge runtime was available: no key, no local model). Nothing in this repository is an AI result. The overnight goal stopped early because every applicable OFFLINE-READY check in PLAN §14 passed with real command output; the deadline was 08:30.

- **Branch:** `codex/alibi-build`, pushed to `origin` (`owly1/HackPrinceton`, currently private). `main` has no commits. HEAD is the commit that contains this handoff (`git log -1`); the last code commit before it is `c234ab5`.
- **Spend:** $0. Model calls made by the application: 0. No billing or account setting was touched.

## Commands

```sh
uv sync                                   # once
./start.sh                                # launch: builds the UI if needed, serves http://127.0.0.1:8000
#   stop: Ctrl-C        other port: ./start.sh --port 8010        (8001 is used by another project on Eric's Mac)
uv run pytest                             # all tests (offline, no key)
uv run pytest -m "not browser"            # skip the 8 Chrome tests
uv run alibi runtime                      # mode, caps, and why live AI is blocked
uv run alibi bench --check && uv run alibi bench     # reproduce the offline benchmark
uv run alibi generate --seed 7 --variant incident_coverup --episode-id demo-7 && uv run alibi verify demo-7
uv run alibi record --preset hero-coverup --name <name>    # save a replay under demo/replays/
```

Replay: on the start screen choose a card under **Recorded replays**, press **Run** (or `POST /api/replays/hero-coverup-fixture/open`). Fallbacks: `ALIBI_DEFAULT_RUNNER=deterministic ./start.sh` (checks without the agent graph), `ALIBI_DEMO_PACE_S=0.25 ./start.sh` (faster display pacing).

## Test output (01:35 ET, this machine)

```
$ uv run pytest
142 passed in 63.36s (0:01:03)
$ uv run pytest -m browser
8 passed, 134 deselected in 17.82s
$ npm --prefix web run build
✓ built in 239ms            (tsc --noEmit strict + vite build)
$ uv run alibi bench --check
evaluation config matches the code: docs/evaluation-config.json
```

## Modes actually used

| | Mode |
|---|---|
| Evidence origin | `SIM` (simulated). No Docker, no real artifact, no external dataset. |
| Demo inference | `Scripted fixture · no model inference`: the real DeepAgents graph (lead + integrity-auditor + skeptic) driven by scripted control flow. Fallback: `Deterministic baseline · no model inference`. |
| Demo playback | `LIVE` (runs on the spot) or `REPLAY` (two committed fixture recordings). |
| Adversary plan | `Scripted scenario · no model chose these steps`. |
| Benchmark | B0 and BR only, offline. B1, B1+, B2, ALIBI: `NOT RUN — runtime unavailable`. |
| Model credits / caps | None available. Defaults: `RUNTIME_MODE=offline`, `LLM_MAX_USD=0`, `BENCH_MAX_SYSTEM_RUNS=0`. Caps if a runtime appears: 12 calls, 40k input / 6k output tokens, 90 s per investigation, shared. |

## Measured results

Offline benchmark `offline-v1`, 12 declared cases (8 incidents, 4 benign controls), simulated evidence, run `20261114T062011Z` at commit `b6ec49c` on a clean tree. Source: [`benchmarks/offline-v1/results.json`](benchmarks/offline-v1/results.json), report: [`docs/benchmark.md`](docs/benchmark.md), locked reports: `benchmarks/offline-v1/reports/`.

| System | Effects caught | Incident cases fully reconstructed | Cover-ups detected | Final precision | Raw proposals correct | Account identified | Benign final false alerts | Benign raw alerts |
|---|---|---|---|---|---|---|---|---|
| B0 keyword recipe | 16/20 | 4/8 | 0/4 | 16/16 | 16/172 | 0/8 | 0/4 | 4/4 |
| BR deterministic checks | 20/20 | 8/8 | 4/4 | 20/20 | 20/20 | 8/8 | 0/4 | 0/4 |
| AI arms | NOT RUN | | | | | | | |

Read this with its caveats: n = 12; BR's checks were written against this simulator; B0's final precision is produced by the shared verifier; simulator v1 leaves the adversary's commands in shell history, which favors B0. No significance is claimed.

Demo timings, `./start.sh` defaults, Eric's MacBook: generation 0.24 s · first finding on screen ~3.4 s · review-ready ~10.6 s (0.67 s compute, the rest is display pacing) · accept+lock 0.5 s · unseal+score 0.1 s. Replay review-ready ~15.5 s.

## PLAN §14 checklist

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | One command launches; hero case and benign controls run capture → normalize → checks → review → lock → reveal → score → reset | **PASS** | `./start.sh`; `tests/test_browser.py` (hero twice with reset, sealed control), `tests/test_m4_api_isolation.py`; fresh-clone run |
| 2 | P0 controls and scorer checks pass; every displayed citation opens; read-only evidence vs writable notes | **PASS** | `tests/test_m2_checks.py`, `tests/test_m2_verifier_scorer.py`, `tests/test_m7_demo.py::test_every_displayed_citation_opens_its_raw_record` |
| 3 | Tool/manifest/stream isolation tests; no shell or arbitrary SQL for either runtime agent | **PASS** as an agent capability boundary (not OS isolation) | `tests/test_m3_agents.py`, `tests/test_m4_api_isolation.py` |
| 4 | B0 and BR on the declared suite with counts, raw records, reproduction; AI arms unrun | **PASS** | `benchmarks/offline-v1/`, `docs/benchmark.md`, `tests/test_m6_bench.py` |
| 5 | Labeled fixture/replay with model access disabled; failure, reconnect, reset; no keys or truth before reveal | **PASS** | `tests/test_m7_demo.py`, restart/reconnect/cancel tests in `tests/test_m4_api_isolation.py`; secret-pattern scan of all tracked files: 0 hits (grep-based, not a full scanner) |
| 6 | Offline tests and frontend build pass; branch green; push status | **PASS** | output above; pushed to `origin/codex/alibi-build` |
| 7 | Real-model DeepAgents run with traces and usage | **BLOCKED** (B-1) | not attempted: no runtime |
| 8 | Recording of a real run replays offline | **BLOCKED** (B-1) | only scripted-fixture recordings exist |
| 9 | Paired 8-system-run AI pilot | **BLOCKED** (B-1) | `uv run alibi pilot` exists and refuses to run |

## What went wrong overnight (so nobody is surprised)

- **No AI ran.** This is the big one for the LangChain and "AI-driven" track stories.
- A segfault when cancelling a run (checkpoint writer used after its SQLite connection was closed). Fixed and covered by a test that passed six repeated runs.
- Reported compute time was negative when tool calls ran in parallel under display pacing. Fixed.
- The ATT&CK id shown for host log removal was stale (T1070.002 now redirects to T1685.006). Corrected; benchmark rerun with identical scores; first run kept at commit `146a7a3`.
- Commits `b6ec49c` and `0ffc5b8` had one red test (my command pipeline hid the failure). Fixed in `4043f5a`.
- The UI was built by one bounded helper. I read `App.tsx`, `panels.tsx` and `bench.tsx` in full and restructured the centre column; `evidence.tsx`, `score.tsx`, `model.ts`, `api.ts` were checked through the browser tests and screenshots, not line by line.
- Not built: network diagram with activity pulses, Docker backend, crime cards 1 and 2, B1/B2 builders, free-form Q&A, evidence-availability experiment, IoT-CAD.
- Not verified: anything on a second physical machine or the venue projector; any model's behavior with the prompts and tool schemas.

## Blockers (details in BLOCKERS.md)

- **B-1** live AI inference (Eric) · **B-2** repository is private (Rayan/Eric) · **B-3** optional coding plugins not installed (non-blocking) · **B-4** not checked on a second machine/projector (Terry/Daniel) · **B-5** `main` does not exist on the remote (Eric).
- No blocker remains for OFFLINE-READY.

## Next task per person

- **Eric (engineering):** (1) Decide the runtime route in BLOCKERS B-1 within a 15-minute box; if one works: `uv run alibi runtime` must show `"live_block_reason": null`, then `uv run alibi smoke`, then one hero case in the UI, then `BENCH_MAX_SYSTEM_RUNS=8 uv run alibi pilot`, then `uv run alibi record --preset hero-coverup --name hero-coverup-live --runner agent-live`. Expect to fix prompts or tool schemas on first contact. (2) Create `main` from this branch after reading the diff. (3) Only then choose one P1: second crime card with its benign control, or a thin Docker slice.
- **Rayan (product, tracks, presentation):** Read [`docs/claims.md`](docs/claims.md) and decide the pitch wording for the offline state; item 12 lists phrases to avoid until a model has run. Decide whether the LangChain track entry is credible without a real run. Edit [`docs/devpost.md`](docs/devpost.md) and start the Devpost draft. Decide which planning-pack files become public and when the repository flips to public (B-2).
- **Daniel (evidence and evaluation QA):** Do not take the 20/20 on trust. Open three locked reports in `benchmarks/offline-v1/reports/` and check their citations in the UI or with `uv run alibi generate --seed <seed> --variant <variant>`. Then write two cases designed to break BR (ideas: a line removed from the oldest retained log generation, a transfer just under the 5 MB threshold, two overlapping sessions) and report what happens. If a rule has to change, the version is bumped and a fresh test split is declared (`docs/evaluation-config.json`).
- **Terry (UX, demo operation, video):** Run `./start.sh` on your own machine and on the real display. Rehearse [`docs/demo-script.md`](docs/demo-script.md) with a timer, including the replay fallback and a mid-review page refresh. Send Eric a list of anything unreadable at distance. Screenshots to start from: `docs/screenshots/`.

## Where things are

README: [`README.md`](README.md) · architecture: [`docs/architecture.md`](docs/architecture.md) · claims: [`docs/claims.md`](docs/claims.md) · judge Q&A: [`docs/judge-qa.md`](docs/judge-qa.md) · demo script: [`docs/demo-script.md`](docs/demo-script.md) · decisions: [`DECISIONS.md`](DECISIONS.md) · screenshots: [`docs/screenshots/case-board-review.png`](docs/screenshots/case-board-review.png), [`case-board-unsealed.png`](docs/screenshots/case-board-unsealed.png), [`benchmark-tab.png`](docs/screenshots/benchmark-tab.png) · replays: `demo/replays/`.

Housekeeping: the human-owned planning pack (`PLAN.md`, `TEAM_RUNBOOK.md`, `JUDGING_KIT.md`, `CLAUDE.md`, …) is untouched and untracked on Eric's machine. ChatOverflow: 4 notes voted up after use, 1 comment, 1 generic field note (a LangGraph/SQLite shutdown-order crash); nothing about the project was shared.
