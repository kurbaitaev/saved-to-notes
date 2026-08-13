#!/bin/bash
# Manage the saved-to-notes launchd service.
# Usage: ./ctl.sh {install|start|stop|restart|status|logs|tail}
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
# Prefer SERVICE_LABEL from the environment, then .env, then the username default.
if [ -z "${SERVICE_LABEL:-}" ] && [ -f "$HERE/.env" ]; then
  SERVICE_LABEL="$(grep -E '^SERVICE_LABEL=' "$HERE/.env" | tail -1 | cut -d= -f2- | tr -d "\"'" || true)"
fi
LABEL="${SERVICE_LABEL:-com.$(id -un).saved-to-notes}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
LOGDIR="$HERE/logs"

case "$1" in
  install)  "$HERE/install.sh" ;;
  start)    launchctl bootstrap "$DOMAIN" "$PLIST" && echo "started" ;;
  stop)     launchctl bootout "$DOMAIN/$LABEL" && echo "stopped" ;;
  restart)  launchctl kickstart -k "$DOMAIN/$LABEL" && echo "restarted" ;;
  status)   launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state =|pid =|last exit code =" | sed 's/^[[:space:]]*//' || echo "not loaded" ;;
  logs)     cat "$LOGDIR/bot.err.log" "$LOGDIR/bot.out.log" 2>/dev/null ;;
  tail)     tail -f "$LOGDIR/bot.err.log" ;;
  *)        echo "usage: $0 {install|start|stop|restart|status|logs|tail}" ; exit 1 ;;
esac
