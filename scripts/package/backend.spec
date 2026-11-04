# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the packaged Second Brain backend (app.standalone).
# Build via scripts/package/build-backend.sh — output lands in build/backend/.

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]
API = ROOT / "apps" / "api"

a = Analysis(
    [str(API / "app" / "standalone.py")],
    pathex=[str(API)],
    binaries=[],
    datas=[
        # Migrations are loaded by path at runtime — ship them as data next to
        # the bundle root (sys._MEIPASS in frozen mode).
        (str(API / "alembic"), "alembic"),
        (str(API / "alembic.ini"), "."),
    ],
    hiddenimports=[
        # psycopg[binary] resolves its impl package dynamically
        "psycopg_binary",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # ONNX embedding fallback — packaged app always uses the local-ai stack
        "fastembed",
        "onnxruntime",
        "tokenizers",
        "pandas",
        "torch",
        # never used at runtime
        "pytest",
        "ruff",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="secondbrain-backend",
    debug=False,
    bootloader_args=None,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="backend",
)
