# Start the overhaul

Repository: **https://github.com/owly1/HackPrinceton**

Plan branch: **codex/product-definition**

Canonical definition: [PRODUCT.md](../../PRODUCT.md)

This package updates requirements and handoffs. It does not claim the new worker sandbox or redesign is already implemented. Existing code and measurements are preserved.

## Send this to Eric

> Eric — the revised definition keeps your backend and restores the team's core idea: useful workers, a seeded rogue transition, an external DeepAgent investigator and measurable resource comparisons. Keep your existing $20 cumulative cap and ledger. Use your current checkout, not a fresh API-enabled clone. Terry owns the UI; Daniel is building independent cases and validating experiments.
>
> [Product](https://github.com/owly1/HackPrinceton/blob/codex/product-definition/PRODUCT.md) · [Implementation](https://github.com/owly1/HackPrinceton/blob/codex/product-definition/docs/overhaul/IMPLEMENTATION.md) · [Schedule](https://github.com/owly1/HackPrinceton/blob/codex/product-definition/docs/overhaul/TEAM.md)

In a terminal **already inside Eric's existing HackPrinceton checkout**:

~~~sh
git fetch origin
uv run alibi runtime
uv run alibi spend
claude
~~~

Check the coding session uses the intended Max login. Paste this entire prompt:

~~~text
Continue ALIBI from this existing checkout and its preserved runtime ledger. Implement the team-defined product; do not redesign its purpose.

First inspect git status and remote branches. Read the new contract directly:
git show origin/codex/product-definition:PRODUCT.md
git show origin/codex/product-definition:docs/overhaul/IMPLEMENTATION.md

Safely incorporate origin/codex/product-definition into codex/eric-overhaul, preserving local and teammate work. If a local untracked CLAUDE.md conflicts, preserve it in a dated backup outside this repo before merging; retain useful engineering notes but apply the new contract. Do not force, reset or discard edits. If the branch exists, inspect and continue it. Keep the existing .env, .alibi ledger and checkpoints; branching must not create a fresh budget.

Then read CLAUDE.md, PRODUCT.md, docs/overhaul/{STATUS,IMPLEMENTATION,EXPERIMENTS,TEAM,API_SETUP,ACCEPTANCE,DEMO}.md and current PROGRESS/DECISIONS. This is the governing direction; older plans are history. Check installed DeepAgents signatures and official docs before changing integration.

Keep the working simulator, checks, recordings, questions, source experiments, imports, exports, benchmarks and budget gateway. Build the missing worker lifecycle on top: productive model-selected work, seeded role transition, strictly bounded synthetic fault actions, executed action tape, frozen evidence and an external investigator with no truth access. Preserve refusal outcomes; never reroute a declined request to evade it. The separate component brief is docs/sandbox-session/CLAUDE.md.

Make the investigator genuinely plan, delegate focused evidence work, revise its plan on conflicts, write/read a useful case file and resume from a checkpoint. Implement explicit 80/20, 50/50 and 20/80 decision allocations with independent permission/context controls. Same-evidence investigator comparisons reuse the snapshot; permission changes create new executions. Keep fast mode and unfavorable historical results. Never label fixtures as real AI.

Publish additive contracts and real examples for Terry immediately. Terry owns web/. Reuse origin/codex/eric-ui-wiring instead of duplicating its completed routes. Daniel owns independent cases, protocol/result validation and clean-machine testing. You integrate. Use at most two bounded coding helpers on disjoint tasks if useful; no new orchestrator setup.

Every runtime call uses the existing gateway and cumulative $20 cap, with development cutoff $19.50. Read actual spend first. Only this runtime spends. Keep models/prices verified; never reset the ledger or purchase services. Run offline checks first and declare live batches before executing them.

Work through implementation gates in order and preserve runnable checkpoints. Saturday 23:00 ET is feature freeze; then finish integration, tests, recordings and release. Target final artifacts Sunday 06:00; hard deadline November 15 at 08:00 ET. A late start compresses intermediate milestones, not the deadline margin.

Finish the end-to-end implementation. Update PROGRESS, ACCEPTANCE, README, API and claims from observed artifacts. Report exact commits, commands, tests, recording IDs, budget and unmet gates. Push the owner branch. Do not claim completion without P1-P10 evidence.
~~~

## Send this to Terry

> Terry — you own the complete UI overhaul. The main reference is the finished frosted/landscape workspace in [this reel](https://www.instagram.com/reel/DfqWmHCmU9p/); Rayan will add his tablet skeleton. Use [UITOP](https://dribbble.com/shots/27869206-AI-Security-Agent-Investigation-UX-for-Evidence-and-Severity) for investigation structure. The [UI brief](https://github.com/owly1/HackPrinceton/blob/codex/product-definition/docs/overhaul/UI.md) covers screens, interactions, mascot and acceptance. Start now: the drawing doesn't block tokens, components or integration. Eric has tested UI wiring to reuse.

For a **new separate checkout**, using the team's existing Git, uv, Node and Claude Code:

~~~sh
git clone --branch codex/product-definition https://github.com/owly1/HackPrinceton.git HackPrinceton-Terry-Overhaul
cd HackPrinceton-Terry-Overhaul
git switch -c codex/terry-overhaul
uv sync --frozen
npm --prefix web ci
claude
~~~

If you have local UI edits, use that checkout instead: fetch the plan branch and let the prompt preserve/merge them. Do not replace your work with a fresh clone. No .env or API key is needed. Paste this prompt, and attach Rayan's sketch when available:

~~~text
You own ALIBI's complete interface overhaul. Read PRODUCT.md and docs/overhaul/{UI,STATUS,TEAM,ACCEPTANCE}.md, then docs/ui-integration-brief.md and docs/api.md. If absent in my existing checkout, fetch origin, read them with git show origin/codex/product-definition:<path>, and incorporate that branch safely. Preserve current UI work; no resets or force-pushes.

Inspect the running app and supplied references. Primary reference: https://www.instagram.com/reel/DfqWmHCmU9p/ . Reproduce its finished frosted graphite/landscape material, hierarchy, grouped actions, folded secondary content and command palette. Use the final design, not the generic dark dashboard at the start. The UITOP/21st/React Bits links and adaptation are in UI.md. Rayan's sketch governs the skeleton when supplied. If a reference is unavailable, use the observed written brief and state that limitation; don't pretend to have watched it.

First inspect origin/codex/eric-ui-wiring, reviewed at 1b9216d, and integrate or port its routes/tests. It already implements questions, source removal, export, mode choice, temperature records, results, designer and spend. Preserve these features and honest states. Refactor its large component as needed without inventing a competing backend.

Build Lab, Investigation and Experiments as one coherent product. Show workers doing useful work, actual action outcomes, the real investigation plan/trace, clickable evidence, report review and saved comparisons. Keep operator action history separate from investigator knowledge. Use API capability/state semantics; label development fixtures. Never invent successful actions, model thoughts, budget results or completion events.

Follow UI.md's five refinement passes. Add the small original Pip investigator mascot and restrained motion. Keep evidence readable on nearly opaque surfaces and technical details inspectable. Build a functional command palette, keyboard navigation and responsive evidence inspector. Avoid decorative metrics and a generic welcome dashboard.

Own web/, UI tests, screenshots and UI docs. Eric owns backend/contracts. Use existing routes and clearly labeled new-contract fixtures while Eric builds; record exact dependencies. Use frontend-design/webapp-testing if already available. Do not install a new framework, paid service or orchestrator. No runtime key or paid model calls in this clone.

Validate the actual app at 1440x900, 1280x720 and 390px. Exercise replay, evidence, review/reveal, questions/unavailable mode, source removal, imports, comparisons, keyboard focus, reduced motion, refresh/reconnect and errors. Retain existing browser tests; add meaningful coverage for new interactions. Build, inspect screenshots and fix defects.

Deliver integrated screens at TEAM.md checkpoints; Saturday 23:00 ET is feature freeze. Push codex/terry-overhaul with screenshots, build/test results and a concise integration note for Eric. Finish the working UI, not just a mockup, while keeping the product's technical depth.
~~~

## Daniel's agent prompt

Work on codex/daniel-overhaul from the plan branch, without an API key:

~~~text
Read PRODUCT.md and docs/overhaul/{STATUS,EXPERIMENTS,TEAM,ACCEPTANCE}.md. Own independent validation for the new worker lab. Preserve Docker captures and measurements. Create owner-scoped worker fixtures and a frozen worker-lab-v1 protocol: incident, similar approved transfer, benign collection gap and a dependent-lead case. Keep expected answers in scorer-only fixtures.

Build a result reader validating evidence-hash pairing, run IDs, conditions, provenance and inclusion of failed/refused/capped cells. Audit actual investigator inputs for truth leakage; verify tape replay and worker/account attribution. Coordinate schemas with Eric. Do not spend from this clone: Eric runs declared live batches through the preserved ledger.

Run the integrated release from a clean checkout on this machine without a key. Verify offline replay, imported capture, evidence navigation, review and export. Produce commands, observed results, complete denominators and three defensible findings for Rayan. Push isolated fixtures/tests/protocol/report changes and give Eric the integration commit. Follow TEAM.md; do not substitute a large download or promotional writing for validation.
~~~

## Which files to forward

Everything is in Git. Eric needs PRODUCT, IMPLEMENTATION, EXPERIMENTS, API_SETUP, TEAM and ACCEPTANCE. Terry needs PRODUCT, UI, the existing API/integration examples and the reel/sketch. Daniel needs PRODUCT, EXPERIMENTS and TEAM. Rayan needs PRODUCT, STATUS, TEAM, DEMO and ACCEPTANCE. The separate sandbox-session CLAUDE file accurately scopes the fault component; it is not a refusal bypass. Do not forward private chats or keys.
