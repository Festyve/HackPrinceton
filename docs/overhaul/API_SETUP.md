# Runtime and coding setup

**Use Eric's existing configured runtime. The user confirmed its $20 cumulative cap.** No new provider, account, credit purchase or Docker setup is needed. The old second-run setup contains completed tasks and outdated numbers; do not replay it blindly.

On Eric's existing checkout:

~~~sh
git status --short
git check-ignore .env .alibi/spend.json
uv run alibi runtime
uv run alibi spend
~~~

These commands do not request model inference. Verify total cap 20, automatic development cutoff 19.50, and preserved prior spending/reservations. The last recorded estimate was $3.651786, not a fresh zero balance. Check current provider usage too. Do not overwrite .env from .env.example, remove .alibi, or copy a key into a new clone with an empty ledger.

The working runtime model recorded in the build is anthropic:claude-haiku-5-5. Keep it and its verified gateway settings unless a concrete capability issue justifies a documented change. Before changing models, verify availability, parameters and price tiers; preserve past spend and reserve against the new rates. Do not assume “Opus 4.8” or “Fable 5.2” is an available API ID. A coding agent's display name is not the runtime configuration.

If the configured key is actually missing, Eric can manage it at [Claude Console → API keys](https://platform.claude.com/settings/keys), following the [official instructions](https://platform.claude.com/docs/en/get-api-key). Put the value only in the existing gitignored local .env, never a prompt, screenshot or frontend variable. The decision to keep the current key remains respected; continuation does not require a new one.

Run Claude Code through the existing Max login and check /status. Do not source the application's .env into the coding terminal; keep application credentials scoped to the application. Terry and Daniel use offline fixtures/recordings and their own coding subscriptions. They need no runtime key.

## Keep the tool setup small

Use the already working LangChain docs/reference MCPs, Git/gh, Python/uv, Node/npm and browser testing. If an MCP is unavailable, use official docs and installed source; do not stop to reinstall the environment. Use frontend-design or webapp-testing if already available and useful. No new orchestrator, memory daemon, deployment tool or paid tracing service is required.

The coding coordinator may use up to two bounded helpers on disjoint files. Runtime investigator specialists are a separate product feature measured through the app's gateway.

Before leaving an unattended run, test an ordinary edit/build/test operation under current project permissions. Resolve actual prompts then. Do not grant blanket shell/Docker/GitHub permissions or disable safeguards to avoid a hypothetical prompt. Plug in the machine and keep it awake using normal settings. The required simulation does not depend on Docker.

## Validation after implementation

~~~sh
uv sync --frozen
npm --prefix web ci
npm --prefix web run build
uv run pytest
./start.sh
~~~

Current browser tests expect installed Google Chrome and a built UI; report skips/failures honestly. Eric must document new CLI commands with working examples. Existing runtime/spend commands and replay/phase-two workflows remain available.
