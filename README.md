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

## Verify

```sh
cd apps/api && uv run pytest -q
cd apps/api && uv run ruff check app tests
cd apps/web && pnpm lint
cd apps/web && pnpm build
git diff --check
```

Architecture and product notes live in [`docs/`](docs/). Local `.env` files and stored data are excluded from Git.
