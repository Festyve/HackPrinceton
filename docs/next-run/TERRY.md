# Terry: redesign the evidence workbench

You own the entire frontend and the way the investigation is presented. This is substantial product work, not a CSS cleanup. Start now; work against existing APIs while Eric adds the interfaces in CONTRACTS.md.

## Direction

**An investigator's desk, not a generic AI dashboard.** Use a warm paper workspace with dark ink, restrained navy controls, and rust for an actual discrepancy. Typography and the evidence comparison should carry the identity. No gradient hero, glowing cards, chatbot landing page, giant decorative metrics, emoji statuses or fake terminal animation.

Spend at most 20 minutes collecting references. Look at a serious editorial document, a code diff, and a well-designed investigation/data table. Choose useful layout patterns; do not copy a brand or spend hours hunting screenshots. Save three references and a short explanation in docs/ui-direction.md, then build.

Suggested tokens: background #F4F2EC; surface #FFFFFF; ink #1D252B; muted #59636B; border #D9DCD8; accent #264D68; discrepancy #A7352E; unresolved #846329. These are starting values; check contrast. Use a locally available system sans for UI, a restrained serif for the case title if it helps, and monospace only for evidence. No runtime CDN fonts.

## Layout at 1440×900; still works at 1280×720

```
ALIBI  /  Case 014                         Recorded AI · Simulated evidence   [Details]
The missing login                         [Case library]  [Reset]
Inside job       Investigation → Review → Reveal
┌──────────────────┬────────────────────────────────────┬─────────────────────┐
│ Sources          │ EVIDENCE COMPARISON                │ FINDINGS            │
│ small topology   │ Local host       Collector copy    │ 01 Missing login    │
│                  │ matching row     matching row       │ 02 Transfer         │
│ Selected source  │ [missing entry]  [surviving entry] │ 03 Staging          │
│ Coverage         │ matching row     matching row       │                     │
│                  │ selected event timeline             │ Account used        │
│ [Test without    │ raw record opens in a drawer        │ Person not proven   │
│  this source]    │                                    │ [Review report]     │
└──────────────────┴────────────────────────────────────┴─────────────────────┘
Ask about this evidence…                                        [Ask]
```

Rough proportions: 200px source rail, flexible central evidence area, 310px findings panel; at 1280 use 170px and 280px rails. The discrepancy and primary action must be visible without scrolling. Raw logs should not wrap into ten narrow lines. Allow local horizontal scrolling in the raw drawer while preserving page layout.

## What to build

1. **Case library.** One clear recorded-demo action, fresh investigation option, concise case description. Show provenance in plain language: Recorded AI / Live AI / Scripted fixture; Simulated / Captured Linux / Mixed. Do not display a global “AI blocked” alarm when an offline replay works.
2. **Evidence workbench.** Side-by-side local and collector records; selected mismatch aligned across both columns; before/after context; time and source visible. Color plus a label, never color alone. Click opens exact raw line and provenance.
3. **Findings.** Compact title, one-sentence observation, status and citations. Expand for rationale, benign alternatives, verifier details and uncertainty. Hide uncalibrated decimal confidence; no fake accuracy meter.
4. **Sources.** Small five-node topology tied to actual case hosts, source availability and selected evidence. Animate only a real event. “Test without collector” creates a child experiment; it must not fake a changed conclusion in React.
5. **Questions.** Compact composer and recent answers, not the whole product becoming chat. Clickable claim citations and visible abstention. Disabled with a useful reason when live inference is unavailable; recorded answers say recorded.
6. **Review.** Human-facing state names. “Awaiting review,” not awaiting_review. Show what locks, offer Accept/Reject, then enable Unseal. Keep the report visible during review.
7. **Reveal.** A readable comparison of what happened and what the report caught/missed. Show unknown/unobservable separately. Three leading facts maximum; detailed precision/token/cost tables are expandable.
8. **Benchmark.** Simple comparative table with sample sizes, origin, model and source links. Preserve equal-accuracy pilot result. No invented progress bars or celebratory 100% card.
9. **Export.** Download a clean evidence report when Eric's endpoint is ready. Until then, omit the action rather than shipping a dead button.
10. **Runtime details.** Model, replay provenance, spend status, seed, hashes, pipeline and tool trace live in a Details drawer. Keep relevant origin/inference badges visible.

## States to design

Empty library; generating; investigating with actual activity; awaiting review; locked; revealed; cancelled; provider/budget error; disconnected; replay; no incident; incomplete evidence; unsupported question; source excluded; unavailable optional feature. Preserve data on refresh and reconnect.

Use normal keyboard focus, labeled controls, Esc-to-close, focus return and focus trapping in modals. Respect reduced motion. Use 150–220ms transitions where helpful. No animation that delays the presentation. Readable at 1280×720, 1440×900, laptop scaling and narrow width. Mobile can stack; projector readability comes first.

## Boundaries and proof

Own web/ and UI browser assertions. Do not change backend logic, scoring, recorded model outputs, inference labels or the answer-key boundary. Do not hand-edit generated/contracts.ts. Preserve existing behavior test IDs where possible.

The existing Playwright suite is a starting point. Update brittle text expectations only for intentional wording changes; preserve checks for citations, refresh, hostile HTML as text, lock-before-reveal, replay labels, reset twice and no console errors. Add coverage for the new source and question states when integrated.

Deliver: branch/commit; six screenshots (library, investigation, mismatch, review, reveal, benign/insufficient case); build output; browser-test output; a 60-second walkthrough; open integration issues. Run locally with networking disabled after dependencies are installed. No mock data in the production UI.

## Paste into Terry's agent

```text
Implement the frontend redesign in docs/next-run/TERRY.md in this existing ALIBI repository. Read CONTRACTS.md and the current web code/API before editing. Own web/ and relevant browser/UI tests only; Eric owns backend and generated contracts, Daniel owns capture. Create a separate branch, codex/terry-ui, without discarding local work. Preserve functioning case flow, exact provenance, citations, truth isolation, review/reveal and offline replay.

Use frontend-design if installed; Playwright is already a project dependency. Spend at most 20 minutes on references, then implement the complete evidence-workbench direction. Use the existing backend now; integrate new capabilities when available and use clearly isolated development fixtures only. No fake live AI, fabricated findings, dead buttons or mocked production APIs.

Run the build and browser behavior checks, inspect screenshots at 1280x720 and 1440x900, refine hierarchy and spacing, and deliver the branch/commit, screenshots and handoff. Work autonomously through completion. Use no paid runtime API calls. Feature freeze is Sunday Nov 15 at 00:00 America/New_York; hand off the first working redesign Saturday by 12:00 and the integrated version by 19:00.
```

Optional one-time Claude Code install: `/plugin install frontend-design@claude-plugins-official`. Do not let plugin setup delay work; existing Playwright can verify the UI.
