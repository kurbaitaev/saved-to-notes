#!/usr/bin/env bash
# For a Mac that only READS the vault while the bot runs elsewhere:
# installs just the 5-minute pull job. Does not touch the bot, watchdog or
# digest jobs — running the bot on two machines makes Telegram refuse both.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LABEL="${SERVICE_LABEL:-com.$(id -un).saved-to-notes}"
AGENTS="$HOME/Library/LaunchAgents"; DOMAIN="gui/$(id -u)"
[ -d "$HERE/vault/.git" ] || { echo "vault/ is not a git clone yet — see docs/vault-sync.md"; exit 1; }
mkdir -p "$HERE/logs" "$AGENTS"
sed -e "s|__LABEL__|$LABEL|g" -e "s|__DIR__|$HERE|g" -e "s|__HOME__|$HOME|g" \
    "$HERE/launchd/vaultpull.plist.template" > "$AGENTS/$LABEL-vaultpull.plist"
launchctl bootout "$DOMAIN/$LABEL-vaultpull" 2>/dev/null || true
for _ in 1 2 3; do launchctl bootstrap "$DOMAIN" "$AGENTS/$LABEL-vaultpull.plist" 2>/dev/null && break; sleep 2; done
echo "installed: $LABEL-vaultpull (pulls every 5 min)"
