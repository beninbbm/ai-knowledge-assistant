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

## Tests

```bash
cd backend
uv run pytest            # all tests (needs Postgres; integration tests need Ollama)
uv run ruff check .      # lint
```
