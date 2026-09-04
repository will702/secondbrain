# Second Brain

A private, single-owner workspace that turns notes and documents into connected tasks, deadlines, calendar proposals, and evidence-backed answers.

## Stack

- Next.js 16, React 19, TypeScript, and Tailwind CSS 4
- Python 3.12, FastAPI, SQLAlchemy 2, and Alembic
- PostgreSQL 16 with pgvector
- A local or OpenAI-compatible model endpoint for extraction, embeddings, and reranking
- A PostgreSQL-backed worker queue and local content-addressed file storage

## Start everything

Install Docker, Python 3.12 with `uv`, Node.js, and `pnpm`, then copy `.env.example` to `.env` and run either command from the repository root:

```sh
make dev
# or
pnpm dev
```

The root command starts PostgreSQL, applies migrations, starts the API and workers, then runs the web app at [http://localhost:3000](http://localhost:3000). Running `pnpm dev` inside `apps/web` starts only Next.js.

Individual services remain available through `make db`, `make api`, `make workers`, and `make web`.

## Demo data

```sh
cd apps/api
uv run python scripts/seed.py
```

Sign in with:

```text
Email: demo@secondbrain.dev
Password: demo-password-1
```

## OCR

Digital PDFs are parsed directly. Textless scanned pages use the largest encoded page images and Tesseract OCR. OCR is optional until a scanned PDF is uploaded.

On macOS:

```sh
brew install tesseract
```

English is the default language. Install an additional Homebrew language package only when those documents require it:

```sh
brew install tesseract-lang
```

If Tesseract is missing or times out, the document is marked failed with a clear error; ordinary text PDFs bypass OCR.

## Desktop app (single-entry build for general users)

`make dist` produces `dist/SecondBrain.dmg` — a self-contained macOS
(Apple Silicon) app that needs **no Docker, Node, Python, or setup**:

- PostgreSQL 16 + pgvector compiled for arm64, embedded and managed per-user
- The API, background workers, and the static web UI served from one frozen
  backend process
- A native SwiftUI shell: staged launch experience, in-app window, menu-bar
  status, graceful shutdown of every child process
- All user data in `~/Library/Application Support/SecondBrain/`
  (database, uploads, logs, per-install secrets)

AI runs as a **guided first-run download**: the app ships small (~85 MB) and
"Enable AI" downloads the local-ai engine plus ~10 GB of Qwen models with
resumable progress into the same app-support directory. Without AI, Ask falls
back to structured facts and uploads wait until AI is enabled.

Distribution targets:

```sh
make dist        # full pipeline: stage → app → dmg → smoke
make dist-check  # end-to-end gate on the assembled app (SKIP_AI=1 to skip AI)
make smoke       # frozen-backend smoke test only
```

Requirements to build: Xcode command line tools, `uv` on PATH, and the
local-ai repo (default `~/ai`, override with `LOCAL_AI_REPO`).

The build is currently **unsigned** — users must right-click → Open the first
time (or copy to /Applications). To sign and notarize, set `SIGN_IDENTITY`
(Developer ID Application) and `NOTARY_KEYCHAIN_PROFILE` when running
`make dist-dmg`.

## Verify

```sh
cd apps/api && uv run pytest -q
cd apps/api && uv run ruff check app tests
cd apps/web && pnpm lint
cd apps/web && pnpm build
git diff --check
```

Architecture and product notes live in [`docs/`](docs/). Local `.env` files and stored data are excluded from Git.
