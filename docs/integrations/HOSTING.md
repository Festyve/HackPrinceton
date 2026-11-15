# Live hosting record: whats-the-alibi.us

This file records what is actually running and where it is set up. It covers the domain, DNS, the Vultr server and
billing. The setup procedure is in [`deploy/vultr/README.md`](../../deploy/vultr/README.md). The background on the
domain offer and the side prizes is in [`SIDE_PRIZES.md`](SIDE_PRIZES.md). Update this file whenever any of it changes.

**Status (2026-11-15): live.** https://whats-the-alibi.us serves the offline recorded demo (the ALIBI case board).

| Piece | Where | What is there |
|---|---|---|
| Domain | **Porkbun** (registrar). `.us` itself is run by GoDaddy Registry. | `whats-the-alibi.us`, registered in the team's Porkbun account. Porkbun shows the next renewal as 2027-11-15. |
| DNS | Porkbun → Domain Management → `whats-the-alibi.us` → DNS (Porkbun's DNS, powered by Cloudflare) | Two `A` records, listed below |
| Server | **Vultr** → Compute → Instances → `alibi-demo` | Shared CPU `vc2-1c-2gb` (1 vCPU, 2 GB RAM, 55 GB SSD), Ubuntu 24.04 LTS x64, New York (NJ), public IPv4 only |
| HTTPS | Caddy on the server | Automatic Let's Encrypt certificate. Nothing was bought. |
| Code served | Branch `codex/alibi-build`, cloned to `/opt/alibi` | Deploy scripts come from branch `integrations-side-prizes` (`/root/alibi-deploy-src`) |

## DNS records (Porkbun)

| Type | Host | Answer | TTL |
|---|---|---|---|
| A | *(blank: the bare domain)* | `45.63.21.119` | 600 |
| A | `www` | `45.63.21.119` | 600 |

Two records were **removed** when the domain was pointed at Vultr: Porkbun's default `ALIAS whats-the-alibi.us →
pixie.porkbun.com` and `CNAME *.whats-the-alibi.us → pixie.porkbun.com` (the parking page). The server has no IPv6, so
there are no `AAAA` records.

`www.whats-the-alibi.us` returns a 301 redirect to `https://whats-the-alibi.us/` (configured in the Caddyfile that
`bootstrap.sh` writes).

## Vultr server

- **Label / hostname:** `alibi-demo` / `alibi`. **Public IPv4:** `45.63.21.119`.
- **Deployed:** 2026-11-15, from the Vultr console, with **Cloud-Init User Data** set to the exact contents of
  [`deploy/vultr/cloud-init.yaml`](../../deploy/vultr/cloud-init.yaml). The User Data can be seen at Instance →
  Settings → User-Data.
- **Options:** Automatic Backups **off** (Vultr turns them on by default for +$2/mo), DDoS protection off, no VPC.
  **No SSH key**: use Vultr's **View Console** with the root password shown on the instance's Overview page.
- **Runtime:** `RUNTIME_MODE=offline`, `LLM_MAX_USD=0`. No model calls and no API key on the server.
- **Setup log:** `/var/log/alibi-bootstrap.log` (ends with `done: https://whats-the-alibi.us (commit …)`).
- **Services:** `alibi` (systemd, uvicorn on 127.0.0.1:8000) and `caddy` (ports 80/443). The ufw firewall allows only
  SSH, 80 and 443.

## Billing

- **Cost:** about $10/month, billed hourly (~$0.014/hr), only for as long as the instance exists.
- **Paid from:** the MLH "Major League Hacking" Vultr credit (+$100), added 2026-11-15. The credit **expires 30 days
  after signup**. Vultr also requires a linked payment method for identity verification (linked with a $0 deposit),
  so the card is charged once the credit runs out or expires.
- **Stopping billing:** **destroy** the instance (Vultr → Instances → `alibi-demo` → Destroy). Stopping it still bills.
  Afterwards, change the DNS records above or the domain will point at an IP Vultr may give to someone else.
- **Domain:** renewal is managed in Porkbun. Check whether auto-renew is on before 2027-11-15.

## Verified (2026-11-15, about 5 minutes after the DNS change)

```sh
dig +short whats-the-alibi.us                     # 45.63.21.119
curl -s https://whats-the-alibi.us | grep title   # <title>ALIBI case board</title>
curl -s https://whats-the-alibi.us/api/runtime    # "runtime_mode":"offline","llm_max_usd":0.0
curl -sI https://www.whats-the-alibi.us           # HTTP/2 301 → https://whats-the-alibi.us/
```

## Common operations

- **Update the demo to the latest `codex/alibi-build`:** open the Vultr console and run
  `ALIBI_REF=codex/alibi-build ALIBI_DOMAIN=whats-the-alibi.us bash /root/alibi-deploy-src/deploy/vultr/bootstrap.sh`.
  Add `ALIBI_REF=<sha>` to freeze a commit before judging.
- **Logs:** `journalctl -u alibi -f`, `journalctl -u caddy -f`, `tail -30 /var/log/alibi-bootstrap.log`.
- **New server:** follow `deploy/vultr/README.md`, then replace the two `A` records above with the new IPv4 and update
  this file.

## Account access

The Vultr and Porkbun accounts belong to the team member who set them up. They are not shared through this
repository. No passwords, keys or tokens are stored here or on the server.
