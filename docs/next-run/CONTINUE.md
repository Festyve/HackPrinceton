# ALIBI: second-run implementation

This is an incremental continuation, not a rebuild. Start from the current working branch, preserve completed work and the original PLAN.md architecture, and use this document for phase-two priorities. Read REVIEW.md once. Commands and routes below marked **target** must be implemented before documentation advertises them.

**Deadline:** Sunday November 15, 2026, 08:00 America/New_York. Feature freeze: Sunday 00:00. Submission target: 06:00. First checkpoint: Saturday 09:00. If starting later, keep the absolute freeze and shorten scope in the order below. Never claim unfinished work is finished.

**Budget:** $20 cumulative (raised from $5 by Eric on November 14), including all earlier usage. No new purchase, paid overage, ledger reset, refusal bypass, or secret in chat. Follow API_SETUP.md. No paid calls before stage 1 passes.

## Ownership and working method

Eric's Claude owns backend, contracts, integration and final checks. Terry owns web/ and UI browser tests. Daniel owns capture tooling, import adapters, independent controls and their tests. Rayan owns product acceptance and presentation. Read CONTRACTS.md and TEAM.md before touching shared files.

Stay in Eric's existing checkout for live calls so its private ledger remains authoritative. Use separate branches/worktrees for coding, but never start a second independently billed runtime. Preserve untracked original planning files. Commit and push small completed changes; no force push, history rewrite, or silent overwrite of a teammate's branch.

Use the installed DeepAgents version and official docs MCPs when changing its API. Avoid framework upgrades. One capable coding lead is enough; native coding subagents can handle isolated tests or modules when useful. Do not add an orchestration framework. Coding-model choice is separate from ALIBI's runtime model and API budget.

## 1. Budget and evidence correctness first — first 60–90 minutes

Files: config.py, agents/gateway.py, checks.py, explain.py; focused tests.

- Reject non-finite settings, negative/zero invalid limits and unknown prices.
- Count the actual serialized provider payload, including system prompt, tool schemas and messages. Enforce a per-request input ceiling. The current 40,000-token number must become an enforced bound, not an assumption. Use provider counting with conservative headroom; if counting fails, do not send an unbudgeted request.
- Atomically reserve input/output tokens and money across parallel specialists. Clamp the provider output ceiling to the tokens actually reserved. Respect per-run and cumulative caps.
- Retain worst-case cost for timeouts, absent usage and crashed processes until explicitly reconciled. An old reservation must not vanish and recreate spending capacity. Settlement must be idempotent.
- Preserve the existing ledger when changing models or branches. A configurable absolute ledger path can support worktrees; migration must carry existing spend forward. Historical usage remains priced as originally recorded.
- Add a development ceiling of $19.50 cumulative beneath the absolute $20 cap. Only an explicit operator action may use the final demo reserve. Unknown billing outcomes consume headroom.
- Do not mix models under one price pair. Keep roles homogeneous for this run.
- Correct missing-prefix/late-start interpretation. Honor source coverage; require both cited brackets before saying “before and after.” Unknown coverage must not become “no anomaly.”

Acceptance: offline tests exercise oversized inputs, near-output-cap calls, parallel reservations, timeouts with unknown usage, missing usage, stale/crashed reservations, duplicate settlement, NaN/infinity, ledger reuse, missing local prefix and missing collector. Existing tests pass. Update public budget wording to describe conservative accounting, not guaranteed provider billing.

## 2. Finish the useful AI workflow — next 2–3 hours

### Fast and specialist investigations

Expose the existing single-agent builder through ordinary case creation. Keep the full DeepAgents graph as Specialist review. Fast is the default for a fresh live investigation; the proven recorded specialist run remains the presentation default. Persist architecture/model/mode with the case so refresh and resume cannot switch it. Do not create unused specialist models in fast mode.

Keep the original ALIBI benchmark arm unchanged. Adaptive delegation, if added, is a separately named configuration, not a new meaning for old results.

Calibrate the inexpensive model exactly as API_SETUP.md describes, using development cases. Record success/failure and cost. Promote only after a full report, benign abstention, citations and review/resume work. Preserve the existing Opus replay.

