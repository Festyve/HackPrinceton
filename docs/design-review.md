# PR #5 integration review

Reviewed the existing Claude Design commit `d18021217ca4017976b9668d2fde84aae64dc93b` in an isolated managed worktree, based on `codex/alibi-build` at `c3dc4ed`. No ZIP was reimported and no second design implementation was created. Original checkout changes, recordings and runtime ledger were preserved.

## Findings and fixes

1. The imported CSS hid evidence-origin and playback badges; mobile CSS also hid playback independently. Existing text assertions still passed on hidden DOM content. Run provenance now appears as a wrapping group beneath the case title, visible on desktop and phone, while retaining the imported window/sidebar/material/font design. Added visibility checks that distinguish a fresh scripted fixture from its recorded replay at 1920px and 390px.
2. Scrubbing inline Activity to zero and opening a new case through the case-library dialog left the new case at zero displayed events. The embedded plan/trace now remount for each case ID, resetting local playback and discarding the previous trace. A regression opens a different real offline case through that exact dialog path and verifies its events display.
3. A comparison with no measured investigator usage drew a zero progress bar. It now says “Usage not recorded”; measured zero remains zero. The check creates a real frozen, uninvestigated worker case and verifies the card does not invent a measurement.

All original design behavior remains: advantage slider, permission/mode/context controls, planned sandbox structure, inline plan/activity, local scrub/speed controls, recent runs, Pip feed, findings, raw evidence, report review/reveal, comparisons and advanced tools.

## Observed verification

- Frozen Python dependency setup and `npm --prefix web ci` completed in the isolated worktree. TypeScript and the Vite production build passed; bundled fonts and their licenses remain local.
- Original browser suite on the supplied commit: **59 passed** in 178.09 seconds.
- The added visibility and cross-case playback regressions failed before their fixes.
- Full offline suite: **594 passed**, 59 browser tests deselected, in 354.87 seconds. No backend code changed in the review fixes.
- Expanded browser run after the fixes: **63 passed in 189.20 seconds**. See [verification](verification/design-review/), [reviewed Lab](design-preview/review-lab-1920.png) and [reviewed Investigation](design-preview/review-investigation-1920.png). GitHub reported no configured CI checks for this PR; these local results are the merge evidence.
- Manual review in the actual in-app browser at port 8000 exercised allocation and permissions, an offline deterministic worker run, playback seeking/stepping/4× speed, a cited raw collector record with its hash/line/record ID, report rejection and lock, answer reveal, a same-evidence 4→16 request comparison, report acceptance on the comparison, recent-run navigation and the new visible provenance group.

All executed runtime work was scripted or deterministic. The server ran with `RUNTIME_MODE=offline`; unavailable live controls stayed disabled. No API key was copied and no API/model budget was spent. Live inference was deliberately not exercised.

## Demo machine

After merging PR #5, update the existing demo checkout to `codex/alibi-build`, install the frozen frontend dependencies, rebuild ignored `web/dist`, and restart the ALIBI server from that checkout. The review worktree's build output is not a deployed artifact and must not substitute for the demo rebuild. Keep the existing runtime ledger and data.

Rayan's separate human usability sign-off and the existing backend/release limitations are not implied by this technical review. No remaining blocker was observed in the reviewed offline flows once the fixes passed.
