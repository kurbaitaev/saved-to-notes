#!/bin/bash
# Install saved-to-notes on a Linux VPS as systemd --user units:
#   the bot (always on), the watchdog (every 90 min), the digest (Sunday 18:00).
# Run as the normal user that owns the checkout, from anywhere:
#   ./deploy/install-linux.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
# Prefer the project venv — a VPS without sudo can't apt-install anything, and
# the system python must not be polluted.
PYTHON="${PYTHON:-$HERE/.venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
UNIT_DIR="$HOME/.config/systemd/user"

if [ ! -f "$HERE/.env" ]; then
  echo "error: no .env yet. Run:  cp .env.example .env  then fill it in." >&2
  exit 1
fi
if ! grep -qE '^(ANTHROPIC_API_KEY|OPENAI_API_KEY)=.+' "$HERE/.env" \
   && ! grep -q '"claudeAiOauth"' "$HOME/.claude/.credentials.json" 2>/dev/null; then
  echo "error: no reasoning backend. Either put ANTHROPIC_API_KEY (or OPENAI_API_KEY)" >&2
  echo "       in .env, or log the Claude CLI in on this machine (claude → /login)." >&2
  exit 1
fi
command -v systemctl >/dev/null || { echo "error: systemd not found." >&2; exit 1; }

mkdir -p "$HERE/logs" "$UNIT_DIR" /tmp/saved-to-notes

render() { sed -e "s|__DIR__|$HERE|g" -e "s|__PYTHON__|$PYTHON|g" "$1"; }

for unit in saved-to-notes.service \
            saved-to-notes-watchdog.service saved-to-notes-watchdog.timer \
            saved-to-notes-digest.service   saved-to-notes-digest.timer \
            saved-to-notes-vaultsync.service saved-to-notes-vaultsync.timer; do
  render "$HERE/deploy/$unit" > "$UNIT_DIR/$unit"
done

systemctl --user daemon-reload
systemctl --user enable --now saved-to-notes.service
systemctl --user enable --now saved-to-notes-watchdog.timer
systemctl --user enable --now saved-to-notes-digest.timer
systemctl --user enable --now saved-to-notes-vaultsync.timer

# Without linger the units stop the moment the SSH session ends.
if ! loginctl show-user "$(id -un)" 2>/dev/null | grep -q "Linger=yes"; then
  loginctl enable-linger "$(id -un)" 2>/dev/null \
    || echo "NOTE: linger is off and needs root once:  sudo loginctl enable-linger $(id -un)"
fi

echo
systemctl --user --no-pager status saved-to-notes.service | head -5
systemctl --user --no-pager list-timers 'saved-to-notes-*' | head -5
echo
echo "  systemctl --user restart saved-to-notes    # after git pull"
echo "  journalctl --user -u saved-to-notes -f     # live logs"
