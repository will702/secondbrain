#!/usr/bin/env bash
# Assemble SecondBrain.app from the build artifacts:
#   build/postgres   build/backend   build/ai-payload   apps/web/out
# plus the SwiftPM-built shell binary. Output: dist/SecondBrain.app
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP="$ROOT/dist/SecondBrain.app"
CONTENTS="$APP/Contents"

for part in \
  "$ROOT/build/postgres/bin/postgres" \
  "$ROOT/build/backend/secondbrain-backend" \
  "$ROOT/build/ai-payload/uv/uv" \
  "$ROOT/apps/web/out/index.html"; do
  [[ -e "$part" ]] || { echo "✗ missing $part — run the earlier build steps or 'make dist-stage'" >&2; exit 1; }
done
ls "$ROOT"/build/ai-payload/local-ai/localai-*.whl >/dev/null 2>&1 \
  || { echo "✗ missing localai wheel — run scripts/package/build-local-ai.sh" >&2; exit 1; }

echo "→ building desktop shell (SwiftPM release)"
(cd "$ROOT/apps/desktop" && swift build -c release --quiet)

echo "→ assembling $APP"
rm -rf "$APP"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"
cp "$ROOT/apps/desktop/.build/release/SecondBrain" "$CONTENTS/MacOS/SecondBrain"
cp "$ROOT/scripts/package/Info.plist" "$CONTENTS/Info.plist"

cp -R "$ROOT/build/backend" "$CONTENTS/Resources/backend"
cp -R "$ROOT/build/postgres" "$CONTENTS/Resources/postgres"
cp -R "$ROOT/apps/web/out" "$CONTENTS/Resources/web"
cp -R "$ROOT/build/ai-payload/uv" "$CONTENTS/Resources/uv"
cp -R "$ROOT/build/ai-payload/local-ai" "$CONTENTS/Resources/local-ai"

chmod +x "$CONTENTS/Resources/uv/uv"

# Ad-hoc signature keeps the bundle internally consistent (needed for
# spawned helpers on Apple Silicon). Developer ID + notarization hooks are
# enabled by setting SIGN_IDENTITY when a certificate is available.
if [[ -n "${SIGN_IDENTITY:-}" ]]; then
  codesign --force --deep --sign "$SIGN_IDENTITY" "$APP"
else
  codesign --force --sign - "$APP"
fi

echo "✓ $APP ($(du -sh "$APP" | cut -f1))"
