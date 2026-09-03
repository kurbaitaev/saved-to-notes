#!/usr/bin/env bash
# Push the vault to its private repo — or pull it, on the reading machine.
#
#   ./vault_sync.sh push   # after a save: rebase on remote, commit, push
#   ./vault_sync.sh pull   # on the Mac: bring new notes down, push local edits
#
# The vault is its own git repo *inside* the code checkout (vault/ is
# gitignored there), so notes never touch the public code repo. Every note
# version is kept: a reprocess or a bad edit is one `git log` away from undo.
#
# Never fails the caller. A push that can't happen (offline, conflict) is
# logged and retried by the timer; the note on disk is already safe.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VAULT="${VAULT_DIR:-$HERE/vault}"
LOG="$HERE/logs/vault_sync.log"
mkdir -p "$HERE/logs"
log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }

[ -d "$VAULT/.git" ] || { log "vault is not a git repo yet — run the setup in docs/vault-sync.md"; exit 0; }
cd "$VAULT" || exit 0
# One sync at a time; a second caller just leaves (the timer will catch up).
# mkdir is atomic on both Linux and macOS — flock(1) does not exist on macOS,
# and the first Mac pull died on it while logging "another sync is running".
LOCK="$VAULT/.git/sync.lock.d"
if ! mkdir "$LOCK" 2>/dev/null; then
  # A lock older than 10 minutes belongs to a crashed run, not a live one.
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then rmdir "$LOCK" 2>/dev/null && mkdir "$LOCK" 2>/dev/null || exit 0
  else log "another sync is running"; exit 0; fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

git add -A >/dev/null 2>&1
if ! git diff --cached --quiet; then
  git commit -q -m "$(hostname -s): $(git diff --cached --name-only | wc -l | tr -d ' ') file(s) $(date '+%F %H:%M')" \
    && log "committed local changes"
fi
# rebase keeps history linear; --autostash protects an in-progress local edit
if ! git pull -q --rebase --autostash origin main 2>>"$LOG"; then
  log "pull --rebase failed (conflict?) — aborting rebase, will retry"
  git rebase --abort >/dev/null 2>&1
  exit 0
fi
log "pulled (HEAD $(git rev-parse --short HEAD))"
if [ "${1:-push}" = push ] || [ -n "$(git log origin/main..HEAD --oneline 2>/dev/null)" ]; then
  git push -q origin main 2>>"$LOG" && log "pushed" || log "push failed — will retry"
fi
