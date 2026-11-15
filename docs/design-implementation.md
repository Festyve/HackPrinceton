# Claude Design implementation

The ZIP export's `ALIBI.dc.html` is translated into the existing React application. `ALIBI Screens.dc.html` is its screen catalogue, not a replacement application. The custom `support.js` renderer is not a runtime dependency.

## What changed

- Landscape background, translucent window, sidebar, serif typography and light primary actions follow the export. Fonts are bundled locally with their OFL licenses; the UI requires no font CDN.
- Lab setup has the advantage slider, permission/mode rules and a sandbox preview showing actual worker roles and planned paths.
- Investigations show recorded plan and activity side by side, findings underneath, and an evidence inspector. Existing questions, source removal, case files, exports, benchmarks and temperature experiments remain accessible.
- Recent runs open saved cases. Pip opens a feed of actual tool events. Replay controls support scrubbing and four display speeds without rerunning a case.
- Comparison cards use saved run measurements and keep the existing detailed comparison table.

## Deliberate differences from the static mockup

The running application cannot truthfully copy the mockup's invented case values. Supported allocations remain 16/4, 10/10 and 4/16. Real worker IDs, permissions, citations and scores come from the backend. The operator tape remains sealed until report lock. Review accepts or rejects the whole report because the backend does not support per-finding verdicts. No fabricated risk score or simulated live model activity is added. Advanced features remain available even where the mockup omitted them.

The export is the visual reference; this is a functional adaptation, not a claim of pixel identity across every state. Worker recordings and reveal retain the existing evidence-rich components in the updated shell.

## Run locally

```sh
uv sync --frozen
npm --prefix web ci
npm --prefix web run build
uv run alibi serve --port 8000
```

Open http://127.0.0.1:8000. Offline fixtures work without an API key. Existing server configuration governs live calls and the configured $20 cap; this UI change does not change either.

## Verification

```sh
npm --prefix web run build
PYTHONPATH=src uv run pytest -m 'not browser'
PYTHONPATH=src uv run pytest tests/test_browser.py tests/test_browser_overhaul.py tests/test_browser_lab.py tests/test_browser_phase2.py tests/test_browser_design.py
```

Browser tests require Google Chrome. The design tests exercise allocation changes, local playback, recent-run navigation, and overflow at desktop and phone widths. Older tests navigate to Cases explicitly and scroll to evidence/review because plan and activity now appear first. Their evidence, report-lock, reveal, and safety assertions are retained.

Local verification: production build and TypeScript passed; 594 non-browser tests passed. Browser coverage includes 57 existing cases plus 2 design checks, with changed-layout checks rerun after updating navigation, scroll, and case-ID normalization. Manual verification covered offline sandbox creation, accepting the report and revealing the measured answer. No paid inference was used.

Screenshots: [Lab](design-preview/design-lab-1920.png) · [Investigation](design-preview/design-investigation-1920.png).

## Terry: integrate, do not reimplement

The work is on `codex/design-implementation` in `owly1/HackPrinceton`. It is already committed; no ZIP import or second implementation is needed.

1. Preserve any local changes on your own branch; never reset or overwrite them.
2. Fetch origin and inspect the design branch against `origin/codex/alibi-build`.
3. Run the build and browser checks above. Open Lab, run an offline case, inspect a citation, lock and reveal, open Experiments, and verify keyboard/dialog behavior.
4. Merge the design PR into `codex/alibi-build` once checks pass. If the base moved, resolve conflicts preserving both backend functionality and the imported design. Do not copy files over newer work or duplicate the commit.
5. Pull the merged branch on the demo machine, rebuild `web/dist`, and restart the server. Git does not distribute the ignored build output.
