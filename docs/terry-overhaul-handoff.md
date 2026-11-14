# Terry — integrated UI handoff

The serif graphite interface now calls the real worker-lab APIs. Lab, Investigation, Cases and Experiments are integrated; the earlier local-only Lab preview has been replaced. This is Terry's implementation handoff, **not a claim that all release gates or human acceptance have passed**.

## Integration

Owner branch: `codex/terry-overhaul`. Preserved the existing checkout and UI, merged the plan at `fc30b01`, Eric's reviewed UI wiring at `1b9216d`, worker contract `c1148c8`, structured trace `40907cd`, and Eric's source-status correction through `6caa909`. The UI checkpoint `9591107` is preserved in history and has already been incorporated on Eric's branch. Merge the owner branch for the complete frontend integration; do not reset either checkout or copy runtime credentials. No backend implementation, dependency version, recording, benchmark or spend ledger was authored or modified by this UI slice.

Actual routes used:

- `GET /api/runtime` and `/api/lab/options`: capabilities, available choices, real unit counts. Ordinary worker choices and investigator system are selected independently. Scripted/offline is the safe UI default; live options are disabled when unavailable.
- `POST /api/lab/experiments`: deliberate execution with an idempotency token, followed by attachment to the returned case. Configuration controls disable while pending. A lost response retains the token for retry. The API returns after execution/freeze; the UI shows pending state until it receives actual records, rather than inventing live worker progress.
- `GET /api/cases/{id}/lab`: identifiable workers, goals/accounts, frozen collector activity, scheduler records and clickable original records. The worker activity log is the default paired record for worker cases. The first discrepant row is initially emphasized; the full loaded comparison remains available for context.
- `GET /api/cases/{id}/lab/operator`: opened explicitly and only when the server says it is available. Every attempted action retains its actual succeeded/failed/denied outcome. Operator history stays in its own view and is never copied into questions or investigator notes. Pre-lock screens do not fetch it. No operator override was enabled here.
- `POST/GET /api/cases/{id}/lab/comparisons`: a different investigator allowance reuses the frozen snapshot; a permission change creates a new execution. Tables retain all returned outcomes and display exact allowances, usage, provenance and missing/revealed scores. A change of investigator system is disclosed as an additional changed condition.
- `GET /api/cases/{id}/trace`: recorded parent spans, actor/input/output/status/time, plan content changes and preceding results, file writes/edits/later reads, and resume counts. Recorded order is explicitly distinct from an inferred cause. No model thoughts or missing per-span cost values are fabricated.

The existing questions, immutable source-removal children, mode choice, temperature records, designer, imports, exports, review/reveal, spend and six-system historical evaluations remain reachable. Imports remain CLI-only because that is the published capability; imported saved cases are unscored and have no reveal action. Model-worker choices and scripted fault policy are separate provenance labels. The current changed-worker unit is a **scripted turn**, while an investigator unit is a **model request**, including retries and specialists. The 20-unit presets show 16/4, 10/10 and 4/16 exactly.

## What changed for the operator

A landscape margin surrounds a frosted graphite frame. The canvas prioritizes proof and report review; sources, filesystem activity and trace are contextual tools. A compact recorded plan remains visible where space permits; smaller worker screens keep its completion count in the Plan action so the discrepancy fits at 1280×720. Selecting a finding opens the nearly opaque evidence inspector. At 390px it becomes a contained drawer. The Lab's execution action sits beside the allocation controls, rather than below the fold.

Cmd/Ctrl K searches valid navigation actions and saved cases; arrows/Enter/Escape work and focus returns. Navigation never starts a paid call. Trace/operator playback is local display pacing over actual received records; stepping or changing speed cannot change a case or invoke a model. Pip's four poses follow application state and never celebrate guilt. Motion is restrained and reduced-motion/transparency fallbacks are included.

Serif typography follows Terry's explicit direction; logs and identifiers remain monospace. The landscape and Pip SVG are original. The Instagram reel was accessible in part, but its final frame was not reliably verified; the written brief governs the finished material. UITOP's investigation structure was inspected. No reference wallpaper, logo, gated source or new UI framework was imported. Rayan's sketch was not supplied.

## Reproduction and validation

Use the team's installed Git, uv and Node:

```sh
uv sync --frozen --group dev
npm --prefix web ci
npm --prefix web run build
RUNTIME_MODE=offline uv run alibi serve --port 8040
```

In another terminal:

```sh
uv run pytest tests/test_browser.py tests/test_browser_phase2.py tests/test_browser_overhaul.py tests/test_browser_lab.py
uv run pytest -m 'not browser'
uv run python tests/capture_overhaul.py --base-url http://127.0.0.1:8040
```

Observed validation:

- TypeScript/Vite build passed: 57 modules; no new frontend dependencies.
- Full browser regression: **57 passed in 179.84 seconds**. The final worker-log/default/visibility adjustment then passed **five focused browser cases**, including 1440×900, 1280×720, 390×844, the default scripted agent and the original hero review/reveal flow. Three further inspector checks verify the visible record ID and focus behavior at all three sizes.
- Full offline suite on the merged backend: **474 passed, 57 browser tests deselected, 344.20 seconds**. The final worker-contract subset also passed 21 tests.
- **30 final actual-app screenshots**, zero page horizontal overflow and zero page/console JavaScript errors. The capture also asserts the worker discrepancy sits above the question panel on laptop sizes.

The browser checks use installed Google Chrome through Playwright. The screenshot script refuses a runtime that reports live model availability. It creates clearly labeled scripted cases and actual same-evidence/new-execution comparisons, never model runs. See [verification artifacts](verification/terry-overhaul/) and [screenshots](screenshots/terry-overhaul/).

Coverage includes replay → citation → review → reveal, benign control, unscored import, question unavailability and pending/refused states, source removal and parent lock, exports, mode persistence, designer, temperature chart, historical results, reconnect/refresh, keyboard/focus, no navigation-triggered POST, allocation independence, worker proof, sealed operator history and comparison hashes. The lost-response test creates a real case, drops its response and proves retry returns the same case. The budget-stopped UI check uses an explicit failure-state fixture; it is not a paid budget exhaustion experiment. Gateway enforcement belongs to Eric's runtime tests.

## Remaining release work

Rayan's observed usability reviews and P9 sign-off are still pending. No person was treated as having approved this interface. The supplied backend reports that a distributable worker model recording and checkpoint-resume proof remain pending; old recorded AI cases still replay. Publish a worker recording through the existing replay catalog when available. UI integration does not turn the scripted fault policy into a model-chosen fault, and does not change the other P1–P10 limits documented in ACCEPTANCE.md.

This checkout made no paid runtime calls and used no runtime key. Codex usage reset naturally during the user-requested reduced-usage interval; no bank reset was consumed.
