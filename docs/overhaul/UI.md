# Terry: the complete interface brief

The primary visual reference is [this redesign reel](https://www.instagram.com/reel/DfqWmHCmU9p/). Rayan's forthcoming tablet sketch controls the screen skeleton. The final reel uses frosted graphite surfaces over a muted landscape, disciplined type, grouped actions, folded secondary content and command navigation. Follow that finished treatment and its sequence of improvements. Keep ALIBI's own data, layout needs and identity.

The investigation structure comes from [UITOP](https://dribbble.com/shots/27869206-AI-Security-Agent-Investigation-UX-for-Evidence-and-Severity). [Agent Trace](https://21st.dev/@n1m4mz/components/agent-trace), [task list](https://21st.dev/@kvnkld/components/task-list) and [animated list](https://reactbits.dev/components/animated-list) provide interaction references. See [source notes](SOURCES.md) for access/license limitations. Do not claim imported source when you recreated the behavior.

## First protect the working features

Inspect and integrate `origin/codex/eric-ui-wiring` (reviewed at `1b9216d`) into your own branch. It contains tested wiring absent from the default UI. Use [the integration brief](../ui-integration-brief.md), [API reference](../api.md) and real `docs/api-examples/` payloads. Preserve its browser coverage while decomposing the large phase-two component into understandable view components. This is a visual/workflow overhaul, not a backend rewrite.

Own `web/`, UI tests, screenshots and UI-specific documentation. Eric owns API contracts. Do not change response semantics or replace real routes with mock successes. Fixtures may support development with a visible fixture label; production controls use capabilities and real responses.

## The main screen

At 1440×900, use a centered application frame with a slim landscape margin, roughly 196 px navigation, a flexible investigation canvas and an optional 320–360 px evidence inspector. Let the frame fill smaller laptop screens. Avoid nested horizontal scrolling.

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ ALIBI  ·  Research lab        Search cases/actions ⌘K    Recorded / Live  │
├────────────┬─────────────────────────────────────────────────────────────┤
│ Lab        │ Research export investigation       seed · run · state     │
│ Cases      │ [80/20] [50/50] [20/80]   Advanced       Run / Replay       │
│ Experiments├───────────────────────────────┬─────────────────────────────┤
│            │ Sandbox / Investigation       │ Evidence inspector          │
│            │ worker jobs OR investigation  │ exact source + record       │
│            │ plan + timeline               │ comparison + citation       │
│            │                               │                             │
│            ├───────────────────────────────┴─────────────────────────────┤
│ mascot     │ Findings / Questions / Case file / Trace                    │
│ Help       │ Next action: Review report → Lock → Reveal / Export         │
└────────────┴─────────────────────────────────────────────────────────────┘
```

This is the default skeleton until Rayan supplies his sketch. The inspector opens on demand so the canvas does not become four cramped columns. Use the sketch without dropping required states or evidence access. Do not wait idle for the drawing: build tokens, components, wiring and the responsive shell first.

**Lab:** configure workers and permissions, see useful work, replay action outcomes. Clearly separate an operator demonstration view from what the investigator is allowed to see. Pre-lock investigator screens never show true rogue labels or hidden objective changes. An operator action recap in a recording must say “operator view,” not pretend to be the investigator's conclusion.

**Investigation:** header identifies the case and current mode; compact task list shows the current plan and revision; chronological evidence leads fill the center. Selecting a finding opens its exact record/side-by-side comparison. The trace sits one click away; a technical judge can expand a real tool call and see input summary, output, actor, cost and status.

**Experiments:** compare two saved runs with the changed variable stated in one sentence. Show exact evidence match or “different execution,” budget allowed/used, complete/stopped state, findings/false allegations/unresolved items and real measured costs. Use a small table or aligned dot/bar chart with accessible labels. Never invent a success percentage or auto-generate a rising line.

**Cases:** retain original case families, captures and replays. Clearly identify unscored imports. Questions, source removal, temperature records, environment designer and export remain reachable as contextual tools or advanced actions, without crowding the hero screen.

## Reproduce the reel's refinement passes

1. **Type and hierarchy.** Choose one locally available or bundled interface sans; use monospace only for IDs/logs. Suggested scale 12 metadata, 14 controls, 15–16 body, 24 heading, 32 only for the screen title. Align baselines and labels. Remove generic welcome text, redundant headings, decorative score cards and unexplained badges.
2. **One material system.** Muted original/licensed desert or landscape background, low detail and low saturation. Frosted graphite outer shell; warm neutral borders, restrained radius (about 12–16 px for panels, 8 px for controls), one shadow family. Keep evidence/log/text panels nearly opaque charcoal so wallpaper cannot reduce readability. Use a solid fallback for reduced transparency/unsupported blur. Do not scrape the reference's wallpaper or logos.
3. **Group by task.** One prominent next action in the header or active panel. Fold low-priority metadata and advanced knobs. Keep configuration near Run, proof near findings, review/reveal near the locked report. Consistent selected/hover/focus states; no more than one action-colored primary button per task area.
4. **Interactions with purpose.** 120–180 ms opacity/translation for list insertions and panel transitions; no perpetual glow, bouncing text or theatrically slow typing. New real events can highlight briefly. Respect reduced motion. Auto-scroll only while the user is already following the live tail.
5. **Command palette.** ⌘K/Ctrl+K opens case/action search, keyboard arrows select, Enter activates, Escape restores focus. Expose only currently valid actions. Starting a paid run still uses its normal labeled action flow; search navigation must not trigger it accidentally.

Starting colors: deep graphite `#20252B`, evidence `#171C21`, warm foreground `#F1EEE8`, muted text `#B9B6AE`, subtle border `#FFFFFF1F`, restrained amber `#D9AE73` for selected details. Use semantic green/red/amber with text and icons. These are implementation suggestions, not values sampled from the video. Validate contrast; dim metadata must remain legible on a projector. Avoid purple neon, rainbow gradients and glass on every small item.

## Original mascot

Create **Pip**, a small investigator character with a magnifying-glass silhouette and a warm amber accent. Original SVG/vector art is sufficient; no new paid asset service. Four simple states: ready, inspecting, waiting for review, finished. State follows real application events; it never celebrates a suspect being guilty. Keep it about 28–40 px in navigation and larger only in a useful empty state. It can point to “Open the source” or “Review needed,” but never occupy evidence space or play continuous animation. Accessible label; decorative parts hidden from screen readers.

## Interaction requirements

- A finding opens source plus record ID, timestamp, origin, coverage and exact quoted bytes/lines. Keyboard back returns to the same finding.
- Plan revisions show what changed and the supporting evidence reference. Completed tasks are real events; elapsed time alone cannot complete one.
- Trace/replay shows real nested spans and preserves causal order. Playback controls and speed never alter the saved result. Label display time versus execution time where they differ.
- Permission and resource settings show units and effects. Changing permissions creates a new execution; changing investigator budget can rerun the same snapshot. No “AI power” marketing slider.
- No auto-paid call on refresh, navigation or opening a case. Disable duplicate submission while pending, retain the request token, handle cancellation and provider/budget failures with a useful explanation.
- Questions retain checked/cited/interpretation/contradicted/unsupported distinctions. With no configured model, show unavailable, not a canned answer under a live badge.
- Source removal opens an immutable child case and its comparison; inability to establish a claim is not disproof. Preserve the parent-lock requirement for reveal.
- Imported cases keep `scored=false` and no Unseal button. Report export is available after lock. Old recordings still replay.

## Acceptance and deliverables

Build and inspect the actual app, not just a component preview. Check 1440×900 and 1280×720 for judging; 390 px must remain usable without page overflow, with the inspector becoming a drawer. Test keyboard navigation, focus return, reduced motion, loading/error/empty/cancelled states, unavailable AI and reconnect/refresh during investigation/review. No API key in your clone.

Browser coverage must include a full replay → evidence → review → reveal; benign control; question availability; source removal; unscored import; saved comparison; model/fixture labels; and a missing/budget-stopped worker run once Eric supplies that contract. Use accessible selectors, not fragile pixel positions.

Provide screenshots of Lab, Investigation with evidence open, Experiments, review and mobile; a short before/after explanation grounded in usability; test/build commands; commit; and any backend dependency. Rayan should be able to discover the main flow without narration in under one minute. Keep a working integrated screen at each checkpoint; do not deliver a beautiful disconnected mockup at midnight.
