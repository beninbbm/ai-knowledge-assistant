# AI Knowledge Assistant

A local RAG (Retrieval-Augmented Generation) assistant: upload PDFs, Word documents and
Markdown, then ask questions and get answers with citations to the source passages.

Stack: FastAPI · Postgres + pgvector · Ollama (local LLM + embeddings) · React.

## One-time setup

```bash
brew install uv ollama
brew services start ollama
ollama pull llama3.1:8b
ollama pull nomic-embed-text
cp .env.example .env            # then set JWT_SECRET
```

## Run

```bash
docker compose up -d --wait     # Postgres + pgvector
cd backend
uv sync                          # install Python dependencies
uv run alembic upgrade head      # create/upgrade database tables
uv run uvicorn app.main:app --reload
```

In a second terminal, start the ingestion worker (it processes uploaded documents):

```bash
cd backend
uv run python -m app.ingestion.worker
```

Check http://localhost:8000/health. Interactive API docs: http://localhost:8000/docs.

## Accounts

Anyone can sign up via `POST /auth/register`, but admins (who manage groups) can only be
created from the command line:

```bash
cd backend
uv run python -m scripts.create_user you@example.com --admin   # prompts for a password
```

In the API docs, click **Authorize** and log in with your email and password to try the
protected endpoints.

## Documents

Upload `.pdf`, `.docx` or `.md` files (max 25 MB) with `POST /documents`. The upload
returns immediately with status `pending`; the worker then extracts the text, splits it
into chunks and marks it `ready` (or `failed` with an error). See a document's chunks
with `GET /documents/{id}/chunks`.

Sample files for a fictional company live in `samples/` (regenerate with
`uv run python -m scripts.make_samples`). To see how any file gets chunked, without the
database:

```bash
cd backend
uv run python -m scripts.inspect_chunks ../samples/travel-expense-policy.pdf --sections
uv run python -m scripts.inspect_chunks ../samples/travel-expense-policy.pdf --target 150 --overlap 30
```

## Tests

```bash
cd backend
uv run pytest            # all tests (needs Postgres; integration tests need Ollama)
uv run ruff check .      # lint
```
