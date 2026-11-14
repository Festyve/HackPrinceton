# Review of the first build

Reviewed against commit `874cc5f` on `codex/alibi-build`, November 14, 2026. This continues the original ALIBI plan. Keep its simulator, evidence contracts, bounded steps, verifier, score, and DeepAgents integration.

## The important correction

The investigator **already uses real AI**. The committed hero recording and eight pilot reports contain real model usage. The missing AI component is the adversary planner, whose one real request was refused. Offline fixtures and recorded playback are correctly distinguished from live inference.

The project is technically stronger than its presentation. It is also narrower than the original plan: one crime card, no captured Linux evidence, no open-ended Q&A, and no source-removal experiment. Finish those useful capabilities rather than replace the foundation.

## Keep

Seeded cases; frozen raw evidence; exact-line provenance; a sealed answer key; separate audience and investigator views; read-only DuckDB; typed tools; no shell or arbitrary SQL; actual DeepAgents planning, specialists, notes and review; benign controls; shared scoring; raw proposal precision; honest replay labels.

## Findings that change the next run

| Priority | Finding and code | Required correction |
|---|---|---|
| Before live calls | `agents/gateway.py` reserves against an assumed 40,000 input tokens, without counting/enforcing the outgoing payload. Output reservation shrinks near the cumulative limit without shrinking the actual provider ceiling. | Count the provider payload including tools, bound input, reserve output atomically, and send the same output limit that was reserved. Test near-cap and concurrent calls. |
| Before live calls | A timeout commits zero tokens; missing usage also becomes zero. Global reservations disappear after 900 seconds. A request may have been billed before losing its response. | Retain uncertain cost conservatively for reconciliation. Age alone must not free money. Idempotent settlement and crash tests. |
| Before live calls | `_f()` accepts non-finite floats; cap validation is incomplete. One price pair serves every model. | Reject NaN, infinity, invalid/negative caps and prices. Use one model/rate for every role until accounting is explicitly per model. Keep historical spend on model changes. |
| Before evaluation | B1/B2 have no builders. `PILOT_SYSTEMS` has only B1+ and ALIBI. `submit_finding` exposes verifier feedback during investigation. | Implement missing tools/prompts. A “without checks” arm must not recover rule-check answers through submission feedback: defer rule verification until report lock, consistently across evaluation arms. |
| Before evaluation | `pilot` writes fixed `ai-pilot-v1` paths and can replace earlier reports. | Preserve v1; new config, immutable run directories, complete failure rows, new result version. Old pilot cases are regression cases, not new holdouts. |
| Product | The lead delegates twice on every case. The single agent matched accuracy and was about three times faster. | Add Fast investigation and Specialist review. Reuse the existing single-agent builder. Keep the measured full architecture; distinguish any new adaptive policy from the original arm. |
| Product | Three canned explanations are the only question interface. | Bounded free-text Q&A over case evidence, validated citations, abstention, persisted answers, honest offline state; cannot edit locked reports or see truth after reveal. |
| Scientific depth | Simulator and checks share assumptions. | Independent Linux capture and hard controls from Daniel; source-removal experiment from Eric. Test evidence dependence, not just more seeds. |
| Coverage | `reconcile_file` requires a later local record, not a preceding one. Some explanations claim both brackets. Source-specific partial-capture coverage is not enforced. | Late-start/missing-prefix controls; source coverage; only claim two brackets when both exist. Missing coverage is unknown, not a clean bill or deletion allegation. |
| UI | Seven header status elements, three dense columns, wrapped tiny logs, and an offline warning beside a valid replay. | Terry owns an evidence workbench: missing entry, surviving copy, next action. Runtime administration and metrics move to a drawer. |
| Submission | Repository is private. | Owner makes it public after a redacted history/worktree secret scan. Creation time is valid. A branch named `main` is not required by the packet. |

Budget findings do not establish that prior runs exceeded the cap. The previous estimate was about $2.92 used / $2.08 remaining; inspect the preserved ledger and Console before any new call.

## Every unfinished item has an owner

| Gap | Owner | Finish |
|---|---|---|
| Budget edges | Eric | Regression-tested gateway before more live calls |
| Real investigator in ordinary UI | Eric + Terry | Fast/specialist modes, correct labels, successful recording of promoted modes |
| AI adversary | Eric | Keep refused route disabled; separate benign scenario designer for noise, maintenance, coverage and timing. Incident steps remain scripted. No refusal evasion. |
| Free-text questions | Eric + Terry | Real endpoint, read-only tools, validated citations, abstention |
| Source availability | Eric | Immutable child bundle without one witness; fresh investigation; supported/unresolved comparison |
| Docker / real artifacts | Daniel | Process-produced logs, independent collector, hashes, parser, benign control, captured replay |
| Records heist | Eric | Records-service access/export trail and approved-export control |
| Cold chain | Eric | Sensor readings, independent reference/counters, legitimate excursion/control, executed effects and scoped scoring |
| B1 / B2 | Eric | Builders without specialized checks or a drafting-time verifier oracle |
| Timestamp edits, cleared history, stopped forwarding | Eric | Bounded simulated steps, benign counterparts, unobservable outcomes |
| Lateral movement | Eric | Simulated second-host session and corroboration; no real-network movement |
| Network/activity view | Terry | Small topology tied to actual evidence/time |
| IoT-CAD | Daniel | Provenance, license, hashes and relevant subset if accessible; supported local-file importer otherwise. External availability is a factual prerequisite. |
| Second machine/projector | Daniel + Terry | Install, offline hero, benign case, citation, review/reveal/reset, legibility |
| User fit, product acceptance, pitch | Rayan | Real target-user feedback, acceptance decisions, measured claims, rehearsal and submitted links |

Simulator extensions follow the finished demo path. They stay assigned, but must not displace deadline integration. A button, stub, fabricated run, or changed label is not completion.

## The stronger demo

Ask **“Can you still prove it if this witness disappears?”** Show the retained collector line, then remove that source from a new evidence view. The conclusion should weaken exactly where support disappeared. That gives log owners a practical reason to use ALIBI.

Use Daniel's real capture to show the same check working on independently produced bytes. Use the model for questions, alternatives, and which evidence to collect next. Do not attribute a deterministic set comparison to model intelligence.

Main track: Science & Discovery. Strong specials: Arlequin forensics, LangChain deepagents, Amazon practical AI, and the connected ChatOverflow leaderboard. Peri needs a real consultation and a resulting user-driven change. Unrelated sponsor integrations would dilute this demo.
