#!/usr/bin/env bash
# Stage the guided-AI payload into build/ai-payload/: the uv binary, the
# localai wheel, and the model-manifest config. The app downloads Python +
# dependencies + models on first run via this payload.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
AI_REPO="${LOCAL_AI_REPO:-$HOME/ai}"
OUT="$ROOT/build/ai-payload"

[[ -d "$AI_REPO" ]] || { echo "✗ local-ai repo not found at $AI_REPO (set LOCAL_AI_REPO)" >&2; exit 1; }

echo "→ building localai wheel in $AI_REPO"
(cd "$AI_REPO" && uv build --quiet)
WHEEL="$(ls -t "$AI_REPO"/dist/localai-*.whl | head -1)"

rm -rf "$OUT"
mkdir -p "$OUT/uv" "$OUT/local-ai"
cp "$(command -v uv)" "$OUT/uv/uv"
# Keep the PEP 427 versioned filename — uv rejects generic names.
cp "$WHEEL" "$OUT/local-ai/"
cp "$AI_REPO/config/config.yaml" "$OUT/local-ai/config.yaml"

echo "✓ staged $OUT (uv $(du -h "$OUT/uv/uv" | cut -f1), wheel $(basename "$WHEEL"))"
