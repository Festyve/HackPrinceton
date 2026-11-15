#!/usr/bin/env bash
# Auto-deploy: run by alibi-update.timer every few minutes. If the deploy branch or the app branch on GitHub has a
# new commit, pull it and rerun bootstrap.sh (which rebuilds and restarts the app). Otherwise it does nothing.
# Settings come from /etc/alibi-deploy.env, written by bootstrap.sh. Log: /var/log/alibi-update.log
set -euo pipefail
exec 9>/run/alibi-update.lock
flock -n 9 || exit 0

# shellcheck disable=SC1091
source /etc/alibi-deploy.env
SRC="${ALIBI_DEPLOY_SRC:-/root/alibi-deploy-src}"
APP_DIR=/opt/alibi
log() { echo "$(date -u +%FT%TZ) $*"; }

# 1. Deploy scripts themselves (this file, bootstrap.sh, units).
src_branch="$(git -C "$SRC" rev-parse --abbrev-ref HEAD)"
git -C "$SRC" fetch -q --depth=50 origin "$src_branch"
src_changed=0
if [ "$(git -C "$SRC" rev-parse HEAD)" != "$(git -C "$SRC" rev-parse FETCH_HEAD)" ]; then
  git -C "$SRC" reset -q --hard FETCH_HEAD
  src_changed=1
fi

# 2. The app branch.
remote="$(git ls-remote "$ALIBI_REPO" "refs/heads/$ALIBI_REF" | cut -f1)"
[ -n "$remote" ] || remote="$ALIBI_REF"   # a tag or a commit sha: pinned, compare as-is
current="$(sudo -u alibi -H git -C "$APP_DIR" rev-parse HEAD 2>/dev/null || echo none)"

if [ "$src_changed" = 0 ] && [ "${remote:0:7}" = "${current:0:7}" ]; then
  exit 0
fi

log "deploying $ALIBI_REF: ${current:0:7} -> ${remote:0:7} (deploy scripts changed: $src_changed)"
if ALIBI_REPO="$ALIBI_REPO" ALIBI_REF="$ALIBI_REF" ALIBI_DOMAIN="$ALIBI_DOMAIN" \
   bash "$SRC/deploy/vultr/bootstrap.sh" >> /var/log/alibi-bootstrap.log 2>&1; then
  log "ok: now at $(sudo -u alibi -H git -C "$APP_DIR" rev-parse --short HEAD)"
else
  log "FAILED: see /var/log/alibi-bootstrap.log"
  exit 1
fi
