#!/usr/bin/env bash
# Compile PostgreSQL + pgvector for macOS arm64 into build/postgres —
# self-contained and relocatable (no Homebrew/Docker at runtime).
# Cached: re-runs are no-ops unless the versions change.
set -euo pipefail

PG_VERSION="${PG_VERSION:-16.9}"
PGVECTOR_VERSION="${PGVECTOR_VERSION:-0.8.1}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$ROOT/build/pgbuild"
OUT="$ROOT/build/postgres"
MARKER="$OUT/.built"
TAG="postgres-$PG_VERSION+pgvector-$PGVECTOR_VERSION"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "error: embedded postgres is built for macOS arm64 only" >&2
  exit 1
fi

if [[ -f "$MARKER" && "$(cat "$MARKER")" == "$TAG" ]]; then
  echo "✓ build/postgres already built ($TAG)"
  exit 0
fi

echo "→ building $TAG"
rm -rf "$OUT"
mkdir -p "$WORK" "$OUT"
cd "$WORK"

if [[ ! -d "postgresql-$PG_VERSION" ]]; then
  curl -fL --retry 3 -o "postgresql-$PG_VERSION.tar.bz2" \
    "https://ftp.postgresql.org/pub/source/v${PG_VERSION}/postgresql-${PG_VERSION}.tar.bz2"
  tar xf "postgresql-$PG_VERSION.tar.bz2"
fi

cd "postgresql-$PG_VERSION"
# --without-icu / --without-readline: avoid the only common Homebrew deps,
# so the staged tree links against the system SDK alone.
./configure --prefix="$OUT" --without-readline --without-icu
make -j"$(sysctl -n hw.ncpu)"
make install

cd "$WORK"
if [[ ! -d "pgvector-$PGVECTOR_VERSION" ]]; then
  curl -fL --retry 3 -o "pgvector-$PGVECTOR_VERSION.tar.gz" \
    "https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz"
  tar xf "pgvector-$PGVECTOR_VERSION.tar.gz"
fi
cd "pgvector-$PGVECTOR_VERSION"
make PG_CONFIG="$OUT/bin/pg_config"
make PG_CONFIG="$OUT/bin/pg_config" install

# --- Relocatability: rewrite absolute install names to @loader_path ---
for dylib in "$OUT"/lib/*.dylib; do
  base="$(basename "$dylib")"
  install_name_tool -id "@loader_path/$base" "$dylib"
done
fix_refs() { # $1 = file, $2 = loader-path prefix for $OUT/lib refs
  local file="$1" prefix="$2" ref base
  for ref in $(otool -L "$file" 2>/dev/null | awk -v out="$OUT" '$0 ~ out {print $1}'); do
    base="$(basename "$ref")"
    install_name_tool -change "$ref" "$prefix/$base" "$file"
  done
}
for bin in "$OUT"/bin/*; do
  fix_refs "$bin" "@loader_path/../lib"
done
for so in "$OUT"/lib/postgresql/*.so; do
  fix_refs "$so" "@loader_path/.."
done

# --- Trim to runtime essentials ---
rm -rf "$OUT/include" "$OUT/share/man"
find "$OUT" -name '*.a' -delete
find "$OUT/bin" -type f -exec strip -x {} +

echo "$TAG" > "$MARKER"
echo "✓ built $OUT ($TAG)"
