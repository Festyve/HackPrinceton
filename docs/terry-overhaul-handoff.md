# Terry UI overhaul

## Runnable checkpoint — November 14, 15:41 ET

The existing checkout preserves Terry's prior interface, incorporates the product-definition branch at fc30b01, and merges Eric's tested UI wiring at 1b9216d. This checkpoint introduces a serif graphite workspace, original vector landscape and Pip mascot, Lab/Cases/Investigation/Experiments navigation, keyboard command search, responsive source inspector, recorded plan history, trace and case-file views, and comparisons of saved cases. Questions, source removal, temperature records, mode selection, designer, exports and historical evaluation remain available.

Run `npm --prefix web ci && npm --prefix web run build`, then `RUNTIME_MODE=offline uv run alibi serve`. No model key or runtime spending is needed. Python development dependencies: `uv sync --frozen --group dev`.

Validation of this checkpoint:

- `npm --prefix web run build`: TypeScript and Vite pass.
- `uv run pytest tests/test_browser.py tests/test_browser_phase2.py tests/test_browser_overhaul.py`: 49 passed, 160.47 seconds, installed Google Chrome.
- `uv run pytest -m 'not browser'`: 453 passed, 49 deselected, 336.96 seconds.
- 21 actual-app screenshots across 1440×900, 1280×720 and 390×844: no page horizontal overflow or JavaScript errors. See [screenshots](screenshots/terry-overhaul/) and [verification](verification/terry-overhaul/).

Keyboard tests verify palette filtering/arrows/Enter/Escape, no navigation-triggered POST, desktop/mobile inspector focus return and modal focus containment. A lost-response test lets the server create a case, aborts its response, retries with the same token and verifies the same case is returned. Comparison tests verify the actual hashes, missing allowance labels and no implicit reveal. Old browser assertions remain intact; source actions now explicitly open their contextual dialog.

## Design decisions and limits

Serif typography follows Terry's explicit direction. Graphite surfaces, low-detail landscape, grouped controls and folded technical content follow UI.md. The Instagram reel was accessible in part; intermediate frames and caption were observed, but the final frame was not reliably verified. The written brief governs the finished material. UITOP's investigation structure was inspected. No reference wallpaper, mascot or gated component source was copied; no new UI dependency was installed. Rayan's sketch has not been supplied.

The main canvas now prioritizes paired evidence and review. Sources, notes and technical trace are contextual tools; selecting evidence opens a near-opaque inspector instead of adding a fourth crowded column. On 390px it becomes a keyboard-contained drawer. Reduced motion and transparency fallbacks are included. Full logs and identifiers remain monospace; interface text uses local serif fonts.

At this checkpoint, Lab is explicitly a local configuration preview because the merged API has no worker lifecycle routes. It never fabricates workers, outcomes or model activity. Allocation settings do not execute anything. Eric published c1148c8 during validation; the next slice integrates that actual contract, replacing this preview. This checkpoint does not pass the new worker gates or human usability gate P9. Rayan must perform and record the actual usability review.
