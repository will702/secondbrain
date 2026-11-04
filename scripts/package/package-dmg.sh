#!/usr/bin/env bash
# Package dist/SecondBrain.app into dist/SecondBrain.dmg with the standard
# drag-to-Applications layout. Notarization runs only when credentials are
# provided via environment (see README).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP="$ROOT/dist/SecondBrain.app"
DMG="$ROOT/dist/SecondBrain.dmg"
VOL="Second Brain"
STAGING="$ROOT/build/dmg-staging"

[[ -d "$APP" ]] || { echo "✗ $APP not built — run scripts/package/build-app.sh first" >&2; exit 1; }

rm -rf "$STAGING" "$DMG"
mkdir -p "$STAGING"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

hdiutil create -volname "$VOL" -srcfolder "$STAGING" -ov -format UDZO "$DMG" -quiet

if [[ -n "${NOTARY_KEYCHAIN_PROFILE:-}" ]]; then
  echo "→ notarizing"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_KEYCHAIN_PROFILE" --wait
  xcrun stapler staple "$DMG"
else
  echo "  (skipped notarization — set NOTARY_KEYCHAIN_PROFILE to enable)"
fi

echo "✓ $DMG ($(du -sh "$DMG" | cut -f1))"
