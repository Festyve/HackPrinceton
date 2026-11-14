# UI integration brief

For whoever owns `web/`. The backend routes below exist on `codex/alibi-build` and `codex/eric-phase2`, are tested, and return the payloads saved in [`docs/api-examples/`](api-examples/). The full reference is [`docs/api.md`](api.md). Nothing here needs a backend change; ask Eric if a field is missing instead of inventing one in a component.

**A working version of all nine items is on the branch `codex/eric-ui-wiring`** (one new file, `web/src/phase2.tsx`, small mounts in `App.tsx`, `workbench.tsx`, `panels.tsx` and `bench.tsx`, styles appended, nineteen browser tests in `tests/test_browser_phase2.py`; three assertions in `tests/test_browser.py` that pinned the old placeholders are changed there). Take it, change it or replace it; it is not merged into `codex/alibi-build`.

The merged interface currently shows two honest placeholders: `question-composer` ("Open-ended questions are unavailable in this server version") in `web/src/workbench.tsx`, and `source-experiment-unavailable`. Both can now become real.

## What to wire, in order of demo value

| # | Feature | Route | Decide availability from | Example payloads |
|---|---|---|---|---|
| 1 | Remove a witness | `POST /api/cases/{id}/source-experiments`, then `GET /api/cases/{child}/source-experiment` | `runtime.capabilities.source_experiments.endpoint` | `manifest-sources.json`, `source-experiment-created.json`, `source-experiment-derived.json`, `source-experiment-child-reveal.json`, `source-experiment-error-400.json` |
| 2 | Ask a question | `POST /api/cases/{id}/questions?wait_s=25`, poll `GET …/questions/{question_id}` while `status` is `pending` | `runtime.capabilities.questions.model_answers` (`CONFIGURED` or `BLOCKED`) | `question-answered-live.json`, `question-insufficient-evidence-live.json`, `question-unavailable-offline.json`, `questions-list-live.json` |
| 3 | Recorded answers on a replay | `GET /api/cases/{id}/questions` on load | always | the hero Haiku recording has two |
| 4 | Export | `GET /api/cases/{id}/report-export` (a download link) | case state is `report_locked` or `scored` | — |
| 5 | Fast or specialist | `investigation_mode` in `POST /api/cases` | `runtime.capabilities.investigation_modes` | `case-created-fast-mode.json` |
| 6 | Spend in the Details drawer | `GET /api/spend` | `configured` | — |
| 7 | New results | `paired_v2` in `GET /api/benchmark` | not `null` | `benchmarks/paired-v2/*/results.json` |
| 8 | Environment designer | `POST /api/scenario-designs`, then `POST /api/cases` with `design_id` | `runtime.capabilities.scenario_designer` | `scenario-design-live.json`, `scenario-design-default-offline.json`, `case-created-from-design.json` |
| 9 | Cold chain: two temperature records | `GET /api/cases/{id}/evidence/sensor-streams` | `applicable` in the response (`card.id === "cold-chain"`) | `sensor-streams-cold-chain.json` |

Items 1 to 4 are the demo. 5 to 9 are worth doing only after those work. Item 9 is what makes the cold-chain case legible: plot both `series` against time with `permitted_range_c` as a band, shade `maintenance_windows`, and mark `discrepancies` whose `classification` is `unexplained`. Word it as "the two records disagree", never as "the readings were falsified".

## Rules that keep the labels honest

1. **Remove a witness.** Send `source_id` values from `manifest.sources[]` (never an artifact path) and a fresh `client_token` per click. Show the comparison rows as the server returns them: `change` is `retains_support`, `loses_support` or `never_supported`, with `reason`. Word `loses_support` as "cannot be established from this evidence", never as "did not happen" or "disproved". Unsealing a derived case returns 409 until the original case's report is locked; show the server's message. The derived case is an ordinary case: navigate to it by `child_case_id`; `case.parent_case_id` and `case.excluded_sources` identify it. Do not compute a changed conclusion in React.
2. **Questions.** Every claim has a `support` label decided by the server: `checked`, `contradicted`, `cited`, `interpretation`, `unsupported`. Show the label and `basis` beside each claim, and make `evidence_ids` open like any other citation. Show `inference_label` on the answer ("Live model", "Recorded AI answer"). For `status: "unavailable"` show the first entry of `limitations`; never substitute the predefined explanations as if they were the answer. They stay below, under their own "Predefined · no model inference" label. `409` means another question is still being answered for this case.
3. **Offline.** With no model configured, a question returns `unavailable` and the designer returns a default labeled "Default environment · no model was asked". Both are real server responses; render them, do not hide the controls behind a fake success.
4. **Unscored cases.** `case.scored === false` (imported evidence) has no answer key: hide Unseal for it; `POST …/reveal` returns 409.
5. **Featured recording.** Use `replays[].presentation_default === true`, not the first item and not a title match.
6. **New presets and cards.** `card.id` can now be `records-heist`, `cold-chain` or `imported`; take the description from `card.audience_setup`, not from a string in the component. Reports on those cases carry more `claim_type` values; render unknown ones by replacing underscores with spaces.
7. **Designer.** Show `preview` (plain sentences) and `label` before a case is generated. The two fixture choices are the operator's, and a case made from a design must look the same in the library whether or not a fixture was placed in it.

## Browser tests worth adding

- Remove the collector on the recorded hero case: the removed-line claim reads "cannot be established", the transfer claim keeps support, and the original case is unchanged after navigating back.
- Offline question: the composer submits, the answer area shows the unavailable state with its reason, and the predefined explanations are still present and still labeled.
- Open the Haiku hero recording: two answers appear labeled "Recorded AI answer", each claim with its support label.
- Export link present only after the report is locked.

## Paste into the UI agent

```text
Wire the new backend routes into the ALIBI case board. Read docs/ui-integration-brief.md, docs/api.md and the real payloads in docs/api-examples/ first. You own web/ and tests/test_browser.py only; do not change backend code, generated contracts, recordings or benchmark files. Start from the current codex/alibi-build.

Do items 1 to 4 of the brief in order (remove a witness, ask a question, recorded answers on a replay, export), following its seven labeling rules exactly. Use real endpoints only: no mock data in production code, no client-side computation of a changed conclusion, no canned text shown as a model answer. Offline states are real server responses and must be rendered as such.

Add the browser tests listed in the brief, run the build and the full browser suite, and push codex/terry-ui with the commit, build output and test output. Use no paid model calls: every state you need has a saved payload or works offline.
```
