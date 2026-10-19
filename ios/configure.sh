#!/usr/bin/env bash
# Copies the app's server address and token out of ../.env into the app, so the token is
# never typed into a file git tracks. Re-run after changing .env.
set -euo pipefail
cd "$(dirname "$0")"
[ -f ../.env ] || { echo "No ../.env — nothing to read"; exit 1; }
set -a; . ../.env; set +a
: "${APP_TOKEN:?APP_TOKEN missing from .env (copy it from .env on the server)}"
: "${APP_API_BASE:?APP_API_BASE missing from .env}"
out=SavedToNotes/Sources/Secrets.swift
sed -e "s|__APP_TOKEN__|${APP_TOKEN}|" \
    -e "s|__APP_API_BASE__|${APP_API_BASE}|" \
    SavedToNotes/Sources/Secrets.swift.template > "$out"
echo "wrote $out"
command -v xcodegen >/dev/null && xcodegen generate --quiet && echo "regenerated SavedToNotes.xcodeproj"
