#!/usr/bin/env bash
# Copies the Notion credentials out of ../.env into the app, so the token is
# never typed into a file git tracks. Re-run after changing .env.
set -euo pipefail
cd "$(dirname "$0")"
[ -f ../.env ] || { echo "No ../.env — nothing to read"; exit 1; }
set -a; . ../.env; set +a
: "${NOTION_TOKEN:?NOTION_TOKEN missing from .env}"
: "${NOTION_DATABASE_ID:?NOTION_DATABASE_ID missing from .env}"
out=SavedToNotes/Sources/Secrets.swift
sed -e "s|__NOTION_TOKEN__|${NOTION_TOKEN}|" \
    -e "s|__NOTION_DATABASE_ID__|${NOTION_DATABASE_ID}|" \
    SavedToNotes/Sources/Secrets.swift.template > "$out"
echo "wrote $out"
command -v xcodegen >/dev/null && xcodegen generate --quiet && echo "regenerated SavedToNotes.xcodeproj"