### Open-ended questions

Implement CONTRACTS.md's question endpoint with a dedicated read-only Q&A tool set. Accept bounded question text; retrieve only this case's evidence and public report; allow at most three model calls and a short answer. Use the same global gateway.

Return an answer with individual factual claims and their evidence IDs, limitations and follow-up evidence requests. Validate every ID against this bundle. A resolvable ID is not proof of entailment: check deterministic claims with registered predicates and label other interpretation as interpretation. If support is insufficient, say so. Do not invent a reference or substitute a canned answer while labeling it AI.

No report tools, shell, URL fetches, arbitrary paths, SQL or sealed truth. Post-reveal Q&A still receives only investigator-visible evidence, never truth or audience events. Idempotent client tokens prevent double charging on a retried request. Questions do not mutate the locked report. Persist answers; export them separately from it.

Test: normal factual question; “who did it?”; unsupported question; malicious text inside evidence; request for the answer key; post-reveal leakage; cross-case IDs; retry; exhausted allowance. Keep canned explanations as explicitly labeled offline help. Saved model answers replay as recorded answers.

### Evidence-removal experiment

Implement an immutable child evidence bundle with one selected witness source excluded. Default demonstration: collector removed. The parent bundle, original report, hashes and answer key remain untouched. Remove the source from raw access, event search, checks, manifest coverage and model context—not just the screen. Start with fresh agent state; do not reuse a parent's notes, answer cache, findings or hidden source records.

A deterministic comparison can immediately show which original claims retain support, lose it or become unresolved. A fresh model investigation is separate and budgeted. Keep the withheld-source record in operator metadata; do not tell the investigator what incident it was supposed to find.

Preserve executed ground truth for research scoring, but recompute observability against the child evidence. Display lost coverage and all original effects as well as conditional recall; a smaller denominator must not look like improved detection. “Unable to establish” must be distinct from “did not happen.”

Acceptance: removing collector removes the deletion proof when no remaining source supports it; removing badge weakens presence interpretation, not transfer evidence; no-source data gives an insufficient-evidence state; parent bytes unchanged; withheld IDs cannot be fetched, cited, reconstructed from cache or found in any agent response.

## 3. Integrate Daniel's evidence and Terry's UI

Publish the additive contracts first. Integrate Daniel's capture/import module without moving his files underneath him. A real process must generate each artifact labeled DOCKER. Containerizing a simulated text generator is not independent Linux validation. HYBRID must expose each source's origin. Import raw bytes without rewriting them to match the parser.

Keep existing recorded runs usable when adding new scenario versions. Do not regenerate v1 recordings under changed simulation behavior. Version-dispatch replay generation or preserve their exact frozen bundles with verified hashes.

Terry's UI must use real endpoints and saved state. Never replace functioning backend interactions with mock data to finish the redesign. Integrate questions, source experiments, capture origin and fast/specialist controls only after their contracts pass.

## 4. Finish the remaining case families

Implement through the existing simulator/normalizer/check/verifier/scorer pipeline; avoid a parallel application.

**Records heist:** records-service access/export, staging and transfer, with an approved-export control. Make source relationships materially different from Inside job; changing the title is not another case.

**Cold chain:** timestamped synthetic temperature readings, sequence counters, an independent reference stream and operational maintenance policy. A displayed-normal/local stream can disagree with the independent capture. Include a real excursion with no falsification and legitimate clock/maintenance conditions. Report the observable discrepancy; do not infer intent from temperature alone. Add claim/effect types, citation predicates and unobservable outcomes before scoring it.

**Remaining bounded simulation steps:** clear synthetic shell history; change simulated file metadata timestamps; stop simulated forwarding; create a second-host simulated session. Each step needs validation, explicit preconditions, recorded success/failure, affected artifacts, independent witnesses where applicable and a benign control. Update scoring only for an observable effect. No shell is granted to the model; no real attack commands or network movement.

### Scenario design with AI

