# Progress

> Times are America/New_York. Entries record concrete check results, not intentions.
> Status vocabulary: **OFFLINE-READY**, **AI-READY**, **INCOMPLETE** (PLAN §14).

## Current state — second run, Saturday November 14, 08:10 ET

This block is the handoff. Everything below it is the build history, oldest first.

| | |
|---|---|
| Branch and commit | `codex/eric-phase2`, pushed, and the default branch `codex/alibi-build` fast-forwarded to the same tested tree. The commit is the tip of those branches (this file is updated with each slice). |
| Launch | `uv sync --frozen && ./start.sh`, then http://127.0.0.1:8000. `./start.sh --port 8010` if the port is busy. |
| Demo selection | Recorded replays. For the pitch: **Inside job · cover-up** recorded on Claude Opus 5.5 (specialist mode) or on Claude Haiku 5.5 (fast mode, with two recorded question answers). Also recorded on Haiku: **Records heist** and **Cold chain**. No key or network needed. |
| Model in use | `anthropic:claude-haiku-5-5`, effort low, for every role. Opus 5.5 recordings and pilot are from the first run and unchanged. |
| Spend | Estimated **$3.517** of the **$20** cap across both runs (543 model calls). This run: about **$0.59**. Reserved: $0. Unreconciled: $0. Automatic calls stop at $19.50. `uv run alibi spend`. |
| Tests | `uv run pytest` → **450 passed**: 429 offline, 21 in headless Chrome. On the UI fallback branch the browser count is 30. A fresh clone of the default branch at `c0cf94e` (07:50) installed, built, passed every test and served the recorded demo with no key and no `.env`. |
| Recordings | `demo/replays/`: 4 real-model runs (1 Opus, 3 Haiku) and 2 scripted-fixture runs. All six reproduce their evidence byte for byte and replay offline. |
| Measured results | `benchmarks/offline-v1`, `benchmarks/ai-pilot-v1` (first run, frozen); `benchmarks/paired-v2` and `benchmarks/paired-v2-rep1` (this run's evaluation and its replication; summary in `docs/evaluation-summary.md`); `benchmarks/calibration`, `benchmarks/feature-checks`, `benchmarks/paired-v2-dev` (operational checks). |

**What works end to end now**

- Budget gateway that counts, bounds and reserves every model call and keeps unknown outcomes at worst case.
- Fast (one agent) and specialist (three agents) investigations, saved with the case.
- Questions about a case, with each claim checked by trusted code. Real answers recorded.
- Source-removal experiment: a derived evidence view without chosen sources, a deterministic comparison of the original claims, and a fresh real-model investigation of the reduced view.
- Three case families and four more cover-up steps, each with sealed controls.
- Scenario designer: a model chooses an ordinary environment from fixed options. It plans no incident.
- Report export with lock hash, provenance and exact cited lines.
- Paired evaluation of six systems on six new cases in two separately declared suites.
- Terminal commands for the whole flow: `alibi run`, `experiment`, `ask`, `review`, `export`, `import`, `cases`.
- A read-only view of a cold-chain case's two temperature records (`GET /api/cases/{id}/evidence/sensor-streams`).
- Two independent reviews (budget code; information barrier and input handling) with every finding fixed and pinned by a test.

**What is not done, and who has it** (details in [BLOCKERS.md](BLOCKERS.md))

- **No captured evidence exists in this build.** `codex/daniel-capture` has not been pushed. Every bundle is simulated. This session did not build a capture of its own: Docker runs on this machine but no container image is cached, pulling one is a download that needs a person's approval, and the capture side is Daniel's. The receiving side is built and tested: `uv run alibi import <directory>` freezes a capture as an unscored case ([`docs/importing.md`](docs/importing.md)). (Daniel to deliver the capture; Eric to merge it.)
- **The case board on the default branch does not yet call the new routes** (questions, source experiment, export, mode choice, temperature records, designer, new results). `codex/terry-ui` has not moved since 04:24. A working fallback for all but the designer is on **`codex/eric-ui-wiring`** (`98a90a8`): 30 browser tests pass there, it was checked by eye in Chrome at 1440 and 390 px wide, and one real-model question was asked through it in a browser (`benchmarks/feature-checks/live-question-in-browser-haiku-5-5.json`). It is **not merged**, because `web/` is Terry's. (Terry to take, change or replace it. If nothing arrives before the feature freeze, Eric's session merges the fallback and records that in DECISIONS.md.)
- **The adversary planner stays disabled** after the model's refusal. Not worked around. Every incident is a scripted scenario.
- Not verified: a second machine, the venue projector, any model other than Opus 5.5 and Haiku 5.5, run-to-run variance.

**Owner actions**

