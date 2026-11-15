# Optional integrations: domain, Vultr hosting, Gemini questions

Additive and **off by default**. The core app, `./start.sh`, `alibi serve`, recordings, benchmarks and the UI are
unchanged; no existing file was edited. Branch: `claude/compassionate-planck-v5iysn`.

| Piece | Files | State |
|---|---|---|
| Domain `whats-the-alibi.us` | this document | **Available** (registry lookup, 2026-11-15). Not registered: needs your account. |
| Vultr hosting of the offline demo | `deploy/vultr/*` | Config written; the served command was verified locally. No server created. |
| Gemini evidence questions | `src/alibi/integrations/gemini_qa.py`, `tests/test_integration_gemini.py` | Works: 5 offline tests, plus one live question answered and checked. |

## 1. Domain: `whats-the-alibi.us` on GoDaddy

**Availability:** a read-only registry lookup on 2026-11-15 returned `available: true`. Availability can change at
any moment until it is registered.

**MLH free domain (not verified).** `mlh.com` could not be reached from the build sandbox, so these terms come from
search results and need checking at the event. MLH's software page lists "GoDaddy Registry: a free domain of your
choice for 1 year". Some 2026 MLH events run a "Best Domain Name from GoDaddy Registry" prize. In earlier years the
offer was claimed through a registrar partner, sometimes without a credit card. Before you buy:

- Ask HackPrinceton's MLH coach or the MLH Discord for this event's **GoDaddy redemption link or code**.
- Confirm that `.us` is covered. GoDaddy Registry runs `.us`, but free-domain offers often restrict the TLD list.
- Confirm the prize rules: usually register during the event and use the domain in your submission (Devpost link).

**`.us` nexus requirement.** A `.us` registrant must be a US citizen or resident, or a US organization, or have a bona
fide US presence (Nexus category C11/C12/C21/C31/C32). The registrar asks for this at checkout; answer truthfully. If
no one on the team qualifies, choose a different TLD that the offer covers.

**Register it yourself (needs your login and possibly payment; Claude did not purchase anything):**
1. Sign in at godaddy.com (or the MLH redemption link), search `whats-the-alibi.us`, and apply the MLH code.
2. Decline paid add-ons. Note that `.us` does **not** allow WHOIS privacy, so the registrant contact is public: use a
   team or role email and an address you are comfortable publishing. Turn auto-renew **off** if you only want the free year.
3. Complete the nexus declaration and checkout. Verify the registrant email that GoDaddy/the registry sends, or the
   domain can be suspended.

**DNS for Vultr (in GoDaddy → Domain → DNS → Manage):**

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `@` | Vultr server IPv4 | 600 |
| A | `www` | same IPv4 | 600 |
| AAAA (if IPv6 is enabled) | `@` and `www` | Vultr server IPv6 | 600 |

Delete any GoDaddy "Parked" `A` record for `@` and any `www` CNAME to `@`/parking. Then check: `dig +short whats-the-alibi.us`.
Caddy on the server obtains the HTTPS certificate on its own once this resolves. No certificate purchase is needed.

## 2. Vultr: see `deploy/vultr/README.md`

Summary: create an Ubuntu 24.04 instance with `deploy/vultr/cloud-init.yaml` as User Data, point DNS at it, open
`https://whats-the-alibi.us`. It serves the offline recorded demo with zero model calls. Creating the instance is
the only step that bills; destroy it after the event.

## 3. Gemini: evidence questions (optional route)

**What it is.** It is the existing "ask a question about a case" feature, answered by a Gemini model. The module only
supplies a model through the orchestrator's existing model-factory seam. Everything else runs unmodified:
`alibi.questions` (the bounded exchange, the read-only toolbox, `validate_answer`) and the existing budget gateway.

- **Sealed ground truth is never exposed.** A question opens only the evidence store, the public manifest and the
  report, through the same code path as before. The test asserts the bound tools are the stock read-only set.
- **Validation is reused.** Cited ids that are not in the bundle are dropped. Claims are compared with the
  deterministic checks. An "answered" status with nothing tied to evidence becomes `insufficient_evidence`.
- **Every call goes through the budget gateway** as a billed route: counted before it is sent, reserved against the
  per-question caps and the cumulative spend ledger (`LLM_MAX_USD` and the development ceiling). The output limit is
  sent on every call. A small adapter maps the gateway's `max_tokens` to this client's `max_output_tokens`, and maps
  Gemini's `MAX_TOKENS` and safety finish reasons to the gateway's `stop_reason`.
- **Scope.** Only questions use it. The investigator stays offline, and the environment designer and worker lab see
  no model. It refuses to run beside `RUNTIME_MODE=live`, because one settings object carries one price pair.
- **No new dependency.** `langchain-google-genai` 4.5.0 is already in `uv.lock` (via deepagents).

**Enable it (all required; keep these in an untracked `.env` or the server's environment, never in git):**

```sh
ALIBI_QA_PROVIDER=gemini
GEMINI_API_KEY=<key>
GEMINI_MODEL=gemini-3.5-flash-lite        # pick from: uv run python -m alibi.integrations.gemini_qa models
GEMINI_PRICE_IN_PER_MTOK=<USD per 1M input tokens, from ai.google.dev pricing; overstating is safe>
GEMINI_PRICE_OUT_PER_MTOK=<USD per 1M output tokens>
LLM_MAX_USD=<cap>                          # the existing cumulative cap
LLM_DEV_CEILING_USD=<≤ cap>                # otherwise automatic use stops at cap − 0.50
```

```sh
uv run python -m alibi.integrations.gemini_qa status
uv run python -m alibi.integrations.gemini_qa serve --port 8000     # the normal case board; Ask uses Gemini
uv run python -m alibi.integrations.gemini_qa ask <case-id> "Was a host log line removed?"
```

**Evidence (2026-11-15)**

- Offline tests: `uv run pytest tests/test_integration_gemini.py`, 5 passed. They cover:
  - off by default, with every setting required;
  - the stock server never imports the module;
  - a question runs through the real gateway and trusted validation, with an invented id dropped and spend recorded;
  - the designer keeps its offline default;
  - the factory refuses non-question ledgers;
  - the adapter sends the reserved output limit and reports truncation.
- `models` (not billed): the key lists `gemini-3.5-flash-lite`, `gemini-2.5-flash` and others.
- **One live question.** Model `gemini-3.5-flash-lite`, case `hero-coverup`, deterministic investigator, prices set
  deliberately high at $1 / $5 per MTok. Asked "Was a host log line removed, and which record shows it?":
  - result: `answered`, 2 model calls, estimated **$0.0121** at those overstated prices;
  - one claim, kind `line_missing_locally`, citing `ev_0e5ae1caaa5a`, marked **checked** by the deterministic
    local-versus-collector check.
- An earlier attempt with `gemini-2.5-flash-lite` returned 404 ("no longer available to new users").
  - Google does not bill a 404. This client's exception carries no HTTP status, so the gateway kept the worst-case
    reservation, **$0.0193**, as *unreconciled*. That is conservative over-counting.
  - Both figures are in a scratch ledger outside the repo, not the team's spend ledger: $0.0315 estimated in total,
    $0 of it on Anthropic.
- Recorded vs live: the smoke question above was a **live model** call. No Gemini recording was added to the demo.

## What this branch did not touch

`start.sh`, `src/alibi/**` outside `integrations/`, `web/`, `tests/` other than the one new file, `PROGRESS.md`, the
benchmarks, recordings, `pyproject.toml` and `uv.lock`. `PROGRESS.md` was left alone on purpose to avoid a merge
conflict with the active build session; this document is the record for this slice.
