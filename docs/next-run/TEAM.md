# Team plan through submission

> **Historical handoff — superseded November 14 afternoon.** Use [../../PRODUCT.md](../../PRODUCT.md) and [the current owner instructions](../overhaul/START_HERE.md) for this continuation. This file preserves the previous plan/demo; its schedule, setup tasks and product direction must not override the current contract.

All times are **America/New_York, November 14–15, 2026**. Submission is Sunday **08:00**, a hard packet deadline. Target 06:00. In-person judging is 09:30–14:30; presentation and optional video are each at most two minutes.

## Owners

| Person | Owns | A real finished deliverable |
|---|---|---|
| Eric Chen | Runtime, backend, contracts, integrations | Safe $20 cumulative accounting; live fast/specialist workflows; cited questions; source experiment; completed evaluation; runnable release |
| Terry | Product UI | Designed evidence workbench, all states and real interactions, screenshots and passing browser checks |
| Daniel | Independent evidence and evaluation | Real Linux/collector capture, importer, benign controls and harder cases, second-machine verification |
| Rayan | Product direction and acceptance | Clear target user, feedback-driven decisions, accepted demo flow, credible claims, presentation and submission |

Eric's Claude handles coding integration overnight. Terry and Daniel each use their own agent on separate owner paths. Rayan does not become the team's administrator: he decides what the product proves and challenges the implementation.

## Rayan's substantial work

1. **Own the demo's argument.** Write a one-page acceptance memo: who uses ALIBI, why they need it, what the missing-line comparison proves, what removing a witness teaches, and what it cannot establish. Reject feature ideas that do not improve this argument.
2. **Run two product reviews.** At Saturday 09:00 and 19:00, run the app yourself without the builder narrating. Record the exact point of confusion, expected behavior and owner. Verify fixes; do not just forward screenshots and ask for “more polish.”
3. **Get concrete domain feedback.** Speak to an on-site forensics mentor, security club member or potential training user. Show the comparison and source-removal concept. Ask what evidence they would need before accepting the finding and what they would do next. Capture consented notes; turn one answer into an implemented change. This is user research, not a hunt for a random team.
4. **Own the claim review.** Compare every sentence of the pitch against a recording, result or test. The current pilot does not show a multi-agent accuracy advantage. Help the team explain why its result informed fast mode.
5. **Rehearse with interruptions.** Practice an 85–110 second walkthrough, a 20-second “where is the AI?” answer, and the offline recovery. Record a real screen demonstration rather than a generated promotional video.
6. **Submit the working project.** Devpost means the event's project page linked under “SUBMIT PROJECTS HERE” in the packet. Fill in title, description, team members/Discord handles, public repo, selected tracks and video URL. Save early, update at 06:00, then verify the submitted page and logged-out links. This is a short release step, not your main assignment.

## Schedule

| When | Eric | Terry | Daniel | Rayan |
|---|---|---|---|---|
| Now → Sat 04:00 | Preserve ledger, guard fixes, publish additive contracts | Inspect app, choose direction, first layout | Start capture/import branch | Set acceptance memo and route agents |
| Sat 04:00–09:00 | Fast mode, cited Q&A, source experiment; checkpoint | Build workbench against existing API | Capture + parser + complete/benign fixtures | Rest, then review at 09:00 |
| Sat 09:00–12:00 | Finish integration endpoints; add case families | First full working redesign | Deliver importer/fixture and hard-case manifest | Product review and target-user feedback |
| Sat 12:00–16:00 | Merge interfaces/capture, versioned evaluation builders | New API integration, keyboard/error states | Controls, independent evidence; IoT subset if available | Turn feedback into one scoped change; draft pitch |
| Sat 16:00–19:00 | Bounded live validation; preserve all results | Integrated screenshots, projector layout | Second-machine test and evidence audit | Accept release candidate; rehearse |
| Sat 19:00–Sun 00:00 | Remaining completed slices, fixes, recording | Polish and final UI checks | Verify reproduction | Final claims and presentation |
| Sun 00:00–03:30 | Feature freeze; integration fixes and release proof | Demo/video capture support | Offline fallback and link checks | Record/upload ≤2-minute video |
| Sun 03:30–06:00 | Final commit and launch instructions | Final screenshots | Verify artifacts | Submit project |
| Sun 06:00–07:15 | Ready for urgent fixes only | Ready | Logged-out verification | Confirm submission/track selections |
| Sun 08:00 | **Hard deadline** | | | |

If starting late, compress feature breadth. Do not move freeze/submission later. Never sacrifice a working end-to-end release to finish a new case card.

## Tracks and proof

Choose **Science & Discovery** as the single main track. Also enter Arlequin AI-Driven Forensics, LangChain deepagents and Amazon Practical AI. ChatOverflow is already connected; contribute useful generic engineering notes, not project secrets or leaderboard spam. Peri requires a real qualifying consultation plus supporting evidence and an implemented need. Enter only if that happens. No need to bolt on banking, property or messaging APIs.

Keep the repo creation history. Make it public after scanning history/worktree for secrets. A default branch named codex/alibi-build is fine; no rule requires main. Confirm one main track and the relevant specials on the actual submission page. The packet also excludes combining a main-track win with Best Overall.

## Coordination

Owner branches: codex/eric-phase2, codex/terry-ui, codex/daniel-capture. Each handoff contains commit, working command, proof, integration request and remaining issue. Eric merges; agents do not silently edit another owner's paths.

At 09:00 and 19:00 each person reports only: what works, a link/command proving it, and what another teammate needs to do. Keep live API usage exclusively on Eric's preserved ledger. The confirmed cap is $20 total, including the first run.