The original planner received a provider refusal. Keep that route disabled; do not rephrase the refused attack-planning task, enable refusal fallback, or switch models to get around it.

A separate, genuinely different task is useful: **AI scenario designer** chooses a benign environment specification—background volume, legitimate maintenance, collection availability and timing—from validated enums/ranges. It cannot output incident steps, commands, destinations, attack strategy or code. Trusted pre-authored incident fixtures remain separate. This may improve fixture variety without an “AI attacker” claim.

Implement schema validation, reproducible seed, provenance and a human preview. Use one bounded design response, then offline execution. Invalid output uses labeled defaults; a refusal ends the request. Never treat this feature as proof that the original adversary became AI.

## 5. Complete the evaluation

Keep offline-v1 and ai-pilot-v1 immutable. Add versioned configuration and result paths. Daniel supplies unseen control cases; do not tune after observing their outcomes and retain the same “held-out” label.

Implement six runnable systems:

| Arm | Access |
|---|---|
| B0 | Existing fixed keyword recipe |
| BR | Existing deterministic checks |
| B1 | Single model, generic evidence tools |
| B1+ | Single model, generic tools + checks |
| B2 | Full specialist architecture, generic tools only |
| ALIBI | Full specialist architecture + checks |

For B1/B2, remove specialized tools from every role and use prompts that do not ask for them. Generic tools must support a fair investigation of collector, local and policy data. Avoid an artificial handicap like hiding ordinary log fields.

**No verifier oracle:** during the new evaluation, submit_finding acknowledges schema/reference validity only. Apply rule support once the report locks, identically for all arms. The interactive product may retain feedback, but declare this evaluation difference. Do not feed deterministic candidates or scripted fixture answers to a no-check model.

Predeclare one difficult incident, a cover-up, a legitimate rotation/partial capture, and an approved transfer or ambiguous-session control; four AI arms × four cases = 16 system-runs, plus B0/BR offline. Set the cap only after estimated worst-case cost fits API_SETUP.md. If it cannot, reduce the declared matrix before execution, not after seeing results. Keep errors, refusals, censored and unrun cells. Report per-case outcomes, valid citations, unsupported allegations, false named attribution, cost, latency and sample size.

Do not chase a multi-agent win. Equal or worse performance remains a result. A small pilot demonstrates functionality; it does not establish generalization or statistical significance. Preserve the old results alongside new ones.

## 6. Finish and ship

- Build report export with evidence citations, raw hashes, assumptions, model/playback labels and locked-report hash. Exclude sealed truth unless the user explicitly exports the revealed answer separately.
- Import IoT-CAD only through Daniel's provenance workflow. Do not manufacture external-data validation if access is unavailable.
- Clean install on a second machine; actual projector check; offline recorded hero and benign control; refresh during review; lock/reveal/reset twice; citation opening; disconnected network; no external assets; no console errors.
- Keep a recording of the final model workflow. Never call a fixture or replay “live AI.”
- Rewrite README, demo script, Devpost draft, claims and Q&A to the final implemented state. Short, factual prose. Preserve measured numbers and their limits. New claims require artifacts.
- Run a redacted secret scan on history and worktree before the owner makes the repo public. Keep private keys, local traces and planning transcripts out. A public default branch named codex/alibi-build is acceptable.
- Record a maximum-two-minute video and verify its link; public repo and submission visible in a logged-out browser.

At each checkpoint update PROGRESS.md with completed feature → evidence/test → exact command → remaining issue. At the top of the final handoff list branch/commit, launch command, demo selection, totals spent/reserved, model used, tests, current recording, and owner actions. Do not print secrets.

## Completion and deadline behavior

Implement stages 1–3 first, then distinct cases and evaluations, then remaining simulator breadth. Work continuously on independent tasks when a teammate is unavailable. Do not spend hours waiting for a credential or an inaccessible dataset.

At 00:00 Sunday freeze new features and merge only completed slices. Continue fixes and release verification. At 06:00 submit the working release. An external dependency or genuinely failed feature must be reported accurately; it must not be disguised as complete. Preserve working functionality while pursuing the remaining assigned work.
