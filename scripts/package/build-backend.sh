#!/usr/bin/env bash
# Freeze the backend with PyInstaller → build/backend/secondbrain-backend
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/apps/api"

uv run pyinstaller "$ROOT/scripts/package/backend.spec" \
  --noconfirm --clean \
  --distpath "$ROOT/build" --workpath "$ROOT/build/pyinstaller-work"

echo "✓ frozen backend at build/backend/secondbrain-backend"
