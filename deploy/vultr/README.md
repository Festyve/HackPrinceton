# Hosting the offline ALIBI demo on Vultr

This serves the **existing offline recorded demo** (the same app as `./start.sh`) on a Vultr server behind Caddy,
with automatic HTTPS once a domain points at it. It changes nothing in the app, `start.sh` or local hosting.
The server runs with `RUNTIME_MODE=offline` and `LLM_MAX_USD=0`: no model calls, no API key, no spend.

**Live deployment record** (domain registrar, DNS records, instance, billing): [`docs/integrations/HOSTING.md`](../../docs/integrations/HOSTING.md).

Files: `bootstrap.sh` (idempotent installer/updater), `alibi.service` (systemd unit), `cloud-init.yaml` (paste as
User Data so a new server sets itself up), `alibi-update.sh` + `alibi-update.service` + `alibi-update.timer`
(continuous deployment, below).

**Continuous deployment.** `bootstrap.sh` installs `alibi-update.timer`. Every 5 minutes it checks GitHub. When
`ALIBI_REF` (the app branch) or the deploy branch has a new commit, it pulls the change and reruns `bootstrap.sh`,
which rebuilds the app and restarts it. With no new commit it does nothing. Pushing to `codex/alibi-build` therefore
puts the change live in about 5 to 10 minutes, with no SSH, no secrets and no CI runner. `https://<domain>/deploy.json`
shows the commit that is live. The log of each update is in `/var/log/alibi-update.log`; the full build output is in
`/var/log/alibi-bootstrap.log`. Settings live in `/etc/alibi-deploy.env`.

## Verified in the dev container

- `bash -n bootstrap.sh` passes.
- The unit's exact `ExecStart` (`uv run --frozen --no-dev alibi serve --host 127.0.0.1 --port …`) with the unit's
  environment served the built UI (HTTP 200), reported `runtime_mode: offline`, `llm_max_usd: 0`, `/api/spend` "nothing
  can be spent", and replayed the recorded **Inside job · cover-up** (Opus) run to `awaiting_review` with no network model call.
- Not verified here (needs a real server, root, systemd and DNS): apt/NodeSource/Caddy installation, the systemd unit
  itself, the firewall, and certificate issuance.

## Manual steps (need your Vultr account and payment approval)

1. **Repository access.** `cloud-init.yaml` clones over anonymous HTTPS. If `owly1/HackPrinceton` is private, either make
   it public for the demo, or add a read-only GitHub deploy key on the server and set `ALIBI_REPO=git@github.com:owly1/HackPrinceton.git`.
2. **Create the server** (Vultr console → Deploy): Cloud Compute, **Ubuntu 24.04 x64**, smallest plan with ≥ 2 GB RAM
   (the UI build and DuckDB are comfortable there; 1 GB may run out of memory during `npm ci`), nearest region
   (e.g. New Jersey). Paste `cloud-init.yaml` into **User Data**. Add your SSH key. This is the step that starts billing.
3. **Point DNS at it** (see the domain steps in `docs/integrations/SIDE_PRIZES.md`): an `A` record for `@` and for `www`
   to the server's IPv4 (and `AAAA` to its IPv6 if enabled).
4. Watch the setup: `ssh root@<ip> tail -f /var/log/alibi-bootstrap.log`. When it prints `done:`, open
   `https://whats-the-alibi.us`. Caddy fetches the certificate on the first request after DNS resolves (if DNS was
   not ready during setup, just reload: `systemctl reload caddy`).

Without a domain: rerun `bash /root/alibi-deploy-src/deploy/vultr/bootstrap.sh` with `ALIBI_DOMAIN` unset to serve
`http://<server-ip>`.

## Operating it

- Updates are automatic (see above). To force one now: `systemctl start alibi-update.service`. To freeze the demo
  before judging, set `ALIBI_REF=<sha>` in `/etc/alibi-deploy.env`; to stop updates, `systemctl disable --now alibi-update.timer`.
- Logs: `journalctl -u alibi -f`, `journalctl -u caddy -f`.
- Optional login in front of the demo: `caddy hash-password`, then rerun bootstrap with
  `ALIBI_BASIC_AUTH_USER=judge ALIBI_BASIC_AUTH_HASH='<hash>'`.
- The public API lets visitors create and reset offline cases. That costs CPU and disk only (no money);
  `rm -rf /opt/alibi/runs/* /opt/alibi/sealed/*` and `systemctl restart alibi` clears them.
- **Stop billing** when the event is over: destroy the instance in the Vultr console (stopping it still bills).

## Optional: Gemini questions on the server

Off by default and not part of this unit. To try it, add an `EnvironmentFile=/etc/alibi/gemini.env` (mode 600, owned
by root, holding the variables in `docs/integrations/SIDE_PRIZES.md`) and change `ExecStart` to
`… uv run --frozen --no-dev python -m alibi.integrations.gemini_qa serve --host 127.0.0.1 --port 8000`.
Never put the key in this repository.
