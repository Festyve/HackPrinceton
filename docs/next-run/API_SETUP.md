# API setup for the second run

**Confirmed limit: $20 total across both runs** (Eric raised it from $5 on November 14). Not another $20: the $2.92 spent in the first run counts. Preserve `.alibi/spend.json`; never reset, replace, or bypass it. About $17.08 remains under the cap, $16.58 before the development ceiling. Reconcile before calling a model.

## Eric's setup

1. Open [Claude Console](https://platform.claude.com/), select the existing organization/workspace, and check Billing and current usage. Leave auto-reload off. No new purchase or paid service.
2. The old key was pasted into a coding chat. Create a replacement under Settings → API keys, edit only the key value in the existing gitignored `.env` locally, and revoke the old key. Do this before sharing transcripts or publishing. Keep keys out of prompts, screenshots, shell history and frontend variables. [Official instructions](https://platform.claude.com/docs/en/get-api-key).
3. Preserve other settings and the ledger. Do not copy `.env.example` over a working `.env`. Run `chmod 600 .env` and `git check-ignore .env .alibi/spend.json`; neither file belongs in Git.
4. Run `uv run alibi runtime` and `uv run alibi spend`. These do not call a model. Record redacted totals.
5. Start Claude Code signed into Max and check `/status`. Do **not** source the application's `.env` into that terminal: an exported API credential can select API billing rather than the intended subscription. The application loads its own `.env`.

No new provider is needed. Terry and Daniel work offline without Eric's key. LangSmith, AWS, OpenAI, Gemini and deployment credentials are unnecessary for the required demo; local traces show framework behavior.

Max may offer separate monthly API credits after seven days. Eric can check claude.ai → Settings → Billing → API credits → Link organization. Select the intended organization and verify the balance; eligibility is not assumed. **Claimed credits do not raise this project's $20 authorization.** [Eligibility and claim steps](https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-ultra-and-team-plans).

## Make the remaining allowance useful

Fix the gateway in `CONTINUE.md` §1 before more paid calls. Only Eric's runtime gets the key: separate clones otherwise start separate ledgers and falsely reset the allowance.

Keep the proven Opus recording. Calibrate **`anthropic:claude-haiku-5-5`** on a development incident and a benign control. Current short-context pricing is $0.10 input / $0.50 output per million tokens, versus Opus 5.5 at $4 / $20. Haiku's rate changes above 100,000 input tokens; enforce a per-request ceiling below that threshold. This is a candidate, not a claim it already works in ALIBI. [Model](https://platform.claude.com/docs/en/models/haiku-5-5/overview) · [pricing](https://platform.claude.com/docs/en/about-claude/pricing).

After guard fixes, use this candidate profile while retaining existing per-investigation limits:

```dotenv
RUNTIME_MODE=live
LIVE_PROVIDER_KIND=included_credits
LLM_MAX_USD=20
LLM_SPEND_FLOOR_USD=2.922403
BENCH_MAX_SYSTEM_RUNS=0
LEAD_MODEL=anthropic:claude-haiku-5-5
SUBAGENT_MODEL=anthropic:claude-haiku-5-5
ADVERSARY_MODEL=anthropic:claude-haiku-5-5
LLM_PRICE_IN_PER_MTOK=0.10
LLM_PRICE_OUT_PER_MTOK=0.50
LLM_EFFORT=low
LLM_MAX_TOKENS_PER_CALL=3000
LLM_MAX_CALLS_PER_RUN=24
LLM_MAX_INPUT_TOKENS_PER_RUN=300000
LLM_MAX_OUTPUT_TOKENS_PER_RUN=20000
LLM_MAX_SECONDS_PER_RUN=240
LANGSMITH_TRACING=false
```

The four per-investigation caps were raised for this profile after calibration (November 14): the specialist graph on Haiku 5.5 hit the earlier 10,000-token output cap before requesting review. At these prices the worst case for one investigation is under $0.05. Results: `benchmarks/calibration/`.

Check availability and provider arguments once; avoid repeated probes. Keep every role on the same model/rates. Preserve historical spend on changes.

Promote Haiku only after correct workflow completion, citations, review pause, and benign abstention. If capability checks fail, retain the proven Opus route for a final necessary check and the existing replay for presentation. A refusal ends that request; do not reroute it to another model.

| Purpose | Maximum additional estimate |
|---|---:|
| Calibration and feature checks | $0.25 |
| New paired evaluation | $0.75 |
| Final recording / necessary repair run | $0.30 |
| Reserve for a judge's live request | $0.50 |
| Reconciliation/headroom | Remainder |

These are ceilings. The stricter of verified remaining balance, total cap, and category allowance wins. Automatic development calls stop by **$19.50 cumulative**; the final $0.50 stays for an operator-triggered live demo (`ALIBI_USE_DEMO_RESERVE=1`). The category ceilings above were sized for the inexpensive profile and did not grow with the cap; a different model means declaring a new matrix against the development ceiling first. If less remains, shrink and declare the evaluation matrix before running it.

Declare the model and new matrix first. `BENCH_MAX_SYSTEM_RUNS=16` applies only to the new four-case × four-AI-arm suite after preflight proves it fits. Do not rerun the old `pilot` command, which currently writes v1 paths.

The ledger estimates usage, not a provider billing guarantee. Count tools and system messages, reserve conservatively, preserve uncertain outcomes, and use Console as billing authority. The official [token-counting endpoint](https://platform.claude.com/docs/en/build-with-claude/token-counting) supports preflight estimates.