1. Eric: rotate the API key (it was pasted into chat); edit only the key line in `.env`.
2. Terry: add UI controls for the new routes, or take `codex/eric-ui-wiring`; rebase on `codex/eric-phase2`. See [`docs/ui-integration-brief.md`](docs/ui-integration-brief.md).
3. Daniel: push the capture branch with its importer entry point.
4. Repository owner: make the repository public. A redacted scan of the worktree and of every commit found no credential-like string, and `.env` and the ledger were never committed.
5. Rayan: decide the pitch from [`docs/claims.md`](docs/claims.md). The honest headline from the measurements is that the deterministic comparison does the detecting (16 of 16 incident effects on the new cases) and the model investigates, explains and answers; the checks lifted one agent from 10 to 15 of 16; one agent did better than three.

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

### 01:50–02:15 — Live runtime unblocked by Eric (commits `53320d0`, `3f0a80e`)
- Eric supplied an Anthropic API key and the Console billing state (auto-reload off) and chose Claude Opus 5.5 with a $5 cap. Key stored only in the gitignored `.env`; verified with the free Models endpoint before any billed call.
- Built before spending: a total-spend ledger (`LLM_MAX_USD` caps all billed calls across runs), cache-aware cost estimates, refusal handling, correct Claude model arguments.
- `uv run alibi smoke` → real tool call from `claude-opus-5-5` (385 tokens in, 46 out, est. $0.0025).
- Real run 1 (hero case, declared caps): correct analysis by the integrity-auditor, then **stopped by the 40,000 input-token cap after 5 calls** (est. $0.17). Recorded as an incomplete run. Caps revised from this measurement and written into the frozen config before any AI benchmark run.
- Real run 2 (hero case): **complete**. 11 model calls (lead 6, integrity-auditor 3, skeptic 2), 109,772 input tokens (73,116 cache reads), 8,047 output tokens, 76.8 s, est. $0.37. Todos, delegation, case notes, 5 findings all supported by the verifier, attribution "account used; human operator not established". After a fresh-process restart: accept → the paused graph resumed from its SQLite checkpoint → locked → unsealed: **3/3 effects caught, final precision 3/3, cover-up detected, account identified, no named person, 29/29 citations valid**. Saved as `demo/replays/hero-coverup-live-opus-5-5`.
- Real run 3, through the real UI in Chrome (preset "model-planned adversary"): investigator again 3/3 in 78 s with the "Live model" badge. **The adversary planning call was declined by the model's safety classifier (category `cyber`)**; the case fell back to the scripted scenario and was labeled so. A change to work around that refusal was blocked by the session's permission system and was not pursued (BLOCKERS B-6).
- Development run of the single-agent baseline B1+ on the demo seed: 3 calls, 26 s, est. $0.13, 3/3, but its attribution was missing from the draft because it shared a turn with `finalize_report` and the review pause held it. Harness fixed and tested before the pilot.
- Check: `uv run pytest -m "not browser"` → 143 passed.

### 02:15–02:30 — AI pilot and wrap-up (commit `1ebe13c` and the handoff commit)
- `BENCH_MAX_SYSTEM_RUNS=8 uv run alibi pilot` on a clean tree at `3f0a80e`: 8/8 system-runs completed, none stopped by budget, no errors. B1+ and ALIBI each 5/5 effects, 1/1 cover-up, 2/2 accounts, 0/2 benign false alerts, 0 named attributions. ALIBI 42 calls / est. $1.30 / median 58.6 s; B1+ 15 calls / est. $0.50 / median 19.2 s. **Delegation did not improve accuracy in this pilot.**
- Fixed after the pilot: the start-screen card of the recorded real run said "Live model" (now "Recorded AI run", covered by a browser test); the "model-planned adversary" preset is opt-in because it can only fall back to scripted; benchmark tab and report show the live rows and say "not part of the pilot" for B1 and B2.
- Recorded-run replay on an offline server: first finding 4.9 s, review-ready 16.0 s, labels `Recorded AI run` / `REPLAY`.
- Check: `uv run pytest` → 153 passed (9 in headless Chrome). Estimated total model spend: $2.92 of the $5 cap, 91 calls.

---

# Morning Handoff (rewritten 02:30 ET, Saturday Nov 14, 2026)

## Status: **OFFLINE-READY, plus a real-model investigator demonstrated. Not fully AI-READY.**

