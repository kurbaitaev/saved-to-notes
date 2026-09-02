#!/usr/bin/env bash
# Archive, export and upload a TestFlight build.
#
#   ./release.sh            # archive + export + validate
#   ./release.sh upload     # ...and upload to TestFlight
#
# Needs the App Store Connect key at
#   ~/.appstoreconnect/private_keys/AuthKey_$ASC_KEY_ID.p8
set -euo pipefail
cd "$(dirname "$0")"

TEAM=A58FFUY6DF                                   # Gameplan Labs, Inc.
BUNDLE=com.kurbaitaev.savedtonotes
PROFILE="SavedToNotes App Store"
ASC_KEY_ID=${ASC_KEY_ID:-AQZ687BDBN}
ASC_ISSUER=${ASC_ISSUER:-4cd18058-a288-478e-9bf4-4d8accc67911}

[ -f "$HOME/.appstoreconnect/private_keys/AuthKey_$ASC_KEY_ID.p8" ] || {
  echo "Missing AuthKey_$ASC_KEY_ID.p8 in ~/.appstoreconnect/private_keys/"; exit 1; }

# App Store Connect rejects uploads built with a beta Xcode (error 90534,
# "Unsupported SDK or Xcode version") once a newer beta ships — and the Mac's
# global xcode-select points at the beta for other work. Build with the stable
# Xcode when it exists, without changing the global selection.
if [ -z "${DEVELOPER_DIR:-}" ] && [ -d /Applications/Xcode.app/Contents/Developer ]; then
  export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi
echo "==> xcode: $(xcodebuild -version | tr '\n' ' ')"

./configure.sh >/dev/null            # Notion token + regenerate the project

# Every upload needs a build number App Store Connect has not seen before.
BUILD=$(date +%Y%m%d%H%M)
echo "==> build $BUILD"

rm -rf build/SavedToNotes.xcarchive build/export
xcodebuild -project SavedToNotes.xcodeproj -scheme SavedToNotes \
  -configuration Release -destination 'generic/platform=iOS' \
  -archivePath build/SavedToNotes.xcarchive \
  CURRENT_PROJECT_VERSION="$BUILD" archive >/dev/null
echo "==> archived"

xcodebuild -exportArchive -archivePath build/SavedToNotes.xcarchive \
  -exportOptionsPlist ExportOptions.plist -exportPath build/export >/dev/null
echo "==> exported build/export/SavedToNotes.ipa"

action=${1:-validate}
if [ "$action" = "upload" ]; then
  xcrun altool --upload-app -f build/export/SavedToNotes.ipa -t ios \
    --apiKey "$ASC_KEY_ID" --apiIssuer "$ASC_ISSUER"
  echo "==> uploaded. Processing takes ~5-15 min before it appears in TestFlight."
else
  xcrun altool --validate-app -f build/export/SavedToNotes.ipa -t ios \
    --apiKey "$ASC_KEY_ID" --apiIssuer "$ASC_ISSUER"
  echo "==> validated. Run './release.sh upload' to send it."
fi