- Everything required for OFFLINE-READY (PLAN §14 items 1–6) passes with real command output.
- After Eric supplied a key at about 01:50, the investigator ran on a real model (Claude Opus 5.5): one complete recorded run, one run through the UI, and the declared 8-run pilot. Items 8 and 9 pass.
- **Item 7 is only partly met:** investigator delegation, case notes, skeptical review and review/resume ran on a real model. Bounded adversary planning did not: the model declined that request (safety classifier, category `cyber`). **The adversary is scripted in every case. Do not say "AI adversary".**
- **Branch:** `codex/alibi-build`, pushed to `origin` (`owly1/HackPrinceton`, private). `main` has no commits. HEAD is the commit containing this handoff (`git log -1`).
- **Spend:** an estimated **$2.92** of the $5 cap Eric set, 91 model calls. Auto-reload is off on the account (per Eric's Console page), so nothing beyond the existing balance can be charged. No billing setting was touched. **The key was pasted into the coding chat: rotate it after the event.** It is only in the gitignored `.env`.

## Commands

```sh
uv sync                                   # once
./start.sh                                # launch: builds the UI if needed, serves http://127.0.0.1:8000
#   stop: Ctrl-C        other port: ./start.sh --port 8010        (8001 is used by another project on Eric's Mac)
uv run pytest                             # all tests; they always run offline, whatever .env says
uv run alibi runtime                      # mode, model, caps
uv run alibi spend                        # estimated total spend against LLM_MAX_USD
uv run alibi bench --check && uv run alibi bench            # reproduce the offline benchmark (no model)
uv run alibi smoke                        # one tiny real call (a fraction of a cent)
BENCH_MAX_SYSTEM_RUNS=8 uv run alibi pilot                  # rerun the AI pilot: about $1.80, 8 minutes
uv run alibi record --preset hero-coverup --name <name>     # save a replay under demo/replays/
```

- **Replay (free, no network):** start screen → **Recorded replays** → **Inside job · cover-up** tagged *Recorded AI run* → **Run**.
- **On Eric's machine `.env` is in live mode**, so **Run** on a preset calls Claude Opus 5.5 (about a minute, about $0.35). To run without spending: `ALIBI_DEFAULT_RUNNER=agent-fixture ./start.sh`, or set `RUNTIME_MODE=offline` in `.env`.
- A fresh clone has no `.env` and is fully offline.

## Test output (02:29 ET, this machine)

```
$ uv run pytest
153 passed in 65.11s (0:01:05)
$ uv run pytest -m browser
9 passed, 144 deselected in 19.97s
$ npm --prefix web run build
✓ built in 227ms            (tsc --noEmit strict + vite build)
$ uv run alibi bench --check
evaluation config matches the code: docs/evaluation-config.json
$ uv run alibi spend
{ "cap_usd": 5.0, "spent_usd": 2.922403, "reserved_usd": 0, "remaining_usd": 2.077597, "calls": 91 }
```

## Modes

| | Mode |
|---|---|
| Evidence origin | `SIM` (simulated). No Docker, no real artifact, no external dataset. |
| Adversary plan | `Scripted scenario · no model chose these steps`, always. |
| Demo inference (recommended) | `Recorded AI run` · playback `REPLAY`: the saved Claude Opus 5.5 investigation of the hero case. |
| Demo inference (optional) | `Live model` (about a minute per case), or `Scripted fixture · no model inference` offline. |
| Benchmark | B0, BR offline on 12 cases. B1+, ALIBI on a real model on 4 of them. B1, B2 not run. |
| Model and caps | `anthropic:claude-opus-5-5`, effort `low`. Total cap $5. Per investigation: 16 calls, 200k input / 10k output tokens, 180 s. |

## Measured results

**Offline suite `offline-v1`**: 12 declared cases, run `20261114T062011Z` at commit `b6ec49c`.

| System | Effects caught | Cover-ups detected | Final precision | Raw proposals correct | Account identified | Benign final false alerts |
|---|---|---|---|---|---|---|
| B0 keyword recipe | 16/20 | 0/4 | 16/16 | 16/172 | 0/8 | 0/4 (raw alerts 4/4) |
| BR deterministic checks | 20/20 | 4/4 | 20/20 | 20/20 | 8/8 | 0/4 |

**AI pilot `ai-pilot-v1`**: cases T01, T05, T10, T12, run `20261114T071403Z` at commit `3f0a80e`, 8/8 completed.

| System | Effects caught | Cover-ups | Account identified | Benign false alerts | Named a person | Model calls | Tokens in / out | Est. cost | Median time |
|---|---|---|---|---|---|---|---|---|---|
| B1+ single agent | 5/5 | 1/1 | 2/2 | 0/2 | 0 | 15 | 162,489 / 8,898 | $0.50 | 19.2 s |
| ALIBI lead + 2 specialists | 5/5 | 1/1 | 2/2 | 0/2 | 0 | 42 | 395,398 / 26,075 | $1.30 | 58.6 s |

**Recorded hero run** (`demo/replays/hero-coverup-live-opus-5-5`): 11 model calls, 109,772 input tokens (73,116 cache reads), 8,047 output tokens, 76.8 s, est. $0.37; 3/3 effects, 29/29 citations valid, no named person.

Sources: [`benchmarks/offline-v1/results.json`](benchmarks/offline-v1/results.json), [`benchmarks/ai-pilot-v1/results.json`](benchmarks/ai-pilot-v1/results.json), locked reports beside them, [`docs/benchmark.md`](docs/benchmark.md).

Read with the caveats: small n, one run per AI cell, simulated evidence, checks written against this simulator and used by both AI systems. The pilot does not show that the three-agent design is better; it shows it costs more for the same answers on these cases.

**Latency:** a live three-agent investigation took 53–78 s, over the 45 s demo target, so the demo script uses the recording (review-ready in 16 s). Offline fixture run: about 10 s.

## PLAN §14 checklist

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | One command launches; hero case and benign controls run capture → … → reset | **PASS** | `./start.sh`; `tests/test_browser.py`, `tests/test_m4_api_isolation.py`; fresh-clone run at 01:35 |
| 2 | P0 controls and scorer checks; every displayed citation opens; evidence read-only vs notes | **PASS** | `tests/test_m2_*.py`, `tests/test_m7_demo.py` |
| 3 | Tool/manifest/stream isolation; no shell or arbitrary SQL for either runtime agent | **PASS** as an agent capability boundary (not OS isolation) | `tests/test_m3_agents.py`, `tests/test_m4_api_isolation.py` |
| 4 | B0 and BR on the declared suite with counts, raw records, reproduction | **PASS** | `benchmarks/offline-v1/`, `tests/test_m6_bench.py` |
| 5 | Labeled fixture/replay with model access disabled; failure, reconnect, reset; no keys or truth before reveal | **PASS** | `tests/test_m7_demo.py`; secret-pattern scan of tracked files: 0 hits (grep-based, not a full scanner) |
| 6 | Offline tests and frontend build pass; branch green; push status | **PASS** | output above; pushed |
| 7 | Real-model DeepAgents run: adversary planning, delegation, case notes, skeptical review, review/resume, traces and usage | **PARTIAL** | Investigator side: yes (recording, pilot, restart-then-accept resume). **Adversary planning: declined by the model**, scripted fallback used and labeled (BLOCKERS B-6) |
| 8 | Recording of a real run replays offline with its provenance | **PASS** | `test_recorded_real_run_replays_as_a_recorded_ai_run_never_as_live`, `test_committed_recording_replays_with_no_network_and_no_inference` |
| 9 | Paired 8-system-run pilot within confirmed resources; demo latency measured | **PASS** | 8/8 completed for an estimated $1.80; latency above |

## What went wrong (so nobody is surprised)

Overnight, before the key:
- A segfault when cancelling a run (checkpoint writer used after its SQLite connection closed). Fixed; the cancel test passed six repeated runs.
- Negative compute time under parallel display pacing. Fixed.
- A stale ATT&CK id (T1070.002 now redirects to T1685.006). Corrected; scores unchanged.
- Commits `b6ec49c` and `0ffc5b8` had one red test because my command pipeline hid the failure. Fixed in `4043f5a`.

With the real model:
- **The model declined to plan the adversary.** I started a change to reword the request and add the provider's refusal fallback; the session's permission system blocked it as working around a safety mechanism and I did not retry. The adversary stays scripted.
- The first real run was stopped by the planning-time token cap after 5 calls (est. $0.17 spent on an incomplete run). Caps were revised from that measurement before any benchmark run.
- The model wrote correct but free-form object names that the frozen matching rule would have rejected. The tool contract was tightened; the scorer was not loosened.
- A single agent submitted its attribution in the same turn as the review request, and the review pause held it back. Found in a development run, fixed and tested before the pilot.
- The recorded real run was listed as "Live model" on the start screen. Fixed after a browser test caught it.

Still true:
- The UI was built by one bounded helper. I read `App.tsx`, `panels.tsx` and `bench.tsx` in full; the rest is covered by browser tests and screenshots, not line-by-line review.
- Not built: network diagram, Docker backend, crime cards 1 and 2, B1/B2 builders, free-form Q&A, evidence-availability experiment, IoT-CAD.
- Not verified: a second machine or the venue projector; any model other than Claude Opus 5.5; run-to-run variance; a model's reaction to hostile text in evidence.

## Blockers (details in BLOCKERS.md)

- **B-1** live inference: resolved. Follow-ups: rotate the key; decide the spend cap for Saturday (about $2.08 of the $5 estimate is left).
- **B-2** repository is private (Rayan/Eric) · **B-3** optional coding plugins (non-blocking) · **B-4** second machine and projector check (Terry/Daniel) · **B-5** `main` does not exist on the remote (Eric).
- **B-6** the model declines to plan the adversary: a product decision for Rayan and Eric.

## Next task per person

- **Eric (engineering):** (1) Rotate the API key after the event and check Console > Billing to see which balance the $2.92 actually came from. (2) Create `main` from this branch after reading the diff. (3) If the team wants a stronger AI story, the most informative next experiment is a harder case set or the arms without the checks (B1, B2), not more of the same pilot. Each three-agent run is about $0.35.
- **Rayan (product, tracks, presentation):** Decide the pitch around two honest facts: the adversary is scripted, and in our pilot one agent matched three at a third of the cost. [`docs/claims.md`](docs/claims.md) lists safe and unsafe wording; [`docs/devpost.md`](docs/devpost.md) is redrafted on that basis. Decide B-6 and when the repository goes public (B-2).
- **Daniel (evidence and evaluation QA):** Open three locked reports in `benchmarks/ai-pilot-v1/reports/` and three in `benchmarks/offline-v1/reports/` and check their citations in the UI. Then design two cases meant to break BR and the agents (a line removed from the oldest retained log generation, a transfer just under the 5 MB threshold, two overlapping sessions). A rule change means a version bump and a fresh declared split.
- **Terry (UX, demo operation, video):** Run `./start.sh` on your own machine (it will be offline there) and on the real display. Rehearse [`docs/demo-script.md`](docs/demo-script.md) with a timer using the *Recorded AI run* replay, including a mid-review page refresh. Screenshots to start from: `docs/screenshots/`.

## Where things are

README: [`README.md`](README.md) · architecture: [`docs/architecture.md`](docs/architecture.md) · claims: [`docs/claims.md`](docs/claims.md) · judge Q&A: [`docs/judge-qa.md`](docs/judge-qa.md) · demo script: [`docs/demo-script.md`](docs/demo-script.md) · decisions: [`DECISIONS.md`](DECISIONS.md) · screenshots: [`docs/screenshots/case-board-recorded-ai.png`](docs/screenshots/case-board-recorded-ai.png), [`case-board-unsealed.png`](docs/screenshots/case-board-unsealed.png), [`benchmark-tab.png`](docs/screenshots/benchmark-tab.png) · replays: `demo/replays/`.

Housekeeping: the human-owned planning pack (`PLAN.md`, `TEAM_RUNBOOK.md`, `JUDGING_KIT.md`, `CLAUDE.md`, …) is untouched and untracked on Eric's machine. Pilot tool traces are kept locally in `benchmarks/ai-pilot-v1/transcripts/` (gitignored). ChatOverflow: 4 notes voted up after use, 1 comment, 2 generic field notes; nothing about the project was shared.


## Phase-two review and handoff — November 14, 2026

Reviewed implementation commit `874cc5f`. This change updates documentation and supplies the next implementation assignment; it does not claim phase-two application features are already built. Start at `docs/next-run/START_HERE.md`.

- Confirmed real investigator recording and pilot; original adversary remains scripted.
- Rayan reconfirmed **$5 cumulative**, with no increase. Preserve the existing ledger. Budget reservation/unknown-usage review findings must be fixed before more live calls.
- Eric owns backend/integration; Terry the full UI; Daniel real Linux capture/import and independent controls; Rayan product acceptance, feedback and presentation.
- Rewrote README, demo script, judge answers, Devpost copy and remaining owner actions. Added exact prompts, key setup, API contracts, deadlines and acceptance gates.
- Reviewer validation: frontend TypeScript/Vite build passed; 143 non-browser tests passed, one asset test initially skipped before UI build and then passed separately; all 9 Chrome browser tests passed. Total: 153 passing checks across those invocations. Browser invocation required `PYTHONPATH=src` in the reviewer tool environment; normal clean-start commands still need the scheduled second-machine check.
- No model inference or paid API calls were made during this review. No credentials were read or copied.
- Existing v1 results and recorded runs were preserved. New features and new measurements belong in a separately versioned phase-two release.


## Phase two implementation log — started November 14, 03:39 ET

Branch `codex/eric-phase2`, continuing from `ffecc3f`. Newest entry last. Times are America/New_York.

### Stage 1 — budget and evidence correctness (done 04:10)

No model call was made in this stage. Spend is unchanged: an estimated **$2.922403, 91 calls**, now against a **$20** cap (development ceiling $19.50).

- **Gateway rewritten** (`src/alibi/agents/gateway.py`). Requests are counted before sending and bounded per request; input, output and money are reserved atomically; the output limit sent equals the output reserved; timeouts, lost responses, missing usage and crashed processes keep their worst case until `alibi spend --reconcile`; settlement is idempotent; the ledger migrates forward, has a floor, an absolute configurable path and fails closed when unreadable.
- **Settings hardened** (`src/alibi/config.py`): NaN, infinity, negative and out-of-range values rejected; development ceiling and demo reserve; one model for all roles; unknown prices block billed routes.
- **Checks 1.1.0** (`src/alibi/checks.py`): both local brackets required; stated source coverage honored; absent collector, host copy, flows, badge reader or heartbeats are "not assessable". Explanations, summaries, the rule baseline's report and the evidence views say "unknown" in those cases.
- **Tests:** `uv run pytest` → 206 passed (197 offline, 9 in headless Chrome). New: `tests/test_budget_gateway.py` (44 tests) and 9 coverage tests in `tests/test_m2_checks.py`.
- **Commands that do not call a model:** `uv run alibi runtime`, `uv run alibi spend`, `uv run alibi smoke --count-only`.
- **Not yet done from the continuation:** stages 2–6 (fast/specialist modes and Haiku calibration, cited questions, source-removal experiment, capture and UI integration, new case families, six-arm evaluation, export, final docs).

## Terry UI — November 14, 2026, verified local handoff

- Implemented the evidence-workbench redesign on `codex/terry-ui` (`98623d8` initial slice), preserving the existing case flow and recording. Integrated Eric's published branch through `0de232d` via `ad62bd8`; consumed his generated coverage fields without editing the generator output.
- Verified production build; 197 integrated non-browser tests; 21 browser tests plus the final case-switch regression; six development-case investigator regression gates with networking denied and zero model calls. Preserved official benchmarks, saved model outputs, scoring and truth isolation.
- Fourteen screenshots cover seven real offline states at 1280×720 and 1440×900. Native modal keyboard behavior, narrow layout, source/coverage selection, provenance, citations, refresh, reconnect, lock-before-reveal, hostile text and two resets are covered.
- Handoff, exact launch/reproduction commands, source references, verification output and a 60-second walkthrough are in `docs/terry-ui-handoff.md`. Questions, immutable source experiments, report export and captured-Linux integration still require the backend/capture contracts; their absence is shown honestly in the UI. Actual projector/second-machine verification remains external.
- No paid runtime inference, spend-ledger reset or Codex banked reset was used.

### Stage 2 — the useful AI workflow (done 04:45)

Phase-two model spend so far: about **$0.08** (ledger total $3.006 of the $20 cap). Model: `anthropic:claude-haiku-5-5`.

| Feature | Evidence | Command or route |
|---|---|---|
| Fast and specialist modes, saved with the case | `tests/test_m8_modes.py` | `POST /api/cases` with `investigation_mode`; `uv run alibi record --mode fast` |
| Haiku 5.5 calibration, both modes | `benchmarks/calibration/` (3 result sets, one a failure) | `uv run alibi calibrate --mode fast` |
| Bounded, cited questions | `tests/test_m9_questions.py` (16 tests); real answers in `docs/api-examples/question-*-live.json` | `POST /api/cases/{id}/questions` |
| Source-removal experiment | `tests/test_m10_source_experiment.py` (8 tests) | `POST /api/cases/{id}/source-experiments`, `GET …/source-experiment` |
| Report export | `tests/test_m11_export.py` | `GET /api/cases/{id}/report-export` |
| UI branch merged | `805c93b`; 21 browser tests pass on the merge | `./start.sh` |

- **Calibration result.** Fast mode: incident 3/3 effects, benign control no allegation, all citations valid, review and resume lock; 6 model calls, about 25 s and $0.007 per case. Specialist mode failed at the first-run 10,000-token output cap and passed with 24 calls / 300k input / 20k output / 240 s; 13 calls, about 60 s and $0.014 per case. Two cases per mode: an operational check, not an accuracy estimate.
- **Questions on the real model.** Four questions on the hero case: a factual one (5 claims, 4 checked), "who did it?" (account only, with the credential-not-person limit), an unsupported one (insufficient evidence) and a request for the answer key (declined; nothing to reveal). 1–3 model calls and $0.002–0.004 each.
- **API reference for the UI:** [`docs/api.md`](docs/api.md) with real payloads in `docs/api-examples/`.
- **Tests:** 231 offline + 21 browser on the merged tree.
- **Still open:** UI controls for questions, source experiments and export (Terry, against `docs/api.md`); capture import (waiting for Daniel's branch); remaining case families (in progress on `codex/eric-families`); B1/B2 arms and the new evaluation; final recording and docs.

### Stage 3 — integration (UI merged 04:38; capture waiting)

- Merged `origin/codex/terry-ui` (`805c93b`). Build and all browser tests pass on the merge; generated contracts regenerated from the models.
- First-run recordings stay usable: a test pins 22 first-run bundles and both baselines' results byte for byte, and all six recordings replay. The scenario seed namespace is kept at `1.0.0` because it is part of every random seed (a version bump was caught by the pin test and reverted).
- `codex/daniel-capture` does not exist on the remote yet, so capture import is not built. Nothing is labeled `DOCKER` or `HYBRID`.

### Stage 4 — remaining case families and the scenario designer (done 05:25)

- Records heist, Cold chain, and four bounded steps (clear shell history, backdate a file, stop log forwarding, second-host session), each with a legitimate counterpart. Built by a helper agent on `codex/eric-families`, merged (`0a838aa`) and wired into runners, tools, the scripted fixture, presets and the CLI (`e947ac3`).
- Six presets: `evasion`, `maintenance-control`, `records-heist`, `records-control`, `cold-chain`, `cold-chain-control`. Each runs through the deterministic runner and the scripted fixture to the same findings; incidents score every observable effect, controls allege nothing. Cleared shell history is recorded as unobservable and not scored.
- Real model on the new families (fast mode, Haiku 5.5): Records heist 3/3, Cold chain 1/1. Saved as recordings.
- Scenario designer (`src/alibi/agents/designer.py`): one bounded model response choosing from fixed options; a real call returned a valid design for $0.0002. Invalid output becomes a labeled default; a refusal ends the request. The adversary planner is untouched and disabled.

### Stage 5 — the evaluation (run 05:21–05:34)

- Declared in `docs/evaluation-config-v2.json` and committed (`5efc7e1`) before the run. Results: `benchmarks/paired-v2/20261114t102149z/`, report `docs/evaluation-v2.md`. All 24 cells completed; estimated cost $0.22 against a $0.72 worst case.

| System | Effects established (2 incident cases) | Benign cases with an accepted allegation | Stopped by a cap | Est. cost |
|---|---|---|---|---|
| B0 keyword recipe | 2/8 | 0/2 | – | – |
| BR deterministic checks | 8/8 | 0/2 | – | – |
| B1 one agent, generic tools | 5/8 | 0/2 | 2 of 4 | $0.054 |
| B1+ one agent with checks | 7/8 | 0/2 | 0 | $0.029 |
| B2 three agents, generic tools | 5/8 | 0/2 | 2 of 4 | $0.081 |
| ALIBI three agents with checks | 5/8 | 0/2 | 0 | $0.057 |

- No verifier feedback during investigation in any arm. No named attribution in any cell.
- A development-case check before the run found that the product's 40,000-token per-request ceiling stopped both arms without checks; the evaluation budget uses 90,000. Both checks are kept in `benchmarks/paired-v2-dev/`.
- Reading: the checks helped one agent; three agents did no better than one; the checks alone did best. One run per cell on two incident cases is not an accuracy estimate.
- `offline-v1` and `ai-pilot-v1` are untouched; `alibi bench` and `alibi pilot` now refuse to rewrite them.

### Stage 6 — shipping work so far

- Report export, question export and reveal export routes (`a01a7d8`).
- README, architecture, API reference, claims, judge answers, demo script and Devpost copy rewritten to what is built and measured.
- Redacted secret scan: no credential-like string in any tracked file or in any commit on any branch; `.env` and `.alibi/` were never committed.
- Real-model check of the source-removal experiment: `benchmarks/feature-checks/source-experiment-haiku-5-5.json`.
- Fresh-clone check (05:50): cloned the branch into an empty directory, `uv sync --frozen`, `npm ci`, build, 373 offline tests passed, `./start.sh --port 8017` served the UI; over HTTP both hero recordings replayed as "Recorded AI run", unsealed 3/3, exported, and the collector-removal comparison and an offline question behaved as documented. Default runtime there: offline, nothing spendable.
- Unscored import mode for captured evidence (`8fa26b9`, test fix `d283dda`). One commit, `8fa26b9`, was pushed with a failing label test because the commit was not gated on the test run; it was fixed in the next commit eight minutes later. The tip is green.

### Replication and summary (06:07–06:15)

- `paired-v2-rep1`, declared (`d10d31e`) after `paired-v2` ran and before its seeds were generated: the two incident kinds again on seeds 205 and 206. All 12 cells completed; estimated cost $0.11. Results `benchmarks/paired-v2-rep1/20261114t110812z/`.
- Both suites together (`docs/evaluation-summary.md`, `uv run alibi eval --summary`), four incident cases with 16 observable effects and two benign controls:

| System | Effects established | Cover-ups found | Stopped by a cap | Est. cost |
|---|---|---|---|---|
| B0 keyword recipe | 4/16 | 0/4 | – | – |
| BR deterministic checks | 16/16 | 4/4 | – | – |
| B1 one agent, generic tools | 10/16 | 3/4 | 3 of 6 | $0.080 |
| B1+ one agent with checks | 15/16 | 4/4 | 0 | $0.042 |
| B2 three agents, generic tools | 7/16 | 1/4 | 3 of 6 | $0.121 |
| ALIBI three agents with checks | 12/16 | 2/4 | 0 | $0.083 |

- No accepted false allegation on a benign control and no named person, in any cell.
- Why the three-agent system scored below one agent: in three cells its skeptic agent withdrew a correct finding that the deterministic check supported (listed in the summary). One run per cell; not an accuracy estimate.

### Visual check of the merged interface (06:11)

- Opened the merged case board in Chrome against an offline server. All nine presets and six recordings are listed with correct labels, no console errors.
- Found and fixed a regression caused by the new recordings: the interface features the first recorded model run in the list, which had become "Cold chain" shown with the Inside-job description. Recordings are now listed with the proven specialist run (Claude Opus 5.5) first and marked `presentation_default`. Verified in the browser: the featured card and the case it opens are Inside job on Opus again.
- The "Ask about this evidence" box in the interface still says questions are unavailable in this server version. The route exists now; the control needs wiring (Terry).

### Independent review of the budget code (06:20–06:40)

- A second agent read `agents/gateway.py` and `config.py` without being told what to expect. Verdict on the route in use: no path that undercounts spend, drops a reservation, charges twice or lets threads or processes jointly pass a cap. It reported five edge defects; all five are fixed and each has a regression test (`80bcb3b`, details in DECISIONS.md).
- None of them had affected recorded spend. After the fixes: the real ledger still validates ($3.4749, 508 calls, nothing reserved or unreconciled), the unbilled count check works, and one smoke call settled normally.
- Two more robustness tests for the checks: reordered or late collector delivery, and a collector clock that disagrees with the host (`40e6dac`). Both passed without a code change.
- Added: `GET /api/spend` (totals only) for the interface's status drawer, and `alibi eval --render` to regenerate a report from saved results.

### While waiting for teammate branches (06:45–07:00)

- Integration briefs with paste-ready prompts: [`docs/ui-integration-brief.md`](docs/ui-integration-brief.md) for the UI owner and the end of [`docs/importing.md`](docs/importing.md) for the capture owner (`e184eab`).
- Questions about the new case families: their claims are now compared with the family's own deterministic check. A real answer about the cold-chain case had been cut off at the per-call output limit; the limit is raised and a cut-off is reported as one (`93ad802`). Verified on the real model: 3 claims checked, $0.003.
- The cold-chain and records-heist recordings were re-recorded with one recorded answer each; both replay offline and score 1/1 and 3/3 (`d4b83f2`). In the cold-chain run the model again put the backup service account in the attribution although no account was involved in that incident; the report still says the human is not established, and the scorer treats account identification as not applicable there.
- Planted instructions in evidence, tried once on the real model (`benchmarks/feature-checks/planted-instructions-haiku-5-5.json`): 3/3 effects, nobody named, nothing leaked, and the model described the line as data. One run; not a robustness measurement.
- A background watcher wakes the session when `codex/terry-ui` moves, when `codex/daniel-capture` appears, or at 09:00 ET.

### Temperature view, UI fallback and a second review (07:00–07:50)

- **Cold chain made visible.** `GET /api/cases/{id}/evidence/sensor-streams` returns the stored readings and the independent reference logger as two series with the deterministic comparison; a withheld source is an empty series marked absent (`8a6e8e6`, 4 tests). Before this the decisive evidence of that case could only be cited, not shown.
- **Route smoke over every recording.** All six committed recordings were opened in a temporary directory and run through every route the case board calls, then accepted and unsealed: no errors.
- **UI fallback on its own branch** (`codex/eric-ui-wiring`, `04620e3`, not merged): question composer with recorded and unanswered states, witness removal with the server's comparison, report download, investigation mode, spend line, and a temperature chart for cold-chain cases. Three assertions in Terry's browser tests that pinned the old "unavailable" placeholders are changed on that branch only. 28 browser tests pass there; screenshots were checked by eye.
- **Second independent review** (information barrier, input handling, new routes): ten defects, each reproduced by the reviewer, all fixed with regression tests (`32eb417`). The three that mattered: a derived evidence view could be unsealed while its original's report was still open; a command-line call beside a running server marked the server's running work as failed; a designed case's public seed differed with and without a placed incident. Details in DECISIONS.md. Recorded answers' labels were re-derived with the stricter claim check: all 22 unchanged.
- Tests after these: **449 passed** (428 offline, 21 browser on this branch). Spend unchanged at $3.515: nothing in this stretch called a model.

### Results in the interface, a live browser check and a fresh clone (07:50–08:10)

- `GET /api/benchmark` now also returns `paired_summary`: the six systems summed over both declared suites, computed from the same result files as `docs/evaluation-summary.md`. A test pins the committed figures (4, 16, 10, 15, 7 and 12 of 16) so a result file cannot change silently (`fb8f9ff`).
- UI fallback branch: the Benchmark tab opens with that table and its limits; a derived case shows the server's refusal when someone tries to unseal it before the original is locked (`98a90a8`, 30 browser tests).
- **One real-model question through the browser** on the Haiku recording: answered in 7.3 s, labeled "Live model", 3 claims confirmed by a check, 1 cited, 1 marked as the model's interpretation, no person named; 2 model calls, est. $0.0021. The recording's own label and its five findings were unchanged. Saved as `benchmarks/feature-checks/live-question-in-browser-haiku-5-5.json`.
- **Fresh clone** of the default branch at `c0cf94e`, with no `.env`: `uv sync --frozen`, UI build, all 449 tests of that commit, `./start.sh`, recorded demo opened as "Recorded AI run". Passed.
- Spend after this stretch: $3.517326, 543 calls, nothing reserved or unreconciled.
